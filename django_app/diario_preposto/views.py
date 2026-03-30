from __future__ import annotations

import logging
import os
from functools import wraps
from io import BytesIO
from xml.sax.saxutils import escape

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
    """Controlla se l'utente puo creare/modificare/eliminare segnalazioni."""
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


def _pdf_safe_text(value: object, *, preserve_breaks: bool = False) -> str:
    text = str(value or "-").strip() or "-"
    text = escape(text)
    if preserve_breaks:
        return text.replace("\n", "<br/>")
    return text


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def lista(request):
    qs = SegnalazionePreposto.objects.all()

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(codice_identificativo__icontains=q)
            | Q(titolo__icontains=q)
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

    return render(
        request,
        "diario_preposto/pages/lista.html",
        {
            "segnalazioni": qs,
            "q": q,
            "filtro_preposto": filtro_preposto,
            "preposti": preposti,
            "can_write": _can_write(request),
            "totale": qs.count(),
        },
    )


@login_required
def dettaglio(request, pk):
    segnalazione = get_object_or_404(SegnalazionePreposto, pk=pk)
    allegati = segnalazione.allegati.all()
    return render(
        request,
        "diario_preposto/pages/dettaglio.html",
        {
            "segnalazione": segnalazione,
            "allegati": allegati,
            "can_write": _can_write(request),
        },
    )


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
            for uploaded_file in request.FILES.getlist("allegati"):
                SegnalazioneAllegato.objects.create(
                    segnalazione=segnalazione,
                    nome_file=uploaded_file.name,
                    file=uploaded_file,
                )
            messages.success(request, "Segnalazione inserita con successo.")
            return redirect("diario_preposto:dettaglio", pk=segnalazione.pk)
    else:
        now_local = timezone.localtime(timezone.now())
        form = SegnalazioneForm(
            initial={
                "chi_segnala": nome,
                "data_segnalazione": now_local.strftime("%Y-%m-%dT%H:%M"),
            }
        )
    return render(
        request,
        "diario_preposto/pages/form.html",
        {
            "form": form,
            "action": "nuovo",
            "title": "Nuovo inserimento",
        },
    )


@_write_required
def modifica(request, pk):
    segnalazione = get_object_or_404(SegnalazionePreposto, pk=pk)
    if request.method == "POST":
        form = SegnalazioneForm(request.POST, instance=segnalazione)
        if form.is_valid():
            form.save()
            for uploaded_file in request.FILES.getlist("allegati"):
                SegnalazioneAllegato.objects.create(
                    segnalazione=segnalazione,
                    nome_file=uploaded_file.name,
                    file=uploaded_file,
                )
            messages.success(request, "Segnalazione aggiornata.")
            return redirect("diario_preposto:dettaglio", pk=segnalazione.pk)
    else:
        initial = {}
        if segnalazione.data_segnalazione:
            local_dt = timezone.localtime(segnalazione.data_segnalazione)
            initial["data_segnalazione"] = local_dt.strftime("%Y-%m-%dT%H:%M")
        form = SegnalazioneForm(instance=segnalazione, initial=initial)
    return render(
        request,
        "diario_preposto/pages/form.html",
        {
            "form": form,
            "action": "modifica",
            "title": "Modifica segnalazione",
            "segnalazione": segnalazione,
            "allegati": segnalazione.allegati.all(),
        },
    )


