"""Report periodico del Security Center: anteprima in pagina e PDF con gli stessi dati."""
from django.http import HttpResponse
from django.shortcuts import render

from .permissions import can_view_security_center
from .services.periodic_report import PRESETS, build_report, parse_date, resolve_period


def _denied(request):
    from security.views import _security_center_denied

    return _security_center_denied(request)


def _period(request):
    preset = request.GET.get("period", "last_week")
    if preset not in dict(PRESETS):
        preset = "last_week"
    start, end, label = resolve_period(preset, parse_date(request.GET.get("from")), parse_date(request.GET.get("to")))
    return preset, start, end, label


def report_page(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    preset, start, end, label = _period(request)
    return render(request, "security/report.html", {
        "report": build_report(start, end, label),
        "presets": PRESETS,
        "preset": preset,
        "query": request.GET.urlencode(),
    })


def report_pdf(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services.soc_pdf import render_period_report_pdf

    _preset, start, end, label = _period(request)
    response = HttpResponse(render_period_report_pdf(build_report(start, end, label)), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="report-soc-{start:%Y%m%d}-{end:%Y%m%d}.pdf"'
    return response
