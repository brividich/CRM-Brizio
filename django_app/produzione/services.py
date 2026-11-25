"""Schede dell'OP e del P/N: quello che gli altri moduli sanno, letto dove sta.

Il P/N è l'articolo principale: ha più OP, il KICK-OFF, i programmi e i FAI. Il FAI è del
P/N, non del singolo OP: la scheda dell'OP ne mostra lo stato e rimanda alla scheda del P/N.

- dati dell'OP: tabella ``ordini_produzione`` (``core/ordini_produzione.py``);
- FAI: Registro FAI, legati al P/N dell'articolo;
- programmi CAM e CMM: righe del KICK-OFF del P/N;
- documenti di produzione: ``DocumentoOP`` di questa app;
- anomalie: conteggi di Gestione anomalie, con il link.

FAI e KICK-OFF rispettano i permessi del modulo KICK-OFF: chi non li ha non li vede.
"""
from __future__ import annotations

from collections import Counter
from urllib.parse import urlencode

from django.urls import reverse

from core import ordini_produzione as op_db
from tasks.identity import normalize_part_number

from . import report_cmm_indice
from .models import DocumentoOP


def _vede_kickoff(request) -> bool:
    from tasks.access import has_task_permission

    return has_task_permission(request, "tasks_view")


def _fai_visibili(request):
    from tasks.views.fai import _fai_visibili as visibili

    return visibili(request)


def url_anomalie(titolo: str) -> str:
    return f"{reverse('gestione_anomalie_page')}?{urlencode({'op': titolo, 'filter': 'tutti'})}"


def righe_elenco(request, testo: str = "", stato: str = "") -> list[dict]:
    ops = op_db.elenco(testo, stato)
    documenti = Counter(t.lower() for t in DocumentoOP.objects.values_list("op", flat=True))
    fai = fai_per_pn(request) if _vede_kickoff(request) else {}
    anomalie = op_db.anomalie_aperte_per_op()
    for op in ops:
        chiave = op["op"].lower()
        op["pn_norm"] = normalize_part_number(op["pn"])
        op["url_pn"] = url_pn(op["pn_norm"]) if op["pn_norm"] else ""
        op["n_documenti"] = documenti.get(chiave, 0)
        op["n_fai"] = len(fai.get(op["pn_norm"], {}).get("fai", [])) if op["pn_norm"] else 0
        op["n_anomalie_aperte"] = anomalie.get(chiave, 0)
    return ops


def fai_per_pn(request) -> dict[str, dict]:
    """FAI visibili per P/N normalizzato, annullati esclusi, con la situazione dell'articolo.

    Stessa lettura del Registro FAI (``righe_registro``): una riga per articolo col FAI più
    recente. Un P/N con più clienti ha più articoli: vale la situazione peggiore.
    """
    from tasks.models import FaiFase
    from tasks.services.fai import righe_registro

    records = list(_fai_visibili(request).select_related("articolo", "stato"))
    per_pn: dict[str, dict] = {}
    for f in records:
        if f.stato.fase == FaiFase.ANNULLATO:
            continue
        per_pn.setdefault(normalize_part_number(f.articolo.part_number), {"fai": [], "righe": []})["fai"].append(f)
    for riga in righe_registro(records):
        voce = per_pn.get(normalize_part_number(riga["articolo"].part_number))
        if voce is not None:
            voce["righe"].append(riga)
    for voce in per_pn.values():
        voce["situazione"] = _peggiore([r["situazione"] for r in voce["righe"]])
    return per_pn


_GRAVITA = {"da_ripetere": 0, "da_verificare": 1, "in_corso": 2, "date_mancanti": 3, "in_regola": 4}


def _peggiore(situazioni: list):
    return min(situazioni, key=lambda s: _GRAVITA.get(s.codice, 9)) if situazioni else None


def url_pn(pn: str, sezione: str = "") -> str:
    """Indirizzo stabile della scheda del P/N (``/produzione/pn/<P/N>/``), con la sezione se serve."""
    url = reverse("produzione:pn", args=[pn])
    return f"{url}?{urlencode({'sez': sezione})}" if sezione else url


