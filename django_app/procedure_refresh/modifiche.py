"""CN-SGI: modifiche ai documenti, dalla richiesta all'emissione.

Ciclo (EN 9100 §7.5.2-7.5.3): **in redazione** (chi redige carica la bozza Word) →
**in verifica** (chi verifica confronta con la revisione in vigore) → **in approvazione**
(chi approva firma) → **approvata, da emettere** (la qualità copia il PDF nella cartella
SGI) → **emessa** (la sincronizzazione riconosce la nuova revisione). Si può annullare
fino all'emissione; chi verifica o approva può rimandare a chi redige.

- ogni azione scrive un :class:`SgiPassaggio` (registro solo in aggiunta, con l'impronta
  della bozza su cui si è agito);
- ogni passaggio avvisa nel portale chi deve agire dopo;
- :func:`riconosci_emissioni` gira dopo ogni sincronizzazione; :func:`solleciti` ogni mattina.

La cartella SGI non viene mai scritta: le bozze stanno nello storage privato cifrato del portale.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    ChangeRequestStatus,
    ProcedureDocument,
    SgiBozza,
    SgiFirmeTipo,
    SgiModifica,
    SgiModificaStato as S,
    SgiPassaggio,
)

logger = logging.getLogger(__name__)

URL_MODIFICHE = "/procedure-refresh/modifiche/"
ESTENSIONI = (".docx", ".xlsx", ".pdf")
MAX_BYTE = 25 * 1024 * 1024
GIORNI_SOLLECITO = 5

PASSI = (
    (S.IN_REDAZIONE, "Redazione", "redattore"),
    (S.IN_VERIFICA, "Verifica", "verificatore"),
    (S.IN_APPROVAZIONE, "Approvazione", "approvatore"),
    (S.APPROVATA, "Emissione", "gestore"),
    (S.EMESSA, "Emessa", ""),
)
AZIONI = {
    "aperta": "Modifica aperta",
    "bozza": "Bozza caricata",
    "in_verifica": "Inviata in verifica",
    "verificata": "Verificata",
    "approvata": "Approvata",
    "rimandata": "Rimandata a chi redige",
    "emessa": "Emessa",
    "annullata": "Annullata",
    "commento": "Commento",
    "persone": "Persone cambiate",
}
RUOLI = {"redattore": "Redige", "verificatore": "Verifica", "approvatore": "Approva", "gestore": "Gestione CN-SGI", "sistema": "Sincronizzazione"}


def nome(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.get_username() or "").strip()


def _legacy(user_ids) -> dict:
    from procedure_refresh.tasks import _legacy_id_map

    ids = [u for u in user_ids if u]
    return _legacy_id_map(ids) if ids else {}


def avvisa(user_ids, messaggio: str, url: str) -> int:
    """Notifica nel portale. Fail-safe: un errore non blocca mai il passaggio."""
    try:
        from core.notifiche import invia_notifica

        mappa = _legacy(set(user_ids))
        n = 0
        for uid in set(u for u in user_ids if u):
            invia_notifica(mappa.get(uid), "presa_visione", messaggio[:480], url_azione=url)
            n += 1
        return n
    except Exception:
        logger.exception("CN-SGI modifiche: avviso non inviato")
        return 0


def url_di(m) -> str:
    return f"{URL_MODIFICHE}{m.pk}/"


# ---------------------------------------------------------------------------
# Chi può fare cosa
# ---------------------------------------------------------------------------


def ruoli_di(m, user, gestore: bool) -> set[str]:
    r = set()
    if gestore:
        r.add("gestore")
    uid = getattr(user, "pk", None)
    for campo in ("redattore", "verificatore", "approvatore"):
        if uid and getattr(m, f"{campo}_id") == uid:
            r.add(campo)
    return r


def puo_vedere(m, user, gestore: bool) -> bool:
    return gestore or bool(ruoli_di(m, user, False)) or (m.creata_da_id and m.creata_da_id == getattr(user, "pk", None))


def chi_deve_agire(m) -> tuple[str, object]:
    """(ruolo, utente) di chi ha in mano la modifica adesso."""
    return {
        S.IN_REDAZIONE: ("redattore", m.redattore),
        S.IN_VERIFICA: ("verificatore", m.verificatore),
        S.IN_APPROVAZIONE: ("approvatore", m.approvatore),
        S.APPROVATA: ("gestore", None),
    }.get(m.stato, ("", None))


def azioni_possibili(m, ruoli: set[str]) -> set[str]:
    a = set()
    g = "gestore" in ruoli
    if m.stato == S.IN_REDAZIONE and (g or "redattore" in ruoli):
        a |= {"bozza", "in_verifica"}
    if m.stato == S.IN_VERIFICA and (g or "verificatore" in ruoli):
        a |= {"verificata", "rimandata"}
    if m.stato == S.IN_APPROVAZIONE and ("approvatore" in ruoli or (g and m.approvatore_id is None)):
        a |= {"approvata", "rimandata"}
    if m.stato == S.APPROVATA and g:
        a |= {"emessa"}
    if m.aperta and g:
        a |= {"annullata", "persone"}
    if m.aperta and ruoli:
        a.add("commento")
    return a


# ---------------------------------------------------------------------------
# Registro e cambi di stato
# ---------------------------------------------------------------------------


def registra(m, azione: str, user=None, *, ruolo: str = "", nota: str = "", bozza=None, stato_da: str = "") -> SgiPassaggio:
    return SgiPassaggio.objects.create(
        modifica=m, azione=azione, utente=user if getattr(user, "pk", None) else None,
        utente_nome=nome(user) if user is not None else "", ruolo=ruolo,
        stato_da=stato_da, stato_a=m.stato, nota=(nota or "")[:4000],
        bozza=bozza, impronta=bozza.impronta if bozza else "",
    )


def _cambia(m, stato: str, azione: str, user, ruolo: str, nota: str = "", bozza=None):
    prima = m.stato
    m.stato = stato
    m.stato_dal = timezone.now()
    m.sollecitata_il = None
    m.save(update_fields=["stato", "stato_dal", "sollecitata_il", "aggiornata_il"])
    return registra(m, azione, user, ruolo=ruolo, nota=nota, bozza=bozza, stato_da=prima)


def ultima_bozza(m):
    return m.bozze.order_by("-numero").first()


def _ruolo_principale(ruoli: set[str], preferito: str) -> str:
    if preferito in ruoli:
        return preferito
    return "gestore" if "gestore" in ruoli else (sorted(ruoli)[0] if ruoli else "")


class Rifiuto(Exception):
    """Azione non permessa o dati mancanti: il messaggio va mostrato all'utente."""


