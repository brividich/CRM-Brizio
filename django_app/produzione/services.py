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

    return {
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
