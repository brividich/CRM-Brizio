from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.contact_people import parse_contact_people, primary_contact, serialize_contact_people
from core.legacy_utils import is_legacy_admin
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from .models import (
    CategoriaDPI,
    ConsegnaDPI,
    DPIImpostazioni,
    RichiestaDPI,
    RichiestaDPICommento,
    StatoRichiesta,
)

logger = logging.getLogger(__name__)

DPI_CATEGORY_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
DPI_CATEGORY_ALLOWED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/x-ms-bmp",
}
# Guard di copertura policy MIME su tutti i FileField/ImageField del modulo DPI.
DPI_MIME_POLICY_FIELDS = {"CategoriaDPI.immagine"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_gestore(request) -> bool:
    from core.legacy_models import UtenteLegacy
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    return request.user.is_superuser or is_legacy_admin(legacy_user)


def _richiedente_info(request) -> dict:
    """Estrae nome, email, reparto del richiedente dall'utente corrente."""
    nome = ""
    email = ""
    reparto = ""
    try:
        from core.legacy_models import AnagraficaDipendente
        ad = AnagraficaDipendente.objects.filter(utente_id=request.user.id).first()
        if ad:
            nome = f"{getattr(ad, 'nome', '') or ''} {getattr(ad, 'cognome', '') or ''}".strip()
            reparto = str(getattr(ad, "reparto", "") or "").strip()
    except Exception:
        pass
    if not nome:
        nome = request.user.get_full_name() or request.user.username
    email = getattr(request.user, "email", "") or ""
    return {"nome": nome, "email": email, "reparto": reparto}


def _legacy_id(request) -> int | None:
    try:
        from core.legacy_models import AnagraficaDipendente
        ad = AnagraficaDipendente.objects.filter(utente_id=request.user.id).first()
        if ad:
            return int(ad.pk)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    is_gestore = _is_gestore(request)

    # KPI globali (visibili al gestore) o personali (utente)
    if is_gestore:
        qs_all = RichiestaDPI.objects.select_related("categoria")
    else:
        qs_all = RichiestaDPI.objects.filter(
            created_by=request.user
        ).select_related("categoria")

    n_totale = qs_all.count()
    n_inviate = qs_all.filter(stato=StatoRichiesta.INVIATA).count()
    n_approvate = qs_all.filter(stato=StatoRichiesta.APPROVATA).count()
    n_consegnate = qs_all.filter(stato=StatoRichiesta.CONSEGNATA).count()
    n_rifiutate = qs_all.filter(stato=StatoRichiesta.RIFIUTATA).count()

    # Scadenze prossime (entro 30 giorni, solo consegnate)
    oggi = timezone.localdate()
    fra_30 = oggi + timedelta(days=30)
    n_in_scadenza = ConsegnaDPI.objects.filter(
        data_scadenza_stimata__isnull=False,
        data_scadenza_stimata__lte=fra_30,
        data_scadenza_stimata__gte=oggi,
        richiesta__stato=StatoRichiesta.CONSEGNATA,
    ).count()
    n_scadute = ConsegnaDPI.objects.filter(
        data_scadenza_stimata__isnull=False,
        data_scadenza_stimata__lt=oggi,
        richiesta__stato=StatoRichiesta.CONSEGNATA,
    ).count()

    # Lista ultime richieste
    ultime = qs_all.order_by("-created_at")[:20]

    # Categorie attive (per link rapido nuova richiesta)
    categorie = CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome")

    return render(request, "dpi/pages/dashboard.html", {
        "is_gestore": is_gestore,
        "n_totale": n_totale,
        "n_inviate": n_inviate,
        "n_approvate": n_approvate,
        "n_consegnate": n_consegnate,
        "n_rifiutate": n_rifiutate,
        "n_in_scadenza": n_in_scadenza,
        "n_scadute": n_scadute,
        "ultime": ultime,
        "categorie": categorie,
    })


# ---------------------------------------------------------------------------
# Nuova richiesta
# ---------------------------------------------------------------------------

@login_required
def nuova_richiesta(request):
    categorie = list(CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome"))
    if not categorie:
        messages.warning(request, "Nessuna categoria DPI disponibile. Contatta l'amministratore.")
        return redirect("dpi:dashboard")

    if request.method == "POST":
        cat_id = request.POST.get("categoria_id", "").strip()
        quantita_raw = request.POST.get("quantita", "1").strip()
        motivazione = request.POST.get("motivazione", "").strip()

        errors = []
        categoria = None
        if not cat_id:
            errors.append("Seleziona un tipo di DPI.")
        else:
            try:
                categoria = CategoriaDPI.objects.get(pk=int(cat_id), is_active=True)
            except (CategoriaDPI.DoesNotExist, ValueError):
                errors.append("Categoria DPI non valida.")

        try:
            quantita = max(1, int(quantita_raw))
        except (ValueError, TypeError):
            quantita = 1

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            info = _richiedente_info(request)
            r = RichiestaDPI.objects.create(
                categoria=categoria,
                quantita=quantita,
                motivazione=motivazione,
                stato=StatoRichiesta.INVIATA,
                richiedente_legacy_id=_legacy_id(request),
                richiedente_nome=info["nome"],
                richiedente_email=info["email"],
                richiedente_reparto=info["reparto"],
                created_by=request.user,
            )
            log_action(request, "crea", "dpi", f"Nuova richiesta DPI {r.numero} — {r.categoria}")
            messages.success(request, f"Richiesta {r.numero} inviata correttamente.")
            return redirect("dpi:detail", pk=r.pk)

    return render(request, "dpi/pages/nuova_richiesta.html", {
        "categorie": categorie,
    })


# ---------------------------------------------------------------------------
# Dettaglio richiesta (richiedente)
# ---------------------------------------------------------------------------

@login_required
def richiesta_detail(request, pk: int):
    is_gestore = _is_gestore(request)
    if is_gestore:
        richiesta = get_object_or_404(RichiestaDPI.objects.select_related("categoria", "created_by"), pk=pk)
    else:
        richiesta = get_object_or_404(
            RichiestaDPI.objects.select_related("categoria", "created_by"),
            pk=pk,
            created_by=request.user,
        )
    commenti = richiesta.commenti.filter(is_interno=False).order_by("created_at")
    consegna = getattr(richiesta, "consegna", None)

    return render(request, "dpi/pages/detail.html", {
        "richiesta": richiesta,
        "commenti": commenti,
        "consegna": consegna,
        "is_gestore": is_gestore,
    })


# ---------------------------------------------------------------------------
# Annulla richiesta (richiedente, solo se INVIATA)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def annulla_richiesta(request, pk: int):
    richiesta = get_object_or_404(RichiestaDPI, pk=pk, created_by=request.user)
    if richiesta.stato != StatoRichiesta.INVIATA:
        messages.error(request, "Solo le richieste in stato 'Inviata' possono essere annullate.")
        return redirect("dpi:detail", pk=pk)
    richiesta.stato = StatoRichiesta.ANNULLATA
    richiesta.save(update_fields=["stato", "updated_at"])
    log_action(request, "annulla", "dpi", f"Annullata richiesta DPI {richiesta.numero}")
    messages.success(request, f"Richiesta {richiesta.numero} annullata.")
    return redirect("dpi:dashboard")


# ---------------------------------------------------------------------------
# Storico per utente corrente
# ---------------------------------------------------------------------------

@login_required
def storico(request):
    qs = RichiestaDPI.objects.filter(created_by=request.user).select_related("categoria").order_by("-created_at")

    filtro_stato = request.GET.get("stato", "").strip()
    filtro_cat = request.GET.get("categoria", "").strip()
    if filtro_stato:
        qs = qs.filter(stato=filtro_stato)
    if filtro_cat:
        qs = qs.filter(categoria_id=filtro_cat)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    categorie = CategoriaDPI.objects.filter(is_active=True).order_by("nome")
    stati = StatoRichiesta.choices

    return render(request, "dpi/pages/storico.html", {
        "page_obj": page_obj,
        "categorie": categorie,
        "stati": stati,
        "filtro_stato": filtro_stato,
        "filtro_cat": filtro_cat,
    })


# ---------------------------------------------------------------------------
# Gestione — lista
# ---------------------------------------------------------------------------

@login_required
def gestione_list(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    qs = RichiestaDPI.objects.select_related("categoria").order_by("-created_at")

    filtro_stato = request.GET.get("stato", "").strip()
    filtro_cat = request.GET.get("categoria", "").strip()
    filtro_q = request.GET.get("q", "").strip()

    if filtro_stato:
        qs = qs.filter(stato=filtro_stato)
    if filtro_cat:
        qs = qs.filter(categoria_id=filtro_cat)
    if filtro_q:
        qs = qs.filter(richiedente_nome__icontains=filtro_q)

    n_inviate = RichiestaDPI.objects.filter(stato=StatoRichiesta.INVIATA).count()

    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    categorie = CategoriaDPI.objects.filter(is_active=True).order_by("nome")

    return render(request, "dpi/pages/gestione_list.html", {
        "page_obj": page_obj,
        "categorie": categorie,
        "stati": StatoRichiesta.choices,
        "filtro_stato": filtro_stato,
        "filtro_cat": filtro_cat,
        "filtro_q": filtro_q,
        "n_inviate": n_inviate,
    })


# ---------------------------------------------------------------------------
# Gestione — dettaglio
# ---------------------------------------------------------------------------

@login_required
def gestione_detail(request, pk: int):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    richiesta = get_object_or_404(
        RichiestaDPI.objects.select_related("categoria", "created_by"),
        pk=pk,
    )
    commenti = richiesta.commenti.order_by("created_at")
    consegna = getattr(richiesta, "consegna", None)

    return render(request, "dpi/pages/gestione_detail.html", {
        "richiesta": richiesta,
        "commenti": commenti,
        "consegna": consegna,
        "oggi": timezone.localdate(),
    })


# ---------------------------------------------------------------------------
# Azioni gestione
# ---------------------------------------------------------------------------

@login_required
@require_POST
def approva_richiesta(request, pk: int):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    richiesta = get_object_or_404(RichiestaDPI, pk=pk)
    if richiesta.stato != StatoRichiesta.INVIATA:
        messages.error(request, "Solo le richieste 'Inviate' possono essere approvate.")
        return redirect("dpi:gestione_detail", pk=pk)
    nota = request.POST.get("nota", "").strip()
    richiesta.stato = StatoRichiesta.APPROVATA
    if nota:
        richiesta.note_gestione = nota
    richiesta.save(update_fields=["stato", "note_gestione", "updated_at"])
    if nota:
        RichiestaDPICommento.objects.create(
            richiesta=richiesta,
            autore_nome=request.user.get_full_name() or request.user.username,
            testo=nota,
            is_interno=False,
        )
    log_action(request, "approva", "dpi", f"Approvata richiesta DPI {richiesta.numero}")
    if richiesta.richiedente_legacy_id:
        from core.notifiche import invia_notifica
        from django.urls import reverse
        invia_notifica(
            legacy_user_id=richiesta.richiedente_legacy_id,
            tipo="dpi_approvata",
            messaggio=f"La tua richiesta {richiesta.numero} ({richiesta.categoria.nome}) è stata approvata.",
            url_azione=reverse("dpi:detail", args=[richiesta.pk]),
        )
    messages.success(request, f"Richiesta {richiesta.numero} approvata.")
    return redirect("dpi:gestione_detail", pk=pk)


@login_required
@require_POST
def rifiuta_richiesta(request, pk: int):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    richiesta = get_object_or_404(RichiestaDPI, pk=pk)
    if richiesta.stato not in (StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA):
        messages.error(request, "Stato non valido per il rifiuto.")
        return redirect("dpi:gestione_detail", pk=pk)
    motivazione = request.POST.get("motivazione", "").strip()
    richiesta.stato = StatoRichiesta.RIFIUTATA
    if motivazione:
        richiesta.note_gestione = motivazione
    richiesta.save(update_fields=["stato", "note_gestione", "updated_at"])
    if motivazione:
        RichiestaDPICommento.objects.create(
            richiesta=richiesta,
            autore_nome=request.user.get_full_name() or request.user.username,
            testo=f"Rifiutata: {motivazione}",
            is_interno=False,
        )
    log_action(request, "rifiuta", "dpi", f"Rifiutata richiesta DPI {richiesta.numero}")
    if richiesta.richiedente_legacy_id:
        from core.notifiche import invia_notifica
        from django.urls import reverse
        invia_notifica(
            legacy_user_id=richiesta.richiedente_legacy_id,
            tipo="dpi_rifiutata",
            messaggio=f"La tua richiesta {richiesta.numero} ({richiesta.categoria.nome}) è stata rifiutata.",
            url_azione=reverse("dpi:detail", args=[richiesta.pk]),
        )
    messages.success(request, f"Richiesta {richiesta.numero} rifiutata.")
    return redirect("dpi:gestione_detail", pk=pk)


@login_required
@require_POST
def consegna_richiesta(request, pk: int):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    richiesta = get_object_or_404(RichiestaDPI.objects.select_related("categoria"), pk=pk)
    if richiesta.stato not in (StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA):
        messages.error(request, "Stato non valido per la consegna.")
        return redirect("dpi:gestione_detail", pk=pk)

    data_str = request.POST.get("data_consegna", "").strip()
    note = request.POST.get("note_consegna", "").strip()
    firmato = bool(request.POST.get("firmato_ricevuta"))

    if not data_str:
        messages.error(request, "Inserisci la data di consegna.")
        return redirect("dpi:gestione_detail", pk=pk)

    from datetime import date
    try:
        data_consegna = date.fromisoformat(data_str)
    except ValueError:
        messages.error(request, "Data di consegna non valida.")
        return redirect("dpi:gestione_detail", pk=pk)

    # Calcola scadenza automatica da vita utile categoria
    scadenza = None
    vita_utile = richiesta.categoria.vita_utile_giorni
    if vita_utile:
        scadenza = data_consegna + timedelta(days=vita_utile)

    # Gestisci override manuale scadenza
    scadenza_override_str = request.POST.get("data_scadenza_stimata", "").strip()
    if scadenza_override_str:
        try:
            scadenza = date.fromisoformat(scadenza_override_str)
        except ValueError:
            pass

    ConsegnaDPI.objects.update_or_create(
        richiesta=richiesta,
        defaults={
            "data_consegna": data_consegna,
            "consegnato_da_nome": request.user.get_full_name() or request.user.username,
            "note_consegna": note,
            "firmato_ricevuta": firmato,
            "data_scadenza_stimata": scadenza,
        },
    )
    richiesta.stato = StatoRichiesta.CONSEGNATA
    richiesta.save(update_fields=["stato", "updated_at"])
    log_action(request, "consegna", "dpi", f"Consegnato DPI {richiesta.numero} in data {data_consegna}")
    if richiesta.richiedente_legacy_id:
        from core.notifiche import invia_notifica
        from django.urls import reverse
        invia_notifica(
            legacy_user_id=richiesta.richiedente_legacy_id,
            tipo="dpi_consegnata",
            messaggio=f"Il tuo {richiesta.categoria.nome} ({richiesta.numero}) è stato consegnato il {data_consegna.strftime('%d/%m/%Y')}.",
            url_azione=reverse("dpi:detail", args=[richiesta.pk]),
        )
    messages.success(request, f"Consegna DPI {richiesta.numero} registrata.")
    return redirect("dpi:gestione_detail", pk=pk)


@login_required
@require_POST
def aggiungi_commento(request, pk: int):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    richiesta = get_object_or_404(RichiestaDPI, pk=pk)
    testo = request.POST.get("testo", "").strip()
    is_interno = bool(request.POST.get("is_interno"))
    if testo:
        RichiestaDPICommento.objects.create(
            richiesta=richiesta,
            autore_nome=request.user.get_full_name() or request.user.username,
            testo=testo,
            is_interno=is_interno,
        )
    return redirect("dpi:gestione_detail", pk=pk)


# ---------------------------------------------------------------------------
# Impostazioni
# ---------------------------------------------------------------------------

@login_required
def impostazioni(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    impost = DPIImpostazioni.get_singleton()

    if request.method == "POST" and request.POST.get("action") == "save_impostazioni":
        responsabili = parse_contact_people(request.POST.get("responsabili_raw", ""))
        primary = primary_contact(responsabili)
        impost.responsabili = responsabili
        impost.responsabile_nome = primary["nome"]
        impost.responsabile_email = primary["email"]
        impost.note_generali = request.POST.get("note_generali", "").strip()
        impost.notifica_nuova_richiesta = bool(request.POST.get("notifica_nuova_richiesta"))
        impost.notifica_email_extra = request.POST.get("notifica_email_extra", "").strip()
        impost.save()
        log_action(request, "modifica", "dpi", "Aggiornate impostazioni DPI")
        messages.success(request, "Impostazioni salvate.")
        return redirect("dpi:impostazioni")

    categorie = CategoriaDPI.objects.all().order_by("order_index", "nome")

    return render(request, "dpi/pages/impostazioni.html", {
        "impost": impost,
        "categorie": categorie,
        "responsabili_raw": serialize_contact_people(
            impost.responsabili,
            fallback_name=impost.responsabile_nome,
            fallback_email=impost.responsabile_email,
        ),
    })


@login_required
def categoria_edit(request, pk: int | None = None):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    if pk:
        cat = get_object_or_404(CategoriaDPI, pk=pk)
    else:
        cat = None

    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        if not nome:
            messages.error(request, "Il nome è obbligatorio.")
            return redirect("dpi:impostazioni")

        data = {
            "nome": nome,
            "descrizione": request.POST.get("descrizione", "").strip(),
            "icona_emoji": request.POST.get("icona_emoji", "🦺").strip() or "🦺",
            "vita_utile_giorni": int(request.POST.get("vita_utile_giorni") or 0) or None,
            "unita_misura": request.POST.get("unita_misura", "pz").strip() or "pz",
            "scorta_minima": int(request.POST.get("scorta_minima") or 0),
            "is_active": bool(request.POST.get("is_active")),
            "order_index": int(request.POST.get("order_index") or 0),
        }
        uploaded_image = request.FILES.get("immagine")
        if uploaded_image is not None:
            try:
                validate_extension_and_mime(
                    uploaded_image,
                    allowed_extensions=DPI_CATEGORY_ALLOWED_IMAGE_EXTENSIONS,
                    allowed_mimes=DPI_CATEGORY_ALLOWED_IMAGE_MIMES,
                    label=uploaded_image.name or "Immagine categoria",
                )
            except UploadMimeValidationError as exc:
                messages.error(request, str(exc))
                return redirect("dpi:impostazioni")

        if cat:
            for k, v in data.items():
                setattr(cat, k, v)
            if uploaded_image is not None:
                cat.immagine = uploaded_image
            cat.save()
            log_action(request, "modifica", "dpi", f"Modificata categoria DPI: {cat.nome}")
            messages.success(request, f"Categoria '{cat.nome}' aggiornata.")
        else:
            cat = CategoriaDPI(**data)
            if uploaded_image is not None:
                cat.immagine = uploaded_image
            cat.save()
            log_action(request, "crea", "dpi", f"Creata categoria DPI: {cat.nome}")
            messages.success(request, f"Categoria '{cat.nome}' creata.")

        return redirect("dpi:impostazioni")

    impost = DPIImpostazioni.get_singleton()
    return render(request, "dpi/pages/impostazioni.html", {
        "impost": impost,
        "categorie": CategoriaDPI.objects.all().order_by("order_index", "nome"),
        "cat_edit": cat,
        "responsabili_raw": serialize_contact_people(
            impost.responsabili,
            fallback_name=impost.responsabile_nome,
            fallback_email=impost.responsabile_email,
        ),
    })


@login_required
@require_POST
def categoria_elimina(request, pk: int):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    cat = get_object_or_404(CategoriaDPI, pk=pk)
    if cat.richieste.exists():
        messages.error(request, f"Impossibile eliminare '{cat.nome}': esistono richieste associate. Disattivala invece.")
        return redirect("dpi:impostazioni")
    nome = cat.nome
    cat.delete()
    log_action(request, "elimina", "dpi", f"Eliminata categoria DPI: {nome}")
    messages.success(request, f"Categoria '{nome}' eliminata.")
    return redirect("dpi:impostazioni")


# ---------------------------------------------------------------------------
# API JSON categorie (per card-picker AJAX se necessario)
# ---------------------------------------------------------------------------

@login_required
def api_categorie(request):
    cats = CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome")
    data = [
        {
            "id": c.pk,
            "nome": c.nome,
            "descrizione": c.descrizione,
            "icona_emoji": c.icona_emoji,
            "immagine_url": c.immagine_url,
            "vita_utile_giorni": c.vita_utile_giorni,
            "unita_misura": c.unita_misura,
        }
        for c in cats
    ]
    return JsonResponse({"categorie": data})