def esegui(m, azione: str, user, ruoli: set[str], *, nota: str = "", revisione=None, gestori=None) -> str:
    """Esegue un'azione del ciclo. Ritorna il messaggio di conferma; :class:`Rifiuto` se non si può."""
    if azione not in azioni_possibili(m, ruoli):
        raise Rifiuto("Questa azione non è disponibile per te in questo momento.")
    nota = (nota or "").strip()
    codice = m.codice
    if azione == "in_verifica":
        b = ultima_bozza(m)
        if b is None:
            raise Rifiuto("Carica prima la bozza.")
        if not m.verificatore_id:
            raise Rifiuto("Manca chi verifica: chiedi a chi gestisce CN-SGI di indicarlo.")
        _cambia(m, S.IN_VERIFICA, azione, user, _ruolo_principale(ruoli, "redattore"), nota, b)
        avvisa([m.verificatore_id], f"Da verificare: {codice} · {m.oggetto} (bozza {b.numero}).", url_di(m))
        return f"{codice} inviato in verifica a {nome(m.verificatore)}."
    if azione == "verificata":
        b = ultima_bozza(m)
        _cambia(m, S.IN_APPROVAZIONE, azione, user, _ruolo_principale(ruoli, "verificatore"), nota, b)
        avvisa([m.approvatore_id], f"Da approvare: {codice} · {m.oggetto} (bozza {b.numero if b else '—'}).", url_di(m))
        avvisa([m.redattore_id], f"{codice}: la bozza è stata verificata e passa in approvazione.", url_di(m))
        return f"Verifica registrata: {codice} passa in approvazione."
    if azione == "approvata":
        b = ultima_bozza(m)
        _cambia(m, S.APPROVATA, azione, user, _ruolo_principale(ruoli, "approvatore"), nota, b)
        avvisa(
            (set(gestori or []) | {m.redattore_id, m.creata_da_id}) - {getattr(user, "pk", None)},
            f"{codice} approvato: va emesso il PDF nella cartella SGI (bozza {b.numero if b else '—'}).", url_di(m),
        )
        return f"{codice} approvato. Resta da copiare il PDF nella cartella SGI: l'HUB lo riconosce da solo."
    if azione == "rimandata":
        if not nota:
            raise Rifiuto("Scrivi a chi redige cosa va corretto.")
        ruolo = _ruolo_principale(ruoli, "verificatore" if m.stato == S.IN_VERIFICA else "approvatore")
        _cambia(m, S.IN_REDAZIONE, azione, user, ruolo, nota, ultima_bozza(m))
        avvisa([m.redattore_id], f"{codice} torna in redazione: «{nota[:140]}»", url_di(m))
        return f"{codice} rimandato a {nome(m.redattore) or 'chi redige'}."
    if azione == "annullata":
        if not nota:
            raise Rifiuto("Scrivi perché la modifica viene annullata.")
        _cambia(m, S.ANNULLATA, azione, user, "gestore", nota)
        avvisa({m.redattore_id, m.verificatore_id, m.approvatore_id} - {getattr(user, "pk", None)},
               f"Modifica annullata: {codice} · {m.oggetto}.", url_di(m))
        return f"Modifica di {codice} annullata."
    if azione == "emessa":
        if revisione is None:
            raise Rifiuto("Scegli la revisione emessa.")
        emetti(m, revisione, user=user, nota=nota)
        return f"{codice} emesso nella Rev.{revisione.revision_code}."
    if azione == "commento":
        if not nota:
            raise Rifiuto("Il commento è vuoto.")
        registra(m, "commento", user, ruolo=_ruolo_principale(ruoli, chi_deve_agire(m)[0]), nota=nota, bozza=ultima_bozza(m))
        ruolo, chi = chi_deve_agire(m)
        destinatari = {m.redattore_id, m.verificatore_id, m.approvatore_id} - {getattr(user, "pk", None)}
        avvisa(destinatari, f"Commento su {codice} da {nome(user)}: «{nota[:140]}»", url_di(m))
        return "Commento aggiunto."
    raise Rifiuto("Azione sconosciuta.")


