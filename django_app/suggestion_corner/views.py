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

from core.form_fields import user_display_label
from core.public_headers import risposta_pubblica

from . import forms as sc_forms
from .foto import FOTO_MAX_MB
from .models import SuggestionCorner, SuggestionCornerAllegato, SuggestionCornerLocandina
from .permissions import (
    can_check, can_complete_do, is_sms_team, visible_segnalazioni,
)


@login_required
def home(request):
    """Dashboard/elenco segnalazioni con scope per-utente e filtro per stato SMS.

    - team SMS / superuser: tutte le segnalazioni;
    - altri: solo le proprie + incarichi assegnati.

    Pulsanti-contatore (Tutte / Da gestire / SMS Sì / SMS No) filtrano la lista
    via `?filtro=`; i conteggi sono sempre sullo scope completo dell'utente.
    """
    team = is_sms_team(request.user)
    base = visible_segnalazioni(request.user).select_related(
        "reparto_provenienza", "incaricato", "controllore",
    )
    S, SMS = SuggestionCorner.Stato, SuggestionCorner.StatoSMS
    conteggi = {
        "tutte": base.count(),
        "da_gestire": base.filter(stato=S.DA_CLASSIFICARE).count(),
        "sms_si": base.filter(stato_sms=SMS.SMS_SI).count(),
        "sms_no": base.filter(stato_sms=SMS.SMS_NO).count(),
    }
    filtro = (request.GET.get("filtro") or "tutte").strip()
    if filtro == "da_gestire":
        segnalazioni = base.filter(stato=S.DA_CLASSIFICARE)
    elif filtro == "sms_si":
        segnalazioni = base.filter(stato_sms=SMS.SMS_SI)
    elif filtro == "sms_no":
        segnalazioni = base.filter(stato_sms=SMS.SMS_NO)
    else:
        filtro = "tutte"
        segnalazioni = base
    return render(request, "suggestion_corner/home.html", {
        "segnalazioni": segnalazioni,
        "conteggi": conteggi,
        "filtro": filtro,
        "is_team": team,
    })


@login_required
def gestione(request, *args, **kwargs):
    """Console di gestione del modulo — riservata al team SMS/superuser.

    Riunisce in un'unica pagina «admin» del modulo: coda di triage
    (DA_CLASSIFICARE), KPI per stato/classificazione, scadenze DO/CHECK,
    membri del team SMS, mappature processo e configurazione operativa
    (soglie solleciti/escalation, gruppo team). La configurazione si salva
    via POST sulla stessa pagina.
    """
    if not is_sms_team(request.user):
        raise PermissionDenied("Sezione riservata al team SMS.")

    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from .models import SuggestionCornerConfig, SuggestionCornerProcessoMapping

    config = SuggestionCornerConfig.load()
    if request.method == "POST":
        form_config = sc_forms.ConfigForm(request.POST, instance=config)
        if form_config.is_valid():
            form_config.save()
            messages.success(request, "Configurazione aggiornata.")
            return redirect("suggestion_corner:gestione")
    else:
        form_config = sc_forms.ConfigForm(instance=config)

    S, SMS = SuggestionCorner.Stato, SuggestionCorner.StatoSMS
    qs = SuggestionCorner.objects.all()
    oggi = timezone.localdate()

    da_classificare = (
        qs.filter(stato=S.DA_CLASSIFICARE)
        .select_related("reparto_provenienza", "area_provenienza")
        .order_by("data_segnalazione")
    )
    scaduti_do = qs.filter(
        do_eseguito=False, data_limite_esecuzione__lt=oggi,
    ).exclude(stato__in=[S.CHIUSA, S.INSERITA, S.DA_CLASSIFICARE]).count()
    scaduti_check = qs.filter(
        check_eseguito=False, data_limite_controllo__lt=oggi,
    ).exclude(stato__in=[S.CHIUSA, S.INSERITA, S.DA_CLASSIFICARE]).count()

    kpi = {
        "totali": qs.count(),
        "da_classificare": da_classificare.count(),
        "aperte": qs.exclude(stato=S.CHIUSA).count(),
        "chiuse": qs.filter(stato=S.CHIUSA).count(),
        "sms_si": qs.filter(stato_sms=SMS.SMS_SI).count(),
        "sms_no": qs.filter(stato_sms=SMS.SMS_NO).count(),
        "scaduti_do": scaduti_do,
        "scaduti_check": scaduti_check,
    }

    User = get_user_model()
    team = (
        User.objects.filter(groups__name=config.sms_team_group_name, is_active=True)
        .order_by("username")
    )
    # Candidati = utenti attivi non ancora nel team (per la select "aggiungi").
    candidati = (
        User.objects.filter(is_active=True)
        .exclude(groups__name=config.sms_team_group_name)
        .order_by("first_name", "last_name", "username")
    )

    return render(request, "suggestion_corner/gestione.html", {
        "form_config": form_config,
        "kpi": kpi,
        "da_classificare": da_classificare,
        "team": team,
        "candidati": candidati,
        "team_group": config.sms_team_group_name,
        "mappature": SuggestionCornerProcessoMapping.objects.all().order_by("valore_libero"),
    })


