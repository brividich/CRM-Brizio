from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
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
    DipendenteLegacyForm,
    FornitoreAssetForm,
    FornitoreDocumentoForm,
    FornitoreForm,
    FornitoreOrdineForm,
    FornitoreValutazioneForm,
)
from .models import (
    AnagraficaStatPermission,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    DipendenteStatLayout,
    Fornitore,
    FornitoreAsset,
    FornitoreDocumento,
    FornitoreOrdine,
    FornitoreValutazione,
    Mansione,
    RuoloOperativo,
    TipoQualifica,
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

    n_fornitori = Fornitore.objects.filter(is_active=True).count()
    n_fornitori_tutti = Fornitore.objects.count()
    n_fornitori_inattivi = n_fornitori_tutti - n_fornitori

    spesa_totale = FornitoreOrdine.objects.aggregate(t=Sum("importo"))["t"] or Decimal("0")
    n_ordini = FornitoreOrdine.objects.count()
    n_asset_assegnati = FornitoreAsset.objects.count()

    ultimi_fornitori = Fornitore.objects.order_by("-created_at")[:6]
    return render(request, "anagrafica/pages/index.html", {
        "n_dipendenti": n_dipendenti,
        "n_reparti": n_reparti,
        "n_fornitori": n_fornitori,
        "n_fornitori_tutti": n_fornitori_tutti,
        "n_fornitori_inattivi": n_fornitori_inattivi,
        "spesa_totale": spesa_totale,
        "n_ordini": n_ordini,
        "n_asset_assegnati": n_asset_assegnati,
        "ultimi_fornitori": ultimi_fornitori,
    })


# ---------------------------------------------------------------------------
# Dipendenti (sola lettura — dati da legacy SQL Server)
# ---------------------------------------------------------------------------

@login_required
def dipendenti_list(request):
    ensure_anagrafica_schema()
    if request.method == "POST":
        form = DipendenteLegacyForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
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
                    detach_account=not bool(data.get("attivo")),
                )
                stato = "attivo" if bool(row.get("attivo", 1)) else "non attivo"
                messages.success(request, f"Dipendente salvato in anagrafica ({stato}).")
                return redirect("anagrafica:dipendenti_list")
            except Exception as exc:
                logger.exception("Errore salvataggio dipendente anagrafica")
                messages.error(request, f"Impossibile salvare il dipendente: {exc}")
    else:
        form = DipendenteLegacyForm(initial={"attivo": True})

    q = request.GET.get("q", "").strip()
    reparto = request.GET.get("reparto", "").strip()

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
        "create_form": form,
        "page_obj": page,
        "q": q,
        "reparto": reparto,
        "reparti": reparti_list,
        "n_totale": n_totale,
        "n_reparti": len(reparti_list),
        "n_attivi": status_stats["active"],
        "n_non_attivi": status_stats["inactive"],
    })


# ---------------------------------------------------------------------------
# Fornitori — lista con stats
# ---------------------------------------------------------------------------

@login_required
def fornitori_list(request):
    q = request.GET.get("q", "").strip()
    categoria = request.GET.get("categoria", "").strip()
    solo_attivi = request.GET.get("attivi", "1") == "1"

    qs = Fornitore.objects.all()
    if solo_attivi:
        qs = qs.filter(is_active=True)
    if q:
        qs = qs.filter(
            Q(ragione_sociale__icontains=q)
            | Q(piva__icontains=q)
            | Q(citta__icontains=q)
        )
    if categoria:
        qs = qs.filter(categoria=categoria)

    stats = Fornitore.objects.aggregate(
        totale=Count("id"),
        attivi=Count("id", filter=Q(is_active=True)),
    )
    spesa_totale = FornitoreOrdine.objects.aggregate(s=Sum("importo"))["s"] or Decimal("0")

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "anagrafica/pages/fornitori_list.html", {
        "page_obj": page,
        "q": q,
        "categoria": categoria,
        "solo_attivi": solo_attivi,
        "categoria_choices": Fornitore.CATEGORIA_CHOICES,
        "stats_totale": stats["totale"],
        "stats_attivi": stats["attivi"],
        "spesa_totale": spesa_totale,
    })


# ---------------------------------------------------------------------------
# Fornitore — scheda dettaglio
# ---------------------------------------------------------------------------

@login_required
def fornitore_detail(request, fornitore_id):
    fornitore = get_object_or_404(Fornitore, pk=fornitore_id)
    ordini = fornitore.ordini.all()
    valutazioni = fornitore.valutazioni.all()
    documenti = fornitore.documenti.all()
    asset_assegnati = fornitore.asset_assegnati.select_related("asset", "created_by").all()
    spesa = ordini.aggregate(t=Sum("importo"))["t"] or Decimal("0")

    return render(request, "anagrafica/pages/fornitore_detail.html", {
        "fornitore": fornitore,
        "documenti": documenti,
        "ordini": ordini,
        "valutazioni": valutazioni,
        "asset_assegnati": asset_assegnati,
        "spesa_totale": spesa,
        "doc_form": FornitoreDocumentoForm(),
        "ordine_form": FornitoreOrdineForm(),
        "valutazione_form": FornitoreValutazioneForm(),
        "asset_form": FornitoreAssetForm(fornitore=fornitore),
    })