# ---------------------------------------------------------------------------
# Bozze
# ---------------------------------------------------------------------------


def _numera_titoli(doc) -> list[str]:
    """Paragrafi di un .docx come righe di testo; i titoli Word ricevono il numero (4.2) se non lo scrivono."""
    righe, contatori = [], [0] * 6
    numerato = re.compile(r"^\s*§?\d+(\.\d+)*[.)]?\s")
    for p in doc.paragraphs:
        testo = (p.text or "").strip()
        if not testo:
            continue
        stile = (getattr(p.style, "name", "") or "").lower()
        m = re.match(r"^(heading|titolo)\s*(\d)", stile)
        if m and not numerato.match(testo):
            livello = min(int(m.group(2)), 6)
            contatori[livello - 1] += 1
            for i in range(livello, 6):
                contatori[i] = 0
            testo = ".".join(str(c) for c in contatori[:livello] if c) + " " + testo
        righe.append(testo)
    for tab in doc.tables:
        for riga in tab.rows:
            celle = [(c.text or "").strip() for c in riga.cells]
            if any(celle):
                righe.append(" | ".join(celle))
    return righe


def testo_di(nome_file: str, dati: bytes) -> str:
    """Testo della bozza per il confronto con la revisione in vigore. Mai eccezioni."""
    est = ("." + nome_file.rsplit(".", 1)[-1].lower()) if "." in nome_file else ""
    try:
        if est == ".docx":
            import docx

            return "\n".join(_numera_titoli(docx.Document(io.BytesIO(dati))))[:500_000]
        if est == ".xlsx":
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(dati), read_only=True, data_only=True)
            righe = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    celle = [str(c).strip() for c in row if c not in (None, "")]
                    if celle:
                        righe.append(" | ".join(celle))
            return "\n".join(righe)[:500_000]
        if est == ".pdf":
            import tempfile
            from pathlib import Path

            from .sgi_testo import estrai

            with tempfile.TemporaryDirectory() as cartella:
                p = Path(cartella) / "bozza.pdf"
                p.write_bytes(dati)
                return (estrai(p).testo or "")[:500_000]
    except Exception as exc:
        logger.info("CN-SGI modifiche: testo della bozza non estratto (%s)", type(exc).__name__)
    return ""


