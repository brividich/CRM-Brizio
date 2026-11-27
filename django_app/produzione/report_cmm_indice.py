"""Archivio dei report CMM della share: lettura dei PDF e andamento delle quote per P/N.

La share (``settings.PRODUZIONE_REPORT_CMM_ROOT``) è ordinata così::

    <radice>\\<P/N>\\<OP-aaaa-n>\\<fase>_<OP-aaaa-n>_<Z..>_<S/N>[_<programma>].pdf

Ogni PDF si legge con il lettore di Gestione anomalie (``anomalie.report_cmm.leggi_pdf``, senza OCR)
e le righe di misura finiscono in ``MisuraCMM``. Un file già letto si rilegge solo se cambiano
dimensione o data di modifica. Il portale non scrive mai nella share.

Le quote si confrontano dentro lo stesso P/N e lo stesso programma senza revisione
(«Part Program Name» del report senza ``_REVn``), per nome: ``chiave`` = nome senza spazi, maiuscolo.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tasks.identity import normalize_part_number

from . import spc
from .models import AliasQuotaCMM, CartellaReportCMM, MisuraCMM, NotaQuotaCMM, ReportCMM

logger = logging.getLogger(__name__)

MAX_BYTES = 25 * 1024 * 1024
_OP_CARTELLA = re.compile(r"^(OP|OG)-(\d{4})-(\d+)$", re.I)
_OP_NEL_FILE = re.compile(r"(?:^|_)((?:OP|OG)-\d{4}-\d+)_", re.I)
_REV = re.compile(r"_REV[\w-]*?(?=_|$)", re.I)
_DATA = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})")
# Mesi per esteso dei report vecchi (italiano, inglese, tedesco): chiave = prime tre lettere.
_MESI = {k: i for i, ks in enumerate((
    ("gen", "jan"), ("feb",), ("mar", "mär"), ("apr",), ("mag", "may", "mai"), ("giu", "jun"),
    ("lug", "jul"), ("ago", "aug"), ("set", "sep"), ("ott", "oct", "okt"), ("nov",), ("dic", "dec", "dez"),
), start=1) for k in ks}
_DATA_ESTESA = re.compile(r"\b(\d{1,2})\.?\s+([A-Za-zäÄ]{3,})\.?\s+(\d{4})\b")
_DATA_ESTESA_EN = re.compile(r"\b([A-Za-z]{3,})\.?\s+(\d{1,2}),?\s+(\d{4})\b")
_NON_STAMPABILI = re.compile(r"[^\w\s./-]", re.U)


# Versione del lettore dei PDF (anomalie.report_cmm.leggi_pdf). Va alzata quando il lettore impara un formato
# nuovo: i report rimasti senza quote con una versione più vecchia si rileggono anche se il file non è cambiato.
# 2 = formato vecchio dei report (CALYPSO con novaPDF, «Aktual», fino al 2024).
LETTORE = 2


def radice() -> str:
    return str(getattr(settings, "PRODUZIONE_REPORT_CMM_ROOT", "") or "").strip()


def attivo() -> bool:
    return bool(radice())


def chiave_quota(nome: str) -> str:
    return re.sub(r"\s+", "", str(nome or "")).upper()[:200]


def titolo_op(cartella_o_file: str) -> str:
    """«OP-2026-0010» (cartella o nome file) -> «OP/2026/0010», come nella tabella degli OP."""
    nome = str(cartella_o_file or "")
    m = _OP_CARTELLA.match(nome)
    if not m:
        m2 = _OP_NEL_FILE.search(nome)
        m = _OP_CARTELLA.match(m2.group(1)) if m2 else None
    return f"{m.group(1).upper()}/{m.group(2)}/{m.group(3)}" if m else ""


def programma_base(programma: str) -> str:
    return _REV.sub("", str(programma or "")).strip("_ ")[:200]


def dati_dal_nome(file: str) -> dict:
    """``210_OP-2026-0007_ZPN_SN900_A.pdf`` -> fase 210, S/N SN900, programma «210_ZPN_A» (ripiego senza testata)."""
    base = re.sub(r"\.pdf$", "", file, flags=re.I)
    m = _OP_NEL_FILE.search(base)
    if not m:
        return {"fase": "", "seriale": "", "programma": ""}
    fase = base[:m.start(1)].strip("_").split("_")[-1] if m.start(1) else ""
    resto = base[m.end():].split("_")
    z = resto[0] if resto and resto[0].upper().startswith("Z") else ""
    dopo = resto[1:] if z else resto
    seriale = dopo[0] if dopo else ""
    suffisso = "_".join(dopo[1:])
    programma = "_".join(x for x in (fase, z, suffisso) if x)
    return {"fase": fase[:40], "seriale": seriale[:100], "programma": programma[:200]}


def pulisci_seriale(testo: str) -> str:
    return re.sub(r"\s+", " ", _NON_STAMPABILI.sub(" ", str(testo or ""))).strip(" _-")[:100]


def data_report(testo: str) -> date | None:
    """«13/09/2023» o, nei report vecchi, «13 settembre 2023» / «September 13, 2023»."""
    testo = str(testo or "")
    m = _DATA.search(testo)
    try:
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = _DATA_ESTESA.search(testo)
        if m:
            return date(int(m.group(3)), _MESI[m.group(2).lower()[:3]], int(m.group(1)))
        m = _DATA_ESTESA_EN.search(testo)
        if m:
            return date(int(m.group(3)), _MESI[m.group(1).lower()[:3]], int(m.group(2)))
    except (ValueError, KeyError):
        return None
    return None


# --- Cartelle dei P/N --------------------------------------------------------------------------------

def cartelle_pn() -> list[tuple[str, str, float]]:
    """``[(pn normalizzato, percorso, data di modifica)]`` delle cartelle sotto la radice."""
    out = []
    try:
        with os.scandir(radice()) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False) and not e.name.startswith((".", "_", "~")):
                    pn = normalize_part_number(e.name)
                    if pn:
                        try:
                            mtime = e.stat().st_mtime
                        except OSError:
                            mtime = 0
                        out.append((pn, e.path, mtime))
    except OSError as exc:
        logger.warning("report CMM: radice non leggibile %s: %s", radice(), exc)
        raise
    return out


def cartella_del_pn(pn: str) -> str:
    """Percorso della cartella del P/N: prima per nome esatto, poi cercando fra tutte."""
    pn_norm = normalize_part_number(pn)
    if not pn_norm or not attivo():
        return ""
    nota = CartellaReportCMM.objects.filter(pn=pn_norm).values_list("percorso", flat=True).first()
    if nota and os.path.isdir(nota):
        return nota
    diretta = os.path.join(radice(), pn_norm)
    if os.path.isdir(diretta):
        return diretta
    for p, percorso, _m in cartelle_pn():
        if p == pn_norm:
            return percorso
    return ""


# Nome dei report CMM: «<fase>_<OP-aaaa-n>_Z.._<S/N>[…].pdf». Gli altri PDF (M, LPT, PLOT, PDU, scansioni, file
# senza OP nel nome) non si aprono: sull'inventario del 25/11 erano 94.000 su 173.000 e quasi mai report.
_NOME_CMM = re.compile(r"(?:^|_)(?:OP|OG)-\d{4}-\d+_Z[A-Z]{0,3}_", re.I)
_NOME_NON_CMM = re.compile(r"_(LPT|M|PDU|PLOT|PDM|DIM|FAI|CCI)(_|\.pdf$)", re.I)
# I report stanno nella cartella dell'OP (99%) o al massimo due livelli sotto; più in basso ci sono i
# programmi della macchina (migliaia di file per P/N): non si scende.
PROFONDITA_MAX = 3


class TempoScaduto(Exception):
    """Il giro ha finito il tempo mentre scorreva le cartelle."""


def nome_da_report_cmm(nome: str) -> bool:
    return nome.lower().endswith(".pdf") and bool(_NOME_CMM.search(nome)) and not _NOME_NON_CMM.search(nome)


def _pdf_della_cartella(percorso: str, scadenza: float | None = None):
    """I PDF con nome da report CMM sotto la cartella del P/N (fino a ``PROFONDITA_MAX`` livelli), con
    dimensione e data. Il tempo si controlla a ogni cartella: oltre ``scadenza`` solleva ``TempoScaduto``."""
    pila = [(percorso, 0)]
    while pila:
        base, livello = pila.pop()
        if scadenza and time.monotonic() > scadenza:
            raise TempoScaduto
        with os.scandir(base) as it:
            voci = list(it)
        for e in voci:
            nome = e.name
            if nome.startswith((".", "~")):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if livello < PROFONDITA_MAX:
                        pila.append((e.path, livello + 1))
                elif nome_da_report_cmm(nome):
                    st = e.stat()
                    yield e.path, nome, st.st_size, st.st_mtime, os.path.basename(base)
            except OSError:
                continue


# --- Lettura -----------------------------------------------------------------------------------------

def _leggi_report(cartella: CartellaReportCMM, percorso: str, file: str, dimensione: int, mtime: float,
                  cartella_op: str, esistente: ReportCMM | None) -> ReportCMM:
    from anomalie.report_cmm import ErroreReport, leggi_pdf

    dal_nome = dati_dal_nome(file)
    campi = {
        "cartella": cartella, "pn": cartella.pn, "file": file[:255], "dimensione": dimensione, "modificato": mtime,
        "op": titolo_op(cartella_op) or titolo_op(file), "fase": dal_nome["fase"], "programma": dal_nome["programma"],
        "programma_base": programma_base(dal_nome["programma"]), "seriale": dal_nome["seriale"],
        "data": datetime.fromtimestamp(mtime).date() if mtime else None,
        "pn_report": "", "righe": 0, "fuori": 0, "da_verificare": 0, "errore": "", "lettore": LETTORE,
    }
    righe = []
    if dimensione > MAX_BYTES:
        campi["errore"] = "File troppo grande (oltre 25 MB)."
    else:
        try:
            with open(percorso, "rb") as fh:
                esito = leggi_pdf(fh.read(), ocr=False)
            testa = esito.get("intestazione") or {}
            righe = esito.get("righe") or []
            if testa.get("programma"):
                campi["programma"] = testa["programma"][:200]
                campi["programma_base"] = programma_base(testa["programma"])
            if pulisci_seriale(testa.get("seriale")):
                campi["seriale"] = pulisci_seriale(testa.get("seriale"))
            campi["data"] = data_report(testa.get("data")) or campi["data"]
            campi["pn_report"] = str(testa.get("part_number") or "")[:100]
        except ErroreReport as exc:
            campi["errore"] = str(exc)[:300]
        except OSError as exc:
            campi["errore"] = f"File non leggibile: {exc}"[:300]
        except Exception as exc:  # un PDF rovinato non deve fermare il giro
            logger.exception("report CMM: errore su %s", percorso)
            campi["errore"] = f"Errore di lettura: {type(exc).__name__}"[:300]
    campi["righe"] = len(righe)
    campi["fuori"] = sum(1 for r in righe if r.get("fuori"))
    campi["da_verificare"] = sum(1 for r in righe if r.get("da_verificare"))
    with transaction.atomic():
        if esistente is None:
            report = ReportCMM.objects.create(percorso=percorso[:500], **campi)
        else:
            for k, v in campi.items():
                setattr(esistente, k, v)
            esistente.save()
            esistente.misure.all().delete()
            report = esistente
        MisuraCMM.objects.bulk_create([
            MisuraCMM(
                report=report, indice=r.get("indice") or n, pagina=r.get("pagina") or 0,
                sezione=str(r.get("sezione") or "")[:200], nome=str(r.get("caratteristica") or "")[:200] or "?",
                chiave=chiave_quota(r.get("caratteristica")) or "?", tipo=str(r.get("tipo_zeiss") or "")[:40],
                misurato=r["misurato"], nominale=r["nominale"], tol_sup=r["tol_sup"],
                tol_inf=r.get("tol_inf_limite", r["tol_inf"]), fuori=bool(r.get("fuori")),
                fuori_di=r.get("fuori_di") if r.get("fuori") else None, da_verificare=bool(r.get("da_verificare")),
            ) for n, r in enumerate(righe)
        ], batch_size=500)
    return report


def leggi_cartella(pn: str, percorso: str, scadenza: float | None = None) -> dict:
    """Legge (o rilegge) i PDF nuovi o cambiati della cartella di un P/N; toglie quelli spariti.

    ``scadenza`` (``time.monotonic()``): oltre, si ferma e la cartella resta da finire."""
    pn = normalize_part_number(pn)
    cartella, _ = CartellaReportCMM.objects.get_or_create(percorso=percorso[:500], defaults={"pn": pn})
    if cartella.pn != pn:
        cartella.pn = pn
    cartella.in_lettura_dal = timezone.now()
    cartella.save(update_fields=["pn", "in_lettura_dal"])
    noti = {r.percorso: r for r in ReportCMM.objects.filter(cartella=cartella)}
    visti, stat = set(), {"letti": 0, "invariati": 0, "tolti": 0, "completa": True}
    try:
        for p, f, dim, mtime, base in _pdf_della_cartella(percorso, scadenza):
            visti.add(p[:500])
            vecchio = noti.get(p[:500])
            if (vecchio and vecchio.dimensione == dim and abs(vecchio.modificato - mtime) < 1
                    and (vecchio.righe or vecchio.lettore >= LETTORE)):
                stat["invariati"] += 1
                continue
            if scadenza and time.monotonic() > scadenza:
                stat["completa"] = False
                break
            _leggi_report(cartella, p, f, dim, mtime, base, vecchio)
            stat["letti"] += 1
        cartella.errore = ""
    except TempoScaduto:
        stat["completa"] = False
    except OSError as exc:
        stat["completa"] = False
        cartella.errore = f"Cartella non leggibile: {exc}"[:300]
    if stat["completa"]:
        spariti = [r.pk for k, r in noti.items() if k not in visti]
        if spariti:
            stat["tolti"] = ReportCMM.objects.filter(pk__in=spariti).delete()[1].get("produzione.ReportCMM", 0)
        cartella.letta_il = timezone.now()
    cartella.in_lettura_dal = None
    cartella.save(update_fields=["letta_il", "errore", "in_lettura_dal"])
    if stat["letti"]:
        from .avvisi_cmm import invia_avvisi

        stat["avvisi"] = invia_avvisi(pn)
    return stat


def leggi_pn(pn: str) -> dict:
    """Lettura completa della cartella di un P/N (pulsante della scheda P/N)."""
    percorso = cartella_del_pn(pn)
    if not percorso:
        return {"errore": "Nessuna cartella per questo P/N nella share dei report."}
    return leggi_cartella(pn, percorso)


def giro(minuti: int | None = None) -> dict:
    """Giro pianificato: prima le cartelle mai lette, poi quelle cambiate, poi quelle con report da rileggere
    (lettore aggiornato), poi le più vecchie, finché c'è tempo."""
    if not attivo():
        return {"saltato": "cartella dei report non impostata"}
    minuti = minuti or int(getattr(settings, "PRODUZIONE_REPORT_CMM_MINUTI", 15) or 15)
    scadenza = time.monotonic() + minuti * 60
    lette = {c.percorso: c.letta_il for c in CartellaReportCMM.objects.all()}
    da_rileggere = set(ReportCMM.objects.filter(righe=0, lettore__lt=LETTORE, errore="")
                       .values_list("cartella__percorso", flat=True).distinct())
    cartelle = cartelle_pn()
    # Mai lette prima; poi quelle cambiate dopo l'ultima lettura; poi quelle con report da rileggere; poi
    # dalla lettura più vecchia.
    def ordine(c):
        letta = lette.get(c[1][:500])
        if letta is None:
            return (0, -c[2])
        if c[2] > letta.timestamp():
            return (1, letta.timestamp())
        return (2 if c[1][:500] in da_rileggere else 3, letta.timestamp())
    cartelle.sort(key=ordine)
    tot = {"cartelle": 0, "letti": 0, "invariati": 0, "tolti": 0, "da_finire": 0}
    for pn, percorso, _m in cartelle:
        if time.monotonic() > scadenza:
            tot["da_finire"] += 1
            continue
        s = leggi_cartella(pn, percorso, scadenza)
        tot["cartelle"] += 1
        for k in ("letti", "invariati", "tolti"):
            tot[k] += s[k]
        if not s["completa"]:
            tot["da_finire"] += 1
    # Anagrafica dei P/N: articoli nuovi dalla share e dagli OP, riepilogo del catalogo; Cpk dei P/N letti ora.
    try:
        from . import articoli

        tot["articoli"] = articoli.sincronizza(cartelle)
        lette_ora = [pn for pn, _p, _m in cartelle[: tot["cartelle"]]]   # le cartelle lette in questo giro
        tot["analizzati"] = articoli.aggiorna_cpk(max(30.0, scadenza - time.monotonic() + 60), pn=lette_ora)
        # poi gli altri P/N con l'analisi vecchia o mai fatta (Quote CMM legge questi numeri)
        tot["analizzati"] += articoli.aggiorna_cpk(max(60.0, scadenza - time.monotonic() + 120))
    except Exception:  # pragma: no cover - il catalogo non deve fermare la lettura dei report
        logger.exception("report CMM: sincronizzazione degli articoli")
    return tot


