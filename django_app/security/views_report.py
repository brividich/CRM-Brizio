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


# --- Conformità ISO/IEC 27001 (services/iso27001.py, services/iso_pacchetto.py) ----------------

def _periodo_iso(request):
    from .services import iso27001

    dati = request.POST if request.method == "POST" else request.GET
    return iso27001.periodo(dati.get("periodo", "mese_corrente"), parse_date(dati.get("dal")), parse_date(dati.get("al")))


def iso27001_page(request):
    """Report › Conformità ISO 27001: un riquadro per controllo dell'Annex A, con esito, numeri, evidenze e cosa fare."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from django.shortcuts import redirect
    from django.urls import reverse

    from .models import SecurityPacchettoIso
    from .services import iso27001
    from .services.configuration import can_manage_security_config

    dal, al, etichetta, preset = _periodo_iso(request)
    can_edit = can_manage_security_config(request.user)
    if request.method == "POST":
        from django.contrib import messages

        if not can_edit:
            return _denied(request)
        from .services import iso_pacchetto

        try:
            p = iso_pacchetto.genera(dal, al, utente=request.user, request=request)
        except Exception as exc:  # noqa: BLE001 - l'errore si legge in pagina, non in un 500
            messages.error(request, f"Pacchetto non generato: {type(exc).__name__}: {exc}"[:400])
        else:
            messages.success(request, f"Pacchetto di evidenze «{p.riepilogo.get('etichetta')}» archiviato (SHA-256 {p.sha256[:12]}…)."
                             + (f" {p.copia_esito}" if p.copia_esito else ""))
        return redirect(f"{reverse('security:iso27001')}?periodo={preset}&dal={dal:%Y-%m-%d}&al={al:%Y-%m-%d}#pacchetti")
    return render(request, "security/iso27001.html", {
        "valutazione": iso27001.valuta(dal, al), "periodi": iso27001.PERIODI, "preset": preset, "dal": dal, "al": al,
        "etichetta": etichetta, "can_edit": can_edit,
        "pacchetti": SecurityPacchettoIso.objects.select_related("generato_da").order_by("-periodo_dal", "-generato_il")[:36],
    })


def iso27001_pacchetto_download(request, pk):
    """Scarica un pacchetto archiviato (chi vede il SOC); ogni download finisce nell'audit."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from django.http import FileResponse, Http404
    from django.shortcuts import get_object_or_404

    from core.audit import log_action

    from .models import SecurityPacchettoIso

    p = get_object_or_404(SecurityPacchettoIso, pk=pk)
    if not p.file or not p.file.name:
        raise Http404("Pacchetto senza file.")
    try:
        handle = p.file.storage.open(p.file.name, "rb")
    except FileNotFoundError:
        raise Http404("File non trovato.") from None
    log_action(request, "pacchetto_iso_scaricato", "security", {"periodo_dal": p.periodo_dal.isoformat(), "periodo_al": p.periodo_al.isoformat(),
                                                                "sha256": p.sha256}, oggetto=p)
    response = FileResponse(handle, as_attachment=True, filename=p.nome_file, content_type="application/pdf")
    response["Cache-Control"] = "private, no-store"
    return response
