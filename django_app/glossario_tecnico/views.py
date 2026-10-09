"""Viste del Glossario tecnico (SSR + HTMX).

Autorizzazione server-side: binding ACL delle route (middleware) più controllo
esplicito del permesso in ogni view, fail-closed. Consultazione per tutti gli
utenti autenticati con il permesso di lettura; gestione (inserire, modificare,
validare, decidere le proposte AI) solo con ``glossario_tecnico.gestione``. Le API
rispondono sempre JSON (401/403 compresi).
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.db.models.functions import Lower
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_action

from . import services
from .acl_bootstrap import PERM_GESTIONE, PERM_VIEW
from .chiave import normalizza_chiave
from .forms import PropostaForm, TermineForm, VarianteForm
from .models import Termine, Variante

logger = logging.getLogger(__name__)
MODULE = "glossario_tecnico"


def _has_perm(request, code: str) -> bool:
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        return bool(evaluate_permission_code_access(
            permission_code=code, legacy_user=legacy_user, django_user=request.user,
        ).get("allowed"))
    except Exception:
        logger.warning("glossario_tecnico: valutazione permesso %s fallita", code, exc_info=True)
        return bool(getattr(request, "user", None) and request.user.is_superuser)


def _nega(request, testo: str = "Non hai i permessi per questa operazione."):
    messages.error(request, testo)
    return redirect("glossario_tecnico:index" if _has_perm(request, PERM_VIEW) else "dashboard:dashboard")


def _json_nega(request):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Autenticazione richiesta."}, status=401)
    return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)


def _filtra(qs, q: str):
    q = (q or "").strip()
    if not q:
        return qs
    chiave = normalizza_chiave(q)
    return qs.filter(
        Q(termine__icontains=q) | Q(termine_en__icontains=q) | Q(simbolo=q)
        | Q(varianti__chiave__icontains=chiave) | Q(varianti__testo__icontains=q)
    ).distinct()


# ── Consultazione ────────────────────────────────────────────────────────────


@login_required
def index(request):
    if not _has_perm(request, PERM_VIEW):
        return _nega(request, "Non hai accesso al glossario tecnico.")
    categoria = request.GET.get("categoria", "")
    stato = request.GET.get("stato", "attivi")
    q = request.GET.get("q", "")
    qs = Termine.objects.all()
    if categoria in dict(Termine.CATEGORIE):
        qs = qs.filter(categoria=categoria)
    if stato in dict(Termine.STATI):
        qs = qs.filter(stato=stato)
    elif stato != "tutti":
        qs = qs.exclude(stato=Termine.DEPRECATO)
    qs = _filtra(qs, q).prefetch_related(Prefetch("varianti", queryset=Variante.objects.order_by("tipo", "testo")))
    pagina = Paginator(qs.order_by(Lower("termine"), "termine"), 50).get_page(request.GET.get("page"))
    conteggi = dict(Termine.objects.values_list("stato").annotate(n=Count("id")).order_by())
    puo_gestire = _has_perm(request, PERM_GESTIONE)
    return render(request, "glossario_tecnico/pages/index.html", {
        "page_title": "Glossario tecnico",
        "pagina": pagina,
        "categorie": Termine.CATEGORIE,
        "categoria": categoria,
        "stato": stato,
        "q": q,
        "conteggi": conteggi,
        "puo_gestire": puo_gestire,
        "proposte_in_attesa": services.proposte_in_attesa().count() if puo_gestire else 0,
    })


@login_required
def guida(request):
    """Guida d'uso: consultazione per tutti, lavoro di revisione per chi gestisce."""
    if not _has_perm(request, PERM_VIEW):
        return _nega(request, "Non hai accesso al glossario tecnico.")
    return render(request, "glossario_tecnico/pages/guida.html", {
        "page_title": "Glossario — guida",
        "puo_gestire": _has_perm(request, PERM_GESTIONE),
        "categorie": Termine.CATEGORIE,
        "tipi_variante": Variante.TIPI,
        "soglia_comune": round(services.SOGLIA_PAROLA_COMUNE * 100),
    })


