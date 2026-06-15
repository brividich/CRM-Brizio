"""View CAPA — Azioni Correttive/Preventive (`core.ActionItem`).

Rotte montate in core/urls.py sotto `/capa/`. Le rotte sono dichiarate
"shared" nella ACLMiddleware (vedi `_ACL_SHARED_ROUTE_NAMES`): il gating reale
avviene qui, fail-closed.

Modello di accesso:
- **gestore** (`_can_manage_capa`): superuser / admin legacy / permesso
  `core.capa_manage` — vede tutto, crea, modifica, verifica, annulla;
- **responsabile**: l'utente assegnato a un'azione vede e può chiudere (eseguire)
  le proprie azioni, anche senza permesso di gestione.

La chiusura (esecuzione) è separata dalla verifica (efficacia): un'azione non
può essere verificata dalla stessa persona che l'ha chiusa (principio dei
quattro occhi), salvo superuser.
"""
from __future__ import annotations

from datetime import date

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.exporting import export_rows_response
from core.models import ActionItem
from core.services import capa as capa_service

User = get_user_model()


# ---------------------------------------------------------------------------
# Permessi
# ---------------------------------------------------------------------------

def _can_manage_capa(request) -> bool:
    """Gestore CAPA: superuser, admin legacy o permesso `core.capa_manage`."""
    if getattr(request.user, "is_superuser", False):
        return True
    from core.legacy_utils import get_legacy_user, is_legacy_admin

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if is_legacy_admin(legacy_user):
        return True
    from core.acl import user_can_modulo_action

    return user_can_modulo_action(request, "core", "capa_manage")


def _can_create_capa(request, source_code: str = "") -> bool:
    """Chi può creare un'azione CAPA.

    - I gestori CAPA possono sempre (incluso l'inserimento manuale da /capa/nuova/).
    - Le azioni che nascono da un evento di **sicurezza** possono crearle anche gli
      attori dell'incidente: preposti (creazione segnalazioni) e RSPP/ASPP. I ruoli
      sono valutati dal modulo `rilevazione_incidenti` (import lazy e difensivo: se
      il modulo è assente/disattivato restano i soli gestori CAPA).
    """
    if _can_manage_capa(request):
        return True
    if (source_code or "") == "rilevazione_incidenti":
        try:
            from rilevazione_incidenti.views import _can_create, _can_manage_rspp

            return bool(_can_create(request) or _can_manage_rspp(request))
        except Exception:
            return False
    return False


def _can_view_action(request, action: ActionItem) -> bool:
    return (
        _can_manage_capa(request)
        or action.responsabile_id == request.user.id
        or action.created_by_id == request.user.id
    )


def _forbidden(request) -> HttpResponse:
    return render(request, "core/pages/forbidden.html", {"page_title": "Accesso negato"}, status=403)


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

class ActionItemForm(forms.ModelForm):
    class Meta:
        model = ActionItem
        fields = ["titolo", "descrizione", "tipo", "responsabile", "reparto", "data_scadenza"]
        widgets = {
            "descrizione": forms.Textarea(attrs={"rows": 4}),
            "data_scadenza": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsabile"].queryset = User.objects.filter(is_active=True).order_by(
            "last_name", "first_name", "username"
        )
        self.fields["responsabile"].required = False
        self.fields["reparto"].required = False
        self.fields["data_scadenza"].required = False


# ---------------------------------------------------------------------------
# Lista + export
# ---------------------------------------------------------------------------

# Filtro scadenza → predicato sui giorni mancanti.
def _giorni(scad: date | None, oggi: date) -> int | None:
    return (scad - oggi).days if scad else None