# --- Letture per le pagine ---------------------------------------------------------------------------

def programmi_del_pn(pn: str) -> list[dict]:
    from django.db.models import Count, Max, Sum

    return list(
        ReportCMM.objects.filter(pn=pn, righe__gt=0).values("programma_base")
        .annotate(n=Count("id"), ultima=Max("data"), fuori=Sum("fuori")).order_by("-ultima", "programma_base")
    )


def id_quota(chiave: str, nominale: float) -> str:
    """Una quota = nome + nominale: un programma che riusa il nome con un altro nominale fa una quota diversa."""
    return f"{chiave}|{nominale:.4f}"


def percorso_sicuro(percorso: str) -> str:
    """Il percorso, se è un PDF che esiste sotto la cartella dei report; altrimenti ``""``."""
    if not attivo() or not percorso or not percorso.lower().endswith(".pdf"):
        return ""
    base = os.path.normcase(os.path.abspath(radice())).rstrip("\\/")
    vero = os.path.normcase(os.path.abspath(percorso))
    if not vero.startswith(base + os.sep) or not os.path.isfile(percorso):
        return ""
    return percorso


def riepilogo_pn(pn: str) -> dict:
    """Per la scheda del P/N: quanti report, quanti con quote fuori, gli ultimi e lo stato della lettura."""
    qs = ReportCMM.objects.filter(pn=pn, righe__gt=0, escluso=False)
    return {
        "n": qs.count(), "con_fuori": qs.filter(fuori__gt=0).count(), "ultimi": list(qs.order_by("-data", "-modificato", "-id")[:8]),
        "cartella": CartellaReportCMM.objects.filter(pn=pn).order_by("-letta_il").first(), "attivo": attivo(),
    }