@login_required
def termine(request, pk: int):
    if not _has_perm(request, PERM_VIEW):
        return _nega(request, "Non hai accesso al glossario tecnico.")
    obj = get_object_or_404(Termine.objects.select_related("validato_da"), pk=pk)
    puo_gestire = _has_perm(request, PERM_GESTIONE)
    return render(request, "glossario_tecnico/pages/termine.html", {
        "page_title": obj.termine,
        "t": obj,
        "varianti": obj.varianti.order_by("tipo", "testo"),
        "puo_gestire": puo_gestire,
        "variante_form": VarianteForm() if puo_gestire else None,
    })


def api_cerca(request):
    """GET ``?q=``: termini (non deprecati) che combaciano per termine o variante."""
    if not request.user.is_authenticated or not _has_perm(request, PERM_VIEW):
        return _json_nega(request)
    q = (request.GET.get("q") or "").strip()[:100]
    risultati = []
    if q:
        qs = _filtra(Termine.objects.exclude(stato=Termine.DEPRECATO), q).order_by("termine")[:20]
        risultati = [
            {"id": t.pk, "termine": t.termine, "termine_en": t.termine_en, "categoria": t.categoria,
             "simbolo": t.simbolo, "stato": t.stato}
            for t in qs
        ]
    return JsonResponse({"ok": True, "q": q, "risultati": risultati})


# ── Gestione ─────────────────────────────────────────────────────────────────


@login_required
def termine_nuovo(request):
    if not _has_perm(request, PERM_GESTIONE):
        return _nega(request)
    form = TermineForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.fonte = "manuale"
        obj.stato = Termine.BOZZA
        obj.save()
        log_action(request, "glossario_termine_creato", MODULE, {"termine": obj.termine}, oggetto=obj)
        messages.success(request, f"Termine «{obj.termine}» creato in bozza.")
        return redirect("glossario_tecnico:termine", pk=obj.pk)
    return render(request, "glossario_tecnico/pages/termine_form.html", {
        "page_title": "Nuovo termine", "form": form, "t": None,
    })


@login_required
def termine_modifica(request, pk: int):
    if not _has_perm(request, PERM_GESTIONE):
        return _nega(request)
    obj = get_object_or_404(Termine, pk=pk)
    form = TermineForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        log_action(request, "glossario_termine_modificato", MODULE,
                   {"termine": obj.termine, "campi": form.changed_data}, oggetto=obj)
        messages.success(request, "Termine aggiornato.")
        return redirect("glossario_tecnico:termine", pk=obj.pk)
    return render(request, "glossario_tecnico/pages/termine_form.html", {
        "page_title": f"Modifica {obj.termine}", "form": form, "t": obj,
    })


def _varianti_partial(request, obj, form=None, errore: str = ""):
    return render(request, "glossario_tecnico/partials/_varianti.html", {
        "t": obj, "varianti": obj.varianti.order_by("tipo", "testo"), "puo_gestire": True,
        "variante_form": form or VarianteForm(), "errore": errore,
    })


@login_required
@require_POST
def variante_aggiungi(request, pk: int):
    if not _has_perm(request, PERM_GESTIONE):
        return _json_nega(request)
    obj = get_object_or_404(Termine, pk=pk)
    form = VarianteForm(request.POST, instance=Variante(termine=obj))
    if form.is_valid():
        variante = form.save()
        log_action(request, "glossario_variante_aggiunta", MODULE,
                   {"termine": obj.termine, "variante": variante.testo, "tipo": variante.tipo}, oggetto=obj)
        return _varianti_partial(request, obj)
    return _varianti_partial(request, obj, form=form)


@login_required
@require_POST
def variante_elimina(request, pk: int):
    if not _has_perm(request, PERM_GESTIONE):
        return _json_nega(request)
    variante = get_object_or_404(Variante.objects.select_related("termine"), pk=pk)
    obj = variante.termine
    log_action(request, "glossario_variante_eliminata", MODULE,
               {"termine": obj.termine, "variante": variante.testo}, oggetto=obj)
    variante.delete()
    return _varianti_partial(request, obj)


