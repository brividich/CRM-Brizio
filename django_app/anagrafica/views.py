from __future__ import annotations

import csv
import json
import logging
from datetime import timedelta as _timedelta
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from core.legacy_anagrafica import (
    count_anagrafica_statuses,
    ensure_anagrafica_schema,
    fetch_anagrafica_rows,
    generate_username,
    upsert_anagrafica_dipendente,
)
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.legacy_utils import is_legacy_admin, legacy_table_columns

from .forms import (
    AnagraficaAziendaleForm,
    AnagraficaCivileForm,
    DipendenteLegacyForm,
    VisitaMedicaForm,
)
from .models import (
    AnagraficaHRPermission,
    AnagraficaStatPermission,
    AnagraficaVisiteMedichePermission,
    AreaAziendale,
    CartellaDocumentoDipendente,
    SubnavCategoriaAnagrafica,
    SubnavLinkAnagrafica,
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    DipendenteCambiamentoOrganizzativo,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    DipendenteStatLayout,
    DocumentoDipendente,
    ImportazioneRetributiva,
    LivelloContrattuale,
    Mansione,
    RuoloAziendale,
    RuoloOperativo,
    ImportazioneCedolini,
    SaldoCedolino,
    StoricoContratto,
    TipologiaContratto,
    TipoQualifica,
    TipoVisitaMedica,
    VisitaMedica,
    VoceRetributiva,
    _classify_pay_item,
)
from .services.dpi_ingresso import (
    RigaConsegnaIniziale,
    archivia_pdf_cumulativo,
    crea_consegne_iniziali,
    proposta_righe_iniziali,
)
from .services.visite import stato_visite, visite_storico

logger = logging.getLogger(__name__)


def _file_field_url(file_field) -> str:
    if not file_field:
        return ""
    try:
        return file_field.url
    except (OSError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Dashboard anagrafica
# ---------------------------------------------------------------------------

@login_required
def index(request):
    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(deduplicate=True)
    n_dipendenti = len(rows)
    n_reparti = len({str(row.get("reparto") or "").strip().casefold() for row in rows if str(row.get("reparto") or "").strip()})

    # Conteggi catalogo per dashboard HR
    n_mansioni = Mansione.objects.filter(is_active=True).count()
    n_aree = AreaAziendale.objects.filter(is_active=True).count()
    n_qualifiche = TipoQualifica.objects.filter(is_active=True).count()

    # Qualifiche in scadenza nei prossimi 60 giorni
    from datetime import timedelta
    from django.utils import timezone as tz
    oggi = tz.localdate()
    soglia = oggi + timedelta(days=60)
    n_qualifiche_scadenza = DipendenteQualifica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__lte=soglia
    ).count()

    return render(request, "anagrafica/pages/index.html", {
        "n_dipendenti": n_dipendenti,
        "n_reparti": n_reparti,
        "n_mansioni": n_mansioni,
        "n_aree": n_aree,
        "n_qualifiche": n_qualifiche,
        "n_qualifiche_scadenza": n_qualifiche_scadenza,
    })


# ---------------------------------------------------------------------------
# Dipendenti (sola lettura — dati da legacy SQL Server)
# ---------------------------------------------------------------------------

@login_required
def dipendenti_list(request):
    ensure_anagrafica_schema()
    q = request.GET.get("q", "").strip()
    reparto = request.GET.get("reparto", "").strip()
    area_filter = request.GET.get("area", "").strip()
    contratto_filter = request.GET.get("tipologia_contratto", "").strip()

    rows = fetch_anagrafica_rows(deduplicate=True)
    reparti_list = sorted({str(row.get("reparto") or "").strip() for row in rows if str(row.get("reparto") or "").strip()})
    n_totale = len(rows)
    if q:
        q_norm = q.casefold()
        rows = [
            row
            for row in rows
            if any(
                q_norm in value.casefold()
                for value in [
                    str(row.get("nome") or "").strip(),
                    str(row.get("cognome") or "").strip(),
                    str(row.get("aliasusername") or "").strip(),
                    str(row.get("matricola") or "").strip(),
                ]
                if value
            )
        ]
    if reparto:
        rows = [row for row in rows if str(row.get("reparto") or "").strip().casefold() == reparto.casefold()]

    # Filtri su campi Django (area, tipologia_contratto)
    if area_filter or contratto_filter:
        az_qs = DipendenteAnagraficaAziendale.objects.all()
        if area_filter:
            az_qs = az_qs.filter(area__iexact=area_filter)
        if contratto_filter:
            az_qs = az_qs.filter(tipologia_contratto=contratto_filter)
        allowed_ids = set(az_qs.values_list("legacy_anagrafica_id", flat=True))
        rows = [row for row in rows if int(row.get("id") or 0) in allowed_ids]

    rows.sort(key=lambda row: (
        str(row.get("cognome") or "").strip().casefold(),
        str(row.get("nome") or "").strip().casefold(),
        str(row.get("aliasusername") or "").strip().casefold(),
        int(row.get("id") or 0),
    ))

    aree_list = sorted(
        DipendenteAnagraficaAziendale.objects.exclude(area="")
        .values_list("area", flat=True)
        .distinct()
        .order_by("area")
    )

    user_map = {
        int(user.id): user
        for user in UtenteLegacy.objects.filter(
            id__in=[int(row.get("utente_id") or 0) for row in rows if int(row.get("utente_id") or 0) > 0]
        )
    }
    for row in rows:
        raw_attivo = row.get("attivo")
        row["anagrafica_attivo"] = True if raw_attivo is None else bool(raw_attivo)
        row["matricola_legacy"] = str(row.get("matricola") or "").strip()
        row["ruolo_legacy"] = str(row.get("ruolo") or row.get("mansione") or "").strip()
        linked_user = user_map.get(int(row.get("utente_id") or 0))
        row["account_attivo"] = bool(getattr(linked_user, "attivo", False))
        row["has_account"] = bool(linked_user)
        row["timbri_operator_id"] = None
        row["timbri_count"] = 0
        row["timbri_legacy_id"] = int(row.get("id") or 0) or None

    paginator = Paginator(rows, 30)
    page = paginator.get_page(request.GET.get("page"))

    civile_map = {
        int(obj.legacy_anagrafica_id): obj
        for obj in DipendenteAnagraficaCivile.objects.filter(
            legacy_anagrafica_id__in=[int(dip.get("id") or 0) for dip in list(page.object_list)]
        ).only("legacy_anagrafica_id", "foto")
    }
    for dip in list(page.object_list):
        civile = civile_map.get(int(dip.get("id") or 0))
        dip["foto_url"] = _file_field_url(civile.foto) if civile else ""

    try:
        from timbri.models import OperatoreTimbri, RegistroTimbro

        operator_map: dict[int, OperatoreTimbri] = {
            int(obj.legacy_anagrafica_id): obj
            for obj in OperatoreTimbri.objects.filter(
                legacy_anagrafica_id__in=[int(dip.get("id") or 0) for dip in list(page.object_list)]
            )
            if obj.legacy_anagrafica_id
        }

        counts = {
            int(row["operatore_id"]): int(row["n"])
            for row in RegistroTimbro.objects.filter(operatore_id__in=[op.id for op in operator_map.values()])
            .order_by()
            .values("operatore_id")
            .annotate(n=Count("id"))
        }
        for dip in list(page.object_list):
            legacy_id = int(dip.get("id") or 0)
            operatore = operator_map.get(legacy_id)
            dip["timbri_operator_id"] = getattr(operatore, "id", None)
            dip["timbri_count"] = counts.get(getattr(operatore, "id", 0), 0)
            dip["timbri_legacy_id"] = legacy_id if legacy_id > 0 else None
    except Exception:
        logger.exception("Impossibile arricchire l'elenco dipendenti con i dati timbri.")
        for dip in list(page.object_list):
            dip["timbri_operator_id"] = None
            dip["timbri_count"] = 0
            dip["timbri_legacy_id"] = None

    status_stats = count_anagrafica_statuses()
    tipologie_contratto_list = list(
        TipologiaContratto.objects.filter(is_active=True).order_by("ordine", "codice")
    )
    return render(request, "anagrafica/pages/dipendenti_list.html", {
        "page_obj": page,
        "q": q,
        "reparto": reparto,
        "area": area_filter,
        "tipologia_contratto": contratto_filter,
        "reparti": reparti_list,
        "aree": aree_list,
        "tipologie_contratto": tipologie_contratto_list,
        "n_totale": n_totale,
        "n_reparti": len(reparti_list),
        "n_attivi": status_stats["active"],
        "n_non_attivi": status_stats["inactive"],
    })


# ---------------------------------------------------------------------------
# Dipendente — creazione completa (legacy + civile + aziendale)
# ---------------------------------------------------------------------------

@login_required
def dipendente_create(request):
    ensure_anagrafica_schema()
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    if not is_admin:
        messages.error(request, "Non hai i permessi per creare un dipendente.")
        return redirect("anagrafica:dipendenti_list")

    can_hr = _check_hr_permission(request)

    if request.method == "POST":
        legacy_form = DipendenteLegacyForm(request.POST)
        form_civile = AnagraficaCivileForm(request.POST, request.FILES)
        form_aziendale = AnagraficaAziendaleForm(request.POST)

        # Le form civile/aziendale sono facoltative: ignora errori se tutti i campi sono vuoti
        civile_has_data = any(
            v for k, v in request.POST.items()
            if k not in ("csrfmiddlewaretoken",) and not k.startswith("az_") and not k.startswith("legacy_")
            and v and k in AnagraficaCivileForm().fields
        ) or bool(request.FILES)
        aziendale_has_data = any(
            v for k, v in request.POST.items()
            if k not in ("csrfmiddlewaretoken",) and v and k in AnagraficaAziendaleForm().fields
        )

        if legacy_form.is_valid():
            data = legacy_form.cleaned_data
            try:
                _nome = (data.get("nome") or "").strip()
                _cognome = (data.get("cognome") or "").strip()
                _alias = (data.get("aliasusername") or "").strip()
                if not _alias:
                    _existing_u = set(
                        AnagraficaDipendente.objects
                        .exclude(aliasusername="")
                        .exclude(aliasusername__isnull=True)
                        .values_list("aliasusername", flat=True)
                    )
                    _alias = generate_username(_nome, _cognome, _existing_u)
                row = upsert_anagrafica_dipendente(
                    aliasusername=_alias,
                    nome=_nome,
                    cognome=_cognome,
                    matricola=(data.get("matricola") or "").strip(),
                    reparto=(data.get("reparto") or "").strip(),
                    mansione=(data.get("mansione") or "").strip(),
                    ruolo=(data.get("ruolo") or "").strip(),
                    email=(data.get("email") or "").strip(),
                    email_notifica=(data.get("email_notifica") or "").strip(),
                    attivo=bool(data.get("attivo")),
                    utente_id=None,
                )
                new_id = int(row.get("id") or 0)

                # Salva anagrafica aziendale se il form è valido
                if new_id and form_aziendale.is_valid():
                    az = form_aziendale.save(commit=False)
                    az.legacy_anagrafica_id = new_id
                    az.updated_by = request.user
                    az.save()

                # Salva anagrafica civile se il form è valido
                if new_id and form_civile.is_valid():
                    civ = form_civile.save(commit=False)
                    civ.legacy_anagrafica_id = new_id
                    civ.updated_by = request.user
                    civ.save()

                # Assegna ruoli operativi scelti nel form (multiselect "ruoli_operativi_ids")
                if new_id:
                    ruoli_raw = request.POST.getlist("ruoli_operativi_ids")
                    ruoli_ids: list[int] = []
                    for raw in ruoli_raw:
                        try:
                            ruoli_ids.append(int(raw))
                        except (TypeError, ValueError):
                            continue
                    if ruoli_ids:
                        ruoli_validi = list(
                            RuoloOperativo.objects.filter(pk__in=ruoli_ids, is_active=True)
                        )
                        for ruolo in ruoli_validi:
                            DipendenteRuoloOperativo.objects.get_or_create(
                                legacy_anagrafica_id=new_id,
                                ruolo=ruolo,
                                defaults={"assegnato_da": request.user},
                            )

                # DPI consegnati all'ingresso (proposti dalla mansione e confermati da HR)
                if new_id:
                    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=new_id).first()
                    aziendale_obj = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=new_id).first()
                    righe_iniziali = _parse_dpi_iniziali_post(request.POST)
                    if righe_iniziali:
                        consegne = crea_consegne_iniziali(
                            civile_obj, aziendale_obj, righe_iniziali, request.user
                        )
                        if consegne:
                            archivia_pdf_cumulativo(consegne, request.user)
                            try:
                                from core.audit import log_action
                                log_action(
                                    request, "DPI_CONSEGNA_INGRESSO", "anagrafica",
                                    f"Consegna iniziale DPI a #{new_id}: {len(consegne)} articoli",
                                )
                            except Exception:
                                logger.warning("Audit DPI_CONSEGNA_INGRESSO fallito", exc_info=True)

                # Crea primo StoricoContratto se la sezione contratto è stata compilata
                if new_id:
                    from datetime import date as _date
                    data_inizio_raw = (request.POST.get("contratto_data_inizio") or "").strip()
                    if data_inizio_raw:
                        try:
                            data_inizio = _date.fromisoformat(data_inizio_raw)
                        except ValueError:
                            data_inizio = None
                        if data_inizio:
                            data_fine_raw = (request.POST.get("contratto_data_fine") or "").strip()
                            data_fine = None
                            if data_fine_raw:
                                try:
                                    data_fine = _date.fromisoformat(data_fine_raw)
                                except ValueError:
                                    data_fine = None
                            tip_id = request.POST.get("contratto_tipologia_id") or ""
                            tipologia_codice = ""
                            if tip_id.isdigit():
                                tip = TipologiaContratto.objects.filter(pk=int(tip_id)).first()
                                if tip:
                                    tipologia_codice = tip.codice
                            cod_lvl = (request.POST.get("contratto_codice_livello") or "").strip().upper()[:10]
                            descr_lvl = ""
                            if cod_lvl:
                                lvl = LivelloContrattuale.objects.filter(codice=cod_lvl).first()
                                if lvl:
                                    descr_lvl = lvl.descrizione
                            tax_code = (request.POST.get("codice_fiscale") or "").upper().strip()[:16]
                            StoricoContratto.objects.create(
                                legacy_anagrafica_id=new_id,
                                tax_code=tax_code,
                                data_inizio=data_inizio,
                                data_fine=data_fine,
                                tipologia_contratto=tipologia_codice,
                                codice_livello=cod_lvl,
                                descrizione_livello=descr_lvl,
                                ccnl=(request.POST.get("contratto_ccnl") or "").strip()[:100],
                                qualifica_nome=(request.POST.get("contratto_qualifica_nome") or "").strip()[:150],
                                importato_da=request.user,
                            )

                nome_disp = f"{data.get('cognome', '')} {data.get('nome', '')}".strip() or "Dipendente"
                messages.success(request, f'Dipendente "{nome_disp}" creato.')
                if new_id:
                    return redirect("anagrafica:dipendente_detail", legacy_id=new_id)
                return redirect("anagrafica:dipendenti_list")
            except Exception as exc:
                logger.exception("Errore creazione dipendente")
                messages.error(request, f"Impossibile creare il dipendente: {exc}")
        else:
            messages.error(request, "Controlla i campi obbligatori nella sezione Dati account.")
    else:
        legacy_form = DipendenteLegacyForm(initial={"attivo": True})
        form_civile = AnagraficaCivileForm()
        form_aziendale = AnagraficaAziendaleForm()

    return render(request, "anagrafica/pages/dipendente_create.html", {
        "legacy_form": legacy_form,
        "form_civile": form_civile,
        "form_aziendale": form_aziendale,
        "can_hr": can_hr,
        "mansioni_catalogo": list(Mansione.objects.filter(is_active=True).order_by("nome")),
        "contratto_choices": DipendenteAnagraficaAziendale.CONTRATTO_CHOICES,
        "tipologie_contratto": list(TipologiaContratto.objects.filter(is_active=True).order_by("ordine", "codice")),
        "livelli_contrattuali": list(LivelloContrattuale.objects.filter(is_active=True).order_by("ordine", "codice")),
        "ruoli_operativi_catalogo": list(RuoloOperativo.objects.filter(is_active=True).order_by("nome")),
    })


def _parse_dpi_iniziali_post(post) -> list[RigaConsegnaIniziale]:
    """Estrae le righe DPI iniziali confermate (checkbox 'consegnato') dal POST.

    Convenzioni di name dei campi (per indice intero ``i``):
      - ``dpi_consegnato_<i>`` checkbox (presenza = riga selezionata)
      - ``dpi_categoria_id_<i>`` int obbligatorio
      - ``dpi_modello_id_<i>`` int opzionale
      - ``dpi_taglia_id_<i>`` int opzionale
      - ``dpi_quantita_<i>`` int (default 1)

    Gli indici disponibili sono enumerati dal campo nascosto ``dpi_indici``
    (CSV) inviato dal partial HTMX.
    """
    righe: list[RigaConsegnaIniziale] = []
    indici_raw = post.get("dpi_indici", "").strip()
    if not indici_raw:
        return righe
    for token in indici_raw.split(","):
        token = token.strip()
        if not token.isdigit():
            continue
        i = int(token)
        if not post.get(f"dpi_consegnato_{i}"):
            continue
        cat_raw = post.get(f"dpi_categoria_id_{i}", "").strip()
        if not cat_raw.isdigit():
            continue
        try:
            quantita = int(post.get(f"dpi_quantita_{i}", "1") or 1)
        except ValueError:
            quantita = 1
        def _int_or_none(value: str) -> int | None:
            value = (value or "").strip()
            return int(value) if value.isdigit() else None

        righe.append(RigaConsegnaIniziale(
            categoria_id=int(cat_raw),
            quantita=max(1, quantita),
            tipo_id=_int_or_none(post.get(f"dpi_tipo_id_{i}", "")),
            modello_id=_int_or_none(post.get(f"dpi_modello_id_{i}", "")),
            taglia_id=_int_or_none(post.get(f"dpi_taglia_id_{i}", "")),
        ))
    return righe


# ---------------------------------------------------------------------------
# NOTE: tutte le view "Fornitori" sono state spostate nel modulo dedicato
# `fornitori` (URL prefix /fornitori/). I modelli Fornitore* restano in
# `anagrafica.models` perché referenziati da `assets.models` via FK storiche
# (tabelle DB invariate).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Definizione widget statistiche dipendente
# ---------------------------------------------------------------------------

STAT_WIDGETS = [
    {
        "id": "tickets_aperti",
        "title": "Ticket aperti",
        "icon": "🎫",
        "color": "#ef4444",
        "link_url": "/tickets/",
        "link_label": "Vai ai ticket",
    },
    {
        "id": "tickets_totali",
        "title": "Ticket totali",
        "icon": "📋",
        "color": "#3b82f6",
        "link_url": "/tickets/",
        "link_label": "Vai ai ticket",
    },
    {
        "id": "anomalie",
        "title": "Anomalie",
        "icon": "⚠️",
        "color": "#f59e0b",
        "link_url": "/gestione-anomalie/",
        "link_label": "Vai alle anomalie",
    },
    {
        "id": "diario_preposto",
        "title": "Diario preposto",
        "icon": "📔",
        "color": "#8b5cf6",
        "link_url": "/diario-preposto/",
        "link_label": "Vai al diario",
    },
    {
        "id": "rilevazioni",
        "title": "Rilevazioni sicurezza",
        "icon": "🦺",
        "color": "#10b981",
        "link_url": "/rilevazione-incidenti/",
        "link_label": "Vai alle rilevazioni",
    },
    {
        "id": "assenze",
        "title": "Assenze",
        "icon": "📅",
        "color": "#06b6d4",
        "link_url": "/assenze/",
        "link_label": "Vai alle assenze",
    },
    {
        "id": "timbri",
        "title": "Timbri",
        "icon": "🕐",
        "color": "#64748b",
        "link_url": "",
        "link_label": "Vai ai timbri",
    },
    {
        "id": "dpi",
        "title": "DPI richiesti",
        "icon": "🦺",
        "color": "#16a34a",
        "link_url": "/dpi/gestione/",
        "link_label": "Vai ai DPI",
    },
]

_WIDGET_DEFAULT_ORDER = [w["id"] for w in STAT_WIDGETS]


def _can_view_stats(request) -> bool:
    """Verifica se l'utente corrente può visualizzare la sezione statistiche."""
    if request.user.is_superuser:
        return True
    perm = AnagraficaStatPermission.get_instance()
    if perm.accesso == AnagraficaStatPermission.ACCESSO_TUTTI:
        return True
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if is_legacy_admin(legacy_user):
        return True
    if perm.accesso == AnagraficaStatPermission.ACCESSO_ADMIN:
        return False
    # ACCESSO_RUOLI: controlla se il ruolo dell'utente è nella lista
    if legacy_user and legacy_user.ruolo_id is not None:
        return int(legacy_user.ruolo_id) in [int(r) for r in (perm.ruolo_ids or [])]
    return False


def _check_hr_permission(request) -> bool:
    """Verifica se l'utente può vedere i dati HR riservati (IBAN, CF, disabilità)."""
    if request.user.is_superuser:
        return True
    perm = AnagraficaHRPermission.get_instance()
    if perm.accesso == AnagraficaHRPermission.ACCESSO_TUTTI:
        return True
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if is_legacy_admin(legacy_user):
        return perm.accesso in (AnagraficaHRPermission.ACCESSO_ADMIN, AnagraficaHRPermission.ACCESSO_TUTTI)
    if perm.accesso == AnagraficaHRPermission.ACCESSO_ADMIN:
        return False
    if legacy_user and legacy_user.ruolo_id is not None:
        return int(legacy_user.ruolo_id) in [int(r) for r in (perm.ruolo_ids or [])]
    return False


def _can_view_visite_mediche(request) -> bool:
    """Verifica se l'utente può vedere/registrare le visite mediche.

    Le visite mediche contengono dati sanitari sensibili (idoneità, prescrizioni).
    Il default del singleton è ADMIN: solo superuser + amministratori legacy.
    """
    if request.user.is_superuser:
        return True
    perm = AnagraficaVisiteMedichePermission.get_instance()
    if perm.accesso == AnagraficaVisiteMedichePermission.ACCESSO_TUTTI:
        return True
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if is_legacy_admin(legacy_user):
        return perm.accesso in (
            AnagraficaVisiteMedichePermission.ACCESSO_ADMIN,
            AnagraficaVisiteMedichePermission.ACCESSO_TUTTI,
        )
    if perm.accesso == AnagraficaVisiteMedichePermission.ACCESSO_ADMIN:
        return False
    if legacy_user and legacy_user.ruolo_id is not None:
        return int(legacy_user.ruolo_id) in [int(r) for r in (perm.ruolo_ids or [])]
    return False


