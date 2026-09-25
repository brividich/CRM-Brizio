"""Viste della sezione Report conformita'.

Autorizzazione a due livelli, entrambi server-side:
- accesso al modulo: binding ACL della route (middleware) + controllo in view;
- area del report: permesso canonico dell'area, verificato qui, fail-closed.
Ogni download PDF/XLSX finisce nell'AuditLog.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.text import slugify

from core.audit import log_action

from .acl_bootstrap import PERM_AREA, PERM_VIEW
from .exports import PdfSection, render_pdf, report_pdf, report_xlsx, section_for
from .registry import AREE, AREE_ORDINE, NORME, ReportParams, all_reports, get_report

logger = logging.getLogger(__name__)

MODULE = "report_conformita"


def _has_perm(request, code: str) -> bool:
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        return bool(evaluate_permission_code_access(
            permission_code=code, legacy_user=legacy_user, django_user=request.user,
        ).get("allowed"))
    except Exception:
        logger.warning("report_conformita: valutazione permesso %s fallita", code, exc_info=True)
        return bool(getattr(request, "user", None) and request.user.is_superuser)


def _aree_consentite(request) -> set[str]:
    if not _has_perm(request, PERM_VIEW):
        return set()
    return {area for area, code in PERM_AREA.items() if _has_perm(request, code)}


def _filtri_label(report, params) -> str:
    parti = []
    for filtro in report.filtri:
        value = params.extra.get(filtro.name, "")
        label = dict(filtro.choices).get(value, "")
        if value and label:
            parti.append(f"{filtro.label}: {label}")
    return ", ".join(parti)


def _download(request, *, body: bytes, filename: str, content_type: str, report_slug: str, fmt: str, params):
    log_action(
        request, "report_conformita_download", MODULE,
        {"report": report_slug, "formato": fmt, **params.as_query()},
        oggetto_tipo="report", oggetto_id=report_slug,
    )
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def index(request):
    aree = _aree_consentite(request)
    if not aree:
        messages.error(request, "Non hai accesso ai Report conformità.")
        return redirect("dashboard:dashboard")
    norma = request.GET.get("norma", "")
    if norma not in NORME:
        norma = ""
    gruppi = []
    for area in AREE_ORDINE:
        if area not in aree:
            continue
        reports = [r for r in all_reports() if r.area == area and (not norma or norma in r.norme)]
        if reports:
            gruppi.append({"area": area, "label": AREE[area], "reports": reports})
    return render(request, "report_conformita/pages/index.html", {
        "page_title": "Report conformità",
        "gruppi": gruppi,
        "norme": NORME,
        "norma": norma,
        "aree_negate": [AREE[a] for a in AREE_ORDINE if a not in aree],
    })


@login_required
def report(request, slug: str):
    definition = get_report(slug)
    if definition is None:
        raise Http404("Report inesistente")
    if definition.area not in _aree_consentite(request):
        messages.error(request, "Non hai i permessi per questo report.")
        return redirect("report_conformita:index")

    params = ReportParams.from_querydict(request.GET, filtri=definition.filtri)
    result = definition.build(params)
    filtri_label = _filtri_label(definition, params)
    fmt = (request.GET.get("formato") or "").strip().lower()
    stamp = timezone.localdate().strftime("%Y%m%d")
    if fmt == "pdf":
        return _download(
            request, body=report_pdf(definition, params, result, filtri_label),
            filename=f"{slugify(definition.slug)}_{stamp}.pdf", content_type="application/pdf",
            report_slug=definition.slug, fmt=fmt, params=params,
        )
    if fmt == "xlsx":
        return _download(
            request, body=report_xlsx(definition, params, result, filtri_label),
            filename=f"{slugify(definition.slug)}_{stamp}.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            report_slug=definition.slug, fmt=fmt, params=params,
        )

    query = urlencode(params.as_query())
    return render(request, "report_conformita/pages/report.html", {
        "page_title": definition.title,
        "report": definition,
        "area_label": AREE[definition.area],
        "params": params,
        "result": result,
        "rows": list(zip(result.rows, result.row_tones)),
        "filtri_label": filtri_label,
        "pdf_url": f"?{query}&formato=pdf",
        "xlsx_url": f"?{query}&formato=xlsx",
    })


@login_required
def riesame(request):
    """Pacchetto di ingresso al riesame della direzione: solo indicatori, per area consentita."""
    aree = _aree_consentite(request)
    if not aree:
        messages.error(request, "Non hai accesso ai Report conformità.")
        return redirect("dashboard:dashboard")
    params = ReportParams.from_querydict(request.GET)
    sezioni = []
    for definition in all_reports():
        if definition.area not in aree:
            continue
        try:
            result = definition.build(params)
        except Exception:
            logger.exception("riesame: report %s non calcolabile", definition.slug)
            result = None
        sezioni.append({"report": definition, "result": result, "area_label": AREE[definition.area]})

    if (request.GET.get("formato") or "").strip().lower() == "pdf":
        pdf_sections = []
        for s in sezioni:
            if s["result"] is None:
                pdf_sections.append(PdfSection(title=s["report"].title, clausole="", kpis=[],
                                               notes=["Report non calcolabile: vedi log applicativo."]))
                continue
            section = section_for(s["report"], s["result"])
            # Nel pacchetto riesame solo indicatori: le righe nominative restano nei singoli report.
            section.columns, section.rows, section.row_tones = [], [], []
            section.notes = []
            pdf_sections.append(section)
        body = render_pdf(
            title="Riesame della direzione - dati di ingresso",
            subtitle=f"Periodo {params.periodo_label} | " + " · ".join(NORME),
            sections=pdf_sections,
            intro=[
                "Dati di ingresso al riesame della direzione (ISO 9001 §9.3.2, EN 9100 §9.3.2, "
                "ISO 45001 §9.3, ISO 27001 §9.3.2): prestazioni dei processi, non conformità e azioni "
                "correttive, risultati di monitoraggio, prestazioni dei fornitori, competenze, "
                "adeguatezza delle risorse.",
                f"Aree incluse: {', '.join(AREE[a] for a in AREE_ORDINE if a in aree)}.",
            ],
        )
        return _download(
            request, body=body, filename=f"riesame_direzione_{timezone.localdate():%Y%m%d}.pdf",
            content_type="application/pdf", report_slug="riesame", fmt="pdf", params=params,
        )

    return render(request, "report_conformita/pages/riesame.html", {
        "page_title": "Riesame della direzione",
        "params": params,
        "sezioni": sezioni,
        "pdf_url": f"?{urlencode(params.as_query())}&formato=pdf",
        "aree_escluse": [AREE[a] for a in AREE_ORDINE if a not in aree],
    })
