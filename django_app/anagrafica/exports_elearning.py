"""Export e-learning: registro dei completamenti e copertura (xlsx/pdf con data e filtri)."""
from __future__ import annotations

from datetime import date

from django.http import HttpRequest

from anagrafica.exports import ExportSpec, acl_gate, register


def _permesso(path):
    def _check(request: HttpRequest) -> bool:
        from anagrafica.views import _can_view_formazione
        return acl_gate(path)(request) and _can_view_formazione(request)
    return _check


def _data(v):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def _registro(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.services.elearning_report import registro
    g = request.GET if scope == "filtered" else {}
    corso = g.get("corso") or ""
    righe = registro(corso_id=int(corso) if str(corso).isdigit() else None, dal=_data(g.get("dal")), al=_data(g.get("al")))
    for r in righe:
        r["data"] = r["data"].strftime("%d/%m/%Y %H:%M")
    return righe


def _filtri_registro(request: HttpRequest) -> str:
    pezzi = [f"{k}={request.GET[k]}" for k in ("corso", "dal", "al") if request.GET.get(k)]
    return ", ".join(pezzi)


def _copertura(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.services.elearning_report import copertura
    g = request.GET if scope == "filtered" else {}
    corso = g.get("corso") or ""
    cop = copertura(reparto=(g.get("reparto") or "").strip(), corso_id=int(corso) if str(corso).isdigit() else None)
    righe = []
    for p in cop["persone"]:
        for v in p["voci"]:
            righe.append({"dipendente": p["nome"], "reparto": p["reparto"], "mansione": p["mansione"],
                          "corso": v["corso"].titolo, "stato": "In regola" if v["ok"] else v["stato"].replace("_", " ").title(),
                          "scadenza": v["scadenza"].strftime("%d/%m/%Y") if v["scadenza"] else ""})
    return righe


register(ExportSpec(
    key="elearning_registro", title="Registro completamenti e-learning", sheet_title="Registro",
    columns=[("Data", "data"), ("Dipendente", "dipendente"), ("Corso", "corso"), ("Codice", "codice"),
             ("Ciclo", "ciclo"), ("Versione", "versione"), ("Minuti effettivi", "minuti_effettivi"),
             ("Slide", "slide"), ("Tentativi", "tentativi"), ("Punteggio %", "punteggio"),
             ("Protocollo attestato", "protocollo"), ("Impronta", "impronta")],
    dataset=_registro, filters_label=_filtri_registro,
    permission=_permesso("/anagrafica/formazione/elearning/registro/"),
))

register(ExportSpec(
    key="elearning_copertura", title="Copertura formazione e-learning", sheet_title="Copertura",
    columns=[("Dipendente", "dipendente"), ("Reparto", "reparto"), ("Mansione", "mansione"),
             ("Corso", "corso"), ("Stato", "stato"), ("Scadenza", "scadenza")],
    dataset=_copertura, filters_label=lambda r: ", ".join(f"{k}={r.GET[k]}" for k in ("reparto", "corso") if r.GET.get(k)),
    permission=_permesso("/anagrafica/formazione/elearning/cruscotto/"),
))
