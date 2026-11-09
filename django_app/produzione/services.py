"""Scheda dell'OP: quello che gli altri moduli sanno di quell'OP, letto dove sta.

- dati dell'OP: tabella ``ordini_produzione`` (``core/ordini_produzione.py``);
- FAI: Registro FAI, legati al titolo dell'OP o, se manca, al suo P/N;
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
    fai = Counter()
    if _vede_kickoff(request):
        fai = Counter(t.strip().lower() for t in _fai_visibili(request).exclude(op="").values_list("op", flat=True))
    anomalie = op_db.anomalie_aperte_per_op()
    for op in ops:
        chiave = op["op"].lower()
        op["n_documenti"] = documenti.get(chiave, 0)
        op["n_fai"] = fai.get(chiave, 0)
        op["n_anomalie_aperte"] = anomalie.get(chiave, 0)
    return ops


def scheda(request, op: dict) -> dict:
    titolo, pn = op["op"], op.get("pn") or ""
    pn_norm = normalize_part_number(pn)
    kickoff = _vede_kickoff(request)

    fai_op, fai_pn, programmi, progetti = [], [], [], []
    if kickoff:
        from tasks.access import scoped_projects_queryset
        from tasks.models import ProjectTechRef, TechRefKind

        fai = _fai_visibili(request).select_related("articolo", "stato")
        fai_op = list(fai.filter(op__iexact=titolo).order_by("-data_invio", "-id"))
        if pn_norm:
            fai_pn = list(
                fai.filter(articolo__part_number__iexact=pn_norm).exclude(pk__in=[f.pk for f in fai_op]).order_by("-data_invio", "-id")[:20]
            )
            visibili = scoped_projects_queryset(request)
            progetti = list(visibili.filter(part_number__iexact=pn_norm).order_by("-id")[:10])
            programmi = list(
                ProjectTechRef.objects.filter(
                    kind__in=[TechRefKind.CAM, TechRefKind.CMM], project__in=visibili.filter(part_number__iexact=pn_norm)
                ).select_related("project", "assigned_to").order_by("kind", "-id")
            )

    dati = {
        "op": op,
        "documenti": list(DocumentoOP.objects.filter(op__iexact=titolo).select_related("tipo", "creato_da")),
        "vede_kickoff": kickoff,
        "fai_op": fai_op,
        "fai_pn": fai_pn,
        "programmi": programmi,
        "progetti": progetti,
        "anomalie": op_db.conta_anomalie(op),
        "url_anomalie": url_anomalie(titolo),
        "url_nuovo_fai": f"{reverse('tasks:fai_nuovo')}?{urlencode({'op': titolo, 'pn': pn})}",
        "altri_op": [o for o in (op_db.elenco(pn) if pn else []) if o["id"] != op["id"] and normalize_part_number(o["pn"]) == pn_norm][:10],
    }
    dati["passi"] = percorso(request, dati)
    dati["prossimo"] = prossimo_passo(dati["passi"])
    return dati


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
        elif progetti:
            passi.append(_passo("kickoff", "KICK-OFF del P/N", "fatto", f"{progetti[0].name} · {progetti[0].get_phase_display()}",
                                "Apri il KICK-OFF", reverse("tasks:project_overview", args=[progetti[0].id])))
        else:
            passi.append(_passo("kickoff", "KICK-OFF del P/N", "dafare", f"Nessun KICK-OFF per il P/N {pn}.",
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

    documenti = dati["documenti"]
    puo = request_has_permission_code(request, PERM_DOCUMENTI)
    if documenti:
        tipi = list(dict.fromkeys(d.tipo.etichetta for d in documenti))
        passi.append(_passo("documenti", "Documenti di produzione", "fatto", ", ".join(tipi) + ".",
                            "Aggiungi documento" if puo else "", "?aggiungi=1#passo-documenti" if puo else ""))
    else:
        passi.append(_passo("documenti", "Documenti di produzione", "dafare", "Nessun documento registrato: ciclo, disegno, DIP, piano di controllo…",
                            "Aggiungi documento" if puo else "", "?aggiungi=1#passo-documenti" if puo else ""))

    if dati["vede_kickoff"]:
        from tasks.models import FaiFase

        validi = [f for f in dati["fai_op"] if not f.stato or f.stato.fase != FaiFase.ANNULLATO]
        positivo = next((f for f in validi if f.stato and f.stato.fase == FaiFase.POSITIVO), None)
        if positivo:
            passi.append(_passo("fai", "FAI", "fatto", f"{positivo.piano_numero or 'FAI'}: {positivo.stato.etichetta}.",
                                "Apri il FAI", reverse("tasks:fai_scheda", args=[positivo.id])))
        elif validi:
            f = validi[0]
            attesa = f.stato is None or f.stato.fase == FaiFase.IN_CORSO
            passi.append(_passo("fai", "FAI", "attesa" if attesa else "dafare",
                                f"{f.piano_numero or 'FAI'}: {f.stato.etichetta if f.stato else 'senza stato'}"
                                + (", in attesa di esito." if attesa else "."),
                                "Apri il FAI", reverse("tasks:fai_scheda", args=[f.id])))
        else:
            passi.append(_passo("fai", "FAI", "dafare", "Nessun FAI per questo OP.", "Nuovo FAI", dati["url_nuovo_fai"]))

    anomalie = dati["anomalie"]
    if anomalie["aperte"]:
        passi.append(_passo("anomalie", "Anomalie", "allerta",
                            f"{anomalie['aperte']} apert{'a' if anomalie['aperte'] == 1 else 'e'} su {anomalie['totale']}.",
                            "Gestisci le anomalie", dati["url_anomalie"]))
    else:
        passi.append(_passo("anomalie", "Anomalie", "fatto",
                            "Tutte chiuse." if anomalie["totale"] else "Nessuna anomalia.",
                            "Vedi le anomalie" if anomalie["totale"] else "", dati["url_anomalie"] if anomalie["totale"] else ""))

    for n, p in enumerate(passi, 1):
        p["n"] = n
    return passi


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