@login_required
def revisione(request):
    """Coda di revisione: bozze da validare e proposte AI in attesa."""
    if not _has_perm(request, PERM_GESTIONE):
        return _nega(request)
    bozze = (Termine.objects.filter(stato=Termine.BOZZA)
             .prefetch_related("varianti").order_by("categoria", "termine"))
    etichette = dict(Termine.CATEGORIE)
    proposte = list(services.proposte_in_attesa().order_by("-created_at")[:200])
    for p in proposte:
        p.categoria_label = etichette.get((p.proposta or {}).get("categoria", ""), "")
    comuni = services.varianti_comuni_salvate()
    if comuni:
        for r in comuni.get("voci") or []:
            r["percentuale"] = round(float(r.get("quota") or 0) * 100)
    return render(request, "glossario_tecnico/pages/revisione.html", {
        "page_title": "Glossario — revisione",
        "bozze": bozze,
        "proposte": proposte,
        "comuni": comuni,
        "soglia_comune": round(services.SOGLIA_PAROLA_COMUNE * 100),
    })


@require_POST
def api_stato(request, pk: int):
    """POST ``stato`` = validato | deprecato | bozza. JSON."""
    if not request.user.is_authenticated or not _has_perm(request, PERM_GESTIONE):
        return _json_nega(request)
    obj = get_object_or_404(Termine, pk=pk)
    stato = request.POST.get("stato", "")
    if stato == Termine.VALIDATO:
        services.valida(obj, request.user)
    elif stato == Termine.DEPRECATO:
        services.depreca(obj)
    elif stato == Termine.BOZZA:
        obj.stato = Termine.BOZZA
        obj.save(update_fields=["stato", "updated_at"])
    else:
        return JsonResponse({"ok": False, "error": "Stato non valido."}, status=400)
    log_action(request, "glossario_stato", MODULE, {"termine": obj.termine, "stato": stato}, oggetto=obj)
    return JsonResponse({"ok": True, "id": obj.pk, "stato": obj.stato})


@login_required
def proposta_decidi(request, pk: int):
    """Proposta AI: accetta (crea il termine validato), correggi (form), scarta.
    Ogni decisione viene registrata per le lezioni delle proposte successive."""
    if not _has_perm(request, PERM_GESTIONE):
        return _nega(request)
    proposta = get_object_or_404(services.proposte_in_attesa(), pk=pk)
    dati = proposta.proposta or {}
    if request.method == "POST":
        azione = request.POST.get("azione", "")
        if azione == "scarta":
            services.scarta_proposta(proposta, request.user)
            log_action(request, "glossario_proposta_scartata", MODULE, {"candidato": dati.get("candidato", "")})
            messages.info(request, "Proposta scartata.")
            return redirect("glossario_tecnico:revisione")
        if azione == "accetta":
            correzione = None
        else:
            form = PropostaForm(request.POST)
            if not form.is_valid():
                return render(request, "glossario_tecnico/pages/proposta_form.html", {
                    "page_title": "Correggi proposta", "form": form, "proposta": proposta,
                })
            correzione = form.cleaned_data
        try:
            termine_creato = services.accetta_proposta(proposta, request.user, correzione)
        except ValidationError as exc:
            messages.error(request, "Proposta non accettata: " + "; ".join(exc.messages))
            return redirect("glossario_tecnico:proposta_decidi", pk=proposta.pk)
        log_action(request, "glossario_proposta_accettata", MODULE,
                   {"termine": termine_creato.termine, "corretta": correzione is not None}, oggetto=termine_creato)
        messages.success(request, f"Termine «{termine_creato.termine}» aggiunto e validato.")
        return redirect("glossario_tecnico:revisione")
    form = PropostaForm(initial={
        "termine": dati.get("termine", ""), "categoria": dati.get("categoria", ""),
        "definizione": dati.get("definizione", ""), "varianti": "\n".join(dati.get("varianti") or []),
    })
    return render(request, "glossario_tecnico/pages/proposta_form.html", {
        "page_title": "Correggi proposta", "form": form, "proposta": proposta,
    })