def _compute_widget_counts(dip: dict) -> dict[str, int]:
    """Calcola i contatori per ogni widget statistiche del dipendente."""
    legacy_id = int(dip.get("id") or 0)
    nome = str(dip.get("nome") or "").strip()
    cognome = str(dip.get("cognome") or "").strip()
    nome_completo = f"{nome} {cognome}".strip()
    counts: dict[str, int] = {w["id"]: 0 for w in STAT_WIDGETS}

    # Ticket aperti e totali
    try:
        from tickets.models import StatoTicket, Ticket
        qs = Ticket.objects.filter(richiedente_legacy_user_id=legacy_id) if legacy_id else Ticket.objects.none()
        counts["tickets_totali"] = qs.count()
        counts["tickets_aperti"] = qs.filter(stato=StatoTicket.APERTA).count()
    except Exception:
        logger.exception("Errore conteggio ticket per dipendente %s", legacy_id)

    # Anomalie (legacy SQL Server — solo se connesso)
    try:
        from django.db import connections
        with connections["default"].cursor() as cur:
            # Cerca per nome in capo_commessa (campo testo con nome)
            cur.execute(
                "SELECT COUNT(*) FROM anomalie WHERE UPPER(COALESCE(capo_commessa,'')) LIKE UPPER(%s)",
                [f"%{nome_completo}%"],
            )
            row = cur.fetchone()
            counts["anomalie"] = int(row[0]) if row else 0
    except Exception:
        logger.debug("Impossibile contare anomalie per dipendente %s (tabella legacy assente in dev)", legacy_id)

    # Diario preposto
    try:
        from diario_preposto.models import SegnalazionePreposto
        counts["diario_preposto"] = SegnalazionePreposto.objects.filter(
            Q(chi_segnala__icontains=nome_completo) | Q(preposto__icontains=nome_completo)
        ).count()
    except Exception:
        logger.exception("Errore conteggio diario preposto per dipendente %s", legacy_id)

    # Rilevazioni sicurezza
    try:
        from rilevazione_incidenti.models import RilevazioneIncidente
        counts["rilevazioni"] = RilevazioneIncidente.objects.filter(
            nominativo__icontains=nome_completo
        ).count()
    except Exception:
        logger.exception("Errore conteggio rilevazioni per dipendente %s", legacy_id)

    # Assenze (legacy SQL Server)
    try:
        from django.db import connections
        with connections["default"].cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM assenze WHERE UPPER(COALESCE(copia_nome,'')) LIKE UPPER(%s)",
                [f"%{nome_completo}%"],
            )
            row = cur.fetchone()
            counts["assenze"] = int(row[0]) if row else 0
    except Exception:
        logger.debug("Impossibile contare assenze per dipendente %s (tabella legacy assente in dev)", legacy_id)

    # Timbri
    try:
        from timbri.models import OperatoreTimbri, RegistroTimbro
        operatore = OperatoreTimbri.objects.filter(legacy_anagrafica_id=legacy_id).first()
        if operatore:
            counts["timbri"] = RegistroTimbro.objects.filter(operatore=operatore).count()
    except Exception:
        logger.exception("Errore conteggio timbri per dipendente %s", legacy_id)

    # DPI richiesti
    try:
        from dpi.models import RichiestaDPI
        counts["dpi"] = RichiestaDPI.objects.filter(richiedente_legacy_id=legacy_id).count() if legacy_id else 0
    except Exception:
        logger.exception("Errore conteggio DPI per dipendente %s", legacy_id)

    return counts


# ---------------------------------------------------------------------------
# Scheda dettaglio dipendente
# ---------------------------------------------------------------------------

@login_required
def dipendente_detail(request, legacy_id: int):
    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    can_stats = _can_view_stats(request)
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    can_hr = _check_hr_permission(request)

    # Anagrafica civile e aziendale estese
    civile = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    aziendale = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).first()
    civile_foto_url = _file_field_url(civile.foto) if civile else ""
    form_civile = AnagraficaCivileForm(instance=civile) if is_admin else None
    form_aziendale = AnagraficaAziendaleForm(instance=aziendale) if is_admin else None

    # Widget layout viewer
    layout_obj = DipendenteStatLayout.objects.filter(viewer_user_id=request.user.id).first()
    hidden_ids: list[str] = list(layout_obj.hidden) if layout_obj else []
    order_ids: list[str] = list(layout_obj.order) if layout_obj else []

    # Costruisce lista widget ordinata
    all_widget_ids = [w["id"] for w in STAT_WIDGETS]
    if order_ids:
        ordered = [wid for wid in order_ids if wid in all_widget_ids]
        ordered += [wid for wid in all_widget_ids if wid not in ordered]
    else:
        ordered = all_widget_ids[:]

    # Contatori
    widget_counts: dict[str, int] = {}
    if can_stats:
        widget_counts = _compute_widget_counts(dip)

    # Costruisce URL filtrati per dipendente
    from urllib.parse import urlencode
    from django.urls import reverse as _reverse

    _nome = str(dip.get("nome") or "").strip()
    _cognome = str(dip.get("cognome") or "").strip()
    _nome_completo = f"{_cognome} {_nome}".strip()
    _alias = str(dip.get("aliasusername") or "").strip()

    def _qs(**params):
        return "?" + urlencode(params) if params else ""

    try:
        _ticket_base = _reverse("tickets:gestione_list")
    except Exception:
        _ticket_base = "/tickets/gestione/"
    try:
        _diario_base = _reverse("diario_preposto:lista")
    except Exception:
        _diario_base = "/diario-preposto/"
    try:
        _rilevazioni_base = _reverse("rilevazione_incidenti:lista")
    except Exception:
        _rilevazioni_base = "/rilevazione-incidenti/"
    try:
        _timbri_base = _reverse("timbri:operatore_detail_by_legacy", args=[legacy_id])
    except Exception:
        _timbri_base = ""

    _widget_links: dict[str, str] = {
        "tickets_aperti": _ticket_base + _qs(q=_nome_completo, stato="APERTA"),
        "tickets_totali": _ticket_base + _qs(q=_nome_completo),
        "anomalie": "/gestione-anomalie/",
        "diario_preposto": _diario_base + _qs(q=_nome_completo),
        "rilevazioni": _rilevazioni_base + _qs(q=_nome_completo),
        "assenze": "/assenze/",
        "timbri": _timbri_base,
        "dpi": "/dpi/gestione/" + _qs(q=_nome_completo),
    }

    # Costruisce lista widget con dati
    widget_map = {w["id"]: w for w in STAT_WIDGETS}
    widgets_visible = []
    widgets_hidden = []
    for wid in ordered:
        w = dict(widget_map[wid])
        w["count"] = widget_counts.get(wid, 0)
        if wid in _widget_links:
            w["link_url"] = _widget_links[wid]
        if wid in hidden_ids:
            widgets_hidden.append(w)
        else:
            widgets_visible.append(w)

    # Ruoli operativi
    ruoli_assegnati = list(
        DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=legacy_id)
        .select_related("ruolo", "assegnato_da")
        .order_by("ruolo__nome")
    )
    ruoli_disponibili = RuoloOperativo.objects.filter(is_active=True).exclude(
        id__in=[a.ruolo_id for a in ruoli_assegnati]
    )

    # Mansioni catalogo
    mansioni_catalogo = list(Mansione.objects.filter(is_active=True).order_by("nome"))

    # Qualifiche dipendente
    from django.utils import timezone as tz
    from datetime import timedelta
    oggi = tz.localdate()
    qualifiche_dip = list(
        DipendenteQualifica.objects.filter(legacy_anagrafica_id=legacy_id)
        .select_related("tipo")
        .order_by("data_scadenza", "tipo__nome")
    )
    tipi_qualifica = list(TipoQualifica.objects.filter(is_active=True).order_by("categoria", "nome"))

    # DPI dipendente
    dpi_consegnati = []
    dpi_richieste = []
    try:
        from dpi.models import RichiestaDPI
        dpi_richieste = list(
            RichiestaDPI.objects.filter(richiedente_legacy_id=legacy_id)
            .select_related("categoria", "consegna")
            .order_by("-created_at")[:20]
        )
        dpi_consegnati = [r for r in dpi_richieste if r.stato == "CONSEGNATA" and hasattr(r, "consegna")]
    except Exception:
        logger.exception("Errore caricamento DPI per dipendente %s", legacy_id)

    # PDF consegne DPI archiviati: mappa consegna_id -> documento per linkare dal tab
    dpi_consegna_doc_map: dict[int, int] = {}
    try:
        dpi_docs = DocumentoDipendente.objects.filter(
            legacy_anagrafica_id=legacy_id,
            tipo=DocumentoDipendente.Tipo.DPI_CONSEGNA,
            oggetto_riferimento_tipo="dpi.consegna",
        ).values_list("oggetto_riferimento_id", "id")
        dpi_consegna_doc_map = {int(c): int(d) for c, d in dpi_docs if c is not None}
    except Exception:
        logger.exception("Errore caricamento documenti DPI per dipendente %s", legacy_id)

    # Visite mediche (dato sanitario sensibile: gating su _can_view_visite_mediche)
    can_view_visite = _can_view_visite_mediche(request)
    visite_stato_list: list = []
    visite_storico_list: list = []
    tipi_visita_attivi: list = []
    if can_view_visite:
        try:
            visite_stato_list = stato_visite(legacy_id)
            visite_storico_list = visite_storico(legacy_id)
            tipi_visita_attivi = list(
                TipoVisitaMedica.objects.filter(is_active=True).order_by("nome")
            )
        except Exception:
            logger.exception("Errore caricamento visite mediche per dipendente %s", legacy_id)

    # Documenti dipendente (spazio privato): riga in tab "Documenti"
    documenti_dipendente = []
    cartelle_documenti = []
    try:
        qs_doc = DocumentoDipendente.objects.filter(legacy_anagrafica_id=legacy_id).select_related("cartella")
        # Nasconde i referti sanitari a chi non ha il permesso visite
        if not can_view_visite:
            qs_doc = qs_doc.exclude(tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO)
        documenti_dipendente = list(qs_doc.order_by("-created_at")[:100])
        cartelle_documenti = list(CartellaDocumentoDipendente.objects.filter(attiva=True).order_by("ordine", "nome"))
    except Exception:
        logger.exception("Errore caricamento documenti per dipendente %s", legacy_id)

    software_licenses = []
    try:
        from assets.models import SoftwareLicense

        legacy_user_id = int(dip.get("utente_id") or 0)
        license_qs = SoftwareLicense.objects.filter(
            Q(assigned_anagrafica_id=legacy_id)
            | (Q(assigned_legacy_user_id=legacy_user_id) if legacy_user_id else Q())
        ).select_related("asset").order_by("category", "vendor", "product_name", "id")
        software_licenses = list(license_qs)
    except Exception:
        logger.exception("Errore caricamento licenze software per dipendente %s", legacy_id)

    # Asset assegnati al dipendente e asset del reparto (se caporeparto)
    assets_assegnati: list = []
    assets_reparto: list = []
    reparti_capo: list = []
    try:
        from assets.models import Asset
        from core.models import RepartoCapoMapping

        utente_id_asset = int(dip.get("utente_id") or 0)
        if utente_id_asset:
            assets_assegnati = list(
                Asset.objects.filter(assigned_legacy_user_id=utente_id_asset)
                .exclude(status=Asset.STATUS_RETIRED)
                .select_related("asset_category")
                .order_by("name")
            )

        # Verifica se è caporeparto: cerca RepartoCapoMapping dove caporeparto
        # corrisponde a email, id numerico o nome dell'utente legacy
        capo_user = UtenteLegacy.objects.filter(id=utente_id_asset).first() if utente_id_asset else None
        if capo_user:
            capo_email = str(getattr(capo_user, "email", "") or "").strip().lower()
            capo_nome = str(getattr(capo_user, "nome", "") or "").strip()
            capo_filters = Q(caporeparto=str(utente_id_asset))
            if capo_email:
                capo_filters |= Q(caporeparto__iexact=capo_email)
            if capo_nome:
                capo_filters |= Q(caporeparto__iexact=capo_nome)
            reparti_capo = list(
                RepartoCapoMapping.objects.filter(capo_filters, is_active=True)
                .values_list("reparto", flat=True)
                .distinct()
            )
            if reparti_capo:
                assets_reparto = list(
                    Asset.objects.filter(assignment_reparto__in=reparti_capo)
                    .exclude(status=Asset.STATUS_RETIRED)
                    .select_related("asset_category")
                    .order_by("assignment_reparto", "name")
                )
    except Exception:
        logger.exception("Errore caricamento asset per dipendente %s", legacy_id)

    # Voci retributive (solo se l'utente ha accesso HR)
    retribuzioni_latest: list = []
    retribuzioni_timeline: list = []
    retribuzioni_importazione = None
    retribuzioni_data_competenza = None
    retribuzioni_has_changes = False
    if can_hr:
        _voci_q = Q(legacy_anagrafica_id=legacy_id)
        if civile and civile.codice_fiscale:
            _voci_q |= Q(tax_code=civile.codice_fiscale.strip().upper())
        voci_qs = VoceRetributiva.objects.filter(
            _voci_q
        ).select_related("importazione").order_by(
            "-data_competenza", "-importazione__data_importazione", "categoria", "pay_item_key"
        )
        voci_all = list(voci_qs)
        if voci_all:
            # Raggruppa per mese, separando CSV (solo più recente per mese) e manuali (sempre incluse).
            # Le voci manuali fanno override delle CSV con stesso pay_item_key.
            _by_month: dict = {}
            for v in voci_all:
                key = v.data_competenza
                if key not in _by_month:
                    _by_month[key] = {"csv_imp": None, "csv_voci": [], "manuale_voci": []}
                if v.manuale:
                    _by_month[key]["manuale_voci"].append(v)
                else:
                    if _by_month[key]["csv_imp"] is None:
                        _by_month[key]["csv_imp"] = v.importazione
                    if v.importazione_id == _by_month[key]["csv_imp"].id:
                        _by_month[key]["csv_voci"].append(v)

            def _merge(entry):
                manuale_keys = {v.pay_item_key for v in entry["manuale_voci"]}
                return [v for v in entry["csv_voci"] if v.pay_item_key not in manuale_keys] + entry["manuale_voci"]

            _months_desc = sorted(_by_month.keys(), reverse=True)
            if _months_desc:
                _latest_month = _months_desc[0]
                _latest_entry = _by_month[_latest_month]
                retribuzioni_data_competenza = _latest_month
                retribuzioni_importazione = _latest_entry["csv_imp"]  # può essere None se mese ha solo manuali
                retribuzioni_latest = _merge(_latest_entry)
                retribuzioni_has_changes = any(v.is_changed for v in retribuzioni_latest)
                retribuzioni_timeline = [(d, _merge(_by_month[d])) for d in _months_desc]

    _TOTALI_SORT = {"retribuzione di fatto": 0, "totale elementi variabili": 1, "rml": 2, "ral": 3}
    retribuzioni_fissi = [v for v in retribuzioni_latest if v.categoria == "fisso"]
    retribuzioni_variabili = [v for v in retribuzioni_latest if v.categoria == "variabile"]
    retribuzioni_totali = sorted(
        [v for v in retribuzioni_latest if v.categoria == "totale"],
        key=lambda v: _TOTALI_SORT.get(v.pay_item_key, 99),
    )
    retribuzioni_altri = [v for v in retribuzioni_latest if v.categoria == "altro"]

    # Ratei ferie/ROL/ex-festività da cedolini (solo se l'utente ha accesso HR)
    ratei_saldi: list = []
    if can_hr:
        _ratei_q = Q(legacy_anagrafica_id=legacy_id)
        if civile and civile.codice_fiscale:
            _ratei_q |= Q(tax_code=civile.codice_fiscale.strip().upper())
        ratei_saldi = list(
            SaldoCedolino.objects.filter(_ratei_q).order_by("-data_competenza")[:1]
        )

    # Storico cambiamenti organizzativi (mansione, reparto, area, ruolo aziendale) — solo admin
    storico_cambiamenti: list = []
    if is_admin:
        storico_cambiamenti = list(
            DipendenteCambiamentoOrganizzativo.objects
            .filter(legacy_anagrafica_id=legacy_id)
            .select_related("created_by")
            .order_by("-data_effetto", "-created_at")[:50]
        )

    # Storico contrattuale
    storico_contratti: list = []
    livelli_catalogo: list = []
    livelli_json: str = "{}"
    tipi_qualifica_prof: list = []
    if can_hr:
        _contr_q = Q(legacy_anagrafica_id=legacy_id)
        tax_code_contr = civile.codice_fiscale.strip().upper() if civile and civile.codice_fiscale else None
        if tax_code_contr:
            _contr_q |= Q(tax_code=tax_code_contr)
        storico_contratti = list(
            StoricoContratto.objects.filter(_contr_q).order_by("-data_inizio", "-created_at")
        )
        tipologie_contratto = list(TipologiaContratto.objects.filter(is_active=True))
        _tipologie_map = {t.codice: t.nome for t in tipologie_contratto}
        for _c in storico_contratti:
            _c.tipologia_nome = _tipologie_map.get(_c.tipologia_contratto, _c.tipologia_contratto)
        livelli_catalogo = list(LivelloContrattuale.objects.filter(is_active=True))
        livelli_json = json.dumps({l.codice: l.descrizione for l in livelli_catalogo})
        tipi_qualifica_prof = [q for q in tipi_qualifica if q.categoria == TipoQualifica.CAT_PROFESSIONALE]

    return render(request, "anagrafica/pages/dipendente_detail.html", {
        "dip": dip,
        "legacy_id": legacy_id,
        "can_stats": can_stats,
        "is_admin": is_admin,
        "can_hr": can_hr,
        "civile": civile,
        "civile_foto_url": civile_foto_url,
        "aziendale": aziendale,
        "form_civile": form_civile,
        "form_aziendale": form_aziendale,
        "widgets_visible": widgets_visible,
        "widgets_hidden": widgets_hidden,
        "all_widgets": STAT_WIDGETS,
        "ruoli_assegnati": ruoli_assegnati,
        "ruoli_disponibili": ruoli_disponibili,
        "mansioni_catalogo": mansioni_catalogo,
        "qualifiche_dip": qualifiche_dip,
        "tipi_qualifica": tipi_qualifica,
        "oggi": oggi,
        "oggi_plus60": oggi + timedelta(days=60),
        "dpi_richieste": dpi_richieste,
        "dpi_consegnati": dpi_consegnati,
        "dpi_consegna_doc_map": dpi_consegna_doc_map,
        "can_view_visite": can_view_visite,
        "visite_stato_list": visite_stato_list,
        "visite_storico_list": visite_storico_list,
        "tipi_visita_attivi": tipi_visita_attivi,
        "documenti_dipendente": documenti_dipendente,
        "cartelle_documenti": cartelle_documenti,
        "visita_esiti": VisitaMedica.Esito.choices,
        "software_licenses": software_licenses,
        "assets_assegnati": assets_assegnati,
        "assets_reparto": assets_reparto,
        "reparti_capo": reparti_capo,
        "retribuzioni_latest": retribuzioni_latest,
        "retribuzioni_fissi": retribuzioni_fissi,
        "retribuzioni_variabili": retribuzioni_variabili,
        "retribuzioni_totali": retribuzioni_totali,
        "retribuzioni_altri": retribuzioni_altri,
        "retribuzioni_timeline": retribuzioni_timeline,
        "retribuzioni_importazione": retribuzioni_importazione,
        "retribuzioni_data_competenza": retribuzioni_data_competenza,
        "retribuzioni_has_changes": retribuzioni_has_changes,
        "storico_cambiamenti": storico_cambiamenti,
        "storico_contratti": storico_contratti,
        "tipologie_contratto": tipologie_contratto,
        "livelli_catalogo": livelli_catalogo,
        "livelli_json": livelli_json,
        "tipi_qualifica_prof": tipi_qualifica_prof,
        "ratei_saldi": ratei_saldi,
    })


# ---------------------------------------------------------------------------
# API: salva layout widget scheda dipendente
# ---------------------------------------------------------------------------

@login_required
@require_POST
def api_dipendente_widget_layout(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"ok": False, "error": "JSON non valido"}, status=400)

    hidden = [str(wid) for wid in (data.get("hidden") or []) if wid in _WIDGET_DEFAULT_ORDER]
    order = [str(wid) for wid in (data.get("order") or []) if wid in _WIDGET_DEFAULT_ORDER]

    DipendenteStatLayout.objects.update_or_create(
        viewer_user_id=request.user.id,
        defaults={"hidden": hidden, "order": order},
    )
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Ruoli operativi — assegna/rimuovi a dipendente
# ---------------------------------------------------------------------------

@login_required
@require_POST
def dipendente_ruolo_assegna(request, legacy_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per assegnare ruoli operativi.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    ruolo_id = int(request.POST.get("ruolo_id") or 0)
    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id, is_active=True)
    _, created = DipendenteRuoloOperativo.objects.get_or_create(
        legacy_anagrafica_id=legacy_id,
        ruolo=ruolo,
        defaults={"assegnato_da": request.user},
    )
    if created:
        messages.success(request, f'Ruolo "{ruolo.nome}" assegnato.')
    else:
        messages.info(request, f'Ruolo "{ruolo.nome}" già assegnato.')
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_ruolo_rimuovi(request, legacy_id: int, assegnazione_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per rimuovere ruoli operativi.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    assegnazione = get_object_or_404(DipendenteRuoloOperativo, pk=assegnazione_id, legacy_anagrafica_id=legacy_id)
    nome = assegnazione.ruolo.nome
    assegnazione.delete()
    messages.success(request, f'Ruolo "{nome}" rimosso.')
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Ruoli operativi — gestione catalogo
# ---------------------------------------------------------------------------

@login_required
def ruoli_operativi_list(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)

    ruoli = RuoloOperativo.objects.annotate(n_assegnati=Count("assegnazioni")).order_by("nome")
    ruoli_suggeriti = [
        "Preposto", "RSPP", "ASPP", "RLS",
        "Squadra antincendio", "Squadra primo soccorso",
        "Addetto emergenze", "Rappresentante sicurezza",
    ]
    return render(request, "anagrafica/pages/ruoli_operativi.html", {
        "ruoli": ruoli,
        "is_admin": is_admin,
        "ruoli_suggeriti": ruoli_suggeriti,
    })


@login_required
@require_POST
def ruolo_operativo_create(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per creare ruoli operativi.")
        return _back_to_caller(request, "anagrafica:ruoli_operativi_list")

    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del ruolo è obbligatorio.")
        return _back_to_caller(request, "anagrafica:ruoli_operativi_list")

    _, created = RuoloOperativo.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "descrizione": (request.POST.get("descrizione") or "").strip(),
            "colore": (request.POST.get("colore") or "#64748b").strip()[:7],
            "icona": (request.POST.get("icona") or "").strip()[:10],
        },
    )
    if created:
        messages.success(request, f'Ruolo "{nome}" creato.')
    else:
        messages.warning(request, f'Esiste già un ruolo con il nome "{nome}".')
    return _back_to_caller(request, "anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ruolo_operativo_edit(request, ruolo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare ruoli operativi.")
        return _back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del ruolo è obbligatorio.")
        return _back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ruolo.nome = nome
    ruolo.descrizione = (request.POST.get("descrizione") or "").strip()
    ruolo.colore = (request.POST.get("colore") or "#64748b").strip()[:7]
    ruolo.icona = (request.POST.get("icona") or "").strip()[:10]
    ruolo.is_active = request.POST.get("is_active") == "1"
    ruolo.save()
    messages.success(request, f'Ruolo "{ruolo.nome}" aggiornato.')
    return _back_to_caller(request, "anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ruolo_operativo_delete(request, ruolo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare ruoli operativi.")
        return _back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id)
    nome = ruolo.nome
    ruolo.delete()
    messages.success(request, f'Ruolo "{nome}" eliminato.')
    return _back_to_caller(request, "anagrafica:ruoli_operativi_list")


# ---------------------------------------------------------------------------
# Impostazioni permessi sezione statistiche (solo admin)
# ---------------------------------------------------------------------------

