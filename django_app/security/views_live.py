"""Barra di stato live, anteprime a pannello, azioni massive e controlli AI del SOC."""
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import SecurityAlert, SecurityEventRecord, SecurityIncident, SecurityRemediationTicket, Severity
from .permissions import can_view_security_center


def _denied(request):
    from security.views import _security_center_denied

    return _security_center_denied(request)


def _ids(request, name):
    return [int(v) for v in request.POST.getlist(name) if str(v).isdigit()]


def _back(request, default):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return default


# --- Barra di stato ------------------------------------------------------------------------

def live_strip(request):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    from .services.live_status import live_status

    return render(request, "security/partials/live_strip.html", {"live": live_status(request.user)})


# --- Anteprime -----------------------------------------------------------------------------

def preview(request, kind, pk=None):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    now = timezone.now()
    if kind == "alert":
        from .services.alert_lifecycle import ACTIVE_ALERT_STATUSES

        alert = get_object_or_404(SecurityAlert.objects.select_related("source", "event", "event__asset"), pk=pk)
        return render(request, "security/partials/preview_alert.html", _preview_alert_context(alert, alert.status in ACTIVE_ALERT_STATUSES))
    if kind == "ticket":
        from .services.cases import ACTIVE_CASE_STATUSES, case_alerts, case_timeline

        case = get_object_or_404(SecurityRemediationTicket.objects.select_related("source", "assignee"), pk=pk)
        tasks = list(case.tasks.all())
        return render(request, "security/partials/preview_ticket.html", {
            "case": case, "alerts": case_alerts(case)[:5], "tasks": tasks, "tasks_open": sum(1 for t in tasks if not t.done),
            "timeline": case_timeline(case)[:5], "active": case.status in ACTIVE_CASE_STATUSES,
        })
    if kind == "incident":
        from .services.incidents import deadlines

        incident = get_object_or_404(SecurityIncident.objects.select_related("owner"), pk=pk)
        return render(request, "security/partials/preview_incident.html", {
            "incident": incident, "deadlines": deadlines(incident, now), "logs": incident.logs.all()[:4],
            "tickets": incident.tickets.order_by("-updated_at")[:4],
        })
    if kind == "event":
        event = get_object_or_404(SecurityEventRecord.objects.select_related("source", "asset", "report"), pk=pk)
        from .templatetags.security_i18n import ui_label

        payload = [(ui_label(k), v) for k, v in (event.payload or {}).items() if not isinstance(v, (dict, list)) and k not in {"dedup_hash", "raw_body_hash", "fingerprint"}][:12]
        return render(request, "security/partials/preview_event.html", {"event": event, "payload": payload, "alerts": event.alerts.all()[:3]})
    if kind == "pc":
        from .services.pc_overview import pc_overview

        name = request.GET.get("nome", "").strip()
        data = pc_overview(name) if name else None
        if data is None:
            raise Http404("Nessun dato SOC per questo dispositivo.")
        return render(request, "security/partials/preview_pc.html", _preview_pc_context(data))
    if kind == "backup_job":
        context = _preview_job_context(request.GET.get("nome", "").strip(), request.GET.get("giorni", ""))
        if context is None:
            raise Http404("Nessuna esecuzione di questo job nel periodo.")
        return render(request, "security/partials/preview_backup_job.html", context)
    raise Http404("Anteprima non disponibile.")


def _preview_pc_context(data):
    from .services import backup_azioni

    jobs = sorted(backup_azioni.jobs_dei_pc([data["name"]]), key=str.casefold)
    backup_alerts = backup_azioni.alert_aperti(jobs)
    # Gli alert di backup hanno il loro riquadro con le azioni: non si ripetono nell'elenco generale.
    shown = {a.pk for a in backup_alerts}
    gia_contati = sum(1 for a in data["alerts"] if a.pk in shown)
    # «Alert aperti» conta anche quelli di backup, che non sempre sono legati al dispositivo.
    data = {**data, "alerts": [a for a in data["alerts"] if a.pk not in shown],
            "alert_count": data["alert_count"] + len(backup_alerts) - gia_contati}
    return {"pc": data, "name_q": quote(data["name"]), "backup_alerts": backup_alerts, "backup_jobs": jobs,
            "esiti": backup_azioni.ESITI}


