"""Dati delle pagine «Report CMM» e «Confronto report»: una funzione per pagina, usata da vista, export e test.

Le quote si identificano con ``id_quota`` (nome + nominale) e, nel confronto, si allineano anche fra programmi
diversi con le unioni fatte in Analisi quote (``AliasQuotaCMM``)."""
from __future__ import annotations

from datetime import date

from django.db.models import Q

from .models import AliasQuotaCMM, ReportCMM
from .report_cmm_indice import analisi_pn, id_quota, report_primo_articolo, usata

MAX_CONFRONTO = 6
SOGLIA_CAMBIO = 0.20  # «cambia»: differenza fra primo e ultimo oltre il 20% della tolleranza
AL_LIMITE = 0.80      # tolleranza usata oltre l'80%


def _ordine(r: ReportCMM):
    return (r.data or date.min, r.id)


def stessi_programma(report: ReportCMM):
    """Report validi dello stesso P/N e programma (base), dal più vecchio."""
    return (ReportCMM.objects.filter(pn=report.pn, programma_base=report.programma_base, righe__gt=0, escluso=False)
            .order_by("data", "id"))


def vicini(report: ReportCMM) -> tuple[ReportCMM | None, ReportCMM | None]:
    """Il pezzo prima e il pezzo dopo nello stesso programma (per data, poi per lettura)."""
    qs = stessi_programma(report).exclude(pk=report.pk)
    d = report.data or date.min
    prima = qs.filter(Q(data__lt=d) | Q(data=d, id__lt=report.id)).order_by("-data", "-id").first()
    dopo = qs.filter(Q(data__gt=d) | Q(data=d, id__gt=report.id)).order_by("data", "id").first()
    return prima, dopo


def _posizione(u: float | None) -> float | None:
    """Tolleranza usata (−1 … +1 ai limiti) → posizione 0–100 nella barra, con la tolleranza fra 15 e 85."""
    if u is None:
        return None
    return max(1.0, min(99.0, 50 + u * 35))


def righe_report(report: ReportCMM) -> dict:
    """Tutte le quote del report con tolleranza usata, posizione nella barra, differenza dal pezzo prima e Cpk
    della quota (ultimi 30 pezzi del programma). Prima le fuori, poi quelle da verificare, poi l'ordine del report."""
    prima, dopo = vicini(report)
    prec = {}
    if prima:
        prec = {id_quota(m.chiave, m.nominale): m.misurato for m in prima.misure.all()}
    analisi = {a["quota"]["id"]: a for a in analisi_pn(report.pn) if a["prog"] == report.programma_base}
    righe = []
    for m in report.misure.all():
        qid = id_quota(m.chiave, m.nominale)
        lsl, usl = m.nominale + m.tol_inf, m.nominale + m.tol_sup
        u = usata(m.misurato, m.nominale, lsl, usl)
        a = analisi.get(qid)
        righe.append({
            "m": m, "id": qid, "u": u, "u_pct": round(abs(u) * 100) if u is not None else None,
            "pos": _posizione(u), "limite": u is not None and abs(u) > AL_LIMITE and not m.fuori,
            "delta": (m.misurato - prec[qid]) if qid in prec else None,
            "cpk": a["cpk"] if a else None, "deriva": bool(a and a["deriva"]),
        })
    righe.sort(key=lambda r: (not r["m"].fuori, not r["m"].da_verificare, r["m"].indice))
    conta = {
        "tutte": len(righe), "fuori": sum(r["m"].fuori for r in righe), "limite": sum(r["limite"] for r in righe),
        "cambiate": sum(1 for r in righe if r["delta"] is not None and r["u"] is not None and _banda(r["m"])
                        and abs(r["delta"]) / _banda(r["m"]) > SOGLIA_CAMBIO),
    }
    return {"righe": righe, "prima": prima, "dopo": dopo, "conta": conta}


def _banda(m) -> float:
    return (m.tol_sup - m.tol_inf) or 0.0


# --- Confronto -------------------------------------------------------------------------------------------