def url_nuovo_fai(pn: str, op: str = "") -> str:
    parametri = {"op": op, "pn": pn} if op else {"pn": pn}
    return f"{reverse('tasks:fai_nuovo')}?{urlencode(parametri)}"


def righe_pn(request, testo: str = "") -> list[dict]:
    """Una riga per P/N degli OP: quanti OP, l'ultimo, le anomalie aperte e la situazione FAI.

    La ricerca sceglie i P/N (basta un OP che corrisponde), ma le righe contano tutti i loro OP.
    """
    ops = op_db.elenco()
    if testo:
        trovati = {normalize_part_number(o["pn"]) for o in op_db.elenco(testo)}
        ops = [o for o in ops if normalize_part_number(o["pn"]) in trovati]
    fai = fai_per_pn(request) if _vede_kickoff(request) else {}
    anomalie = op_db.anomalie_aperte_per_op()
    cmm = report_cmm_indice.conteggi_per_pn()
    righe: dict[str, dict] = {}
    for op in ops:  # dal più recente
        pn = normalize_part_number(op["pn"])
        if not pn:
            continue
        riga = righe.get(pn)
        if riga is None:
            voce = fai.get(pn, {})
            riga = righe[pn] = {
                "pn": pn, "url": url_pn(pn), "ultimo_op": op, "capocommessa": op["capocommessa"],
                "n_op": 0, "n_anomalie_aperte": 0,
                "n_fai": len(voce.get("fai", [])), "situazione": voce.get("situazione"),
                "cmm": cmm.get(pn), "url_quote": f"{reverse('produzione:pn_quote')}?{urlencode({'pn': pn})}",
            }
        riga["n_op"] += 1
        riga["n_anomalie_aperte"] += anomalie.get(op["op"].lower(), 0)
    return list(righe.values())


MANCA_PN = (
    ("anomalie", "Con anomalie aperte"),
    ("fai", "Senza FAI"),
    ("scadenza", "FAI da ripetere o verificare"),
)


def filtra_manca_pn(righe: list[dict], manca: str) -> list[dict]:
    if manca == "anomalie":
        return [r for r in righe if r["n_anomalie_aperte"]]
    if manca == "fai":
        return [r for r in righe if not r["n_fai"]]
    if manca == "scadenza":
        return [r for r in righe if r["situazione"] and r["situazione"].codice in ("da_ripetere", "da_verificare")]
    return righe


def conteggi_manca_pn(righe: list[dict], vede_kickoff: bool) -> list[dict]:
    return [
        {"chiave": k, "etichetta": e, "n": len(filtra_manca_pn(righe, k))}
        for k, e in MANCA_PN if k == "anomalie" or vede_kickoff
    ]


def _kickoff_del_pn(request, pn_norm: str) -> tuple[list, list]:
    from tasks.access import scoped_projects_queryset
    from tasks.models import ProjectTechRef, TechRefKind

    visibili = scoped_projects_queryset(request).filter(part_number__iexact=pn_norm)
    progetti = list(visibili.order_by("-id")[:10])
    programmi = list(
        ProjectTechRef.objects.filter(kind__in=[TechRefKind.CAM, TechRefKind.CMM], project__in=visibili)
        .select_related("project", "assigned_to").order_by("kind", "-id")
    )
    return progetti, programmi


def scheda(request, op: dict) -> dict:
    titolo, pn = op["op"], op.get("pn") or ""
    pn_norm = normalize_part_number(pn)
    kickoff = _vede_kickoff(request)

    fai_pn, situazione, programmi, progetti = [], None, [], []
    if kickoff and pn_norm:
        fai_pn, situazione, _ = _fai_del_pn(request, pn_norm)
        progetti, programmi = _kickoff_del_pn(request, pn_norm)

    dati = {
        "op": op,
        "documenti": list(DocumentoOP.objects.filter(op__iexact=titolo).select_related("tipo", "creato_da")),
        "vede_kickoff": kickoff,
        "fai_pn": fai_pn,
        "situazione_fai": situazione,
        "programmi": programmi,
        "progetti": progetti,
        "anomalie": op_db.conta_anomalie(op),
        "url_anomalie": url_anomalie(titolo),
        "url_nuovo_fai": url_nuovo_fai(pn_norm, titolo),
        "url_pn": url_pn(pn_norm) if pn_norm else "",
        "report_cmm": report_cmm_indice.report_dell_op(titolo),
        "url_quote": f"{reverse('produzione:pn_quote')}?{urlencode({'pn': pn_norm})}" if pn_norm else "",
        "altri_op": [o for o in (op_db.elenco(pn) if pn else []) if o["id"] != op["id"] and normalize_part_number(o["pn"]) == pn_norm][:10],
    }
    dati["passi"] = percorso(request, dati)
    dati["prossimo"] = prossimo_passo(dati["passi"])
    return dati


