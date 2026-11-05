from __future__ import annotations

import base64
import binascii
import json
import logging
import mimetypes
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.acl_v2 import request_has_permission_code
from core.audit import log_action
from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows
from core.contact_people import parse_contact_people, primary_contact, serialize_contact_people
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.operational_roles import get_legacy_anagrafica_id
from core.permessi import decisione, puo_fare, sistema_ruoli_attivo, utenti_visibili
from core.permessi.identita import anagrafiche_di_utenti, utente_da_anagrafica
from core.permessi.negato import risposta_negata
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from . import dotazione as dotazione_dpi
from . import flusso, magazzino
from . import report as report_dpi
from .acl_bootstrap import PERM_DPI_MANAGE

from .models import (
    ICONE_DPI_DISPONIBILI,
    CategoriaDPI,
    ConsegnaDPI,
    DocumentoDPI,
    MovimentoMagazzinoDPI,
    DPIImpostazioni,
    ModalitaNegozio,
    ModelloDPI,
    RichiestaDPI,
    RichiestaDPICommento,
    StatoRichiesta,
    TagliaDPI,
    TipoDPI,
    normalizza_icona_dpi,
)
from core import naming
from core.upload_limits import DOCUMENT_MAX_BYTES
from core.permessi.impostazioni import impostazioni_o

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
DPI_DOCUMENT_ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png"}
DPI_DOCUMENT_ALLOWED_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",
    "application/x-ole-storage",
    "application/cdfv2",
    "image/jpeg",
    "image/png",
}
DPI_DOCUMENT_MAX_BYTES = DOCUMENT_MAX_BYTES
DPI_CATEGORY_ALLOWED_IMAGE_EXTENSIONS = DPI_ALLOWED_IMAGE_EXTENSIONS
DPI_CATEGORY_ALLOWED_IMAGE_MIMES = DPI_ALLOWED_IMAGE_MIMES
# Guard di copertura policy MIME su tutti i FileField/ImageField del modulo DPI.
DPI_MIME_POLICY_FIELDS = {"CategoriaDPI.immagine", "ModelloDPI.immagine", "DocumentoDPI.file", "FatturaNegozioDPI.file"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODULO = "dpi"


def _anagrafiche_visibili(request, azione: str) -> set[int] | None:
    """Ruoli attivi: id anagrafica dei richiedenti su cui l'azione e' concessa. None = tutti."""
    ammessi = utenti_visibili(request, MODULO, azione)
    if ammessi is None:
        return None
    return anagrafiche_di_utenti(ammessi)


def _filtro_visibili(request, azione: str = "vedere") -> Q:
    """Q delle richieste visibili con i ruoli attivi (le proprie sempre comprese)."""
    ids = _anagrafiche_visibili(request, azione)
    if ids is None:
        return Q()
    q = _own_richiesta_filter(request) if decisione(request, MODULO, azione).consentito else Q(pk__in=[])
    return q | Q(richiedente_legacy_id__in=list(ids)) if ids else q


def _is_gestore(request) -> bool:
    if request.user.is_superuser:
        return True
    if sistema_ruoli_attivo():
        # Gestire = consegne, magazzino, catalogo, impostazioni (Sicurezza, Magazzino).
        return puo_fare(request, MODULO, "gestire")
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    # ACL v2 canonico: concedibile per ruolo da /admin-portale/acl-canonico/
    # (additivo, fail-closed). Prima il gate era binario e nessun ruolo diverso
    # da "admin" poteva gestire il modulo DPI.
    return request_has_permission_code(request, PERM_DPI_MANAGE)


def _scope_approvatore(request) -> set[int]:
    """Dipendenti (id legacy anagrafica) le cui richieste l'utente approva come responsabile/preposto."""
    if sistema_ruoli_attivo():
        # Ruoli: chi approva e' deciso dalla matrice, il perimetro e' il team d'organigramma.
        ids = _anagrafiche_visibili(request, "approvare")
        if ids is None:
            return set(RichiestaDPI.objects.exclude(richiedente_legacy_id=None).values_list("richiedente_legacy_id", flat=True))
        ids.discard(_legacy_id(request))  # nessuno approva la propria richiesta
        return ids
    return flusso.dipendenti_di_approvatore(_legacy_id(request))


def _can_approve(request, richiesta: RichiestaDPI, *, scope: set[int] | None = None) -> bool:
    """Gestori DPI (ripiego) oppure responsabile/preposto del dipendente della richiesta."""
    if sistema_ruoli_attivo():
        if richiesta.richiedente_legacy_id and richiesta.richiedente_legacy_id == _legacy_id(request):
            return False  # la propria richiesta non si approva
        return puo_fare(request, MODULO, "approvare", richiesta)
    if _is_gestore(request):
        return True
    if not richiesta.richiedente_legacy_id:
        return False
    scope = _scope_approvatore(request) if scope is None else scope
    return int(richiesta.richiedente_legacy_id) in scope


def _archivia_pdf_consegna(request, consegna: ConsegnaDPI) -> None:
    """Genera il PDF del modulo consegna e lo archivia in DocumentoDipendente.

    Idempotente: se per la stessa ConsegnaDPI esiste già un documento lo
    sovrascrive (es. firma aggiunta dopo la consegna iniziale).
    Fail-soft: in caso di errore, logga e prosegue senza bloccare la consegna.
    """
    try:
        from django.core.files.base import ContentFile

        from anagrafica.models import DocumentoDipendente

        from .pdf import render_modulo_consegna_dpi
    except Exception:
        logger.warning("Impossibile importare le dipendenze per archivio PDF consegna DPI", exc_info=True)
        return

    legacy_id = consegna.richiesta.richiedente_legacy_id
    if not legacy_id:
        # niente collegamento moderno al dipendente: salta archivio
        return

    try:
        pdf_bytes = render_modulo_consegna_dpi(consegna)
    except Exception:
        logger.exception("Errore generazione PDF consegna DPI %s", consegna.pk)
        log_action(
            request, "DPI_CONSEGNA_PDF_ERRORE", "dpi",
            f"Errore generazione PDF per consegna {consegna.pk}",
        )
        return

    nome_file = f"consegna_dpi_{consegna.richiesta.numero}_{consegna.data_consegna:%Y%m%d}.pdf"
    descrizione = (
        f"Modulo consegna DPI {consegna.richiesta.numero}"
        f" ({consegna.richiesta.categoria.nome})"
    )

    try:
        doc, created = DocumentoDipendente.objects.get_or_create(
            oggetto_riferimento_tipo="dpi.consegna",
            oggetto_riferimento_id=consegna.pk,
            defaults={
                "legacy_anagrafica_id": legacy_id,
                "tipo": DocumentoDipendente.Tipo.DPI_CONSEGNA,
                "nome_originale": nome_file,
                "tipo_mime": "application/pdf",
                "dimensione_bytes": len(pdf_bytes),
                "descrizione": descrizione,
                "created_by": request.user if request.user.is_authenticated else None,
                "created_by_display": (
                    request.user.get_full_name() or request.user.username
                ) if request.user.is_authenticated else "",
            },
        )
        # In ogni caso (created o aggiornamento) scrivo il file:
        # se la consegna cambia (firma aggiunta, note, scadenza), il PDF
        # deve riflettere lo stato corrente.
        if not created:
            # rimuovo il vecchio file dal disco prima di scrivere il nuovo
            try:
                doc.file.delete(save=False)
            except Exception:
                logger.warning("Impossibile rimuovere il PDF precedente di consegna %s", consegna.pk)
            doc.dimensione_bytes = len(pdf_bytes)
            doc.descrizione = descrizione
        doc.file.save(nome_file, ContentFile(pdf_bytes), save=True)
    except Exception:
        logger.exception("Errore archivio DocumentoDipendente per consegna DPI %s", consegna.pk)
        log_action(
            request, "DPI_CONSEGNA_PDF_ERRORE", "dpi",
            f"Errore archivio DocumentoDipendente per consegna {consegna.pk}",
        )
        return

    log_action(
        request, "DPI_CONSEGNA_PDF_ARCHIVIATO", "dpi",
        f"Archiviato PDF consegna {consegna.richiesta.numero} (doc {doc.pk})",
    )


def _richiedente_info(request, legacy_id: int | None = None) -> dict:
    """Estrae nome, email, reparto del richiedente (default: l'utente corrente)."""
    nome = ""
    email = ""
    reparto = ""
    per_altri = legacy_id is not None and legacy_id != _legacy_id(request)
    try:
        from core.legacy_models import AnagraficaDipendente
        ad = AnagraficaDipendente.objects.filter(
            pk=legacy_id if legacy_id is not None else get_legacy_anagrafica_id(request.user)
        ).first()
        if ad:
            nome = naming.nome_completo(getattr(ad, 'nome', ''), getattr(ad, 'cognome', ''))
            reparto = str(getattr(ad, "reparto", "") or "").strip()
            if per_altri:
                email = (getattr(ad, "email_notifica", "") or "").strip()
    except Exception:
        pass
    if not nome:
        nome = request.user.get_full_name() or request.user.username
    if not per_altri:
        email = getattr(request.user, "email", "") or ""
    return {"nome": nome, "email": email, "reparto": reparto}


def _dipendenti_selezionabili(request) -> list[dict]:
    """Chi si puo' scegliere come richiedente: i propri dipendenti (responsabile/preposto),
    tutti per i gestori DPI. Vuota = nessuna scelta, la richiesta e' sempre personale."""
    try:
        from core.legacy_models import AnagraficaDipendente

        own = _legacy_id(request)
        if _is_gestore(request):
            ids = None
        else:
            ids = _scope_approvatore(request)
            if not ids:
                return []
        qs = AnagraficaDipendente.objects.all()
        if ids is not None:
            qs = qs.filter(pk__in=list(ids | ({own} if own else set())))
        return [
            {"id": ad.pk, "nome": naming.nome_completo(ad.nome, ad.cognome) or ad.aliasusername or f"#{ad.pk}"}
            for ad in qs.order_by("cognome", "nome")
        ]
    except Exception:
        return []


def _legacy_id(request) -> int | None:
    # `AnagraficaDipendente.utente_id` e' l'id di `utenti` (legacy), NON di `auth_user`:
    # il ponte e' `profile.legacy_user_id`, mai `request.user.id` diretto.
    try:
        return get_legacy_anagrafica_id(request.user)
    except Exception:
        return None


def _own_richiesta_filter(request) -> Q:
    """Richieste "proprie" per le viste self-service (storico, dettaglio): per
    `created_by` (richieste fatte dal form) OPPURE per `richiedente_legacy_id`
    (consegne storiche importate via management command, mai legate a un utente
    Django — senza questo OR restano invisibili al dipendente pur essendo sue)."""
    q = Q(created_by=request.user)
    legacy_id = _legacy_id(request)
    if legacy_id:
        q |= Q(richiedente_legacy_id=legacy_id)
    return q


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
        "icone_disponibili": ICONE_DPI_DISPONIBILI,
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
    if sistema_ruoli_attivo():
        # Ruoli: proprie, del team o tutte secondo la visibilita' su «vedere».
        qs_all = RichiestaDPI.objects.filter(_filtro_visibili(request)).select_related(
            "categoria", "tipo_dpi", "modello_dpi", "taglia_dpi"
        )
    elif is_gestore:
        qs_all = RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi")
    else:
        qs_all = RichiestaDPI.objects.filter(
            _own_richiesta_filter(request)
        ).select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi")

    # Lista ultime richieste
    ultime = qs_all.order_by("-created_at")[:20]

    legacy_id = _legacy_id(request)
    return render(request, "dpi/pages/dashboard.html", {
        "is_gestore": is_gestore,
        "is_approvatore": bool(_scope_approvatore(request)),
        "da_fare": _da_fare(request, is_gestore),
        "situazione": dotazione_dpi.dotazione(legacy_id) if legacy_id else None,
        "ultime": ultime,
    })


def _tessera(etichetta: str, n: int, url: str, tono: str, nota: str = "") -> dict:
    return {"etichetta": etichetta, "n": n, "url": url, "tono": tono if n else "zero", "nota": nota}


def _da_fare(request, is_gestore: bool) -> list[dict]:
    """Il lavoro in attesa, ogni numero con il link alla lista che lo mostra uguale."""
    from django.urls import reverse

    consentito, scope = _gestione_scope(request, is_gestore)
    lista = reverse("dpi:gestione_list")
    base = RichiestaDPI.objects.all()
    if scope is not None:
        base = base.filter(richiedente_legacy_id__in=list(scope))
    tessere = []
    if consentito:
        tessere.append(_tessera(
            "In attesa di approvazione", base.filter(stato=StatoRichiesta.INVIATA).count(),
            f"{lista}?stato={StatoRichiesta.INVIATA}", "blu",
        ))
    if is_gestore:
        banco = _banco_queryset(request)
        n_magazzino = banco.filter(categoria__consegna_magazzino=True).count()
        altre = banco.count() - n_magazzino
        tessere.append(_tessera(
            "Da consegnare", n_magazzino, reverse("dpi:banco") + ("" if n_magazzino or not altre else "?tutte=1"), "arancione",
            f"+ {altre} non del magazzino" if altre else "",
        ))
        tessere.append(_tessera("Da riordinare", magazzino.da_riordinare(), reverse("dpi:magazzino"), "arancione"))
        if CategoriaDPI.objects.filter(si_ordina_al_negozio=True, is_active=True).exists():
            from . import negozio

            approvate = _approvate_queryset(request)
            n_ordine = negozio.da_ordinare(approvate).count()
            n_fuori = negozio.fuori_convenzione(approvate).count()
            tessere.append(_tessera(
                "Scarpe da gestire", n_ordine + n_fuori, reverse("dpi:negozio"), "arancione",
                f"{n_ordine} da ordinare · {n_fuori} al negozio" if n_ordine + n_fuori else "",
            ))
    if consentito:
        for chiave, etichetta, tono in (
            (dotazione_dpi.SCADUTI, "DPI scaduti", "rosso"),
            (dotazione_dpi.IN_SCADENZA, f"In scadenza ({dotazione_dpi.GIORNI_AVVISO} gg)", "arancione"),
        ):
            n = base.filter(dotazione_dpi.filtro_scadenza(chiave)).count()
            tessere.append(_tessera(etichetta, n, f"{lista}?scadenza={chiave}", tono))
    return tessere


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

    # Punto 2.1: filtra le categorie al profilo di rischio del richiedente (mansione di
    # rischio a vista). Fuori profilo resta richiedibile con override + motivazione.
    from anagrafica.services import mansionario
    _own_legacy = _legacy_id(request)
    per_conto_di = _dipendenti_selezionabili(request)
    _req_legacy = _own_legacy
    _scelto = _parse_optional_positive_int(request.POST.get("richiedente") if request.method == "POST" else request.GET.get("per"))
    if _scelto and _scelto != _own_legacy:
        if _scelto in {d["id"] for d in per_conto_di}:
            _req_legacy = _scelto
        else:
            messages.error(request, "Non puoi fare richieste per questo dipendente.")
            return redirect("dpi:nuova")
    _profilo = (
        mansionario.requisiti_dipendente(_req_legacy) if _req_legacy
        else mansionario.requisiti_vuoti()
    )
    profilo_ids = {c.pk for c in _profilo["dpi"]}
    profilo_attivo = bool(profilo_ids)  # se vuoto, nessun filtro reale (mostra tutto)
    situazione = dotazione_dpi.dotazione(_req_legacy) if _req_legacy else None
    aiuti = dotazione_dpi.aiuti_per_categoria(situazione) if situazione else {}
    parole: dict[int, list[str]] = {}
    for tipo in catalog_options["tipi_attivi"]:
        parole.setdefault(tipo.categoria_id, []).append(tipo.nome)
    for modello in catalog_options["modelli_attivi"]:
        parole.setdefault(modello.tipo.categoria_id, []).extend([modello.nome, modello.codice])
    for c in categorie:
        c.in_profilo = c.pk in profilo_ids
        c.parole_ricerca = " ".join([c.nome, *parole.get(c.pk, [])])
        c.etichetta_stato = dotazione_dpi.etichetta_categoria(aiuti.get(c.pk))

    dati = request.POST if request.method == "POST" else request.GET
    scelta = {
        "categoria": _parse_optional_positive_int(dati.get("categoria_id") or dati.get("categoria")),
        "tipo": _parse_optional_positive_int(dati.get("tipo_dpi_id") or dati.get("tipo")),
        "modello": _parse_optional_positive_int(dati.get("modello_dpi_id") or dati.get("modello")),
        "taglia": _parse_optional_positive_int(dati.get("taglia_dpi_id") or dati.get("taglia")),
    }
    motivi_precompilati = {"scadenza": "Sostituzione alla scadenza", "prima": "Prima dotazione"}
    testo_motivazione = motivi_precompilati.get(request.GET.get("motivo", ""), "")

    if request.method == "POST":
        testo_motivazione = request.POST.get("motivazione", "")
        quantita_raw = request.POST.get("quantita", "1").strip()
        motivazione = request.POST.get("motivazione", "").strip()
        categoria, tipo_dpi, modello_dpi, taglia_dpi, errors = _resolve_richiesta_catalog_selection(request.POST)

        try:
            quantita = max(1, int(quantita_raw))
        except (ValueError, TypeError):
            quantita = 1

        modalita_negozio = ""
        if categoria is not None and categoria.si_ordina_al_negozio:
            modalita_negozio = request.POST.get("modalita_negozio", "")
            if modalita_negozio not in ModalitaNegozio.values:
                modalita_negozio = ""
                errors.append("Scegli se le scarpe sono in convenzione o fuori convenzione.")

        fuori_profilo = (
            profilo_attivo and categoria is not None and categoria.pk not in profilo_ids
        )
        if fuori_profilo and not motivazione:
            errors.append(
                "Questo DPI è fuori dal profilo di rischio della tua mansione: "
                "indica una motivazione per richiederlo comunque."
            )

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            info = _richiedente_info(request, _req_legacy)
            per_altri = bool(_req_legacy and _req_legacy != _own_legacy)
            note_iniziali = "[Richiesta fuori profilo di rischio]" if fuori_profilo else ""
            if per_altri:
                inserita = request.user.get_full_name() or request.user.username
                note_iniziali = (note_iniziali + " " if note_iniziali else "") + f"[Inserita da {inserita} per conto del dipendente]"
            r = RichiestaDPI.objects.create(
                categoria=categoria,
                tipo_dpi=tipo_dpi,
                modello_dpi=modello_dpi,
                taglia_dpi=taglia_dpi,
                quantita=quantita,
                motivazione=motivazione,
                modalita_negozio=modalita_negozio,
                stato=StatoRichiesta.INVIATA,
                richiedente_legacy_id=_req_legacy,
                richiedente_nome=info["nome"],
                richiedente_email=info["email"],
                richiedente_reparto=info["reparto"],
                note_gestione=note_iniziali,
                created_by=request.user,
            )
            log_action(request, "crea", "dpi", f"Nuova richiesta DPI {r.numero} — {r.categoria}" + (f" (per conto di {info['nome']})" if per_altri else ""))
            # Chi la inserisce e' CAR/preposto (per se' o per un suo dipendente): approvata da sola.
            if _own_legacy and flusso.e_capo_o_preposto(_own_legacy):
                _approva(request, r, "Approvata automaticamente: richiesta inserita da un CAR/preposto.", automatica=True)
                messages.success(request, f"Richiesta {r.numero} approvata automaticamente: il magazzino è stato avvisato.")
                return redirect("dpi:detail", pk=r.pk)
            flusso.notifica_nuova_richiesta(r)
            messages.success(request, f"Richiesta {r.numero} inviata correttamente.")
            return redirect("dpi:detail", pk=r.pk)

    return render(request, "dpi/pages/nuova_richiesta.html", {
        "categorie": categorie,
        "profilo_attivo": profilo_attivo,
        "per_conto_di": per_conto_di,
        "is_gestore": _is_gestore(request),
        "is_approvatore": bool(per_conto_di) or bool(_scope_approvatore(request)),
        "richiedente_scelto": _req_legacy,
        "richiedente_proprio": _own_legacy,
        "aiuti": {str(k): v for k, v in aiuti.items()},
        "scelta": scelta,
        "testo_motivazione": testo_motivazione,
        "quantita_scelta": request.POST.get("quantita", "1") if request.method == "POST" else "1",
        "motivi_rapidi": ("Usura", "Rotto", "Perso", "Prima dotazione", "Cambio taglia"),
        "negozio_nome": DPIImpostazioni.get_singleton().negozio_nome,
        "modalita_scelta": request.POST.get("modalita_negozio", ModalitaNegozio.CONVENZIONE),
        "negozio_giorni": DPIImpostazioni.get_singleton().negozio_giorni_riepilogo,
        **catalog_options,
    })


# ---------------------------------------------------------------------------
# Dettaglio richiesta (richiedente)
# ---------------------------------------------------------------------------

@login_required
def richiesta_detail(request, pk: int):
    is_gestore = _is_gestore(request)
    if sistema_ruoli_attivo():
        richiesta = get_object_or_404(
            RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "created_by"),
            pk=pk,
        )
        if not (richiesta.created_by_id == request.user.id or puo_fare(request, MODULO, "vedere", richiesta)):
            return risposta_negata(
                request, "Questa richiesta non rientra fra quelle che il tuo ruolo ti consente di vedere.", pagina="DPI"
            )
    elif is_gestore:
        richiesta = get_object_or_404(
            RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "created_by"),
            pk=pk,
        )
    else:
        richiesta = get_object_or_404(
            RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "created_by")
            .filter(_own_richiesta_filter(request)),
            pk=pk,
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
    qs = RichiestaDPI.objects.filter(_own_richiesta_filter(request)).select_related(
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

def _scope_report(request) -> set[int] | None:
    """Persone che chi gestisce puo' vedere nei report. None = tutte."""
    return _anagrafiche_visibili(request, "gestire") if sistema_ruoli_attivo() else None


def _dipendenti_attivi(request) -> list[dict]:
    """Dipendenti attivi nel perimetro di chi guarda, in ordine di cognome e nome."""
    ensure_anagrafica_schema()
    scope = _scope_report(request)
    righe = [
        {**row, "nominativo": naming.nome_completo(row.get("nome"), row.get("cognome"))}
        for row in fetch_anagrafica_rows(deduplicate=True)
        if row.get("id")
        and (row.get("attivo") is None or bool(row.get("attivo")))
        and (scope is None or int(row["id"]) in scope)
    ]
    return sorted(righe, key=lambda row: (
        str(row.get("cognome") or "").casefold(),
        str(row.get("nome") or "").casefold(),
        str(row.get("aliasusername") or "").casefold(),
    ))


@login_required
def report_conformita(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    q = request.GET.get("q", "").strip()
    dipendente_id_raw = request.GET.get("dipendente_id", "").strip()
    categoria_id_raw = request.GET.get("categoria_id", "").strip()
    solo_obbligatorie = request.GET.get("solo_obbligatorie", "1") != "0"

    tutti = _dipendenti_attivi(request)
    dipendenti = tutti
    if q:
        q_norm = q.casefold()
        dipendenti = [
            row for row in dipendenti
            if any(
                q_norm in str(row.get(field) or "").casefold()
                for field in ("nome", "cognome", "aliasusername", "reparto", "mansione")
            )
        ]

    categorie_qs = CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome")
    categorie_obbligatorie = categorie_qs.filter(obbligatoria_mansionario=True)

    dipendente = next((row for row in tutti if str(row.get("id") or "") == dipendente_id_raw), None) if dipendente_id_raw else None
    righe_report = []
    conforme = None
    in_scadenza = False
    if dipendente:
        situazione = report_dpi.conformita(
            [dipendente], categoria_id=_int_or_none(categoria_id_raw), tutte_le_categorie=not solo_obbligatorie,
        )["persone"][0]
        righe_report = situazione["righe"]
        conforme = situazione["conforme"]
        in_scadenza = situazione["esito"] == report_dpi.IN_SCADENZA

    if request.GET.get("export") == "xlsx" and dipendente and righe_report:
        from core.excel_export import make_xlsx_response

        _rows = []
        for _r in righe_report:
            _c = _r.get("consegna")
            _scad = (getattr(_c, "scadenza_calcolata", None) or getattr(_c, "data_scadenza_stimata", None)) if _c else None
            _rows.append([
                _r["categoria"].nome,
                _r["origine"],
                _r["etichetta"],
                _c.data_consegna.strftime("%d-%m-%Y") if _c and _c.data_consegna else "",
                _scad.strftime("%d-%m-%Y") if _scad else "",
                _c.richiesta.numero if _c and _c.richiesta_id else "",
            ])
        _nome = naming.nome_completo(dipendente.get('nome'), dipendente.get('cognome')) or "dipendente"
        log_action(request, "dpi_conformita_export_xlsx", "dpi", {
            "dipendente_id": dipendente_id_raw,
            "rows": len(_rows),
        })
        return make_xlsx_response(
            filename=f"conformita-dpi-{_nome.replace(' ', '_')}.xlsx",
            columns=["Categoria", "Perché", "Stato", "Ultima consegna", "Scadenza", "Richiesta"],
            rows=_rows,
            sheet_title="Conformità DPI",
            title=f"Conformità DPI — {_nome}",
        )

    return render(request, "dpi/pages/report_conformita.html", {
        "dipendenti": dipendenti,
        "dipendente": dipendente,
        "categorie": categorie_qs,
        "categorie_obbligatorie": categorie_obbligatorie,
        "righe_report": righe_report,
        "conforme": conforme,
        "in_scadenza": in_scadenza,
        "q": q,
        "dipendente_id": dipendente_id_raw,
        "categoria_id": categoria_id_raw,
        "solo_obbligatorie": solo_obbligatorie,
    })


# ---------------------------------------------------------------------------
# Gestione — lista
# ---------------------------------------------------------------------------

def _gestione_scope(request, is_gestore: bool) -> tuple[bool, set[int] | None]:
    """Coda di lavoro: chi gestisce (consegne) e chi approva, ognuno sul suo perimetro.
    Ritorna (accesso consentito, id dei richiedenti; None = tutti)."""
    if sistema_ruoli_attivo():
        gestire = _anagrafiche_visibili(request, "gestire") if is_gestore else set()
        approvare = _scope_approvatore(request) if decisione(request, MODULO, "approvare").consentito else set()
        if gestire is None:
            return True, None
        scope = set(gestire) | set(approvare)
        return bool(scope), scope
    scope = None if is_gestore else _scope_approvatore(request)
    return (is_gestore or bool(scope)), scope


@login_required
def gestione_list(request):
    is_gestore = _is_gestore(request)
    consentito, scope = _gestione_scope(request, is_gestore)
    if not consentito:
        if sistema_ruoli_attivo():
            return risposta_negata(request, pagina="DPI — gestione richieste")
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    base_qs = RichiestaDPI.objects.all()
    if scope is not None:
        base_qs = base_qs.filter(richiedente_legacy_id__in=list(scope))
    qs = base_qs.select_related(
        "categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "consegna"
    ).order_by("-created_at")

    filtro_stato = request.GET.get("stato", "").strip()
    filtro_cat = request.GET.get("categoria", "").strip()
    filtro_q = request.GET.get("q", "").strip()
    filtro_scadenza = request.GET.get("scadenza", "").strip()
    if filtro_scadenza not in dict(dotazione_dpi.FILTRI_SCADENZA):
        filtro_scadenza = ""

    if filtro_scadenza:
        qs = qs.filter(dotazione_dpi.filtro_scadenza(filtro_scadenza)).order_by("consegna__data_scadenza_stimata")
    if filtro_stato:
        qs = qs.filter(stato=filtro_stato)
    if filtro_cat:
        qs = qs.filter(categoria_id=filtro_cat)
    if filtro_q:
        qs = qs.filter(richiedente_nome__icontains=filtro_q)

    n_inviate = base_qs.filter(stato=StatoRichiesta.INVIATA).count()

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
        "filtro_scadenza": filtro_scadenza,
        "filtri_scadenza": dotazione_dpi.FILTRI_SCADENZA,
        "n_inviate": n_inviate,
        "is_gestore": is_gestore,
        "is_approvatore": True,
    })


