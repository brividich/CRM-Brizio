"""Lezione online di una sessione: slide + test finale (vedi ``models_sessione_online``).

Regole che valgono per tutte le view:

- le slide si vedono in sequenza: si passa alla successiva solo dopo il tempo
  minimo, misurato dal server (``slide_aperta_il``), non dal browser;
- il test si apre dopo l'ultima slide e solo se restano tentativi;
- la correzione avviene sul server: il template non riceve mai quale risposta è
  giusta; una domanda è giusta se le risposte scelte sono tutte e sole quelle giuste;
- chi supera il test ha presenza 100% e verifica «Test scritto» registrate
  sull'iscrizione alla sessione; il completamento a libretto lo registra chi
  gestisce la sessione (in blocco), con le regole del corso di sempre.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from ..models_formazione import TrainingEnrollment, TrainingSession
from ..models_sessione_online import (
    TrainingSessionAttempt, TrainingSessionOnline, TrainingSessionOption, TrainingSessionProgress,
    TrainingSessionQuestion, TrainingSessionSlide,
)

logger = logging.getLogger(__name__)

STATI_ESCLUSI = ("RITIRATO",)
MAX_SECONDI_PER_SLIDE = 600  # oltre, la pagina è rimasta aperta: non è studio
MAX_RISPOSTE = 8

# Stato della persona nella lezione, nell'ordine in cui si mostra.
NON_INIZIATA, IN_CORSO, TEST_DA_FARE, SUPERATA, NON_SUPERATA, REGISTRATA = (
    "non_iniziata", "in_corso", "test_da_fare", "superata", "non_superata", "registrata")
ETICHETTE_STATO = {
    NON_INIZIATA: "Non iniziata",
    IN_CORSO: "Slide in corso",
    TEST_DA_FARE: "Test da fare",
    SUPERATA: "Superata",
    NON_SUPERATA: "Non superata",
    REGISTRATA: "Completata a libretto",
}
TONO_STATO = {
    NON_INIZIATA: "neutral", IN_CORSO: "info", TEST_DA_FARE: "warning",
    SUPERATA: "success", NON_SUPERATA: "danger", REGISTRATA: "success",
}


class LezioneOnlineError(Exception):
    """Errore con un messaggio da mostrare all'utente."""


# ─────────────────────────────────────────────────────────────────────────────
# Impostazioni
# ─────────────────────────────────────────────────────────────────────────────

def config(sessione: TrainingSession, *, crea: bool = False) -> TrainingSessionOnline | None:
    cfg = TrainingSessionOnline.objects.filter(sessione=sessione).first()
    if cfg is None and crea:
        soglia = getattr(sessione.corso, "quiz_punteggio_minimo", None) or 70
        cfg, _ = TrainingSessionOnline.objects.get_or_create(sessione=sessione, defaults={
            "soglia_pct": soglia,
            "disponibile_dal": sessione.data_inizio,
            "scadenza": sessione.data_fine,
        })
    return cfg


def slides(sessione) -> list[TrainingSessionSlide]:
    return list(TrainingSessionSlide.objects.filter(sessione=sessione).order_by("ordine", "pk"))


def domande(sessione) -> list[TrainingSessionQuestion]:
    return list(TrainingSessionQuestion.objects.filter(sessione=sessione)
                .prefetch_related("opzioni").order_by("ordine", "pk"))


def problema_domanda(d: TrainingSessionQuestion) -> str:
    opzioni = list(d.opzioni.all())
    if len(opzioni) < 2:
        return "Servono almeno due risposte."
    if not any(o.corretta for o in opzioni):
        return "Nessuna risposta segnata come giusta."
    if all(o.corretta for o in opzioni):
        return "Tutte le risposte sono segnate giuste."
    return ""


def domande_valide(sessione) -> list[TrainingSessionQuestion]:
    return [d for d in domande(sessione) if not problema_domanda(d)]


def iscrizioni(sessione):
    return (TrainingEnrollment.objects.filter(sessione=sessione)
            .exclude(stato__in=STATI_ESCLUSI).order_by("pk"))


def cosa_manca(sessione, cfg=None) -> list[str]:
    """Cosa impedisce di pubblicare (lista vuota = si può)."""
    manca = []
    if not TrainingSessionSlide.objects.filter(sessione=sessione).exists():
        manca.append("nessuna slide caricata")
    tutte = domande(sessione)
    if not tutte:
        manca.append("nessuna domanda nel test")
    elif any(problema_domanda(d) for d in tutte):
        manca.append("ci sono domande da sistemare (risposta giusta mancante o meno di due risposte)")
    if not iscrizioni(sessione).exists():
        manca.append("nessun iscritto alla sessione")
    cfg = cfg or config(sessione)
    if cfg and cfg.scadenza and cfg.disponibile_dal and cfg.scadenza < cfg.disponibile_dal:
        manca.append("la scadenza è prima della data di apertura")
    return manca


