from __future__ import annotations

import csv
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from .models import SCADENZA_SDS_GIORNI, PresaVisioneScheda, ProdottoChimico, SchedaSicurezza
from .reports import matrice_presa_visione, prodotti_senza_scheda_corrente
from .services.ingestion import estrai_sds
from .services.qr import genera_qr_png

logger = logging.getLogger(__name__)

SDS_ALLOWED_EXTENSIONS = {".pdf"}
SDS_ALLOWED_MIMES = {"application/pdf"}
SDS_MAX_BYTES = 25 * 1024 * 1024  # 25 MB

PERM_VIEW = "schede_sicurezza.prodotto.view"
PERM_GESTISCI = "schede_sicurezza.prodotto.gestisci"


# ---------------------------------------------------------------------------
# Helpers ACL v2 (fail-safe: in assenza del sottosistema ricade su
# is_authenticated / is_superuser, mai su un default più permissivo)
# ---------------------------------------------------------------------------

def _can_view(request) -> bool:
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        return bool(evaluate_permission_code_access(
            permission_code=PERM_VIEW,
            legacy_user=legacy_user,
            django_user=request.user,
        ).get("allowed"))
    except Exception:
        return bool(getattr(request, "user", None) and request.user.is_authenticated)


def _can_gestire(request) -> bool:
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        return bool(evaluate_permission_code_access(
            permission_code=PERM_GESTISCI,
            legacy_user=legacy_user,
            django_user=request.user,
        ).get("allowed"))
    except Exception:
        return bool(getattr(request, "user", None) and request.user.is_superuser)


# ---------------------------------------------------------------------------
# Lista + dettaglio prodotto
# ---------------------------------------------------------------------------

@login_required
def prodotto_list(request):
    if not _can_view(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    from anagrafica.models import Reparto

    query = request.GET.get("q", "").strip()
    reparto_id = request.GET.get("reparto", "").strip()
    famiglia = request.GET.get("famiglia", "").strip()
    stato = request.GET.get("stato", "").strip()

    qs = (
        ProdottoChimico.objects.filter(attivo=True)
        .select_related("reparto")
        .order_by("nome")
    )
    if query:
        qs = qs.filter(
            Q(nome__icontains=query)
            | Q(fornitore__icontains=query)
            | Q(codice_prodotto__icontains=query)
        )
    if reparto_id:
        qs = qs.filter(reparto_id=reparto_id)
    if famiglia:
        qs = qs.filter(famiglia=famiglia)
    if stato == "senza_scheda":
        qs = qs.filter(pk__in=prodotti_senza_scheda_corrente())
    elif stato == "con_scheda":
        qs = qs.filter(schede__is_corrente=True).distinct()
    elif stato == "da_rivedere":
        soglia = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI)
        qs = qs.filter(schede__is_corrente=True, schede__data_caricamento__lt=soglia).distinct()

    return render(request, "schede_sicurezza/pages/prodotto_list.html", {
        "prodotti": qs,
        "query": query,
        "reparto_selezionato": reparto_id,
        "famiglia_selezionata": famiglia,
        "stato_selezionato": stato,
        "reparti_options": Reparto.objects.filter(is_active=True).order_by("nome"),
        "famiglie_options": (
            ProdottoChimico.objects.exclude(famiglia="")
            .values_list("famiglia", flat=True).distinct().order_by("famiglia")
        ),
        "can_gestire": _can_gestire(request),
    })