# ---------------------------------------------------------------------------
# Gestione — dettaglio
# ---------------------------------------------------------------------------

@login_required
def gestione_detail(request, pk: int):
    is_gestore = _is_gestore(request)
    richiesta = get_object_or_404(
        RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi", "created_by"),
        pk=pk,
    )
    if sistema_ruoli_attivo():
        if not (_can_approve(request, richiesta) or puo_fare(request, MODULO, "gestire", richiesta)):
            return risposta_negata(request, pagina="DPI — gestione richieste")
    elif not _can_approve(request, richiesta):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    commenti = richiesta.commenti.order_by("created_at")
    consegna = getattr(richiesta, "consegna", None)
    vita_utile_consegna = (
        richiesta.modello_dpi.effective_vita_utile_giorni
        if richiesta.modello_dpi
        else richiesta.categoria.vita_utile_giorni
    )

    storico_ai = None
    if richiesta.stato == StatoRichiesta.INVIATA:
        from .ai_richiesta import storico_richiesta

        try:
            storico_ai = storico_richiesta(richiesta)
        except Exception:  # noqa: BLE001 - lo storico e' un aiuto, la pagina deve aprirsi comunque
            logger.exception("Storico richiesta DPI non disponibile")
    return render(request, "dpi/pages/gestione_detail.html", {
        "storico_ai": storico_ai,
        "richiesta": richiesta,
        "commenti": commenti,
        "consegna": consegna,
        "oggi": timezone.localdate(),
        "vita_utile_consegna": vita_utile_consegna,
        "giacenza_modello": magazzino.giacenza(richiesta.modello_dpi_id) if richiesta.modello_dpi_id and not richiesta.modalita_negozio else None,
        "chiedi_motivo_giacenza": richiesta.stato == StatoRichiesta.APPROVATA and bool(magazzino.mancanze([richiesta])),
        "is_gestore": is_gestore,
        "is_approvatore": True,
    })