@login_required
def widget_permissions(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Accesso riservato agli amministratori.")
        return redirect("anagrafica:index")

    from core.legacy_models import Ruolo
    perm = AnagraficaStatPermission.get_instance()

    if request.method == "POST":
        perm.accesso = request.POST.get("accesso", AnagraficaStatPermission.ACCESSO_ADMIN)
        if perm.accesso not in (
            AnagraficaStatPermission.ACCESSO_TUTTI,
            AnagraficaStatPermission.ACCESSO_ADMIN,
            AnagraficaStatPermission.ACCESSO_RUOLI,
        ):
            perm.accesso = AnagraficaStatPermission.ACCESSO_ADMIN
        ruolo_ids_raw = request.POST.getlist("ruolo_ids")
        perm.ruolo_ids = [int(r) for r in ruolo_ids_raw if str(r).isdigit()]
        perm.save()
        messages.success(request, "Impostazioni salvate.")
        return redirect("anagrafica:widget_permissions")

    try:
        ruoli_acl = list(Ruolo.objects.order_by("nome"))
    except Exception:
        ruoli_acl = []

    return render(request, "anagrafica/pages/widget_permissions.html", {
        "perm": perm,
        "ruoli_acl": ruoli_acl,
        "ACCESSO_TUTTI": AnagraficaStatPermission.ACCESSO_TUTTI,
        "ACCESSO_ADMIN": AnagraficaStatPermission.ACCESSO_ADMIN,
        "ACCESSO_RUOLI": AnagraficaStatPermission.ACCESSO_RUOLI,
    })


# ---------------------------------------------------------------------------
# Mansione dipendente — set dal catalogo (scrive su legacy DB)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def _registra_cambiamento(
    legacy_id: int,
    tipo: str,
    vecchio: str,
    nuovo: str,
    user,
    data_effetto=None,
    note: str = "",
) -> DipendenteCambiamentoOrganizzativo | None:
    """Crea una riga di storico solo se il valore è effettivamente cambiato.

    Confronto case-insensitive con strip, così micro-edit di whitespace o maiuscole
    non generano voci storiche spurie.
    """
    from django.utils import timezone as _tz
    v = (vecchio or "").strip()
    n = (nuovo or "").strip()
    if v.casefold() == n.casefold():
        return None
    return DipendenteCambiamentoOrganizzativo.objects.create(
        legacy_anagrafica_id=legacy_id,
        tipo=tipo,
        valore_precedente=v[:300],
        valore_nuovo=n[:300],
        data_effetto=data_effetto or _tz.localdate(),
        note=note,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def dipendente_mansione_set(request, legacy_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare la mansione.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    mansione_nome = (request.POST.get("mansione_nome") or "").strip()[:200]

    # Recupera la riga esistente per non sovrascrivere gli altri campi
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]
    mansione_vecchia = (dip.get("mansione") or "").strip()

    try:
        upsert_anagrafica_dipendente(
            row_id=legacy_id,
            aliasusername=dip.get("aliasusername") or "",
            nome=dip.get("nome") or "",
            cognome=dip.get("cognome") or "",
            reparto=dip.get("reparto") or "",
            mansione=mansione_nome,
            ruolo=dip.get("ruolo") or "",
            matricola=dip.get("matricola") or "",
            email=dip.get("email") or "",
            email_notifica=dip.get("email_notifica") or "",
            attivo=bool(dip.get("attivo", True)),
        )
        _registra_cambiamento(
            legacy_id,
            DipendenteCambiamentoOrganizzativo.TIPO_MANSIONE,
            mansione_vecchia, mansione_nome,
            request.user,
        )
        messages.success(request, f'Mansione aggiornata a "{mansione_nome}".' if mansione_nome else "Mansione rimossa.")
    except Exception:
        logger.exception("Errore aggiornamento mansione dipendente %s", legacy_id)
        messages.error(request, "Errore durante l'aggiornamento della mansione.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_reparto_set(request, legacy_id: int):
    """Modifica il reparto di un dipendente con storicizzazione automatica."""
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare il reparto.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    reparto_nome = (request.POST.get("reparto") or "").strip()[:200]

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]
    reparto_vecchio = (dip.get("reparto") or "").strip()

    try:
        upsert_anagrafica_dipendente(
            row_id=legacy_id,
            aliasusername=dip.get("aliasusername") or "",
            nome=dip.get("nome") or "",
            cognome=dip.get("cognome") or "",
            reparto=reparto_nome,
            mansione=dip.get("mansione") or "",
            ruolo=dip.get("ruolo") or "",
            matricola=dip.get("matricola") or "",
            email=dip.get("email") or "",
            email_notifica=dip.get("email_notifica") or "",
            attivo=bool(dip.get("attivo", True)),
        )
        _registra_cambiamento(
            legacy_id,
            DipendenteCambiamentoOrganizzativo.TIPO_REPARTO,
            reparto_vecchio, reparto_nome,
            request.user,
        )
        messages.success(request, f'Reparto aggiornato a "{reparto_nome}".' if reparto_nome else "Reparto rimosso.")
    except Exception:
        logger.exception("Errore aggiornamento reparto dipendente %s", legacy_id)
        messages.error(request, "Errore durante l'aggiornamento del reparto.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Qualifiche dipendente — assegna/rimuovi
# ---------------------------------------------------------------------------

@login_required
@require_POST
def dipendente_qualifica_add(request, legacy_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per aggiungere qualifiche.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    tipo_id = int(request.POST.get("tipo_id") or 0)
    tipo = get_object_or_404(TipoQualifica, pk=tipo_id, is_active=True)

    data_cons_raw = (request.POST.get("data_conseguimento") or "").strip()
    data_scad_raw = (request.POST.get("data_scadenza") or "").strip()

    from datetime import date, timedelta
    data_conseguimento = None
    data_scadenza = None

    if data_cons_raw:
        try:
            data_conseguimento = date.fromisoformat(data_cons_raw)
        except ValueError:
            pass

    if data_scad_raw:
        try:
            data_scadenza = date.fromisoformat(data_scad_raw)
        except ValueError:
            pass
    elif tipo.durata_mesi > 0 and data_conseguimento:
        # Auto-calcola scadenza
        from dateutil.relativedelta import relativedelta
        try:
            data_scadenza = data_conseguimento + relativedelta(months=tipo.durata_mesi)
        except Exception:
            data_scadenza = data_conseguimento + timedelta(days=tipo.durata_mesi * 30)

    note = (request.POST.get("note") or "").strip()[:255]

    DipendenteQualifica.objects.create(
        legacy_anagrafica_id=legacy_id,
        tipo=tipo,
        data_conseguimento=data_conseguimento,
        data_scadenza=data_scadenza,
        note=note,
        assegnato_da=request.user,
    )
    messages.success(request, f'Qualifica "{tipo.nome}" aggiunta.')
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_qualifica_delete(request, legacy_id: int, q_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per rimuovere qualifiche.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    qualifica = get_object_or_404(DipendenteQualifica, pk=q_id, legacy_anagrafica_id=legacy_id)
    nome = qualifica.tipo.nome
    qualifica.delete()
    messages.success(request, f'Qualifica "{nome}" rimossa.')
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Anagrafica civile e aziendale — salvataggio
# ---------------------------------------------------------------------------

@login_required
@require_POST
def dipendente_anagrafica_civile_save(request, legacy_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare l'anagrafica civile.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    instance, _ = DipendenteAnagraficaCivile.objects.get_or_create(
        legacy_anagrafica_id=legacy_id
    )
    form = AnagraficaCivileForm(request.POST, request.FILES, instance=instance)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.legacy_anagrafica_id = legacy_id
        obj.updated_by = request.user
        obj.save()
        messages.success(request, "Anagrafica civile salvata.")
    else:
        for field, errs in form.errors.items():
            for err in errs:
                messages.error(request, f"{field}: {err}")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_anagrafica_aziendale_save(request, legacy_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare l'anagrafica aziendale.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    instance, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
        legacy_anagrafica_id=legacy_id
    )
    area_vecchia = instance.area or ""
    ruolo_az_vecchio = instance.ruolo_aziendale or ""

    form = AnagraficaAziendaleForm(request.POST, instance=instance)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.legacy_anagrafica_id = legacy_id
        obj.updated_by = request.user
        obj.save()
        _registra_cambiamento(
            legacy_id,
            DipendenteCambiamentoOrganizzativo.TIPO_AREA,
            area_vecchia, obj.area or "",
            request.user,
        )
        _registra_cambiamento(
            legacy_id,
            DipendenteCambiamentoOrganizzativo.TIPO_RUOLO_AZIENDALE,
            ruolo_az_vecchio, obj.ruolo_aziendale or "",
            request.user,
        )
        messages.success(request, "Anagrafica aziendale salvata.")
    else:
        for field, errs in form.errors.items():
            for err in errs:
                messages.error(request, f"{field}: {err}")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Voci retributive — importazione CSV dallo studio paghe
# ---------------------------------------------------------------------------

def _import_csv_retribuzioni(file_obj, user, file_nome: str = "") -> ImportazioneRetributiva:
    """Parsa il CSV paghe e crea ImportazioneRetributiva + VoceRetributiva."""
    raw = file_obj.read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Impossibile decodificare il file CSV (provati utf-8, latin-1, cp1252).")

    reader = csv.DictReader(StringIO(text), delimiter=";")
    rows = [r for r in reader if any(v.strip() for v in r.values())]
    if not rows:
        raise ValueError("Il file CSV è vuoto o non contiene righe valide.")

    # Data competenza dal primo record
    first_date_str = (rows[0].get("date") or "").strip()
    try:
        data_comp_raw = datetime.strptime(first_date_str, "%d/%m/%Y").date()
        data_competenza = data_comp_raw.replace(day=1)
    except ValueError:
        raise ValueError(f"Formato data non riconosciuto: '{first_date_str}' (atteso gg/mm/aaaa).")

    importazione = ImportazioneRetributiva.objects.create(
        data_competenza=data_competenza,
        importato_da=user,
        file_nome=file_nome,
        righe_totali=len(rows),
    )

    # Mappa codice fiscale → legacy_anagrafica_id
    all_cf = {(r.get("tax_code") or "").strip().upper() for r in rows if (r.get("tax_code") or "").strip()}
    cf_to_id: dict[str, int] = dict(
        DipendenteAnagraficaCivile.objects.filter(
            codice_fiscale__in=all_cf
        ).values_list("codice_fiscale", "legacy_anagrafica_id")
    )

    # Fallback nome "COGNOME NOME" → legacy_anagrafica_id quando il CF non è ancora in DipendenteAnagraficaCivile
    nome_to_id: dict[str, int] = {}
    try:
        _legacy_all = fetch_anagrafica_rows(deduplicate=True)
        for _lr in _legacy_all:
            _cog = str(_lr.get("cognome") or "").strip().upper()
            _nom = str(_lr.get("nome") or "").strip().upper()
            _full = f"{_cog} {_nom}".strip()
            _lid = int(_lr.get("id") or 0)
            if _full and _lid:
                nome_to_id[_full] = _lid
    except Exception:
        logger.warning("Fallback nome-based per retribuzioni non disponibile (legacy DB non raggiungibile)")

    # Voci dell'ultima importazione precedente per rilevare variazioni
    prev_import = (
        ImportazioneRetributiva.objects
        .filter(data_competenza__lt=data_competenza)
        .order_by("-data_competenza")
        .first()
    )
    prev_voci: dict[tuple, Decimal] = {}
    if prev_import:
        for voce in VoceRetributiva.objects.filter(importazione=prev_import):
            prev_voci[(voce.tax_code, voce.pay_item_key)] = voce.importo

    ok = err = 0
    voci_to_create: list[VoceRetributiva] = []
    for row in rows:
        try:
            tax_code = (row.get("tax_code") or "").strip().upper()
            pay_item = (row.get("pay_item") or "").strip()
            value_str = (row.get("value") or "0").strip().replace(",", ".")
            date_str = (row.get("date") or "").strip()
            if not tax_code or not pay_item:
                err += 1
                continue
            importo = Decimal(value_str)
            data_riga = datetime.strptime(date_str, "%d/%m/%Y").date()
            pay_item_key = pay_item.lower()
            categoria = _classify_pay_item(pay_item_key)
            legacy_id = cf_to_id.get(tax_code)
            if not legacy_id:
                nome_csv = (row.get("nome") or "").strip().upper()
                legacy_id = nome_to_id.get(nome_csv)
            prev_importo = prev_voci.get((tax_code, pay_item_key))
            is_changed = prev_importo is not None and prev_importo != importo
            voci_to_create.append(VoceRetributiva(
                importazione=importazione,
                tax_code=tax_code,
                legacy_anagrafica_id=legacy_id,
                data_competenza=data_riga,
                pay_item=pay_item,
                pay_item_key=pay_item_key,
                categoria=categoria,
                importo=importo,
                is_changed=is_changed,
                importo_precedente=prev_importo if is_changed else None,
            ))
            ok += 1
        except (InvalidOperation, ValueError):
            err += 1

    VoceRetributiva.objects.bulk_create(voci_to_create)
    importazione.righe_ok = ok
    importazione.righe_errore = err
    importazione.save(update_fields=["righe_ok", "righe_errore"])
    return importazione


@login_required
def retribuzioni_import(request):
    """Pagina importazione CSV retributivo (solo admin)."""
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    if not is_admin:
        messages.error(request, "Accesso riservato agli amministratori.")
        return redirect("anagrafica:dipendenti_list")

    if request.method == "POST":
        file_obj = request.FILES.get("file_csv")
        if not file_obj:
            messages.error(request, "Nessun file selezionato.")
        else:
            try:
                imp = _import_csv_retribuzioni(file_obj, request.user, file_obj.name)
                messages.success(
                    request,
                    f"Importazione completata: {imp.righe_ok} voci caricate"
                    f"{f', {imp.righe_errore} errori' if imp.righe_errore else ''}."
                )
                return redirect("anagrafica:retribuzioni_import")
            except Exception as exc:
                logger.exception("Errore importazione CSV retribuzioni")
                messages.error(request, f"Errore durante l'importazione: {exc}")

    importazioni = list(
        ImportazioneRetributiva.objects
        .filter(origine=ImportazioneRetributiva.ORIGINE_CSV)
        .select_related("importato_da")[:30]
    )
    return render(request, "anagrafica/pages/retribuzioni_import.html", {
        "importazioni": importazioni,
        "is_admin": is_admin,
    })


@login_required
def dipendente_retribuzioni(request, legacy_id: int):
    """Storico completo voci retributive per un dipendente (accesso HR)."""
    can_hr = _check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    civile_retr = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    _retr_q = Q(legacy_anagrafica_id=legacy_id)
    if civile_retr and civile_retr.codice_fiscale:
        _retr_q |= Q(tax_code=civile_retr.codice_fiscale.strip().upper())
    voci_all = list(
        VoceRetributiva.objects.filter(_retr_q)
        .select_related("importazione")
        .order_by("-data_competenza", "-importazione__data_importazione", "categoria", "pay_item_key")
    )

    # Merge: una sola importazione CSV per mese (la più recente) + voci manuali del mese
    # (le voci manuali fanno override delle voci CSV con lo stesso pay_item_key).
    _by_month: dict = {}
    for v in voci_all:
        key = v.data_competenza
        if key not in _by_month:
            _by_month[key] = {"csv_imp": None, "csv_voci": [], "manuale_voci": []}
        if v.manuale:
            _by_month[key]["manuale_voci"].append(v)
        else:
            if _by_month[key]["csv_imp"] is None:
                _by_month[key]["csv_imp"] = v.importazione
            if v.importazione_id == _by_month[key]["csv_imp"].id:
                _by_month[key]["csv_voci"].append(v)

    # Costruisco mese -> {pay_item_key: voce effettiva (manuale prevale su CSV)}
    _mesi_dict: dict = {}
    for _date, entry in _by_month.items():
        _manuale_keys = {v.pay_item_key for v in entry["manuale_voci"]}
        _voci = [v for v in entry["csv_voci"] if v.pay_item_key not in _manuale_keys] + entry["manuale_voci"]
        _mesi_dict[_date] = {v.pay_item_key: v for v in _voci}

    # Ordinamento colonne pivot: per categoria (fisso, variabile, altro, totale)
    # e all'interno per ordine di prima apparizione cronologica (rispecchia l'ordine CSV originale).
    _CAT_ORDER = {"fisso": 0, "variabile": 1, "altro": 2, "totale": 3}
    _TOTALI_SORT = {"retribuzione di fatto": 0, "totale elementi variabili": 1, "rml": 2, "ral": 3}
    _key_meta: dict = {}
    # Iterazione cronologica ascendente per registrare prima apparizione
    _voci_for_meta = sorted(voci_all, key=lambda v: (v.data_competenza, v.categoria, v.pay_item_key))
    _seq = 0
    for v in _voci_for_meta:
        if v.pay_item_key not in _key_meta:
            _key_meta[v.pay_item_key] = {
                "key": v.pay_item_key,
                "label": v.pay_item,
                "categoria": v.categoria,
                "_seq": _seq,
            }
            _seq += 1

    def _col_sort(m):
        cat = _CAT_ORDER.get(m["categoria"], 99)
        sub = _TOTALI_SORT.get(m["key"], 50) if m["categoria"] == "totale" else m["_seq"]
        return (cat, sub)

    colonne = sorted(_key_meta.values(), key=_col_sort)

    # Costruzione righe pivot: per ogni mese cronologico ASC calcolo le celle e il flag changed
    # (confronto con il mese precedente per cui esiste un valore nella stessa colonna).
    _mesi_asc = sorted(_mesi_dict.keys())
    _prev_value_by_key: dict = {}  # pay_item_key -> ultimo importo visto
    _rows_by_date: dict = {}
    for _date in _mesi_asc:
        voci_map = _mesi_dict[_date]
        celle = []
        for col in colonne:
            v = voci_map.get(col["key"])
            importo = v.importo if v else None
            prev = _prev_value_by_key.get(col["key"])
            # Cella variata se il valore differisce dal mese precedente
            # (None vs valore = variazione; entrambi None = invariato).
            changed = (importo != prev) and not (importo is None and prev is None)
            # Aggiorno il "valore precedente" solo se in questo mese c'è un valore
            if importo is not None:
                _prev_value_by_key[col["key"]] = importo
            celle.append({
                "voce": v,
                "importo": importo,
                "changed": changed,
                "manuale": bool(v and v.manuale),
                "categoria": col["categoria"],
                "is_totale": col["categoria"] == "totale",
                "is_ral": col["key"] == "ral",
            })
        _rows_by_date[_date] = {
            "data": _date,
            "celle": celle,
            "importazione": _by_month[_date]["csv_imp"],
            "n_manuale": len(_by_month[_date]["manuale_voci"]),
            "n_changed": sum(1 for c in celle if c["changed"] and c["importo"] is not None),
        }

    # Raggruppo per anno (anno decrescente, mesi decrescenti dentro l'anno)
    _today = date.today()
    _anni_default_aperti = {_today.year, _today.year - 1}
    _by_year: dict = {}
    for _date in _mesi_asc:
        _by_year.setdefault(_date.year, []).append(_rows_by_date[_date])

    anni = []
    for anno in sorted(_by_year.keys(), reverse=True):
        mesi_desc = list(reversed(_by_year[anno]))
        anni.append({
            "anno": anno,
            "mesi": mesi_desc,
            "n_mesi": len(mesi_desc),
            "n_changed": sum(m["n_changed"] for m in mesi_desc),
            "open": anno in _anni_default_aperti,
        })

    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)

    return render(request, "anagrafica/pages/dipendente_retribuzioni.html", {
        "dip": dip,
        "legacy_id": legacy_id,
        "colonne": colonne,
        "anni": anni,
        "n_mesi": len(_mesi_asc),
        "n_colonne": len(colonne),
        "can_hr": can_hr,
        "is_admin": is_admin,
        "tax_code_dipendente": civile_retr.codice_fiscale.strip().upper() if civile_retr and civile_retr.codice_fiscale else "",
        "categorie_voce": VoceRetributiva.CATEGORIA_CHOICES,
    })


@login_required
def dipendente_retribuzioni_export_xlsx(request, legacy_id: int):
    """Esporta in Excel lo storico retributivo del dipendente come tabella pivot
    (righe = mesi cronologici desc, colonne = pay_item per categoria, celle = importi
    con highlight delle variazioni vs mese precedente)."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    can_hr = _check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    civile = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    _q = Q(legacy_anagrafica_id=legacy_id)
    if civile and civile.codice_fiscale:
        _q |= Q(tax_code=civile.codice_fiscale.strip().upper())
    voci_all = list(
        VoceRetributiva.objects.filter(_q)
        .order_by("-data_competenza", "categoria", "pay_item_key")
    )

    # Merge manuali/CSV identico alla view principale
    _by_month: dict = {}
    for v in voci_all:
        key = v.data_competenza
        if key not in _by_month:
            _by_month[key] = {"csv_imp": None, "csv_voci": [], "manuale_voci": []}
        if v.manuale:
            _by_month[key]["manuale_voci"].append(v)
        else:
            if _by_month[key]["csv_imp"] is None:
                _by_month[key]["csv_imp"] = v.importazione
            if v.importazione_id == _by_month[key]["csv_imp"].id:
                _by_month[key]["csv_voci"].append(v)

    _mesi_dict: dict = {}
    for _date, entry in _by_month.items():
        _manuale_keys = {v.pay_item_key for v in entry["manuale_voci"]}
        _voci = [v for v in entry["csv_voci"] if v.pay_item_key not in _manuale_keys] + entry["manuale_voci"]
        _mesi_dict[_date] = {v.pay_item_key: v for v in _voci}

    _CAT_ORDER = {"fisso": 0, "variabile": 1, "altro": 2, "totale": 3}
    _TOTALI_SORT = {"retribuzione di fatto": 0, "totale elementi variabili": 1, "rml": 2, "ral": 3}
    _key_meta: dict = {}
    _seq = 0
    for v in sorted(voci_all, key=lambda v: (v.data_competenza, v.categoria, v.pay_item_key)):
        if v.pay_item_key not in _key_meta:
            _key_meta[v.pay_item_key] = {
                "key": v.pay_item_key, "label": v.pay_item,
                "categoria": v.categoria, "_seq": _seq,
            }
            _seq += 1

    def _col_sort(m):
        cat = _CAT_ORDER.get(m["categoria"], 99)
        sub = _TOTALI_SORT.get(m["key"], 50) if m["categoria"] == "totale" else m["_seq"]
        return (cat, sub)

    colonne = sorted(_key_meta.values(), key=_col_sort)
    _mesi_asc = sorted(_mesi_dict.keys())

    # Workbook + foglio
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Storico retributivo"

    # Stili
    thin = Side(border_style="thin", color="E2E8F0")
    border_all = Border(left=thin, right=thin, top=thin, bottom=thin)
    fill_by_cat = {
        "fisso":     PatternFill(fill_type="solid", fgColor="F1F5F9"),
        "variabile": PatternFill(fill_type="solid", fgColor="FFF7ED"),
        "altro":     PatternFill(fill_type="solid", fgColor="F5F3FF"),
        "totale":    PatternFill(fill_type="solid", fgColor="ECFDF5"),
    }
    font_header = Font(bold=True, name="Calibri", size=10, color="1E293B")
    font_date = Font(bold=True, name="Calibri", size=10)
    font_normal = Font(name="Calibri", size=10)
    font_totale = Font(bold=True, name="Calibri", size=10, color="065F46")
    fill_changed = PatternFill(fill_type="solid", fgColor="DBEAFE")
    fill_changed_totale = PatternFill(fill_type="solid", fgColor="BBF7D0")
    fill_manuale_marker = PatternFill(fill_type="solid", fgColor="EDE9FE")

    # Intestazione (riga 1)
    ws.cell(row=1, column=1, value="Data retribuzione").font = font_header
    ws.cell(row=1, column=1).fill = PatternFill(fill_type="solid", fgColor="F8FAFC")
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="left", vertical="center")
    ws.cell(row=1, column=1).border = border_all
    for ci, col in enumerate(colonne, start=2):
        c = ws.cell(row=1, column=ci, value=col["label"])
        c.font = font_header
        c.fill = fill_by_cat.get(col["categoria"], PatternFill(fill_type="solid", fgColor="F8FAFC"))
        c.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
        c.border = border_all

    # Righe: mesi in ordine cronologico discendente
    _prev_value_by_key: dict = {}
    # Per il calcolo "changed" itero ASC ma scrivo le righe DESC: costruisco prima la matrice
    _cell_data_by_date: dict = {}  # date -> list of (importo, changed, manuale)
    for _date in _mesi_asc:
        voci_map = _mesi_dict[_date]
        row_cells = []
        for col in colonne:
            v = voci_map.get(col["key"])
            importo = v.importo if v else None
            prev = _prev_value_by_key.get(col["key"])
            changed = (importo != prev) and not (importo is None and prev is None)
            if importo is not None:
                _prev_value_by_key[col["key"]] = importo
            row_cells.append((importo, changed, bool(v and v.manuale)))
        _cell_data_by_date[_date] = row_cells

    for ri, _date in enumerate(reversed(_mesi_asc), start=2):
        c_date = ws.cell(row=ri, column=1, value=_date)
        c_date.number_format = "DD/MM/YYYY"
        c_date.font = font_date
        c_date.alignment = Alignment(horizontal="left", vertical="center")
        c_date.border = border_all
        for ci, (col, (importo, changed, manuale)) in enumerate(zip(colonne, _cell_data_by_date[_date]), start=2):
            cell = ws.cell(row=ri, column=ci)
            if importo is not None:
                cell.value = float(importo)
                cell.number_format = '#,##0.00 "€"'
            cell.font = font_totale if col["categoria"] == "totale" else font_normal
            cell.alignment = Alignment(horizontal="right", vertical="center")
            cell.border = border_all
            if changed and importo is not None:
                cell.fill = fill_changed_totale if col["categoria"] == "totale" else fill_changed
            elif manuale:
                cell.fill = fill_manuale_marker

    # Freeze pane: prima riga + prima colonna
    ws.freeze_panes = "B2"

    # Auto-width approssimativo (label + padding)
    ws.column_dimensions["A"].width = 18
    for ci, col in enumerate(colonne, start=2):
        ws.column_dimensions[get_column_letter(ci)].width = max(14, min(28, len(col["label"]) + 4))

    _cognome = str(dip.get("cognome") or "").strip()
    _nome = str(dip.get("nome") or "").strip()

    # Riga riepilogo finale
    summary_row = len(_mesi_asc) + 3
    ws.cell(row=summary_row, column=1,
            value=f"Dipendente: {_cognome} {_nome} — {len(_mesi_asc)} mesi · {len(colonne)} voci").font = Font(italic=True, size=9, color="64748B")

    # Output
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    today = date.today().strftime("%Y%m%d")
    safe_name = "".join(ch for ch in f"{_cognome}_{_nome}" if ch.isalnum() or ch in ("_", "-")).strip("_") or str(legacy_id)
    filename = f"storico_retributivo_{safe_name}_{today}.xlsx"

    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


# ---------------------------------------------------------------------------
# Voci retributive — data-entry manuale (HR/admin)
# ---------------------------------------------------------------------------

def _get_or_create_import_manuale(data_competenza, user) -> ImportazioneRetributiva:
    """Recupera o crea l'unica `ImportazioneRetributiva` manuale per quel mese di competenza."""
    imp, created = ImportazioneRetributiva.objects.get_or_create(
        origine=ImportazioneRetributiva.ORIGINE_MANUALE,
        data_competenza=data_competenza,
        defaults={
            "importato_da": user,
            "file_nome": "(inserimento manuale)",
            "note": "Container voci retributive inserite manualmente",
        },
    )
    return imp


def _parse_data_competenza(raw: str):
    """Accetta 'YYYY-MM' o 'YYYY-MM-DD' e restituisce date(primo giorno mese)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 7:  # YYYY-MM
            return datetime.strptime(raw + "-01", "%Y-%m-%d").date()
        d = datetime.strptime(raw, "%Y-%m-%d").date()
        return d.replace(day=1)
    except ValueError:
        return None


def _parse_importo(raw: str):
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


@login_required
@require_POST
def dipendente_retribuzione_voce_add(request, legacy_id: int):
    """Aggiunge una voce retributiva manuale (HR + admin)."""
    can_hr = _check_hr_permission(request)
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    if not (can_hr or is_admin):
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    data_comp = _parse_data_competenza(request.POST.get("data_competenza"))
    if not data_comp:
        messages.error(request, "Mese di competenza non valido.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    pay_item = (request.POST.get("pay_item") or "").strip()[:150]
    importo = _parse_importo(request.POST.get("importo"))
    if not pay_item or importo is None:
        messages.error(request, "Voce e importo sono obbligatori.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    categoria_raw = (request.POST.get("categoria") or "").strip().lower()
    valid_cats = {c for c, _ in VoceRetributiva.CATEGORIA_CHOICES}
    categoria = categoria_raw if categoria_raw in valid_cats else _classify_pay_item(pay_item.lower())

    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    tax_code = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else ""

    imp = _get_or_create_import_manuale(data_comp, request.user)
    VoceRetributiva.objects.create(
        importazione=imp,
        tax_code=tax_code,
        legacy_anagrafica_id=legacy_id,
        data_competenza=data_comp,
        pay_item=pay_item,
        pay_item_key=pay_item.lower(),
        categoria=categoria,
        importo=importo,
        manuale=True,
        note=(request.POST.get("note") or "").strip()[:300],
        updated_by=request.user,
    )
    imp.righe_ok = imp.voci.count()
    imp.save(update_fields=["righe_ok"])

    messages.success(request, f'Voce "{pay_item}" aggiunta per {data_comp.strftime("%B %Y")}.')
    return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_retribuzione_voce_edit(request, legacy_id: int, voce_id: int):
    """Modifica una voce retributiva (solo voci con flag manuale=True)."""
    can_hr = _check_hr_permission(request)
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    if not (can_hr or is_admin):
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    voce = get_object_or_404(VoceRetributiva, pk=voce_id)
    if not voce.manuale:
        messages.error(request, "Solo le voci inserite manualmente sono modificabili. Le voci da CSV vanno reimportate.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    tc = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else ""
    if voce.legacy_anagrafica_id != legacy_id and (not tc or voce.tax_code != tc):
        messages.error(request, "Voce non appartenente a questo dipendente.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    pay_item = (request.POST.get("pay_item") or "").strip()[:150]
    importo = _parse_importo(request.POST.get("importo"))
    if not pay_item or importo is None:
        messages.error(request, "Voce e importo sono obbligatori.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    categoria_raw = (request.POST.get("categoria") or "").strip().lower()
    valid_cats = {c for c, _ in VoceRetributiva.CATEGORIA_CHOICES}
    categoria = categoria_raw if categoria_raw in valid_cats else _classify_pay_item(pay_item.lower())

    voce.pay_item = pay_item
    voce.pay_item_key = pay_item.lower()
    voce.importo = importo
    voce.categoria = categoria
    voce.note = (request.POST.get("note") or "").strip()[:300]
    voce.updated_by = request.user
    voce.save(update_fields=["pay_item", "pay_item_key", "importo", "categoria", "note", "updated_by", "updated_at"])

    messages.success(request, "Voce aggiornata.")
    return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_retribuzione_voce_delete(request, legacy_id: int, voce_id: int):
    """Elimina una voce retributiva (solo voci con flag manuale=True)."""
    can_hr = _check_hr_permission(request)
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    if not (can_hr or is_admin):
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    voce = get_object_or_404(VoceRetributiva, pk=voce_id)
    if not voce.manuale:
        messages.error(request, "Solo le voci inserite manualmente sono eliminabili.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    tc = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else ""
    if voce.legacy_anagrafica_id != legacy_id and (not tc or voce.tax_code != tc):
        messages.error(request, "Voce non appartenente a questo dipendente.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    imp = voce.importazione
    voce.delete()
    # Se l'importazione manuale è rimasta senza voci, eliminala
    if imp.origine == ImportazioneRetributiva.ORIGINE_MANUALE and not imp.voci.exists():
        imp.delete()
    else:
        imp.righe_ok = imp.voci.count()
        imp.save(update_fields=["righe_ok"])

    messages.success(request, "Voce eliminata.")
    return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Storico contrattuale — import CSV + CRUD manuale
# ---------------------------------------------------------------------------

_CONTRATTO_LABEL_MAP: dict[str, str] = {
    label.lower(): value
    for value, label in DipendenteAnagraficaAziendale.CONTRATTO_CHOICES
}
_CONTRATTO_LABEL_MAP.update({
    "indeterminato": DipendenteAnagraficaAziendale.CONTRATTO_INDETERMINATO,
    "determinato": DipendenteAnagraficaAziendale.CONTRATTO_DETERMINATO,
    "apprendistato": DipendenteAnagraficaAziendale.CONTRATTO_APPRENDISTATO,
    "somministrazione": DipendenteAnagraficaAziendale.CONTRATTO_SOMMINISTRAZIONE,
    "collaborazione": DipendenteAnagraficaAziendale.CONTRATTO_COLLABORAZIONE,
    "stage": DipendenteAnagraficaAziendale.CONTRATTO_STAGE,
    "tirocinio": DipendenteAnagraficaAziendale.CONTRATTO_STAGE,
    "altro": DipendenteAnagraficaAziendale.CONTRATTO_ALTRO,
})


def _normalize_contratto_choice(raw: str) -> str:
    key = raw.strip().lower()
    if key in _CONTRATTO_LABEL_MAP:
        return _CONTRATTO_LABEL_MAP[key]
    # partial match
    for k, v in _CONTRATTO_LABEL_MAP.items():
        if k in key or key in k:
            return v
    return ""


def _import_csv_contratti(file_obj, user) -> tuple[int, int, int]:
    """Parsa il CSV contrattuale e crea/aggiorna record StoricoContratto.

    Formato: Codice fiscale;Data Inizio;Data Fine;Tipo di contratto;Qualifica;Livello;CCNL;Descrizione livello
    Più righe con stesso (CF, Data Inizio, Data Fine) vengono aggregate automaticamente.
    Restituisce (created, updated, skipped).
    """
    raw = file_obj.read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Impossibile decodificare il file CSV (provati utf-8, latin-1, cp1252).")

    # Mappa CF → legacy_id
    cf_to_id: dict[str, int] = {}
    for row in DipendenteAnagraficaCivile.objects.filter(
        codice_fiscale__isnull=False, legacy_anagrafica_id__isnull=False
    ).exclude(codice_fiscale="").values("codice_fiscale", "legacy_anagrafica_id"):
        cf_to_id[str(row["codice_fiscale"]).strip().upper()] = row["legacy_anagrafica_id"]

    # Fallback nome-based
    nome_to_id: dict[str, int] = {}
    try:
        _legacy_all = fetch_anagrafica_rows(deduplicate=True)
        for _lr in _legacy_all:
            _cog = str(_lr.get("cognome") or "").strip().upper()
            _nom = str(_lr.get("nome") or "").strip().upper()
            _full = f"{_cog} {_nom}".strip()
            _lid = int(_lr.get("id") or 0)
            if _full and _lid:
                nome_to_id[_full] = _lid
    except Exception:
        logger.warning("Fallback nome-based per contratti non disponibile")

    # Raggruppa righe per (CF, data_inizio, data_fine)
    groups: dict[tuple, dict] = {}
    reader = csv.DictReader(StringIO(text), delimiter=";")
    for row in reader:
        cf = (row.get("Codice fiscale") or "").strip().upper()
        if not cf:
            continue
        di_raw = (row.get("Data Inizio") or "").strip()
        df_raw = (row.get("Data Fine") or "").strip()
        if not di_raw:
            continue
        try:
            di = datetime.strptime(di_raw, "%d/%m/%Y").date()
            df = datetime.strptime(df_raw, "%d/%m/%Y").date() if df_raw else None
        except ValueError:
            continue
        key = (cf, di, df)
        if key not in groups:
            groups[key] = {
                "tax_code": cf, "data_inizio": di, "data_fine": df,
                "tipologia_contratto": "", "qualifica_nome": "",
                "codice_livello": "", "ccnl": "", "descrizione_livello": "",
            }
        g = groups[key]
        tipo = (row.get("Tipo di contratto") or "").strip()
        qualifica = (row.get("Qualifica") or "").strip()
        livello = (row.get("Livello") or "").strip()
        ccnl = (row.get("CCNL") or "").strip()
        desc = (row.get("Descrizione livello") or "").strip()
        if tipo and not g["tipologia_contratto"]:
            g["tipologia_contratto"] = _normalize_contratto_choice(tipo)
        if qualifica and not g["qualifica_nome"]:
            g["qualifica_nome"] = qualifica
        if livello and not g["codice_livello"]:
            g["codice_livello"] = livello.upper()
        if ccnl and not g["ccnl"]:
            g["ccnl"] = ccnl
        if desc and not g["descrizione_livello"]:
            g["descrizione_livello"] = desc

    created_n = updated_n = 0
    for (cf, di, df), data in groups.items():
        lid = cf_to_id.get(cf) or nome_to_id.get(cf)
        defaults = {
            "tipologia_contratto": data["tipologia_contratto"],
            "qualifica_nome": data["qualifica_nome"],
            "codice_livello": data["codice_livello"],
            "ccnl": data["ccnl"],
            "descrizione_livello": data["descrizione_livello"],
            "legacy_anagrafica_id": lid,
            "importato_da": user,
        }
        _, created = StoricoContratto.objects.update_or_create(
            tax_code=cf, data_inizio=di, data_fine=df,
            defaults=defaults,
        )
        if created:
            created_n += 1
        else:
            updated_n += 1
    return created_n, updated_n, 0


@login_required
def contratti_import(request):
    """Pagina importazione CSV contratti (solo admin)."""
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    if not is_admin:
        messages.error(request, "Accesso riservato agli amministratori.")
        return redirect("anagrafica:dipendenti_list")

    stats = None
    if request.method == "POST":
        file_obj = request.FILES.get("file_csv")
        if not file_obj:
            messages.error(request, "Nessun file selezionato.")
        else:
            try:
                created, updated, _ = _import_csv_contratti(file_obj, request.user)
                messages.success(
                    request,
                    f"Importazione completata: {created} record creati, {updated} aggiornati.",
                )
                stats = {"created": created, "updated": updated}
                return redirect("anagrafica:contratti_import")
            except Exception as exc:
                logger.exception("Errore importazione CSV contratti")
                messages.error(request, f"Errore durante l'importazione: {exc}")

    recenti = list(
        StoricoContratto.objects.select_related("importato_da").order_by("-created_at")[:30]
    )
    return render(request, "anagrafica/pages/contratti_import.html", {
        "recenti": recenti,
        "is_admin": is_admin,
    })


@login_required
@require_POST
def dipendente_contratto_add(request, legacy_id: int):
    """Aggiunge manualmente un record storico contrattuale."""
    can_hr = _check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    di_raw = request.POST.get("data_inizio", "").strip()
    df_raw = request.POST.get("data_fine", "").strip()
    try:
        data_inizio = datetime.strptime(di_raw, "%Y-%m-%d").date()
        data_fine = datetime.strptime(df_raw, "%Y-%m-%d").date() if df_raw else None
    except ValueError:
        messages.error(request, "Formato data non valido.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    tax_code = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else ""

    # Auto-chiudi il record "in corso" se il nuovo inizia dopo
    _q_inc = Q(legacy_anagrafica_id=legacy_id)
    if tax_code:
        _q_inc |= Q(tax_code=tax_code)
    in_corso = (
        StoricoContratto.objects.filter(_q_inc, data_fine__isnull=True)
        .order_by("-data_inizio")
        .first()
    )
    if in_corso and in_corso.data_inizio < data_inizio:
        in_corso.data_fine = data_inizio
        in_corso.save(update_fields=["data_fine"])

    codice_liv = request.POST.get("codice_livello", "").strip().upper()
    # Auto-popola descrizione dal catalogo se non specificata manualmente
    desc_liv = request.POST.get("descrizione_livello", "").strip()
    if codice_liv and not desc_liv:
        _lc = LivelloContrattuale.objects.filter(codice=codice_liv).first()
        if _lc:
            desc_liv = _lc.descrizione

    StoricoContratto.objects.create(
        legacy_anagrafica_id=legacy_id,
        tax_code=tax_code,
        data_inizio=data_inizio,
        data_fine=data_fine,
        tipologia_contratto=request.POST.get("tipologia_contratto", "").strip(),
        codice_livello=codice_liv,
        descrizione_livello=desc_liv,
        qualifica_nome=request.POST.get("qualifica_nome", "").strip(),
        importato_da=request.user,
    )
    messages.success(request, "Record contrattuale aggiunto.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_contratto_delete(request, legacy_id: int, contratto_id: int):
    """Elimina un record storico contrattuale."""
    can_hr = _check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    contratto = get_object_or_404(StoricoContratto, pk=contratto_id)
    if contratto.legacy_anagrafica_id != legacy_id:
        civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
        tc = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else None
        if contratto.tax_code != tc:
            messages.error(request, "Record non appartenente a questo dipendente.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    contratto.delete()
    messages.success(request, "Record contrattuale eliminato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_contratto_edit(request, legacy_id: int, contratto_id: int):
    """Aggiorna un record storico contrattuale esistente."""
    can_hr = _check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    contratto = get_object_or_404(StoricoContratto, pk=contratto_id)
    if contratto.legacy_anagrafica_id != legacy_id:
        civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
        tc = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else None
        if contratto.tax_code != tc:
            messages.error(request, "Record non appartenente a questo dipendente.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    di_raw = request.POST.get("data_inizio", "").strip()
    df_raw = request.POST.get("data_fine", "").strip()
    try:
        data_inizio = datetime.strptime(di_raw, "%Y-%m-%d").date()
        data_fine = datetime.strptime(df_raw, "%Y-%m-%d").date() if df_raw else None
    except ValueError:
        messages.error(request, "Formato data non valido.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    codice_liv = request.POST.get("codice_livello", "").strip().upper()
    desc_liv = request.POST.get("descrizione_livello", "").strip()
    if codice_liv and not desc_liv:
        _lc = LivelloContrattuale.objects.filter(codice=codice_liv).first()
        if _lc:
            desc_liv = _lc.descrizione

    contratto.data_inizio = data_inizio
    contratto.data_fine = data_fine
    contratto.tipologia_contratto = request.POST.get("tipologia_contratto", "").strip()
    contratto.codice_livello = codice_liv
    contratto.descrizione_livello = desc_liv
    contratto.qualifica_nome = request.POST.get("qualifica_nome", "").strip()
    contratto.save()
    messages.success(request, "Record contrattuale aggiornato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Report dipendenti — filtri avanzati + export CSV
# ---------------------------------------------------------------------------

@login_required
def dipendenti_report(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    if not is_admin:
        messages.error(request, "Accesso riservato agli amministratori.")
        return redirect("anagrafica:dipendenti_list")

    q = request.GET.get("q", "").strip()
    reparto_filter = request.GET.get("reparto", "").strip()
    area_filter = request.GET.get("area", "").strip()
    contratto_filter = request.GET.get("tipologia_contratto", "").strip()
    consenso_filter = request.GET.get("consenso_privacy", "").strip()
    cat_protetta_filter = request.GET.get("categoria_protetta", "").strip()

    # Parte da tutti i dipendenti legacy
    all_rows = fetch_anagrafica_rows(deduplicate=True)

    # Filtro per testo su nome/cognome
    if q:
        q_norm = q.casefold()
        all_rows = [
            row for row in all_rows
            if any(
                q_norm in str(row.get(k) or "").casefold()
                for k in ("nome", "cognome", "aliasusername", "matricola")
            )
        ]

    # Filtro per reparto (da legacy)
    if reparto_filter:
        all_rows = [
            row for row in all_rows
            if str(row.get("reparto") or "").strip().casefold() == reparto_filter.casefold()
        ]

    # Filtri su campi Django: area e tipologia_contratto
    django_filter_ids: set[int] | None = None
    az_qs = DipendenteAnagraficaAziendale.objects.all()
    if area_filter:
        az_qs = az_qs.filter(area__iexact=area_filter)
    if contratto_filter:
        az_qs = az_qs.filter(tipologia_contratto=contratto_filter)
    if consenso_filter == "si":
        az_qs = az_qs.filter(consenso_privacy=True)
    elif consenso_filter == "no":
        az_qs = az_qs.filter(consenso_privacy=False)
    if area_filter or contratto_filter or consenso_filter:
        django_filter_ids = set(az_qs.values_list("legacy_anagrafica_id", flat=True))

    # Filtro categoria protetta (da DipendenteAnagraficaCivile)
    civ_filter_ids: set[int] | None = None
    if cat_protetta_filter == "si":
        civ_filter_ids = set(
            DipendenteAnagraficaCivile.objects.filter(categoria_protetta=True)
            .values_list("legacy_anagrafica_id", flat=True)
        )
    elif cat_protetta_filter == "no":
        civ_filter_ids = set(
            DipendenteAnagraficaCivile.objects.filter(categoria_protetta=False)
            .values_list("legacy_anagrafica_id", flat=True)
        )

    if django_filter_ids is not None:
        all_rows = [row for row in all_rows if int(row.get("id") or 0) in django_filter_ids]
    if civ_filter_ids is not None:
        all_rows = [row for row in all_rows if int(row.get("id") or 0) in civ_filter_ids]

    # Arricchisce ogni riga con dati Django
    legacy_ids = [int(row.get("id") or 0) for row in all_rows if int(row.get("id") or 0)]
    az_map = {
        obj.legacy_anagrafica_id: obj
        for obj in DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=legacy_ids)
    }
    for row in all_rows:
        lid = int(row.get("id") or 0)
        az = az_map.get(lid)
        row["_az"] = az

    # Export CSV (no campi sensibili)
    fmt = request.GET.get("format", "").strip()
    if fmt == "csv":
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = 'attachment; filename="dipendenti_report.csv"'
        writer = csv.writer(response, delimiter=";")
        writer.writerow([
            "ID", "Cognome", "Nome", "Matricola", "Reparto",
            "Area", "Ruolo aziendale", "Tipologia contratto",
            "Livello inquadramento", "Data prima assunzione",
            "Consenso privacy", "Email aziendale", "Telefono aziendale",
        ])
        for row in all_rows:
            az = row.get("_az")
            writer.writerow([
                row.get("id", ""),
                row.get("cognome", ""),
                row.get("nome", ""),
                row.get("matricola", ""),
                row.get("reparto", ""),
                getattr(az, "area", "") or "",
                getattr(az, "ruolo_aziendale", "") or "",
                getattr(az, "get_tipologia_contratto_display", lambda: "")() if az else "",
                getattr(az, "livello_inquadramento", "") or "",
                getattr(az, "data_prima_assunzione", "") or "",
                "Sì" if getattr(az, "consenso_privacy", False) else "No",
                getattr(az, "email_aziendale", "") or "",
                getattr(az, "telefono_aziendale", "") or "",
            ])
        return response

    reparti_list = sorted({str(r.get("reparto") or "").strip() for r in fetch_anagrafica_rows(deduplicate=True) if str(r.get("reparto") or "").strip()})
    aree_list = sorted(
        DipendenteAnagraficaAziendale.objects.exclude(area="")
        .values_list("area", flat=True)
        .distinct()
        .order_by("area")
    )

    paginator = Paginator(all_rows, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "anagrafica/pages/dipendenti_report.html", {
        "page_obj": page,
        "q": q,
        "reparto": reparto_filter,
        "area": area_filter,
        "tipologia_contratto": contratto_filter,
        "consenso_privacy": consenso_filter,
        "categoria_protetta": cat_protetta_filter,
        "reparti": reparti_list,
        "aree": aree_list,
        "contratto_choices": DipendenteAnagraficaAziendale.CONTRATTO_CHOICES,
        "n_totale": len(all_rows),
    })


# ---------------------------------------------------------------------------
# Mansioni — gestione catalogo
# ---------------------------------------------------------------------------

@login_required
def mansioni_list(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)

    mansioni = list(Mansione.objects.all().order_by("nome"))

    # Conta dipendenti per mansione dal DB legacy
    mansione_counts: dict[str, int] = {}
    try:
        from django.db import connections
        conn_name = "legacy" if "legacy" in connections else "default"
        with connections[conn_name].cursor() as cur:
            cur.execute(
                "SELECT LOWER(mansione), COUNT(*) FROM anagrafica_dipendenti "
                "WHERE mansione IS NOT NULL AND mansione != '' GROUP BY LOWER(mansione)"
            )
            for row in cur.fetchall():
                mansione_counts[row[0]] = row[1]
    except Exception:
        pass

    for m in mansioni:
        m.n_dipendenti = mansione_counts.get(m.nome.lower(), 0)

    # Raggruppa per categoria nell'ordine definito
    cat_order = [c for c, _ in Mansione.CATEGORIA_CHOICES]
    cat_labels = dict(Mansione.CATEGORIA_CHOICES)
    # Le mansioni senza categoria vanno in "Altro"
    grouped: list[tuple[str, str, list]] = []
    seen_cats: set[str] = set()
    for cat_code in cat_order:
        items = [m for m in mansioni if (m.categoria or Mansione.CAT_ALTRO) == cat_code]
        if items:
            grouped.append((cat_code, cat_labels[cat_code], items))
            seen_cats.add(cat_code)
    # Mansioni senza categoria classificate come "Altro"
    senza_cat = [m for m in mansioni if not m.categoria and Mansione.CAT_ALTRO not in seen_cats]
    if senza_cat:
        altro_label = cat_labels.get(Mansione.CAT_ALTRO, "Altro")
        grouped.append((Mansione.CAT_ALTRO, altro_label, senza_cat))

    mansioni_suggerite = [
        "Operaio generico", "Operaio specializzato", "Operaio qualificato",
        "Impiegato", "Impiegato tecnico", "Impiegato amministrativo",
        "Quadro", "Dirigente",
    ]

    return render(request, "anagrafica/pages/mansioni_list.html", {
        "mansioni": mansioni,
        "mansioni_grouped": grouped,
        "is_admin": is_admin,
        "mansioni_suggerite": mansioni_suggerite,
        "CATEGORIA_CHOICES": Mansione.CATEGORIA_CHOICES,
    })


@login_required
@require_POST
def mansione_create(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per creare mansioni.")
        return _back_to_caller(request, "anagrafica:mansioni_list")

    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome della mansione è obbligatorio.")
        return _back_to_caller(request, "anagrafica:mansioni_list")

    _, created = Mansione.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "categoria": (request.POST.get("categoria") or "").strip()[:20],
            "descrizione": (request.POST.get("descrizione") or "").strip(),
            "colore": (request.POST.get("colore") or "#64748b").strip()[:7],
        },
    )
    if created:
        messages.success(request, f'Mansione "{nome}" creata.')
    else:
        messages.warning(request, f'Esiste già una mansione con il nome "{nome}".')
    return _back_to_caller(request, "anagrafica:mansioni_list")


@login_required
@require_POST
def mansione_edit(request, mansione_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare mansioni.")
        return _back_to_caller(request, "anagrafica:mansioni_list")

    mansione = get_object_or_404(Mansione, pk=mansione_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome della mansione è obbligatorio.")
        return _back_to_caller(request, "anagrafica:mansioni_list")

    mansione.nome = nome
    mansione.categoria = (request.POST.get("categoria") or "").strip()[:20]
    mansione.descrizione = (request.POST.get("descrizione") or "").strip()
    mansione.colore = (request.POST.get("colore") or "#64748b").strip()[:7]
    mansione.is_active = request.POST.get("is_active") == "1"
    mansione.save()
    messages.success(request, f'Mansione "{mansione.nome}" aggiornata.')
    return _back_to_caller(request, "anagrafica:mansioni_list")


@login_required
@require_POST
def mansione_delete(request, mansione_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare mansioni.")
        return _back_to_caller(request, "anagrafica:mansioni_list")

    mansione = get_object_or_404(Mansione, pk=mansione_id)
    nome = mansione.nome
    mansione.delete()
    messages.success(request, f'Mansione "{nome}" eliminata.')
    return _back_to_caller(request, "anagrafica:mansioni_list")


# ---------------------------------------------------------------------------
# Aree aziendali — catalogo dropdown
# ---------------------------------------------------------------------------

@login_required
def aree_list(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    aree = list(AreaAziendale.objects.all().order_by("nome"))
    return render(request, "anagrafica/pages/aree_list.html", {
        "aree": aree,
        "is_admin": is_admin,
    })


@login_required
@require_POST
def area_create(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per creare aree.")
        return _back_to_caller(request, "anagrafica:aree_list")
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome dell'area è obbligatorio.")
        return _back_to_caller(request, "anagrafica:aree_list")
    _, created = AreaAziendale.objects.get_or_create(
        nome__iexact=nome,
        defaults={"nome": nome, "descrizione": (request.POST.get("descrizione") or "").strip()},
    )
    if created:
        messages.success(request, f'Area "{nome}" creata.')
    else:
        messages.warning(request, f'Esiste già un\'area con il nome "{nome}".')
    return _back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_edit(request, area_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare aree.")
        return _back_to_caller(request, "anagrafica:aree_list")
    area = get_object_or_404(AreaAziendale, pk=area_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome dell'area è obbligatorio.")
        return _back_to_caller(request, "anagrafica:aree_list")
    area.nome = nome
    area.descrizione = (request.POST.get("descrizione") or "").strip()
    area.is_active = request.POST.get("is_active") == "1"
    area.save()
    messages.success(request, f'Area "{area.nome}" aggiornata.')
    return _back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_delete(request, area_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare aree.")
        return _back_to_caller(request, "anagrafica:aree_list")
    area = get_object_or_404(AreaAziendale, pk=area_id)
    nome = area.nome
    area.delete()
    messages.success(request, f'Area "{nome}" eliminata.')
    return _back_to_caller(request, "anagrafica:aree_list")


# ---------------------------------------------------------------------------
# Ruoli aziendali — catalogo dropdown
# ---------------------------------------------------------------------------

@login_required
def ruoli_aziendali_list(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    ruoli = list(RuoloAziendale.objects.all().order_by("nome"))
    return render(request, "anagrafica/pages/ruoli_aziendali_list.html", {
        "ruoli": ruoli,
        "is_admin": is_admin,
    })


@login_required
@require_POST
def ruolo_aziendale_create(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per creare ruoli aziendali.")
        return _back_to_caller(request, "anagrafica:ruoli_aziendali_list")
    nome = (request.POST.get("nome") or "").strip()[:200]
    if not nome:
        messages.error(request, "Il nome del ruolo è obbligatorio.")
        return _back_to_caller(request, "anagrafica:ruoli_aziendali_list")
    _, created = RuoloAziendale.objects.get_or_create(
        nome__iexact=nome,
        defaults={"nome": nome, "descrizione": (request.POST.get("descrizione") or "").strip()},
    )
    if created:
        messages.success(request, f'Ruolo aziendale "{nome}" creato.')
    else:
        messages.warning(request, f'Esiste già un ruolo aziendale con il nome "{nome}".')
    return _back_to_caller(request, "anagrafica:ruoli_aziendali_list")


@login_required
@require_POST
def ruolo_aziendale_edit(request, ruolo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare ruoli aziendali.")
        return _back_to_caller(request, "anagrafica:ruoli_aziendali_list")
    ruolo = get_object_or_404(RuoloAziendale, pk=ruolo_id)
    nome = (request.POST.get("nome") or "").strip()[:200]
    if not nome:
        messages.error(request, "Il nome del ruolo è obbligatorio.")
        return _back_to_caller(request, "anagrafica:ruoli_aziendali_list")
    ruolo.nome = nome
    ruolo.descrizione = (request.POST.get("descrizione") or "").strip()
    ruolo.is_active = request.POST.get("is_active") == "1"
    ruolo.save()
    messages.success(request, f'Ruolo aziendale "{ruolo.nome}" aggiornato.')
    return _back_to_caller(request, "anagrafica:ruoli_aziendali_list")


@login_required
@require_POST
def ruolo_aziendale_delete(request, ruolo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare ruoli aziendali.")
        return _back_to_caller(request, "anagrafica:ruoli_aziendali_list")
    ruolo = get_object_or_404(RuoloAziendale, pk=ruolo_id)
    nome = ruolo.nome
    ruolo.delete()
    messages.success(request, f'Ruolo aziendale "{nome}" eliminato.')
    return _back_to_caller(request, "anagrafica:ruoli_aziendali_list")


# ---------------------------------------------------------------------------
# Qualifiche — gestione catalogo + panoramica scadenze
# ---------------------------------------------------------------------------

@login_required
def qualifiche_list(request):
    from datetime import timedelta
    from django.utils import timezone as tz

    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)

    tipi = list(
        TipoQualifica.objects.annotate(n_assegnazioni=Count("assegnazioni")).order_by("categoria", "nome")
    )

    oggi = tz.localdate()
    soglia = oggi + timedelta(days=60)

    # Qualifiche in scadenza o scadute
    scadenze_qs = list(
        DipendenteQualifica.objects.filter(data_scadenza__isnull=False)
        .filter(data_scadenza__lte=soglia)
        .select_related("tipo")
        .order_by("data_scadenza")
    )

    # Arricchisce con nome dipendente
    legacy_ids = list({q.legacy_anagrafica_id for q in scadenze_qs})
    nome_map: dict[int, str] = {}
    if legacy_ids:
        try:
            rows = fetch_anagrafica_rows(ids=legacy_ids)
            for r in rows:
                rid = int(r.get("id") or 0)
                if rid:
                    nome_map[rid] = f"{r.get('cognome', '')} {r.get('nome', '')}".strip()
        except Exception:
            pass

    scadenze = []
    for q in scadenze_qs:
        scadenze.append({
            "id": q.id,
            "legacy_anagrafica_id": q.legacy_anagrafica_id,
            "dipendente": nome_map.get(q.legacy_anagrafica_id, f"Dip. #{q.legacy_anagrafica_id}"),
            "tipo_nome": q.tipo.nome,
            "tipo_categoria": q.tipo.categoria,
            "data_conseguimento": q.data_conseguimento,
            "data_scadenza": q.data_scadenza,
            "scaduta": q.data_scadenza < oggi,
            "in_scadenza": oggi <= q.data_scadenza <= soglia,
            "note": q.note,
        })

    tipi_suggeriti = [
        ("Patentino carrellista", "PROFESSIONALE", 60),
        ("Primo soccorso", "SICUREZZA", 36),
        ("Addetto antincendio (livello 1)", "SICUREZZA", 60),
        ("Addetto antincendio (livello 2)", "SICUREZZA", 60),
        ("Addetto antincendio (livello 3)", "SICUREZZA", 60),
        ("RSPP", "SICUREZZA", 60),
        ("RLS", "SICUREZZA", 60),
        ("Preposto sicurezza", "SICUREZZA", 60),
        ("Uso DPI anticaduta", "SICUREZZA", 60),
    ]

    # Raggruppa tipi per categoria
    cat_order_q = [c for c, _ in TipoQualifica.CATEGORIA_CHOICES]
    cat_labels_q = dict(TipoQualifica.CATEGORIA_CHOICES)
    tipi_grouped: list[tuple[str, str, list]] = []
    for cat_code in cat_order_q:
        items = [t for t in tipi if t.categoria == cat_code]
        if items:
            tipi_grouped.append((cat_code, cat_labels_q[cat_code], items))

    return render(request, "anagrafica/pages/qualifiche_list.html", {
        "tipi": tipi,
        "tipi_grouped": tipi_grouped,
        "scadenze": scadenze,
        "is_admin": is_admin,
        "oggi": oggi,
        "CATEGORIA_CHOICES": TipoQualifica.CATEGORIA_CHOICES,
        "tipi_suggeriti": tipi_suggeriti,
    })


@login_required
@require_POST
def tipo_qualifica_create(request):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per creare tipi di qualifica.")
        return _back_to_caller(request, "anagrafica:qualifiche_list")

    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della qualifica è obbligatorio.")
        return _back_to_caller(request, "anagrafica:qualifiche_list")

    durata_raw = request.POST.get("durata_mesi") or "0"
    try:
        durata_mesi = max(0, int(durata_raw))
    except ValueError:
        durata_mesi = 0

    _, created = TipoQualifica.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "categoria": (request.POST.get("categoria") or TipoQualifica.CAT_ALTRO).strip()[:20],
            "durata_mesi": durata_mesi,
            "descrizione": (request.POST.get("descrizione") or "").strip(),
        },
    )
    if created:
        messages.success(request, f'Tipo qualifica "{nome}" creato.')
    else:
        messages.warning(request, f'Esiste già un tipo qualifica con il nome "{nome}".')
    return _back_to_caller(request, "anagrafica:qualifiche_list")


@login_required
@require_POST
def tipo_qualifica_edit(request, tipo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare tipi di qualifica.")
        return _back_to_caller(request, "anagrafica:qualifiche_list")

    tipo = get_object_or_404(TipoQualifica, pk=tipo_id)
    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della qualifica è obbligatorio.")
        return _back_to_caller(request, "anagrafica:qualifiche_list")

    durata_raw = request.POST.get("durata_mesi") or "0"
    try:
        durata_mesi = max(0, int(durata_raw))
    except ValueError:
        durata_mesi = 0

    tipo.nome = nome
    tipo.categoria = (request.POST.get("categoria") or TipoQualifica.CAT_ALTRO).strip()[:20]
    tipo.durata_mesi = durata_mesi
    tipo.descrizione = (request.POST.get("descrizione") or "").strip()
    tipo.is_active = request.POST.get("is_active") == "1"
    tipo.save()
    messages.success(request, f'Tipo qualifica "{tipo.nome}" aggiornato.')
    return _back_to_caller(request, "anagrafica:qualifiche_list")


@login_required
@require_POST
def tipo_qualifica_delete(request, tipo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare tipi di qualifica.")
        return _back_to_caller(request, "anagrafica:qualifiche_list")

    tipo = get_object_or_404(TipoQualifica, pk=tipo_id)
    if tipo.assegnazioni.exists():
        messages.error(request, f'"{tipo.nome}" ha assegnazioni attive — non eliminabile.')
        return _back_to_caller(request, "anagrafica:qualifiche_list")

    nome = tipo.nome
    tipo.delete()
    messages.success(request, f'Tipo qualifica "{nome}" eliminato.')
    return _back_to_caller(request, "anagrafica:qualifiche_list")


# ---------------------------------------------------------------------------
# Helper: redirect verso il pannello impostazioni con tab attivo
# ---------------------------------------------------------------------------

def _redirect_impostazioni(tab: str | None = None):
    url = reverse("anagrafica:impostazioni")
    if tab:
        url = f"{url}?tab={tab}#tab-{tab}"
    return HttpResponseRedirect(url)


def _back_to_caller(request, fallback_view_name: str):
    """
    Redirect intelligente per le view CRUD dei cataloghi: se il form proviene dal
    pannello impostazioni (campo nascosto `next_tab`) torna lì, altrimenti
    redirige alla pagina di lista standalone.
    """
    next_tab = (request.POST.get("next_tab") or "").strip()
    if next_tab:
        return _redirect_impostazioni(next_tab)
    return redirect(fallback_view_name)


def _impostazioni_admin_check(request, tab: str | None = None):
    """Restituisce (is_admin, redirect_response_or_None)."""
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    if not is_admin:
        messages.error(request, "Permessi insufficienti.")
        return False, _redirect_impostazioni(tab)
    return True, None


# ---------------------------------------------------------------------------
# Livelli contrattuali — catalogo (CRUD)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def livello_contrattuale_create(request):
    ok, resp = _impostazioni_admin_check(request, "livelli")
    if not ok:
        return resp

    codice = (request.POST.get("codice") or "").strip().upper()[:10]
    if not codice:
        messages.error(request, "Il codice del livello è obbligatorio.")
        return _redirect_impostazioni("livelli")

    descrizione = (request.POST.get("descrizione") or "").strip()[:200]
    try:
        ordine = max(0, int(request.POST.get("ordine") or "0"))
    except ValueError:
        ordine = 0

    _, created = LivelloContrattuale.objects.get_or_create(
        codice=codice,
        defaults={"descrizione": descrizione, "ordine": ordine},
    )
    if created:
        messages.success(request, f'Livello "{codice}" creato.')
    else:
        messages.warning(request, f'Esiste già un livello con codice "{codice}".')
    return _redirect_impostazioni("livelli")


@login_required
@require_POST
def livello_contrattuale_edit(request, livello_id: int):
    ok, resp = _impostazioni_admin_check(request, "livelli")
    if not ok:
        return resp

    livello = get_object_or_404(LivelloContrattuale, pk=livello_id)
    codice = (request.POST.get("codice") or "").strip().upper()[:10]
    if not codice:
        messages.error(request, "Il codice del livello è obbligatorio.")
        return _redirect_impostazioni("livelli")

    try:
        ordine = max(0, int(request.POST.get("ordine") or "0"))
    except ValueError:
        ordine = 0

    livello.codice = codice
    livello.descrizione = (request.POST.get("descrizione") or "").strip()[:200]
    livello.ordine = ordine
    livello.is_active = request.POST.get("is_active") == "1"
    livello.save()
    messages.success(request, f'Livello "{livello.codice}" aggiornato.')
    return _redirect_impostazioni("livelli")


@login_required
@require_POST
def livello_contrattuale_delete(request, livello_id: int):
    ok, resp = _impostazioni_admin_check(request, "livelli")
    if not ok:
        return resp

    livello = get_object_or_404(LivelloContrattuale, pk=livello_id)
    codice = livello.codice
    # Controllo se esistono StoricoContratto con questo codice
    if StoricoContratto.objects.filter(codice_livello=codice).exists():
        messages.error(
            request,
            f'"{codice}" è referenziato nello storico contrattuale — non eliminabile. Disattivalo.',
        )
        return _redirect_impostazioni("livelli")

    livello.delete()
    messages.success(request, f'Livello "{codice}" eliminato.')
    return _redirect_impostazioni("livelli")


# ---------------------------------------------------------------------------
# Tipologie contratto — catalogo (CRUD)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def tipologia_contratto_create(request):
    ok, resp = _impostazioni_admin_check(request, "tipologie")
    if not ok:
        return resp

    codice = (request.POST.get("codice") or "").strip().upper()[:20]
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not codice or not nome:
        messages.error(request, "Codice e nome della tipologia sono obbligatori.")
        return _redirect_impostazioni("tipologie")

    try:
        ordine = max(0, int(request.POST.get("ordine") or "0"))
    except ValueError:
        ordine = 0

    _, created = TipologiaContratto.objects.get_or_create(
        codice=codice,
        defaults={"nome": nome, "ordine": ordine},
    )
    if created:
        messages.success(request, f'Tipologia "{codice}" creata.')
    else:
        messages.warning(request, f'Esiste già una tipologia con codice "{codice}".')
    return _redirect_impostazioni("tipologie")


@login_required
@require_POST
def tipologia_contratto_edit(request, tipologia_id: int):
    ok, resp = _impostazioni_admin_check(request, "tipologie")
    if not ok:
        return resp

    tipologia = get_object_or_404(TipologiaContratto, pk=tipologia_id)
    codice = (request.POST.get("codice") or "").strip().upper()[:20]
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not codice or not nome:
        messages.error(request, "Codice e nome della tipologia sono obbligatori.")
        return _redirect_impostazioni("tipologie")

    try:
        ordine = max(0, int(request.POST.get("ordine") or "0"))
    except ValueError:
        ordine = 0

    tipologia.codice = codice
    tipologia.nome = nome
    tipologia.ordine = ordine
    tipologia.is_active = request.POST.get("is_active") == "1"
    tipologia.save()
    messages.success(request, f'Tipologia "{tipologia.codice}" aggiornata.')
    return _redirect_impostazioni("tipologie")


@login_required
@require_POST
def tipologia_contratto_delete(request, tipologia_id: int):
    ok, resp = _impostazioni_admin_check(request, "tipologie")
    if not ok:
        return resp

    tipologia = get_object_or_404(TipologiaContratto, pk=tipologia_id)
    codice = tipologia.codice
    if StoricoContratto.objects.filter(tipologia_contratto=codice).exists():
        messages.error(
            request,
            f'"{codice}" è referenziata nello storico contrattuale — non eliminabile. Disattivala.',
        )
        return _redirect_impostazioni("tipologie")

    tipologia.delete()
    messages.success(request, f'Tipologia "{codice}" eliminata.')
    return _redirect_impostazioni("tipologie")


# ---------------------------------------------------------------------------
# Pannello impostazioni anagrafica — vista aggregata con tabs
# ---------------------------------------------------------------------------
# Ratei ferie/ROL/ex-festività — vista aggregata con filtro mese + dipendente
# ---------------------------------------------------------------------------

@login_required
def ratei_list(request):
    """Lista aggregata saldi cedolini con filtro per periodo e dipendente (solo HR)."""
    from core.legacy_models import UtenteLegacy
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    can_hr = _check_hr_permission(request)

    if not can_hr:
        messages.error(request, "Accesso non autorizzato ai dati HR.")
        return redirect("anagrafica:index")

    # Periodi disponibili
    periodi_qs = (
        SaldoCedolino.objects.values("data_competenza")
        .distinct()
        .order_by("-data_competenza")
    )
    periodi = [p["data_competenza"] for p in periodi_qs]

    # Build opzioni multi-select dipendente: tax_code → "Cognome Nome"
    all_cf_legacy = list(
        SaldoCedolino.objects.values("tax_code", "legacy_anagrafica_id")
        .distinct()
        .order_by("tax_code")
    )
    legacy_ids = [s["legacy_anagrafica_id"] for s in all_cf_legacy if s["legacy_anagrafica_id"]]
    dip_qs = list(AnagraficaDipendente.objects.filter(id__in=legacy_ids).values("id", "cognome", "nome", "reparto"))
    id_to_nome: dict = {
        d["id"]: f'{(d["cognome"] or "").strip()} {(d["nome"] or "").strip()}'.strip()
        for d in dip_qs
    }
    id_to_reparto: dict = {d["id"]: (d["reparto"] or "").strip() for d in dip_qs}

    seen_cf: set = set()
    dipendenti_options: list = []
    for row in all_cf_legacy:
        cf = row["tax_code"]
        if cf in seen_cf:
            continue
        seen_cf.add(cf)
        lid = row["legacy_anagrafica_id"]
        nome = id_to_nome.get(lid) if lid else None
        reparto = id_to_reparto.get(lid, "") if lid else ""
        dipendenti_options.append({"cf": cf, "nome": nome or cf, "reparto": reparto})
    dipendenti_options.sort(key=lambda x: x["nome"])
    cf_to_nome: dict = {d["cf"]: d["nome"] for d in dipendenti_options}

    reparti_options: list = sorted({d["reparto"] for d in dipendenti_options if d["reparto"]})

    # Filtri GET — backward compat: ?cf=CF_CODE (link da dipendente_detail legacy)
    filtro_periodo = request.GET.get("periodo", "")
    filtro_dipendenti: list = request.GET.getlist("dipendente")
    if not filtro_dipendenti:
        cf_compat = request.GET.get("cf", "").strip().upper()
        if cf_compat:
            filtro_dipendenti = [cf_compat]
    filtro_reparti: list = request.GET.getlist("reparto")

    qs = SaldoCedolino.objects.all().order_by("-data_competenza", "tax_code")

    if filtro_periodo:
        try:
            from datetime import date as _date
            anno, mese, giorno = filtro_periodo.split("-")
            qs = qs.filter(data_competenza=_date(int(anno), int(mese), int(giorno)))
        except (ValueError, AttributeError):
            pass

    if filtro_reparti:
        ids_in_reparto = [lid for lid, rep in id_to_reparto.items() if rep in filtro_reparti]
        qs = qs.filter(legacy_anagrafica_id__in=ids_in_reparto)

    if filtro_dipendenti:
        qs = qs.filter(tax_code__in=filtro_dipendenti)

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    for s in page_obj.object_list:
        s.nome_display = cf_to_nome.get(s.tax_code.upper(), s.tax_code)

    return render(request, "anagrafica/pages/ratei_list.html", {
        "page_obj": page_obj,
        "periodi": periodi,
        "filtro_periodo": filtro_periodo,
        "filtro_dipendenti": filtro_dipendenti,
        "filtro_reparti": filtro_reparti,
        "dipendenti_options": dipendenti_options,
        "reparti_options": reparti_options,
        "can_hr": can_hr,
        "is_admin": is_admin,
        "totale": qs.count(),
    })


# ---------------------------------------------------------------------------
# Ratei ferie — export XLSX (stessa logica filtri di ratei_list)
# ---------------------------------------------------------------------------

@login_required
def ratei_export(request):
    """Scarica XLSX dei saldi cedolini con i filtri correnti (solo HR)."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment
    from openpyxl.utils import get_column_letter

    can_hr = _check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso non autorizzato ai dati HR.")
        return redirect("anagrafica:index")

    # Mappa legacy_id → nome/reparto
    all_cf_legacy = list(
        SaldoCedolino.objects.values("tax_code", "legacy_anagrafica_id")
        .distinct()
        .order_by("tax_code")
    )
    legacy_ids = [s["legacy_anagrafica_id"] for s in all_cf_legacy if s["legacy_anagrafica_id"]]
    dip_qs = list(AnagraficaDipendente.objects.filter(id__in=legacy_ids).values("id", "cognome", "nome", "reparto"))
    id_to_nome: dict = {
        d["id"]: f'{(d["cognome"] or "").strip()} {(d["nome"] or "").strip()}'.strip()
        for d in dip_qs
    }
    id_to_reparto: dict = {d["id"]: (d["reparto"] or "").strip() for d in dip_qs}
    cf_to_nome: dict = {}
    cf_to_reparto: dict = {}
    for row in all_cf_legacy:
        cf = row["tax_code"]
        lid = row["legacy_anagrafica_id"]
        cf_to_nome[cf] = id_to_nome.get(lid, cf) if lid else cf
        cf_to_reparto[cf] = id_to_reparto.get(lid, "") if lid else ""

    # Filtri GET (identici a ratei_list)
    filtro_periodo = request.GET.get("periodo", "")
    filtro_dipendenti: list = request.GET.getlist("dipendente")
    if not filtro_dipendenti:
        cf_compat = request.GET.get("cf", "").strip().upper()
        if cf_compat:
            filtro_dipendenti = [cf_compat]
    filtro_reparti: list = request.GET.getlist("reparto")

    qs = SaldoCedolino.objects.all().order_by("-data_competenza", "tax_code")
    if filtro_periodo:
        try:
            anno, mese, giorno = filtro_periodo.split("-")
            qs = qs.filter(data_competenza=date(int(anno), int(mese), int(giorno)))
        except (ValueError, AttributeError):
            pass
    if filtro_reparti:
        ids_in_reparto = [lid for lid, rep in id_to_reparto.items() if rep in filtro_reparti]
        qs = qs.filter(legacy_anagrafica_id__in=ids_in_reparto)
    if filtro_dipendenti:
        qs = qs.filter(tax_code__in=filtro_dipendenti)

    # --- Workbook ---
    wb = Workbook()
    ws = wb.active
    ws.title = "Ratei Ferie"

    fill_hdr  = PatternFill("solid", fgColor="F1F5F9")
    fill_fer  = PatternFill("solid", fgColor="FEF9C3")
    fill_rol  = PatternFill("solid", fgColor="DBEAFE")
    fill_exf  = PatternFill("solid", fgColor="DCFCE7")
    font_b    = Font(bold=True)
    font_fer  = Font(bold=True, color="854D0E")
    font_rol  = Font(bold=True, color="1E40AF")
    font_exf  = Font(bold=True, color="166534")
    c_center  = Alignment(horizontal="center", vertical="center", wrap_text=True)
    c_right   = Alignment(horizontal="right")

    # Riga 1 — gruppi
    groups = [
        ("A1:A2", "Dipendente",   fill_hdr, font_b),
        ("B1:B2", "Reparto",      fill_hdr, font_b),
        ("C1:C2", "Periodo",      fill_hdr, font_b),
        ("D1:D2", "Anzianità",    fill_hdr, font_b),
        ("E1:H1", "Ferie",        fill_fer, font_fer),
        ("I1:L1", "ROL",          fill_rol, font_rol),
        ("M1:P1", "Ex-Festività", fill_exf, font_exf),
    ]
    for rng, label, fill, fnt in groups:
        ws.merge_cells(rng)
        c = ws[rng.split(":")[0]]
        c.value = label; c.fill = fill; c.font = fnt; c.alignment = c_center

    # Riga 2 — sotto-intestazioni
    sub = [
        ("E", "Anni Prec.", fill_fer, font_fer), ("F", "Maturate",  fill_fer, font_fer),
        ("G", "Godute",     fill_fer, font_fer), ("H", "Residue",   fill_fer, font_fer),
        ("I", "Anni Prec.", fill_rol, font_rol), ("J", "Maturati",  fill_rol, font_rol),
        ("K", "Goduti",     fill_rol, font_rol), ("L", "Residui",   fill_rol, font_rol),
        ("M", "Anni Prec.", fill_exf, font_exf), ("N", "Maturate",  fill_exf, font_exf),
        ("O", "Godute",     fill_exf, font_exf), ("P", "Residue",   fill_exf, font_exf),
    ]
    for col, label, fill, fnt in sub:
        c = ws[f"{col}2"]
        c.value = label; c.fill = fill; c.font = fnt; c.alignment = c_center

    ws.freeze_panes = "A3"

    # Dati
    for s in qs.iterator():
        cf_upper = s.tax_code.upper()
        nome = cf_to_nome.get(cf_upper, s.tax_code)
        reparto = cf_to_reparto.get(cf_upper, "")
        periodo = s.data_competenza.strftime("%b %Y") if s.data_competenza else ""
        if s.anzianita_anni is not None:
            anz = f"{s.anzianita_anni}a"
            if s.anzianita_mesi:
                anz += f" {s.anzianita_mesi}m"
        else:
            anz = ""
        ws.append([
            nome, reparto, periodo, anz,
            s.ferie_anni_prec, s.ferie_maturati, s.ferie_goduti, s.ferie_residui,
            s.rol_anni_prec, s.rol_maturati, s.rol_goduti, s.rol_residui,
            s.ex_fest_anni_prec, s.ex_fest_maturati, s.ex_fest_goduti, s.ex_fest_residui,
        ])

    # Larghezze colonne
    for i, w in enumerate([28, 20, 12, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Nome file
    parts = []
    if filtro_reparti:
        parts.append("_".join(r.replace(" ", "-") for r in filtro_reparti[:2]))
    if filtro_periodo:
        parts.append(filtro_periodo[:7])
    fname = "ratei_ferie" + (f"_{'_'.join(parts)}" if parts else "") + ".xlsx"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    return response


# ---------------------------------------------------------------------------

@login_required
def impostazioni(request):
    """Pannello unico di gestione dei cataloghi/configurazioni del modulo anagrafica."""
    from datetime import timedelta
    from django.utils import timezone as tz

    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)

    active_tab = (request.GET.get("tab") or "mansioni").strip().lower()

    # --- Mansioni ---
    mansioni = list(Mansione.objects.all().order_by("nome"))
    mansione_counts: dict[str, int] = {}
    try:
        from django.db import connections
        conn_name = "legacy" if "legacy" in connections else "default"
        with connections[conn_name].cursor() as cur:
            cur.execute(
                "SELECT LOWER(mansione), COUNT(*) FROM anagrafica_dipendenti "
                "WHERE mansione IS NOT NULL AND mansione != '' GROUP BY LOWER(mansione)"
            )
            for row in cur.fetchall():
                mansione_counts[row[0]] = row[1]
    except Exception:
        pass
    for m in mansioni:
        m.n_dipendenti = mansione_counts.get(m.nome.lower(), 0)

    cat_order = [c for c, _ in Mansione.CATEGORIA_CHOICES]
    cat_labels = dict(Mansione.CATEGORIA_CHOICES)
    mansioni_grouped: list[tuple[str, str, list]] = []
    for cat_code in cat_order:
        items = [m for m in mansioni if (m.categoria or Mansione.CAT_ALTRO) == cat_code]
        if items:
            mansioni_grouped.append((cat_code, cat_labels[cat_code], items))

    # --- Aree aziendali ---
    aree = list(AreaAziendale.objects.all().order_by("nome"))

    # --- Ruoli aziendali ---
    ruoli_aziendali = list(RuoloAziendale.objects.all().order_by("nome"))

    # --- Ruoli operativi sicurezza ---
    ruoli_operativi = RuoloOperativo.objects.annotate(
        n_assegnati=Count("assegnazioni")
    ).order_by("nome")

    # --- Qualifiche professionali ---
    tipi_qualifica = list(
        TipoQualifica.objects.annotate(n_assegnazioni=Count("assegnazioni"))
        .order_by("categoria", "nome")
    )
    oggi = tz.localdate()
    soglia_q = oggi + timedelta(days=60)
    scadenze_q_count = DipendenteQualifica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__lte=soglia_q
    ).count()

    # --- Livelli contrattuali ---
    livelli = list(LivelloContrattuale.objects.all().order_by("ordine", "codice"))

    # --- Tipologie contratto ---
    tipologie = list(TipologiaContratto.objects.all().order_by("ordine", "codice"))

    # --- Permessi HR / widget statistiche (singleton) ---
    stat_perm = AnagraficaStatPermission.get_instance()
    hr_perm = AnagraficaHRPermission.get_instance()
    visite_perm = AnagraficaVisiteMedichePermission.get_instance()
    try:
        from core.legacy_models import Ruolo
        ruoli_acl = list(Ruolo.objects.order_by("nome"))
    except Exception:
        ruoli_acl = []

    # --- Tipi visita medica ---
    tipi_visita = list(
        TipoVisitaMedica.objects
        .annotate(n_visite=Count("visite"))
        .prefetch_related("ruoli_operativi")
        .order_by("nome")
    )
    scadenze_vm_count = VisitaMedica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__lte=soglia_q
    ).count()

    # --- DPI catalogo (gestione diretta dal pannello) ---
    dpi_categorie = []
    dpi_tipi = []
    dpi_modelli = []
    dpi_taglie = []
    try:
        from dpi.models import CategoriaDPI, TipoDPI, ModelloDPI, TagliaDPI as _TagliaDPI
        dpi_categorie = list(CategoriaDPI.objects.order_by("order_index", "nome"))
        dpi_tipi = list(TipoDPI.objects.select_related("categoria").prefetch_related("modelli").order_by("categoria__order_index", "categoria__nome", "ordine", "nome"))
        dpi_modelli = list(ModelloDPI.objects.select_related("tipo", "tipo__categoria").order_by("tipo__categoria__order_index", "tipo__ordine", "codice", "nome"))
        dpi_taglie = list(_TagliaDPI.objects.select_related("modello", "modello__tipo", "modello__tipo__categoria").order_by("modello__tipo__categoria__order_index", "modello__tipo__ordine", "ordine", "valore"))
    except Exception:
        pass

    # --- Cartelle documenti ---
    cartelle_documenti = list(
        CartellaDocumentoDipendente.objects
        .annotate(n_documenti=Count("documenti"))
        .order_by("ordine", "nome")
    )

    # --- Subnav navigazione ---
    subnav_categorie = list(SubnavCategoriaAnagrafica.objects.order_by("ordine", "nome"))
    subnav_links = list(
        SubnavLinkAnagrafica.objects
        .select_related("categoria")
        .order_by("ordine", "etichetta")
    )

    return render(request, "anagrafica/pages/impostazioni.html", {
        "is_admin": is_admin,
        "active_tab": active_tab,
        # Mansioni
        "mansioni": mansioni,
        "mansioni_grouped": mansioni_grouped,
        "CATEGORIA_CHOICES": Mansione.CATEGORIA_CHOICES,
        # Aree
        "aree": aree,
        # Ruoli aziendali
        "ruoli_aziendali": ruoli_aziendali,
        # Ruoli operativi
        "ruoli_operativi": ruoli_operativi,
        # Qualifiche
        "tipi_qualifica": tipi_qualifica,
        "QUAL_CATEGORIA_CHOICES": TipoQualifica.CATEGORIA_CHOICES,
        "scadenze_q_count": scadenze_q_count,
        # Livelli
        "livelli": livelli,
        # Tipologie
        "tipologie": tipologie,
        # Visite mediche
        "tipi_visita": tipi_visita,
        "scadenze_vm_count": scadenze_vm_count,
        # DPI
        "dpi_categorie": dpi_categorie,
        "dpi_tipi": dpi_tipi,
        "dpi_modelli": dpi_modelli,
        "dpi_taglie": dpi_taglie,
        # Permessi
        "stat_perm": stat_perm,
        "hr_perm": hr_perm,
        "visite_perm": visite_perm,
        "ruoli_acl": ruoli_acl,
        "ACCESSO_TUTTI": AnagraficaStatPermission.ACCESSO_TUTTI,
        "ACCESSO_ADMIN": AnagraficaStatPermission.ACCESSO_ADMIN,
        "ACCESSO_RUOLI": AnagraficaStatPermission.ACCESSO_RUOLI,
        # Cartelle documenti
        "cartelle_documenti": cartelle_documenti,
        # Subnav navigazione
        "subnav_categorie": subnav_categorie,
        "subnav_links": subnav_links,
    })


@login_required
@require_POST
def impostazioni_permessi_save(request):
    """Salvataggio combinato dei permessi statistiche e dati HR riservati."""
    ok, resp = _impostazioni_admin_check(request, "permessi")
    if not ok:
        return resp

    def _parse_accesso(prefix: str) -> str:
        val = (request.POST.get(f"{prefix}_accesso") or "").strip()
        if val in (
            AnagraficaStatPermission.ACCESSO_TUTTI,
            AnagraficaStatPermission.ACCESSO_ADMIN,
            AnagraficaStatPermission.ACCESSO_RUOLI,
        ):
            return val
        return AnagraficaStatPermission.ACCESSO_ADMIN

    def _parse_ruoli(prefix: str) -> list[int]:
        raw = request.POST.getlist(f"{prefix}_ruolo_ids")
        return [int(r) for r in raw if str(r).isdigit()]

    stat_perm = AnagraficaStatPermission.get_instance()
    stat_perm.accesso = _parse_accesso("stat")
    stat_perm.ruolo_ids = _parse_ruoli("stat")
    stat_perm.save()

    hr_perm = AnagraficaHRPermission.get_instance()
    hr_perm.accesso = _parse_accesso("hr")
    hr_perm.ruolo_ids = _parse_ruoli("hr")
    hr_perm.save()

    visite_perm = AnagraficaVisiteMedichePermission.get_instance()
    visite_perm.accesso = _parse_accesso("visite")
    visite_perm.ruolo_ids = _parse_ruoli("visite")
    visite_perm.save()

    messages.success(request, "Permessi salvati.")
    return _redirect_impostazioni("permessi")


@login_required
@require_POST
def tipo_visita_medica_create(request):
    ok, resp = _impostazioni_admin_check(request, "visite-mediche")
    if not ok:
        return resp
    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della visita è obbligatorio.")
        return _redirect_impostazioni("visite-mediche")
    durata_raw = request.POST.get("durata_mesi") or "12"
    try:
        durata_mesi = max(0, int(durata_raw))
    except ValueError:
        durata_mesi = 12
    tv, created = TipoVisitaMedica.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "durata_mesi": durata_mesi,
            "obbligatoria": request.POST.get("obbligatoria") == "1",
            "descrizione": (request.POST.get("descrizione") or "").strip(),
        },
    )
    if created:
        ruolo_ids = [int(x) for x in request.POST.getlist("ruolo_ids") if str(x).isdigit()]
        if ruolo_ids:
            tv.ruoli_operativi.set(ruolo_ids)
        messages.success(request, f'Tipo visita "{nome}" creato.')
    else:
        messages.warning(request, f'Esiste già un tipo visita con il nome "{nome}".')
    return _redirect_impostazioni("visite-mediche")