def report_dell_op(titolo: str) -> list[ReportCMM]:
    return list(ReportCMM.objects.filter(op=titolo, righe__gt=0).order_by("-data", "-modificato", "-id")[:50]) if titolo else []


def conteggi_per_pn() -> dict[str, dict]:
    """``{pn: {"n": report, "con_fuori": report con quote fuori}}`` per l'elenco dei P/N (una query)."""
    from django.db.models import Count, Q

    return {
        r["pn"]: {"n": r["n"], "con_fuori": r["con_fuori"]}
        for r in ReportCMM.objects.filter(righe__gt=0, escluso=False).values("pn")
        .annotate(n=Count("id"), con_fuori=Count("id", filter=Q(fuori__gt=0)))
    }


# --- Analisi quote (pagina interattiva) ----------------------------------------------------------------

LIMITE_REPORT = 800
_CACHE_FINESTRA = "prod_cmm_finestra"


def finestra() -> int:
    """Su quanti pezzi (ultima misura per S/N) si calcolano gli indici di riferimento: Impostazioni, predefinito 30."""
    from django.core.cache import cache

    from .models import ImpostazioniQuoteCMM

    n = cache.get(_CACHE_FINESTRA)
    if n is None:
        n = ImpostazioniQuoteCMM.attuali().finestra
        cache.set(_CACHE_FINESTRA, n, 300)
    return n if n in spc.FINESTRE else spc.FINESTRA


