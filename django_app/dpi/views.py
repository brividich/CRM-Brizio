from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows
from core.contact_people import parse_contact_people, primary_contact, serialize_contact_people
from core.legacy_utils import is_legacy_admin
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from .models import (
    CategoriaDPI,
    ConsegnaDPI,
    DPIImpostazioni,
    ModelloDPI,
    RichiestaDPI,
    RichiestaDPICommento,
    StatoRichiesta,
    TagliaDPI,
    TipoDPI,
)

logger = logging.getLogger(__name__)

DPI_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
DPI_ALLOWED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/x-ms-bmp",
}
DPI_CATEGORY_ALLOWED_IMAGE_EXTENSIONS = DPI_ALLOWED_IMAGE_EXTENSIONS
DPI_CATEGORY_ALLOWED_IMAGE_MIMES = DPI_ALLOWED_IMAGE_MIMES
# Guard di copertura policy MIME su tutti i FileField/ImageField del modulo DPI.
DPI_MIME_POLICY_FIELDS = {"CategoriaDPI.immagine", "ModelloDPI.immagine"}


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


def _parse_optional_positive_int(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _catalog_select_related():
    return {
        "tipi": TipoDPI.objects.select_related("categoria").order_by("categoria__order_index", "categoria__nome", "ordine", "nome"),
        "modelli": ModelloDPI.objects.select_related("tipo", "tipo__categoria").order_by("tipo__categoria__order_index", "tipo__ordine", "codice", "nome"),
        "taglie": TagliaDPI.objects.select_related("modello", "modello__tipo", "modello__tipo__categoria").order_by("modello__tipo__categoria__order_index", "modello__tipo__ordine", "ordine", "valore"),
    }


def _catalog_context(impost: DPIImpostazioni, **extra) -> dict:
    context = {
        "impost": impost,
        "categorie": CategoriaDPI.objects.all().order_by("order_index", "nome"),
        "categorie_attive": CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome"),
        "responsabili_raw": serialize_contact_people(
            impost.responsabili,
            fallback_name=impost.responsabile_nome,
            fallback_email=impost.responsabile_email,
        ),
        **_catalog_select_related(),
    }
    context.update(extra)
    return context


def _validate_uploaded_dpi_image(uploaded_image, label: str) -> str | None:
    if uploaded_image is None:
        return None
    try:
        validate_extension_and_mime(
            uploaded_image,
            allowed_extensions=DPI_ALLOWED_IMAGE_EXTENSIONS,
            allowed_mimes=DPI_ALLOWED_IMAGE_MIMES,
            label=label,
        )
    except UploadMimeValidationError as exc:
        return str(exc)
    return None


def _clean_signature_data_uri(raw: str) -> tuple[str, str | None]:
    value = (raw or "").strip()
    if not value:
        return "", None
    prefix = "data:image/png;base64,"
    if not value.startswith(prefix):
        return "", "La firma deve essere acquisita in formato PNG."
    payload = value[len(prefix):]
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return "", "La firma acquisita non e valida."
    if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        return "", "La firma acquisita non e un PNG valido."
    if len(decoded) > 512 * 1024:
        return "", "La firma supera la dimensione massima consentita."
    return value, None


def _active_catalog_options() -> dict:
    return {
        "tipi_attivi": TipoDPI.objects.filter(is_active=True, categoria__is_active=True)
        .select_related("categoria")
        .order_by("categoria__order_index", "categoria__nome", "ordine", "nome"),
        "modelli_attivi": ModelloDPI.objects.filter(is_active=True, tipo__is_active=True, tipo__categoria__is_active=True)
        .select_related("tipo", "tipo__categoria")
        .order_by("tipo__categoria__order_index", "tipo__ordine", "codice", "nome"),
        "taglie_attive": TagliaDPI.objects.filter(
            is_active=True,
            modello__is_active=True,
            modello__tipo__is_active=True,
            modello__tipo__categoria__is_active=True,
        )
        .select_related("modello", "modello__tipo", "modello__tipo__categoria")
        .order_by("modello__tipo__categoria__order_index", "modello__tipo__ordine", "ordine", "valore"),
    }


def _resolve_richiesta_catalog_selection(post_data) -> tuple[CategoriaDPI | None, TipoDPI | None, ModelloDPI | None, TagliaDPI | None, list[str]]:
    errors: list[str] = []
    categoria = None
    tipo = None
    modello = None
    taglia = None

    cat_id = (post_data.get("categoria_id", "") or "").strip()
    tipo_id = (post_data.get("tipo_dpi_id", "") or "").strip()
    modello_id = (post_data.get("modello_dpi_id", "") or "").strip()
    taglia_id = (post_data.get("taglia_dpi_id", "") or "").strip()

    if cat_id:
        try:
            categoria = CategoriaDPI.objects.get(pk=int(cat_id), is_active=True)
        except (CategoriaDPI.DoesNotExist, ValueError):
            errors.append("Categoria DPI non valida.")

    if tipo_id:
        try:
            tipo = TipoDPI.objects.select_related("categoria").get(pk=int(tipo_id), is_active=True, categoria__is_active=True)
        except (TipoDPI.DoesNotExist, ValueError):
            errors.append("Tipo DPI non valido.")

    if modello_id:
        try:
            modello = ModelloDPI.objects.select_related("tipo", "tipo__categoria").get(
                pk=int(modello_id),
                is_active=True,
                tipo__is_active=True,
                tipo__categoria__is_active=True,
            )
        except (ModelloDPI.DoesNotExist, ValueError):
            errors.append("Modello DPI non valido.")

    if taglia_id:
        try:
            taglia = TagliaDPI.objects.select_related("modello", "modello__tipo", "modello__tipo__categoria").get(
                pk=int(taglia_id),
                is_active=True,
                modello__is_active=True,
                modello__tipo__is_active=True,
                modello__tipo__categoria__is_active=True,
            )
        except (TagliaDPI.DoesNotExist, ValueError):
            errors.append("Taglia DPI non valida.")

    if taglia:
        if modello and taglia.modello_id != modello.pk:
            errors.append("La taglia selezionata non appartiene al modello DPI indicato.")
        else:
            modello = taglia.modello

    if modello:
        if tipo and modello.tipo_id != tipo.pk:
            errors.append("Il modello selezionato non appartiene al tipo DPI indicato.")
        else:
            tipo = modello.tipo

    if tipo:
        if categoria and tipo.categoria_id != categoria.pk:
            errors.append("Il tipo selezionato non appartiene alla categoria DPI indicata.")
        else:
            categoria = tipo.categoria

    if categoria is None and not errors:
        errors.append("Seleziona una categoria DPI.")

    return categoria, tipo, modello, taglia, errors


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    is_gestore = _is_gestore(request)

    # KPI globali (visibili al gestore) o personali (utente)
    if is_gestore:
        qs_all = RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi")
    else:
        qs_all = RichiestaDPI.objects.filter(
            created_by=request.user
        ).select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi")

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
    catalog_options = _active_catalog_options()

    if request.method == "POST":
        quantita_raw = request.POST.get("quantita", "1").strip()
        motivazione = request.POST.get("motivazione", "").strip()
        categoria, tipo_dpi, modello_dpi, taglia_dpi, errors = _resolve_richiesta_catalog_selection(request.POST)

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
                tipo_dpi=tipo_dpi,
                modello_dpi=modello_dpi,
                taglia_dpi=taglia_dpi,
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
        **catalog_options,
    })


