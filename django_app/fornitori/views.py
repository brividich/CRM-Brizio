"""
Views per il modulo Anagrafica Fornitori.

I modelli `Fornitore`, `FornitoreDocumento`, `FornitoreOrdine`,
`FornitoreValutazione`, `FornitoreAsset` restano fisicamente in
`anagrafica.models` (tabelle DB invariate); questa app espone solo URL,
view, template e form dedicati per separare nettamente la UI fornitori
dall'anagrafica HR dei dipendenti.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from anagrafica.models import (
    Fornitore,
    FornitoreAsset,
    FornitoreDocumento,
    FornitoreOrdine,
    FornitoreValutazione,
)
from core.audit import log_action

from . import guestportal as gp
from . import ingressi as ing
from .forms import (
    FornitoreAssetForm,
    FornitoreDocumentoForm,
    FornitoreForm,
    FornitoreOrdineForm,
    FornitoreValutazioneForm,
)


# ---------------------------------------------------------------------------
# Dashboard fornitori
# ---------------------------------------------------------------------------

@login_required
def index(request):
    n_fornitori = Fornitore.objects.filter(is_active=True).count()
    n_fornitori_tutti = Fornitore.objects.count()
    n_fornitori_inattivi = n_fornitori_tutti - n_fornitori

    spesa_totale = FornitoreOrdine.objects.aggregate(t=Sum("importo"))["t"] or Decimal("0")
    n_ordini = FornitoreOrdine.objects.count()
    n_asset_assegnati = FornitoreAsset.objects.count()

    ultimi_fornitori = Fornitore.objects.order_by("-created_at")[:6]

    # Spesa per categoria — top 5
    spesa_per_categoria = (
        FornitoreOrdine.objects.values("fornitore__categoria")
        .annotate(totale=Sum("importo"), n=Count("id"))
        .order_by("-totale")[:5]
    )
    cat_labels = dict(Fornitore.CATEGORIA_CHOICES)
    spesa_categorie = [
        {
            "codice": row["fornitore__categoria"] or "",
            "label": cat_labels.get(row["fornitore__categoria"] or "", "Senza categoria"),
            "totale": row["totale"] or Decimal("0"),
            "n_ordini": row["n"],
        }
        for row in spesa_per_categoria
    ]

    return render(request, "fornitori/pages/index.html", {
        "n_fornitori": n_fornitori,
        "n_fornitori_tutti": n_fornitori_tutti,
        "n_fornitori_inattivi": n_fornitori_inattivi,
        "spesa_totale": spesa_totale,
        "n_ordini": n_ordini,
        "n_asset_assegnati": n_asset_assegnati,
        "ultimi_fornitori": ultimi_fornitori,
        "spesa_categorie": spesa_categorie,
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

    return render(request, "fornitori/pages/fornitori_list.html", {
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

    return render(request, "fornitori/pages/fornitore_detail.html", {
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


@login_required
def fornitore_documento_download(request, fornitore_id, doc_id):
    """Serve un documento fornitore dallo storage PRIVATO (mai da /media pubblico).

    SEC: i documenti (contratti, visure, certificazioni) sono salvati fuori webroot
    e cifrati at-rest; l'accesso al modulo fornitori è già imposto dal middleware ACL
    sul prefisso /fornitori/. Il file viene streammato come allegato.
    """
    import mimetypes
    from pathlib import Path as _Path

    from django.http import FileResponse, Http404

    from anagrafica.models import FornitoreDocumento

    doc = get_object_or_404(
        FornitoreDocumento.objects.select_related("fornitore"),
        pk=doc_id, fornitore_id=fornitore_id,
    )
    if not doc.file or not doc.file.name:
        raise Http404("Documento non disponibile.")
    try:
        fh = doc.file.open("rb")
    except Exception:
        log_action(request, "fornitore_doc_download", "fornitori",
                   {"doc_id": doc.id, "fornitore_id": fornitore_id, "esito": "not_found"})
        raise Http404("File non trovato.")

    filename = doc.nome or _Path(doc.file.name).name
    # Neutralizza " e CR/LF nel nome per non corrompere l'header Content-Disposition.
    safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "").strip() or "documento"
    content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    log_action(request, "fornitore_doc_download", "fornitori",
               {"doc_id": doc.id, "fornitore_id": fornitore_id, "esito": "success"})
    resp = FileResponse(fh, content_type=content_type)
    resp["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------------------------------------------------------------------------
# Fornitore — crea / modifica
# ---------------------------------------------------------------------------

@login_required
def fornitore_create(request):
    if request.method == "POST":
        form = FornitoreForm(request.POST)
        if form.is_valid():
            fornitore = form.save()
            log_action(request, "fornitore_creato", "fornitori", {"fornitore_id": fornitore.pk, "ragione_sociale": fornitore.ragione_sociale})
            messages.success(request, f'Fornitore "{fornitore.ragione_sociale}" creato.')
            return redirect("fornitori:fornitore_detail", fornitore_id=fornitore.pk)
    else:
        form = FornitoreForm()
    return render(request, "fornitori/pages/fornitore_form.html", {
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
            log_action(request, "fornitore_modificato", "fornitori", {"fornitore_id": fornitore.pk, "ragione_sociale": fornitore.ragione_sociale})
            messages.success(request, "Fornitore aggiornato.")
            return redirect("fornitori:fornitore_detail", fornitore_id=fornitore.pk)
    else:
        form = FornitoreForm(instance=fornitore)
    return render(request, "fornitori/pages/fornitore_form.html", {
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
    log_action(request, f"fornitore_{stato}", "fornitori", {"fornitore_id": fornitore.pk, "ragione_sociale": fornitore.ragione_sociale})
    messages.success(request, f'Fornitore "{fornitore.ragione_sociale}" {stato}.')
    return redirect("fornitori:fornitore_detail", fornitore_id=fornitore.pk)


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
        log_action(request, "fornitore_documento_caricato", "fornitori", {"fornitore_id": fornitore.pk, "doc_id": doc.pk, "nome": doc.nome})
        messages.success(request, f'Documento "{doc.nome}" caricato.')
    else:
        messages.error(request, "Errore nel caricamento: verifica i campi obbligatori.")
    return redirect("fornitori:fornitore_detail", fornitore_id=fornitore.pk)


@login_required
@require_POST
def fornitore_documento_delete(request, fornitore_id, doc_id):
    doc = get_object_or_404(FornitoreDocumento, pk=doc_id, fornitore_id=fornitore_id)
    nome = doc.nome
    doc.delete()
    log_action(request, "fornitore_documento_eliminato", "fornitori", {"fornitore_id": fornitore_id, "doc_id": doc_id, "nome": nome})
    messages.success(request, f'Documento "{nome}" eliminato.')
    return redirect("fornitori:fornitore_detail", fornitore_id=fornitore_id)


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
        log_action(request, "fornitore_ordine_aggiunto", "fornitori", {"fornitore_id": fornitore.pk, "ordine_id": ordine.pk})
        messages.success(request, "Ordine aggiunto.")
    else:
        messages.error(request, "Errore nel salvataggio dell'ordine.")
    return redirect("fornitori:fornitore_detail", fornitore_id=fornitore.pk)


@login_required
@require_POST
def fornitore_ordine_stato(request, fornitore_id, ordine_id):
    ordine = get_object_or_404(FornitoreOrdine, pk=ordine_id, fornitore_id=fornitore_id)
    nuovo_stato = request.POST.get("stato", "")
    stati_validi = dict(FornitoreOrdine.STATO_CHOICES)
    if nuovo_stato in stati_validi:
        ordine.stato = nuovo_stato
        ordine.save(update_fields=["stato", "updated_at"])
        log_action(request, "fornitore_ordine_stato_aggiornato", "fornitori", {"fornitore_id": fornitore_id, "ordine_id": ordine_id, "nuovo_stato": nuovo_stato})
        messages.success(request, f"Stato aggiornato: {stati_validi[nuovo_stato]}.")
    else:
        messages.error(request, "Stato non valido.")
    return redirect("fornitori:fornitore_detail", fornitore_id=fornitore_id)


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
        log_action(request, "fornitore_valutazione_aggiunta", "fornitori", {"fornitore_id": fornitore.pk, "valutazione_id": val.pk})
        messages.success(request, "Valutazione aggiunta.")
    else:
        messages.error(request, "Errore nel salvataggio della valutazione.")
    return redirect("fornitori:fornitore_detail", fornitore_id=fornitore.pk)


@login_required
@require_POST
def fornitore_valutazione_delete(request, fornitore_id, val_id):
    val = get_object_or_404(FornitoreValutazione, pk=val_id, fornitore_id=fornitore_id)
    val.delete()
    log_action(request, "fornitore_valutazione_eliminata", "fornitori", {"fornitore_id": fornitore_id, "valutazione_id": val_id})
    messages.success(request, "Valutazione eliminata.")
    return redirect("fornitori:fornitore_detail", fornitore_id=fornitore_id)


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
        log_action(request, "fornitore_asset_assegnato", "fornitori", {"fornitore_id": fornitore.pk, "asset_id": fa.asset_id})
        messages.success(request, f'Asset "{fa.asset}" assegnato al fornitore.')
    else:
        messages.error(request, "Errore nell'assegnazione dell'asset.")
    return redirect("fornitori:fornitore_detail", fornitore_id=fornitore.pk)


@login_required
@require_POST
def fornitore_asset_remove(request, fornitore_id, fa_id):
    fa = get_object_or_404(FornitoreAsset, pk=fa_id, fornitore_id=fornitore_id)
    nome = str(fa.asset)
    fa.delete()
    log_action(request, "fornitore_asset_rimosso", "fornitori", {"fornitore_id": fornitore_id, "fa_id": fa_id, "asset": nome})
    messages.success(request, f'Asset "{nome}" rimosso dal fornitore.')
    return redirect("fornitori:fornitore_detail", fornitore_id=fornitore_id)


# ---------------------------------------------------------------------------
# Accessi esterni (GuestPortal, sola lettura) e apertura pannello con SSO
# ---------------------------------------------------------------------------

def _data_param(valore, default: date) -> date:
    try:
        return date.fromisoformat((valore or "").strip())
    except ValueError:
        return default


@login_required
def accessi_esterni(request):
    """Visitatori, fornitori e consulenti registrati al GuestPortal: chi è presente
    ora e lo storico del periodo. Lettura diretta, nessuna copia nell'HUB."""
    oggi = timezone.localdate()
    dal = _data_param(request.GET.get("dal"), oggi - timedelta(days=6))
    al = _data_param(request.GET.get("al"), oggi)
    if al < dal:
        dal, al = al, dal
    testo = request.GET.get("q", "").strip()[:80]
    tipo = request.GET.get("tipo", "").strip()
    if tipo not in gp.TIPI:
        tipo = ""

    configurato = gp.db_configurato()
    presenti: list = []
    righe: list = []
    troncato = False
    errore = ""
    if configurato:
        try:
            presenti = gp.presenti_ora()
            righe, troncato = gp.storico(dal=dal, al=al, testo=testo, tipo=tipo)
        except gp.GuestPortalNonConfigurato:
            configurato = False
        except gp.GuestPortalNonRaggiungibile:
            errore = "Il database del GuestPortal non risponde: riprova tra poco o avvisa l'IT."

    # Collega l'azienda dell'esterno alla scheda fornitore: abbinamento ditta
    # GuestPortal → fornitore HUB, altrimenti stessa ragione sociale.
    from .models import DittaGuestPortal

    per_ditta = dict(DittaGuestPortal.objects.values_list("ditta_gp_id", "fornitore_id"))
    nomi = {a.azienda.strip().lower() for a in presenti + righe if a.azienda}
    fornitori_per_nome: dict[str, int] = {}
    if nomi:
        for pk, rs in Fornitore.objects.filter(is_active=True).values_list("pk", "ragione_sociale"):
            chiave = (rs or "").strip().lower()
            if chiave in nomi:
                fornitori_per_nome.setdefault(chiave, pk)
    collegati = ing.interventi_per_visite([a.visita_id for a in presenti + righe])
    for accesso in presenti + righe:
        accesso.fornitore_id = per_ditta.get(accesso.ditta_gp_id) or fornitori_per_nome.get(accesso.azienda.strip().lower())
        accesso.interventi = collegati.get(accesso.visita_id, [])

    return render(request, "fornitori/pages/accessi_esterni.html", {
        "dal": dal,
        "al": al,
        "q": testo,
        "tipo": tipo,
        "tipi": list(gp.TIPI.items()),
        "configurato": configurato,
        "presenti": presenti,
        "storico": righe,
        "troncato": troncato,
        "limite": gp.STORICO_MAX_RIGHE,
        "errore": errore,
        "sso_attivo": gp.sso_configurato(),
    })