def report_da_confrontare(ids) -> list[ReportCMM]:
    """I report scelti (al massimo ``MAX_CONFRONTO``, senza doppioni), dal più vecchio."""
    puliti = []
    for v in ids:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n not in puliti:
            puliti.append(n)
    scelti = list(ReportCMM.objects.filter(pk__in=puliti[:MAX_CONFRONTO]))
    return sorted(scelti, key=_ordine)


def proposte(report: ReportCMM) -> dict[str, list[int]]:
    """I confronti pronti partendo da un report: stesso S/N in tutte le fasi, primo articolo dell'OP contro
    gli ultimi pezzi dello stesso programma, pezzo prima / pezzo dopo."""
    out = {}
    if report.seriale:
        stesso = list(ReportCMM.objects.filter(pn=report.pn, seriale=report.seriale, righe__gt=0)
                      .order_by("data", "id").values_list("id", flat=True)[:MAX_CONFRONTO])
        if len(stesso) > 1:
            out["fasi"] = stesso
    primo = report_primo_articolo(report.op) if report.op else None
    if primo:
        ultimi = list(stessi_programma(primo).exclude(pk=primo.pk).order_by("-data", "-id")
                      .values_list("id", flat=True)[:3])
        if ultimi:
            out["primo"] = [primo.pk] + ultimi[::-1]
    prima, dopo = vicini(report)
    vic = [r.pk for r in (prima, report, dopo) if r]
    if len(vic) > 1:
        out["vicini"] = vic
    return out


def _mappa_alias(pn: str) -> dict[tuple[str, str], tuple[str, str]]:
    return {(a.prog_origine, a.quota_origine): (a.prog_destinazione, a.quota_destinazione)
            for a in AliasQuotaCMM.objects.filter(pn=pn)}


def confronta(reports: list[ReportCMM], solo_cambiate: bool = False) -> dict:
    """Le quote dei report affiancate. Una riga per quota (nome + nominale); le quote unite in Analisi quote
    finiscono nella stessa riga anche fra programmi diversi. Per ogni riga: i valori, se sono fuori, la
    differenza fra l'ultimo e il primo report che la misurano e la stessa in percentuale della tolleranza."""
    alias = {}
    for pn in {r.pn for r in reports}:
        alias.update({(pn,) + k: v for k, v in _mappa_alias(pn).items()})
    righe: dict[tuple, dict] = {}
    for col, r in enumerate(reports):
        for m in r.misure.all():
            qid = id_quota(m.chiave, m.nominale)
            dest = alias.get((r.pn, r.programma_base, qid))
            chiave = dest[1] if dest else qid
            riga = righe.get(chiave)
            if riga is None:
                riga = righe[chiave] = {"id": chiave, "nome": m.nome, "nominale": m.nominale, "lsl": m.nominale + m.tol_inf,
                                        "usl": m.nominale + m.tol_sup, "ordine": (col, m.indice), "valori": [None] * len(reports)}
            if riga["valori"][col] is None:
                riga["valori"][col] = {"x": m.misurato, "fuori": m.fuori,
                                       "pos": _posizione(usata(m.misurato, m.nominale, m.nominale + m.tol_inf, m.nominale + m.tol_sup))}
    out = []
    for riga in righe.values():
        presenti = [v for v in riga["valori"] if v]
        banda = riga["usl"] - riga["lsl"]
        delta = presenti[-1]["x"] - presenti[0]["x"] if len(presenti) > 1 else None
        riga["delta"] = delta
        riga["delta_pct"] = round(delta / banda * 100) if delta is not None and banda > 0 else None
        riga["cambia"] = riga["delta_pct"] is not None and abs(riga["delta_pct"]) > SOGLIA_CAMBIO * 100
        riga["fuori"] = any(v["fuori"] for v in presenti)
        out.append(riga)
    out.sort(key=lambda r: (not r["fuori"], not r["cambia"], r["ordine"]))
    totale = len(out)
    if solo_cambiate:
        out = [r for r in out if r["cambia"] or r["fuori"]]
    return {"righe": out, "totale": totale, "cambiate": sum(1 for r in righe.values() if r["cambia"])}


# --- Scheda OP: pezzi × fasi -----------------------------------------------------------------------------