def _sms_team_group():
    from django.contrib.auth.models import Group

    from .models import SuggestionCornerConfig
    g, _ = Group.objects.get_or_create(name=SuggestionCornerConfig.load().sms_team_group_name)
    return g


@login_required
@require_POST
def gestione_team_add(request):
    """Aggiunge un utente al gruppo SMS_TEAM (dalla console Gestione)."""
    from django.contrib.auth import get_user_model

    if not is_sms_team(request.user):
        raise PermissionDenied("Sezione riservata al team SMS.")
    u = get_user_model().objects.filter(pk=request.POST.get("user_id")).first()
    if u is None:
        messages.error(request, "Utente non trovato.")
    else:
        u.groups.add(_sms_team_group())
        messages.success(request, f"{u.get_full_name() or u.username} aggiunto al team SMS.")
    return redirect("suggestion_corner:gestione")


@login_required
@require_POST
def gestione_team_remove(request):
    """Rimuove un utente dal gruppo SMS_TEAM (dalla console Gestione)."""
    from django.contrib.auth import get_user_model

    if not is_sms_team(request.user):
        raise PermissionDenied("Sezione riservata al team SMS.")
    u = get_user_model().objects.filter(pk=request.POST.get("user_id")).first()
    if u is None:
        messages.error(request, "Utente non trovato.")
    else:
        u.groups.remove(_sms_team_group())
        note = " (hai rimosso te stesso: perderai l'accesso di gestione)" if u == request.user else ""
        messages.success(request, f"{u.get_full_name() or u.username} rimosso dal team SMS.{note}")
    return redirect("suggestion_corner:gestione")


def _corpo_cliente(seg):
    """Corpo pre-compilato per la mail al cliente (SMS Sì), aperto nel client di
    posta del team via mailto: contiene il contenuto della segnalazione."""
    righe = [
        f"Gentile {seg.cliente_nome or 'cliente'},",
        "",
        f"nell'ambito del nostro Sistema di Miglioramento/Segnalazione (SMS) le "
        f"comunichiamo la seguente segnalazione (SC#{seg.pk}, provenienza "
        f"{seg.provenienza_display}):",
        "",
        f"Opportunità di miglioramento:",
        seg.opportunity or "—",
    ]
    for etichetta, testo in (("Plan", seg.plan_testo), ("Do", seg.do_testo),
                             ("Check", seg.check_testo), ("Act", seg.act_testo)):
        if testo:
            righe += ["", f"{etichetta}:", testo]
    righe += ["", "Cordiali saluti,", "Team SMS — NOVICROM"]
    return "\n".join(righe)


def _pdca_steps(stato):
    """Stato delle 4 fasi PDCA (Plan/Do/Check/Act) per lo stepper del dettaglio.

    Ritorna una lista di dict {letter, label, state} con state ∈ done/current/todo,
    derivato dallo stato FSM corrente. Nessun effetto collaterale.
    """
    order = [
        "INSERITA", "DA_CLASSIFICARE", "CLASSIFICATA", "PLAN_DEFINITO",
        "DO_IN_CORSO", "DO_COMPLETATO", "CHECK_IN_CORSO", "CHECK_COMPLETATO",
        "ACT_INSERITO", "CHIUSA",
    ]
    idx = order.index(stato) if stato in order else 0
    # (letter, label, indice in cui la fase è "current", soglia di "done")
    fasi = [
        ("P", "Plan", {"DA_CLASSIFICARE", "CLASSIFICATA"}, order.index("PLAN_DEFINITO")),
        ("D", "Do", {"PLAN_DEFINITO", "DO_IN_CORSO"}, order.index("DO_COMPLETATO")),
        ("C", "Check", {"DO_COMPLETATO", "CHECK_IN_CORSO"}, order.index("CHECK_COMPLETATO")),
        ("A", "Act", {"CHECK_COMPLETATO", "ACT_INSERITO"}, order.index("CHIUSA")),
    ]
    steps = []
    for letter, label, current_states, done_from in fasi:
        if stato in current_states:
            state = "current"
        elif idx >= done_from:
            state = "done"
        else:
            state = "todo"
        steps.append({"letter": letter, "label": label, "state": state})
    return steps


