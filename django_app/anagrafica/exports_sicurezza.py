"""Export Salute e sicurezza: organigramma per mansione di rischio (RSPP / medico competente).

Una riga per persona esposta: mansione di rischio (codice, livello, DVR, fattori,
protocollo), mansione lavorativa, reparto, perché è esposta, stato operativo
(solo l'etichetta). Nessun esito di idoneità, nessuna prescrizione.
"""
from __future__ import annotations

from django.http import HttpRequest

from anagrafica.exports import ExportSpec, acl_gate, register


def _righe(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.services.organigramma_rischio import costruisci, righe_export

    from anagrafica.views import _can_view_visite_mediche

    can_view = _can_view_visite_mediche(request)
    fattore = (request.GET.get("fattore") or "").strip() if scope == "filtered" else ""
    righe = righe_export(costruisci(fattore_id=int(fattore) if fattore.isdigit() else None,
                                    can_view_visite=can_view))
    if not can_view:
        for r in righe:
            r["protocollo"] = ""
    return righe


def _permesso(request: HttpRequest) -> bool:
    from anagrafica.views import _check_hr_permission, _is_anagrafica_admin
    return acl_gate("/anagrafica/organigramma/mansioni-rischio/")(request) and (
        _is_anagrafica_admin(request) or _check_hr_permission(request)
    )


register(ExportSpec(
    key="organigramma_mansioni_rischio",
    title="Organigramma per mansione di rischio",
    sheet_title="Mansioni di rischio",
    columns=[
        ("Codice", "codice"),
        ("Mansione di rischio", "mansione_rischio"),
        ("Livello DVR", "livello"),
        ("Revisione DVR", "dvr"),
        ("Fattori di rischio", "fattori"),
        ("Protocollo sanitario", "protocollo"),
        ("Mansione lavorativa", "mansione"),
        ("Dipendente", "dipendente"),
        ("Reparto", "reparto"),
        ("Esposto per", "via"),
        ("Stato operativo", "stato"),
    ],
    dataset=_righe,
    permission=_permesso,
))