@login_required
def capa_list(request: HttpRequest) -> HttpResponse:
    can_manage = _can_manage_capa(request)

    qs = ActionItem.objects.select_related("responsabile").all()
    # Non gestori: solo le azioni che li riguardano (assegnate a loro o create da loro).
    if not can_manage:
        qs = qs.filter(Q(responsabile_id=request.user.id) | Q(created_by_id=request.user.id))

    f_stato = request.GET.get("stato", "").strip()
    f_tipo = request.GET.get("tipo", "").strip()
    f_origine = request.GET.get("origine", "").strip()
    f_reparto = request.GET.get("reparto", "").strip()
    f_scad = request.GET.get("scadenza", "").strip()  # scaduta/30/60
    q = request.GET.get("q", "").strip()
    solo_aperte = request.GET.get("aperte", "").strip() == "1"

    if f_stato in dict(ActionItem.STATO_CHOICES):
        qs = qs.filter(stato=f_stato)
    if f_tipo in dict(ActionItem.TIPO_CHOICES):
        qs = qs.filter(tipo=f_tipo)
    if f_origine:
        qs = qs.filter(source_code=f_origine)
    if f_reparto:
        qs = qs.filter(reparto__iexact=f_reparto)
    if q:
        qs = qs.filter(Q(titolo__icontains=q) | Q(descrizione__icontains=q) | Q(source_label__icontains=q))
    if solo_aperte:
        qs = qs.exclude(stato__in=ActionItem.STATI_CONCLUSI)

    oggi = timezone.localdate()
    from datetime import timedelta

    if f_scad == "scaduta":
        qs = qs.filter(data_scadenza__lt=oggi).exclude(stato__in=ActionItem.STATI_CONCLUSI)
    elif f_scad in ("30", "60"):
        limite = oggi + timedelta(days=int(f_scad))
        qs = qs.filter(data_scadenza__gte=oggi, data_scadenza__lte=limite).exclude(
            stato__in=ActionItem.STATI_CONCLUSI
        )

    qs = qs.order_by("-created_at")

    # Export CSV/XLSX del set filtrato (prima della paginazione).
    if request.GET.get("export") or request.GET.get("format"):
        fmt = (request.GET.get("export") or request.GET.get("format") or "csv").lower()
        if fmt in ("csv", "xlsx"):
            return _export_capa(qs, fmt)

    # KPI sul set visibile (non filtrato per stato, per dare il quadro generale).
    base = (
        ActionItem.objects.all() if can_manage
        else ActionItem.objects.filter(Q(responsabile_id=request.user.id) | Q(created_by_id=request.user.id))
    )
    n_aperte = base.exclude(stato__in=ActionItem.STATI_CONCLUSI).count()
    n_scadute = base.exclude(stato__in=ActionItem.STATI_CONCLUSI).filter(data_scadenza__lt=oggi).count()
    n_da_verificare = base.filter(stato=ActionItem.STATO_CHIUSA).count()

    reparti = sorted(r for r in base.values_list("reparto", flat=True).distinct() if r)

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Annota i giorni alla scadenza per la riga.
    rows = []
    for a in page_obj:
        rows.append({"a": a, "giorni": _giorni(a.data_scadenza, oggi)})

    context = {
        "page_title": "Azioni CAPA",
        "page_obj": page_obj,
        "rows": rows,
        "can_manage": can_manage,
        "n_aperte": n_aperte,
        "n_scadute": n_scadute,
        "n_da_verificare": n_da_verificare,
        "reparti": reparti,
        "origini": list(ActionItem.ORIGINE_LABELS.items()),
        "stati": ActionItem.STATO_CHOICES,
        "tipi": ActionItem.TIPO_CHOICES,
        "f_stato": f_stato, "f_tipo": f_tipo, "f_origine": f_origine,
        "f_reparto": f_reparto, "f_scad": f_scad, "q": q, "solo_aperte": solo_aperte,
    }
    return render(request, "core/pages/capa_list.html", context)


def _export_capa(qs, fmt: str) -> HttpResponse:
    columns = (
        ("ID", "pk"),
        ("Titolo", "titolo"),
        ("Tipo", "get_tipo_display"),
        ("Stato", "get_stato_display"),
        ("Origine", "origine_label"),
        ("Riferimento origine", "source_label"),
        ("Responsabile", lambda a: a.responsabile.get_full_name() or a.responsabile.username if a.responsabile else ""),
        ("Reparto", "reparto"),
        ("Scadenza", "data_scadenza"),
        ("Chiusa da", lambda a: a.chiusa_da.get_full_name() or a.chiusa_da.username if a.chiusa_da else ""),
        ("Data chiusura", "data_chiusura"),
        ("Verificata da", lambda a: a.verificata_da.get_full_name() or a.verificata_da.username if a.verificata_da else ""),
        ("Data verifica", "data_verifica"),
    )
    return export_rows_response(rows=qs, columns=columns, filename="azioni_capa", fmt=fmt)


# ---------------------------------------------------------------------------
# Dettaglio + workflow
# ---------------------------------------------------------------------------

@login_required
def capa_detail(request: HttpRequest, pk: int) -> HttpResponse:
    action = get_object_or_404(ActionItem.objects.select_related("responsabile", "chiusa_da", "verificata_da"), pk=pk)
    if not _can_view_action(request, action):
        return _forbidden(request)
    can_manage = _can_manage_capa(request)
    context = {
        "page_title": f"CAPA #{action.pk}",
        "a": action,
        "can_manage": can_manage,
        "can_close": (can_manage or action.responsabile_id == request.user.id) and action.is_aperta and action.stato != ActionItem.STATO_CHIUSA,
        "giorni": _giorni(action.data_scadenza, timezone.localdate()),
    }
    return render(request, "core/pages/capa_detail.html", context)