# ─────────────────────────────────────────────────────────────────────────────
# Slide
# ─────────────────────────────────────────────────────────────────────────────

def _prossimo_ordine(qs) -> int:
    return (qs.aggregate(m=Max("ordine"))["m"] or 0) + 1


def importa_file(sessione, uploaded_file, user=None) -> int:
    """PowerPoint/PDF → una slide-immagine per pagina, accodate a quelle esistenti."""
    from . import elearning_import as imp

    name = (getattr(uploaded_file, "name", "") or "").strip()
    ext = Path(name).suffix.lower()
    if ext not in imp.ALLOWED_EXTS:
        raise LezioneOnlineError(f"Formato non supportato ({ext or 'sconosciuto'}): carica PPTX, PPT, ODP o PDF.")
    try:
        with tempfile.TemporaryDirectory(prefix="sessione_online_") as tmp:
            src = os.path.join(tmp, "src" + ext)
            with open(src, "wb") as fh:
                for chunk in uploaded_file.chunks():
                    fh.write(chunk)
            pdf = src if ext in imp.PDF_EXTS else imp._convert_pptx_to_pdf(src, tmp)
            pagine = imp._pdf_to_png_list(pdf)
    except imp.ImportError_ as exc:
        raise LezioneOnlineError(str(exc)) from exc

    stem = (Path(name).stem or "Slide")[:120]
    qs = TrainingSessionSlide.objects.filter(sessione=sessione)
    primo = _prossimo_ordine(qs)
    with transaction.atomic():
        for i, png in enumerate(pagine):
            s = TrainingSessionSlide(sessione=sessione, ordine=primo + i, titolo=f"{stem} — {i + 1}",
                                     origine=Path(name).name[:255],
                                     created_by=user if getattr(user, "is_authenticated", False) else None)
            s.immagine.save(f"slide_{primo + i}.png", ContentFile(png), save=False)
            s.save()
    return len(pagine)


def copia_slide_dal_corso(sessione, user=None) -> tuple[int, int]:
    """Copia le slide attive del corso (file compresi). Ritorna (copiate, saltate)."""
    from ..models_formazione import TrainingSlide

    sorgenti = list(TrainingSlide.objects.filter(corso=sessione.corso, is_active=True).order_by("ordine", "pk"))
    qs = TrainingSessionSlide.objects.filter(sessione=sessione)
    ordine = _prossimo_ordine(qs)
    copiate = saltate = 0
    origine = f"Corso {sessione.corso.codice}"[:255]
    with transaction.atomic():
        for src in sorgenti:
            if src.tipo == "VIDEO" or (not src.immagine and not (src.contenuto or "").strip()):
                saltate += 1
                continue
            s = TrainingSessionSlide(sessione=sessione, ordine=ordine, titolo=src.titolo[:300],
                                     testo="" if src.immagine else src.contenuto, origine=origine,
                                     created_by=user if getattr(user, "is_authenticated", False) else None)
            if src.immagine:
                try:
                    with src.immagine.open("rb") as fh:
                        s.immagine.save(f"slide_{ordine}.png", ContentFile(fh.read()), save=False)
                except (FileNotFoundError, OSError):
                    saltate += 1
                    continue
            s.save()
            ordine += 1
            copiate += 1
    return copiate, saltate


def sposta_slide(slide: TrainingSessionSlide, direzione: str) -> None:
    elenco = slides(slide.sessione_id)
    idx = next((i for i, s in enumerate(elenco) if s.pk == slide.pk), None)
    if idx is None:
        return
    j = idx - 1 if direzione == "su" else idx + 1
    if 0 <= j < len(elenco):
        elenco[idx], elenco[j] = elenco[j], elenco[idx]
    rinumera(elenco)


def rinumera(elenco) -> None:
    for n, obj in enumerate(elenco, start=1):
        if obj.ordine != n:
            type(obj).objects.filter(pk=obj.pk).update(ordine=n)


# ─────────────────────────────────────────────────────────────────────────────
# Domande
# ─────────────────────────────────────────────────────────────────────────────