@login_required
@require_POST
def tipo_visita_medica_edit(request, tipo_id: int):
    ok, resp = _impostazioni_admin_check(request, "visite-mediche")
    if not ok:
        return resp
    tipo = get_object_or_404(TipoVisitaMedica, pk=tipo_id)
    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della visita è obbligatorio.")
        return _redirect_impostazioni("visite-mediche")
    durata_raw = request.POST.get("durata_mesi") or "12"
    try:
        durata_mesi = max(0, int(durata_raw))
    except ValueError:
        durata_mesi = 12
    tipo.nome = nome
    tipo.durata_mesi = durata_mesi
    tipo.obbligatoria = request.POST.get("obbligatoria") == "1"
    tipo.descrizione = (request.POST.get("descrizione") or "").strip()
    tipo.is_active = request.POST.get("is_active") == "1"
    tipo.save()
    ruolo_ids = [int(x) for x in request.POST.getlist("ruolo_ids") if str(x).isdigit()]
    tipo.ruoli_operativi.set(ruolo_ids)
    messages.success(request, f'Tipo visita "{tipo.nome}" aggiornato.')
    return _redirect_impostazioni("visite-mediche")


@login_required
@require_POST
def tipo_visita_medica_delete(request, tipo_id: int):
    ok, resp = _impostazioni_admin_check(request, "visite-mediche")
    if not ok:
        return resp
    tipo = get_object_or_404(TipoVisitaMedica, pk=tipo_id)
    if tipo.visite.exists():
        messages.error(request, f'"{tipo.nome}" ha visite registrate — non eliminabile.')
        return _redirect_impostazioni("visite-mediche")
    nome = tipo.nome
    tipo.delete()
    messages.success(request, f'Tipo visita "{nome}" eliminato.')
    return _redirect_impostazioni("visite-mediche")