@login_required
def capa_create(request: HttpRequest) -> HttpResponse:
    # source_code determina chi può creare: manuale → solo gestori; origine
    # sicurezza → anche preposti/RSPP (vedi _can_create_capa).
    source_code = (
        request.POST.get("source_code", "")
        if request.method == "POST"
        else request.GET.get("source", request.GET.get("source_code", ""))
    ).strip()
    if not _can_create_capa(request, source_code):
        return _forbidden(request)

    torna = request.GET.get("torna", "") or request.POST.get("torna", "")
    if request.method == "POST":
        form = ActionItemForm(request.POST)
        if form.is_valid():
            action = form.save(commit=False)
            action.source_code = (request.POST.get("source_code") or ActionItem.ORIGINE_MANUALE).strip()[:64]
            action.source_pk = (request.POST.get("source_pk") or "").strip()[:64]
            action.source_label = (request.POST.get("source_label") or "").strip()[:255]
            action.source_url = (request.POST.get("source_url") or "").strip()[:255]
            action.created_by = request.user
            action.save()
            if action.responsabile_id:
                capa_service.notifica_responsabile(action)
            messages.success(request, f"Azione CAPA #{action.pk} creata.")
            if torna:
                return redirect(torna)
            return redirect("capa_detail", pk=action.pk)
    else:
        initial = {
            "reparto": request.GET.get("reparto", ""),
        }
        form = ActionItemForm(initial=initial)

    context = {
        "page_title": "Nuova azione CAPA",
        "form": form,
        "torna": torna,
        # campi origine in prefill (passati come hidden nel template)
        "source_code": request.GET.get("source", request.GET.get("source_code", "")),
        "source_pk": request.GET.get("pk", request.GET.get("source_pk", "")),
        "source_label": request.GET.get("label", request.GET.get("source_label", "")),
        "source_url": request.GET.get("url", request.GET.get("source_url", "")),
        "is_edit": False,
    }
    return render(request, "core/pages/capa_form.html", context)


@login_required
def capa_edit(request: HttpRequest, pk: int) -> HttpResponse:
    action = get_object_or_404(ActionItem, pk=pk)
    if not _can_manage_capa(request):
        return _forbidden(request)

    old_responsabile_id = action.responsabile_id
    if request.method == "POST":
        form = ActionItemForm(request.POST, instance=action)
        if form.is_valid():
            action = form.save()
            # Notifica se cambia il responsabile.
            if action.responsabile_id and action.responsabile_id != old_responsabile_id:
                capa_service.notifica_responsabile(action)
            messages.success(request, "Azione CAPA aggiornata.")
            return redirect("capa_detail", pk=action.pk)
    else:
        form = ActionItemForm(instance=action)

    context = {"page_title": f"Modifica CAPA #{action.pk}", "form": form, "a": action, "is_edit": True}
    return render(request, "core/pages/capa_form.html", context)


@login_required
@require_POST
def capa_take(request: HttpRequest, pk: int) -> HttpResponse:
    """Prendi in carico: APERTA → IN_CORSO (gestore o responsabile)."""
    action = get_object_or_404(ActionItem, pk=pk)
    if not _can_view_action(request, action):
        return _forbidden(request)
    if action.stato == ActionItem.STATO_APERTA:
        action.stato = ActionItem.STATO_IN_CORSO
        action.save(update_fields=["stato", "updated_at"])
        messages.success(request, "Azione presa in carico.")
    return redirect("capa_detail", pk=action.pk)


@login_required
@require_POST
def capa_close(request: HttpRequest, pk: int) -> HttpResponse:
    """Chiusura (esecuzione del rimedio): richiede evidenza. Gestore o responsabile."""
    action = get_object_or_404(ActionItem, pk=pk)
    if not (_can_manage_capa(request) or action.responsabile_id == request.user.id):
        return _forbidden(request)
    if action.is_conclusa:
        messages.warning(request, "Azione già conclusa.")
        return redirect("capa_detail", pk=action.pk)
    evidenza = request.POST.get("evidenza_chiusura", "")
    if not capa_service.chiudi_azione(action, utente=request.user, evidenza=evidenza):
        messages.error(request, "Per chiudere l'azione devi descrivere l'evidenza di cosa è stato fatto.")
        return redirect("capa_detail", pk=action.pk)
    messages.success(request, "Azione chiusa. In attesa di verifica di efficacia.")
    return redirect("capa_detail", pk=action.pk)


@login_required
@require_POST
def capa_verify(request: HttpRequest, pk: int) -> HttpResponse:
    """Verifica di efficacia: CHIUSA → VERIFICATA. Solo gestore, mai chi ha chiuso (4 occhi)."""
    action = get_object_or_404(ActionItem, pk=pk)
    if not _can_manage_capa(request):
        return _forbidden(request)
    if action.stato != ActionItem.STATO_CHIUSA:
        messages.warning(request, "Solo le azioni chiuse possono essere verificate.")
        return redirect("capa_detail", pk=action.pk)
    if action.chiusa_da_id == request.user.id and not request.user.is_superuser:
        messages.error(
            request,
            "La verifica di efficacia deve essere fatta da una persona diversa da chi ha chiuso l'azione.",
        )
        return redirect("capa_detail", pk=action.pk)
    capa_service.verifica_azione(action, utente=request.user, note=request.POST.get("note_verifica", ""))
    messages.success(request, "Azione verificata e chiusa definitivamente.")
    return redirect("capa_detail", pk=action.pk)


@login_required
@require_POST
def capa_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    """Annulla l'azione (solo gestore)."""
    action = get_object_or_404(ActionItem, pk=pk)
    if not _can_manage_capa(request):
        return _forbidden(request)
    if not action.is_conclusa:
        action.stato = ActionItem.STATO_ANNULLATA
        action.save(update_fields=["stato", "updated_at"])
        messages.success(request, "Azione annullata.")
    return redirect("capa_detail", pk=action.pk)