def salva_domanda(sessione, *, domanda_id=None, testo: str, risposte: list[str], giuste: set[int]):
    """Crea o aggiorna una domanda. ``giuste`` = indici (0-based) delle risposte giuste."""
    testo = (testo or "").strip()
    coppie = [(r.strip()[:500], i in giuste) for i, r in enumerate(risposte[:MAX_RISPOSTE]) if (r or "").strip()]
    if not testo:
        raise LezioneOnlineError("Scrivi il testo della domanda.")
    if len(coppie) < 2:
        raise LezioneOnlineError("Servono almeno due risposte.")
    if not any(g for _, g in coppie):
        raise LezioneOnlineError("Segna la risposta giusta.")
    with transaction.atomic():
        if domanda_id:
            d = TrainingSessionQuestion.objects.select_for_update().get(pk=domanda_id, sessione=sessione)
            d.testo = testo
            d.save(update_fields=["testo"])
            d.opzioni.all().delete()
        else:
            d = TrainingSessionQuestion.objects.create(
                sessione=sessione, testo=testo,
                ordine=_prossimo_ordine(TrainingSessionQuestion.objects.filter(sessione=sessione)))
        TrainingSessionOption.objects.bulk_create([
            TrainingSessionOption(domanda=d, ordine=n, testo=t, corretta=g)
            for n, (t, g) in enumerate(coppie, start=1)
        ])
    return d


def copia_domande_dal_corso(sessione) -> int:
    from ..models_formazione import TrainingQuizQuestion

    sorgenti = (TrainingQuizQuestion.objects.filter(corso=sessione.corso, is_active=True)
                .prefetch_related("opzioni").order_by("ordine", "pk"))
    n = 0
    with transaction.atomic():
        for q in sorgenti:
            opzioni = list(q.opzioni.all())
            if len(opzioni) < 2 or not any(o.corretta for o in opzioni):
                continue
            salva_domanda(sessione, testo=q.testo, risposte=[o.testo for o in opzioni],
                          giuste={i for i, o in enumerate(opzioni) if o.corretta})
            n += 1
    return n


def importa_domande_excel(sessione, file_obj) -> int:
    from . import elearning_quiz_import as qi

    try:
        righe = qi.leggi(file_obj)
    except qi.ImportQuizError as exc:
        raise LezioneOnlineError("; ".join(exc.errori[:5])) from exc
    with transaction.atomic():
        for r in righe:
            if r.tipo == "VERO_FALSO":
                risposte, giuste = ["Vero", "Falso"], {0} if 1 in r.corrette else {1}
            else:
                risposte, giuste = r.risposte, {i - 1 for i in r.corrette}
            salva_domanda(sessione, testo=r.testo, risposte=risposte, giuste=giuste)
    return len(righe)


_RE_GIUSTA = re.compile(r"^\s*(\*|\+|\[x\]|\(x\))\s*", re.IGNORECASE)
_RE_SBAGLIATA = re.compile(r"^\s*(-|–|\[ \]|\( \)|[a-hA-H][\).]|\d+[\).])\s*")


@dataclass
class DomandaLetta:
    testo: str
    risposte: list[str] = field(default_factory=list)
    giuste: set[int] = field(default_factory=set)


def leggi_testo_incollato(testo: str) -> list[DomandaLetta]:
    """Domande incollate da Word: blocchi separati da una riga vuota.

    Prima riga = domanda; righe successive = risposte. La giusta inizia con ``*``
    (o ``+``, ``[x]``); le altre con ``-``, ``a)``, ``1.`` o niente.
    """
    blocchi = re.split(r"\n\s*\n", (testo or "").replace("\r\n", "\n").strip())
    out, errori = [], []
    for n, blocco in enumerate(blocchi, start=1):
        righe = [r for r in blocco.split("\n") if r.strip()]
        if not righe:
            continue
        d = DomandaLetta(testo=re.sub(r"^\s*\d+[\).]\s*", "", righe[0]).strip())
        for riga in righe[1:]:
            m = _RE_GIUSTA.match(riga)
            if m:
                d.giuste.add(len(d.risposte))
                d.risposte.append(riga[m.end():].strip())
            else:
                d.risposte.append(_RE_SBAGLIATA.sub("", riga, count=1).strip())
        if len(d.risposte) < 2:
            errori.append(f"domanda {n}: servono almeno due risposte")
        elif not d.giuste:
            errori.append(f"domanda {n}: segna la giusta con * all'inizio della riga")
        out.append(d)
    if errori:
        raise LezioneOnlineError("; ".join(errori[:6]))
    if not out:
        raise LezioneOnlineError("Nessuna domanda trovata nel testo incollato.")
    return out


def incolla_domande(sessione, testo: str) -> int:
    lette = leggi_testo_incollato(testo)
    with transaction.atomic():
        for d in lette:
            salva_domanda(sessione, testo=d.testo, risposte=d.risposte, giuste=d.giuste)
    return len(lette)


# ─────────────────────────────────────────────────────────────────────────────
# Avanzamento della persona
# ─────────────────────────────────────────────────────────────────────────────

def avanzamento(enrollment: TrainingEnrollment, *, lock: bool = False) -> TrainingSessionProgress:
    prog, _ = TrainingSessionProgress.objects.get_or_create(enrollment=enrollment)
    if lock:
        prog = TrainingSessionProgress.objects.select_for_update().get(pk=prog.pk)
    return prog