# ---------------------------------------------------------------------------
# Azioni gestione
# ---------------------------------------------------------------------------

@login_required
@require_POST
def approva_richiesta(request, pk: int):
    richiesta = get_object_or_404(RichiestaDPI, pk=pk)
    if not _can_approve(request, richiesta):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    if richiesta.stato != StatoRichiesta.INVIATA:
        messages.error(request, "Solo le richieste 'Inviate' possono essere approvate.")
        return redirect("dpi:gestione_detail", pk=pk)
    _approva(request, richiesta, request.POST.get("nota", "").strip())
    messages.success(request, f"Richiesta {richiesta.numero} approvata.")
    return redirect("dpi:gestione_detail", pk=pk)


def _notifica_richiedente(richiesta: RichiestaDPI, messaggio: str) -> None:
    if richiesta.richiedente_legacy_id:
        from core.notifiche import invia_notifica
        from django.urls import reverse
        invia_notifica(
            legacy_user_id=utente_da_anagrafica(richiesta.richiedente_legacy_id),
            tipo="dpi_approvata",
            messaggio=messaggio,
            url_azione=reverse("dpi:detail", args=[richiesta.pk]),
        )


def _approva(request, richiesta: RichiestaDPI, nota: str = "", *, automatica: bool = False) -> None:
    """Approva: avviso al magazzino e, se in Impostazioni e' scelto l'avviso
    immediato, la richiesta e' subito «Pronta al ritiro»."""
    richiesta.stato = StatoRichiesta.APPROVATA
    if nota and not automatica:  # l'automatica non copre le note di inserimento
        richiesta.note_gestione = nota
    richiesta.save(update_fields=["stato", "note_gestione", "updated_at"])
    if nota:
        RichiestaDPICommento.objects.create(
            richiesta=richiesta,
            autore_nome="Portale" if automatica else (request.user.get_full_name() or request.user.username),
            testo=nota,
            is_interno=False,
        )
    if automatica:
        log_action(request, "approva", "dpi", f"Approvata automaticamente la richiesta DPI {richiesta.numero} (CAR/preposto)")
    else:
        log_action(request, "approva", "dpi", f"Approvata richiesta DPI {richiesta.numero}")
        from .ai_richiesta import registra_esito

        registra_esito(richiesta, "approvare", user=request.user)
    _notifica_richiedente(richiesta, f"La tua richiesta {richiesta.numero} ({richiesta.categoria.nome}) è stata approvata.")
    flusso.notifica_approvata(richiesta)
    if DPIImpostazioni.get_singleton().avviso_ritiro_all_approvazione and not richiesta.modalita_negozio:
        _segna_pronta(request, richiesta, da_nome="Portale (all'approvazione)")