@login_required
def guestportal_apri(request):
    """Apre il pannello admin del GuestPortal già autenticato (token firmato, 60 s,
    uso singolo). Senza SSO configurato porta al login normale del pannello."""
    if gp.sso_configurato():
        try:
            token = gp.firma_token(request.user.get_username())
        except (gp.GuestPortalNonConfigurato, ValueError):
            token = ""
        if token:
            log_action(request, "guestportal_sso", "fornitori", {"esito": "token_emesso"})
            risposta = HttpResponseRedirect(f"{gp.sso_url()}?{urlencode({'t': token})}")
            risposta["Cache-Control"] = "no-store"
            risposta["Referrer-Policy"] = "no-referrer"
            return risposta
    url = gp.admin_url()
    if not url:
        messages.error(request, "Indirizzo del GuestPortal non configurato (GUESTPORTAL_ADMIN_URL).")
        return redirect("fornitori:accessi_esterni")
    return HttpResponseRedirect(url)


# ---------------------------------------------------------------------------
# Presenze in azienda: ingressi GuestPortal collegati a ticket e OdL
# (riquadro HTMX nelle pagine ticket/OdL; il permesso si verifica qui, sulla
# regola della pagina che lo ospita)
# ---------------------------------------------------------------------------

def _puo_presenze(request, iv, *, modifica: bool) -> bool:
    if iv.tipo == ing.TIPO_TICKET:
        from tickets.services.accesso import utente_puo_gestire_ticket

        return utente_puo_gestire_ticket(request, iv.oggetto)
    from django.urls import reverse

    from core.middleware import acl_allows_path

    vede = acl_allows_path(
        reverse("assets:wo_view", args=[iv.pk]), django_user=request.user,
        legacy_user=getattr(request, "legacy_user", None), request=request,
    )
    if not vede or not modifica:
        return vede
    from assets.views_maintenance import can_execute_maintenance

    return bool(can_execute_maintenance(request))