def imposta_finestra(n: int) -> bool:
    """Cambia la finestra; ``True`` se è cambiata (le analisi precalcolate vanno rifatte: ``analisi_il`` a vuoto)."""
    from django.core.cache import cache

    from .models import ArticoloPN, ImpostazioniQuoteCMM

    imp = ImpostazioniQuoteCMM.attuali()
    if n not in spc.FINESTRE or imp.finestra == n:
        return False
    imp.finestra = n
    imp.save(update_fields=["finestra"])
    cache.delete(_CACHE_FINESTRA)
    ArticoloPN.objects.update(analisi_il=None)
    return True


def pn_da_guardare(non_capaci, deriva, fuori_ultimo, fuori_recenti) -> bool:
    """L'unica regola di «P/N da guardare» dalle misure: quote sotto obiettivo, in deriva, fuori nell'ultimo report,
    o report recenti con quote fuori."""
    return bool(non_capaci or deriva or fuori_ultimo or fuori_recenti)


def _round(v):
    return None if v is None else round(float(v), 6)


def _split_quota(qid: str) -> tuple[str, float]:
    chiave, _, nom = str(qid or "").rpartition("|")
    try:
        return chiave, float(nom)
    except ValueError:
        return qid, 0.0


def dati_programma(pn: str, prog: str, da: date | None = None, a: date | None = None,
                   limite: int = LIMITE_REPORT, con_esclusi: bool = True) -> dict:
    """Tutte le misure del programma, compatte, per la pagina «Analisi quote».

    ``report``: ``[id, S/N, OP, data ISO, file, n fuori, escluso 0/1, programma con revisione, motivo esclusione]``
    dal più vecchio (al massimo ``limite``, i più recenti, più i report delle quote unite da altri programmi);
    ``quote``: ``{id, nome, sezione, tipo, nominale, unite}`` nell'ordine del report più recente;
    ``valori[i]``: per la quota i, ``[indice report, rilevato, tol+, tol-, fuori 0/1, fuori di, da verificare 0/1]``;
    ``note``: eventi scritti a mano; ``anomalie``: per indice report, le segnalazioni dello stesso OP e S/N.
    """
    qs = ReportCMM.objects.filter(pn=pn, programma_base=prog, righe__gt=0)
    if not con_esclusi:
        qs = qs.filter(escluso=False)
    if da:
        qs = qs.filter(data__gte=da)
    if a:
        qs = qs.filter(data__lte=a)
    totale = qs.count()
    campi = ("id", "seriale", "op", "data", "file", "fuori", "escluso", "programma", "escluso_motivo", "modificato")
    righe = list(qs.order_by("-data", "-modificato", "-id").values_list(*campi)[:limite])
    primo = min((r[3] for r in righe if r[3]), default=None)

    # Quote unite: l'origine (anche di un altro programma) entra nella quota di destinazione.
    alias = list(AliasQuotaCMM.objects.filter(pn=pn, prog_destinazione=prog))
    misure_alias = []
    for al in alias:
        chiave, nom = _split_quota(al.quota_origine)
        m = MisuraCMM.objects.filter(report__pn=pn, report__programma_base=al.prog_origine, report__righe__gt=0,
                                     chiave=chiave, nominale__gte=nom - 5e-5, nominale__lte=nom + 5e-5)
        if not con_esclusi:
            m = m.filter(report__escluso=False)
        if primo:
            m = m.filter(report__data__gte=primo)
        if a:
            m = m.filter(report__data__lte=a)
        misure_alias.append((al, m))
    id_noti = {r[0] for r in righe}
    extra = set()
    for _al, m in misure_alias:
        extra.update(m.values_list("report_id", flat=True))
    extra -= id_noti
    if extra:
        righe += list(ReportCMM.objects.filter(pk__in=list(extra)[:2000]).values_list(*campi))
    righe.sort(key=lambda r: (r[3] or date.min, r[9], r[0]))   # giorno, ora del file, lettura
    indice = {r[0]: i for i, r in enumerate(righe)}

    quote: dict[str, dict] = {}
    valori: dict[str, list] = {}

    def aggiungi(qid, rid, nome, sezione, tipo, ind, x, ts, ti, fuori, fdi, dv, nom):
        ri = indice.get(rid)
        if ri is None:
            return
        q = quote.get(qid)
        if q is None:
            q = quote[qid] = {"id": qid, "nominale": round(nom, 6), "unite": []}
            valori[qid] = []
        q.update(nome=nome, sezione=sezione, tipo=tipo, ordine=ind)
        valori[qid].append([ri, _round(x), _round(ts), _round(ti), 1 if fuori else 0, _round(fdi), 1 if dv else 0])

    if righe:
        origini_stesso_prog = {al.quota_origine: al.quota_destinazione for al in alias if al.prog_origine == prog}
        misure = MisuraCMM.objects.filter(report__pn=pn, report__programma_base=prog, report__righe__gt=0)
        if not con_esclusi:
            misure = misure.filter(report__escluso=False)
        if primo:
            misure = misure.filter(report__data__gte=primo)
        if a:
            misure = misure.filter(report__data__lte=a)
        colonne = ("report_id", "chiave", "nominale", "nome", "sezione", "tipo", "indice", "misurato", "tol_sup",
                   "tol_inf", "fuori", "fuori_di", "da_verificare")
        for rid, chiave, nom, nome, sezione, tipo, ind, x, ts, ti, fuori, fdi, dv in misure.values_list(*colonne).order_by(
                "report__data", "report_id", "indice"):
            qid = id_quota(chiave, nom)
            if qid in origini_stesso_prog:
                continue          # arriva con l'alias, sotto la destinazione
            aggiungi(qid, rid, nome, sezione, tipo, ind, x, ts, ti, fuori, fdi, dv, nom)
        for al, m in misure_alias:
            dest_chiave, dest_nom = _split_quota(al.quota_destinazione)
            for rid, chiave, nom, nome, sezione, tipo, ind, x, ts, ti, fuori, fdi, dv in m.values_list(*colonne):
                q = quote.get(al.quota_destinazione)
                aggiungi(al.quota_destinazione, rid, q["nome"] if q else nome, q["sezione"] if q else sezione,
                         q["tipo"] if q else tipo, q["ordine"] if q else ind, x, ts, ti, fuori, fdi, dv, dest_nom)
            if al.quota_destinazione in quote:
                quote[al.quota_destinazione]["unite"].append(
                    {"prog": al.prog_origine, "quota": al.quota_origine, "nome": _split_quota(al.quota_origine)[0], "id": al.pk})
        for qid in valori:
            valori[qid].sort(key=lambda v: v[0])
    elenco = sorted(quote.values(), key=lambda q: (q["ordine"], q["nome"]))
    note = [
        {"id": n.pk, "ri": indice[n.report_id], "testo": n.testo, "quota": n.quota,
         "autore": (n.creato_da.get_full_name() or n.creato_da.username) if n.creato_da_id else "",
         "il": n.creato_il.date().isoformat() if n.creato_il else ""}
        for n in NotaQuotaCMM.objects.filter(pn=pn, programma_base=prog).select_related("creato_da")
        if n.report_id in indice
    ]
    return {
        "pn": pn, "prog": prog, "totale": totale, "limite": limite, "tagliati": max(0, totale - min(totale, limite)),
        "report": [[r[0], r[1] or r[4], r[2], r[3].isoformat() if r[3] else "", r[4], r[5], 1 if r[6] else 0, r[7], r[8]]
                   for r in righe],
        "quote": elenco,
        "valori": [valori[q["id"]] for q in elenco],
        "note": note,
        "anomalie": anomalie_per_report(righe),
    }