def tentativi_massimi(cfg, prog) -> int | None:
    if not cfg.max_tentativi:
        return None
    return cfg.max_tentativi + (prog.tentativi_extra or 0)


def tentativi_rimasti(cfg, prog) -> int | None:
    massimo = tentativi_massimi(cfg, prog)
    return None if massimo is None else max(0, massimo - prog.n_tentativi)


def motivo_accesso_negato(sessione, cfg, enrollment, *, anteprima: bool) -> str:
    if anteprima:
        return ""
    if cfg is None or not cfg.pubblicata:
        return "La lezione online non è ancora stata pubblicata."
    if enrollment is None:
        return "Non risulti iscritto a questa sessione."
    if enrollment.stato in STATI_ESCLUSI:
        return "La tua iscrizione a questa sessione è stata ritirata."
    oggi = timezone.localdate()
    if cfg.disponibile_dal and oggi < cfg.disponibile_dal:
        return f"La lezione sarà disponibile dal {cfg.disponibile_dal:%d-%m-%Y}."
    return ""


def scaduta(cfg) -> bool:
    return bool(cfg and cfg.scadenza and timezone.localdate() > cfg.scadenza)


def apri_slide(prog, ordine: int, n_slide: int) -> bool:
    """Registra l'apertura della slide <ordine>, se consentita (in sequenza)."""
    if ordine < 1 or ordine > n_slide or ordine > prog.slide_viste + 1:
        return False
    adesso = timezone.now()
    campi = ["ultimo_accesso_il"]
    prog.ultimo_accesso_il = adesso
    if not prog.iniziata_il:
        prog.iniziata_il = adesso
        campi.append("iniziata_il")
    if prog.slide_corrente != ordine or prog.slide_aperta_il is None:
        prog.slide_corrente, prog.slide_aperta_il = ordine, adesso
        campi += ["slide_corrente", "slide_aperta_il"]
    prog.save(update_fields=campi)
    return True


def secondi_da_attendere(prog, ordine: int, cfg) -> int:
    """Secondi che mancano al tempo minimo sulla slide (0 = si può andare avanti)."""
    if ordine <= prog.slide_viste or not cfg.secondi_minimi_slide:
        return 0
    if prog.slide_corrente != ordine or prog.slide_aperta_il is None:
        return cfg.secondi_minimi_slide
    trascorsi = (timezone.now() - prog.slide_aperta_il).total_seconds()
    return max(0, int(cfg.secondi_minimi_slide - trascorsi + 0.999))


def completa_slide(prog, ordine: int, cfg) -> int:
    """Segna la slide come vista. Ritorna i secondi ancora da attendere (0 = fatto)."""
    attesa = secondi_da_attendere(prog, ordine, cfg)
    if attesa:
        return attesa
    if ordine == prog.slide_viste + 1:
        trascorsi = 0
        if prog.slide_corrente == ordine and prog.slide_aperta_il:
            trascorsi = int((timezone.now() - prog.slide_aperta_il).total_seconds())
        prog.slide_viste = ordine
        prog.secondi = (prog.secondi or 0) + max(0, min(trascorsi, MAX_SECONDI_PER_SLIDE))
        prog.save(update_fields=["slide_viste", "secondi"])
    return 0


def motivo_test_chiuso(cfg, prog, n_slide: int) -> str:
    if prog.superata_il:
        return "Hai già superato il test."
    if prog.slide_viste < n_slide:
        return "Il test si apre dopo l'ultima slide."
    if tentativi_rimasti(cfg, prog) == 0:
        return "Hai esaurito i tentativi: chiedi al responsabile della formazione di concedertene un altro."
    return ""


