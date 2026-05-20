from __future__ import annotations

import csv
import json
import logging
from datetime import timedelta as _timedelta
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from core.legacy_anagrafica import (
    count_anagrafica_statuses,
    ensure_anagrafica_schema,
    fetch_anagrafica_rows,
    upsert_anagrafica_dipendente,
)
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.legacy_utils import is_legacy_admin, legacy_table_columns

from .forms import (
    AnagraficaAziendaleForm,
    AnagraficaCivileForm,
    DipendenteLegacyForm,
)
from .models import (
    AnagraficaHRPermission,
    AnagraficaStatPermission,
    AreaAziendale,
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    DipendenteCambiamentoOrganizzativo,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    DipendenteStatLayout,
    ImportazioneRetributiva,
    LivelloContrattuale,
    Mansione,
    RuoloAziendale,
    RuoloOperativo,
    StoricoContratto,
    TipologiaContratto,
    TipoQualifica,
    VoceRetributiva,
    _classify_pay_item,
)

logger = logging.getLogger(__name__)


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
    return render(request, "anagrafica/pages/dipendenti_list.html", {
        "page_obj": page,
        "q": q,
        "reparto": reparto,
        "area": area_filter,
        "tipologia_contratto": contratto_filter,
        "reparti": reparti_list,
        "aree": aree_list,
        "contratto_choices": DipendenteAnagraficaAziendale.CONTRATTO_CHOICES,
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
        form_civile = AnagraficaCivileForm(request.POST)
        form_aziendale = AnagraficaAziendaleForm(request.POST)

        # Le form civile/aziendale sono facoltative: ignora errori se tutti i campi sono vuoti
        civile_has_data = any(
            v for k, v in request.POST.items()
            if k not in ("csrfmiddlewaretoken",) and not k.startswith("az_") and not k.startswith("legacy_")
            and v and k in AnagraficaCivileForm().fields
        )
        aziendale_has_data = any(
            v for k, v in request.POST.items()
            if k not in ("csrfmiddlewaretoken",) and v and k in AnagraficaAziendaleForm().fields
        )

        if legacy_form.is_valid():
            data = legacy_form.cleaned_data
            try:
                row = upsert_anagrafica_dipendente(
                    aliasusername=(data.get("aliasusername") or "").strip(),
                    nome=(data.get("nome") or "").strip(),
                    cognome=(data.get("cognome") or "").strip(),
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
    })


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
    form = AnagraficaCivileForm(request.POST, instance=instance)
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

    # Logica di merge: una sola importazione CSV per mese (la più recente) + voci manuali del mese.
    # Le voci manuali fanno override delle voci CSV con lo stesso pay_item_key.
    _TOTALI_SORT = {"retribuzione di fatto": 0, "totale elementi variabili": 1, "rml": 2, "ral": 3}
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

    timeline = []
    for _date in sorted(_by_month.keys(), reverse=True):
        entry = _by_month[_date]
        _manuale_keys = {v.pay_item_key for v in entry["manuale_voci"]}
        _voci = [v for v in entry["csv_voci"] if v.pay_item_key not in _manuale_keys] + entry["manuale_voci"]
        _fissi = [v for v in _voci if v.categoria == "fisso"]
        _variabili = [v for v in _voci if v.categoria == "variabile"]
        _altri = [v for v in _voci if v.categoria == "altro"]
        _totali = sorted([v for v in _voci if v.categoria == "totale"],
                         key=lambda v: _TOTALI_SORT.get(v.pay_item_key, 99))
        _ral = next((v for v in _totali if v.pay_item_key == "ral"), None)
        timeline.append({
            "data_comp": _date,
            "importazione": entry["csv_imp"],
            "n_manuale": len(entry["manuale_voci"]),
            "fissi": _fissi,
            "variabili": _variabili,
            "altri": _altri,
            "totali": _totali,
            "ral": _ral,
            "n_changed": sum(1 for v in _voci if v.is_changed),
        })

    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)

    return render(request, "anagrafica/pages/dipendente_retribuzioni.html", {
        "dip": dip,
        "legacy_id": legacy_id,
        "timeline": timeline,
        "n_mesi": len(timeline),
        "can_hr": can_hr,
        "is_admin": is_admin,
        "tax_code_dipendente": civile_retr.codice_fiscale.strip().upper() if civile_retr and civile_retr.codice_fiscale else "",
        "categorie_voce": VoceRetributiva.CATEGORIA_CHOICES,
    })


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
    try:
        from core.legacy_models import Ruolo
        ruoli_acl = list(Ruolo.objects.order_by("nome"))
    except Exception:
        ruoli_acl = []

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
        # Permessi
        "stat_perm": stat_perm,
        "hr_perm": hr_perm,
        "ruoli_acl": ruoli_acl,
        "ACCESSO_TUTTI": AnagraficaStatPermission.ACCESSO_TUTTI,
        "ACCESSO_ADMIN": AnagraficaStatPermission.ACCESSO_ADMIN,
        "ACCESSO_RUOLI": AnagraficaStatPermission.ACCESSO_RUOLI,
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

    messages.success(request, "Permessi salvati.")
    return _redirect_impostazioni("permessi")