@login_required
def dettaglio(request, pk: int):
    """Dettaglio in sola lettura; 404 se l'utente non ha visibilità sull'oggetto.

    Espone i form/flag delle azioni FSM disponibili nello stato corrente per
    l'utente (i pulsanti sono renderizzati dal template in base a stato + permesso).
    """
    seg = get_object_or_404(
        visible_segnalazioni(request.user).select_related(
            "reparto_provenienza", "reparto_destinazione",
            "area_provenienza", "area_destinazione",
            "incaricato", "controllore",
        ),
        pk=pk,
    )
    storico = seg.storico.select_related("autore").all()
    team = is_sms_team(request.user)
    ctx = {
        "seg": seg,
        "allegati": list(seg.allegati.all()),
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
        "form_comunica_cliente": sc_forms.ComunicazioneClienteForm(initial={
            "cliente_nome": seg.cliente_nome, "cliente_email": seg.cliente_email,
        }),
        "SMS": SuggestionCorner.StatoSMS,
        "pdca": _pdca_steps(seg.stato),
        "cliente_mail_subject": f"[Suggestion Corner] Comunicazione SMS — SC#{seg.pk}",
        "cliente_mail_body": _corpo_cliente(seg),
    }
    return render(request, "suggestion_corner/dettaglio.html", ctx)


@login_required
def modifica(request, pk: int):
    """Modifica amministrativa della segnalazione (gestione interna al modulo).

    Riservata al team SMS/superuser (`is_sms_team`), come le altre operazioni di
    gestione. Consente di correggere reparti, persone, esiti e testi PDCA — utile
    ad esempio dopo un import storico. NON tocca `stato` (workflow) né le date di
    sistema. Ogni modifica lascia una voce nello storico (audit).
    """
    seg = get_object_or_404(SuggestionCorner, pk=pk)
    if not is_sms_team(request.user):
        raise PermissionDenied("Solo il team SMS può modificare le segnalazioni.")

    if request.method == "POST":
        form = sc_forms.ModificaSegnalazioneForm(request.POST, instance=seg)
        if form.is_valid():
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.updated_by = request.user
                obj.save()
                _log_modifica_manuale(seg, request.user, form.changed_data)
            messages.success(request, "Segnalazione aggiornata.")
            return redirect("suggestion_corner:dettaglio", pk=pk)
    else:
        form = sc_forms.ModificaSegnalazioneForm(instance=seg)

    return render(request, "suggestion_corner/modifica.html", {"seg": seg, "form": form})


@login_required
@require_POST
def azione_comunica_cliente(request, pk: int):
    """Registra la comunicazione al cliente per una segnalazione SMS Sì.

    La mail vera si scrive dal **client di posta del team** (pulsante mailto nel
    dettaglio: apre il client con oggetto e corpo = contenuto segnalazione già
    pronti). Qui NON si invia nulla lato server: si salva il destinatario
    (nome/email) e si marca la comunicazione come effettuata (data + flag +
    audit). Riservata al team SMS; solo se la segnalazione è SMS Sì."""
    from django.utils import timezone

    seg = get_object_or_404(SuggestionCorner, pk=pk)
    if not is_sms_team(request.user):
        raise PermissionDenied("Solo il team SMS può comunicare al cliente.")
    if seg.stato_sms != SuggestionCorner.StatoSMS.SMS_SI:
        messages.error(request, "La comunicazione al cliente è prevista solo per le segnalazioni classificate SMS Sì.")
        return redirect("suggestion_corner:dettaglio", pk=pk)

    form = sc_forms.ComunicazioneClienteForm(request.POST)
    if not form.is_valid():
        for field, errs in form.errors.items():
            messages.error(request, f"{field}: {'; '.join(errs)}")
        return redirect("suggestion_corner:dettaglio", pk=pk)

    cd = form.cleaned_data
    seg.cliente_nome = cd["cliente_nome"]
    seg.cliente_email = cd["cliente_email"]
    seg.comunicazione_cliente_inviata = True
    seg.data_comunicazione_cliente = timezone.now()
    seg.updated_by = request.user
    seg.save()
    _log_comunicazione_cliente(seg, request.user)
    messages.success(request, f"Comunicazione al cliente registrata ({seg.cliente_email}).")
    return redirect("suggestion_corner:dettaglio", pk=pk)