def correggi(enrollment, cfg, scelte: dict[int, set[int]], *, user=None, iniziato_il=None) -> TrainingSessionAttempt:
    """Corregge il test sulle domande valide di oggi. ``scelte`` = {id domanda: {id risposte}}."""
    elenco = domande_valide(enrollment.sessione)
    if not elenco:
        raise LezioneOnlineError("Il test non ha domande.")
    with transaction.atomic():
        prog = avanzamento(enrollment, lock=True)
        n_slide = TrainingSessionSlide.objects.filter(sessione=enrollment.sessione_id).count()
        if motivo := motivo_test_chiuso(cfg, prog, n_slide):
            raise LezioneOnlineError(motivo)
        dettaglio, giuste_n = [], 0
        for d in elenco:
            opzioni = list(d.opzioni.all())
            ids_validi = {o.pk for o in opzioni}
            scelte_d = set(scelte.get(d.pk, set())) & ids_validi
            giuste_ids = {o.pk for o in opzioni if o.corretta}
            ok = scelte_d == giuste_ids
            giuste_n += ok
            dettaglio.append({
                "domanda_id": d.pk,
                "domanda": d.testo,
                "scelte": [o.testo for o in opzioni if o.pk in scelte_d],
                "giuste": [o.testo for o in opzioni if o.corretta],
                "ok": ok,
            })
        pct = (Decimal(giuste_n * 100) / Decimal(len(elenco))).quantize(Decimal("0.01"), ROUND_HALF_UP)
        superato = pct >= Decimal(cfg.soglia_pct)
        prog.n_tentativi += 1
        tentativo = TrainingSessionAttempt.objects.create(
            enrollment=enrollment, numero=prog.n_tentativi, iniziato_il=iniziato_il,
            punteggio_pct=pct, n_corrette=giuste_n, n_totali=len(elenco), soglia_pct=cfg.soglia_pct,
            superato=superato, risposte_json=dettaglio,
            utente=user if getattr(user, "is_authenticated", False) else None,
        )
        if prog.miglior_pct is None or pct > prog.miglior_pct:
            prog.miglior_pct = pct
        campi = ["n_tentativi", "miglior_pct"]
        if superato:
            prog.superata_il = tentativo.inviato_il
            campi.append("superata_il")
        prog.save(update_fields=campi)
        _riporta_su_iscrizione(enrollment, cfg, prog, tentativo)
    return tentativo


def _riporta_su_iscrizione(enrollment, cfg, prog, tentativo) -> None:
    """Presenza e verifica sull'iscrizione alla sessione (non il completamento a libretto)."""
    if enrollment.stato == "COMPLETATO":
        return
    campi = ["punteggio", "punteggio_minimo", "modalita_verifica", "data_verifica"]
    enrollment.punteggio = prog.miglior_pct
    enrollment.punteggio_minimo = cfg.soglia_pct
    enrollment.modalita_verifica = "TEST"
    enrollment.data_verifica = timezone.localdate()
    if tentativo.superato:
        enrollment.verifica_superata = True
        enrollment.idoneo = True
        enrollment.percentuale_presenza = Decimal("100")
        ore = enrollment.sessione.corso.durata_ore_teorica or 0
        if ore and (enrollment.ore_frequentate or 0) < ore:
            enrollment.ore_frequentate = ore
            campi.append("ore_frequentate")
        campi += ["verifica_superata", "idoneo", "percentuale_presenza"]
    elif tentativi_rimasti(cfg, prog) == 0:
        enrollment.verifica_superata = False
        campi.append("verifica_superata")
    if enrollment.stato == "ISCRITTO":
        enrollment.stato = "IN_CORSO"
        campi.append("stato")
    enrollment.save(update_fields=campi + ["updated_at"])


# ─────────────────────────────────────────────────────────────────────────────
# Pagina di gestione: righe, numeri, domande più sbagliate
# ─────────────────────────────────────────────────────────────────────────────

def stato_persona(enrollment, prog, cfg, n_slide: int) -> str:
    if enrollment.stato == "COMPLETATO":
        return REGISTRATA
    if prog is None or (not prog.iniziata_il and not prog.n_tentativi):
        return NON_INIZIATA
    if prog.superata_il:
        return SUPERATA
    if prog.n_tentativi and tentativi_rimasti(cfg, prog) == 0:
        return NON_SUPERATA
    if n_slide and prog.slide_viste >= n_slide:
        return TEST_DA_FARE
    return IN_CORSO