# ---------------------------------------------------------------------------
# Fornitore — crea / modifica
# ---------------------------------------------------------------------------

@login_required
def fornitore_create(request):
    if request.method == "POST":
        form = FornitoreForm(request.POST)
        if form.is_valid():
            fornitore = form.save()
            messages.success(request, f'Fornitore "{fornitore.ragione_sociale}" creato.')
            return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore.pk)
    else:
        form = FornitoreForm()
    return render(request, "anagrafica/pages/fornitore_form.html", {
        "form": form,
        "form_title": "Nuovo fornitore",
    })


@login_required
def fornitore_edit(request, fornitore_id):
    fornitore = get_object_or_404(Fornitore, pk=fornitore_id)
    if request.method == "POST":
        form = FornitoreForm(request.POST, instance=fornitore)
        if form.is_valid():
            form.save()
            messages.success(request, "Fornitore aggiornato.")
            return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore.pk)
    else:
        form = FornitoreForm(instance=fornitore)
    return render(request, "anagrafica/pages/fornitore_form.html", {
        "form": form,
        "fornitore": fornitore,
        "form_title": f"Modifica — {fornitore.ragione_sociale}",
    })


@login_required
@require_POST
def fornitore_toggle_active(request, fornitore_id):
    fornitore = get_object_or_404(Fornitore, pk=fornitore_id)
    fornitore.is_active = not fornitore.is_active
    fornitore.save(update_fields=["is_active", "updated_at"])
    stato = "attivato" if fornitore.is_active else "disattivato"
    messages.success(request, f'Fornitore "{fornitore.ragione_sociale}" {stato}.')
    return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore.pk)


# ---------------------------------------------------------------------------
# Documenti
# ---------------------------------------------------------------------------

@login_required
@require_POST
def fornitore_documento_add(request, fornitore_id):
    fornitore = get_object_or_404(Fornitore, pk=fornitore_id)
    form = FornitoreDocumentoForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.fornitore = fornitore
        doc.uploaded_by = request.user
        doc.save()
        messages.success(request, f'Documento "{doc.nome}" caricato.')
    else:
        messages.error(request, "Errore nel caricamento: verifica i campi obbligatori.")
    return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore.pk)


@login_required
@require_POST
def fornitore_documento_delete(request, fornitore_id, doc_id):
    doc = get_object_or_404(FornitoreDocumento, pk=doc_id, fornitore_id=fornitore_id)
    nome = doc.nome
    doc.delete()
    messages.success(request, f'Documento "{nome}" eliminato.')
    return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore_id)


# ---------------------------------------------------------------------------
# Ordini
# ---------------------------------------------------------------------------

@login_required
@require_POST
def fornitore_ordine_add(request, fornitore_id):
    fornitore = get_object_or_404(Fornitore, pk=fornitore_id)
    form = FornitoreOrdineForm(request.POST)
    if form.is_valid():
        ordine = form.save(commit=False)
        ordine.fornitore = fornitore
        ordine.created_by = request.user
        ordine.save()
        messages.success(request, "Ordine aggiunto.")
    else:
        messages.error(request, "Errore nel salvataggio dell'ordine.")
    return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore.pk)


@login_required
@require_POST
def fornitore_ordine_stato(request, fornitore_id, ordine_id):
    ordine = get_object_or_404(FornitoreOrdine, pk=ordine_id, fornitore_id=fornitore_id)
    nuovo_stato = request.POST.get("stato", "")
    stati_validi = dict(FornitoreOrdine.STATO_CHOICES)
    if nuovo_stato in stati_validi:
        ordine.stato = nuovo_stato
        ordine.save(update_fields=["stato", "updated_at"])
        messages.success(request, f"Stato aggiornato: {stati_validi[nuovo_stato]}.")
    else:
        messages.error(request, "Stato non valido.")
    return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore_id)


# ---------------------------------------------------------------------------
# Valutazioni
# ---------------------------------------------------------------------------

@login_required
@require_POST
def fornitore_valutazione_add(request, fornitore_id):
    fornitore = get_object_or_404(Fornitore, pk=fornitore_id)
    form = FornitoreValutazioneForm(request.POST)
    if form.is_valid():
        val = form.save(commit=False)
        val.fornitore = fornitore
        val.valutato_da = request.user
        val.save()
        messages.success(request, "Valutazione aggiunta.")
    else:
        messages.error(request, "Errore nel salvataggio della valutazione.")
    return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore.pk)


@login_required
@require_POST
def fornitore_valutazione_delete(request, fornitore_id, val_id):
    val = get_object_or_404(FornitoreValutazione, pk=val_id, fornitore_id=fornitore_id)
    val.delete()
    messages.success(request, "Valutazione eliminata.")
    return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore_id)


# ---------------------------------------------------------------------------
# Asset assegnati al fornitore
# ---------------------------------------------------------------------------