def carica_bozza(m, file, user, ruoli: set[str], sintesi: str = "") -> SgiBozza:
    if "bozza" not in azioni_possibili(m, ruoli):
        raise Rifiuto("Le bozze si caricano mentre la modifica è in redazione.")
    nome_file = (getattr(file, "name", "") or "bozza").replace("\\", "/").rsplit("/", 1)[-1][:200]
    if not nome_file.lower().endswith(ESTENSIONI):
        raise Rifiuto("Carica un file Word (.docx), Excel (.xlsx) o PDF.")
    if (getattr(file, "size", 0) or 0) > MAX_BYTE:
        raise Rifiuto("Il file supera i 25 MB.")
    dati = file.read()
    if not dati:
        raise Rifiuto("Il file è vuoto.")
    from django.core.files.base import ContentFile

    with transaction.atomic():
        numero = (m.bozze.order_by("-numero").values_list("numero", flat=True).first() or 0) + 1
        b = SgiBozza(
            modifica=m, numero=numero, nome_file=nome_file, dimensione=len(dati),
            impronta=hashlib.sha256(dati).hexdigest(), sintesi=(sintesi or "").strip()[:4000],
            testo=testo_di(nome_file, dati), caricata_da=user,
        )
        b.file.save(f"mod{m.pk}_b{numero}_{re.sub(r'[^A-Za-z0-9._-]+', '_', nome_file)}"[:180], ContentFile(dati), save=False)
        b.save()
        registra(m, "bozza", user, ruolo=_ruolo_principale(ruoli, "redattore"), nota=b.sintesi, bozza=b, stato_da=m.stato)
        SgiModifica.objects.filter(pk=m.pk).update(aggiornata_il=timezone.now())
    return b


def confronto(m, bozza=None):
    """Paragrafi cambiati fra la revisione in vigore e la bozza (None se manca un testo)."""
    from .esperienza import differenze

    bozza = bozza or ultima_bozza(m)
    if bozza is None or not bozza.testo or not m.documento_id:
        return None
    rev = m.documento.current_revision()
    testo = getattr(getattr(rev, "testo_estratto", None), "testo", "") if rev else ""
    if not testo:
        return None
    try:
        return differenze(testo, bozza.testo)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Apertura, emissione, solleciti
# ---------------------------------------------------------------------------


def firme_per(doc) -> dict:
    """Persone proposte per redazione, verifica e approvazione dal tipo del documento."""
    from .esperienza import tipo_documento

    tipo = tipo_documento(doc) if doc is not None else "altro"
    righe = {r.tipo: r for r in SgiFirmeTipo.objects.filter(tipo__in=[tipo, "altro"])}
    out = {}
    for campo in ("redattore", "verificatore", "approvatore"):
        for t in (tipo, "altro"):
            valore = getattr(righe.get(t), f"{campo}_id", None)
            if valore:
                out[campo] = valore
                break
    return out


def prossima_revisione(rev) -> str:
    codice = (getattr(rev, "revision_code", "") or "").strip()
    if codice.isdigit():
        return str(int(codice) + 1).zfill(len(codice))
    return ""


