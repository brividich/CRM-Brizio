"""Report FAI: la pagina con i conteggi e i file da scaricare."""
from __future__ import annotations

from django.http import Http404, HttpResponse
from django.shortcuts import render

from core.audit import log_action
from core.excel_export import make_xlsx_response
from core.table_pdf import render_table_pdf

from ..access import task_permissions_required
from ..services import fai_report as rep
from ..services.fai import righe_registro, soglie
from ._shared import _tasks_shell_context
from .fai import _fai_visibili, colonne_tutti, righe_tutti


def _filtrati(request):
    cliente = (request.GET.get("cliente") or "").strip()
    records = _fai_visibili(request)
    if cliente:
        records = records.filter(articolo__client_name=cliente)
    return cliente, records


def _righe_report(chiave: str, righe: list[dict]) -> list[dict]:
    if chiave == "scadenze":
        return rep.scadenze(righe)
    if chiave == "trimestrale":
        return rep.trimestrale(righe)
    return righe


@task_permissions_required("tasks_view")
def fai_report(request):
    cliente, records = _filtrati(request)
    righe = righe_registro(records)
    conti = rep.conta_situazioni(righe)
    limiti = soglie()
    clienti = sorted(
        set(_fai_visibili(request).exclude(articolo__client_name="").values_list("articolo__client_name", flat=True)),
        key=str.lower,
    )
    riepilogo = rep.per_cliente(righe)
    quante = {
        "scadenze": len(rep.scadenze(righe)),
        "trimestrale": len(rep.trimestrale(righe)),
        "situazione": len(righe),
        "clienti": len(riepilogo),
        "tutti": records.count(),
    }
    return render(request, "tasks/fai_report.html", {
        **_tasks_shell_context(request, active="fai"),
        "page_title": "Report FAI",
        "cliente": cliente,
        "clienti": clienti,
        "viste": [
            {"codice": "", "etichetta": "Articoli", "conta": len(righe)},
            {"codice": "da_ripetere", "etichetta": "Da ripetere", "conta": conti["da_ripetere"]},
            {"codice": "da_verificare", "etichetta": f"Oltre {limiti.mesi_verifica} mesi", "conta": conti["da_verificare"]},
            {"codice": "in_corso", "etichetta": "In corso", "conta": conti["in_corso"]},
            {"codice": "in_regola", "etichetta": "In regola", "conta": conti["in_regola"]},
            {"codice": "date_mancanti", "etichetta": "Senza date", "conta": conti["date_mancanti"]},
        ],
        "report": [
            {"chiave": r.chiave, "nome": r.nome, "descrizione": r.descrizione, "pdf": r.pdf, "righe": quante[r.chiave]}
            for r in rep.REPORT
        ],
        "per_cliente": riepilogo,
        "per_stato": rep.per_stato(records),
        "per_anno": rep.per_anno(records),
        "mesi_verifica": limiti.mesi_verifica,
    })


def _tabella(chiave: str, records) -> tuple[list, list[list]]:
    if chiave == "tutti":
        return colonne_tutti(), righe_tutti(records)
    righe = righe_registro(records)
    if chiave == "clienti":
        colonne = ["Cliente", "Articoli", "Da ripetere", f"Oltre {soglie().mesi_verifica} mesi", "In corso", "In regola", "Senza date"]
        return colonne, [
            [r["cliente"], r["totale"], *(r[s] for s in rep.SITUAZIONI)] for r in rep.per_cliente(righe)
        ]
    return list(rep.COLONNE_ARTICOLI), rep.righe_articoli(_righe_report(chiave, righe))


@task_permissions_required("tasks_view")
def fai_report_scarica(request):
    voce = rep.PER_CHIAVE.get(request.GET.get("report", ""))
    formato = request.GET.get("formato", "xlsx")
    if voce is None or formato not in ("xlsx", "pdf") or (formato == "pdf" and not voce.pdf):
        raise Http404
    cliente, records = _filtrati(request)
    colonne, righe = _tabella(voce.chiave, records)
    log_action(request, "kickoff_fai_report", "tasks", {
        "report": voce.chiave, "formato": formato, "cliente": cliente, "righe": len(righe),
    })
    nome = f"report_fai_{voce.chiave}"
    if formato == "xlsx":
        return make_xlsx_response(
            filename=f"{nome}.xlsx", columns=colonne, rows=righe, sheet_title="Report FAI",
            title=voce.nome, subtitle=voce.descrizione, filters_label=f"Cliente: {cliente}" if cliente else None,
        )
    if voce.chiave == "clienti":
        righe_stampa = [[str(v) for v in r] for r in righe]
    else:
        colonne, righe_stampa = list(rep.COLONNE_ARTICOLI_PDF), rep.righe_pdf(righe)
    pdf = render_table_pdf(
        title=voce.nome, headers=colonne, rows=righe_stampa,
        subtitle=f"{voce.descrizione}{f' Cliente: {cliente}.' if cliente else ''}",
    )
    risposta = HttpResponse(pdf, content_type="application/pdf")
    risposta["Content-Disposition"] = f'attachment; filename="{nome}.pdf"'
    return risposta