def _segna_pronta(request, richiesta: RichiestaDPI, *, da_nome: str) -> None:
    richiesta.pronta_ritiro_il = timezone.now()
    richiesta.pronta_ritiro_da_nome = da_nome[:200]
    richiesta.save(update_fields=["pronta_ritiro_il", "pronta_ritiro_da_nome", "updated_at"])
    log_action(request, "pronta_ritiro", "dpi", f"DPI {richiesta.numero} pronto per il ritiro")
    _notifica_richiedente(richiesta, f"Il tuo DPI {richiesta.numero} ({richiesta.categoria.nome}) è pronto: passa {flusso.luogo_ritiro(richiesta)} a ritirarlo.")
    flusso.notifica_pronta_ritiro(richiesta)


@login_required
@require_POST
def pronta_ritiro(request, pk: int):
    """Il magazzino ha preparato il DPI: avvisa il dipendente di passare a ritirarlo."""
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    richiesta = get_object_or_404(RichiestaDPI.objects.select_related("categoria"), pk=pk)
    if richiesta.stato != StatoRichiesta.APPROVATA:
        messages.error(request, "Solo una richiesta approvata e non ancora consegnata può essere pronta per il ritiro.")
        return redirect("dpi:gestione_detail", pk=pk)
    if richiesta.da_gestire_in_negozio:
        messages.info(request, "Queste scarpe si gestiscono dalla pagina Scarpe.")
        return redirect("dpi:negozio")
    gia = richiesta.pronta_ritiro_il is not None
    _segna_pronta(request, richiesta, da_nome=request.user.get_full_name() or request.user.username)
    messages.success(request, f"Il dipendente è stato {'avvisato di nuovo' if gia else 'avvisato'} di passare a ritirare il DPI.")
    return redirect("dpi:gestione_detail", pk=pk)


@login_required
@require_POST
def rifiuta_richiesta(request, pk: int):
    richiesta = get_object_or_404(RichiestaDPI, pk=pk)
    if not _can_approve(request, richiesta):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    if richiesta.stato not in (StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA):
        messages.error(request, "Stato non valido per il rifiuto.")
        return redirect("dpi:gestione_detail", pk=pk)
    motivazione = request.POST.get("motivazione", "").strip()
    era_approvata = richiesta.stato == StatoRichiesta.APPROVATA
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
    from .ai_richiesta import registra_esito

    registra_esito(richiesta, "rifiutare", user=request.user)
    if richiesta.richiedente_legacy_id:
        from core.notifiche import invia_notifica
        from django.urls import reverse
        invia_notifica(
            legacy_user_id=utente_da_anagrafica(richiesta.richiedente_legacy_id),
            tipo="dpi_rifiutata",
            messaggio=f"La tua richiesta {richiesta.numero} ({richiesta.categoria.nome}) è stata rifiutata.",
            url_azione=reverse("dpi:detail", args=[richiesta.pk]),
        )
    if era_approvata:
        flusso.notifica_rifiutata_dopo_approvazione(richiesta)
    messages.success(request, f"Richiesta {richiesta.numero} rifiutata.")
    return redirect("dpi:gestione_detail", pk=pk)


def _sostituisci_consegne_precedenti(request, richiesta: RichiestaDPI, consegna: ConsegnaDPI, data_consegna) -> None:
    """Marca come sostituite le consegne attive dello stesso tipo DPI già in carico
    allo stesso dipendente, così non contano più come "in uso" ma restano in storico."""
    if not richiesta.richiedente_legacy_id:
        return

    precedenti = ConsegnaDPI.objects.filter(
        richiesta__richiedente_legacy_id=richiesta.richiedente_legacy_id,
        richiesta__categoria_id=richiesta.categoria_id,
        richiesta__tipo_dpi_id=richiesta.tipo_dpi_id,
        richiesta__stato=StatoRichiesta.CONSEGNATA,
        sostituita_da__isnull=True,
    ).exclude(richiesta_id=richiesta.pk).select_related("richiesta")

    for vecchia in precedenti:
        vecchia.sostituita_da = consegna
        vecchia.data_sostituzione = data_consegna
        vecchia.save(update_fields=["sostituita_da", "data_sostituzione"])
        RichiestaDPICommento.objects.create(
            richiesta=vecchia.richiesta,
            autore_nome=consegna.consegnato_da_nome,
            testo=f"DPI sostituito dalla nuova consegna {richiesta.numero} del {data_consegna.strftime('%d-%m-%Y')}.",
            is_interno=True,
        )
        log_action(
            request, "modifica", "dpi",
            f"DPI {vecchia.richiesta.numero} sostituito da {richiesta.numero}",
        )


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
    if richiesta.stato != StatoRichiesta.APPROVATA:
        messages.error(request, "La consegna si registra solo dopo l'approvazione del responsabile.")
        return redirect("dpi:gestione_detail", pk=pk)
    if richiesta.da_gestire_in_negozio:
        messages.info(request, "Queste scarpe si gestiscono dalla pagina Scarpe.")
        return redirect("dpi:negozio")

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

    try:
        data_consegna = date.fromisoformat(data_str)
    except ValueError:
        messages.error(request, "Data di consegna non valida.")
        return redirect("dpi:gestione_detail", pk=pk)

    # Override manuale della scadenza (vuoto = calcolata dalla vita utile).
    scadenza_override = None
    scadenza_override_str = request.POST.get("data_scadenza_stimata", "").strip()
    if scadenza_override_str:
        try:
            scadenza_override = date.fromisoformat(scadenza_override_str)
        except ValueError:
            pass

    motivo = request.POST.get("motivo_giacenza", "").strip()[:200]
    mancanze = magazzino.mancanze([richiesta])
    if mancanze and not motivo:
        messages.error(request, _testo_manca_motivo(mancanze))
        return redirect("dpi:gestione_detail", pk=pk)

    residuo = _registra_consegna(
        request, richiesta, data_consegna=data_consegna, note=note, firmato=firmato,
        firma_immagine=firma_immagine, scadenza_override=scadenza_override, motivo_giacenza=motivo if mancanze else "",
    )
    messages.success(request, f"Consegna DPI {richiesta.numero} registrata.")
    _avviso_giacenza(request, richiesta, residuo)
    if not firmato:
        _chiedi_conferma(request, [richiesta.consegna])
    return redirect("dpi:gestione_detail", pk=pk)


def _testo_manca_motivo(mancanze: list[dict]) -> str:
    elenco = ", ".join(f"{m['codice']} (servono {m['pezzi']}, in magazzino {m['giacenza']})" for m in mancanze)
    return f"Giacenza insufficiente: {elenco}. Registra il carico oppure scrivi il motivo per consegnare lo stesso."


def _chiedi_conferma(request, consegne: list[ConsegnaDPI]) -> None:
    """Senza firma ne' ricevuta su carta: mail di conferma al dipendente (mail aziendale)
    o al suo caporeparto. La consegna resta registrata comunque."""
    from . import conferme

    autore = consegne[0].consegnato_da_nome if consegne else ""
    conferma, tipo, inviate = conferme.richiedi(consegne, autore=autore)
    if getattr(request, "_senza_utente", False):  # dal task: nessuno a cui mostrare i messaggi
        if conferma is not None:
            log_action(request, "dpi_conferma_richiesta", "dpi", f"Conferma ricevuta {conferma.pk} per {conferma.richiedente_nome} ({tipo})")
        return
    if conferma is not None and not inviate:
        messages.warning(request, "Mail di conferma della ricevuta non inviata (regola «DPI consegnato - conferma della "
                                  "ricevuta via mail» spenta in Automazioni o invio fallito): fai firmare il dipendente "
                                  "o conserva la ricevuta su carta.")
        return
    if conferma is None:
        messages.warning(request, "Nessuna mail a cui chiedere la conferma di ricevuta: fai firmare il dipendente o "
                                  "conserva la ricevuta su carta.")
        return
    chi = "al dipendente" if tipo == conferma.Destinatario.DIPENDENTE else "al caporeparto (il dipendente non ha la mail aziendale)"
    log_action(request, "dpi_conferma_richiesta", "dpi", f"Conferma ricevuta {conferma.pk} per {conferma.richiedente_nome} ({tipo})")
    messages.info(request, f"Mail di conferma della ricevuta inviata {chi}.")


def _avviso_giacenza(request, richiesta: RichiestaDPI, residuo: int | None) -> None:
    if residuo is not None and residuo < 0:
        messages.warning(request, f"Giacenza di magazzino negativa ({residuo}) per {richiesta.modello_dpi.codice}: registra il carico dei DDT o una rettifica.")
    elif residuo is not None and richiesta.modello_dpi.scorta_minima and residuo <= richiesta.modello_dpi.scorta_minima:
        messages.warning(request, f"{richiesta.modello_dpi.codice} sotto scorta minima: restano {residuo} pezzi.")


def _registra_consegna(request, richiesta: RichiestaDPI, *, data_consegna, note: str = "", firmato: bool = False,
                       firma_immagine: str = "", scadenza_override=None, motivo_giacenza: str = "",
                       in_sospeso_dal=None) -> int | None:
    """Registra la consegna di una richiesta approvata: consegna + stato + scarico di magazzino,
    poi sostituzione delle precedenti, PDF nei documenti del dipendente e notifiche.
    Con ``in_sospeso_dal`` la seconda parte aspetta ``_completa_in_sospeso``: la consegna e' gia'
    salva, ma finche' non e' partito nulla si puo' annullare (Banco consegne).
    Ritorna la giacenza residua del modello (None se la richiesta non ha un modello).
    Unico punto per la consegna dalla scheda richiesta e dal Banco consegne."""
    # Scadenza automatica da vita utile modello, se presente, altrimenti categoria.
    scadenza = scadenza_override
    if scadenza is None:
        vita_utile = (
            richiesta.modello_dpi.effective_vita_utile_giorni
            if richiesta.modello_dpi
            else richiesta.categoria.vita_utile_giorni
        )
        if vita_utile:
            scadenza = data_consegna + timedelta(days=vita_utile)

    autore = request.user.get_full_name() or request.user.username
    movimento, residuo = None, None
    with transaction.atomic():
        consegna, _ = ConsegnaDPI.objects.update_or_create(
            richiesta=richiesta,
            defaults={
                "data_consegna": data_consegna,
                "consegnato_da_nome": autore,
                "note_consegna": note,
                "firmato_ricevuta": firmato,
                "data_scadenza_stimata": scadenza,
                "firma_immagine": firma_immagine,
                "avvisi_in_sospeso_dal": in_sospeso_dal,
            },
        )
        richiesta.stato = StatoRichiesta.CONSEGNATA
        richiesta.save(update_fields=["stato", "updated_at"])
        if motivo_giacenza:
            RichiestaDPICommento.objects.create(
                richiesta=richiesta, autore_nome=autore, is_interno=True,
                testo=f"Consegnato senza giacenza sufficiente: {motivo_giacenza}",
            )
        # Le scarpe comprate per la persona non sono mai state in magazzino.
        if not richiesta.modalita_negozio:
            movimento, residuo = magazzino.scarica_per_consegna(richiesta, data_consegna, user=request.user, motivo=motivo_giacenza)
    log_action(request, "consegna", "dpi", f"Consegnato DPI {richiesta.numero} in data {data_consegna}")
    if movimento is not None:
        log_action(request, "DPI_MAGAZZINO_SCARICO", "dpi", f"Scarico {movimento.quantita} x {movimento.modello.codice} per {richiesta.numero}")
    if in_sospeso_dal is None:
        _completa_consegna(request, consegna)
    return residuo