def _log_comunicazione_cliente(seg, user):
    from .models import SuggestionCornerStorico

    SuggestionCornerStorico.objects.create(
        segnalazione=seg, stato_precedente=seg.stato, stato_nuovo=seg.stato,
        campo_modificato="comunicazione_cliente",
        valore_nuovo=f"Comunicato al cliente: {seg.cliente_email}",
        autore=user,
    )


def _log_modifica_manuale(seg, user, changed_fields):
    """Voce di storico per una modifica manuale (audit). Lo stato non cambia."""
    from .models import SuggestionCornerStorico

    SuggestionCornerStorico.objects.create(
        segnalazione=seg,
        stato_precedente=seg.stato, stato_nuovo=seg.stato,
        campo_modificato="modifica_manuale",
        valore_nuovo=", ".join(changed_fields) if changed_fields else "(nessun campo)",
        autore=user,
    )


# --- Form pubblico anonimo (sessione 4, §5) ---------------------------------
# Route ESCLUSA dal gate ACL/login/onboarding via MIDDLEWARE_EXEMPT_PREFIXES
# ("/suggestion-corner/nuova/"). Unica superficie pubblica non autenticata.

@risposta_pubblica
def nuova(request):
    """Form pubblico: crea una segnalazione (INSERITA→DA_CLASSIFICARE).

    Rate-limit per IP + honeypot anti-bot. Nessun login richiesto.

    `Referrer-Policy: same-origin` invece del `no-referrer` di
    `risposta_pubblica`: con `no-referrer` Chromium invia `Origin: null`
    sul POST del form e il controllo CSRF di Django lo rifiuta (l'invio finiva
    su «Sessione scaduta»). same-origin non fa uscire nulla dal dominio.
    """
    response = _nuova(request)
    response["Referrer-Policy"] = "same-origin"
    return response


def _nuova(request):
    from .ratelimit import is_rate_limited

    if request.method == "POST":
        if is_rate_limited(request):
            return render(request, "suggestion_corner/pubblica_limite.html", status=429)

        # Honeypot: se il campo nascosto è compilato è un bot → finto successo,
        # nessuna creazione, nessun indizio all'attaccante.
        if request.POST.get("website"):
            return render(request, "suggestion_corner/pubblica_ok.html")

        form = sc_forms.SegnalazionePubblicaForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            cd = form.cleaned_data
            anonima = form.anonima
            # Con il login e «Mi identifico» l'autore è l'account; senza login
            # resta il nome dichiarato. Anonima: nessun legame con chi scrive.
            autore = form.user if not anonima else None
            seg = SuggestionCorner(
                reparto_provenienza=cd.get("reparto_provenienza"),
                area_provenienza=cd.get("area_provenienza"),
                opportunity=cd["opportunity"],
                anonima=anonima,
                segnalante_nome=cd["segnalante_nome"],
                da_portale=True,
                created_by=autore,
            )
            with transaction.atomic():
                seg.save()
                if cd.get("foto"):
                    SuggestionCornerAllegato.objects.create(
                        segnalazione=seg, file=cd["foto"], caricato_da=autore,
                    )
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
        form = sc_forms.SegnalazionePubblicaForm(user=request.user)
    return render(request, "suggestion_corner/pubblica_form.html", {
        "form": form,
        "utente": form.user,
        "utente_nome": user_display_label(form.user) if form.user else "",
        "foto_max_mb": FOTO_MAX_MB,
    })


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


# --- Foto/allegati della segnalazione -----------------------------------------