def righe_gestione(sessione, cfg, n_slide: int) -> list[dict]:
    from core.legacy_anagrafica import fetch_anagrafica_rows

    iscr = list(iscrizioni(sessione).select_related("avanzamento_online"))
    ids = [e.legacy_anagrafica_id for e in iscr]
    anag = {}
    if ids:
        try:
            anag = {int(r["id"]): r for r in fetch_anagrafica_rows(ids=ids) if r.get("id")}
        except Exception:
            logger.exception("Anagrafica non leggibile per la lezione online %s", sessione.pk)
    ultimi = {}
    for t in TrainingSessionAttempt.objects.filter(enrollment__in=iscr).order_by("enrollment_id", "-inviato_il"):
        ultimi.setdefault(t.enrollment_id, t)
    oggi = timezone.localdate()
    righe = []
    for e in iscr:
        prog = getattr(e, "avanzamento_online", None)
        r = anag.get(e.legacy_anagrafica_id, {})
        stato = stato_persona(e, prog, cfg, n_slide)
        rimasti = tentativi_rimasti(cfg, prog) if prog else (cfg.max_tentativi or None)
        inattivo_gg = None
        if prog and prog.ultimo_accesso_il:
            inattivo_gg = (oggi - timezone.localtime(prog.ultimo_accesso_il).date()).days
        righe.append({
            "enrollment": e,
            "prog": prog,
            "nome": f"{(r.get('cognome') or '').upper()} {r.get('nome') or ''}".strip() or f"#{e.legacy_anagrafica_id}",
            "reparto": r.get("reparto") or r.get("mansione") or "",
            "ha_email": bool((r.get("email_notifica") or r.get("email") or "").strip()),
            "ha_utente": bool(r.get("utente_id")),
            "stato": stato,
            "stato_label": ETICHETTE_STATO[stato],
            "tono": TONO_STATO[stato],
            "slide_viste": prog.slide_viste if prog else 0,
            "slide_pct": int(round(100 * (prog.slide_viste if prog else 0) / n_slide)) if n_slide else 0,
            "minuti": round((prog.secondi or 0) / 60) if prog else 0,
            "n_tentativi": prog.n_tentativi if prog else 0,
            "rimasti": rimasti,
            "miglior_pct": prog.miglior_pct if prog else None,
            "ultimo": ultimi.get(e.pk),
            "ultimo_accesso": prog.ultimo_accesso_il if prog else None,
            "inattivo_gg": inattivo_gg,
            "link_inviato": prog.link_inviato_il if prog else None,
            "solleciti": prog.solleciti if prog else 0,
            "da_registrare": stato == SUPERATA,
            "da_sollecitare": stato in (NON_INIZIATA, IN_CORSO, TEST_DA_FARE),
        })
    ordine = [NON_SUPERATA, TEST_DA_FARE, IN_CORSO, NON_INIZIATA, SUPERATA, REGISTRATA]
    righe.sort(key=lambda x: (ordine.index(x["stato"]), x["nome"]))
    return righe


def numeri(righe: list[dict], cfg) -> dict:
    tot = len(righe)
    conta = {k: 0 for k in ETICHETTE_STATO}
    for r in righe:
        conta[r["stato"]] += 1
    finiti = conta[SUPERATA] + conta[REGISTRATA]
    tentati = [r for r in righe if r["n_tentativi"]]
    superati_al_primo = sum(1 for r in tentati if r["ultimo"] and r["ultimo"].superato and r["n_tentativi"] == 1)
    punteggi = [float(r["miglior_pct"]) for r in tentati if r["miglior_pct"] is not None]
    minuti = [r["minuti"] for r in righe if r["minuti"]]
    giorni = None
    if cfg and cfg.scadenza:
        giorni = (cfg.scadenza - timezone.localdate()).days
    return {
        "totale": tot,
        "conta": conta,
        "finiti": finiti,
        "finiti_pct": round(100 * finiti / tot) if tot else 0,
        "iniziati": tot - conta[NON_INIZIATA],
        "media_punteggio": round(sum(punteggi) / len(punteggi)) if punteggi else None,
        "primo_tentativo_pct": round(100 * superati_al_primo / len(tentati)) if tentati else None,
        "media_minuti": round(sum(minuti) / len(minuti)) if minuti else None,
        "giorni_alla_scadenza": giorni,
        "da_registrare": conta[SUPERATA],
        "da_sollecitare": conta[NON_INIZIATA] + conta[IN_CORSO] + conta[TEST_DA_FARE],
        "senza_contatto": sum(1 for r in righe if not r["ha_email"] and not r["ha_utente"]),
    }


def domande_difficili(sessione, limite: int = 5) -> list[dict]:
    """Le domande sbagliate più spesso nei tentativi consegnati (sui testi del momento)."""
    stat: dict[str, dict] = {}
    for risposte in (TrainingSessionAttempt.objects.filter(enrollment__sessione=sessione)
                     .values_list("risposte_json", flat=True)):
        for v in risposte or []:
            s = stat.setdefault(v.get("domanda", ""), {"domanda": v.get("domanda", ""), "totale": 0, "errate": 0})
            s["totale"] += 1
            s["errate"] += 0 if v.get("ok") else 1
    elenco = [dict(s, pct=round(100 * s["errate"] / s["totale"])) for s in stat.values() if s["totale"] and s["errate"]]
    elenco.sort(key=lambda s: (-s["pct"], -s["errate"]))
    return elenco[:limite]


# ─────────────────────────────────────────────────────────────────────────────
# Pubblicazione, link, solleciti, tentativi, completamenti
# ─────────────────────────────────────────────────────────────────────────────

def _url_lezione(sessione) -> str:
    from django.urls import reverse
    return reverse("anagrafica:sessione_online_player", args=[sessione.pk])