def _completa_consegna(request, consegna: ConsegnaDPI) -> None:
    """Quello che esce dalla consegna: sostituzione delle precedenti, PDF, notifiche e mail."""
    richiesta, data_consegna = consegna.richiesta, consegna.data_consegna
    _sostituisci_consegne_precedenti(request, richiesta, consegna, data_consegna)

    # Genera e archivia il PDF del modulo di consegna nello spazio documenti del
    # dipendente. Idempotente: se esiste già un documento per questa consegna
    # viene sovrascritto (es. firma aggiunta dopo). Fail-soft: un errore PDF
    # non blocca la consegna registrata sopra.
    _archivia_pdf_consegna(request, consegna)
    if richiesta.richiedente_legacy_id:
        from core.notifiche import invia_notifica
        from django.urls import reverse
        invia_notifica(
            legacy_user_id=utente_da_anagrafica(richiesta.richiedente_legacy_id),
            tipo="dpi_consegnata",
            messaggio=f"Il tuo {richiesta.categoria.nome} ({richiesta.numero}) è stato consegnato il {data_consegna.strftime('%d-%m-%Y')}.",
            url_azione=reverse("dpi:detail", args=[richiesta.pk]),
        )
    flusso.notifica_consegnata(consegna)


def _completa_in_sospeso(request, consegne) -> int:
    """Manda mail e PDF delle consegne ancora in sospeso. Chi toglie il segno per primo la
    completa: browser e task insieme non producono mail doppie, e dopo non si annulla piu'."""
    fatte = 0
    senza_firma: dict[str, list[ConsegnaDPI]] = {}
    for c in consegne:
        if not ConsegnaDPI.objects.filter(pk=c.pk, avvisi_in_sospeso_dal__isnull=False).update(avvisi_in_sospeso_dal=None):
            continue
        try:
            _completa_consegna(request, c)
        except Exception:  # la consegna e' registrata: un avviso fallito non ferma le altre
            logger.exception("Avvisi della consegna DPI %s non completati", c.pk)
            log_action(request, "DPI_CONSEGNA_AVVISI_ERRORE", "dpi", f"Avvisi non completati per {c.richiesta.numero}")
            continue
        fatte += 1
        if not c.firmato_ricevuta:
            senza_firma.setdefault(_chiave_persona(c.richiesta), []).append(c)
    for gruppo in senza_firma.values():
        _chiedi_conferma(request, gruppo)
    return fatte


def completa_consegne_in_sospeso(minuti: int = 2) -> int:
    """Rete di sicurezza: l'annullo dura pochi secondi, quindi quello che resta in sospeso
    oltre ``minuti`` viene da un browser chiuso o senza rete e parte da qui."""
    from types import SimpleNamespace

    from django.contrib.auth.models import AnonymousUser

    limite = timezone.now() - timedelta(minutes=minuti)
    consegne = list(ConsegnaDPI.objects.filter(avvisi_in_sospeso_dal__lt=limite).select_related(
        "richiesta", "richiesta__categoria", "richiesta__tipo_dpi", "richiesta__modello_dpi", "richiesta__taglia_dpi",
    ).order_by("avvisi_in_sospeso_dal"))
    if not consegne:
        return 0
    return _completa_in_sospeso(SimpleNamespace(user=AnonymousUser(), META={}, _senza_utente=True), consegne)


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
    if not impostazioni_o(request, "dpi", _is_gestore):
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
        impost.magazzino_emails = request.POST.get("magazzino_emails", "").strip()
        impost.negozio_nome = request.POST.get("negozio_nome", "").strip()[:120] or impost.negozio_nome
        impost.negozio_email = request.POST.get("negozio_email", "").strip()[:254]
        impost.negozio_operatore_emails = request.POST.get("negozio_operatore_emails", "").strip()
        impost.negozio_giorni_riepilogo = _parse_optional_positive_int(request.POST.get("negozio_giorni_riepilogo")) or impost.negozio_giorni_riepilogo
        impost.amministrazione_emails = request.POST.get("amministrazione_emails", "").strip()
        impost.avviso_ritiro_all_approvazione = bool(request.POST.get("avviso_ritiro_all_approvazione"))
        impost.domini_email_aziendali = request.POST.get("domini_email_aziendali", "").strip()[:300]
        impost.save()
        log_action(request, "modifica", "dpi", "Aggiornate impostazioni DPI")
        messages.success(request, "Impostazioni salvate.")
        return redirect("dpi:impostazioni")

    return render(request, "dpi/pages/impostazioni.html", _catalog_context(impost))


@login_required
def categoria_edit(request, pk: int | None = None):
    if not impostazioni_o(request, "dpi", _is_gestore):
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
            "icona_emoji": normalizza_icona_dpi(request.POST.get("icona_emoji", "")),
            "vita_utile_giorni": _parse_optional_positive_int(request.POST.get("vita_utile_giorni")),
            "obbligatoria_mansionario": bool(request.POST.get("obbligatoria_mansionario")),
            "unita_misura": request.POST.get("unita_misura", "pz").strip() or "pz",
            "scorta_minima": _parse_optional_positive_int(request.POST.get("scorta_minima")) or 0,
            "avvisa_amministrazione_consegna": bool(request.POST.get("avvisa_amministrazione_consegna")),
            "consegna_magazzino": bool(request.POST.get("consegna_magazzino")),
            "si_ordina_al_negozio": bool(request.POST.get("si_ordina_al_negozio")),
            "consegna_diretta": bool(request.POST.get("consegna_diretta")),
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
    if not impostazioni_o(request, "dpi", _is_gestore):
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
    if not impostazioni_o(request, "dpi", _is_gestore):
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
    if not impostazioni_o(request, "dpi", _is_gestore):
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
    if not impostazioni_o(request, "dpi", _is_gestore):
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


@require_POST
@login_required
def copilota_richiesta(request, pk: int):
    """Proposta dell'AI su una richiesta (approvare / chiedere informazioni / rifiutare). Non cambia nulla."""
    richiesta = get_object_or_404(
        RichiestaDPI.objects.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi"), pk=pk,
    )
    if not _can_approve(request, richiesta):
        return HttpResponse("Accesso non autorizzato.", status=403)
    from .ai_richiesta import proponi_valutazione

    proposta = proponi_valutazione(richiesta, user=request.user)
    log_action(request, "dpi_copilota_richiesta", "dpi", {
        "richiesta": richiesta.numero, "decisione": proposta["decisione"], "ai_disponibile": proposta["ai_disponibile"],
    })
    return render(request, "dpi/components/_copilota_richiesta.html", {"p": proposta})


@require_POST
@login_required
def api_copilota_dpi(request):
    """Copilota DPI: propone (NON salva) un set DPI per una mansione.

    Read-only: i DPI proposti sono validati contro il catalogo reale e le categorie
    obbligatorie da mansionario sono sempre incluse; il gestore rivede e firma.
    Solo gestori (JSON 403 altrimenti). Audit solo-metadati.
    """
    if not _is_gestore(request):
        return JsonResponse({"ok": False, "error": "Permessi insufficienti."}, status=403)
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"ok": False, "error": "Dati non validi."}, status=400)
    mansione = str(payload.get("mansione") or "").strip()
    note = str(payload.get("note") or "").strip()
    if not mansione:
        return JsonResponse({"ok": False, "error": "Indica la mansione."}, status=400)

    cats = (
        CategoriaDPI.objects.filter(is_active=True)
        .prefetch_related("tipi")
        .order_by("order_index", "nome")
    )
    categorie = []
    obbligatorie = []
    for c in cats:
        tipi = [t.nome for t in c.tipi.all() if t.is_active]
        categorie.append({"nome": c.nome, "tipi": tipi})
        if c.obbligatoria_mansionario:
            obbligatorie.append(c.nome)

    from .ai_copilota import proponi_dpi_mansione
    proposta = proponi_dpi_mansione(
        mansione=mansione, note=note, categorie=categorie, obbligatorie=obbligatorie,
    )

    log_action(request, "dpi_copilota", "dpi", {
        "mansione_chars": len(mansione),
        "dpi_count": len(proposta.get("dpi") or []),
        "obbligatorie_count": len(obbligatorie),
        "ai_disponibile": proposta.get("ai_disponibile"),
    })
    return JsonResponse({"ok": True, "proposta": proposta})


# ---------------------------------------------------------------------------
# Raccoglitore documenti (certificati, attestati, manuali d'uso)
# ---------------------------------------------------------------------------

@login_required
def documenti(request):
    """Raccoglitore unico: tutti gli utenti DPI consultano, i gestori caricano ed eliminano."""
    is_gestore = _is_gestore(request)
    if request.method == "POST":
        if not is_gestore:
            messages.error(request, "Solo chi gestisce i DPI puo' caricare documenti.")
            return redirect("dpi:documenti")
        titolo = request.POST.get("titolo", "").strip()[:200]
        descrizione = request.POST.get("descrizione", "").strip()[:500]
        modello = ModelloDPI.objects.filter(pk=_parse_optional_positive_int(request.POST.get("modello"))).first()
        if modello is None:
            messages.error(request, "Scegli il DPI a cui appartiene il documento.")
            return redirect("dpi:documenti")
        files = request.FILES.getlist("files")
        if not files:
            messages.error(request, "Scegli almeno un file da caricare.")
            return redirect("dpi:documenti")
        salvati = 0
        for upload in files:
            try:
                validate_extension_and_mime(
                    upload,
                    allowed_extensions=DPI_DOCUMENT_ALLOWED_EXTENSIONS,
                    allowed_mimes=DPI_DOCUMENT_ALLOWED_MIMES,
                    max_bytes=DPI_DOCUMENT_MAX_BYTES,
                    label=upload.name,
                    allow_empty=False,
                )
            except UploadMimeValidationError as exc:
                messages.error(request, str(exc))
                continue
            nome = (upload.name or "documento")[:255]
            doc = DocumentoDPI.objects.create(
                modello=modello,
                # Il titolo a mano vale solo con un file; con piu' file ognuno prende il proprio nome.
                titolo=(titolo if titolo and len(files) == 1 else nome.rsplit(".", 1)[0])[:200],
                descrizione=descrizione,
                file=upload,
                nome_originale=nome,
                dimensione_bytes=int(upload.size or 0),
                caricato_da=request.user,
            )
            log_action(request, "DPI_DOCUMENTO_CARICATO", "dpi", f"Caricato documento DPI {doc.pk} ({modello.codice}): {doc.nome_originale}")
            salvati += 1
        if salvati:
            messages.success(request, "Documento caricato." if salvati == 1 else f"{salvati} documenti caricati.")
        return redirect("dpi:documenti")

    q = request.GET.get("q", "").strip()
    qs = DocumentoDPI.objects.select_related("caricato_da", "modello", "modello__tipo", "modello__tipo__categoria")
    modello_filtro = _parse_optional_positive_int(request.GET.get("modello"))
    if modello_filtro:
        qs = qs.filter(modello_id=modello_filtro)
    if q:
        qs = qs.filter(Q(titolo__icontains=q) | Q(descrizione__icontains=q) | Q(nome_originale__icontains=q) | Q(modello__nome__icontains=q) | Q(modello__codice__icontains=q))
    return render(request, "dpi/pages/documenti.html", {
        "is_gestore": is_gestore,
        "documenti": qs,
        "q": q,
        "modelli": _catalog_select_related()["modelli"].filter(is_active=True),
        "modello_filtro": modello_filtro,
    })


