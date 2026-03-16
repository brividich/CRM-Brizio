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
    DipendenteRuoloOperativo,
    DipendenteStatLayout,
    Fornitore,
    FornitoreAsset,
    FornitoreDocumento,
    FornitoreOrdine,
    FornitoreValutazione,
    RuoloOperativo,
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

    # Costruisce lista widget con dati
    widget_map = {w["id"]: w for w in STAT_WIDGETS}
    widgets_visible = []
    widgets_hidden = []
    for wid in ordered:
        w = dict(widget_map[wid])
        w["count"] = widget_counts.get(wid, 0)
        # link timbri specifico per il dipendente
        if wid == "timbri" and int(dip.get("id") or 0):
            try:
                from django.urls import reverse
                w["link_url"] = reverse("timbri:operatore_detail_by_legacy", args=[int(dip["id"])])
            except Exception:
                pass
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
    return render(request, "anagrafica/pages/ruoli_operativi.html", {
        "ruoli": ruoli,
        "is_admin": is_admin,
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