# ---------------------------------------------------------------------------
# Dettaglio richiesta (richiedente)
# ---------------------------------------------------------------------------

@login_required
def richiesta_detail(request, pk: int):
    is_gestore = _is_gestore(request)
    if is_gestore:
        richiesta = get_object_or_404(
            RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "created_by"),
            pk=pk,
        )
    else:
        richiesta = get_object_or_404(
            RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "created_by"),
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
    qs = RichiestaDPI.objects.filter(created_by=request.user).select_related(
        "categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "consegna"
    ).order_by("-created_at")

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
# Report conformita
# ---------------------------------------------------------------------------

@login_required
def report_conformita(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    ensure_anagrafica_schema()
    q = request.GET.get("q", "").strip()
    dipendente_id_raw = request.GET.get("dipendente_id", "").strip()
    categoria_id_raw = request.GET.get("categoria_id", "").strip()
    solo_obbligatorie = request.GET.get("solo_obbligatorie", "1") != "0"

    dipendenti = fetch_anagrafica_rows(deduplicate=True)
    dipendenti = [
        row for row in dipendenti
        if row.get("id") and (row.get("attivo") is None or bool(row.get("attivo")))
    ]
    if q:
        q_norm = q.casefold()
        dipendenti = [
            row for row in dipendenti
            if any(
                q_norm in str(row.get(field) or "").casefold()
                for field in ("nome", "cognome", "aliasusername", "reparto", "mansione")
            )
        ]
    dipendenti = sorted(
        dipendenti,
        key=lambda row: (
            str(row.get("cognome") or "").casefold(),
            str(row.get("nome") or "").casefold(),
            str(row.get("aliasusername") or "").casefold(),
        ),
    )[:100]

    categorie_qs = CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome")
    categorie_obbligatorie = categorie_qs.filter(obbligatoria_mansionario=True)
    categorie_report = categorie_obbligatorie if solo_obbligatorie else categorie_qs
    if categoria_id_raw:
        try:
            categorie_report = categorie_report.filter(pk=int(categoria_id_raw))
        except ValueError:
            categorie_report = categorie_report.none()

    dipendente = None
    righe_report = []
    conforme = None
    oggi = timezone.localdate()
    if dipendente_id_raw:
        try:
            dipendente_id = int(dipendente_id_raw)
        except ValueError:
            dipendente_id = None
        for row in fetch_anagrafica_rows(deduplicate=True):
            if str(row.get("id") or "") == dipendente_id_raw:
                dipendente = row
                break
        if dipendente and dipendente_id:
            consegne = (
                ConsegnaDPI.objects.filter(
                    richiesta__richiedente_legacy_id=dipendente_id,
                    richiesta__stato=StatoRichiesta.CONSEGNATA,
                )
                .select_related("richiesta", "richiesta__categoria", "richiesta__tipo_dpi", "richiesta__modello_dpi", "richiesta__taglia_dpi")
                .order_by("richiesta__categoria_id", "-data_consegna", "-created_at")
            )
            consegna_per_categoria = {}
            for consegna in consegne:
                consegna_per_categoria.setdefault(consegna.richiesta.categoria_id, consegna)

            for categoria in categorie_report:
                consegna = consegna_per_categoria.get(categoria.pk)
                stato = "mancante"
                if consegna:
                    stato = "ok"
                    if consegna.data_scadenza_stimata and consegna.data_scadenza_stimata < oggi:
                        stato = "scaduto"
                righe_report.append({
                    "categoria": categoria,
                    "consegna": consegna,
                    "stato": stato,
                })
            conforme = bool(righe_report) and all(row["stato"] == "ok" for row in righe_report)

    return render(request, "dpi/pages/report_conformita.html", {
        "dipendenti": dipendenti,
        "dipendente": dipendente,
        "categorie": categorie_qs,
        "categorie_obbligatorie": categorie_obbligatorie,
        "righe_report": righe_report,
        "conforme": conforme,
        "q": q,
        "dipendente_id": dipendente_id_raw,
        "categoria_id": categoria_id_raw,
        "solo_obbligatorie": solo_obbligatorie,
    })


# ---------------------------------------------------------------------------
# Gestione — lista
# ---------------------------------------------------------------------------

@login_required
def gestione_list(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    qs = RichiestaDPI.objects.select_related(
        "categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "consegna"
    ).order_by("-created_at")

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
        RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "created_by"),
        pk=pk,
    )
    commenti = richiesta.commenti.order_by("created_at")
    consegna = getattr(richiesta, "consegna", None)
    vita_utile_consegna = (
        richiesta.modello_dpi.effective_vita_utile_giorni
        if richiesta.modello_dpi
        else richiesta.categoria.vita_utile_giorni
    )

    return render(request, "dpi/pages/gestione_detail.html", {
        "richiesta": richiesta,
        "commenti": commenti,
        "consegna": consegna,
        "oggi": timezone.localdate(),
        "vita_utile_consegna": vita_utile_consegna,
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
    richiesta = get_object_or_404(
        RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi"),
        pk=pk,
    )
    if richiesta.stato not in (StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA):
        messages.error(request, "Stato non valido per la consegna.")
        return redirect("dpi:gestione_detail", pk=pk)

    data_str = request.POST.get("data_consegna", "").strip()
    note = request.POST.get("note_consegna", "").strip()
    firmato = bool(request.POST.get("firmato_ricevuta"))
    firma_immagine, firma_error = _clean_signature_data_uri(request.POST.get("firma_immagine", ""))
    if firma_error:
        messages.error(request, firma_error)
        return redirect("dpi:gestione_detail", pk=pk)
    if firma_immagine:
        firmato = True

    if not data_str:
        messages.error(request, "Inserisci la data di consegna.")
        return redirect("dpi:gestione_detail", pk=pk)

    from datetime import date
    try:
        data_consegna = date.fromisoformat(data_str)
    except ValueError:
        messages.error(request, "Data di consegna non valida.")
        return redirect("dpi:gestione_detail", pk=pk)

    # Calcola scadenza automatica da vita utile modello, se presente, altrimenti categoria.
    scadenza = None
    vita_utile = (
        richiesta.modello_dpi.effective_vita_utile_giorni
        if richiesta.modello_dpi
        else richiesta.categoria.vita_utile_giorni
    )
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
            "firma_immagine": firma_immagine,
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

    return render(request, "dpi/pages/impostazioni.html", _catalog_context(impost))


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
            "vita_utile_giorni": _parse_optional_positive_int(request.POST.get("vita_utile_giorni")),
            "obbligatoria_mansionario": bool(request.POST.get("obbligatoria_mansionario")),
            "unita_misura": request.POST.get("unita_misura", "pz").strip() or "pz",
            "scorta_minima": _parse_optional_positive_int(request.POST.get("scorta_minima")) or 0,
            "is_active": bool(request.POST.get("is_active")),
            "order_index": _parse_optional_positive_int(request.POST.get("order_index")) or 0,
        }
        uploaded_image = request.FILES.get("immagine")
        image_error = _validate_uploaded_dpi_image(
            uploaded_image,
            uploaded_image.name if uploaded_image else "Immagine categoria",
        )
        if image_error:
            messages.error(request, image_error)
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
    return render(request, "dpi/pages/impostazioni.html", _catalog_context(impost, cat_edit=cat))


@login_required
def tipo_edit(request, pk: int | None = None):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    tipo = get_object_or_404(TipoDPI.objects.select_related("categoria"), pk=pk) if pk else None

    if request.method == "POST":
        categoria_id = request.POST.get("categoria_id", "").strip()
        nome = request.POST.get("nome", "").strip()
        if not categoria_id:
            messages.error(request, "La categoria del tipo DPI e obbligatoria.")
            return redirect("dpi:impostazioni")
        if not nome:
            messages.error(request, "Il nome del tipo DPI e obbligatorio.")
            return redirect("dpi:impostazioni")
        try:
            categoria = CategoriaDPI.objects.get(pk=int(categoria_id))
        except (CategoriaDPI.DoesNotExist, ValueError):
            messages.error(request, "Categoria DPI non valida.")
            return redirect("dpi:impostazioni")

        duplicate = TipoDPI.objects.filter(categoria=categoria, nome=nome)
        if tipo:
            duplicate = duplicate.exclude(pk=tipo.pk)
        if duplicate.exists():
            messages.error(request, "Esiste gia un tipo DPI con questo nome nella categoria selezionata.")
            return redirect("dpi:impostazioni")

        data = {
            "categoria": categoria,
            "nome": nome,
            "descrizione": request.POST.get("descrizione", "").strip(),
            "ordine": _parse_optional_positive_int(request.POST.get("ordine")) or 0,
            "is_active": bool(request.POST.get("is_active")),
        }
        if tipo:
            for key, value in data.items():
                setattr(tipo, key, value)
            tipo.save()
            log_action(request, "modifica", "dpi", f"Modificato tipo DPI: {tipo.nome}")
            messages.success(request, f"Tipo '{tipo.nome}' aggiornato.")
        else:
            tipo = TipoDPI.objects.create(**data)
            log_action(request, "crea", "dpi", f"Creato tipo DPI: {tipo.nome}")
            messages.success(request, f"Tipo '{tipo.nome}' creato.")
        return redirect("dpi:impostazioni")

    impost = DPIImpostazioni.get_singleton()
    return render(request, "dpi/pages/impostazioni.html", _catalog_context(impost, tipo_edit=tipo))


@login_required
def modello_edit(request, pk: int | None = None):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    modello = get_object_or_404(ModelloDPI.objects.select_related("tipo", "tipo__categoria"), pk=pk) if pk else None

    if request.method == "POST":
        tipo_id = request.POST.get("tipo_id", "").strip()
        codice = request.POST.get("codice", "").strip()
        nome = request.POST.get("nome", "").strip()
        if not tipo_id:
            messages.error(request, "Il tipo del modello DPI e obbligatorio.")
            return redirect("dpi:impostazioni")
        if not codice:
            messages.error(request, "Il codice del modello DPI e obbligatorio.")
            return redirect("dpi:impostazioni")
        if not nome:
            messages.error(request, "Il nome del modello DPI e obbligatorio.")
            return redirect("dpi:impostazioni")
        try:
            tipo = TipoDPI.objects.select_related("categoria").get(pk=int(tipo_id))
        except (TipoDPI.DoesNotExist, ValueError):
            messages.error(request, "Tipo DPI non valido.")
            return redirect("dpi:impostazioni")

        duplicate = ModelloDPI.objects.filter(codice=codice)
        if modello:
            duplicate = duplicate.exclude(pk=modello.pk)
        if duplicate.exists():
            messages.error(request, "Esiste gia un modello DPI con questo codice.")
            return redirect("dpi:impostazioni")

        uploaded_image = request.FILES.get("immagine")
        image_error = _validate_uploaded_dpi_image(
            uploaded_image,
            uploaded_image.name if uploaded_image else "Immagine modello",
        )
        if image_error:
            messages.error(request, image_error)
            return redirect("dpi:impostazioni")

        data = {
            "tipo": tipo,
            "codice": codice,
            "nome": nome,
            "produttore": request.POST.get("produttore", "").strip(),
            "descrizione": request.POST.get("descrizione", "").strip(),
            "vita_utile_giorni": _parse_optional_positive_int(request.POST.get("vita_utile_giorni")),
            "is_active": bool(request.POST.get("is_active")),
        }
        try:
            if modello:
                for key, value in data.items():
                    setattr(modello, key, value)
                if uploaded_image is not None:
                    modello.immagine = uploaded_image
                modello.save()
                log_action(request, "modifica", "dpi", f"Modificato modello DPI: {modello.codice}")
                messages.success(request, f"Modello '{modello.codice}' aggiornato.")
            else:
                modello = ModelloDPI(**data)
                if uploaded_image is not None:
                    modello.immagine = uploaded_image
                modello.save()
                log_action(request, "crea", "dpi", f"Creato modello DPI: {modello.codice}")
                messages.success(request, f"Modello '{modello.codice}' creato.")
        except IntegrityError:
            messages.error(request, "Esiste gia un modello DPI con questo codice.")
        return redirect("dpi:impostazioni")

    impost = DPIImpostazioni.get_singleton()
    return render(request, "dpi/pages/impostazioni.html", _catalog_context(impost, modello_edit=modello))


@login_required
def taglia_edit(request, pk: int | None = None):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    taglia = get_object_or_404(
        TagliaDPI.objects.select_related("modello", "modello__tipo", "modello__tipo__categoria"),
        pk=pk,
    ) if pk else None

    if request.method == "POST":
        modello_id = request.POST.get("modello_id", "").strip()
        valore = request.POST.get("valore", "").strip()
        if not modello_id:
            messages.error(request, "Il modello della taglia DPI e obbligatorio.")
            return redirect("dpi:impostazioni")
        if not valore:
            messages.error(request, "Il valore della taglia DPI e obbligatorio.")
            return redirect("dpi:impostazioni")
        try:
            modello = ModelloDPI.objects.select_related("tipo", "tipo__categoria").get(pk=int(modello_id))
        except (ModelloDPI.DoesNotExist, ValueError):
            messages.error(request, "Modello DPI non valido.")
            return redirect("dpi:impostazioni")

        duplicate = TagliaDPI.objects.filter(modello=modello, valore=valore)
        if taglia:
            duplicate = duplicate.exclude(pk=taglia.pk)
        if duplicate.exists():
            messages.error(request, "Esiste gia questa taglia per il modello selezionato.")
            return redirect("dpi:impostazioni")

        data = {
            "modello": modello,
            "valore": valore,
            "ordine": _parse_optional_positive_int(request.POST.get("ordine")) or 0,
            "is_active": bool(request.POST.get("is_active")),
        }
        if taglia:
            for key, value in data.items():
                setattr(taglia, key, value)
            taglia.save()
            log_action(request, "modifica", "dpi", f"Modificata taglia DPI: {taglia.valore}")
            messages.success(request, f"Taglia '{taglia.valore}' aggiornata.")
        else:
            taglia = TagliaDPI.objects.create(**data)
            log_action(request, "crea", "dpi", f"Creata taglia DPI: {taglia.valore}")
            messages.success(request, f"Taglia '{taglia.valore}' creata.")
        return redirect("dpi:impostazioni")

    impost = DPIImpostazioni.get_singleton()
    return render(request, "dpi/pages/impostazioni.html", _catalog_context(impost, taglia_edit=taglia))


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
            "obbligatoria_mansionario": c.obbligatoria_mansionario,
            "unita_misura": c.unita_misura,
        }
        for c in cats
    ]
    return JsonResponse({"categorie": data})
