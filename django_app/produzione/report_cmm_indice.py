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

import logging
import os
import re
import time
from datetime import date, datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tasks.identity import normalize_part_number

from .models import CartellaReportCMM, MisuraCMM, ReportCMM

logger = logging.getLogger(__name__)

MAX_BYTES = 25 * 1024 * 1024
_OP_CARTELLA = re.compile(r"^(OP|OG)-(\d{4})-(\d+)$", re.I)
_OP_NEL_FILE = re.compile(r"(?:^|_)((?:OP|OG)-\d{4}-\d+)_", re.I)
_REV = re.compile(r"_REV[\w-]*?(?=_|$)", re.I)
_DATA = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})")
_NON_STAMPABILI = re.compile(r"[^\w\s./-]", re.U)


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
    m = _DATA.search(str(testo or ""))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
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


def _pdf_della_cartella(percorso: str):
    """Tutti i PDF sotto la cartella del P/N (OP e sottocartelle), con dimensione e data."""
    for base, cartelle, files in os.walk(percorso):
        cartelle[:] = [c for c in cartelle if not c.startswith((".", "~"))]
        for f in files:
            if f.lower().endswith(".pdf") and not f.startswith("~"):
                p = os.path.join(base, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                yield p, f, st.st_size, st.st_mtime, os.path.basename(base)


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
        "pn_report": "", "righe": 0, "fuori": 0, "da_verificare": 0, "errore": "",
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
        for p, f, dim, mtime, base in _pdf_della_cartella(percorso):
            visti.add(p[:500])
            vecchio = noti.get(p[:500])
            if vecchio and vecchio.dimensione == dim and abs(vecchio.modificato - mtime) < 1:
                stat["invariati"] += 1
                continue
            if scadenza and time.monotonic() > scadenza:
                stat["completa"] = False
                break
            _leggi_report(cartella, p, f, dim, mtime, base, vecchio)
            stat["letti"] += 1
        cartella.errore = ""
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
    return stat


def leggi_pn(pn: str) -> dict:
    """Lettura completa della cartella di un P/N (pulsante della scheda P/N)."""
    percorso = cartella_del_pn(pn)
    if not percorso:
        return {"errore": "Nessuna cartella per questo P/N nella share dei report."}
    return leggi_cartella(pn, percorso)


def giro(minuti: int | None = None) -> dict:
    """Giro pianificato: prima le cartelle mai lette, poi le più vecchie, finché c'è tempo."""
    if not attivo():
        return {"saltato": "cartella dei report non impostata"}
    minuti = minuti or int(getattr(settings, "PRODUZIONE_REPORT_CMM_MINUTI", 15) or 15)
    scadenza = time.monotonic() + minuti * 60
    lette = {c.percorso: c.letta_il for c in CartellaReportCMM.objects.all()}
    cartelle = cartelle_pn()
    # Mai lette prima; poi quelle cambiate dopo l'ultima lettura; poi dalla lettura più vecchia.
    def ordine(c):
        letta = lette.get(c[1][:500])
        if letta is None:
            return (0, -c[2])
        cambiata = c[2] > letta.timestamp()
        return (1 if cambiata else 2, letta.timestamp())
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


def quote_del_programma(pn: str, prog: str) -> list[dict]:
    """Una riga per quota (nome + nominale): nome e gruppo più recenti, in quanti report c'è e quante volte è fuori."""
    righe: dict[str, dict] = {}
    for m in (MisuraCMM.objects.filter(report__pn=pn, report__programma_base=prog)
              .order_by("report__data", "report_id", "indice")
              .values("chiave", "nominale", "nome", "sezione", "tipo", "indice", "fuori", "report_id")):
        k = id_quota(m["chiave"], m["nominale"])
        r = righe.get(k)
        if r is None:
            r = righe[k] = {"id": k, "chiave": m["chiave"], "nominale": m["nominale"], "report": set(), "n_fuori": 0}
        r.update(nome=m["nome"], sezione=m["sezione"], tipo=m["tipo"], indice=m["indice"])
        r["report"].add(m["report_id"])
        r["n_fuori"] += 1 if m["fuori"] else 0
    out = []
    nomi_doppi = {c for c in (r["chiave"] for r in righe.values()) if sum(1 for x in righe.values() if x["chiave"] == c) > 1}
    for r in righe.values():
        r["n"] = len(r.pop("report"))
        r["doppio"] = r["chiave"] in nomi_doppi
        out.append(r)
    out.sort(key=lambda r: (r["indice"], r["nome"]))
    return out


def andamento(pn: str, prog: str, quota: dict) -> list[dict]:
    """La quota (nome + nominale) in tutti i report del programma, dal più vecchio."""
    out = []
    for m in (MisuraCMM.objects.filter(report__pn=pn, report__programma_base=prog, chiave=quota["chiave"],
                                       nominale__gte=quota["nominale"] - 0.00005, nominale__lte=quota["nominale"] + 0.00005)
              .select_related("report").order_by("report__data", "report__id", "indice")):
        out.append({
            "report": m.report, "misura": m, "inf": m.nominale + m.tol_inf, "sup": m.nominale + m.tol_sup,
        })
    return out


def grafico(punti: list[dict], larghezza: int = 760, altezza: int = 260) -> dict | None:
    """Coordinate SVG dell'andamento: rilevato, nominale e limiti, un punto per report.

    Le coordinate decimali vanno al template già come testo col punto: con la localizzazione
    italiana un float diventerebbe «226,0», che l'SVG non accetta."""
    if not punti:
        return None
    sx, dx, su, giu = 48, 16, 16, 34
    valori = [p["misura"].misurato for p in punti] + [p["inf"] for p in punti] + [p["sup"] for p in punti]
    lo, hi = min(valori), max(valori)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    margine = (hi - lo) * 0.08
    lo, hi = lo - margine, hi + margine
    n = len(punti)
    passo = (larghezza - sx - dx) / max(n - 1, 1)

    def x(i):
        return round(sx + (i * passo if n > 1 else (larghezza - sx - dx) / 2), 1)

    def y(v):
        return round(su + (hi - v) / (hi - lo) * (altezza - su - giu), 1)

    def linea(chiave):
        return " ".join(f"{x(i)},{y(chiave(p))}" for i, p in enumerate(punti))

    tacche = [lo + (hi - lo) * k / 4 for k in range(5)]
    return {
        "w": larghezza, "h": altezza, "sx": sx, "sx_testo": sx - 4, "dx": larghezza - dx,
        "y_etichette": altezza - giu + 16,
        "rilevato": linea(lambda p: p["misura"].misurato),
        "nominale": linea(lambda p: p["misura"].nominale),
        "sup": linea(lambda p: p["sup"]), "inf": linea(lambda p: p["inf"]),
        "punti": [{"x": f"{x(i)}", "y": f"{y(p['misura'].misurato)}", "fuori": p["misura"].fuori, "id": p["report"].pk,
                   "testo": f"{p['report'].seriale or p['report'].file} · {p['misura'].misurato:.4f}"}
                  for i, p in enumerate(punti)],
        "tacche": [{"y": f"{y(v)}", "v": f"{v:.4f}".replace(".", ",")} for v in tacche],
        "raggio": "4.5" if n <= 40 else ("3" if n <= 120 else "2"),
        "etichette": [{"x": f"{x(i)}", "t": (p["report"].seriale or "")[:12]} for i, p in enumerate(punti)]
        if n <= 30 else [],
    }


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
    qs = ReportCMM.objects.filter(pn=pn, righe__gt=0)
    return {
        "n": qs.count(), "con_fuori": qs.filter(fuori__gt=0).count(), "ultimi": list(qs.order_by("-data", "-id")[:8]),
        "cartella": CartellaReportCMM.objects.filter(pn=pn).order_by("-letta_il").first(), "attivo": attivo(),
    }


def report_dell_op(titolo: str) -> list[ReportCMM]:
    return list(ReportCMM.objects.filter(op__iexact=titolo, righe__gt=0).order_by("-data", "-id")[:50]) if titolo else []


def conteggi_per_pn() -> dict[str, dict]:
    """``{pn: {"n": report, "con_fuori": report con quote fuori}}`` per l'elenco dei P/N (una query)."""
    from django.db.models import Count, Q

    return {
        r["pn"]: {"n": r["n"], "con_fuori": r["con_fuori"]}
        for r in ReportCMM.objects.filter(righe__gt=0).values("pn")
        .annotate(n=Count("id"), con_fuori=Count("id", filter=Q(fuori__gt=0)))
    }