def _fai_del_pn(request, pn_norm: str) -> tuple[list, object, list]:
    """Tutti i FAI del P/N dal più recente (annullati compresi), la situazione e le righe per articolo."""
    from tasks.services.fai import righe_registro

    fai = list(_fai_visibili(request).select_related("articolo", "stato")
               .filter(articolo__part_number__iexact=pn_norm).order_by("-id"))
    righe = righe_registro(fai)
    return fai, _peggiore([r["situazione"] for r in righe]), righe


def fai_cmm(op: str, pn: str = "") -> dict | None:
    """Report CMM del primo articolo dell'OP del FAI e capacità sui pezzi dopo (riquadro di scheda FAI e P/N)."""
    rep = report_cmm_indice.report_primo_articolo(op)
    if rep is None:
        return None
    return {"report": rep, "righe": report_cmm_indice.capacita_dopo(rep),
            "url_analisi": f"{reverse('produzione:pn_quote')}?{urlencode({'pn': rep.pn, 'prog': rep.programma_base, 'r': rep.pk})}"}


def collega_programmi_cmm(pn_norm: str, programmi: list) -> None:
    """Righe CMM del KICK-OFF -> ``url_quote``: andamento del programma dei report che contiene quel codice."""
    righe_cmm = [r for r in programmi if r.kind == "CMM" and (r.code or "").strip()]
    if not righe_cmm:
        return
    nomi = [p["programma_base"] for p in report_cmm_indice.programmi_del_pn(pn_norm)]
    for r in righe_cmm:
        codice = report_cmm_indice.programma_base(r.code).upper()
        trovato = next((n for n in nomi if codice and (codice in n.upper() or n.upper() in codice)), "")
        if trovato:
            r.url_quote = f"{reverse('produzione:pn_quote')}?{urlencode({'pn': pn_norm, 'prog': trovato})}"


def scheda_pn(request, pn: str) -> dict | None:
    """Scheda del P/N: i suoi OP, KICK-OFF, programmi e FAI. ``None`` se nessun OP ha quel P/N."""
    pn_norm = normalize_part_number(pn)
    if not pn_norm:
        return None
    ops = [o for o in op_db.elenco(pn_norm) if normalize_part_number(o["pn"]) == pn_norm]
    if not ops:
        return None
    documenti = Counter(t.lower() for t in DocumentoOP.objects.values_list("op", flat=True))
    anomalie = op_db.anomalie_aperte_per_op()
    for o in ops:
        o["n_documenti"] = documenti.get(o["op"].lower(), 0)
        o["n_anomalie_aperte"] = anomalie.get(o["op"].lower(), 0)
    kickoff = _vede_kickoff(request)
    fai, situazione, progetti, programmi, articoli = [], None, [], [], []
    if kickoff:
        fai, situazione, articoli = _fai_del_pn(request, pn_norm)
        progetti, programmi = _kickoff_del_pn(request, pn_norm)
    dati = {
        "pn": pn_norm,
        "ops": ops,
        "ultimo_op": ops[0],
        "vede_kickoff": kickoff,
        "fai_pn": fai,
        "situazione_fai": situazione,
        "articoli": articoli,
        "progetti": progetti,
        "programmi": programmi,
        "url_nuovo_fai": url_nuovo_fai(pn_norm),
        "n_anomalie_aperte": sum(o["n_anomalie_aperte"] for o in ops),
        "senza_documenti": sum(1 for o in ops if not o["n_documenti"]),
        "report_cmm": report_cmm_indice.riepilogo_pn(pn_norm),
        "quote_critiche": report_cmm_indice.quote_critiche(pn_norm),
        "fai_cmm": next((x for x in (fai_cmm(f.op) for f in fai[:5] if f.op) if x), None) if fai else None,
    }
    collega_programmi_cmm(pn_norm, programmi)
    passi = _passi_kickoff(pn_norm, progetti, programmi) if kickoff else []
    if kickoff:
        passi.append(_passo_fai(fai, situazione, dati["url_nuovo_fai"]))
    passi.append(_passo_ops(dati))
    in_tabella = {"kickoff": len(progetti) > 1, "programmi": bool(programmi), "fai": bool(fai), "op": True}
    for n, p in enumerate(passi, 1):
        p["n"], p["in_tabella"] = n, in_tabella[p["chiave"]]
    dati["passi"] = passi
    dati["prossimo"] = prossimo_passo(passi)
    dati["da_fare"] = da_fare_pn(dati)
    dati["pezzi_mese"] = pezzi_per_mese(pn_norm)
    return dati


