from __future__ import annotations

import logging
import os
from functools import wraps
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.legacy_utils import get_legacy_user, is_legacy_admin

from .forms import SegnalazioneForm
from .models import DiarioPrepostoImpostazioni, SegnalazioneAllegato, SegnalazionePreposto

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _legacy_identity(request) -> tuple[str, str]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user:
        name = (legacy_user.nome or "").strip() or request.user.get_full_name() or request.user.get_username()
        email = (legacy_user.email or "").strip().lower() or (request.user.email or "").strip().lower()
        return name, email
    name = request.user.get_full_name() or request.user.get_username()
    email = (request.user.email or "").strip().lower()
    return name, email


def _can_write(request) -> bool:
    """Controlla se l'utente può creare/modificare/eliminare segnalazioni."""
    if not request.user.is_authenticated:
        return False
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    cfg = DiarioPrepostoImpostazioni.objects.first()
    if not cfg:
        return True  # nessuna config = accesso aperto
    acl = cfg.acl_scrittura or []
    if not acl:
        return True
    username = request.user.get_username().lower()
    email = (request.user.email or "").lower()
    return any(v.lower() in (username, email) for v in acl)


def _write_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _can_write(request):
            return render(request, "core/pages/forbidden.html", status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped


def _json_err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": msg}, status=status)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def lista(request):
    qs = SegnalazionePreposto.objects.all()

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(titolo__icontains=q)
            | Q(descrizione__icontains=q)
            | Q(chi_segnala__icontains=q)
            | Q(preposto__icontains=q)
        )

    filtro_preposto = request.GET.get("preposto", "").strip()
    if filtro_preposto:
        qs = qs.filter(preposto__icontains=filtro_preposto)

    preposti = (
        SegnalazionePreposto.objects.exclude(preposto="")
        .values_list("preposto", flat=True)
        .distinct()
        .order_by("preposto")
    )

    return render(request, "diario_preposto/pages/lista.html", {
        "segnalazioni": qs,
        "q": q,
        "filtro_preposto": filtro_preposto,
        "preposti": preposti,
        "can_write": _can_write(request),
        "totale": qs.count(),
    })


@login_required
def dettaglio(request, pk):
    segnalazione = get_object_or_404(SegnalazionePreposto, pk=pk)
    allegati = segnalazione.allegati.all()
    return render(request, "diario_preposto/pages/dettaglio.html", {
        "segnalazione": segnalazione,
        "allegati": allegati,
        "can_write": _can_write(request),
    })


@_write_required
def nuovo(request):
    nome, email = _legacy_identity(request)
    if request.method == "POST":
        form = SegnalazioneForm(request.POST)
        if form.is_valid():
            segnalazione = form.save(commit=False)
            segnalazione.creato_da = request.user
            segnalazione.preposto = nome
            segnalazione.chi_segnala = nome
            segnalazione.save()
            # Gestione allegati multipli
            for f in request.FILES.getlist("allegati"):
                SegnalazioneAllegato.objects.create(
                    segnalazione=segnalazione,
                    nome_file=f.name,
                    file=f,
                )
            messages.success(request, "Segnalazione inserita con successo.")
            return redirect("diario_preposto:dettaglio", pk=segnalazione.pk)
    else:
        now_local = timezone.localtime(timezone.now())
        form = SegnalazioneForm(initial={
            "chi_segnala": nome,
            "data_segnalazione": now_local.strftime("%Y-%m-%dT%H:%M"),
        })
    return render(request, "diario_preposto/pages/form.html", {
        "form": form,
        "action": "nuovo",
        "title": "Nuovo inserimento",
    })


@_write_required
def modifica(request, pk):
    segnalazione = get_object_or_404(SegnalazionePreposto, pk=pk)
    if request.method == "POST":
        form = SegnalazioneForm(request.POST, instance=segnalazione)
        if form.is_valid():
            form.save()
            # Nuovi allegati
            for f in request.FILES.getlist("allegati"):
                SegnalazioneAllegato.objects.create(
                    segnalazione=segnalazione,
                    nome_file=f.name,
                    file=f,
                )
            messages.success(request, "Segnalazione aggiornata.")
            return redirect("diario_preposto:dettaglio", pk=segnalazione.pk)
    else:
        initial = {}
        if segnalazione.data_segnalazione:
            local_dt = timezone.localtime(segnalazione.data_segnalazione)
            initial["data_segnalazione"] = local_dt.strftime("%Y-%m-%dT%H:%M")
        form = SegnalazioneForm(instance=segnalazione, initial=initial)
    return render(request, "diario_preposto/pages/form.html", {
        "form": form,
        "action": "modifica",
        "title": "Modifica segnalazione",
        "segnalazione": segnalazione,
        "allegati": segnalazione.allegati.all(),
    })