# ---------------------------------------------------------------------------
# DPI catalogo — CRUD inline da anagrafica/impostazioni
# ---------------------------------------------------------------------------

def _dpi_parse_int(value) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _dpi_validate_image(uploaded) -> str | None:
    if uploaded is None:
        return None
    try:
        from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
        validate_extension_and_mime(
            uploaded,
            allowed_extensions={".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"},
            allowed_mimes={"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/x-ms-bmp"},
            label=getattr(uploaded, "name", "immagine"),
        )
    except Exception as exc:
        return str(exc)
    return None


@login_required
@require_POST
def dpi_categoria_create(request):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import CategoriaDPI
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome della categoria DPI è obbligatorio.")
        return _redirect_impostazioni("dpi")
    cat = CategoriaDPI(
        nome=nome,
        descrizione=(request.POST.get("descrizione") or "").strip(),
        icona_emoji=(request.POST.get("icona_emoji") or "🦺").strip() or "🦺",
        vita_utile_giorni=_dpi_parse_int(request.POST.get("vita_utile_giorni")),
        obbligatoria_mansionario=request.POST.get("obbligatoria_mansionario") == "1",
        unita_misura=(request.POST.get("unita_misura") or "pz").strip() or "pz",
        scorta_minima=_dpi_parse_int(request.POST.get("scorta_minima")) or 0,
        is_active=True,
        order_index=_dpi_parse_int(request.POST.get("order_index")) or 0,
    )
    uploaded = request.FILES.get("immagine")
    if uploaded:
        err = _dpi_validate_image(uploaded)
        if err:
            messages.error(request, err)
            return _redirect_impostazioni("dpi")
        cat.immagine = uploaded
    cat.save()
    messages.success(request, f'Categoria DPI "{nome}" creata.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_categoria_edit(request, pk: int):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import CategoriaDPI
    cat = get_object_or_404(CategoriaDPI, pk=pk)
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome della categoria DPI è obbligatorio.")
        return _redirect_impostazioni("dpi")
    cat.nome = nome
    cat.descrizione = (request.POST.get("descrizione") or "").strip()
    cat.icona_emoji = (request.POST.get("icona_emoji") or "🦺").strip() or "🦺"
    cat.vita_utile_giorni = _dpi_parse_int(request.POST.get("vita_utile_giorni"))
    cat.obbligatoria_mansionario = request.POST.get("obbligatoria_mansionario") == "1"
    cat.unita_misura = (request.POST.get("unita_misura") or "pz").strip() or "pz"
    cat.scorta_minima = _dpi_parse_int(request.POST.get("scorta_minima")) or 0
    cat.is_active = request.POST.get("is_active") == "1"
    cat.order_index = _dpi_parse_int(request.POST.get("order_index")) or 0
    uploaded = request.FILES.get("immagine")
    if uploaded:
        err = _dpi_validate_image(uploaded)
        if err:
            messages.error(request, err)
            return _redirect_impostazioni("dpi")
        cat.immagine = uploaded
    cat.save()
    messages.success(request, f'Categoria DPI "{cat.nome}" aggiornata.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_categoria_delete(request, pk: int):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import CategoriaDPI
    cat = get_object_or_404(CategoriaDPI, pk=pk)
    if cat.richieste.exists():
        messages.error(request, f'"{cat.nome}" ha richieste associate — disattivala invece di eliminarla.')
        return _redirect_impostazioni("dpi")
    nome = cat.nome
    cat.delete()
    messages.success(request, f'Categoria DPI "{nome}" eliminata.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_tipo_create(request):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import CategoriaDPI, TipoDPI
    categoria_id = (request.POST.get("categoria_id") or "").strip()
    nome = (request.POST.get("nome") or "").strip()
    if not categoria_id or not nome:
        messages.error(request, "Categoria e nome del tipo DPI sono obbligatori.")
        return _redirect_impostazioni("dpi")
    try:
        categoria = CategoriaDPI.objects.get(pk=int(categoria_id))
    except (CategoriaDPI.DoesNotExist, ValueError):
        messages.error(request, "Categoria DPI non valida.")
        return _redirect_impostazioni("dpi")
    if TipoDPI.objects.filter(categoria=categoria, nome=nome).exists():
        messages.error(request, f'Esiste già un tipo "{nome}" in questa categoria.')
        return _redirect_impostazioni("dpi")
    TipoDPI.objects.create(
        categoria=categoria,
        nome=nome,
        descrizione=(request.POST.get("descrizione") or "").strip(),
        ordine=_dpi_parse_int(request.POST.get("ordine")) or 0,
        is_active=True,
    )
    messages.success(request, f'Tipo DPI "{nome}" creato.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_tipo_edit(request, pk: int):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TipoDPI
    tipo = get_object_or_404(TipoDPI, pk=pk)
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome del tipo DPI è obbligatorio.")
        return _redirect_impostazioni("dpi")
    tipo.nome = nome
    tipo.descrizione = (request.POST.get("descrizione") or "").strip()
    tipo.ordine = _dpi_parse_int(request.POST.get("ordine")) or 0
    tipo.is_active = request.POST.get("is_active") == "1"
    tipo.save()
    messages.success(request, f'Tipo DPI "{tipo.nome}" aggiornato.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_tipo_delete(request, pk: int):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TipoDPI
    tipo = get_object_or_404(TipoDPI, pk=pk)
    if tipo.modelli.exists():
        messages.error(request, f'"{tipo.nome}" ha modelli associati — eliminali prima.')
        return _redirect_impostazioni("dpi")
    nome = tipo.nome
    tipo.delete()
    messages.success(request, f'Tipo DPI "{nome}" eliminato.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_modello_create(request):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TipoDPI, ModelloDPI
    tipo_id = (request.POST.get("tipo_id") or "").strip()
    codice = (request.POST.get("codice") or "").strip()
    nome = (request.POST.get("nome") or "").strip()
    if not tipo_id or not codice or not nome:
        messages.error(request, "Tipo, codice e nome del modello DPI sono obbligatori.")
        return _redirect_impostazioni("dpi")
    try:
        tipo = TipoDPI.objects.select_related("categoria").get(pk=int(tipo_id))
    except (TipoDPI.DoesNotExist, ValueError):
        messages.error(request, "Tipo DPI non valido.")
        return _redirect_impostazioni("dpi")
    if ModelloDPI.objects.filter(codice=codice).exists():
        messages.error(request, f'Esiste già un modello con codice "{codice}".')
        return _redirect_impostazioni("dpi")
    modello = ModelloDPI(
        tipo=tipo, codice=codice, nome=nome,
        produttore=(request.POST.get("produttore") or "").strip(),
        descrizione=(request.POST.get("descrizione") or "").strip(),
        vita_utile_giorni=_dpi_parse_int(request.POST.get("vita_utile_giorni")),
        is_active=True,
    )
    uploaded = request.FILES.get("immagine")
    if uploaded:
        err = _dpi_validate_image(uploaded)
        if err:
            messages.error(request, err)
            return _redirect_impostazioni("dpi")
        modello.immagine = uploaded
    modello.save()
    messages.success(request, f'Modello DPI "{codice}" creato.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_modello_edit(request, pk: int):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import ModelloDPI
    modello = get_object_or_404(ModelloDPI, pk=pk)
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome del modello DPI è obbligatorio.")
        return _redirect_impostazioni("dpi")
    modello.nome = nome
    modello.produttore = (request.POST.get("produttore") or "").strip()
    modello.descrizione = (request.POST.get("descrizione") or "").strip()
    modello.vita_utile_giorni = _dpi_parse_int(request.POST.get("vita_utile_giorni"))
    modello.is_active = request.POST.get("is_active") == "1"
    uploaded = request.FILES.get("immagine")
    if uploaded:
        err = _dpi_validate_image(uploaded)
        if err:
            messages.error(request, err)
            return _redirect_impostazioni("dpi")
        modello.immagine = uploaded
    modello.save()
    messages.success(request, f'Modello DPI "{modello.codice}" aggiornato.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_modello_delete(request, pk: int):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import ModelloDPI
    modello = get_object_or_404(ModelloDPI, pk=pk)
    if modello.taglie.exists():
        messages.error(request, f'"{modello.codice}" ha taglie associate — eliminale prima.')
        return _redirect_impostazioni("dpi")
    codice = modello.codice
    modello.delete()
    messages.success(request, f'Modello DPI "{codice}" eliminato.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_taglia_create(request):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import ModelloDPI, TagliaDPI as _TagliaDPI
    modello_id = (request.POST.get("modello_id") or "").strip()
    valore = (request.POST.get("valore") or "").strip()
    if not modello_id or not valore:
        messages.error(request, "Modello e valore della taglia DPI sono obbligatori.")
        return _redirect_impostazioni("dpi")
    try:
        modello = ModelloDPI.objects.get(pk=int(modello_id))
    except (ModelloDPI.DoesNotExist, ValueError):
        messages.error(request, "Modello DPI non valido.")
        return _redirect_impostazioni("dpi")
    if _TagliaDPI.objects.filter(modello=modello, valore=valore).exists():
        messages.error(request, f'Esiste già la taglia "{valore}" per questo modello.')
        return _redirect_impostazioni("dpi")
    _TagliaDPI.objects.create(
        modello=modello,
        valore=valore,
        ordine=_dpi_parse_int(request.POST.get("ordine")) or 0,
        is_active=True,
    )
    messages.success(request, f'Taglia DPI "{valore}" creata.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_taglia_edit(request, pk: int):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TagliaDPI as _TagliaDPI
    taglia = get_object_or_404(_TagliaDPI, pk=pk)
    valore = (request.POST.get("valore") or "").strip()
    if not valore:
        messages.error(request, "Il valore della taglia DPI è obbligatorio.")
        return _redirect_impostazioni("dpi")
    taglia.valore = valore
    taglia.ordine = _dpi_parse_int(request.POST.get("ordine")) or 0
    taglia.is_active = request.POST.get("is_active") == "1"
    taglia.save()
    messages.success(request, f'Taglia DPI "{taglia.valore}" aggiornata.')
    return _redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_taglia_delete(request, pk: int):
    ok, resp = _impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TagliaDPI as _TagliaDPI
    taglia = get_object_or_404(_TagliaDPI, pk=pk)
    valore = taglia.valore
    taglia.delete()
    messages.success(request, f'Taglia DPI "{valore}" eliminata.')
    return _redirect_impostazioni("dpi")


# ===========================================================================
# Visite mediche / Documenti dipendente / HTMX DPI iniziali
# ===========================================================================

def _ensure_admin(request):
    """Ritorna (legacy_user, is_admin). Riusa la convenzione del modulo."""
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    return legacy_user, (request.user.is_superuser or is_legacy_admin(legacy_user))


@login_required
@require_POST
def dipendente_visita_add(request, legacy_id: int):
    if not _can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per registrare visite mediche.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    form = VisitaMedicaForm(request.POST, request.FILES)
    if not form.is_valid():
        for err in form.errors.values():
            messages.error(request, "; ".join(err))
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    visita = form.save(commit=False)
    visita.legacy_anagrafica_id = legacy_id
    visita.created_by = request.user
    visita.updated_by = request.user
    visita.save()

    referto_file = form.cleaned_data.get("referto_file")
    if referto_file:
        doc = DocumentoDipendente(
            legacy_anagrafica_id=legacy_id,
            tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
            nome_originale=getattr(referto_file, "name", "") or "referto",
            tipo_mime=getattr(referto_file, "content_type", "") or "",
            dimensione_bytes=getattr(referto_file, "size", 0) or 0,
            descrizione=f"Referto visita {visita.tipo.nome} del {visita.data_svolgimento}",
            oggetto_riferimento_tipo="anagrafica.visitamedica",
            oggetto_riferimento_id=visita.pk,
            created_by=request.user,
            created_by_display=request.user.get_full_name() or request.user.username,
        )
        doc.file.save(referto_file.name, referto_file, save=True)
        visita.referto_documento = doc
        visita.save(update_fields=["referto_documento", "updated_at"])

    try:
        from core.audit import log_action
        log_action(
            request, "VISITA_MEDICA_CREATA", "anagrafica",
            f"Nuova visita {visita.tipo.nome} per #{legacy_id} ({visita.data_svolgimento})",
        )
    except Exception:
        logger.warning("Audit VISITA_MEDICA_CREATA fallito", exc_info=True)

    messages.success(request, f"Visita medica registrata. Scadenza: {visita.data_scadenza or '—'}")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_visita_edit(request, legacy_id: int, v_id: int):
    if not _can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per modificare le visite mediche.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    visita = get_object_or_404(VisitaMedica, pk=v_id, legacy_anagrafica_id=legacy_id)
    form = VisitaMedicaForm(request.POST, request.FILES, instance=visita)
    if not form.is_valid():
        for err in form.errors.values():
            messages.error(request, "; ".join(err))
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    visita = form.save(commit=False)
    visita.updated_by = request.user
    visita.save()

    referto_file = form.cleaned_data.get("referto_file")
    if referto_file:
        # Se esisteva un referto, lo sostituiamo con uno nuovo
        if visita.referto_documento_id:
            try:
                visita.referto_documento.delete()
            except Exception:
                logger.warning("Impossibile rimuovere referto precedente di visita %s", v_id, exc_info=True)
            visita.referto_documento = None
        doc = DocumentoDipendente(
            legacy_anagrafica_id=legacy_id,
            tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
            nome_originale=getattr(referto_file, "name", "") or "referto",
            tipo_mime=getattr(referto_file, "content_type", "") or "",
            dimensione_bytes=getattr(referto_file, "size", 0) or 0,
            descrizione=f"Referto visita {visita.tipo.nome} del {visita.data_svolgimento}",
            oggetto_riferimento_tipo="anagrafica.visitamedica",
            oggetto_riferimento_id=visita.pk,
            created_by=request.user,
            created_by_display=request.user.get_full_name() or request.user.username,
        )
        doc.file.save(referto_file.name, referto_file, save=True)
        visita.referto_documento = doc
        visita.save(update_fields=["referto_documento", "updated_at"])

    try:
        from core.audit import log_action
        log_action(
            request, "VISITA_MEDICA_MODIFICATA", "anagrafica",
            f"Modificata visita {visita.tipo.nome} per #{legacy_id} (v_id={v_id})",
        )
    except Exception:
        logger.warning("Audit VISITA_MEDICA_MODIFICATA fallito", exc_info=True)

    messages.success(request, "Visita medica aggiornata.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_visita_delete(request, legacy_id: int, v_id: int):
    if not _can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per eliminare visite mediche.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    _, is_admin = _ensure_admin(request)
    if not is_admin:
        messages.error(request, "Solo gli amministratori possono eliminare una visita medica.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    visita = get_object_or_404(VisitaMedica, pk=v_id, legacy_anagrafica_id=legacy_id)
    tipo_nome = visita.tipo.nome
    data = visita.data_svolgimento
    visita.delete()
    try:
        from core.audit import log_action
        log_action(
            request, "VISITA_MEDICA_ELIMINATA", "anagrafica",
            f"Eliminata visita {tipo_nome} per #{legacy_id} ({data})",
        )
    except Exception:
        logger.warning("Audit VISITA_MEDICA_ELIMINATA fallito", exc_info=True)
    messages.success(request, "Visita medica eliminata.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
def documento_dipendente_download(request, doc_id: int):
    doc = get_object_or_404(DocumentoDipendente, pk=doc_id)

    # ACL: referti visite mediche → permesso visite. Altri → admin/HR.
    if doc.tipo == DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO:
        if not _can_view_visite_mediche(request):
            return HttpResponse(status=403)
    else:
        legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
        if not (request.user.is_superuser or is_legacy_admin(legacy_user) or _check_hr_permission(request)):
            return HttpResponse(status=403)

    if not doc.file:
        return HttpResponse("File non disponibile.", status=404)

    try:
        from core.audit import log_action
        log_action(
            request, "DOCUMENTO_DIPENDENTE_DOWNLOAD", "anagrafica",
            f"Download documento #{doc.pk} ({doc.tipo}) di dipendente #{doc.legacy_anagrafica_id}",
        )
    except Exception:
        logger.warning("Audit DOCUMENTO_DIPENDENTE_DOWNLOAD fallito", exc_info=True)

    from django.http import FileResponse
    try:
        fh = doc.file.open("rb")
    except FileNotFoundError:
        return HttpResponse("File non trovato sul server.", status=404)
    response = FileResponse(fh, as_attachment=True, filename=doc.nome_originale or f"documento_{doc.pk}.bin")
    if doc.tipo_mime:
        response["Content-Type"] = doc.tipo_mime
    return response


@login_required
@require_POST
def documento_dipendente_delete(request, doc_id: int):
    _, is_admin = _ensure_admin(request)
    if not is_admin:
        messages.error(request, "Solo gli amministratori possono eliminare un documento.")
        return redirect("anagrafica:dipendenti_list")
    doc = get_object_or_404(DocumentoDipendente, pk=doc_id)
    legacy_id = doc.legacy_anagrafica_id
    tipo = doc.tipo
    doc.delete()
    try:
        from core.audit import log_action
        log_action(
            request, "DOCUMENTO_DIPENDENTE_ELIMINATO", "anagrafica",
            f"Eliminato documento #{doc_id} ({tipo}) di dipendente #{legacy_id}",
        )
    except Exception:
        logger.warning("Audit DOCUMENTO_DIPENDENTE_ELIMINATO fallito", exc_info=True)
    messages.success(request, "Documento eliminato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Upload manuale documento dipendente
# ---------------------------------------------------------------------------

_ALLOWED_DOC_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/jpeg",
    "image/png",
    "image/webp",
}
_ALLOWED_DOC_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".webp"}
_MAX_DOC_SIZE = 20 * 1024 * 1024  # 20 MB


@login_required
@require_POST
def documento_dipendente_upload(request, legacy_id: int):
    """Carica un documento manuale nella cartella virtuale del dipendente."""
    _, is_admin = _ensure_admin(request)
    if not is_admin:
        messages.error(request, "Solo gli amministratori possono caricare documenti.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    cartella_id = request.POST.get("cartella_id") or None
    descrizione = (request.POST.get("descrizione") or "").strip()[:300]
    uploaded = request.FILES.get("file")

    if not uploaded:
        messages.error(request, "Seleziona un file da caricare.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    suffix = Path(uploaded.name or "").suffix.lower()
    if suffix not in _ALLOWED_DOC_EXTENSIONS:
        messages.error(request, f"Formato non consentito ({suffix}). Formati ammessi: PDF, DOC, DOCX, XLS, XLSX, JPG, PNG.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    if uploaded.size > _MAX_DOC_SIZE:
        messages.error(request, f"File troppo grande ({uploaded.size // (1024*1024)} MB). Limite: 20 MB.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    try:
        from core.upload_mime import sniff_mime
        mime = sniff_mime(uploaded)
    except Exception:
        mime = uploaded.content_type or "application/octet-stream"

    if mime not in _ALLOWED_DOC_MIMES:
        messages.error(request, "Tipo di file non consentito (contenuto non valido).")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    cartella = None
    if cartella_id:
        cartella = CartellaDocumentoDipendente.objects.filter(pk=cartella_id, attiva=True).first()

    doc = DocumentoDipendente(
        legacy_anagrafica_id=legacy_id,
        tipo=DocumentoDipendente.Tipo.MANUALE,
        cartella=cartella,
        nome_originale=uploaded.name[:255],
        tipo_mime=mime,
        dimensione_bytes=uploaded.size,
        descrizione=descrizione,
        created_by=request.user,
        created_by_display=request.user.get_full_name() or request.user.username,
    )
    doc.file = uploaded
    doc.save()

    try:
        from core.audit import log_action
        log_action(
            request, "DOCUMENTO_DIPENDENTE_UPLOAD", "anagrafica",
            {
                "documento_id": doc.pk,
                "nome_originale": doc.nome_originale,
                "cartella_id": cartella.pk if cartella else None,
                "cartella_nome": cartella.nome if cartella else "",
                "legacy_anagrafica_id": legacy_id,
            },
        )
    except Exception:
        logger.warning("Audit DOCUMENTO_DIPENDENTE_UPLOAD fallito", exc_info=True)

    messages.success(request, f"Documento '{doc.nome_originale}' caricato correttamente.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Lista globale documenti manuali (tab generale)
# ---------------------------------------------------------------------------

@login_required
def documenti_list(request):
    """Lista di tutti i documenti caricati manualmente, filtrabile per dipendente/cartella."""
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    hr_ok = _check_hr_permission(request)

    if not (is_admin or hr_ok):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("anagrafica:index")

    cartelle = list(CartellaDocumentoDipendente.objects.all())
    qs = DocumentoDipendente.objects.filter(tipo=DocumentoDipendente.Tipo.MANUALE).select_related("cartella", "created_by").order_by("-created_at")

    filtro_cartella = request.GET.get("cartella", "").strip()
    filtro_cerca = request.GET.get("q", "").strip()
    filtro_anno = request.GET.get("anno", "").strip()

    if filtro_cartella:
        if filtro_cartella == "__nessuna__":
            qs = qs.filter(cartella__isnull=True)
        else:
            try:
                qs = qs.filter(cartella_id=int(filtro_cartella))
            except (ValueError, TypeError):
                pass

    if filtro_anno:
        try:
            qs = qs.filter(created_at__year=int(filtro_anno))
        except (ValueError, TypeError):
            pass

    nomi_map = _build_nomi_map()
    documenti = list(qs[:500])
    if filtro_cerca:
        q_low = filtro_cerca.lower()
        documenti = [
            d for d in documenti
            if q_low in nomi_map.get(d.legacy_anagrafica_id, "").lower()
            or q_low in (d.nome_originale or "").lower()
            or q_low in (d.descrizione or "").lower()
        ]

    for d in documenti:
        d.nome_dipendente = nomi_map.get(d.legacy_anagrafica_id, f"#{d.legacy_anagrafica_id}")

    return render(request, "anagrafica/pages/documenti_list.html", {
        "is_admin": is_admin,
        "documenti": documenti,
        "cartelle": cartelle,
        "filtro_cartella": filtro_cartella,
        "filtro_cerca": filtro_cerca,
        "filtro_anno": filtro_anno,
        "anni_disponibili": list(range(2020, __import__("datetime").date.today().year + 1)),
    })


# ---------------------------------------------------------------------------
# CRUD cartelle documenti (da impostazioni)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def cartella_documento_create(request):
    ok, resp = _impostazioni_admin_check(request, "documenti")
    if not ok:
        return resp
    nome = (request.POST.get("nome") or "").strip()[:100]
    descrizione = (request.POST.get("descrizione") or "").strip()[:300]
    ordine_raw = (request.POST.get("ordine") or "0").strip()
    if not nome:
        messages.error(request, "Il nome della cartella è obbligatorio.")
        return _redirect_impostazioni("documenti")
    try:
        ordine = int(ordine_raw)
    except (ValueError, TypeError):
        ordine = 0
    if CartellaDocumentoDipendente.objects.filter(nome__iexact=nome).exists():
        messages.error(request, f"Esiste già una cartella con nome «{nome}».")
        return _redirect_impostazioni("documenti")
    CartellaDocumentoDipendente.objects.create(nome=nome, descrizione=descrizione, ordine=ordine)
    messages.success(request, f"Cartella «{nome}» creata.")
    return _redirect_impostazioni("documenti")


@login_required
@require_POST
def cartella_documento_edit(request, cartella_id: int):
    ok, resp = _impostazioni_admin_check(request, "documenti")
    if not ok:
        return resp
    cartella = get_object_or_404(CartellaDocumentoDipendente, pk=cartella_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    descrizione = (request.POST.get("descrizione") or "").strip()[:300]
    ordine_raw = (request.POST.get("ordine") or "0").strip()
    attiva = request.POST.get("attiva") == "1"
    if not nome:
        messages.error(request, "Il nome della cartella è obbligatorio.")
        return _redirect_impostazioni("documenti")
    if CartellaDocumentoDipendente.objects.filter(nome__iexact=nome).exclude(pk=cartella_id).exists():
        messages.error(request, f"Esiste già un'altra cartella con nome «{nome}».")
        return _redirect_impostazioni("documenti")
    try:
        ordine = int(ordine_raw)
    except (ValueError, TypeError):
        ordine = cartella.ordine
    cartella.nome = nome
    cartella.descrizione = descrizione
    cartella.ordine = ordine
    cartella.attiva = attiva
    cartella.save()
    messages.success(request, f"Cartella «{nome}» aggiornata.")
    return _redirect_impostazioni("documenti")


@login_required
@require_POST
def cartella_documento_delete(request, cartella_id: int):
    ok, resp = _impostazioni_admin_check(request, "documenti")
    if not ok:
        return resp
    cartella = get_object_or_404(CartellaDocumentoDipendente, pk=cartella_id)
    n_docs = cartella.documenti.count()
    if n_docs > 0:
        messages.error(request, f"Impossibile eliminare: la cartella contiene {n_docs} documento/i. Spostali o disattiva la cartella.")
        return _redirect_impostazioni("documenti")
    nome = cartella.nome
    cartella.delete()
    messages.success(request, f"Cartella «{nome}» eliminata.")
    return _redirect_impostazioni("documenti")


# ---------------------------------------------------------------------------
# CRUD subnav — categorie e link (da impostazioni)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def subnav_categoria_create(request):
    ok, resp = _impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    nome = (request.POST.get("nome") or "").strip()[:80]
    icona = (request.POST.get("icona") or "").strip()[:20]
    ordine_raw = (request.POST.get("ordine") or "0").strip()
    if not nome:
        messages.error(request, "Il nome della categoria è obbligatorio.")
        return _redirect_impostazioni("navigazione")
    try:
        ordine = int(ordine_raw)
    except (ValueError, TypeError):
        ordine = 0
    SubnavCategoriaAnagrafica.objects.create(nome=nome, icona=icona, ordine=ordine)
    messages.success(request, f"Categoria «{nome}» creata.")
    return _redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_categoria_edit(request, cat_id: int):
    ok, resp = _impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    cat = get_object_or_404(SubnavCategoriaAnagrafica, pk=cat_id)
    cat.nome = (request.POST.get("nome") or "").strip()[:80] or cat.nome
    cat.icona = (request.POST.get("icona") or "").strip()[:20]
    cat.is_active = request.POST.get("is_active") == "1"
    try:
        cat.ordine = int(request.POST.get("ordine") or cat.ordine)
    except (ValueError, TypeError):
        pass
    cat.save()
    messages.success(request, f"Categoria «{cat.nome}» aggiornata.")
    return _redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_categoria_delete(request, cat_id: int):
    ok, resp = _impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    cat = get_object_or_404(SubnavCategoriaAnagrafica, pk=cat_id)
    n_links = cat.links.count()
    if n_links > 0:
        messages.error(request, f"Impossibile eliminare: la categoria contiene {n_links} link/s. Spostarli o eliminarli prima.")
        return _redirect_impostazioni("navigazione")
    nome = cat.nome
    cat.delete()
    messages.success(request, f"Categoria «{nome}» eliminata.")
    return _redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_link_create(request):
    ok, resp = _impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    etichetta = (request.POST.get("etichetta") or "").strip()[:80]
    icona = (request.POST.get("icona") or "").strip()[:20]
    url_type = request.POST.get("url_type") or "raw"
    if url_type not in ("named", "raw"):
        url_type = "raw"
    url_value = (request.POST.get("url_value") or "").strip()[:255]
    cat_id_raw = (request.POST.get("categoria_id") or "").strip()
    apri_nuova_tab = request.POST.get("apri_nuova_tab") == "1"
    try:
        ordine = int(request.POST.get("ordine") or 0)
    except (ValueError, TypeError):
        ordine = 0
    if not etichetta or not url_value:
        messages.error(request, "Etichetta e URL sono obbligatori.")
        return _redirect_impostazioni("navigazione")
    cat = None
    if cat_id_raw:
        cat = SubnavCategoriaAnagrafica.objects.filter(pk=cat_id_raw).first()
    SubnavLinkAnagrafica.objects.create(
        etichetta=etichetta, icona=icona, url_type=url_type, url_value=url_value,
        categoria=cat, apri_nuova_tab=apri_nuova_tab, ordine=ordine, is_sistema=False,
    )
    messages.success(request, f"Link «{etichetta}» aggiunto.")
    return _redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_link_edit(request, link_id: int):
    ok, resp = _impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    link = get_object_or_404(SubnavLinkAnagrafica, pk=link_id)
    link.etichetta = (request.POST.get("etichetta") or "").strip()[:80] or link.etichetta
    link.icona = (request.POST.get("icona") or "").strip()[:20]
    link.is_active = request.POST.get("is_active") == "1"
    link.apri_nuova_tab = request.POST.get("apri_nuova_tab") == "1"
    try:
        link.ordine = int(request.POST.get("ordine") or link.ordine)
    except (ValueError, TypeError):
        pass
    cat_id_raw = (request.POST.get("categoria_id") or "").strip()
    if cat_id_raw:
        link.categoria = SubnavCategoriaAnagrafica.objects.filter(pk=cat_id_raw).first()
    else:
        link.categoria = None
    # Per link non di sistema permetti anche di cambiare URL
    if not link.is_sistema:
        url_type = request.POST.get("url_type") or link.url_type
        if url_type in ("named", "raw"):
            link.url_type = url_type
        url_value = (request.POST.get("url_value") or "").strip()[:255]
        if url_value:
            link.url_value = url_value
    link.save()
    messages.success(request, f"Link «{link.etichetta}» aggiornato.")
    return _redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_link_delete(request, link_id: int):
    ok, resp = _impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    link = get_object_or_404(SubnavLinkAnagrafica, pk=link_id)
    if link.is_sistema:
        messages.error(request, "I link di sistema non possono essere eliminati. Puoi disattivarli.")
        return _redirect_impostazioni("navigazione")
    nome = link.etichetta
    link.delete()
    messages.success(request, f"Link «{nome}» eliminato.")
    return _redirect_impostazioni("navigazione")


@login_required
def dipendente_dpi_iniziali_proposti(request):
    """Partial HTMX: lista righe DPI iniziali in base ai ruoli operativi scelti.

    Accetta ``ruoli_operativi_ids`` (multi-value) via GET. Ritorna l'HTML
    parziale ``_dpi_iniziali_righe.html`` con il formset pre-compilato.
    """
    ruoli_raw = request.GET.getlist("ruoli_operativi_ids")
    ruoli_ids: list[int] = []
    for raw in ruoli_raw:
        try:
            ruoli_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    righe = proposta_righe_iniziali(ruoli_ids)
    return render(
        request,
        "anagrafica/partials/_dpi_iniziali_righe.html",
        {"righe": righe, "indici": list(range(len(righe)))},
    )


@login_required
def visite_mediche_dashboard(request):
    """Dashboard globale visite mediche.

    Mostra (gating su ``_can_view_visite_mediche``):
    - contatori: scadute / in scadenza / valide / mancanti aggregati sull'azienda
    - tabella "scadute o in scadenza" con dettaglio dipendente
    - tabella "ultime visite registrate"
    - elenco tipologie attive con counter di dipendenti coperti vs richiesti
    """
    if not _can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per visualizzare le visite mediche.")
        return redirect("anagrafica:index")

    import calendar as _calendar
    from django.utils import timezone as _tz

    oggi = _tz.localdate()
    soglia_avviso = oggi + _timedelta(days=60)

    # Filtro mese dalla query string (?scad=mese_corrente | prossimo_mese | tutti)
    filtro_scad = request.GET.get("scad", "").strip()

    # Map legacy_id -> "Cognome Nome" da AnagraficaDipendente (lookup unico)
    nomi_map = _build_nomi_map()

    # KPI globali (sempre sull'intero dataset, non influenzati dal filtro)
    kpi_scadute = VisitaMedica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__lt=oggi
    ).count()
    kpi_in_scad = VisitaMedica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__range=[oggi, soglia_avviso]
    ).count()
    kpi_visite_totali = VisitaMedica.objects.count()

    # Ultime visite registrate (globale, 30 più recenti)
    ultime_visite = list(
        VisitaMedica.objects
        .select_related("tipo")
        .order_by("-data_svolgimento", "-id")[:30]
    )
    for v in ultime_visite:
        v.dipendente_nome = nomi_map.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")

    # Scadute o in scadenza — con filtro mese opzionale
    if filtro_scad == "mese_corrente":
        _, last_day_n = _calendar.monthrange(oggi.year, oggi.month)
        _range_start = oggi.replace(day=1)
        _range_end = oggi.replace(day=last_day_n)
        scad_qs = VisitaMedica.objects.filter(
            data_scadenza__isnull=False,
            data_scadenza__range=[_range_start, _range_end],
        )
    elif filtro_scad == "prossimo_mese":
        pm_y = oggi.year + 1 if oggi.month == 12 else oggi.year
        pm_m = 1 if oggi.month == 12 else oggi.month + 1
        _, last_day_n = _calendar.monthrange(pm_y, pm_m)
        _range_start = date(pm_y, pm_m, 1)
        _range_end = date(pm_y, pm_m, last_day_n)
        scad_qs = VisitaMedica.objects.filter(
            data_scadenza__isnull=False,
            data_scadenza__range=[_range_start, _range_end],
        )
    else:
        filtro_scad = "tutti"
        scad_qs = VisitaMedica.objects.filter(
            data_scadenza__isnull=False, data_scadenza__lte=soglia_avviso
        )

    scad_o_in_scad = list(scad_qs.select_related("tipo").order_by("data_scadenza"))
    for v in scad_o_in_scad:
        v.dipendente_nome = nomi_map.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")
        v.giorni_a_scadenza = (v.data_scadenza - oggi).days if v.data_scadenza else None

    # Pre-aggrega conteggi DB per tipo (evita N query nel loop)
    _valide_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in VisitaMedica.objects
        .filter(data_scadenza__gte=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }
    _scadute_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in VisitaMedica.objects
        .filter(data_scadenza__lt=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }

    # Tipologie con copertura ruoli + conteggi reali DB
    tipi_attivi_qs = TipoVisitaMedica.objects.filter(is_active=True).prefetch_related("ruoli_operativi")
    tipologie_stats = []
    for t in tipi_attivi_qs:
        ruoli_ids = list(t.ruoli_operativi.values_list("id", flat=True))
        if ruoli_ids:
            legacy_ids_richiesti = set(
                DipendenteRuoloOperativo.objects
                .filter(ruolo_id__in=ruoli_ids)
                .values_list("legacy_anagrafica_id", flat=True)
            )
        else:
            legacy_ids_richiesti = set()
        legacy_ids_coperti = set(
            VisitaMedica.objects
            .filter(tipo=t, data_scadenza__gte=oggi)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        mancanti = legacy_ids_richiesti - legacy_ids_coperti
        tipologie_stats.append({
            "tipo": t,
            "ha_ruoli": bool(ruoli_ids),
            "richiesti": len(legacy_ids_richiesti),
            "coperti": len(legacy_ids_richiesti & legacy_ids_coperti),
            "mancanti": len(mancanti),
            "valide_db": _valide_per_tipo.get(t.pk, 0),
            "scadute_db": _scadute_per_tipo.get(t.pk, 0),
        })

    kpi_tipi_attivi = tipi_attivi_qs.count()

    return render(request, "anagrafica/pages/visite_mediche_dashboard.html", {
        "oggi": oggi,
        "kpi_scadute": kpi_scadute,
        "kpi_in_scad": kpi_in_scad,
        "kpi_totali": kpi_visite_totali,
        "kpi_tipi_attivi": kpi_tipi_attivi,
        "ultime_visite": ultime_visite,
        "scad_o_in_scad": scad_o_in_scad,
        "tipologie_stats": tipologie_stats,
        "can_manage": _can_view_visite_mediche(request),
        "filtro_scad": filtro_scad,
    })


# ---------------------------------------------------------------------------
# Helpers: registrazione sessione batch visite mediche
# ---------------------------------------------------------------------------

def _build_nomi_map() -> dict[int, str]:
    """Ritorna dict {legacy_anagrafica_id: 'Cognome Nome'} per tutti i dipendenti."""
    nomi: dict[int, str] = {}
    try:
        for r in AnagraficaDipendente.objects.values("id", "cognome", "nome"):
            try:
                lid = int(r.get("id") or 0)
            except (TypeError, ValueError):
                continue
            cog = (r.get("cognome") or "").strip()
            nom = (r.get("nome") or "").strip()
            nomi[lid] = f"{cog} {nom}".strip() or f"#{lid}"
    except Exception:
        logger.exception("Errore lookup nomi dipendenti per sessione visita")
    return nomi


def _build_candidati_sessione(tipo: TipoVisitaMedica, oggi) -> list[dict]:
    """Ritorna lista dipendenti candidati per una sessione di visita del tipo dato.

    Vengono inclusi i dipendenti:
    - con almeno un ruolo operativo collegato al tipo (o tutti gli attivi se nessun ruolo configurato)
    - la cui ultima visita del tipo è scaduta, in scadenza ≤90gg, oppure mai effettuata
    """
    from django.utils import timezone as _tz

    soglia = oggi + _timedelta(days=90)

    # Determina il pool di legacy_id candidati
    ruolo_ids = list(tipo.ruoli_operativi.values_list("id", flat=True))
    if ruolo_ids:
        pool_ids = set(
            DipendenteRuoloOperativo.objects
            .filter(ruolo_id__in=ruolo_ids)
            .values_list("legacy_anagrafica_id", flat=True)
        )
    else:
        # Tipo senza ruoli → tutti i dipendenti attivi
        pool_ids = set(
            DipendenteAnagraficaAziendale.objects
            .filter(data_cessazione__isnull=True)
            .values_list("legacy_anagrafica_id", flat=True)
        )

    if not pool_ids:
        return []

    # Ultima visita del tipo per ogni legacy_id
    ultima_per_id: dict[int, "VisitaMedica"] = {}
    for v in (
        VisitaMedica.objects
        .filter(tipo=tipo, legacy_anagrafica_id__in=pool_ids)
        .select_related("tipo")
        .order_by("legacy_anagrafica_id", "-data_svolgimento")
    ):
        if v.legacy_anagrafica_id not in ultima_per_id:
            ultima_per_id[v.legacy_anagrafica_id] = v

    nomi_map = _build_nomi_map()

    candidati = []
    for lid in pool_ids:
        ultima = ultima_per_id.get(lid)
        if ultima is None:
            status = "mai_effettuata"
            giorni = None
        elif ultima.data_scadenza is None or ultima.data_scadenza < oggi:
            status = "scaduta"
            giorni = (ultima.data_scadenza - oggi).days if ultima.data_scadenza else None
        elif ultima.data_scadenza <= soglia:
            status = "in_scadenza"
            giorni = (ultima.data_scadenza - oggi).days
        else:
            continue  # Visita ancora valida, non proporre

        candidati.append({
            "legacy_id": lid,
            "nome": nomi_map.get(lid, f"#{lid}"),
            "ultima_visita": ultima,
            "status": status,
            "giorni_a_scadenza": giorni,
        })

    # Ordine: in_scadenza → scaduta → mai_effettuata; poi alfabetico per nome
    _status_order = {"in_scadenza": 0, "scaduta": 1, "mai_effettuata": 2}
    candidati.sort(key=lambda c: (_status_order.get(c["status"], 9), c["nome"]))
    return candidati


# ---------------------------------------------------------------------------
# View: registrazione nuova sessione batch visite mediche
# ---------------------------------------------------------------------------

@login_required
def visite_mediche_nuova_sessione(request):
    """Registrazione batch di visite mediche per un tipo e una data.

    Step 1 (GET / POST step=1): selezione tipo visita, data, medico competente.
    Step 2 (POST step=2): tabella dipendenti candidati con esito per ognuno → salva.
    """
    if not _can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per registrare le visite mediche.")
        return redirect("anagrafica:visite_mediche_dashboard")

    from django.utils import timezone as _tz

    oggi = _tz.localdate()
    tipi_attivi = list(TipoVisitaMedica.objects.filter(is_active=True).order_by("nome"))

    # ---- Step 2: salva i record -----------------------------------------
    if request.method == "POST" and request.POST.get("step") == "2":
        tipo_id = request.POST.get("tipo_id", "").strip()
        data_str = request.POST.get("data_svolgimento", "").strip()
        medico = request.POST.get("medico_competente", "").strip()

        try:
            tipo = TipoVisitaMedica.objects.get(pk=tipo_id, is_active=True)
        except (TipoVisitaMedica.DoesNotExist, ValueError):
            messages.error(request, "Tipo visita non valido.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        try:
            data_svolgimento = date.fromisoformat(data_str)
        except (ValueError, TypeError):
            messages.error(request, "Data non valida.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        selected_ids = request.POST.getlist("dipendenti_selezionati")
        if not selected_ids:
            messages.warning(request, "Nessun dipendente selezionato.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        creati = 0
        errori = []
        for legacy_id_str in selected_ids:
            try:
                legacy_id = int(legacy_id_str)
            except (ValueError, TypeError):
                continue
            esito = request.POST.get(f"esito_{legacy_id}", VisitaMedica.Esito.IDONEO)
            if esito not in VisitaMedica.Esito.values:
                esito = VisitaMedica.Esito.IDONEO
            note = request.POST.get(f"note_{legacy_id}", "").strip()
            try:
                VisitaMedica.objects.create(
                    legacy_anagrafica_id=legacy_id,
                    tipo=tipo,
                    data_svolgimento=data_svolgimento,
                    esito=esito,
                    prescrizioni=note,
                    medico_competente=medico,
                    created_by=request.user,
                    updated_by=request.user,
                )
                creati += 1
            except Exception:
                logger.exception("Errore creazione VisitaMedica per legacy_id=%s", legacy_id)
                errori.append(legacy_id_str)

        try:
            from core.audit import log_action
            log_action(
                request,
                "VISITA_MEDICA_BATCH_CREATA",
                "anagrafica",
                f"Sessione {tipo.nome} del {data_svolgimento}: {creati} visite registrate.",
            )
        except Exception:
            logger.warning("Audit VISITA_MEDICA_BATCH_CREATA fallito", exc_info=True)

        if errori:
            messages.warning(request, f"{creati} visite registrate. Errori per: {', '.join(errori)}.")
        else:
            messages.success(request, f"{creati} visite registrate per {tipo.nome} del {data_svolgimento.strftime('%d/%m/%Y')}.")
        return redirect("anagrafica:visite_mediche_dashboard")

    # ---- Step 1: carica candidati ----------------------------------------
    candidati = []
    tipo_selezionato = None
    data_svolgimento_str = ""
    medico_competente = ""
    step = 1

    if request.method == "POST" and request.POST.get("step") == "1":
        tipo_id = request.POST.get("tipo_id", "").strip()
        data_svolgimento_str = request.POST.get("data_svolgimento", "").strip()
        medico_competente = request.POST.get("medico_competente", "").strip()
        step = 2

        try:
            tipo_selezionato = TipoVisitaMedica.objects.get(pk=tipo_id, is_active=True)
        except (TipoVisitaMedica.DoesNotExist, ValueError):
            messages.error(request, "Seleziona un tipo di visita valido.")
            step = 1

        if step == 2 and not data_svolgimento_str:
            messages.error(request, "Inserisci la data di svolgimento.")
            step = 1

        if step == 2:
            try:
                data_svolgimento_parsed = date.fromisoformat(data_svolgimento_str)
            except (ValueError, TypeError):
                messages.error(request, "Data non valida.")
                step = 1
            else:
                candidati = _build_candidati_sessione(tipo_selezionato, oggi)
                if not candidati:
                    messages.info(
                        request,
                        f"Nessun dipendente risulta in scadenza per '{tipo_selezionato.nome}' "
                        f"nei prossimi 90 giorni.",
                    )

    return render(request, "anagrafica/pages/visite_mediche_nuova_sessione.html", {
        "tipi_attivi": tipi_attivi,
        "step": step,
        "tipo_selezionato": tipo_selezionato,
        "data_svolgimento_str": data_svolgimento_str,
        "medico_competente": medico_competente,
        "candidati": candidati,
        "esiti": VisitaMedica.Esito.choices,
        "esito_default": VisitaMedica.Esito.IDONEO,
    })


# ---------------------------------------------------------------------------
# API: ricerca live dipendente per aggiunta manuale in sessione
# ---------------------------------------------------------------------------

@login_required
def visite_mediche_api_cerca_dipendente(request):
    """Ricerca live dipendenti per il popup '+Aggiungi dipendente' nella sessione.

    GET ?q=QUERY&exclude=ID1,ID2,...
    Ritorna JSON {results: [{legacy_id, nome}, ...]}
    """
    if not _can_view_visite_mediche(request):
        return JsonResponse({"error": "Forbidden"}, status=403)

    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})

    exclude_ids: set[int] = set()
    for s in request.GET.get("exclude", "").split(","):
        try:
            exclude_ids.add(int(s.strip()))
        except (ValueError, TypeError):
            pass

    qs = (
        AnagraficaDipendente.objects
        .filter(Q(cognome__icontains=q) | Q(nome__icontains=q))
        .exclude(id__in=exclude_ids)
        .order_by("cognome", "nome")[:25]
    )
    results = []
    for d in qs:
        cog = (getattr(d, "cognome", "") or "").strip()
        nom = (getattr(d, "nome", "") or "").strip()
        results.append({"legacy_id": d.id, "nome": f"{cog} {nom}".strip() or f"#{d.id}"})
    return JsonResponse({"results": results})


# ---------------------------------------------------------------------------
# Export Excel: copertura per tipologia e visite in scadenza
# ---------------------------------------------------------------------------

@login_required
def visite_mediche_export_scadenze(request):
    """Scarica le visite scadute/in scadenza come file .xlsx.

    Accetta ?scad=mese_corrente | prossimo_mese (default: tutti ≤60g).
    """
    if not _can_view_visite_mediche(request):
        return HttpResponse(status=403)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return HttpResponse("openpyxl non installato.", status=500)

    import calendar as _cal
    from django.utils import timezone as _tz

    oggi = _tz.localdate()
    filtro = request.GET.get("scad", "tutti").strip()

    if filtro == "mese_corrente":
        _, ld = _cal.monthrange(oggi.year, oggi.month)
        qs = VisitaMedica.objects.filter(
            data_scadenza__isnull=False,
            data_scadenza__range=[oggi.replace(day=1), oggi.replace(day=ld)],
        )
        label = f"mese_corrente_{oggi.strftime('%Y%m')}"
    elif filtro == "prossimo_mese":
        pm_y = oggi.year + 1 if oggi.month == 12 else oggi.year
        pm_m = 1 if oggi.month == 12 else oggi.month + 1
        _, ld = _cal.monthrange(pm_y, pm_m)
        qs = VisitaMedica.objects.filter(
            data_scadenza__isnull=False,
            data_scadenza__range=[date(pm_y, pm_m, 1), date(pm_y, pm_m, ld)],
        )
        label = f"prossimo_mese_{pm_y}{pm_m:02d}"
    else:
        qs = VisitaMedica.objects.filter(
            data_scadenza__isnull=False, data_scadenza__lte=oggi + _timedelta(days=60)
        )
        label = "scadenze_60gg"

    qs = qs.select_related("tipo").order_by("data_scadenza")
    nomi_map = _build_nomi_map()

    # CF lookup
    cf_map: dict[int, str] = dict(
        DipendenteAnagraficaCivile.objects
        .exclude(codice_fiscale="")
        .values_list("legacy_anagrafica_id", "codice_fiscale")
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Scadenze"

    header = ["Dipendente", "Codice Fiscale", "Tipo visita", "Data svolgimento",
              "Data scadenza", "Giorni a scadenza", "Esito", "Note"]
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E2E8F0")

    for v in qs:
        nome = nomi_map.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")
        cf = cf_map.get(v.legacy_anagrafica_id, "")
        giorni = (v.data_scadenza - oggi).days if v.data_scadenza else ""
        ws.append([
            nome, cf, v.tipo.nome,
            v.data_svolgimento.strftime("%d/%m/%Y") if v.data_svolgimento else "",
            v.data_scadenza.strftime("%d/%m/%Y") if v.data_scadenza else "",
            giorni,
            v.get_esito_display(),
            v.prescrizioni or "",
        ])

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            len(str(c.value or "")) for c in col
        ) + 4

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="visite_scadenze_{label}.xlsx"'
    wb.save(response)
    return response


@login_required
def visite_mediche_export_copertura(request):
    """Scarica la tabella copertura per tipologia come .xlsx."""
    if not _can_view_visite_mediche(request):
        return HttpResponse(status=403)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return HttpResponse("openpyxl non installato.", status=500)

    from django.utils import timezone as _tz

    oggi = _tz.localdate()

    _valide_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in VisitaMedica.objects
        .filter(data_scadenza__gte=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }
    _scadute_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in VisitaMedica.objects
        .filter(data_scadenza__lt=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }

    tipi = TipoVisitaMedica.objects.filter(is_active=True).prefetch_related("ruoli_operativi")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Copertura tipologie"

    header = ["Tipologia", "Periodicità (mesi)", "Obbligatoria",
              "Ruoli collegati", "Richiesti (ruoli)", "Coperti (ruoli)", "Mancanti (ruoli)",
              "Valide (DB)", "Scadute (DB)"]
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E2E8F0")

    for t in tipi:
        ruoli_ids = list(t.ruoli_operativi.values_list("id", flat=True))
        if ruoli_ids:
            legacy_ids_richiesti = set(
                DipendenteRuoloOperativo.objects
                .filter(ruolo_id__in=ruoli_ids)
                .values_list("legacy_anagrafica_id", flat=True)
            )
        else:
            legacy_ids_richiesti = set()
        legacy_ids_coperti = set(
            VisitaMedica.objects
            .filter(tipo=t, data_scadenza__gte=oggi)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        mancanti = legacy_ids_richiesti - legacy_ids_coperti
        ruoli_nomi = ", ".join(t.ruoli_operativi.values_list("nome", flat=True)) or "—"

        ws.append([
            t.nome, t.durata_mesi, "Sì" if t.obbligatoria else "No",
            ruoli_nomi,
            len(legacy_ids_richiesti),
            len(legacy_ids_richiesti & legacy_ids_coperti),
            len(mancanti),
            _valide_per_tipo.get(t.pk, 0),
            _scadute_per_tipo.get(t.pk, 0),
        ])

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            len(str(c.value or "")) for c in col
        ) + 4

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="visite_copertura_tipologie.xlsx"'
    wb.save(response)
    return response