@login_required
def documento_download(request, pk: int):
    doc = get_object_or_404(DocumentoDPI, pk=pk)
    storage = doc.file.storage
    if not doc.file or not doc.file.name or not storage.exists(doc.file.name):
        return HttpResponse("Documento non trovato.", status=404)
    log_action(request, "DPI_DOCUMENTO_SCARICATO", "dpi", f"Aperto documento DPI {doc.pk}: {doc.nome_originale}")
    filename = doc.nome_originale or doc.titolo
    inline = filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")) and request.GET.get("download") != "1"
    return FileResponse(
        storage.open(doc.file.name, "rb"),
        as_attachment=not inline,
        filename=filename,
        content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )


@login_required
@require_POST
def documento_elimina(request, pk: int):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:documenti")
    doc = get_object_or_404(DocumentoDPI, pk=pk)
    dettaglio = f"Eliminato documento DPI {doc.pk}: {doc.nome_originale}"
    doc.delete()
    log_action(request, "DPI_DOCUMENTO_ELIMINATO", "dpi", dettaglio)
    messages.success(request, "Documento eliminato.")
    return redirect("dpi:documenti")


# ---------------------------------------------------------------------------
# Magazzino: scorta per modello, carico da DDT (manuale), rettifiche
# ---------------------------------------------------------------------------

def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


_DDT_ESTENSIONI = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


def _magazzino_ddt(request):
    """«Leggi un DDT»: ``leggi_ddt`` risponde con la proposta (JSON, il file non resta
    sul server); ``carico_ddt`` registra le righe confermate, un carico per riga."""
    if request.POST.get("azione") == "leggi_ddt":
        from anagrafica.services.upload_documenti import UploadMimeValidationError, valida_documento
        from core.lettura_documenti import DocumentoNonLeggibile, leggi

        from .lettura_ddt import proponi

        uploaded = request.FILES.get("file")
        if not uploaded:
            return JsonResponse({"ok": False, "errore": "Scegli il file del DDT."}, status=400)
        try:
            valida_documento(uploaded, _DDT_ESTENSIONI, label="DDT")
            uploaded.seek(0)
            lettura = leggi(uploaded.read())
        except (UploadMimeValidationError, DocumentoNonLeggibile) as exc:
            return JsonResponse({"ok": False, "errore": str(exc)}, status=400)
        return JsonResponse({"ok": True, **proponi(lettura)})

    try:
        data = date.fromisoformat(request.POST.get("data", "").strip()) if request.POST.get("data") else timezone.localdate()
    except ValueError:
        messages.error(request, "Data del DDT non valida.")
        return redirect("dpi:magazzino")
    ddt_numero = request.POST.get("ddt_numero", "").strip()
    fornitore = request.POST.get("fornitore", "").strip()
    caricati = []
    for mid in request.POST.getlist("riga_modello"):
        if request.POST.get(f"riga_ok_{mid}") != "1":
            continue
        modello = ModelloDPI.objects.filter(pk=_int_or_none(mid), is_active=True).first()
        qta = _int_or_none(request.POST.get(f"riga_qta_{mid}"))
        if modello is None or not qta or qta <= 0:
            continue
        mov = magazzino.carica_ddt(modello, qta, ddt_numero=ddt_numero, data=data, fornitore=fornitore,
                                   note="Da «Leggi un DDT».", user=request.user)
        caricati.append(f"{mov.quantita} × {modello.codice}")
    if not caricati:
        messages.warning(request, "Nessuna riga confermata: niente caricato.")
        return redirect("dpi:magazzino")
    log_action(request, "DPI_MAGAZZINO_CARICO_DDT", "dpi", f"DDT {ddt_numero or 's.n.'}: " + ", ".join(caricati))
    messages.success(request, f"Caricato il DDT {ddt_numero or 's.n.'}: " + ", ".join(caricati) + ".")
    return redirect("dpi:magazzino")