@_write_required
@require_POST
def elimina(request, pk):
    segnalazione = get_object_or_404(SegnalazionePreposto, pk=pk)
    # Elimina fisicamente i file
    for allegato in segnalazione.allegati.all():
        try:
            if allegato.file and os.path.isfile(allegato.file.path):
                os.remove(allegato.file.path)
        except Exception:
            pass
    segnalazione.delete()
    messages.success(request, "Segnalazione eliminata.")
    return redirect("diario_preposto:lista")


@login_required
def export_pdf(request, pk):
    segnalazione = get_object_or_404(SegnalazionePreposto, pk=pk)
    allegati = segnalazione.allegati.all()

    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as rl_canvas

        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=A4)
        w, h = A4

        teal = HexColor("#03787C")
        dark = HexColor("#1e293b")
        grey = HexColor("#64748b")

        # Header bar
        c.setFillColor(teal)
        c.rect(0, h - 40 * mm, w, 40 * mm, fill=1, stroke=0)
        c.setFillColor(HexColor("#ffffff"))
        c.setFont("Helvetica-Bold", 16)
        c.drawString(20 * mm, h - 20 * mm, "Diario Preposto RSPP ASPP RLS")
        c.setFont("Helvetica", 10)
        c.drawString(20 * mm, h - 28 * mm, "Segnalazione n. " + str(segnalazione.pk))

        y = h - 55 * mm

        def field(label, value, bold_val=False):
            nonlocal y
            c.setFillColor(grey)
            c.setFont("Helvetica", 8)
            c.drawString(20 * mm, y, label.upper())
            y -= 5 * mm
            c.setFillColor(dark)
            font = "Helvetica-Bold" if bold_val else "Helvetica"
            c.setFont(font, 11)
            # Word wrap semplice
            max_w = w - 40 * mm
            words = str(value or "—").split()
            line = ""
            for word in words:
                test = (line + " " + word).strip()
                if c.stringWidth(test, font, 11) > max_w:
                    c.drawString(20 * mm, y, line)
                    y -= 5 * mm
                    line = word
                else:
                    line = test
            if line:
                c.drawString(20 * mm, y, line)
            y -= 9 * mm

        field("Titolo", segnalazione.titolo, bold_val=True)
        field("Preposto", segnalazione.preposto)
        field("Chi segnala", segnalazione.chi_segnala)
        field(
            "Data segnalazione",
            timezone.localtime(segnalazione.data_segnalazione).strftime("%d/%m/%Y %H:%M")
            if segnalazione.data_segnalazione else "—",
        )

        # Separatore
        c.setStrokeColor(HexColor("#e2e8f0"))
        c.line(20 * mm, y + 4 * mm, w - 20 * mm, y + 4 * mm)
        y -= 5 * mm

        field("Descrizione della segnalazione", segnalazione.descrizione)

        if allegati:
            y -= 3 * mm
            c.setFillColor(grey)
            c.setFont("Helvetica", 8)
            c.drawString(20 * mm, y, "ALLEGATI")
            y -= 5 * mm
            c.setFillColor(dark)
            c.setFont("Helvetica", 10)
            for a in allegati:
                c.drawString(24 * mm, y, f"• {a.nome_file}")
                y -= 5 * mm

        # Footer
        c.setFillColor(grey)
        c.setFont("Helvetica", 8)
        c.drawString(20 * mm, 15 * mm, f"Esportato il {timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M')}")
        c.drawRightString(w - 20 * mm, 15 * mm, "Portale Applicativo — Costruzioni Novicrom SRL")

        c.save()
        buf.seek(0)
        filename = f"segnalazione_{segnalazione.pk}.pdf"
        resp = HttpResponse(buf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp

    except ImportError:
        return HttpResponse("reportlab non disponibile", status=500)


# ---------------------------------------------------------------------------
# API allegati
# ---------------------------------------------------------------------------

@_write_required
@require_POST
def api_allegato_upload(request):
    pk = request.POST.get("segnalazione_id")
    if not pk:
        return _json_err("segnalazione_id obbligatorio")
    segnalazione = get_object_or_404(SegnalazionePreposto, pk=pk)
    f = request.FILES.get("file")
    if not f:
        return _json_err("Nessun file ricevuto")
    allegato = SegnalazioneAllegato.objects.create(
        segnalazione=segnalazione,
        nome_file=f.name,
        file=f,
    )
    return JsonResponse({
        "ok": True,
        "id": allegato.pk,
        "nome_file": allegato.nome_file,
        "url": allegato.file.url,
    })


@_write_required
@require_POST
def api_allegato_delete(request):
    pk = request.POST.get("allegato_id")
    if not pk:
        return _json_err("allegato_id obbligatorio")
    allegato = get_object_or_404(SegnalazioneAllegato, pk=pk)
    try:
        if allegato.file and os.path.isfile(allegato.file.path):
            os.remove(allegato.file.path)
    except Exception:
        pass
    allegato.delete()
    return JsonResponse({"ok": True})