MAX_REPORT_OP = 1500


def chiave_seriale(sn: str) -> str:
    """S/N confrontabile: solo lettere e cifre, maiuscolo (come «ultima misura per S/N»)."""
    import re

    return re.sub(r"[^A-Z0-9]", "", str(sn or "").upper())


def matrice_op(titolo: str, anomalie_sn: dict[str, int] | None = None) -> dict:
    """I pezzi (S/N) dell'OP per fase di controllo (programma CMM senza revisione), dai report CMM letti.

    Le fasi vanno nell'ordine in cui compaiono la prima volta. In ogni cella l'ultimo report valido di quel
    pezzo in quella fase: «fuori» (quote fuori), «limite» (una quota oltre l'80% della tolleranza), «ok»;
    ``n`` > 1 = rimisurato. I pezzi dal più recente."""
    from .models import MisuraCMM

    anomalie_sn = anomalie_sn or {}
    righe = list(ReportCMM.objects.filter(op__iexact=titolo, righe__gt=0)
                 .order_by("data", "id").values("id", "seriale", "programma_base", "data", "fuori", "escluso")[:MAX_REPORT_OP])
    validi = [r for r in righe if not r["escluso"]]
    massimo: dict[int, float] = {}
    for m in MisuraCMM.objects.filter(report_id__in=[r["id"] for r in validi]).values_list(
            "report_id", "misurato", "nominale", "tol_sup", "tol_inf").iterator():
        u = usata(m[1], m[2], m[2] + m[4], m[2] + m[3])
        if u is not None and abs(u) > massimo.get(m[0], 0):
            massimo[m[0]] = abs(u)
    fasi: list[str] = []
    for r in validi:
        f = r["programma_base"] or "—"
        if f not in fasi:
            fasi.append(f)
    pezzi: dict[str, dict] = {}
    for r in validi:
        chiave = chiave_seriale(r["seriale"]) or f"#{r['id']}"
        p = pezzi.setdefault(chiave, {"sn": r["seriale"] or "senza S/N", "celle": {}, "ultimo": r["data"], "anomalie": anomalie_sn.get(chiave, 0)})
        f = r["programma_base"] or "—"
        prima = p["celle"].get(f)
        stato = "fuori" if r["fuori"] else ("limite" if massimo.get(r["id"], 0) > AL_LIMITE else "ok")
        p["celle"][f] = {"id": r["id"], "stato": stato, "fuori": r["fuori"], "data": r["data"], "n": (prima["n"] + 1) if prima else 1}
        if r["data"] and (not p["ultimo"] or r["data"] >= p["ultimo"]):
            p["ultimo"] = r["data"]
    elenco = sorted(pezzi.values(), key=lambda p: (p["ultimo"] or date.min, p["sn"]), reverse=True)
    for p in elenco:
        p["riga"] = [p["celle"].get(f) for f in fasi]
        p["con_fuori"] = any(c and c["stato"] == "fuori" for c in p["riga"])
        p["completo"] = bool(fasi) and p["riga"][-1] is not None and not p["con_fuori"]
    return {
        "fasi": fasi, "pezzi": elenco, "esclusi": len(righe) - len(validi), "troncato": len(righe) >= MAX_REPORT_OP,
        "conta": {"pezzi": len(elenco), "con_fuori": sum(p["con_fuori"] for p in elenco),
                  "completi": sum(p["completo"] for p in elenco), "anomalie": sum(1 for p in elenco if p["anomalie"])},
    }


def cronologia_op(titolo: str, documenti, quanti: int = 12) -> list[dict]:
    """Cosa è successo sull'OP, dal più recente: report CMM (con le quote fuori) e documenti registrati."""
    eventi = []
    for r in ReportCMM.objects.filter(op__iexact=titolo, righe__gt=0).order_by("-data", "-id")[:quanti]:
        eventi.append({"quando": r.data, "tipo": "fuori" if r.fuori else "ok", "id": r.id,
                       "testo": f"{r.seriale or r.file} · {r.programma_base or '—'}",
                       "esito": f"{r.fuori} quot{'a' if r.fuori == 1 else 'e'} fuori" if r.fuori else "tutto in tolleranza"})
    for d in documenti:
        eventi.append({"quando": d.creato_il.date() if d.creato_il else d.data, "tipo": "documento", "id": None,
                       "testo": f"{d.tipo.etichetta}{' ' + d.titolo if d.titolo else ''}{' rev. ' + d.revisione if d.revisione else ''}",
                       "esito": "documento registrato"})
    eventi.sort(key=lambda e: e["quando"] or date.min, reverse=True)
    return eventi[:quanti]