@login_required
def allegato(request, pk: int):
    """Foto o file di una segnalazione, a chi vede la segnalazione (storage privato).

    Le foto del form pubblico sono JPEG ricodificati (foto.py) e si mostrano
    in pagina; gli altri file si scaricano.
    """
    import mimetypes
    import os

    from django.http import FileResponse, Http404

    alleg = get_object_or_404(SuggestionCornerAllegato, pk=pk)
    get_object_or_404(visible_segnalazioni(request.user), pk=alleg.segnalazione_id)
    if not alleg.file or not alleg.file.name:
        raise Http404("Allegato senza file.")
    try:
        handle = alleg.file.storage.open(alleg.file.name, "rb")
    except FileNotFoundError:
        raise Http404("File non trovato.")
    filename = os.path.basename(alleg.file.name)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = FileResponse(
        handle, as_attachment=not content_type.startswith("image/"),
        filename=filename, content_type=content_type,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# --- Locandine QR per le bacheche (team SMS) -----------------------------------

def _richiede_team(request):
    if not is_sms_team(request.user):
        raise PermissionDenied("Sezione riservata al team SMS.")


@login_required
def locandine(request):
    """Preset delle locandine con QR al form pubblico: scelta, modifica, salvataggio.

    Il PDF (anteprima nella pagina e download) lo produce `locandina_pdf`;
    qui si gestiscono i preset e l'indirizzo codificato nel QR.
    """
    from .locandina import url_form_pubblico
    from .models import SuggestionCornerConfig

    _richiede_team(request)
    presets = list(SuggestionCornerLocandina.objects.all())
    scelto = None
    pid = request.POST.get("preset") or request.GET.get("preset")
    if pid and str(pid).isdigit():
        scelto = next((p for p in presets if p.pk == int(pid)), None)
    if scelto is None:
        scelto = next((p for p in presets if p.predefinita), presets[0] if presets else None)

    config = SuggestionCornerConfig.load()
    form = sc_forms.LocandinaForm(instance=scelto)
    form_url = sc_forms.LocandinaUrlForm(instance=config)

    if request.method == "POST":
        azione = request.POST.get("azione", "")
        if azione == "url":
            form_url = sc_forms.LocandinaUrlForm(request.POST, instance=config)
            if form_url.is_valid():
                form_url.save()
                messages.success(request, "Indirizzo del QR aggiornato.")
                return _redirect_locandine(scelto)
        elif azione == "elimina" and scelto is not None:
            if len(presets) <= 1:
                messages.error(request, "Serve almeno un preset: questo non si può eliminare.")
            else:
                nome = scelto.nome
                scelto.delete()
                messages.success(request, f"Preset «{nome}» eliminato.")
                return _redirect_locandine(None)
        elif azione in ("salva", "nuovo"):
            nuovo = azione == "nuovo" or scelto is None
            istanza = SuggestionCornerLocandina() if nuovo else scelto
            dati = request.POST.copy()
            if nuovo:
                dati["nome"] = (request.POST.get("nome_nuovo") or "").strip()
            form = sc_forms.LocandinaForm(dati, instance=istanza)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.updated_by = request.user
                with transaction.atomic():
                    if obj.predefinita:
                        SuggestionCornerLocandina.objects.exclude(pk=obj.pk).update(predefinita=False)
                    obj.save()
                messages.success(request, f"Preset «{obj.nome}» {'creato' if nuovo else 'salvato'}.")
                return _redirect_locandine(obj)

    return render(request, "suggestion_corner/locandine.html", {
        "presets": presets,
        "scelto": scelto,
        "form": form,
        "form_url": form_url,
        "url_qr": url_form_pubblico(request),
    })


def _redirect_locandine(preset):
    from django.urls import reverse

    url = reverse("suggestion_corner:locandine")
    return redirect(f"{url}?preset={preset.pk}" if preset else url)


@login_required
def locandina_pdf(request):
    """PDF della locandina: GET `?preset=<id>` (salvato) o POST con i campi del form (anteprima).

    `scarica=1` lo manda come file da salvare; altrimenti si apre nella pagina
    (iframe di anteprima, stessa origine).
    """
    from django.http import HttpResponse
    from django.utils.text import slugify

    from .locandina import render_locandina_pdf, url_form_pubblico

    _richiede_team(request)
    if request.method == "POST":
        pid = request.POST.get("preset")
        base = SuggestionCornerLocandina.objects.filter(pk=pid).first() if str(pid or "").isdigit() else None
        dati = request.POST.copy()
        dati["nome"] = (base.nome if base else "") or "anteprima"
        form = sc_forms.LocandinaForm(dati, instance=SuggestionCornerLocandina())
        form.is_valid()  # i limiti di lunghezza valgono anche in anteprima
        locandina = SuggestionCornerLocandina(**{
            k: form.cleaned_data.get(k, getattr(base, k, "") if base else "")
            for k in sc_forms.LocandinaForm.Meta.fields if k != "predefinita"
        })
        if not locandina.titolo:
            locandina.titolo = "Suggestion Corner"
    else:
        locandina = get_object_or_404(SuggestionCornerLocandina, pk=request.GET.get("preset") or 0)

    pdf = render_locandina_pdf(locandina, url_form_pubblico(request))
    response = HttpResponse(pdf, content_type="application/pdf")
    nome_file = f"locandina-suggestion-corner-{slugify(locandina.nome) or 'anteprima'}.pdf"
    tipo = "attachment" if request.GET.get("scarica") or request.POST.get("scarica") else "inline"
    response["Content-Disposition"] = f'{tipo}; filename="{nome_file}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response