SEZIONI_PN = (("", "Panoramica"), ("op", "OP"), ("report", "Report CMM"), ("programmi", "Programmi"), ("fai", "FAI"))


def da_fare_pn(dati: dict) -> list[dict]:
    """Una sola lista per la Panoramica, dalla più urgente: quote fuori nell'ultimo report o in deriva, anomalie
    aperte, OP senza documenti. I passi del percorso (KICK-OFF, programmi, FAI) stanno nella striscia sopra e non si
    ripetono qui. Ogni voce: gravità, testo, dove, azione."""
    voci = []
    for c in dati.get("quote_critiche") or []:
        url = (f"{reverse('produzione:pn_quote')}?{urlencode({'pn': dati['pn'], 'prog': c['prog'], 'q': c['quota']['id']})}")
        if c["fuori_ultimo"]:
            voci.append({"livello": "allerta", "testo": f"{c['quota']['nome']} fuori nell'ultimo report",
                         "dove": f"{c['n_fuori']} volte su {c['n']} · {c['prog']}", "azione": "Andamento", "url": url})
        elif c["deriva"]:
            voci.append({"livello": "dafare", "testo": f"{c['quota']['nome']} in deriva verso il limite",
                         "dove": c["prog"], "azione": "Andamento", "url": url})
    if dati["n_anomalie_aperte"]:
        n = dati["n_anomalie_aperte"]
        op = next((o for o in dati["ops"] if o["n_anomalie_aperte"]), None)
        voci.append({"livello": "allerta", "testo": f"{n} anomali{'a' if n == 1 else 'e'} apert{'a' if n == 1 else 'e'}",
                     "dove": "Gestione anomalie", "azione": "Apri",
                     "url": url_anomalie(op["op"]) if op else ""})
    if dati["senza_documenti"]:
        n = dati["senza_documenti"]
        voci.append({"livello": "attesa", "testo": f"{n} OP senza documenti di produzione", "dove": "sezione OP",
                     "azione": "Vedi", "url": url_pn(dati["pn"], "op")})
    ordine = {"allerta": 0, "dafare": 1, "attesa": 2}
    voci.sort(key=lambda v: ordine.get(v["livello"], 3))
    return voci


def pezzi_per_mese(pn: str, mesi: int = 6) -> list[dict]:
    """Report CMM validi per mese (ultimi ``mesi`` mesi, anche quelli a zero) e quanti con quote fuori."""
    from datetime import date

    from django.db.models import Count, Q
    from django.db.models.functions import TruncMonth

    from .models import ReportCMM

    oggi = date.today()
    inizio = date(oggi.year - (1 if oggi.month <= mesi - 1 else 0), (oggi.month - mesi) % 12 + 1, 1)
    righe = (ReportCMM.objects.filter(pn=pn, righe__gt=0, escluso=False, data__gte=inizio)
             .annotate(mese=TruncMonth("data")).values("mese")
             .annotate(n=Count("id"), fuori=Count("id", filter=Q(fuori__gt=0))))
    per_mese = {(r["mese"].year, r["mese"].month): r for r in righe if r["mese"]}
    nomi = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
    out, a, m = [], inizio.year, inizio.month
    for _ in range(mesi):
        r = per_mese.get((a, m), {})
        out.append({"etichetta": f"{nomi[m - 1]} {str(a)[2:]}", "n": r.get("n", 0), "fuori": r.get("fuori", 0)})
        m += 1
        if m > 12:
            a, m = a + 1, 1
    massimo = max((x["n"] for x in out), default=0) or 1
    for x in out:
        x["h"] = round(x["n"] / massimo * 100)
        x["hf"] = round(x["fuori"] / massimo * 100)
    return out