def anomalie_per_report(righe) -> dict:
    """``{indice report: [{id, testo, aperta}]}``: segnalazioni di Gestione anomalie dello stesso OP e S/N."""
    from core.legacy_utils import legacy_table_columns

    colonne = legacy_table_columns("anomalie")
    if not righe or not {"ex_op_nominativo", "seriale"} <= set(colonne):
        return {}
    per_op: dict[str, list] = {}
    for i, r in enumerate(righe):
        if r[2] and r[1]:
            per_op.setdefault(r[2].lower(), []).append((i, r[1].upper()))
    if not per_op:
        return {}
    from django.db import connection

    descr = "descrizione" if "descrizione" in colonne else "seriale"
    chiusa = "COALESCE(chiudere, 0)" if "chiudere" in colonne else "0"
    out: dict[int, list] = {}
    ops = list(per_op)[:200]
    segnaposti = ",".join(["%s"] * len(ops))
    try:
        with connection.cursor() as cur:
            cur.execute(f"SELECT id, LOWER(ex_op_nominativo), seriale, {descr}, {chiusa} FROM anomalie "
                        f"WHERE LOWER(ex_op_nominativo) IN ({segnaposti})", ops)
            dati = cur.fetchall()
    except Exception:
        logger.exception("anomalie per i report CMM non lette")
        return {}
    for aid, op, seriale, testo, ch in dati:
        sn_anom = str(seriale or "").upper().strip()
        if len(sn_anom) < 2:
            continue
        for i, sn in per_op.get(op, []):
            if sn and (sn in sn_anom or sn_anom in sn):
                out.setdefault(i, []).append({"id": aid, "testo": str(testo or "")[:140], "aperta": not ch})
    return out


def deriva(us: list[float], ultimi: int = 20) -> dict | None:
    """Tendenza degli ultimi ``ultimi`` valori di tolleranza usata (0 = ideale, ±1 = limite).

    In deriva se la retta sale (o scende) di almeno il 20% della tolleranza in quei pezzi, l'ultimo punto della
    retta è oltre metà tolleranza nella stessa direzione e, al ritmo attuale, il limite arriva entro 50 pezzi.
    ``{"pendenza": per pezzo, "pezzi": quanti pezzi al limite (0 se già oltre), "verso": "sup"|"inf",
    "pezzi_min"/"pezzi_max": forchetta al 95% (``None`` = oltre 200 pezzi)}``."""
    return spc.deriva(us, ultimi)     # la formula è in spc


def segnali(xs: list[float]) -> list[dict]:
    """Regole di Nelson 1-8 ed EWMA: vedi ``spc.segnali``."""
    return spc.segnali(xs)


def unilaterale(nominale: float, lsl: float, usl: float) -> bool:
    """Forma, posizione, concentricità…: nominale 0 e limite inferiore 0, conta solo il superiore."""
    return spc.unilaterale(nominale, lsl, usl)