def apri(*, documento, dati: dict, user, segnalazioni=()) -> SgiModifica:
    """Crea la modifica (stato «in redazione»), collega le segnalazioni e avvisa chi redige."""
    rev = documento.current_revision() if documento is not None else None
    with transaction.atomic():
        m = SgiModifica.objects.create(
            documento=documento, revisione_base=rev,
            revisione_prevista=dati.get("revisione_prevista") or prossima_revisione(rev),
            creata_da=user, stato=S.IN_REDAZIONE,
            **{k: v for k, v in dati.items() if k != "revisione_prevista"},
        )
        segn = list(segnalazioni)
        if segn:
            m.segnalazioni.set(segn)
        registra(m, "aperta", user, ruolo="gestore", nota=m.motivo)
    from .segnalazioni import avvisa_autore

    for cr in segn:
        if cr.status == ChangeRequestStatus.APERTA:
            cr.status = ChangeRequestStatus.IN_CARICO
            cr.gestita_da = user
            cr.gestita_il = timezone.now()
            if not cr.risposta_gestore:
                cr.risposta_gestore = f"Presa in carico: modifica di {m.codice} in corso."
            cr.save(update_fields=["status", "gestita_da", "gestita_il", "risposta_gestore", "updated_at"])
            avvisa_autore(cr)
    if m.redattore_id and m.redattore_id != getattr(user, "pk", None):
        avvisa([m.redattore_id], f"Ti è stata affidata la redazione di {m.codice} · {m.oggetto}.", url_di(m))
    return m


def emetti(m, revisione, *, user=None, nota: str = "", automatica: bool = False) -> None:
    """Chiude la modifica sulla revisione emessa: segnalazioni recepite, rilettura, avvisi."""
    from .segnalazioni import avvisa_autore, crea_rilettura

    with transaction.atomic():
        if m.documento_id is None:
            m.documento = revisione.document
        m.revisione_emessa = revisione
        prima = m.stato
        m.stato = S.EMESSA
        m.stato_dal = timezone.now()
        m.save(update_fields=["documento", "revisione_emessa", "stato", "stato_dal", "aggiornata_il"])
        testo = nota or (f"Riconosciuta dalla sincronizzazione: Rev.{revisione.revision_code} nella cartella SGI."
                         if automatica else f"Rev.{revisione.revision_code}")
        registra(m, "emessa", user, ruolo="sistema" if automatica else "gestore", nota=testo, stato_da=prima)
    for cr in m.segnalazioni.exclude(status=ChangeRequestStatus.RESPINTA):
        if cr.status == ChangeRequestStatus.RECEPITA and cr.recepita_in_revisione_id:
            continue
        cr.status = ChangeRequestStatus.RECEPITA
        cr.recepita_in_revisione = revisione
        cr.gestita_il = timezone.now()
        if user is not None and getattr(user, "pk", None):
            cr.gestita_da = user
        cr.save(update_fields=["status", "recepita_in_revisione", "gestita_il", "gestita_da", "updated_at"])
        avvisa_autore(cr)
    if m.rilettura_automatica:
        try:
            crea_rilettura(m.documento, revisione, da_utente=user if getattr(user, "pk", None) else m.creata_da)
        except Exception:
            logger.exception("CN-SGI modifiche: rilettura automatica non creata per %s", m.pk)
    avvisa({m.redattore_id, m.verificatore_id, m.approvatore_id, m.creata_da_id} - {getattr(user, "pk", None)},
           f"{m.codice} è in vigore nella Rev.{revisione.revision_code}.", url_di(m))


def _codice_piatto(c: str) -> str:
    return re.sub(r"[\s._-]+", "", (c or "").upper())


def riconosci_emissioni() -> int:
    """Dopo la sincronizzazione: le modifiche approvate la cui nuova revisione è arrivata nella cartella SGI."""
    n = 0
    for m in SgiModifica.objects.filter(stato=S.APPROVATA).select_related("documento"):
        try:
            doc = m.documento
            if doc is None and m.nuovo_codice:
                piatto = _codice_piatto(m.nuovo_codice)
                doc = next((d for d in ProcedureDocument.objects.filter(is_active=True).only("pk", "code")
                            if _codice_piatto(d.code) == piatto), None)
            if doc is None:
                continue
            rev = doc.current_revision()
            if rev is None or rev.pk == m.revisione_base_id:
                continue
            if m.documento_id is None:
                m.documento = doc
            emetti(m, rev, automatica=True)
            n += 1
        except Exception:
            logger.exception("CN-SGI modifiche: emissione non riconosciuta per %s", m.pk)
    return n


