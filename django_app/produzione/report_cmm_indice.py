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


# --- Analisi quote (pagina interattiva) ----------------------------------------------------------------

LIMITE_REPORT = 800


def _round(v):
    return None if v is None else round(float(v), 6)


def dati_programma(pn: str, prog: str, da: date | None = None, a: date | None = None,
                   limite: int = LIMITE_REPORT) -> dict:
    """Tutte le misure del programma, compatte, per la pagina «Analisi quote».

    ``report``: ``[id, S/N, OP, data ISO, file, n fuori]`` dal più vecchio (al massimo ``limite``, i più recenti);
    ``quote``: ``{id, nome, sezione, tipo, nominale}`` nell'ordine del report più recente;
    ``valori[i]``: per la quota i, ``[indice report, rilevato, tol+, tol-, fuori 0/1, fuori di, da verificare 0/1]``.
    """
    qs = ReportCMM.objects.filter(pn=pn, programma_base=prog, righe__gt=0)
    if da:
        qs = qs.filter(data__gte=da)
    if a:
        qs = qs.filter(data__lte=a)
    totale = qs.count()
    righe = list(qs.order_by("-data", "-id").values_list("id", "seriale", "op", "data", "file", "fuori")[:limite])[::-1]
    indice = {r[0]: i for i, r in enumerate(righe)}
    quote: dict[str, dict] = {}
    valori: dict[str, list] = {}
    if righe:
        misure = MisuraCMM.objects.filter(report__pn=pn, report__programma_base=prog, report__righe__gt=0)
        primo = righe[0][3]
        if primo:
            misure = misure.filter(report__data__gte=primo)
        if a:
            misure = misure.filter(report__data__lte=a)
        for rid, chiave, nom, nome, sezione, tipo, ind, x, ts, ti, fuori, fdi, dv in misure.values_list(
                "report_id", "chiave", "nominale", "nome", "sezione", "tipo", "indice", "misurato", "tol_sup",
                "tol_inf", "fuori", "fuori_di", "da_verificare").order_by("report__data", "report_id", "indice"):
            ri = indice.get(rid)
            if ri is None:
                continue
            k = id_quota(chiave, nom)
            q = quote.get(k)
            if q is None:
                q = quote[k] = {"id": k, "nominale": round(nom, 6)}
                valori[k] = []
            q.update(nome=nome, sezione=sezione, tipo=tipo, ordine=ind, ultimo=ri)
            valori[k].append([ri, _round(x), _round(ts), _round(ti), 1 if fuori else 0, _round(fdi), 1 if dv else 0])
    # Ordine delle righe nel report più recente che ha la quota (le quote sparite finiscono dove stavano).
    elenco = sorted(quote.values(), key=lambda q: (q["ordine"], q["nome"]))
    for q in elenco:
        q.pop("ultimo", None)
    return {
        "pn": pn, "prog": prog, "totale": totale, "limite": limite, "tagliati": max(0, totale - len(righe)),
        "report": [[r[0], r[1] or r[4], r[2], r[3].isoformat() if r[3] else "", r[4], r[5]] for r in righe],
        "quote": elenco,
        "valori": [valori[q["id"]] for q in elenco],
    }


def unilaterale(nominale: float, lsl: float, usl: float) -> bool:
    """Forma, posizione, concentricità…: nominale 0 e limite inferiore 0, conta solo il superiore."""
    return abs(nominale) < 1e-12 and abs(lsl) < 1e-12 and usl > 0


def usata(x: float, nominale: float, lsl: float, usl: float) -> float | None:
    """Tolleranza usata: 0 = ideale, ±1 = limite. Unilaterali: rilevato / limite superiore; le altre dal centro."""
    if unilaterale(nominale, lsl, usl):
        return x / usl
    banda = usl - lsl
    return (x - (usl + lsl) / 2) / (banda / 2) if banda > 0 else None


def statistiche(punti: list[tuple[float, float, float]], nominale: float | None = None) -> dict:
    """``punti`` = ``[(rilevato, limite inferiore, limite superiore)]`` dal più vecchio.

    Media, deviazione standard (campione), Cp e Cpk sui limiti dell'ultima misura (servono almeno 5 punti),
    tolleranza usata dall'ultima misura (``u``, vedi ``usata``). Con il nominale, una quota unilaterale
    (nominale 0, limite inferiore 0) ha Cpk = (limite superiore − media) / 3σ e nessun Cp."""
    n = len(punti)
    if not n:
        return {"n": 0}
    xs = [p[0] for p in punti]
    media = sum(xs) / n
    sd = (sum((x - media) ** 2 for x in xs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    x, lsl, usl = punti[-1]
    banda = usl - lsl
    uni = nominale is not None and unilaterale(nominale, lsl, usl)
    out = {"n": n, "media": media, "sd": sd, "min": min(xs), "max": max(xs), "ultimo": x, "cp": None, "cpk": None,
           "u": usata(x, nominale, lsl, usl) if nominale is not None
           else ((x - (usl + lsl) / 2) / (banda / 2) if banda > 0 else None)}
    if n >= 5 and sd > 0 and banda > 0:
        if uni:
            out["cpk"] = (usl - media) / (3 * sd)
        else:
            out["cp"] = banda / (6 * sd)
            out["cpk"] = min(usl - media, media - lsl) / (3 * sd)
    return out


def quote_critiche(pn: str, ultimi: int = 30, quante: int = 6) -> list[dict]:
    """Le quote da guardare del P/N: sugli ultimi ``ultimi`` report di ogni programma, prima quelle fuori
    nell'ultimo report, poi Cpk sotto 1,33 dal peggiore. Per il riquadro della scheda P/N."""
    out = []
    for p in programmi_del_pn(pn):
        d = dati_programma(pn, p["programma_base"], limite=ultimi)
        if not d["report"]:
            continue
        ultimo = len(d["report"]) - 1
        for q, vals in zip(d["quote"], d["valori"]):
            punti = [(v[1], q["nominale"] + v[3], q["nominale"] + v[2]) for v in vals if v[1] is not None]
            s = statistiche(punti, q["nominale"])
            fuori_ultimo = bool(vals and vals[-1][0] == ultimo and vals[-1][4])
            if fuori_ultimo or (s.get("cpk") is not None and s["cpk"] < 1.33):
                out.append({"prog": p["programma_base"], "quota": q, "fuori_ultimo": fuori_ultimo,
                            "n_fuori": sum(v[4] for v in vals), "n": len(vals), **{k: s.get(k) for k in ("cpk", "u")},
                            "u_abs": abs(s["u"]) if s.get("u") is not None else None})
    out.sort(key=lambda r: (not r["fuori_ultimo"], r["cpk"] if r["cpk"] is not None else 9))
    return out[:quante]