def usata(x: float, nominale: float, lsl: float, usl: float) -> float | None:
    """Tolleranza usata: 0 = ideale, ±1 = limite. Unilaterali: rilevato / limite superiore; le altre dal centro."""
    return spc.usata(x, nominale, lsl, usl)


def statistiche(punti: list[tuple[float, float, float]], nominale: float | None = None) -> dict:
    """``punti`` = ``[(rilevato, limite inferiore, limite superiore)]`` dal più vecchio, sui limiti dell'ultima misura.

    Le formule sono in ``spc.capacita``: Cp/Cpk con la σ di breve periodo, Pp/Ppk con la σ totale, metodo dei
    percentili per le quote di forma e posizione, intervallo del Cpk e verdetto; qui in più min, max, ultimo valore
    e tolleranza usata dall'ultima misura (``u``, vedi ``usata``)."""
    n = len(punti)
    if not n:
        return {"n": 0}
    xs = [p[0] for p in punti]
    x, lsl, usl = punti[-1]
    banda = usl - lsl
    out = spc.capacita(xs, lsl, usl, nominale)
    out.pop("weibull", None)
    out.update({"min": min(xs), "max": max(xs), "ultimo": x,
                "u": usata(x, nominale, lsl, usl) if nominale is not None
                else ((x - (usl + lsl) / 2) / (banda / 2) if banda > 0 else None)})
    return out


def ultima_per_seriale(report: list) -> list[int]:
    """Indici dei report da tenere con «ultima misura per S/N»: per ogni S/N il più recente (gli altri sono rimisure)."""
    return spc.ultima_per_seriale([r[1] for r in report])


def _confronto_op(vals, rep, lsl, usl, nom) -> dict | None:
    """Gli OP sono diversi fra loro? Kruskal-Wallis sui valori per OP e Cpk/Ppk di ognuno (almeno 5 pezzi)."""
    gruppi: dict[str, list] = {}
    for v in vals:
        gruppi.setdefault(rep[v[0]][2] or "—", []).append(v[1])
    test = spc.kruskal(gruppi)
    if not test:
        return None
    per_op = []
    for op, xs in gruppi.items():
        if len(xs) >= spc.MIN_CAPACITA:
            c = spc.capacita(xs, lsl, usl, nom)
            per_op.append({"op": op, "n": len(xs), "media": c["media"], "indice": c["indice"], "min": min(xs), "max": max(xs)})
    per_op.sort(key=lambda o: (o["indice"] if o["indice"] is not None else 99))
    return {"p": test["p"], "diversi": test["p"] < 0.05, "op": per_op}


def _tratto(vals, nom):
    """I valori del tratto finale con la tolleranza dell'ultima misura (``spc.tratto_tolleranza``)."""
    return vals[spc.tratto_tolleranza([(nom + v[3], nom + v[2]) for v in vals]):]


def _ripetibilita(tutti, rep, banda) -> dict | None:
    """Ripetibilità della CMM dalle rimisure dello stesso S/N entro 2 giorni, quando la prima misura non aveva quote
    fuori (altrimenti il pezzo è stato probabilmente rilavorato in mezzo)."""
    per_sn: dict[str, list] = {}
    for v in tutti:
        if v[1] is None:
            continue
        r = rep[v[0]]
        k = re.sub(r"[^A-Z0-9]", "", str(r[1] or "").upper())
        if k:
            per_sn.setdefault(k, []).append((r[3] or "", v[1], r[5]))
    diff = []
    for misure in per_sn.values():
        misure.sort()
        for (d1, x1, f1), (d2, x2, _f2) in zip(misure, misure[1:]):
            try:
                giorni = (date.fromisoformat(d2) - date.fromisoformat(d1)).days
            except ValueError:
                continue
            if giorni <= 2 and not f1:
                diff.append(x2 - x1)
    return spc.ripetibilita(diff, banda)