# --- Filo conduttore: i passi di un OP, nell'ordine in cui si lavora ---------------------------------
# Stati: «fatto», «attesa» (tocca ad altri), «dafare», «allerta». Ogni passo ha al massimo un'azione.

def _passo(chiave, titolo, stato, testo, azione="", url=""):
    return {"chiave": chiave, "titolo": titolo, "stato": stato, "testo": testo, "azione": azione, "url": url}


def percorso(request, dati: dict) -> list[dict]:
    from core.acl_v2 import request_has_permission_code

    from .acl_bootstrap import PERM_DOCUMENTI

    op = dati["op"]
    pn = op.get("pn") or ""
    progetti, programmi = dati["progetti"], dati["programmi"]
    passi = []

    if dati["vede_kickoff"]:
        if not pn:
            passi.append(_passo("kickoff", "KICK-OFF del P/N", "dafare", "L'OP non ha un P/N: senza P/N non si collega al KICK-OFF."))
        else:
            passi += _passi_kickoff(pn, progetti, programmi)

    documenti = dati["documenti"]
    puo = request_has_permission_code(request, PERM_DOCUMENTI)
    if documenti:
        tipi = list(dict.fromkeys(d.tipo.etichetta for d in documenti))
        passi.append(_passo("documenti", "Documenti di produzione", "fatto", ", ".join(tipi) + ".",
                            "Aggiungi documento" if puo else "", "?sez=documenti&aggiungi=1" if puo else ""))
    else:
        passi.append(_passo("documenti", "Documenti di produzione", "dafare", "Nessun documento registrato: ciclo, disegno, DIP, piano di controllo…",
                            "Aggiungi documento" if puo else "", "?sez=documenti&aggiungi=1" if puo else ""))

    if dati["vede_kickoff"]:
        if pn:
            passi.append(_passo_fai(dati["fai_pn"], dati["situazione_fai"], dati["url_nuovo_fai"]))
        else:
            passi.append(_passo("fai", "FAI del P/N", "dafare", "Il FAI è del P/N: senza P/N non si collega."))

    anomalie = dati["anomalie"]
    if anomalie["aperte"]:
        passi.append(_passo("anomalie", "Anomalie", "allerta",
                            f"{anomalie['aperte']} apert{'a' if anomalie['aperte'] == 1 else 'e'} su {anomalie['totale']}.",
                            "Gestisci le anomalie", dati["url_anomalie"]))
    else:
        passi.append(_passo("anomalie", "Anomalie", "fatto",
                            "Tutte chiuse." if anomalie["totale"] else "Nessuna anomalia.",
                            "Vedi le anomalie" if anomalie["totale"] else "", dati["url_anomalie"] if anomalie["totale"] else ""))

    # Il testo del passo si mostra solo se sotto non c'è già una tabella con gli stessi dati.
    in_tabella = {
        "kickoff": len(progetti) > 1,
        "programmi": bool(programmi),
        "documenti": bool(documenti),
        "fai": bool(dati["fai_pn"]),
        "anomalie": False,
    }
    for n, p in enumerate(passi, 1):
        p["n"] = n
        p["in_tabella"] = in_tabella[p["chiave"]]
    return passi