def invia_link(sessione, cfg, enrollments, *, sollecito: bool = False) -> dict:
    """Notifica nel portale + mail a ogni iscritto. Ritorna i conteggi."""
    from core.accounts.portal_links import portal_link
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from core.notifiche import invia_notifica
    from core.notifiche_prefs import should_notify

    enrollments = list(enrollments)
    ids = [e.legacy_anagrafica_id for e in enrollments]
    anag = {}
    if ids:
        try:
            anag = {int(r["id"]): r for r in fetch_anagrafica_rows(ids=ids) if r.get("id")}
        except Exception:
            logger.exception("Anagrafica non leggibile per l'invio dei link (sessione %s)", sessione.pk)
    url_rel = _url_lezione(sessione)
    url_abs = portal_link(url_rel) or url_rel
    corso = sessione.corso.titolo
    entro = f" entro il {cfg.scadenza:%d-%m-%Y}" if cfg.scadenza else ""
    tipo = "formazione_promemoria"
    testo_notifica = (f"Promemoria: completa la lezione online «{corso}»{entro}." if sollecito
                      else f"Nuova lezione online: «{corso}». Guarda le slide e fai il test{entro}.")
    oggetto = (f"Promemoria lezione online: {corso}" if sollecito else f"Lezione online da seguire: {corso}")
    n_mail = n_notifiche = 0
    adesso = timezone.now()
    for e in enrollments:
        r = anag.get(e.legacy_anagrafica_id, {})
        utente_id = r.get("utente_id")
        if utente_id:
            invia_notifica(utente_id, tipo, testo_notifica, url_rel)
            n_notifiche += 1
        email = (r.get("email_notifica") or r.get("email") or "").strip()
        if email and (not utente_id or should_notify(tipo=tipo, legacy_user_id=utente_id)):
            if _manda_mail(email, oggetto, sessione, cfg, url_abs, sollecito=sollecito):
                n_mail += 1
        prog = avanzamento(e)
        if sollecito:
            prog.solleciti += 1
            prog.ultimo_sollecito_il = adesso
            prog.save(update_fields=["solleciti", "ultimo_sollecito_il"])
        else:
            prog.link_inviato_il = adesso
            prog.save(update_fields=["link_inviato_il"])
    return {"mail": n_mail, "notifiche": n_notifiche, "persone": len(enrollments)}


def _manda_mail(email, oggetto, sessione, cfg, url, *, sollecito: bool) -> bool:
    try:
        from core.email_utils import email_cta, email_facts_table, send_hub_mail, text_to_html
        n_slide = TrainingSessionSlide.objects.filter(sessione=sessione).count()
        n_dom = len(domande_valide(sessione))
        facts = [("Corso", sessione.corso.titolo), ("Sessione", sessione.codice_sessione),
                 ("Contenuto", f"{n_slide} slide e un test di {n_dom} domande (soglia {cfg.soglia_pct}%)")]
        if cfg.scadenza:
            facts.append(("Da completare entro", f"{cfg.scadenza:%d-%m-%Y}"))
        intro = ("Non hai ancora completato la lezione online:" if sollecito
                 else "Ti è stata assegnata una lezione online da seguire quando puoi:")
        fragment = (text_to_html(intro)
                    + '<div style="height:12px;line-height:12px;font-size:0;">&nbsp;</div>'
                    + email_facts_table(facts)
                    + '<div style="height:16px;line-height:16px;font-size:0;">&nbsp;</div>'
                    + email_cta("Apri la lezione", url,
                                note="Puoi interrompere e riprendere dalla stessa slide."))
        corpo = f"{intro}\n\n" + "\n".join(f"{k}: {v}" for k, v in facts) + f"\n\nApri la lezione: {url}"
        send_hub_mail(oggetto, corpo, [email], email_type="Anagrafica HR", section_label="Lezione online",
                      body_html_fragment=fragment, fail_silently=True)
        return True
    except Exception:
        logger.exception("Mail della lezione online non inviata (sessione %s)", sessione.pk)
        return False


def pubblica(sessione, cfg, user, *, invia: bool = True) -> dict:
    if manca := cosa_manca(sessione, cfg):
        raise LezioneOnlineError("Prima di pubblicare: " + "; ".join(manca) + ".")
    nome = (getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "") or "")[:160]
    cfg.pubblicata_il = timezone.now()
    cfg.pubblicata_da_nome = nome
    cfg.save(update_fields=["pubblicata_il", "pubblicata_da_nome", "updated_at"])
    for e in iscrizioni(sessione):
        avanzamento(e)
    if not invia:
        return {"mail": 0, "notifiche": 0, "persone": 0}
    # Il link va a chi non l'ha ancora ricevuto (ripubblicare non manda doppioni).
    nuovi = [e for e in iscrizioni(sessione).select_related("avanzamento_online")
             if not getattr(getattr(e, "avanzamento_online", None), "link_inviato_il", None)
             and e.stato != "COMPLETATO"]
    return invia_link(sessione, cfg, nuovi)


def sospendi(cfg) -> None:
    cfg.pubblicata_il = None
    cfg.save(update_fields=["pubblicata_il", "updated_at"])