@login_required
@require_POST
def fornitore_asset_add(request, fornitore_id):
    fornitore = get_object_or_404(Fornitore, pk=fornitore_id)
    form = FornitoreAssetForm(request.POST, fornitore=fornitore)
    if form.is_valid():
        fa = form.save(commit=False)
        fa.fornitore = fornitore
        fa.created_by = request.user
        fa.save()
        messages.success(request, f'Asset "{fa.asset}" assegnato al fornitore.')
    else:
        messages.error(request, "Errore nell'assegnazione dell'asset.")
    return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore.pk)


@login_required
@require_POST
def fornitore_asset_remove(request, fornitore_id, fa_id):
    fa = get_object_or_404(FornitoreAsset, pk=fa_id, fornitore_id=fornitore_id)
    nome = str(fa.asset)
    fa.delete()
    messages.success(request, f'Asset "{nome}" rimosso dal fornitore.')
    return redirect("anagrafica:fornitore_detail", fornitore_id=fornitore_id)


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

    return render(request, "anagrafica/pages/dipendente_detail.html", {
        "dip": dip,
        "legacy_id": legacy_id,
        "can_stats": can_stats,
        "is_admin": is_admin,
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
        return redirect("anagrafica:ruoli_operativi_list")

    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del ruolo è obbligatorio.")
        return redirect("anagrafica:ruoli_operativi_list")

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
    return redirect("anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ruolo_operativo_edit(request, ruolo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare ruoli operativi.")
        return redirect("anagrafica:ruoli_operativi_list")

    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del ruolo è obbligatorio.")
        return redirect("anagrafica:ruoli_operativi_list")

    ruolo.nome = nome
    ruolo.descrizione = (request.POST.get("descrizione") or "").strip()
    ruolo.colore = (request.POST.get("colore") or "#64748b").strip()[:7]
    ruolo.icona = (request.POST.get("icona") or "").strip()[:10]
    ruolo.is_active = request.POST.get("is_active") == "1"
    ruolo.save()
    messages.success(request, f'Ruolo "{ruolo.nome}" aggiornato.')
    return redirect("anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ruolo_operativo_delete(request, ruolo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare ruoli operativi.")
        return redirect("anagrafica:ruoli_operativi_list")

    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id)
    nome = ruolo.nome
    ruolo.delete()
    messages.success(request, f'Ruolo "{nome}" eliminato.')
    return redirect("anagrafica:ruoli_operativi_list")


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
        messages.success(request, f'Mansione aggiornata a "{mansione_nome}".' if mansione_nome else "Mansione rimossa.")
    except Exception:
        logger.exception("Errore aggiornamento mansione dipendente %s", legacy_id)
        messages.error(request, "Errore durante l'aggiornamento della mansione.")
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
        return redirect("anagrafica:mansioni_list")

    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome della mansione è obbligatorio.")
        return redirect("anagrafica:mansioni_list")

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
    return redirect("anagrafica:mansioni_list")


@login_required
@require_POST
def mansione_edit(request, mansione_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare mansioni.")
        return redirect("anagrafica:mansioni_list")

    mansione = get_object_or_404(Mansione, pk=mansione_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome della mansione è obbligatorio.")
        return redirect("anagrafica:mansioni_list")

    mansione.nome = nome
    mansione.categoria = (request.POST.get("categoria") or "").strip()[:20]
    mansione.descrizione = (request.POST.get("descrizione") or "").strip()
    mansione.colore = (request.POST.get("colore") or "#64748b").strip()[:7]
    mansione.is_active = request.POST.get("is_active") == "1"
    mansione.save()
    messages.success(request, f'Mansione "{mansione.nome}" aggiornata.')
    return redirect("anagrafica:mansioni_list")


@login_required
@require_POST
def mansione_delete(request, mansione_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare mansioni.")
        return redirect("anagrafica:mansioni_list")

    mansione = get_object_or_404(Mansione, pk=mansione_id)
    nome = mansione.nome
    mansione.delete()
    messages.success(request, f'Mansione "{nome}" eliminata.')
    return redirect("anagrafica:mansioni_list")


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
        return redirect("anagrafica:qualifiche_list")

    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della qualifica è obbligatorio.")
        return redirect("anagrafica:qualifiche_list")

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
    return redirect("anagrafica:qualifiche_list")


@login_required
@require_POST
def tipo_qualifica_edit(request, tipo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare tipi di qualifica.")
        return redirect("anagrafica:qualifiche_list")

    tipo = get_object_or_404(TipoQualifica, pk=tipo_id)
    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della qualifica è obbligatorio.")
        return redirect("anagrafica:qualifiche_list")

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
    return redirect("anagrafica:qualifiche_list")


@login_required
@require_POST
def tipo_qualifica_delete(request, tipo_id: int):
    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare tipi di qualifica.")
        return redirect("anagrafica:qualifiche_list")

    tipo = get_object_or_404(TipoQualifica, pk=tipo_id)
    if tipo.assegnazioni.exists():
        messages.error(request, f'"{tipo.nome}" ha assegnazioni attive — non eliminabile.')
        return redirect("anagrafica:qualifiche_list")

    nome = tipo.nome
    tipo.delete()
    messages.success(request, f'Tipo qualifica "{nome}" eliminato.')
    return redirect("anagrafica:qualifiche_list")