def _preview_job_context(name, giorni=""):
    from .services import backup_azioni
    from .services.backup_center import PERIODS

    days = int(giorni) if str(giorni).isdigit() and int(giorni) in {d for d, _l in PERIODS} else 30
    job = backup_azioni.job_detail(name, days) if name else None
    if job is None and name and days < 90:
        # Dal Log si apre anche un job fermo da più del periodo scelto.
        job = backup_azioni.job_detail(name, 90)
    if job is None:
        return None
    return {"job": job, "name_q": quote(job["name"]), "esiti": backup_azioni.ESITI}


def _preview_alert_context(alert, active):
    from .services import alert_simili

    dati = alert_simili.simili(alert)
    return {
        "alert": alert, "active": active,
        "rule": (alert.decision_trace or {}).get("rule") or (alert.decision_trace or {}).get("decision") or "—",
        "logs": alert.action_logs.order_by("-created_at")[:5],
        "case": alert.linked_remediation_tickets.order_by("-updated_at").first() or alert.tickets.order_by("-updated_at").first(),
        "ctx": dati["contesto"], "simili": dati["criteri"], "simili_max_pk": dati["max_pk"],
        "simili_aperti": sum(c["n_aperti"] for c in dati["criteri"]), "esiti": alert_simili.ESITI,
    }


@require_POST
def alert_simili_chiudi(request, pk):
    """Dal pannello laterale: chiude l'alert e i simili aperti (stessa CVE, stesso software, stesso PC o stesso problema)."""
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    from .services import alert_simili
    from .services.alert_lifecycle import ACTIVE_ALERT_STATUSES

    alert = get_object_or_404(SecurityAlert.objects.select_related("source", "event", "event__asset"), pk=pk)
    motivo = request.POST.get("motivo", "").strip()[:500]
    esito = request.POST.get("esito", "")
    criterio = request.POST.get("criterio", "")
    max_pk = request.POST.get("max_pk", "")
    errore = ""
    if not motivo:
        errore = "Scrivi il motivo: resta su ogni alert chiuso."
    elif esito not in dict(alert_simili.ESITI):
        errore = "Scegli come chiudere."
    else:
        try:
            fatti = alert_simili.chiudi_simili(alert, criterio=criterio, esito=esito, motivo=motivo, user=request.user,
                                               max_pk=int(max_pk) if max_pk.isdigit() else None)
        except ValueError:
            errore = "Criterio non valido."
        else:
            esito_label = dict(alert_simili.ESITI)[esito]
            messaggio = f"{fatti} alert chius{'o' if fatti == 1 else 'i'} come «{esito_label}»." if fatti else "Nessun alert da chiudere: erano già stati gestiti."
    if errore:
        if request.headers.get("HX-Request") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            alert.refresh_from_db()
            context = _preview_alert_context(alert, alert.status in ACTIVE_ALERT_STATUSES)
            context["simili_errore"] = errore
            return render(request, "security/partials/preview_alert.html", context)
        messages.error(request, errore)
        return redirect("security:alert_detail", pk=alert.pk)
    if request.headers.get("HX-Request") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        alert.refresh_from_db()
        context = _preview_alert_context(alert, alert.status in ACTIVE_ALERT_STATUSES)
        context["simili_esito"] = messaggio
        return render(request, "security/partials/preview_alert.html", context)
    messages.success(request, messaggio)
    return redirect("security:segnalazioni")


# --- Controlli AI --------------------------------------------------------------------------

@require_POST
def incident_ai_check(request, pk):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    from .services.ai_explain import check_incident

    incident = get_object_or_404(SecurityIncident.objects.select_related("owner"), pk=pk)
    ai = check_incident(incident, user=request.user, refresh=request.POST.get("refresh") == "1")
    return render(request, "security/partials/ai_explanation.html", {"ai": ai})


@require_POST
def pc_ai_check(request):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    from .services.ai_explain import check_pc
    from .services.pc_overview import pc_overview

    data = pc_overview(request.POST.get("nome", "").strip())
    if data is None:
        raise Http404("Nessun dato SOC per questo dispositivo.")
    ai = check_pc(data, user=request.user, refresh=request.POST.get("refresh") == "1")
    return render(request, "security/partials/ai_explanation.html", {"ai": ai})