def _render_presenze(request, iv, *, esito: str = "", errore: str = "", status: int = 200):
    giorno_txt = (request.POST.get("giorno") or request.GET.get("giorno") or "").strip()
    giorno = _data_param(giorno_txt, None) if giorno_txt else None
    puo_modificare = _puo_presenze(request, iv, modifica=True) and not iv.chiuso
    configurato = gp.db_configurato()
    proposte: list = []
    del_giorno: list = []
    errore_gp = ""
    if configurato:
        try:
            ing.aggiorna_uscite(iv)
            if puo_modificare:
                proposte = ing.proposte(iv)
                if giorno:
                    del_giorno = ing.ingressi_del_giorno(iv, giorno)
        except gp.GuestPortalNonConfigurato:
            configurato = False
        except gp.GuestPortalNonRaggiungibile:
            errore_gp = "Il GuestPortal non risponde: proposte non disponibili, i collegamenti già fatti restano."
    collegamenti = list(iv.collegamenti())
    confronto = ing.confronto_ore(iv, collegamenti)
    return render(request, "fornitori/components/presenze_intervento.html", {
        "iv": iv,
        "collegamenti": collegamenti,
        "confronto": confronto,
        "presenza_label": ing.ore_label(confronto.presenza_minuti),
        "dichiarate_label": ing.ore_label(confronto.dichiarate_minuti) if confronto.dichiarate_minuti is not None else "",
        "proposte": proposte,
        "del_giorno": del_giorno,
        "giorno": giorno,
        "configurato": configurato,
        "puo_modificare": puo_modificare,
        "errore_gp": errore_gp,
        "esito": esito,
        "errore": errore,
        "dal_al": iv.finestra(),
    }, status=status)


