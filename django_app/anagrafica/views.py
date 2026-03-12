from __future__ import annotations

import logging
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
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
from core.legacy_utils import legacy_table_columns

from .forms import (
    DipendenteLegacyForm,
    FornitoreAssetForm,
    FornitoreDocumentoForm,
    FornitoreForm,
    FornitoreOrdineForm,
    FornitoreValutazioneForm,
)
from .models import Fornitore, FornitoreAsset, FornitoreDocumento, FornitoreOrdine, FornitoreValutazione

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