def analisi_pn(pn: str, ultimi: int | None = None) -> list[dict]:
    """Ogni quota di ogni programma del P/N sugli ultimi ``ultimi`` report validi (esclusi fuori, rimisure fuori):
    fuori nell'ultimo report, volte fuori, capacità (``spc.capacita``: Cpk, Ppk, ``indice`` = il peggiore dei due,
    intervallo e verdetto), deriva con forchetta, rischio del prossimo pezzo, limiti di controllo, segnali, punti di
    cambio, famiglia di quote che si muovono insieme, confronto fra OP, ripetibilità della misura e la serie dei
    valori. In cache finché non arrivano report nuovi."""
    from django.core.cache import cache
    from django.db.models import Max

    ultimi = ultimi or finestra()
    firma = ReportCMM.objects.filter(pn=pn).aggregate(m=Max("letto_il"), e=Max("escluso_il"))
    chiave = f"prod_cmm_analisi5:{pn}:{ultimi}:{firma['m']}:{firma['e']}:{AliasQuotaCMM.objects.filter(pn=pn).count()}"
    trovato = cache.get(chiave)
    if trovato is not None:
        return trovato
    out = []
    for p in programmi_del_pn(pn):
        d = dati_programma(pn, p["programma_base"], limite=ultimi * 2, con_esclusi=False)
        if not d["report"]:
            continue
        rep = d["report"]
        larga = ultima_per_seriale(rep)           # tutti i pezzi caricati (il doppio della finestra): confronto fra OP
        tieni = set(larga[-ultimi:])
        larga = set(larga)
        ultimo = max(tieni)
        righe_prog = []
        serie_famiglie = {}
        for q, tutti in zip(d["quote"], d["valori"]):
            vals = [v for v in tutti if v[0] in tieni and v[1] is not None]
            if not vals:
                continue
            nom = q["nominale"]
            # indici solo sul tratto con la tolleranza di oggi: una revisione che la cambia non riscrive il passato
            finestra_vals = vals
            i0 = spc.tratto_tolleranza([(nom + v[3], nom + v[2]) for v in vals])
            vals = finestra_vals[i0:]
            tol_cambio = None
            if i0:
                tol_cambio = {"indice": i0, "report": rep[vals[0][0]][0], "sn": rep[vals[0][0]][1],
                              "lsl": nom + finestra_vals[i0 - 1][3], "usl": nom + finestra_vals[i0 - 1][2]}
            punti = [(v[1], nom + v[3], nom + v[2]) for v in vals]
            s_ = statistiche(punti, nom)
            xs = [v[1] for v in vals]
            lsl, usl = punti[-1][1], punti[-1][2]
            us = [usata(v[1], nom, nom + v[3], nom + v[2]) for v in vals]
            der = deriva(us)
            pend_x = 0.0
            if der:
                pend_x = der["pendenza"] * (usl if unilaterale(nom, lsl, usl) else (usl - lsl) / 2)
            base = spc.base_controllo(len(xs))        # limiti di controllo congelati sui primi pezzi
            lim = spc.limiti_controllo(xs, base)
            cambi = [{"indice": c["indice"] + i0, "prima": c["prima"], "dopo": c["dopo"], "report": rep[vals[c["indice"]][0]][0],
                      "sn": rep[vals[c["indice"]][0]][1]} for c in spc.punti_cambio(xs)]
            serie_famiglie[q["id"]] = {rep[v[0]][0]: v[1] for v in vals}
            righe_prog.append({
                "prog": p["programma_base"], "quota": q, "fuori_ultimo": bool(vals[-1][0] == ultimo and vals[-1][4]),
                "n_fuori": sum(v[4] for v in vals), "n": len(vals), "cpk": s_.get("cpk"), "u": s_.get("u"),
                "ppk": s_.get("ppk"), "indice": s_.get("indice"), "cpk_basso": s_.get("cpk_basso"),
                "cpk_alto": s_.get("cpk_alto"), "verdetto": s_.get("verdetto"), "metodo": s_.get("metodo"),
                "u_abs": abs(s_["u"]) if s_.get("u") is not None else None, "deriva": der,
                "media": s_.get("media"), "sd": s_.get("sd"), "sigma_breve": s_.get("sigma_breve"), "cp": s_.get("cp"),
                "pp": s_.get("pp"), "lsl": lsl, "usl": usl, "deriva_info": der,
                "rischio": spc.rischio_prossimo(xs, lsl, usl, nom, pend_x),
                "controllo": lim, "cambi": cambi, "tol_cambio": tol_cambio,
                "segnali": [dict(g, da=g["da"] + i0, a=g["a"] + i0) for g in spc.segnali(xs, base)],
                "op_confronto": _confronto_op(_tratto([v for v in tutti if v[0] in larga and v[1] is not None], nom), rep, lsl, usl, nom),
                "ripetibilita": _ripetibilita(tutti, rep, usl - lsl if not unilaterale(nom, lsl, usl) else usl),
                # per il grafico del protocollo: [rilevato, fuori 0/1, id report] dal più vecchio
                "serie": [[round(v[1], 6), int(v[4]), rep[v[0]][0]] for v in finestra_vals],
            })
        numero, legami = spc.famiglie(serie_famiglie)
        nomi = {r["quota"]["id"]: r["quota"]["nome"] for r in righe_prog}
        for r in righe_prog:
            qid = r["quota"]["id"]
            r["famiglia"] = numero.get(qid)
            r["processo"] = spc.stato_processo(r["deriva"], r["cambi"], r["segnali"], r["n"])
            r["legami"] = [{"nome": nomi.get(o, o), "id": o, "r": round(rr, 2)} for o, rr in legami.get(qid, [])[:3]]
        out += righe_prog
    cache.set(chiave, out, 6 * 3600)
    return out


def analisi_salvata(pn: str) -> list[dict]:
    """L'analisi delle quote del P/N per le pagine: quella salvata dal giro in ``QuotaCapacita`` (una riga per quota,
    con ``pk`` = id stabile della quota) se è aggiornata all'ultimo report letto o escluso; altrimenti ``analisi_pn``
    (in cache). Le pagine non ricalcolano quando il giro ha già calcolato."""
    from django.db.models import Max

    from .models import ArticoloPN, QuotaCapacita

    fatta = ArticoloPN.objects.filter(pn=pn).values_list("analisi_il", flat=True).first()
    if fatta:
        firma = ReportCMM.objects.filter(pn=pn, righe__gt=0).aggregate(m=Max("letto_il"), e=Max("escluso_il"))
        ultimo = max((x for x in (firma["m"], firma["e"]) if x), default=None)
        if ultimo is None or ultimo <= fatta:
            righe = []
            for pk, dati in QuotaCapacita.objects.filter(pn=pn).exclude(dati="").values_list("pk", "dati"):
                try:
                    r = json.loads(dati)
                except ValueError:
                    continue
                r["pk"] = pk
                righe.append(r)
            if righe:
                righe.sort(key=lambda r: (r["prog"], r["quota"].get("ordine", 0), r["quota"]["nome"]))
                return righe
    return analisi_pn(pn)


def quote_critiche(pn: str, ultimi: int | None = None, quante: int = 6) -> list[dict]:
    """Le quote da guardare del P/N (``spc.da_guardare``): fuori nell'ultimo report, poi dal rischio più alto."""
    righe = [r for r in (analisi_pn(pn, ultimi) if ultimi else analisi_salvata(pn)) if spc.da_guardare(r["fuori_ultimo"], r["deriva"], r.get("verdetto"))]
    righe.sort(key=lambda r: (not r["fuori_ultimo"], -(r["rischio"] or 0), r["indice"] if r["indice"] is not None else 9))
    return righe[:quante]


def _cella_mappa(fuori: int, misurati: int, lunedi) -> dict:
    """Una cella della mappa P/N × settimana: report con quote fuori su report misurati, colore dalla quota fuori."""
    from datetime import timedelta

    if not misurati:
        livello = "vuoto"
    elif not fuori:
        livello = "zero"
    else:
        r = fuori / misurati
        livello = "basso" if r <= 0.12 else ("medio" if r <= 0.25 else "alto")
    return {"fuori": fuori, "n": misurati, "livello": livello, "da": lunedi, "a": lunedi + timedelta(days=6)}


def settimane_mappa(settimane: int = 12) -> list[dict]:
    """Le colonne della mappa: lunedì e numero ISO della settimana, dalla più vecchia."""
    from datetime import timedelta

    oggi = timezone.localdate()
    inizio = oggi - timedelta(days=oggi.weekday() + 7 * (settimane - 1))
    return [{"da": inizio + timedelta(days=7 * k), "n": (inizio + timedelta(days=7 * k)).isocalendar()[1]} for k in range(settimane)]