def _intervento_o_404(tipo: str, pk: int):
    from django.http import Http404

    iv = ing.intervento(tipo, pk)
    if iv is None:
        raise Http404("Intervento non trovato")
    return iv


@login_required
def presenze_intervento(request, tipo, pk):
    iv = _intervento_o_404(tipo, pk)
    if not _puo_presenze(request, iv, modifica=False):
        return HttpResponseForbidden("Permesso negato")
    return _render_presenze(request, iv)


@login_required
@require_POST
def presenze_collega(request, tipo, pk):
    iv = _intervento_o_404(tipo, pk)
    if not _puo_presenze(request, iv, modifica=True):
        return HttpResponseForbidden("Permesso negato")
    try:
        visita_id = int(request.POST.get("visita_id") or 0)
    except ValueError:
        visita_id = 0
    if not visita_id:
        return _render_presenze(request, iv, errore="Ingresso non indicato.", status=400)
    try:
        link = ing.collega(iv, visita_id, utente=request.user, modo=request.POST.get("modo", ""))
    except ing.CollegamentoNonValido as exc:
        return _render_presenze(request, iv, errore=str(exc))
    except (gp.GuestPortalNonConfigurato, gp.GuestPortalNonRaggiungibile):
        return _render_presenze(request, iv, errore="Il GuestPortal non risponde: riprova tra poco.")
    log_action(request, "ingresso_esterno_collegato", "fornitori",
               {"intervento": f"{iv.tipo}:{iv.pk}", "visita_gp_id": link.visita_gp_id, "modo": link.modo})
    return _render_presenze(request, iv, esito=f"Ingresso del {timezone.localtime(link.ingresso):%d/%m/%Y %H:%M} collegato." if link.ingresso else "Ingresso collegato.")