# --- Pagina del pezzo (S/N) ------------------------------------------------------------------------------

MAX_FASI_PEZZO = 12


def report_del_pezzo(pn: str, sn: str) -> list[ReportCMM]:
    """Tutti i report CMM del pezzo (P/N + S/N, confronto su lettere e cifre), dal più vecchio, esclusi compresi."""
    chiave = chiave_seriale(sn)
    if not chiave:
        return []
    import re

    cifre = re.findall(r"\d+", chiave)
    filtro = cifre[-1][-4:] if cifre else chiave[-3:]      # le ultime cifre restano uguali anche con trattini e spazi
    candidati = ReportCMM.objects.filter(pn=pn, righe__gt=0, seriale__icontains=filtro).order_by("data", "id")
    return [r for r in candidati if chiave_seriale(r.seriale) == chiave]


def pezzo(pn: str, sn: str, solo: str = "") -> dict | None:
    """La pagina del pezzo: i suoi report (una colonna per report, al massimo gli ultimi ``MAX_FASI_PEZZO``), le
    quote allineate come nel confronto, la storia con le anomalie, l'OP e se è il primo articolo del FAI."""
    from core import ordini_produzione as op_db

    reports = report_del_pezzo(pn, sn)
    if not reports:
        return None
    validi = [r for r in reports if not r.escluso]
    colonne = (validi or reports)[-MAX_FASI_PEZZO:]
    dati = confronta(colonne)
    righe = dati["righe"]
    if solo == "fuori":
        righe = [r for r in righe if r["fuori"]]
    elif solo == "cambiate":
        righe = [r for r in righe if r["cambia"]]
    else:
        solo = ""
    ultimo = colonne[-1]
    ops = list(dict.fromkeys(r.op for r in reports if r.op))
    primi = {r.op: report_primo_articolo(r.op) for r in reports if r.op}
    primo_articolo = any(p and p.pk == r.pk for r in reports for p in [primi.get(r.op)])
    anomalie = op_db.anomalie_del_seriale(ultimo.seriale) if op_db.disponibile() else []
    storia = []
    fasi_viste: dict[str, int] = {}
    for r in reports:
        fasi_viste[r.programma_base] = fasi_viste.get(r.programma_base, 0) + 1
        storia.append({"quando": r.data, "id": r.id, "tipo": "escluso" if r.escluso else ("fuori" if r.fuori else "ok"),
                       "testo": f"{r.programma_base or '—'}{' · rimisura' if fasi_viste[r.programma_base] > 1 else ''}",
                       "esito": ("escluso dall'analisi: " + r.escluso_motivo) if r.escluso else
                       (f"{r.fuori} quot{'a' if r.fuori == 1 else 'e'} fuori" if r.fuori else "tutto in tolleranza"),
                       "op": r.op})
    storia.reverse()
    stato = "fuori" if ultimo.fuori else "ok"
    return {
        "pn": pn, "sn": ultimo.seriale or sn, "reports": reports, "colonne": colonne, "righe": righe, "totale": dati["totale"],
        "cambiate": dati["cambiate"], "n_fuori": sum(1 for r in dati["righe"] if r["fuori"]), "solo": solo, "ops": ops,
        "primo_articolo": primo_articolo, "anomalie": anomalie, "anomalie_aperte": sum(a["aperta"] for a in anomalie),
        "storia": storia, "stato": stato, "ultimo": ultimo, "esclusi": len(reports) - len(validi),
        "nascosti": max(0, len(validi or reports) - MAX_FASI_PEZZO),
    }