# --- Azioni massive ------------------------------------------------------------------------

@require_POST
def tickets_bulk(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services.cases import CASE_STATUSES, assign_case, set_case_status

    back = _back(request, "security:tickets_list")
    cases = list(SecurityRemediationTicket.objects.filter(pk__in=_ids(request, "ticket_ids")))
    if not cases:
        messages.error(request, "Nessun ticket selezionato.")
        return redirect(back)
    action = request.POST.get("action", "")
    done = 0
    if action in ("assign_me", "assign"):
        if action == "assign_me":
            user = request.user
        else:
            uid = request.POST.get("assignee", "")
            user = get_user_model().objects.filter(pk=int(uid), is_active=True).first() if uid.isdigit() else None
            if user is None:
                messages.error(request, "Scegli a chi assegnare i ticket.")
                return redirect(back)
        for case in cases:
            if case.assignee_id != user.pk:
                assign_case(case, user, user=request.user)
                done += 1
        messages.success(request, f"{done} ticket assegnati a {user.get_full_name() or user.get_username()}.")
        return redirect(back)
    status = request.POST.get("status", "")
    if action == "status" and status in CASE_STATUSES:
        reason = request.POST.get("reason", "").strip()
        closing = status in ("resolved", "closed", "false_positive")
        if closing and not reason:
            messages.error(request, "Per chiudere più ticket insieme scrivi l'esito: resta nella traccia di ognuno.")
            return redirect(back)
        skipped = 0
        for case in cases:
            if case.status == status:
                continue
            try:
                set_case_status(case, status, user=request.user, reason=reason, close_alerts=closing and request.POST.get("close_alerts") == "1")
                done += 1
            except Exception:  # noqa: BLE001 - es. riapertura in conflitto con un caso attivo
                skipped += 1
        messages.success(request, f"Stato aggiornato su {done} ticket" + (f"; {skipped} non modificabili." if skipped else "."))
        return redirect(back)
    messages.error(request, "Azione non supportata.")
    return redirect(back)


@require_POST
def incidents_bulk(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services import incidents as svc

    back = _back(request, "security:incidents")
    incidents = list(SecurityIncident.objects.filter(pk__in=_ids(request, "incident_ids")))
    if not incidents:
        messages.error(request, "Nessun incidente selezionato.")
        return redirect(back)
    action = request.POST.get("action", "")
    done = 0
    for incident in incidents:
        before = svc.snapshot(incident)
        if action == "owner_me":
            incident.owner = request.user
        elif action == "status" and request.POST.get("status") in dict(SecurityIncident.STATUS_CHOICES):
            incident.status = request.POST["status"]
        else:
            messages.error(request, "Azione non supportata.")
            return redirect(back)
        incident.save()
        done += bool(svc.save_changes(incident, before, request.user))
    messages.success(request, f"{done} incident{'e aggiornato' if done == 1 else 'i aggiornati'}.")
    return redirect(back)


@require_POST
def events_bulk(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services import event_triage as triage

    back = _back(request, "security:events")
    events = list(SecurityEventRecord.objects.filter(pk__in=_ids(request, "event_ids")).select_related("source"))
    if not events:
        messages.error(request, "Nessun evento selezionato.")
        return redirect(back)
    action = request.POST.get("action", "")
    if action == "ok":
        for event in events:
            triage.confirm_ok(event, user=request.user)
        messages.success(request, f"{len(events)} eventi confermati a posto.")
        return redirect(back)
    if action == "promote":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "Scrivi perché sono allarmi: resta nell'alert e insegna al sistema.")
            return redirect(back)
        severity = request.POST.get("severity") if request.POST.get("severity") in dict(Severity.choices) else Severity.WARNING
        created = 0
        for event in events:
            _alert, _rule, was_created = triage.promote_event(event, user=request.user, severity=severity, reason=reason, learn=False)
            created += bool(was_created)
        messages.success(request, f"{created} alert creati da {len(events)} eventi (gli altri sono finiti in alert già aperti).")
        return redirect(back)
    messages.error(request, "Azione non supportata.")
    return redirect(back)


_BACKUP_ACTIONS = ("case", "acknowledge", "close")


def _backup_selection(request):
    """Job o PC scelti: ``jobs`` dalla tabella Per job, ``devices`` dalla tabella Per PC."""
    from .services.backup_azioni import MAX_ITEMS, alert_aperti, jobs_dei_pc

    # dict.fromkeys: dal Log arrivano più esecuzioni dello stesso job.
    jobs = list(dict.fromkeys(n.strip() for n in request.POST.getlist("jobs") if n.strip()))[:MAX_ITEMS]
    devices = list(dict.fromkeys(n.strip() for n in request.POST.getlist("devices") if n.strip()))[:MAX_ITEMS]
    alerts = alert_aperti(jobs if jobs else jobs_dei_pc(devices)) if (jobs or devices) else []
    return jobs, devices, alerts


def _backup_alert_action(request, alerts):
    """Presa in carico o chiusura degli alert: ritorna (messaggio, errore)."""
    from .services import backup_azioni

    action = request.POST.get("action", "")
    if action == "acknowledge":
        fatti = backup_azioni.prendi_in_carico(alerts, request.user)
        return (f"{fatti} alert pres{'o' if fatti == 1 else 'i'} in carico." if fatti else "Nessun alert nuovo da prendere in carico."), ""
    esito = request.POST.get("esito", "")
    motivo = request.POST.get("motivo", "").strip()[:500]
    if esito not in dict(backup_azioni.ESITI):
        return "", "Scegli come chiudere gli alert."
    if not motivo:
        return "", "Scrivi il motivo: resta su ogni alert chiuso."
    fatti = backup_azioni.chiudi(alerts, esito=esito, motivo=motivo, user=request.user)
    label = dict(backup_azioni.ESITI)[esito]
    return (f"{fatti} alert chius{'o' if fatti == 1 else 'i'} come «{label}»." if fatti else "Nessun alert aperto da chiudere."), ""


@require_POST
def backup_bulk_case(request):
    """Azioni sui PC o sui job selezionati nella pagina Backup: ticket, presa in carico, chiusura degli alert."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services import backup_azioni

    back = _back(request, "security:backup")
    jobs, devices, alerts = _backup_selection(request)
    if not jobs and not devices:
        messages.error(request, "Nessun PC o job selezionato.")
        return redirect(back)
    action = request.POST.get("action", "case")
    if action not in _BACKUP_ACTIONS:
        messages.error(request, "Azione non supportata.")
        return redirect(back)
    if action == "case":
        case = backup_azioni.apri_ticket(jobs=jobs, devices=devices, user=request.user, title=request.POST.get("title", ""))
        if case is None:
            messages.error(request, "Nessun report di backup: impossibile collegare il ticket a una sorgente.")
            return redirect(back)
        n, cosa = (len(devices), "PC") if devices else (len(jobs), "job")
        messages.success(request, f"Ticket #{case.pk} aperto con {n} {cosa} e assegnato a te.")
        return redirect("security:case_detail", pk=case.pk)
    messaggio, errore = _backup_alert_action(request, alerts)
    if errore:
        messages.error(request, errore)
    else:
        messages.success(request, messaggio)
    return redirect(back)


@require_POST
def backup_pannello_azione(request):
    """Dal pannello laterale di un job o di un PC: presa in carico o chiusura dei suoi alert di backup.

    Risponde con il pannello rifatto e l'esito dentro (``data-drawer-replace``).
    """
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    from .services.pc_overview import pc_overview

    kind = request.POST.get("kind", "")
    name = request.POST.get("nome", "").strip()
    if kind not in ("job", "pc") or not name or request.POST.get("action") not in ("acknowledge", "close"):
        raise Http404("Azione non disponibile.")
    _jobs, _devices, alerts = _backup_selection(request)
    messaggio, errore = _backup_alert_action(request, alerts)
    if kind == "job":
        context = _preview_job_context(name, request.POST.get("giorni", ""))
        template = "security/partials/preview_backup_job.html"
    else:
        data = pc_overview(name)
        context = _preview_pc_context(data) if data else None
        template = "security/partials/preview_pc.html"
    if context is None:
        raise Http404("Nessun dato per questo elemento.")
    context["azione_esito"], context["azione_errore"] = messaggio, errore
    return render(request, template, context)