@login_required
@require_POST
def presenze_scollega(request, link_id):
    from .models import IngressoIntervento

    link = get_object_or_404(IngressoIntervento, pk=link_id)
    iv = ing.Intervento(ing.TIPO_TICKET, link.ticket) if link.ticket_id else ing.Intervento(ing.TIPO_ODL, link.work_order)
    if not _puo_presenze(request, iv, modifica=True) or iv.chiuso:
        return HttpResponseForbidden("Permesso negato")
    log_action(request, "ingresso_esterno_scollegato", "fornitori",
               {"intervento": f"{iv.tipo}:{iv.pk}", "visita_gp_id": link.visita_gp_id})
    link.delete()
    return _render_presenze(request, iv, esito="Collegamento tolto.")


# ---------------------------------------------------------------------------
# Ditte GuestPortal ↔ fornitori HUB (abbinamento una tantum)
# ---------------------------------------------------------------------------

@login_required
def guestportal_ditte(request):
    from .models import DittaGuestPortal

    if request.method == "POST":
        try:
            ditta_gp_id = int(request.POST.get("ditta_gp_id") or 0)
        except ValueError:
            ditta_gp_id = 0
        fornitore_id = (request.POST.get("fornitore_id") or "").strip()
        nome_gp = (request.POST.get("ditta_gp_nome") or "").strip()[:200]
        if ditta_gp_id:
            if fornitore_id:
                fornitore = get_object_or_404(Fornitore, pk=fornitore_id)
                DittaGuestPortal.objects.update_or_create(
                    ditta_gp_id=ditta_gp_id,
                    defaults={"fornitore": fornitore, "ditta_gp_nome": nome_gp or str(ditta_gp_id),
                              "creato_da": request.user},
                )
                messages.success(request, f"«{nome_gp}» abbinata a «{fornitore.ragione_sociale}».")
            else:
                DittaGuestPortal.objects.filter(ditta_gp_id=ditta_gp_id).delete()
                messages.success(request, f"Abbinamento di «{nome_gp}» tolto.")
            log_action(request, "guestportal_ditta_abbinata", "fornitori",
                       {"ditta_gp_id": ditta_gp_id, "fornitore_id": fornitore_id or None})
        return redirect("fornitori:guestportal_ditte")

    configurato = gp.db_configurato()
    ditte: list = []
    errore = ""
    if configurato:
        try:
            ditte = gp.ditte_guestportal()
        except gp.GuestPortalNonConfigurato:
            configurato = False
        except gp.GuestPortalNonRaggiungibile:
            errore = "Il database del GuestPortal non risponde: riprova tra poco o avvisa l'IT."
    abbinate = {d.ditta_gp_id: d for d in DittaGuestPortal.objects.select_related("fornitore")}
    fornitori = list(Fornitore.objects.filter(is_active=True).order_by("ragione_sociale").values_list("pk", "ragione_sociale"))
    per_nome = {(rs or "").strip().lower(): pk for pk, rs in fornitori}
    righe = []
    for ditta_id, nome in ditte:
        abb = abbinate.get(ditta_id)
        righe.append({
            "id": ditta_id,
            "nome": nome,
            "abbinata": abb,
            "suggerito": None if abb else per_nome.get(nome.strip().lower()),
        })
    return render(request, "fornitori/pages/guestportal_ditte.html", {
        "configurato": configurato,
        "errore": errore,
        "righe": righe,
        "fornitori": fornitori,
        "n_abbinate": sum(1 for r in righe if r["abbinata"]),
    })