def solleciti(gestori=None) -> int:
    """Ogni mattina: avvisa chi ha in mano una modifica ferma da almeno GIORNI_SOLLECITO giorni (una volta ogni GIORNI_SOLLECITO)."""
    adesso = timezone.now()
    soglia = adesso - timedelta(days=GIORNI_SOLLECITO)
    n = 0
    for m in SgiModifica.objects.filter(stato__in=[S.IN_REDAZIONE, S.IN_VERIFICA, S.IN_APPROVAZIONE, S.APPROVATA],
                                        stato_dal__lte=soglia).select_related("documento"):
        if m.sollecitata_il and m.sollecitata_il > soglia:
            continue
        ruolo, chi = chi_deve_agire(m)
        destinatari = [chi.pk] if chi is not None else list(gestori or [])
        giorni = (adesso - m.stato_dal).days
        if avvisa(destinatari, f"{m.codice} · {m.oggetto}: {m.get_stato_display().lower()} da {giorni} giorni.", url_di(m)):
            SgiModifica.objects.filter(pk=m.pk).update(sollecitata_il=adesso)
            n += 1
    return n


# ---------------------------------------------------------------------------
# Elenchi
# ---------------------------------------------------------------------------


@dataclass
class Riga:
    m: SgiModifica
    ruolo: str
    chi: object
    giorni: int
    mia: bool

    @property
    def ruolo_label(self) -> str:
        return RUOLI.get(self.ruolo, "")

    @property
    def scaduta(self) -> bool:
        return bool(self.m.entro and self.m.entro < timezone.localdate())


def elenco(user, gestore: bool, *, stato: str = "", solo_mie: bool = False, aperte: bool = True) -> list[Riga]:
    from django.db.models import Q

    qs = SgiModifica.objects.select_related("documento", "redattore", "verificatore", "approvatore")
    if not gestore or solo_mie:
        uid = getattr(user, "pk", None)
        qs = qs.filter(Q(redattore_id=uid) | Q(verificatore_id=uid) | Q(approvatore_id=uid) | Q(creata_da_id=uid))
    if stato:
        qs = qs.filter(stato=stato)
    elif aperte:
        qs = qs.exclude(stato__in=[S.EMESSA, S.ANNULLATA])
    adesso = timezone.now()
    out = []
    for m in qs.order_by("stato_dal")[:300]:
        ruolo, chi = chi_deve_agire(m)
        mia = (chi is not None and chi.pk == getattr(user, "pk", None)) or (ruolo == "gestore" and gestore)
        out.append(Riga(m, ruolo, chi, (adesso - m.stato_dal).days, mia))
    return out


def da_fare(user, gestore: bool) -> list[Riga]:
    """Le modifiche che aspettano un'azione dell'utente."""
    return [r for r in elenco(user, gestore) if r.mia]


def in_lavorazione_per(doc):
    return SgiModifica.objects.filter(documento=doc).exclude(stato__in=[S.EMESSA, S.ANNULLATA]).order_by("-creata_il").first()


def prossimi_codici(limite: int = 8) -> list[tuple[str, str]]:
    """Famiglie di codici più usate con il prossimo numero libero (aiuto per i documenti nuovi)."""
    famiglie: dict[str, list[tuple[int, int]]] = {}
    for code in ProcedureDocument.objects.filter(is_active=True).values_list("code", flat=True):
        m = re.match(r"^(.*?)(\d+)\s*$", code or "")
        if not m or not m.group(1).strip():
            continue
        famiglie.setdefault(m.group(1), []).append((int(m.group(2)), len(m.group(2))))
    out = []
    for pref, numeri in sorted(famiglie.items(), key=lambda kv: -len(kv[1]))[:limite]:
        massimo, cifre = max(numeri)
        out.append((pref.strip(), f"{pref}{str(massimo + 1).zfill(cifre)}"))
    return out