def quote_da_guardare_tutte(pns: list[str], quante: int = 15) -> list:
    """Le quote da guardare di questi P/N, dalla tabella precalcolata ``QuotaCapacita``: fuori nell'ultimo report,
    in deriva o sotto obiettivo (stessa regola di ``spc.da_guardare``), dal rischio più alto."""
    from django.db.models import Q

    from .models import QuotaCapacita

    # niente «pn IN (centinaia di P/N)»: si scorrono le quote da guardare già ordinate e si tengono quelle dei P/N scelti
    scelti, out = set(pns), []
    qs = (QuotaCapacita.objects.filter(Q(fuori_ultimo=True) | Q(deriva=True) | Q(verdetto__in=spc.SOTTO_OBIETTIVO))
          .order_by("-fuori_ultimo", "-rischio", "indice"))
    for q in qs.iterator(chunk_size=200):
        if q.pn in scelti:
            out.append(q)
            if len(out) >= quante:
                break
    return out


def cruscotto(giorni: int = 30, settimane: int = 12) -> list[dict]:
    """Una riga per P/N con report: fuori negli ultimi ``giorni``, per settimana report con fuori su report misurati
    (``celle``, la mappa), ultimo report (letture SQL veloci) e, dall'analisi precalcolata in ``ArticoloPN``, quote
    fuori nell'ultimo report, in deriva e con Cpk sotto 1,33 (``analisi_pronta`` falso = non ancora calcolata).
    Ordinate dalla più grave."""
    from datetime import timedelta

    from django.db.models import Count, Max, Q

    oggi = timezone.localdate()
    dal = oggi - timedelta(days=giorni)
    inizio_sett = oggi - timedelta(days=oggi.weekday() + 7 * (settimane - 1))
    validi = ReportCMM.objects.filter(righe__gt=0, escluso=False)
    righe = {r["pn"]: r for r in validi.values("pn").annotate(
        n=Count("id"), fuori_rec=Count("id", filter=Q(fuori__gt=0, data__gte=dal)), ultima=Max("data"))}
    if not righe:
        return []
    sett: dict[str, list[int]] = {pn: [0] * settimane for pn in righe}
    misurati: dict[str, list[int]] = {pn: [0] * settimane for pn in righe}
    for pn, d, f in validi.filter(data__gte=inizio_sett, data__lte=oggi).values_list("pn", "data", "fuori"):
        k = (d - inizio_sett).days // 7
        if 0 <= k < settimane and pn in sett:
            misurati[pn][k] += 1
            if f:
                sett[pn][k] += 1

    # con ROW_NUMBER() per P/N: una riga per P/N (una sottoquery in .annotate() non raggruppa e dava una riga per
    # report), senza liste lunghe in IN (mssql-django le trasforma in una tabella temporanea)
    from django.db.models import F, Window
    from django.db.models.functions import RowNumber

    numerati = validi.annotate(rn=Window(RowNumber(), partition_by=[F("pn")], order_by=[F("data").desc(), F("modificato").desc(), F("id").desc()]))
    ultimi = {pn: (sn, d, rid) for pn, sn, d, rid in numerati.filter(rn=1).values_list("pn", "seriale", "data", "id")}
    from .models import ArticoloPN

    # tutto il catalogo (qualche centinaio di righe) e filtro in Python: niente IN con centinaia di P/N
    calcolati = {a["pn"]: a for a in ArticoloPN.objects.values(
        "pn", "quote_non_capaci", "quote_deriva", "quote_fuori_ultimo", "analisi_il", "rischio_max", "salute") if a["pn"] in righe}
    out = []
    for pn, r in righe.items():
        a = calcolati.get(pn) or {}
        pronto = a.get("analisi_il") is not None
        out.append({
            "pn": pn, "n": r["n"], "fuori_rec": r["fuori_rec"], "settimane": sett[pn], "max_sett": max(sett[pn]) or 1,
            "analisi_pronta": pronto, "analisi_il": a.get("analisi_il"),
            "celle": [_cella_mappa(f, n, inizio_sett + timedelta(days=7 * k)) for k, (f, n) in enumerate(zip(sett[pn], misurati[pn]))],
            # dall'analisi precalcolata (articoli.analizza, nel giro): la pagina non ricalcola
            "cpk_bassi": a.get("quote_non_capaci", 0) if pronto else 0,
            "deriva": a.get("quote_deriva", 0) if pronto else 0,
            "fuori_ultimo": a.get("quote_fuori_ultimo", 0) if pronto else 0,
            "rischio": a.get("rischio_max") if pronto else None, "salute": a.get("salute") if pronto else None,
            "ultimo": ultimi.get(pn),
        })
    for r in out:
        r["da_guardare"] = pn_da_guardare(r["cpk_bassi"], r["deriva"], r["fuori_ultimo"], r["fuori_rec"])
        r["barre"] = [{"x": k * 9, "h": max(1, round(v / r["max_sett"] * 20)) if v else 1, "v": v}
                      for k, v in enumerate(r["settimane"])]
        for b in r["barre"]:
            b["y"] = 22 - b["h"]
    out.sort(key=lambda r: (r["salute"] if r["salute"] is not None else 101, -r["fuori_ultimo"], -r["fuori_rec"], r["pn"]))
    return out


def report_primo_articolo(op: str) -> ReportCMM | None:
    """Per il FAI: il primo report CMM valido dell'OP."""
    if not op:
        return None
    return (ReportCMM.objects.filter(op=op.replace("-", "/"), righe__gt=0, escluso=False)
            .order_by("data", "modificato", "id").first())


def capacita_dopo(report: ReportCMM, quante: int = 8) -> list[dict]:
    """Quote del report del primo articolo con il Cpk sui pezzi successivi dello stesso programma (peggiori prima)."""
    righe = []
    analisi = {(a["prog"], a["quota"]["id"]): a for a in analisi_salvata(report.pn)}
    for m in report.misure.all():
        a = analisi.get((report.programma_base, id_quota(m.chiave, m.nominale)))
        righe.append({"misura": m, "cpk": a["indice"] if a else None, "deriva": a["deriva"] if a else None,
                      "id": id_quota(m.chiave, m.nominale)})
    righe.sort(key=lambda r: (not r["misura"].fuori, r["cpk"] if r["cpk"] is not None else 9))
    return righe[:quante]
