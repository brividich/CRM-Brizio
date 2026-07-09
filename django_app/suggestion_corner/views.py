"""Viste del modulo Suggestion Corner.

Lettura (home, dettaglio) + azioni FSM (sessione 3b). Gating: `@login_required`
+ ACLMiddleware (binding canonico per rotta, vedi acl_bootstrap.py, PERM_VIEW).
Lo scope dei dati è deciso da `permissions.visible_segnalazioni`; l'autorizzazione
delle azioni FSM è decisa in-view (SMS_TEAM/incaricato/controllore).
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_fsm import TransitionNotAllowed

from . import forms as sc_forms
from .models import SuggestionCorner
from .permissions import (
    can_check, can_complete_do, is_sms_team, visible_segnalazioni,
)


@login_required
def home(request):
    """Elenco segnalazioni con scope per-utente.

    - team SMS / superuser: tutte + coda 'da gestire' (DA_CLASSIFICARE);
    - altri: solo le proprie + incarichi assegnati.
    """
    team = is_sms_team(request.user)
    segnalazioni = visible_segnalazioni(request.user).select_related(
        "reparto_provenienza", "incaricato", "controllore",
    )
    da_gestire = (
        segnalazioni.filter(stato=SuggestionCorner.Stato.DA_CLASSIFICARE)
        if team else SuggestionCorner.objects.none()
    )
    return render(request, "suggestion_corner/home.html", {
        "segnalazioni": segnalazioni,
        "da_gestire": da_gestire,
        "is_team": team,
    })


@login_required
def dettaglio(request, pk: int):
    """Dettaglio in sola lettura; 404 se l'utente non ha visibilità sull'oggetto.

    Espone i form/flag delle azioni FSM disponibili nello stato corrente per
    l'utente (i pulsanti sono renderizzati dal template in base a stato + permesso).
    """
    seg = get_object_or_404(
        visible_segnalazioni(request.user).select_related(
            "reparto_provenienza", "reparto_destinazione", "incaricato", "controllore",
        ),
        pk=pk,
    )
    storico = seg.storico.select_related("autore").all()
    team = is_sms_team(request.user)
    ctx = {
        "seg": seg,
        "storico": storico,
        "is_team": team,
        "can_do": can_complete_do(request.user, seg),
        "can_ck": can_check(request.user, seg),
        "S": SuggestionCorner.Stato,
        "form_classifica": sc_forms.ClassificaForm(),
        "form_plan": sc_forms.PlanForm(),
        "form_completa_do": sc_forms.CompletaDoForm(),
        "form_do_rifare": sc_forms.DoRifareForm(),
        "form_check": sc_forms.CheckForm(),
        "form_check_rinviato": sc_forms.CheckRinviatoForm(),
    }
    return render(request, "suggestion_corner/dettaglio.html", ctx)


# --- Form pubblico anonimo (sessione 4, §5) ---------------------------------
# Route ESCLUSA dal gate ACL/login/onboarding via MIDDLEWARE_EXEMPT_PREFIXES
# ("/suggestion-corner/nuova/"). Unica superficie pubblica non autenticata.

def nuova(request):
    """Form pubblico: crea una segnalazione (INSERITA→DA_CLASSIFICARE).

    Rate-limit per IP + honeypot anti-bot. Nessun login richiesto.
    """
    from .ratelimit import is_rate_limited

    if request.method == "POST":
        if is_rate_limited(request):
            return render(request, "suggestion_corner/pubblica_limite.html", status=429)

        # Honeypot: se il campo nascosto è compilato è un bot → finto successo,
        # nessuna creazione, nessun indizio all'attaccante.
        if request.POST.get("website"):
            return render(request, "suggestion_corner/pubblica_ok.html")

        form = sc_forms.SegnalazionePubblicaForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            anonima = cd["anonima"]
            autenticato = getattr(request.user, "is_authenticated", False)
            seg = SuggestionCorner(
                reparto_provenienza=cd["reparto_provenienza"],
                opportunity=cd["opportunity"],
                anonima=anonima,
                da_portale=True,
                created_by=(request.user if autenticato and not anonima else None),
            )
            with transaction.atomic():
                seg.save()
                # auto-avanzamento INSERITA → DA_CLASSIFICARE
                seg.notifica_sms_team()
                seg.save()
            # mail al team SMS (fuori transazione, fail-safe)
            try:
                from .notifications import notifica_team_nuova_segnalazione
                notifica_team_nuova_segnalazione(seg)
            except Exception:
                pass
            return render(request, "suggestion_corner/pubblica_ok.html")
    else:
        form = sc_forms.SegnalazionePubblicaForm()
    return render(request, "suggestion_corner/pubblica_form.html", {"form": form})


# --- Azioni FSM (sessione 3b) -----------------------------------------------

def _do_transition(request, pk, *, authorize, apply, form_class=None, on_success=None):
    """Helper comune: autorizza, valida il form, esegue la transizione in
    transazione atomica (transition + save insieme), gestisce gli errori e
    torna al dettaglio con un messaggio. `on_success(seg)` è un hook fail-safe
    eseguito dopo il commit (es. notifiche)."""
    seg = get_object_or_404(SuggestionCorner, pk=pk)
    if not authorize(request.user, seg):
        raise PermissionDenied("Non autorizzato a questa operazione.")

    cleaned = {}
    if form_class is not None:
        form = form_class(request.POST)
        if not form.is_valid():
            for field, errs in form.errors.items():
                messages.error(request, f"{field}: {'; '.join(errs)}")
            return redirect("suggestion_corner:dettaglio", pk=pk)
        cleaned = form.cleaned_data

    try:
        with transaction.atomic():
            apply(seg, request.user, cleaned)
            seg.save()
    except (TransitionNotAllowed, ValidationError) as exc:
        messages.error(request, getattr(exc, "message", None) or str(exc) or "Transizione non consentita.")
        return redirect("suggestion_corner:dettaglio", pk=pk)

    if on_success is not None:
        try:
            on_success(seg)
        except Exception:
            pass

    messages.success(request, "Operazione completata.")
    return redirect("suggestion_corner:dettaglio", pk=pk)


def _team(user, seg):
    return is_sms_team(user)


@login_required
@require_POST
def azione_classifica(request, pk: int):
    return _do_transition(
        request, pk, authorize=_team, form_class=sc_forms.ClassificaForm,
        apply=lambda seg, user, cd: seg.classifica(cd["stato_sms"], attore=user),
    )


@login_required
@require_POST
def azione_definisci_plan(request, pk: int):
    return _do_transition(
        request, pk, authorize=_team, form_class=sc_forms.PlanForm,
        apply=lambda seg, user, cd: seg.definisci_plan(
            incaricato=cd["incaricato"], controllore=cd["controllore"],
            data_limite_esecuzione=cd["data_limite_esecuzione"],
            data_limite_controllo=cd["data_limite_controllo"],
            plan_testo=cd.get("plan_testo", ""), attore=user,
        ),
        on_success=lambda seg: _notifica_assegnazione(seg),
    )


def _notifica_assegnazione(seg):
    from .notifications import notifica_assegnazione_in_app
    notifica_assegnazione_in_app(seg)


@login_required
@require_POST
def azione_avvia_do(request, pk: int):
    return _do_transition(
        request, pk, authorize=_team,
        apply=lambda seg, user, cd: seg.avvia_do(attore=user),
    )


@login_required
@require_POST
def azione_completa_do(request, pk: int):
    return _do_transition(
        request, pk, authorize=can_complete_do, form_class=sc_forms.CompletaDoForm,
        apply=lambda seg, user, cd: seg.completa_do(
            cd["esito_do"], do_testo=cd.get("do_testo", ""), attore=user,
        ),
    )


@login_required
@require_POST
def azione_avvia_check(request, pk: int):
    return _do_transition(
        request, pk, authorize=can_check,
        apply=lambda seg, user, cd: seg.avvia_check(attore=user),
    )


@login_required
@require_POST
def azione_do_da_rifare(request, pk: int):
    return _do_transition(
        request, pk, authorize=_team, form_class=sc_forms.DoRifareForm,
        apply=lambda seg, user, cd: seg.do_da_rifare(
            nuova_data_limite_esecuzione=cd["nuova_data_limite_esecuzione"], attore=user,
        ),
    )


@login_required
@require_POST
def azione_check_positivo(request, pk: int):
    return _do_transition(
        request, pk, authorize=can_check, form_class=sc_forms.CheckForm,
        apply=lambda seg, user, cd: seg.check_positivo(check_testo=cd.get("check_testo", ""), attore=user),
    )


@login_required
@require_POST
def azione_check_negativo(request, pk: int):
    return _do_transition(
        request, pk, authorize=can_check, form_class=sc_forms.CheckForm,
        apply=lambda seg, user, cd: seg.check_negativo(check_testo=cd.get("check_testo", ""), attore=user),
    )


@login_required
@require_POST
def azione_check_rinviato(request, pk: int):
    return _do_transition(
        request, pk, authorize=can_check, form_class=sc_forms.CheckRinviatoForm,
        apply=lambda seg, user, cd: seg.check_rinviato(
            nuova_data_limite_controllo=cd["nuova_data_limite_controllo"], attore=user,
        ),
    )


@login_required
@require_POST
def azione_inserisci_act(request, pk: int):
    return _do_transition(
        request, pk, authorize=_team,
        apply=lambda seg, user, cd: seg.inserisci_act(attore=user),
    )


@login_required
@require_POST
def azione_chiudi(request, pk: int):
    return _do_transition(
        request, pk, authorize=_team,
        apply=lambda seg, user, cd: seg.chiudi(attore=user),
    )


# --- Copilota AI (sessione 9) — endpoint JSON AJAX --------------------------
# Gating: @login_required + ACL PERM_VIEW (binding di rotta) + SMS_TEAM in-view.
# Per la regola API/AJAX (CLAUDE.md) i non-autorizzati ricevono JSON 403, non un
# redirect HTML. L'AI PROPONE soltanto: nessuna scrittura DB, nessuna transizione.

def _richiede_team_json(request, pk):
    """Restituisce (seg, None) se autorizzato, altrimenti (None, JsonResponse 403)."""
    seg = get_object_or_404(SuggestionCorner, pk=pk)
    if not is_sms_team(request.user):
        return None, JsonResponse({"error": "Non autorizzato."}, status=403)
    return seg, None


@login_required
@require_POST
def ai_classifica(request, pk: int):
    """Proposta AI di classificazione SMS Sì/No (l'operatore conferma)."""
    from . import ai as sc_ai

    seg, deny = _richiede_team_json(request, pk)
    if deny is not None:
        return deny
    return JsonResponse(sc_ai.classifica_ai(seg))


@login_required
@require_POST
def ai_bozza_plan(request, pk: int):
    """Bozza AI del PLAN (l'operatore rivede e firma)."""
    from . import ai as sc_ai

    seg, deny = _richiede_team_json(request, pk)
    if deny is not None:
        return deny
    return JsonResponse(sc_ai.bozza_plan_ai(seg))


@login_required
@require_POST
def ai_simili(request, pk: int):
    """Segnalazioni simili (dedup) — similarità token, senza dipendere dall'AI."""
    from . import ai as sc_ai

    seg, deny = _richiede_team_json(request, pk)
    if deny is not None:
        return deny
    return JsonResponse({"risultati": sc_ai.trova_simili(seg)})