def _passi_kickoff(pn: str, progetti: list, programmi: list) -> list[dict]:
    passi = []
    if progetti:
        passi.append(_passo("kickoff", "KICK-OFF del P/N", "fatto", f"{progetti[0].name} · {progetti[0].get_phase_display()}",
                            "Apri il KICK-OFF", reverse("tasks:project_overview", args=[progetti[0].id])))
    else:
        passi.append(_passo("kickoff", "KICK-OFF del P/N", "dafare", "Nessun KICK-OFF per questo P/N.",
                            "Nuovo KICK-OFF", f"{reverse('tasks:project_create')}?{urlencode({'pn': pn})}"))

    url_prog = reverse("tasks:project_tech_refs", args=[progetti[0].id]) if progetti else ""
    da_fare = [r for r in programmi if r.status == "OPEN"]
    if not programmi:
        passi.append(_passo("programmi", "Programmi CAM e CMM", "dafare",
                            "Nessun programma nel KICK-OFF del P/N." if progetti else "Arrivano dal KICK-OFF: prima crealo.",
                            "Aggiungi nel KICK-OFF" if url_prog else "", url_prog))
    elif da_fare:
        passi.append(_passo("programmi", "Programmi CAM e CMM", "attesa",
                            f"{len(da_fare)} da fare su {len(programmi)}.", "Apri i programmi", url_prog))
    else:
        passi.append(_passo("programmi", "Programmi CAM e CMM", "fatto",
                            f"{len(programmi)} fatt{'o' if len(programmi) == 1 else 'i'}.", "Apri i programmi", url_prog))
    return passi


def _passo_fai(fai: list, situazione, url_nuovo: str) -> dict:
    """Il FAI è del P/N: conta il più recente non annullato, poi la situazione dell'articolo."""
    from tasks.models import FaiFase

    validi = [f for f in fai if not f.stato or f.stato.fase != FaiFase.ANNULLATO]
    if not validi:
        return _passo("fai", "FAI del P/N", "dafare", "Nessun FAI per questo P/N.", "Nuovo FAI", url_nuovo)
    f = validi[0]
    testo = f"{f.piano_numero or 'FAI'}: {f.stato.etichetta if f.stato else 'senza stato'}"
    url_fai = reverse("tasks:fai_scheda", args=[f.id])
    if f.stato is None or f.stato.fase == FaiFase.IN_CORSO:
        return _passo("fai", "FAI del P/N", "attesa", testo + ", in attesa di esito.", "Apri il FAI", url_fai)
    if situazione is not None and situazione.codice == "da_ripetere":
        return _passo("fai", "FAI del P/N", "allerta", f"Da ripetere. {situazione.nota}".strip(), "Nuovo FAI", url_nuovo)
    if f.stato.fase == FaiFase.POSITIVO:
        if situazione is not None and situazione.codice == "da_verificare":
            return _passo("fai", "FAI del P/N", "allerta", f"{testo}. {situazione.nota}", "Apri il FAI", url_fai)
        return _passo("fai", "FAI del P/N", "fatto", testo + ".", "Apri il FAI", url_fai)
    return _passo("fai", "FAI del P/N", "dafare", testo + ".", "Apri il FAI", url_fai)


def _passo_ops(dati: dict) -> dict:
    n, aperte, senza = len(dati["ops"]), dati["n_anomalie_aperte"], dati["senza_documenti"]
    testo = f"{n} OP"
    if senza:
        testo += f", {senza} senza documenti"
    if aperte:
        testo += f", {aperte} anomali{'a' if aperte == 1 else 'e'} apert{'a' if aperte == 1 else 'e'}"
        return _passo("op", "OP del P/N", "allerta", testo + ".")
    return _passo("op", "OP del P/N", "dafare" if senza else "fatto", testo + ".")


def prossimo_passo(passi: list[dict]) -> dict | None:
    """Il primo passo che tocca a chi guarda; se restano solo attese, la prima attesa."""
    for stati in (("dafare", "allerta"), ("attesa",)):
        for p in passi:
            if p["stato"] in stati:
                return p
    return None


MANCA = (
    ("anomalie", "Con anomalie aperte"),
    ("documenti", "Senza documenti"),
    ("fai", "Senza FAI"),
)


def filtra_manca(righe: list[dict], manca: str) -> list[dict]:
    if manca == "anomalie":
        return [r for r in righe if r["n_anomalie_aperte"]]
    if manca == "documenti":
        return [r for r in righe if not r["n_documenti"]]
    if manca == "fai":
        return [r for r in righe if not r["n_fai"]]
    return righe


def conteggi_manca(righe: list[dict], vede_kickoff: bool) -> list[dict]:
    return [
        {"chiave": k, "etichetta": e, "n": len(filtra_manca(righe, k))}
        for k, e in MANCA if k != "fai" or vede_kickoff
    ]