@login_required
def magazzino_view(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    if request.method == "POST" and request.POST.get("azione") in ("leggi_ddt", "carico_ddt"):
        return _magazzino_ddt(request)
    if request.method == "POST":
        azione = request.POST.get("azione", "")
        modello = ModelloDPI.objects.filter(pk=_int_or_none(request.POST.get("modello"))).first()
        if modello is None:
            messages.error(request, "Scegli il DPI.")
            return redirect("dpi:magazzino")
        if azione == "carico":
            qta = _int_or_none(request.POST.get("quantita"))
            try:
                data = date.fromisoformat(request.POST.get("data", "").strip()) if request.POST.get("data") else timezone.localdate()
            except ValueError:
                data = None
            if not qta or qta <= 0 or data is None:
                messages.error(request, "Indica una quantità positiva e una data valida.")
                return redirect("dpi:magazzino")
            mov = magazzino.carica_ddt(
                modello, qta, ddt_numero=request.POST.get("ddt_numero", "").strip(), data=data,
                fornitore=request.POST.get("fornitore", "").strip(), note=request.POST.get("note", "").strip(), user=request.user,
            )
            log_action(request, "DPI_MAGAZZINO_CARICO", "dpi", f"Carico {qta} x {modello.codice} (DDT {mov.ddt_numero or 's.n.'})")
            messages.success(request, f"Caricati {qta} × {modello.codice}. Giacenza: {magazzino.giacenza(modello.pk)}.")
        elif azione == "rettifica":
            nuova = _int_or_none(request.POST.get("giacenza"))
            if nuova is None or nuova < 0:
                messages.error(request, "Indica la giacenza corretta (zero o più).")
                return redirect("dpi:magazzino")
            mov = magazzino.imposta_giacenza(modello, nuova, note=request.POST.get("note", "").strip(), user=request.user)
            if mov:
                log_action(request, "DPI_MAGAZZINO_RETTIFICA", "dpi", f"Rettifica {mov.quantita:+d} su {modello.codice}: giacenza {nuova}")
            messages.success(request, f"Giacenza di {modello.codice} impostata a {nuova}.")
        elif azione == "soglia":
            soglia = _int_or_none(request.POST.get("scorta_minima"))
            if soglia is None or soglia < 0:
                messages.error(request, "La scorta minima deve essere zero o più.")
                return redirect("dpi:magazzino")
            modello.scorta_minima = soglia
            modello.save(update_fields=["scorta_minima", "updated_at"])
            messages.success(request, f"Scorta minima di {modello.codice}: {soglia}.")
        return redirect("dpi:magazzino")

    modelli = list(_catalog_select_related()["modelli"].filter(is_active=True).exclude(tipo__categoria__si_ordina_al_negozio=True))
    per_modello = magazzino.giacenze()
    righe = []
    for m in modelli:
        qta = per_modello.get(m.pk, 0)
        pct = min(100, max(0, round(qta * 50 / m.scorta_minima))) if m.scorta_minima else 0
        righe.append({"modello": m, "giacenza": qta, "pct": pct, "stato": magazzino.stato_scorta(qta, m.scorta_minima)})
    n_esauriti = sum(1 for r in righe if r["stato"] == magazzino.STATO_ESAURITO)
    n_sotto = sum(1 for r in righe if r["stato"] == magazzino.STATO_SOTTO_SCORTA)
    solo = request.GET.get("stato", "")
    if solo in (magazzino.STATO_ESAURITO, magazzino.STATO_SOTTO_SCORTA, magazzino.STATO_OK):
        righe = [r for r in righe if r["stato"] == solo]
    movimenti = MovimentoMagazzinoDPI.objects.select_related("modello", "created_by")
    modello_mov = _parse_optional_positive_int(request.GET.get("modello"))
    if modello_mov:
        movimenti = movimenti.filter(modello_id=modello_mov)
    return render(request, "dpi/pages/magazzino.html", {
        "is_gestore": True,
        "righe": righe,
        "modelli": modelli,
        "n_modelli": len(modelli),
        "n_esauriti": n_esauriti,
        "n_sotto": n_sotto,
        "pezzi_totali": sum(per_modello.get(m.pk, 0) for m in modelli),
        "filtro_stato": solo,
        "modello_mov": modello_mov,
        "movimenti": movimenti[:40],
        "oggi": timezone.localdate(),
    })


@login_required
def magazzino_riordino(request):
    """Bozza d'ordine ai fornitori: si corregge e si copia, il portale non invia nulla."""
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    giorni = _int_or_none(request.GET.get("giorni")) or 90
    if giorni not in (30, 90, 180, 365):
        giorni = 90
    return render(request, "dpi/pages/magazzino_riordino.html", {
        "is_gestore": True,
        "is_approvatore": True,
        "giorni": giorni,
        "periodi": (30, 90, 180, 365),
        "fornitori": magazzino.bozza_ordine(giorni),
    })


@login_required
def magazzino_report(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    giorni = _int_or_none(request.GET.get("giorni")) or 90
    if giorni not in (30, 90, 180, 365):
        giorni = 90
    dati = magazzino.report(giorni)

    if request.GET.get("formato") == "csv":
        from core.csv_export import csv_download_response

        response, writer = csv_download_response(f"movimenti_dpi_{timezone.localdate():%Y%m%d}.csv", delimiter=";")
        writer.writerow(["Data", "Movimento", "Codice", "DPI", "Quantita", "DDT", "Fornitore", "Nota"])
        for m in MovimentoMagazzinoDPI.objects.filter(data__gte=dati["da"]).select_related("modello").order_by("data", "id"):
            writer.writerow([
                m.data.isoformat(), m.get_tipo_display(), m.modello.codice, m.modello.nome,
                m.quantita, m.ddt_numero, m.fornitore, m.note,
            ])
        log_action(request, "DPI_MAGAZZINO_EXPORT", "dpi", f"Esportati movimenti magazzino dal {dati['da']}")
        return response

    return render(request, "dpi/pages/magazzino_report.html", {**dati, "is_gestore": True, "periodi": (30, 90, 180, 365)})


# ---------------------------------------------------------------------------
# Banco consegne: la coda del magazzino per persona, consegna di piu' DPI con una
# sola firma, consegna diretta dei consumabili senza richiesta approvata.
# ---------------------------------------------------------------------------

def _banco_queryset(request):
    """Richieste approvate da consegnare al banco: non le scarpe fuori convenzione (si chiudono
    con la fattura) ne' quelle in convenzione non ancora ordinate."""
    return _approvate_queryset(request).exclude(modalita_negozio=ModalitaNegozio.FUORI).exclude(
        modalita_negozio=ModalitaNegozio.CONVENZIONE, ordine_negozio__isnull=True
    )


def _approvate_queryset(request):
    """Richieste approvate non ancora consegnate, nel perimetro di chi gestisce."""
    qs = RichiestaDPI.objects.filter(stato=StatoRichiesta.APPROVATA).select_related(
        "categoria", "tipo_dpi", "modello_dpi", "taglia_dpi"
    )
    if sistema_ruoli_attivo():
        ids = _anagrafiche_visibili(request, "gestire")
        if ids is not None:
            qs = qs.filter(richiedente_legacy_id__in=list(ids))
    return qs


def _banco_redirect(chiave: str = "", tutte: bool = False):
    from django.urls import reverse

    url = reverse("dpi:banco") + ("?tutte=1" if tutte else "")
    return redirect(url + (f"#{chiave}" if chiave else ""))


def _chiave_persona(richiesta: RichiestaDPI) -> str:
    if richiesta.richiedente_legacy_id:
        return f"p{richiesta.richiedente_legacy_id}"
    return "n" + "".join(c for c in (richiesta.richiedente_nome or "").casefold() if c.isalnum())[:40]


def _banco_persone(qs, giac: dict) -> list[dict]:
    """Richieste del banco raggruppate per persona (pagina Banco e pannello della home)."""
    gruppi: dict[str, dict] = {}
    for r in qs.order_by("richiedente_nome", "created_at"):
        chiave = _chiave_persona(r)
        g = gruppi.setdefault(chiave, {
            "chiave": chiave, "nome": r.richiedente_nome, "reparto": r.richiedente_reparto,
            "legacy_id": r.richiedente_legacy_id,
            "righe": [], "n_pronte": 0, "n_da_preparare": 0, "n_mancanti": 0,
        })
        g_mod = giac.get(r.modello_dpi_id, 0) if r.modello_dpi_id and not r.modalita_negozio else None
        manca = bool(giac) and g_mod is not None and g_mod < r.quantita  # senza movimenti il magazzino non e' in uso
        g["righe"].append({"r": r, "giacenza": g_mod, "manca": manca})
        g["n_pronte" if r.pronta_ritiro_il else "n_da_preparare"] += 1
        g["n_mancanti"] += int(manca)
    return sorted(gruppi.values(), key=lambda g: (g["nome"] or "").casefold())


def _banco_conferme_qs(request):
    """Conferme di ricevuta nel perimetro di chi gestisce."""
    from .models import ConfermaConsegnaDPI

    qs = ConfermaConsegnaDPI.objects.prefetch_related("consegne__richiesta")
    if sistema_ruoli_attivo():
        ids_gestire = _anagrafiche_visibili(request, "gestire")
        if ids_gestire is not None:
            qs = qs.filter(richiedente_legacy_id__in=list(ids_gestire))
    return qs


def _banco_selezionate(request) -> list[RichiestaDPI]:
    ids = [i for i in (_int_or_none(v) for v in request.POST.getlist("ids")) if i]
    if not ids:
        return []
    return list(_banco_queryset(request).filter(pk__in=ids).order_by("created_at"))


def _banco_consegna_diretta(request, tutte: bool):
    """Consumabili (categorie con «Consegna diretta»): il magazzino crea la richiesta gia'
    approvata per il dipendente al banco; poi la consegna con la firma come le altre."""
    scelti = {d["id"]: d["nome"] for d in _dipendenti_selezionabili(request)}
    legacy_id = _int_or_none(request.POST.get("dipendente"))
    if not legacy_id or legacy_id not in scelti:
        messages.error(request, "Scegli il dipendente a cui consegni il DPI.")
        return _banco_redirect(tutte=tutte)
    categoria, tipo_dpi, modello_dpi, taglia_dpi, errors = _resolve_richiesta_catalog_selection(request.POST)
    if not errors and (modello_dpi is None or not categoria.consegna_diretta):
        errors.append("Scegli un DPI di una categoria con «Consegna diretta dal banco».")
    if errors:
        for e in errors:
            messages.error(request, e)
        return _banco_redirect(tutte=tutte)
    quantita = max(1, _int_or_none(request.POST.get("quantita")) or 1)
    info = _richiedente_info(request, legacy_id)
    autore = request.user.get_full_name() or request.user.username
    r = RichiestaDPI.objects.create(
        categoria=categoria, tipo_dpi=tipo_dpi, modello_dpi=modello_dpi, taglia_dpi=taglia_dpi,
        quantita=quantita, motivazione=request.POST.get("motivazione", "").strip(),
        stato=StatoRichiesta.APPROVATA,
        richiedente_legacy_id=legacy_id, richiedente_nome=info["nome"] or scelti[legacy_id],
        richiedente_email=info["email"], richiedente_reparto=info["reparto"],
        note_gestione=f"[Consegna diretta al banco: inserita da {autore}]",
        created_by=request.user,
    )
    RichiestaDPICommento.objects.create(
        richiesta=r, autore_nome="Portale", is_interno=False,
        testo=f"Consegna diretta al banco ({categoria.nome}: categoria senza approvazione), inserita da {autore}.",
    )
    log_action(request, "crea", "dpi", f"Consegna diretta al banco {r.numero} - {categoria.nome} per {r.richiedente_nome}")
    messages.success(request, f"{r.numero} aggiunta: registra la consegna a {r.richiedente_nome}.")
    return _banco_redirect("apri-" + _chiave_persona(r), tutte)


def _banco_cambia_modello(request, tutte: bool):
    """Al banco manca quel modello o quella taglia: si cambia sulla richiesta, con traccia."""
    r = _banco_queryset(request).filter(pk=_int_or_none(request.POST.get("cambia_richiesta"))).first()
    if r is None:
        messages.error(request, "Richiesta non trovata tra quelle da consegnare.")
        return _banco_redirect(tutte=tutte)
    chiave = _chiave_persona(r)
    if r.modalita_negozio:
        messages.error(request, "Queste scarpe sono ordinate al negozio: non si cambiano dal banco.")
        return _banco_redirect(chiave, tutte)
    modello = ModelloDPI.objects.filter(
        pk=_int_or_none(request.POST.get("cambia_modello")), is_active=True, tipo__is_active=True, tipo__categoria_id=r.categoria_id,
    ).select_related("tipo").first()
    if modello is None:
        messages.error(request, "Scegli un modello attivo della stessa categoria.")
        return _banco_redirect(chiave, tutte)
    taglia_id = _int_or_none(request.POST.get("cambia_taglia"))
    taglia = TagliaDPI.objects.filter(pk=taglia_id, modello=modello, is_active=True).first() if taglia_id else None
    if taglia_id and taglia is None:
        messages.error(request, "La taglia scelta non è di quel modello.")
        return _banco_redirect(chiave, tutte)
    if r.modello_dpi_id == modello.pk and r.taglia_dpi_id == (taglia.pk if taglia else None):
        messages.info(request, "Nessuna modifica.")
        return _banco_redirect(chiave, tutte)
    prima = flusso._riga_dpi(r)
    r.tipo_dpi, r.modello_dpi, r.taglia_dpi = modello.tipo, modello, taglia
    r.save(update_fields=["tipo_dpi", "modello_dpi", "taglia_dpi", "updated_at"])
    autore = request.user.get_full_name() or request.user.username
    dopo = flusso._riga_dpi(r)
    RichiestaDPICommento.objects.create(
        richiesta=r, autore_nome=autore, is_interno=False, testo=f"Cambiato al banco: da {prima} a {dopo}.",
    )
    log_action(request, "DPI_BANCO_CAMBIO", "dpi", f"{r.numero}: da {prima} a {dopo}")
    messages.success(request, f"{r.numero}: ora {dopo}.")
    return _banco_redirect(chiave, tutte)


def _banco_in_sospeso(request) -> list[ConsegnaDPI]:
    """Consegne indicate dal modulo, ancora annullabili e nel perimetro di chi gestisce."""
    ids = [i for i in (_int_or_none(v) for v in request.POST.getlist("ids")) if i]
    qs = ConsegnaDPI.objects.filter(richiesta_id__in=ids, avvisi_in_sospeso_dal__isnull=False).select_related(
        "richiesta", "richiesta__categoria", "richiesta__tipo_dpi", "richiesta__modello_dpi", "richiesta__taglia_dpi",
    )
    if sistema_ruoli_attivo():
        visibili = _anagrafiche_visibili(request, "gestire")
        if visibili is not None:
            qs = qs.filter(richiesta__richiedente_legacy_id__in=list(visibili))
    return list(qs)


def _banco_annulla_consegne(request, tutte: bool):
    """Ripensamento subito dopo la consegna: non e' partito nulla, si torna alla richiesta approvata."""
    autore = request.user.get_full_name() or request.user.username
    annullate = []
    for c in _banco_in_sospeso(request):
        r = c.richiesta
        with transaction.atomic():
            if not ConsegnaDPI.objects.filter(pk=c.pk, avvisi_in_sospeso_dal__isnull=False).delete()[0]:
                continue  # gli avvisi sono partiti proprio ora
            magazzino.annulla_scarico(r)
            r.stato = StatoRichiesta.APPROVATA
            r.save(update_fields=["stato", "updated_at"])
            RichiestaDPICommento.objects.create(
                richiesta=r, autore_nome=autore, is_interno=True,
                testo=f"Consegna del {c.data_consegna:%d-%m-%Y} annullata subito dopo la registrazione.",
            )
        log_action(request, "DPI_CONSEGNA_ANNULLATA", "dpi", f"Consegna {r.numero} annullata da {autore}")
        annullate.append(r.pk)
    request.banco_annullate = annullate
    if annullate:
        messages.info(request, f"Consegna annullata: {len(annullate)} DPI di nuovo da consegnare.")
    else:
        messages.error(request, "Troppo tardi per annullare: gli avvisi della consegna sono già partiti.")
    return _banco_redirect(tutte=tutte)


def _banco_azione(request):
    azione = request.POST.get("azione", "")
    tutte = request.POST.get("tutte") == "1"
    if azione == "diretta":
        return _banco_consegna_diretta(request, tutte)
    if azione == "cambia":
        return _banco_cambia_modello(request, tutte)
    if azione == "avvisi":
        _completa_in_sospeso(request, _banco_in_sospeso(request))
        return _banco_redirect(tutte=tutte)
    if azione == "annulla":
        return _banco_annulla_consegne(request, tutte)
    richieste = _banco_selezionate(request)
    if not richieste:
        messages.warning(request, "Spunta almeno un DPI.")
        return _banco_redirect(tutte=tutte)
    chiave = _chiave_persona(richieste[0])
    autore = request.user.get_full_name() or request.user.username

    if azione == "pronta":
        avvisate = 0
        for r in richieste:
            if r.pronta_ritiro_il is None:
                _segna_pronta(request, r, da_nome=autore)
                avvisate += 1
        if avvisate:
            messages.success(request, f"Avvisi di ritiro inviati: {avvisate}.")
        else:
            messages.info(request, "I DPI spuntati erano già segnati come pronti.")
        return _banco_redirect(chiave, tutte)

    if azione == "consegna":
        try:
            data_consegna = date.fromisoformat(request.POST.get("data_consegna", "").strip())
        except ValueError:
            messages.error(request, "Data di consegna non valida.")
            return _banco_redirect(chiave, tutte)
        firma_immagine, firma_error = _clean_signature_data_uri(request.POST.get("firma_immagine", ""))
        if firma_error:
            messages.error(request, firma_error)
            return _banco_redirect(chiave, tutte)
        firmato = bool(firma_immagine) or bool(request.POST.get("firmato_ricevuta"))
        note = request.POST.get("note_consegna", "").strip()
        motivo = request.POST.get("motivo_giacenza", "").strip()[:200]
        mancanze = magazzino.mancanze(richieste)
        if mancanze and not motivo:
            request.banco_chiedi_motivo = True
            messages.error(request, _testo_manca_motivo(mancanze))
            return _banco_redirect(chiave, tutte)
        senza_giacenza = {m["modello_id"] for m in mancanze}
        # Dalla pagina aperta: mail e PDF aspettano qualche secondo, per poter annullare.
        differita = request.POST.get("differisci") == "1" and request.headers.get("X-Requested-With") == "XMLHttpRequest"
        adesso = timezone.now() if differita else None
        per_persona: dict[str, list[ConsegnaDPI]] = {}
        for r in richieste:
            residuo = _registra_consegna(
                request, r, data_consegna=data_consegna, note=note, firmato=firmato, firma_immagine=firma_immagine,
                motivo_giacenza=motivo if r.modello_dpi_id in senza_giacenza else "", in_sospeso_dal=adesso,
            )
            _avviso_giacenza(request, r, residuo)
            per_persona.setdefault(_chiave_persona(r), []).append(r.consegna)
        if differita:
            request.banco_registrate = [r.pk for r in richieste]
            return _banco_redirect(tutte=tutte)
        nomi = sorted({r.richiedente_nome for r in richieste})
        messages.success(request, f"Consegnati {len(richieste)} DPI a {', '.join(nomi)}.")
        if not firmato:
            for consegne in per_persona.values():
                _chiedi_conferma(request, consegne)
        return _banco_redirect(tutte=tutte)

    messages.error(request, "Azione non riconosciuta.")
    return _banco_redirect(tutte=tutte)


@login_required
def banco(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    # Dalla pagina aperta (fetch) torna solo la parte di lavoro: niente ricarica. Il toast
    # dei messaggi lo consegna FlashMessagesDeliveryMiddleware.
    parziale = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method == "POST":
        risposta = _banco_azione(request)
        if not parziale:
            return risposta
        tutte = request.POST.get("tutte") == "1"
        pagina = render(request, "dpi/components/_banco_lavoro.html", _banco_contesto(request, tutte))
        pagina["X-Banco-Apri"] = risposta.url.partition("#")[2].removeprefix("apri-")
        pagina["X-Banco-Registrate"] = ",".join(str(i) for i in getattr(request, "banco_registrate", []))
        pagina["X-Banco-Annullate"] = ",".join(str(i) for i in getattr(request, "banco_annullate", []))
        if getattr(request, "banco_chiedi_motivo", False):
            pagina["X-Banco-Motivo"] = "1"
        return pagina

    if not parziale:
        completa_consegne_in_sospeso()
    tutte = request.GET.get("tutte") == "1"
    contesto = _banco_contesto(request, tutte)
    if parziale:
        return render(request, "dpi/components/_banco_lavoro.html", contesto)
    if contesto["ha_diretta"]:
        giac = magazzino.giacenze()
        modelli_diretti = list(_modelli_diretti().select_related("tipo", "tipo__categoria").prefetch_related("taglie").order_by(
            "tipo__categoria__order_index", "tipo__categoria__nome", "tipo__ordine", "nome"
        ))
        for m in modelli_diretti:
            m.giacenza = giac.get(m.pk, 0)
            m.taglie_attive = [t for t in m.taglie.all() if t.is_active]
        contesto["modelli_diretti"] = modelli_diretti
        contesto["dipendenti"] = _dipendenti_selezionabili(request)
    contesto["cerca"] = request.GET.get("cerca", "").strip()[:80]
    contesto["catalogo_modelli"] = _banco_catalogo()
    contesto["badge_persone"] = _banco_badge_persone(request)
    return render(request, "dpi/pages/banco.html", contesto)


def _banco_catalogo() -> dict[str, list[dict]]:
    """Per categoria, i modelli tra cui scegliere al banco, con giacenza e taglie."""
    giac = magazzino.giacenze()
    catalogo: dict[str, list[dict]] = {}
    modelli = ModelloDPI.objects.filter(is_active=True, tipo__is_active=True, tipo__categoria__is_active=True).select_related(
        "tipo"
    ).prefetch_related("taglie").order_by("tipo__ordine", "codice", "nome")
    for m in modelli:
        catalogo.setdefault(str(m.tipo.categoria_id), []).append({
            "id": m.pk,
            "nome": f"{m.codice} {m.nome}".strip(),
            "giacenza": giac.get(m.pk, 0),
            "taglie": [{"id": t.pk, "valore": t.valore} for t in m.taglie.all() if t.is_active],
        })
    return catalogo


def _banco_badge_persone(request) -> list[dict]:
    """Badge delle persone selezionabili: una lettura riconosce anche chi non ha richieste aperte."""
    from anagrafica.models import DipendenteAnagraficaAziendale

    nomi = {d["id"]: d["nome"] for d in _dipendenti_selezionabili(request)}
    righe = DipendenteAnagraficaAziendale.objects.exclude(badge="").filter(
        legacy_anagrafica_id__in=list(nomi)
    ).values_list("legacy_anagrafica_id", "badge")
    return [{"id": legacy, "nome": nomi[legacy], "badge": badge} for legacy, badge in righe]


def _prelievo_gruppi(qs, giac: dict) -> list[dict]:
    """Richieste da preparare raggruppate per cio' che si prende dallo scaffale."""
    gruppi: dict[tuple, dict] = {}
    for r in qs.order_by("richiedente_nome", "created_at"):
        chiave = (r.categoria_id, r.modello_dpi_id, r.tipo_dpi_id if not r.modello_dpi_id else None, r.taglia_dpi_id)
        g = gruppi.setdefault(chiave, {
            "categoria": r.categoria.nome,
            "etichetta": r.modello_dpi.nome if r.modello_dpi_id else (r.tipo_dpi.nome if r.tipo_dpi_id else r.categoria.nome),
            "codice": r.modello_dpi.codice if r.modello_dpi_id else "",
            "taglia": r.taglia_dpi.valore if r.taglia_dpi_id else "",
            "giacenza": giac.get(r.modello_dpi_id, 0) if r.modello_dpi_id and not r.modalita_negozio else None,
            "pezzi": 0,
            "richieste": [],
        })
        g["pezzi"] += r.quantita
        g["richieste"].append(r)
    for g in gruppi.values():
        g["manca"] = bool(giac) and g["giacenza"] is not None and g["giacenza"] < g["pezzi"]
    return sorted(gruppi.values(), key=lambda g: (g["categoria"].casefold(), g["etichetta"].casefold(), g["taglia"]))


@login_required
def banco_prelievo(request):
    """Foglio per preparare i DPI: tutto cio' che e' da preparare, e l'avviso di ritiro in blocco."""
    from django.urls import reverse

    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    tutte = (request.POST if request.method == "POST" else request.GET).get("tutte") == "1"
    qs = _banco_queryset(request).filter(pronta_ritiro_il__isnull=True)
    if not tutte:
        qs = qs.filter(categoria__consegna_magazzino=True)
    url = reverse("dpi:banco_prelievo") + ("?tutte=1" if tutte else "")
    if request.method == "POST":
        ids = [i for i in (_int_or_none(v) for v in request.POST.getlist("ids")) if i]
        richieste = list(qs.filter(pk__in=ids)) if ids else []
        autore = request.user.get_full_name() or request.user.username
        for r in richieste:
            _segna_pronta(request, r, da_nome=autore)
        if richieste:
            messages.success(request, f"Avvisi di ritiro inviati: {len(richieste)}.")
        else:
            messages.warning(request, "Spunta almeno un DPI.")
        return redirect(url)
    gruppi = _prelievo_gruppi(qs, magazzino.giacenze())
    return render(request, "dpi/pages/banco_prelievo.html", {
        "is_gestore": True,
        "is_approvatore": True,
        "tutte": tutte,
        "gruppi": gruppi,
        "n_righe": sum(len(g["richieste"]) for g in gruppi),
        "n_pezzi": sum(g["pezzi"] for g in gruppi),
        "oggi": timezone.localdate(),
    })


def _modelli_diretti():
    return ModelloDPI.objects.filter(
        is_active=True, tipo__is_active=True, tipo__categoria__is_active=True,
        tipo__categoria__consegna_diretta=True,
    )


def _banco_contesto(request, tutte: bool) -> dict:
    """La parte di lavoro del banco: numeri, persone, conferme."""
    qs = _banco_queryset(request)
    n_altre = qs.filter(categoria__consegna_magazzino=False).count()
    if not tutte:
        qs = qs.filter(categoria__consegna_magazzino=True)
    giac = magazzino.giacenze()
    persone = _banco_persone(qs, giac)
    from anagrafica.models import DipendenteAnagraficaAziendale

    badge = dict(DipendenteAnagraficaAziendale.objects.exclude(badge="").filter(
        legacy_anagrafica_id__in=[p["legacy_id"] for p in persone if p["legacy_id"]]
    ).values_list("legacy_anagrafica_id", "badge"))
    for p in persone:
        p["badge"] = badge.get(p["legacy_id"], "")

    from .models import ConfermaConsegnaDPI

    conferme_qs = _banco_conferme_qs(request)
    conferme_attesa = list(conferme_qs.filter(stato=ConfermaConsegnaDPI.Stato.IN_ATTESA).order_by("created_at")[:30])
    conferme_contestate = list(conferme_qs.filter(
        stato=ConfermaConsegnaDPI.Stato.CONTESTATA, decisa_il__gte=timezone.now() - timedelta(days=30)
    ).order_by("-decisa_il")[:30])

    return {
        "conferme_attesa": conferme_attesa,
        "n_conferme_attesa": conferme_qs.filter(stato=ConfermaConsegnaDPI.Stato.IN_ATTESA).count(),
        "conferme_contestate": conferme_contestate,
        "is_gestore": True,
        "is_approvatore": True,
        "persone": persone,
        "n_persone": len(persone),
        "n_pronte": sum(g["n_pronte"] for g in persone),
        "n_da_preparare": sum(g["n_da_preparare"] for g in persone),
        "n_mancanti": sum(g["n_mancanti"] for g in persone),
        "n_altre": n_altre,
        "tutte": tutte,
        "oggi": timezone.localdate(),
        "avviso_all_approvazione": DPIImpostazioni.get_singleton().avviso_ritiro_all_approvazione,
        "ha_diretta": _modelli_diretti().exists(),
    }