@login_required
def prodotto_form(request, pk: int | None = None):
    if not _can_gestire(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("schede_sicurezza:prodotto_list")

    from anagrafica.models import Reparto
    from dpi.models import CategoriaDPI

    prodotto = get_object_or_404(ProdottoChimico, pk=pk) if pk else None

    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        reparto_id = request.POST.get("reparto", "").strip()

        errors = []
        if not nome:
            errors.append("Il nome è obbligatorio.")
        reparto = None
        if reparto_id:
            try:
                reparto = Reparto.objects.get(pk=int(reparto_id))
            except (Reparto.DoesNotExist, ValueError):
                errors.append("Reparto non valido.")
        else:
            errors.append("Il reparto è obbligatorio.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            if prodotto is None:
                prodotto = ProdottoChimico()
            prodotto.nome = nome
            prodotto.reparto = reparto
            prodotto.fornitore = request.POST.get("fornitore", "").strip()
            prodotto.produttore = request.POST.get("produttore", "").strip()
            prodotto.famiglia = request.POST.get("famiglia", "").strip()
            prodotto.sottocategoria = request.POST.get("sottocategoria", "").strip()
            prodotto.numero_interno = request.POST.get("numero_interno", "").strip()
            prodotto.codice_prodotto = request.POST.get("codice_prodotto", "").strip()
            prodotto.ubicazione = request.POST.get("ubicazione", "").strip()
            prodotto.quantita_presente = request.POST.get("quantita_presente", "").strip()
            prodotto.attivo = bool(request.POST.get("attivo"))
            prodotto.save()

            dpi_ids = request.POST.getlist("dpi_obbligatori")
            prodotto.dpi_obbligatori.set(dpi_ids) if dpi_ids else prodotto.dpi_obbligatori.clear()

            messages.success(request, "Prodotto salvato.")
            return redirect("schede_sicurezza:prodotto_detail", pk=prodotto.pk)

    return render(request, "schede_sicurezza/pages/prodotto_form.html", {
        "prodotto": prodotto,
        "reparti": Reparto.objects.filter(is_active=True).order_by("nome"),
        "categorie_dpi": CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome"),
    })


@login_required
def prodotto_detail(request, pk: int):
    if not _can_view(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    prodotto = get_object_or_404(ProdottoChimico.objects.select_related("reparto"), pk=pk)

    if request.method == "POST":
        if not _can_gestire(request):
            messages.error(request, "Accesso non autorizzato.")
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        pdf_file = request.FILES.get("pdf")
        versione = request.POST.get("versione", "").strip()
        if not pdf_file:
            messages.error(request, "Seleziona un file PDF.")
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        try:
            validate_extension_and_mime(
                pdf_file,
                allowed_extensions=SDS_ALLOWED_EXTENSIONS,
                allowed_mimes=SDS_ALLOWED_MIMES,
                max_bytes=SDS_MAX_BYTES,
                allow_empty=False,
            )
        except UploadMimeValidationError as exc:
            messages.error(request, str(exc))
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        nuova_scheda = SchedaSicurezza.objects.create(
            prodotto=prodotto,
            pdf=pdf_file,
            versione=versione,
            caricata_da=request.user,
            is_corrente=True,
        )
        try:
            estrai_sds(nuova_scheda)
        except Exception:
            logger.exception("Estrazione SDS fallita per scheda %s", nuova_scheda.pk)

        messages.success(request, "Nuova versione della scheda caricata.")
        return redirect("schede_sicurezza:prodotto_detail", pk=pk)

    schede = prodotto.schede.order_by("-data_caricamento")
    return render(request, "schede_sicurezza/pages/prodotto_detail.html", {
        "prodotto": prodotto,
        "schede": schede,
        "scheda_corrente": prodotto.scheda_corrente(),
        "can_gestire": _can_gestire(request),
        "qr_url": request.build_absolute_uri(
            reverse("schede_sicurezza:scheda_mobile", args=[str(prodotto.uuid)])
        ),
    })


@login_required
def prodotto_qr(request, pk: int):
    if not _can_view(request):
        raise Http404()
    prodotto = get_object_or_404(ProdottoChimico, pk=pk)
    url = request.build_absolute_uri(
        reverse("schede_sicurezza:scheda_mobile", args=[str(prodotto.uuid)])
    )
    return HttpResponse(genera_qr_png(url), content_type="image/png")


# ---------------------------------------------------------------------------
# Vista mobile (QR) + download PDF + presa visione
# ---------------------------------------------------------------------------

@login_required
def scheda_mobile(request, uuid):
    # Gated dietro login + ACL v2 (default sicuro, vedi RECON §5): un'eventuale
    # variante a token pubblico non indicizzabile per scansione da dispositivo
    # non loggato è predisposta a livello di URL (uuid, non PK) ma non attivata.
    if not _can_view(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    prodotto = get_object_or_404(ProdottoChimico, uuid=uuid, attivo=True)
    scheda = prodotto.scheda_corrente()
    if scheda is None:
        raise Http404("Nessuna scheda di sicurezza corrente per questo prodotto.")

    gia_presa_visione = PresaVisioneScheda.objects.filter(
        scheda=scheda, operatore=request.user
    ).exists()
    return render(request, "schede_sicurezza/pages/scheda_mobile.html", {
        "prodotto": prodotto,
        "scheda": scheda,
        "gia_presa_visione": gia_presa_visione,
    })


@login_required
def scheda_download(request, pk: int):
    if not _can_view(request):
        raise Http404()
    scheda = get_object_or_404(SchedaSicurezza.objects.select_related("prodotto"), pk=pk)
    try:
        fh = scheda.pdf.open("rb")
    except Exception:
        raise Http404("File non disponibile.")
    filename = f"{scheda.prodotto.nome}_v{scheda.versione or scheda.pk}.pdf"
    return FileResponse(fh, content_type="application/pdf", filename=filename)


@login_required
@require_POST
def presa_visione_conferma(request, scheda_pk: int):
    if not _can_view(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    scheda = get_object_or_404(SchedaSicurezza.objects.select_related("prodotto"), pk=scheda_pk)
    note = request.POST.get("note", "").strip()
    _, created = PresaVisioneScheda.objects.get_or_create(
        scheda=scheda, operatore=request.user, defaults={"note": note},
    )
    if created:
        messages.success(request, "Presa visione registrata.")
    else:
        messages.info(request, "Presa visione già registrata per questa versione.")

    if getattr(request, "htmx", False):
        return render(request, "schede_sicurezza/partials/_presa_visione_stato.html", {
            "gia_presa_visione": True,
        })
    return redirect("schede_sicurezza:scheda_mobile", uuid=scheda.prodotto.uuid)


@login_required
def presa_visione_list(request, scheda_pk: int):
    if not _can_gestire(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")
    scheda = get_object_or_404(SchedaSicurezza.objects.select_related("prodotto"), pk=scheda_pk)
    prese = scheda.prese_visione.select_related("operatore").order_by("-data_presa_visione")
    return render(request, "schede_sicurezza/pages/presa_visione_list.html", {
        "scheda": scheda,
        "prese": prese,
    })


# ---------------------------------------------------------------------------
# Report compliance SDS
# ---------------------------------------------------------------------------

@login_required
def report_compliance(request):
    if not _can_gestire(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    formato = request.GET.get("formato", "").strip()
    sezione = request.GET.get("sezione", "").strip()

    if formato == "csv" and sezione == "gap":
        return _csv_gap_sds(prodotti_senza_scheda_corrente())
    if formato == "csv" and sezione == "matrice":
        return _csv_matrice_presa_visione(matrice_presa_visione())

    return render(request, "schede_sicurezza/pages/report_compliance.html", {
        "gap": prodotti_senza_scheda_corrente(),
        "matrice": matrice_presa_visione(),
    })


def _csv_gap_sds(prodotti):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="schede_sicurezza_gap_sds.csv"'
    writer = csv.writer(response)
    writer.writerow(["Prodotto", "Reparto", "Fornitore"])
    for p in prodotti:
        writer.writerow([p.nome, p.reparto.nome, p.fornitore])
    return response


def _csv_matrice_presa_visione(reparti):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="schede_sicurezza_matrice_presa_visione.csv"'
    writer = csv.writer(response)
    writer.writerow(["Reparto", "Prodotto", "Versione scheda", "Dipendenti totali", "Confermati", "Percentuale"])
    for reparto in reparti:
        for riga in reparto.righe:
            percentuale = "n/d" if riga.percentuale is None else f"{riga.percentuale}%"
            writer.writerow([
                reparto.reparto_nome, riga.prodotto_nome, riga.scheda_versione,
                riga.totale_dipendenti, riga.confermati, percentuale,
            ])
    return response