def da_sollecitare(sessione, cfg) -> list:
    n_slide = TrainingSessionSlide.objects.filter(sessione=sessione).count()
    out = []
    for e in iscrizioni(sessione).select_related("avanzamento_online"):
        stato = stato_persona(e, getattr(e, "avanzamento_online", None), cfg, n_slide)
        if stato in (NON_INIZIATA, IN_CORSO, TEST_DA_FARE):
            out.append(e)
    return out


def concedi_tentativo(enrollment) -> None:
    with transaction.atomic():
        prog = avanzamento(enrollment, lock=True)
        prog.tentativi_extra += 1
        prog.save(update_fields=["tentativi_extra"])
        if enrollment.verifica_superata is False:
            enrollment.verifica_superata = None
            enrollment.save(update_fields=["verifica_superata", "updated_at"])


def azzera_avanzamento(enrollment) -> None:
    """Fa ripartire la persona da capo (slide e tentativi); i tentativi restano a registro."""
    if enrollment.stato == "COMPLETATO":
        raise LezioneOnlineError("Completamento già a libretto: non si azzera.")
    with transaction.atomic():
        prog = avanzamento(enrollment, lock=True)
        prog.slide_viste = prog.slide_corrente = 0
        prog.slide_aperta_il = prog.superata_il = None
        prog.tentativi_extra = prog.n_tentativi
        prog.save()


def registra_completamenti(sessione, user, *, enrollment_ids=None) -> tuple[int, list[str]]:
    """Porta a «Completato» (record a libretto) chi ha superato il test.

    Applica la regola di superamento del corso come la pagina degli iscritti:
    chi è bloccato resta com'è e torna nell'elenco dei motivi.
    """
    from ..views.formazione import _crea_employee_record, _motivi_blocco_completamento

    qs = iscrizioni(sessione).filter(verifica_superata=True).exclude(stato="COMPLETATO") \
        .select_related("avanzamento_online", "sessione", "sessione__corso")
    if enrollment_ids is not None:
        qs = qs.filter(pk__in=list(enrollment_ids))
    fatti, bloccati = 0, []
    for e in qs:
        prog = getattr(e, "avanzamento_online", None)
        if not prog or not prog.superata_il:
            continue
        if motivi := _motivi_blocco_completamento(e):
            bloccati.append(f"#{e.legacy_anagrafica_id}: " + "; ".join(motivi))
            continue
        with transaction.atomic():
            e.stato = "COMPLETATO"
            e.data_completamento = timezone.localtime(prog.superata_il).date()
            e.save(update_fields=["stato", "data_completamento", "updated_at"])
            _crea_employee_record(e, user)
        fatti += 1
    return fatti, bloccati


def promemoria_in_scadenza(oggi=None) -> int:
    """Promemoria automatico: N giorni prima della scadenza, una volta, a chi non ha finito."""
    oggi = oggi or timezone.localdate()
    n = 0
    for cfg in (TrainingSessionOnline.objects.filter(pubblicata_il__isnull=False, scadenza__gte=oggi,
                                                     promemoria_giorni__gt=0)
                .select_related("sessione", "sessione__corso")):
        if cfg.scadenza - timedelta(days=cfg.promemoria_giorni) != oggi or cfg.ultimo_promemoria_il == oggi:
            continue
        persone = da_sollecitare(cfg.sessione, cfg)
        if persone:
            invia_link(cfg.sessione, cfg, persone, sollecito=True)
            n += len(persone)
        cfg.ultimo_promemoria_il = oggi
        cfg.save(update_fields=["ultimo_promemoria_il"])
    return n


def lezioni_della_persona(legacy_id: int) -> list[dict]:
    """Lezioni online pubblicate a cui la persona è iscritta (per catalogo e «Le mie attività»)."""
    if not legacy_id:
        return []
    out = []
    qs = (TrainingEnrollment.objects.filter(legacy_anagrafica_id=legacy_id,
                                            sessione__lezione_online__pubblicata_il__isnull=False)
          .exclude(stato__in=STATI_ESCLUSI)
          .select_related("sessione", "sessione__corso", "sessione__lezione_online", "avanzamento_online")
          .order_by("sessione__lezione_online__scadenza"))
    for e in qs:
        cfg = e.sessione.lezione_online
        n_slide = TrainingSessionSlide.objects.filter(sessione=e.sessione_id).count()
        stato = stato_persona(e, getattr(e, "avanzamento_online", None), cfg, n_slide)
        out.append({"enrollment": e, "sessione": e.sessione, "cfg": cfg, "stato": stato,
                    "stato_label": ETICHETTE_STATO[stato], "tono": TONO_STATO[stato],
                    "finita": stato in (SUPERATA, REGISTRATA), "url": _url_lezione(e.sessione),
                    "n_slide": n_slide})
    return out