@_write_required
@require_POST
def elimina(request, pk):
    segnalazione = get_object_or_404(SegnalazionePreposto, pk=pk)
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
    allegati = list(segnalazione.allegati.all())

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        buf = BytesIO()
        generated_at = timezone.localtime(timezone.now())
        codice = segnalazione.codice_identificativo or f"PK-{segnalazione.pk}"
        data_segnalazione = (
            timezone.localtime(segnalazione.data_segnalazione).strftime("%d/%m/%Y %H:%M")
            if segnalazione.data_segnalazione
            else "-"
        )
        created_at = timezone.localtime(segnalazione.created_at).strftime("%d/%m/%Y %H:%M")
        updated_at = timezone.localtime(segnalazione.updated_at).strftime("%d/%m/%Y %H:%M")

        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=50 * mm,
            bottomMargin=20 * mm,
            title=f"Segnalazione {codice}",
            author="Portale Applicativo - Costruzioni Novicrom SRL",
        )

        stylesheet = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "DpTitle",
            parent=stylesheet["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "DpBody",
            parent=stylesheet["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#1e293b"),
        )
        muted_style = ParagraphStyle(
            "DpMuted",
            parent=stylesheet["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#64748b"),
        )
        value_style = ParagraphStyle(
            "DpValue",
            parent=stylesheet["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#0f172a"),
        )
        section_style = ParagraphStyle(
            "DpSection",
            parent=stylesheet["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=colors.HexColor("#0f766e"),
            spaceAfter=6,
        )

        def meta_cell(label: str, value: object) -> list[Paragraph]:
            return [
                Paragraph(_pdf_safe_text(label).upper(), muted_style),
                Paragraph(_pdf_safe_text(value), value_style),
            ]

        story = [
            Paragraph(_pdf_safe_text(segnalazione.titolo), title_style),
            Paragraph(
                "Report della segnalazione di sicurezza con riepilogo dati, descrizione completa e allegati collegati.",
                body_style,
            ),
            Spacer(1, 8 * mm),
        ]

        meta_table = Table(
            [
                [meta_cell("ID segnalazione", codice), meta_cell("Data segnalazione", data_segnalazione)],
                [meta_cell("Preposto", segnalazione.preposto or "-"), meta_cell("Chi segnala", segnalazione.chi_segnala or "-")],
                [meta_cell("Creato il", created_at), meta_cell("Ultimo aggiornamento", updated_at)],
            ],
            colWidths=[doc.width / 2, doc.width / 2],
            hAlign="LEFT",
        )
        meta_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.extend([meta_table, Spacer(1, 8 * mm)])

        story.append(Paragraph("Descrizione della segnalazione", section_style))
        descrizione_table = Table(
            [[Paragraph(_pdf_safe_text(segnalazione.descrizione, preserve_breaks=True), body_style)]],
            colWidths=[doc.width],
            hAlign="LEFT",
        )
        descrizione_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#dbeafe")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ]
            )
        )
        story.extend([descrizione_table, Spacer(1, 8 * mm)])

        story.append(Paragraph("Allegati", section_style))
        if allegati:
            allegati_table = Table(
                [
                    [Paragraph(str(index), muted_style), Paragraph(_pdf_safe_text(allegato.nome_file), body_style)]
                    for index, allegato in enumerate(allegati, start=1)
                ],
                colWidths=[12 * mm, doc.width - 12 * mm],
                hAlign="LEFT",
            )
            allegati_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                )
            )
            story.append(allegati_table)
        else:
            story.append(Paragraph("Nessun allegato associato.", body_style))

        def draw_page(canvas, document):
            width, height = A4
            teal = colors.HexColor("#03787C")
            mint = colors.HexColor("#d1fae5")
            dark = colors.HexColor("#0f172a")
            muted = colors.HexColor("#64748b")

            canvas.saveState()
            canvas.setFillColor(teal)
            canvas.rect(0, height - 38 * mm, width, 38 * mm, fill=1, stroke=0)
            canvas.setFillColor(mint)
            canvas.circle(width - 18 * mm, height - 12 * mm, 10 * mm, fill=1, stroke=0)
            canvas.circle(width - 34 * mm, height - 23 * mm, 6 * mm, fill=1, stroke=0)

            canvas.setFillColor(colors.white)
            canvas.setFont("Helvetica-Bold", 18)
            canvas.drawString(16 * mm, height - 16 * mm, "Diario Preposto")
            canvas.setFont("Helvetica", 10)
            canvas.drawString(16 * mm, height - 23 * mm, "Report segnalazione sicurezza")
            canvas.setFont("Helvetica-Bold", 12)
            canvas.drawRightString(width - 16 * mm, height - 16 * mm, codice)
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(width - 16 * mm, height - 23 * mm, f"Generato il {generated_at.strftime('%d/%m/%Y %H:%M')}")

            canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
            canvas.line(16 * mm, 15 * mm, width - 16 * mm, 15 * mm)
            canvas.setFillColor(muted)
            canvas.setFont("Helvetica", 8)
            canvas.drawString(16 * mm, 9 * mm, "Portale Applicativo - Costruzioni Novicrom SRL")
            canvas.setFillColor(dark)
            canvas.drawRightString(width - 16 * mm, 9 * mm, f"Pagina {document.page}")
            canvas.restoreState()

        doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
        buf.seek(0)
        export_code = codice.lower()
        filename = f"segnalazione_{export_code}.pdf"
        response = HttpResponse(buf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response

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
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return _json_err("Nessun file ricevuto")
    allegato = SegnalazioneAllegato.objects.create(
        segnalazione=segnalazione,
        nome_file=uploaded_file.name,
        file=uploaded_file,
    )
    return JsonResponse(
        {
            "ok": True,
            "id": allegato.pk,
            "nome_file": allegato.nome_file,
            "url": allegato.file.url,
        }
    )


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


@login_required
def impostazioni(request):
    """Impostazioni modulo Diario Preposto — solo admin legacy."""
    legacy_user = get_legacy_user(request.user)
    if not (legacy_user and is_legacy_admin(legacy_user)):
        return render(request, "core/pages/forbidden.html", status=403)

    cfg = DiarioPrepostoImpostazioni.objects.filter(pk=1).first()
    if cfg is None:
        cfg = DiarioPrepostoImpostazioni.objects.create(pk=1, acl_scrittura=[])

    if request.method == "POST":
        raw = request.POST.get("acl_scrittura", "").strip()
        entries = [e.strip() for e in raw.replace(",", "\n").splitlines() if e.strip()]
        cfg.acl_scrittura = entries
        cfg.save()
        from core.audit import log_action
        log_action(request, "modifica", "diario_preposto", "Aggiornate impostazioni Diario Preposto")
        messages.success(request, "Impostazioni salvate.")
        return redirect("diario_preposto:impostazioni")

    acl_text = "\n".join(cfg.acl_scrittura) if cfg.acl_scrittura else ""
    return render(request, "diario_preposto/pages/impostazioni.html", {
        "cfg": cfg,
        "acl_text": acl_text,
    })
