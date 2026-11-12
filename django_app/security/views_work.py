"""Impostazioni avvisi, «Il mio lavoro», ricerca unica e scheda PC del SOC."""
import logging
from urllib.parse import quote, urlencode

from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    BackupJobRecord,
    SecurityAlert,
    SecurityAsset,
    SecurityIncident,
    SecurityNotificationChannel,
    SecurityNotificationLog,
    SecurityRemediationTicket,
    SecurityVulnerabilityFinding,
)
from .permissions import can_view_security_center
from .services import soc_settings
from .services.configuration import can_configure_soc, can_manage_security_config
from .templatetags.security_i18n import ui_label

logger = logging.getLogger(__name__)


def _denied(request):
    from security.views import _security_center_denied

    return _security_center_denied(request)


# --- Impostazioni ----------------------------------------------------------------------

def settings_page(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    can_edit = can_configure_soc(request)
    errors = []
    if request.method == "POST":
        if not can_edit:
            return _denied(request)
        values, errors = soc_settings.parse_post(request.POST)
        if not errors:
            changed = soc_settings.save(values, request.user)
            messages.success(request, f"Impostazioni salvate ({changed} modific{'a' if changed == 1 else 'he'})." if changed else "Nessuna modifica.")
            return redirect("security:soc_settings")
    from .services import proactive_alerts

    preview = {"incidenti": None, "backup": None, "report": None}
    try:
        preview["incidenti"] = len(proactive_alerts.incident_items())
        preview["backup"] = len(proactive_alerts.backup_items())
        preview["report"] = _next_report_date()
    except Exception:  # noqa: BLE001 - l'anteprima non deve impedire di salvare le impostazioni
        pass
    events = [proactive_alerts.EVENT_INCIDENT, proactive_alerts.EVENT_BACKUP, proactive_alerts.EVENT_REPORT]
    from .services import veeam_api, watchguard_api

    return render(request, "security/soc_settings.html", {
        "wg": watchguard_api.riepilogo(),
        "veeam_cred": veeam_api.riepilogo(),
        "sections": soc_settings.form_sections(),
        "channels": list(SecurityNotificationChannel.objects.order_by("name")),
        "can_edit": can_edit,
        "errors": errors,
        "preview": preview,
        "recent_logs": SecurityNotificationLog.objects.filter(event_kind__in=events).select_related("channel")[:12],
        "event_labels": {
            proactive_alerts.EVENT_INCIDENT: "Scadenza incidente",
            proactive_alerts.EVENT_BACKUP: "Backup PC",
            proactive_alerts.EVENT_REPORT: "Report periodico",
        },
    })


def _next_report_date():
    from datetime import timedelta

    today = timezone.localdate()
    if soc_settings.value("report.auto.frequenza") == "monthly":
        return (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


@require_POST
def settings_run_now(request):
    if not can_configure_soc(request):
        return _denied(request)
    from .services.proactive_alerts import run_scheduled_notifications

    result = run_scheduled_notifications()
    sent = sum(v for v in result.values() if isinstance(v, int))
    errors = [f"{k}: {v}" for k, v in result.items() if not isinstance(v, int)]
    if errors:
        messages.error(request, "Controllo eseguito con errori: " + "; ".join(errors))
    else:
        messages.success(request, f"Controllo eseguito: {sent} avvis{'o' if sent == 1 else 'i'} inviat{'o' if sent == 1 else 'i'} (quelli già mandati non ripartono).")
    return redirect("security:soc_settings")


# --- Da fare ---------------------------------------------------------------------------

def my_work(request):
    """«Da fare»: tutto cio' che e' aperto, per urgenza. Il team e' piccolo: niente filtro per persona."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services.alert_lifecycle import ACTIVE_ALERT_STATUSES
    from .services.cases import ACTIVE_CASE_STATUSES
    from .services.incidents import ACTIVE_STATUSES, next_open_deadline

    now = timezone.now()
    incidents = list(SecurityIncident.objects.filter(status__in=ACTIVE_STATUSES).order_by("detected_at"))
    for incident in incidents:
        incident.next_deadline = next_open_deadline(incident, now)
    incidents.sort(key=lambda i: (i.next_deadline is None, i.next_deadline["due_at"] if i.next_deadline else i.detected_at))
    tickets_qs = SecurityRemediationTicket.objects.filter(status__in=ACTIVE_CASE_STATUSES)
    alerts_qs = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES)
    # Per urgenza: prima la gravità, poi il più recente.
    from django.db.models import Case, IntegerField, Value, When

    from .models import Severity

    rank = Case(*[When(severity=v, then=Value(i)) for i, (v, _l) in enumerate(Severity.choices)], default=Value(-1), output_field=IntegerField())
    tickets = list(tickets_qs.select_related("source").annotate(_rank=rank).order_by("-_rank", "-updated_at")[:50])
    alerts = list(alerts_qs.select_related("source").annotate(_rank=rank).order_by("-_rank", "-updated_at")[:30])
    # Totali pieni (come «segnalazioni aperte»): le liste mostrano solo le più urgenti.
    n_tickets, n_alerts = tickets_qs.count(), alerts_qs.count()
    return render(request, "security/my_work.html", {
        "incidents": incidents, "tickets": tickets, "alerts": alerts,
        "n_tickets": n_tickets, "n_alerts": n_alerts,
        "altri_ticket": n_tickets - len(tickets), "altri_alert": n_alerts - len(alerts),
        "total": len(incidents) + n_tickets + n_alerts,
    })


# --- Segnalazioni ----------------------------------------------------------------------

SEGNALAZIONI_PER_PAGINA = 40


def segnalazioni(request):
    """Alert, ticket e incidenti in un elenco solo, dal più urgente; ogni riga apre l'anteprima laterale."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from django.core.paginator import Paginator

    from .services import segnalazioni as svc

    tipo = request.GET.get("tipo", "")
    stato = request.GET.get("stato", "aperte")
    severity = request.GET.get("gravita", "")
    q = request.GET.get("q", "").strip()[:100]
    urgenti = request.GET.get("urgenti") == "1"
    scadenza = request.GET.get("scadenza") == "1"
    if request.GET.get("formato") == "csv":
        # Tutte le righe del filtro, anche oltre il taglio per tipo della pagina.
        return _segnalazioni_csv(request, svc.elenco(tipo=tipo, stato=stato, severity=severity, q=q, urgenti=urgenti,
                                                     scadenza=scadenza, tutte=True))
    righe = svc.elenco(tipo=tipo, stato=stato, severity=severity, q=q, urgenti=urgenti, scadenza=scadenza)
    tipo = tipo if tipo in dict(svc.KINDS) else ""
    stato = stato if stato in {"aperte", "chiuse", "tutte"} else "aperte"
    severity = severity if severity in dict(svc.GRAVITA) else ""
    page = Paginator(righe, SEGNALAZIONI_PER_PAGINA).get_page(request.GET.get("page"))
    counts = svc.conteggi(stato=stato, severity=severity, q=q)
    if urgenti:
        # con «Solo urgenti» i chip contano le urgenti: il numero sul chip è sempre uguale alle righe che apre
        from collections import Counter

        per_tipo = Counter(r["kind"] for r in svc.elenco(urgenti=True))
        counts = {k: per_tipo.get(k, 0) for k, _l in svc.KINDS}
    # Le righe si fermano a PER_KIND_LIMIT per tipo: la pagina lo dice invece di
    # mostrare «1200» sul chip sopra una lista di 300. I conteggi seguono stato,
    # gravità e ricerca scelti, così anche con «Chiuse» o «Tutte» il taglio si vede.
    tipi_visibili = [tipo] if tipo else [k for k, _l in svc.KINDS]
    troncata = any(counts[k] > svc.PER_KIND_LIMIT for k in tipi_visibili) and not (urgenti or scadenza)

    def link(**cambi):
        params = {"tipo": tipo, "stato": stato, "gravita": severity, "q": q, "urgenti": "1" if urgenti else "", "scadenza": "1" if scadenza else ""}
        params.update(cambi)
        return "?" + urlencode({k: v for k, v in params.items() if v and not (k == "stato" and v == "aperte")})

    return render(request, "security/segnalazioni.html", {
        "page": page, "righe_totali": len(righe), "tipo": tipo, "stato": stato, "gravita": severity, "q": q,
        "urgenti": urgenti, "scadenza": scadenza, "n_urgenti": svc.conta_urgenti(),
        "troncata": troncata, "limite_per_tipo": svc.PER_KIND_LIMIT, "totale_filtri": sum(counts[k] for k in tipi_visibili),
        "link_urgenti": link(urgenti="" if urgenti else "1", scadenza="", page=""),
        "counts": counts, "counts_totale": sum(counts.values()),
        "chips_tipo": [{"value": "", "label": "Tutte", "count": sum(counts.values()), "active": not tipo, "url": link(tipo="", page="")}] + [
            {"value": k, "label": label, "count": counts[k], "active": tipo == k, "url": link(tipo=k, page="")} for k, label in svc.KINDS
        ],
        "chips_stato": [
            {"value": "aperte", "label": "Da gestire", "active": stato == "aperte", "url": link(stato="aperte", page="")},
            {"value": "chiuse", "label": "Chiuse", "active": stato == "chiuse", "url": link(stato="chiuse", page="")},
            {"value": "tutte", "label": "Tutte", "active": stato == "tutte", "url": link(stato="tutte", page="")},
        ],
        "gravita_choices": svc.GRAVITA,
        "ticket_stati": _stati_ticket_bulk(), "incident_stati": SecurityIncident.STATUS_CHOICES,
        "pagina_prec": link(page=page.previous_page_number()) if page.has_previous() else "",
        "pagina_succ": link(page=page.next_page_number()) if page.has_next() else "",
    })


def _segnalazioni_csv(request, righe):
    from .services import esporta_csv

    def stato(r):
        if r["kind"] == "incident":
            return dict(SecurityIncident.STATUS_CHOICES).get(r["status"], r["status"])
        return esporta_csv.etichetta(r["status"])

    return esporta_csv.risposta(
        request, "segnalazioni",
        ["Tipo", "N.", "Titolo", "Gravità", "Stato", "Urgente", "Dove", "Dal", "Chi", "Prossima notifica di legge", "Scade il"],
        ([r["kind_label"], r["pk"], r["title"], esporta_csv.etichetta(r["severity"]), stato(r), esporta_csv.si_no(r["urgente"]),
          r["where"], esporta_csv.data_ora(r["since"]), r["who"],
          r["deadline"]["label"] if r.get("deadline") else "", esporta_csv.data_ora(r["deadline"]["due_at"]) if r.get("deadline") else ""]
         for r in righe),
        azione="soc_segnalazioni_export", filtri=esporta_csv.filtri_get(request, "tipo", "stato", "gravita", "q", "urgenti", "scadenza"),
    )


def _stati_ticket_bulk():
    from .templatetags.security_i18n import ui_label

    return [(v, ui_label(v)) for v in ("in_progress", "resolved", "closed", "false_positive")]


# --- Copertura dei PC ----------------------------------------------------------------------

def pc_copertura(request):
    """Dispositivi: una riga per PC o server con fonti, backup, CVE e asset del registro collegato."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services import pc_copertura as svc

    can_manage = can_manage_security_config(request.user)
    if request.method == "POST":
        from .services.asset_signals import link, suggest_hub_asset
        from .views_soc import _assets_post

        if not can_manage:
            messages.error(request, "Serve il permesso di configurazione del Security Center.")
        elif request.POST.get("action") == "windows_lavoro":
            from .services import windows_lavoro

            try:
                caso = windows_lavoro.apri_lavoro(request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(request.get_full_path())
            messages.success(request, "Piano di aggiornamento aperto: le attività dei PC si spuntano da sole quando passano a una release supportata.")
            return redirect("security:case_detail", pk=caso.pk)
        elif request.POST.get("action") == "confirm_selected":
            # «Collega gli asset proposti» sui PC spuntati: la stessa proposta e lo stesso collegamento di «Conferma» della riga.
            scelti = {n.strip().casefold() for n in request.POST.getlist("devices") if n.strip()}
            fatti = 0
            for r in svc.righe():
                if r["nome"].casefold() in scelti and r["soc_da_collegare"] and r["proposta"]:
                    link(r["soc_da_collegare"], r["proposta"], actor=request.user, request=request)
                    fatti += 1
            if fatti:
                messages.success(request, f"{fatti} dispositiv{'o collegato' if fatti == 1 else 'i collegati'} all'asset proposto.")
            if len(scelti) > fatti:
                messages.warning(request, f"{len(scelti) - fatti} dei selezionati senza una proposta di collegamento: lasciati com'erano.")
        else:
            _assets_post(request, link, suggest_hub_asset)
        return redirect(request.get_full_path())

    rows = svc.righe()
    codice = request.GET.get("f", "tutti")
    codice = codice if codice in dict(svc.FILTRI + svc.FILTRI_LINK) else "tutti"
    q = request.GET.get("q", "").strip()[:100]
    visibili = svc.filtra(rows, codice)
    if q:
        needle = q.casefold()
        visibili = [r for r in visibili if needle in r["nome"].casefold() or (r["intune"] and needle in (r["intune"].utente_nome or "").casefold())
                    or (r["rete"] and needle in (r["rete"].ip, r["rete"].mac))]
    if request.GET.get("formato") == "csv":
        return _pc_csv(request, visibili, codice, q)
    counts = svc.conteggi(rows)
    from .services import alert_doppioni, windows_lavoro

    bloccati = alert_doppioni.dispositivi_bloccati_per_pc(30)
    return render(request, "security/pc_copertura.html", {
        "bloccati": bloccati, "bloccati_totale": sum(b["blocchi"] for b in bloccati),
        "bloccati_aperto": request.GET.get("vista") == "bloccati",
        "rows": visibili, "totale": len(rows), "q": q, "codice": codice, "can_manage": can_manage,
        "windows_da_aggiornare": counts["sistema_fuori"] + counts["sistema_in_scadenza"],
        "windows_fuori": counts["sistema_fuori"], "windows_in_scadenza": counts["sistema_in_scadenza"],
        "windows_lavoro": windows_lavoro.riepilogo(),
        "filtri": [{"code": c, "label": label, "count": counts[c], "active": c == codice} for c, label in svc.FILTRI],
        "intune_totale": sum(1 for r in rows if r["intune"]),
        "collegati": len(svc.filtra(rows, "collegati")),
        "n_proposte": sum(1 for r in rows if r["proposta"]),
    })


def _pc_csv(request, righe, codice, q):
    """I dispositivi del filtro e della ricerca, con le stesse colonne della pagina."""
    from .services import esporta_csv

    def sistema(r):
        s = r.get("sistema")
        if not s:
            return ""
        return s["nome"] + (" · fuori supporto" if s["fuori"] else (" · in scadenza" if s["in_scadenza"] else ""))

    def stato_intune(r):
        if r["problemi"]:
            return ", ".join(r["problemi"])
        if r["intune"]:
            return "Conforme" if r["intune"].conformita == "compliant" else "Nessun problema"
        return ""

    def asset(r):
        if r["asset"]:
            return r["asset"].asset_tag
        return f"Proposto: {r['proposta'].asset_tag}" if r["proposta"] else ""

    return esporta_csv.risposta(
        request, "dispositivi",
        ["Dispositivo", "Utente", "Produttore e modello", "Indirizzo IP", "Sistema", "Fine aggiornamenti", "Intune", "WatchGuard",
         "Defender", "Backup", "Ultimo backup", "CVE", "CVE gravi", "CVE sfruttate (KEV)", "Stato Intune", "Asset del registro"],
        ([r["nome"], r["intune"].utente_nome if r["intune"] else "",
          f"{r['intune'].produttore} {r['intune'].modello}".strip() if r["intune"] else "",
          r["rete"].ip if r["rete"] else "", sistema(r), esporta_csv.data(r["sistema"]["fine"]) if r.get("sistema") else "",
          esporta_csv.si_no(r["intune"]), esporta_csv.si_no(r["watchguard"]), esporta_csv.si_no(r["defender"]),
          r["backup"]["last_label"] if r["backup"] else "nessuno", esporta_csv.data_ora(r["backup"]["last_at"]) if r["backup"] else "",
          r["cve"]["cves"] if r["cve"] else 0, r["cve"]["gravi"] if r["cve"] else 0, r["cve"]["kev"] if r["cve"] else 0,
          stato_intune(r), asset(r)] for r in righe),
        azione="soc_dispositivi_export", filtri={"f": codice, "q": q},
    )


# --- Ricerca ---------------------------------------------------------------------------

SEARCH_LIMIT = 8


def search(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    query = request.GET.get("q", "").strip()[:100]
    groups = []
    if len(query) >= 2:
        groups = [
            ("Incidenti", [
                {"title": f"{i.code} · {i.title}", "meta": f"{i.get_status_display()} · rilevato {timezone.localtime(i.detected_at):%d/%m/%Y}", "url": f"/soc/incidenti/{i.pk}/"}
                for i in SecurityIncident.objects.filter(Q(code__icontains=query) | Q(title__icontains=query) | Q(csirt_reference__icontains=query)).order_by("-detected_at")[:SEARCH_LIMIT]
            ]),
            ("Ticket", [
                {"title": f"#{t.pk} · {t.title}", "meta": f"{ui_label(t.status)} · {t.source.name}", "url": f"/soc/tickets/{t.pk}/"}
                for t in SecurityRemediationTicket.objects.filter(Q(title__icontains=query) | Q(cve__icontains=query) | Q(affected_product__icontains=query)).select_related("source").order_by("-updated_at")[:SEARCH_LIMIT]
            ]),
            ("Alert", [
                {"title": a.title, "meta": f"{ui_label(a.severity)} · {ui_label(a.status)} · {timezone.localtime(a.created_at):%d/%m/%Y}", "url": f"/soc/alerts/{a.pk}/"}
                for a in SecurityAlert.objects.filter(title__icontains=query).order_by("-updated_at")[:SEARCH_LIMIT]
            ]),
            ("PC e server", [
                {"title": name, "meta": "scheda del dispositivo", "url": f"/soc/pc/?nome={quote(name)}"}
                for name in _device_names(query)
            ]),
            ("Vulnerabilità", [
                {"title": f"{f.cve} · {f.affected_product}", "meta": f"CVSS {f.cvss:.1f} · {f.exposed_devices} dispositivi".replace(".", ","), "url": f"/soc/tickets/?q={quote(f.cve)}"}
                for f in SecurityVulnerabilityFinding.objects.filter(Q(cve__icontains=query) | Q(affected_product__icontains=query)).order_by("-last_seen_at")[:SEARCH_LIMIT]
            ]),
        ]
        groups = [(label, rows) for label, rows in groups if rows]
    return render(request, "security/search.html", {"query": query, "groups": groups, "too_short": 0 < len(query) < 2})


def _device_names(query):
    """Nomi dei PC: dispositivi SOC e PC citati nei backup degli ultimi 90 giorni."""
    from datetime import timedelta

    from .services.backup_center import device_runs

    names = {h.casefold(): h for h in SecurityAsset.objects.filter(hostname__icontains=query).values_list("hostname", flat=True)[:50]}
    since = timezone.now() - timedelta(days=90)
    needle = query.casefold()
    for record in BackupJobRecord.objects.filter(created_at__gte=since).only("payload", "status", "job_name", "completed_at", "started_at", "created_at")[:3000]:
        for run in device_runs(record):
            if needle in run["device"].casefold():
                names.setdefault(run["device"].casefold(), run["device"])
        if len(names) >= SEARCH_LIMIT * 2:
            break
    return sorted(names.values(), key=str.casefold)[:SEARCH_LIMIT]


# --- Scheda PC -------------------------------------------------------------------------

def pc_detail(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services.pc_overview import pc_scheda

    name = request.GET.get("nome", "").strip()
    if not name:
        raise Http404("Dispositivo non indicato.")
    data = pc_scheda(name)
    if data is None:
        raise Http404("Nessun dato SOC per questo dispositivo.")
    return render(request, "security/pc_detail.html", {"pc": data})


# --- WatchGuard (API): credenziali, patch e protezione ------------------------------------

@require_POST
def watchguard_credenziali(request):
    """Salva, prova o cancella le credenziali API WatchGuard (solo chi configura il SOC)."""
    if not can_configure_soc(request):
        return _denied(request)
    from .services import watchguard_api as wg

    azione = request.POST.get("azione", "")
    if azione == "cancella":
        wg.cancella_credenziali(request.user)
        messages.success(request, "Credenziali API WatchGuard cancellate.")
    elif azione == "prova":
        try:
            esito = wg.prova()
            messages.success(request, f"Connessione a WatchGuard riuscita: l'account vede {esito['pc'] if esito['pc'] is not None else 'i'} PC.")
        except wg.WatchGuardError as exc:
            messages.error(request, f"Connessione a WatchGuard non riuscita: {exc}")
        except Exception as exc:  # noqa: BLE001 - rete, DNS, certificati
            messages.error(request, f"Connessione a WatchGuard non riuscita ({type(exc).__name__}).")
    else:
        errori = wg.salva_credenziali({c: request.POST.get(c, "") for c in wg.CAMPI}, request.user)
        if errori:
            messages.error(request, " ".join(errori))
        else:
            messages.success(request, "Credenziali API WatchGuard salvate (cifrate). Prova la connessione, poi accendi le letture.")
    return redirect(reverse("security:soc_settings") + "#watchguard-api")


@require_POST
def veeam_credenziali(request):
    """Salva, prova o cancella le credenziali API Veeam (solo chi configura il SOC)."""
    if not can_configure_soc(request):
        return _denied(request)
    from .services import veeam_api

    azione = request.POST.get("azione", "")
    if azione == "cancella":
        veeam_api.cancella_credenziali(request.user)
        messages.success(request, "Credenziali API Veeam cancellate.")
    elif azione == "fidati":
        try:
            info = veeam_api.fidati_del_certificato(request.user)
            messages.success(
                request,
                f"Certificato del server salvato: intestato a «{info['intestato_a']}», emesso da «{info['emesso_da']}», "
                f"scade il {info['scadenza']:%d/%m/%Y}. Identificazione personale (SHA-1) {info['sha1']}: "
                "dev'essere uguale a quella del certificato sul server Veeam. Ora prova la connessione.")
            if info["scaduto"]:
                messages.warning(request, "Attenzione: il certificato del server Veeam è scaduto.")
        except veeam_api.VeeamError as exc:
            messages.error(request, str(exc))
    elif azione == "prova":
        try:
            esito = veeam_api.prova()
            messages.success(request, f"Connessione a Veeam riuscita: {esito['sessioni_backup']} sessioni di backup nelle ultime "
                                      f"24 ore, {len(esito['repository'])} repository.")
        except veeam_api.VeeamError as exc:
            messages.error(request, f"Connessione a Veeam non riuscita: {exc}")
        except Exception as exc:  # noqa: BLE001 - rete, DNS, certificati
            messages.error(request, f"Connessione a Veeam non riuscita ({type(exc).__name__}).")
    else:
        errori = veeam_api.salva_credenziali({c: request.POST.get(c, "") for c in veeam_api.CAMPI_FORM}, request.user,
                                             togli_ca=request.POST.get("togli_ca") == "on")
        if errori:
            messages.error(request, " ".join(errori))
        else:
            messages.success(request, "Credenziali API Veeam salvate (cifrate). Prova la connessione, poi accendi la lettura.")
    return redirect(reverse("security:soc_settings") + "#veeam-api")


def rete_indirizzi(request):
    """Rete (IP): gli indirizzi del DHCP/DNS di Windows Server, la stessa vista di Asset › Indirizzi IP.

    Dati e azioni di riga (Conferma, Scollega, Crea asset) vengono da ``assets.views_rete``, con gli stessi
    permessi sugli asset; la configurazione dei server resta in Asset.
    """
    if not can_view_security_center(request.user):
        return _denied(request)
    from assets import views_rete

    if request.method == "POST":
        views_rete.azione_riga(request)
        return redirect(request.get_full_path())
    data = views_rete.contesto_pagina(request)
    if request.GET.get("export") == "xlsx":
        return views_rete.export_excel(request, data)
    from core.middleware import acl_allows_path

    asset_url = reverse("assets:rete_indirizzi")
    # La guida è il «?» nell'intestazione del SOC (security_help.PAGE_HELP).
    return render(request, "security/rete_indirizzi.html", {
        **data,
        "puo_configurare": False,
        "asset_url": asset_url if acl_allows_path(asset_url, django_user=request.user, request=request) else "",
    })


@require_POST
def watchguard_patch_ai(request):
    """Spiegazione di una patch mancante dall'AI locale (con i problemi noti dal web se chiesti)."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services.ai_risoluzione import spiega_patch

    nome, programma = request.POST.get("nome", "")[:500], request.POST.get("programma", "")[:255]
    ai = spiega_patch(nome, programma, user=request.user, web=request.POST.get("web") == "1", refresh=request.POST.get("refresh") == "1")
    return render(request, "security/partials/ai_explanation.html", {"ai": ai})


VISTE_PATCH = ("patch", "pc", "protezione", "senza_agente", "errori")
PATCH_PER_PAGINA = 200  # la ricerca live della tabella vede solo la pagina: di solito tutto sta in una


def watchguard_pc(request):
    """Patch e protezione: quello che l'API WatchGuard dice dei PC, una vista alla volta.

    I riquadri in alto scelgono la vista (patch mancanti, PC, protezione, senza agente, installazioni
    fallite); ogni vista è una tabella filtrabile con selezione multipla (ticket per i PC) ed export CSV.
    Il dettaglio di una patch si apre nel pannello laterale (``preview`` kind «patch»). Il raggruppamento
    delle patch è in cache (``services/patch_mancanti.py``).
    """
    if not can_view_security_center(request.user):
        return _denied(request)
    from datetime import timedelta

    from django.core.paginator import Paginator

    from .models import WatchGuardDispositivo, WatchGuardPatch
    from .services import patch_mancanti
    from .services import watchguard_api as wg

    now = timezone.now()
    vista = request.GET.get("vista") if request.GET.get("vista") in VISTE_PATCH else "patch"
    dispositivi = list(WatchGuardDispositivo.objects.filter(presente=True).select_related("hub_asset"))
    gestiti = [d for d in dispositivi if d.gestito]
    vecchi = now - timedelta(days=7)
    protezione = sorted(
        (d for d in gestiti if not d.protetto or d.riavvio_richiesto or (d.ultima_connessione and d.ultima_connessione < vecchi)),
        key=lambda d: (d.protetto, not d.riavvio_richiesto, d.host))
    senza_agente = sorted((d for d in dispositivi if not d.gestito), key=lambda d: (d.hub_asset_id is None, d.host))
    dati = patch_mancanti.dati()
    patch, per_pc = dati["patch"], dati["pc"]
    errori_qs = (WatchGuardPatch.objects.filter(esito__in=WatchGuardPatch.ESITI_ERRORE, esito_il__gte=now - timedelta(days=14))
                 .select_related("hub_asset").order_by("-esito_il"))

    q = (request.GET.get("q") or "").strip()[:100]
    criticita = request.GET.get("criticita", "")
    filtri = {"criticita": criticita if criticita in patch_mancanti.CRITICITA_FILTRO else "",
              "kev": request.GET.get("kev") == "1", "errori": request.GET.get("errori") == "1",
              "nascondi_comprese": request.GET.get("comprese") == "0"}
    Q_ = q.upper()
    if vista == "patch":
        righe = patch_mancanti.filtra_patch(patch, q=q, **filtri)
        totale = len(patch)
    elif vista == "pc":
        righe = [x for x in per_pc if (not q or Q_ in x["nome"].upper()) and (not filtri["kev"] or x["kev"])
                 and (not filtri["errori"] or x["errori"])]
        totale = len(per_pc)
    elif vista == "protezione":
        righe = [d for d in protezione if not q or Q_ in f"{d.host_display or d.host} {d.sistema}".upper()]
        totale = len(protezione)
    elif vista == "senza_agente":
        righe = [d for d in senza_agente if not q or Q_ in f"{d.host_display} {d.host} {d.ip} {d.mac} {d.produttore_scheda}".upper()]
        totale = len(senza_agente)
    else:
        qs = errori_qs
        if q:
            qs = qs.filter(Q(host__icontains=q) | Q(host_display__icontains=q) | Q(nome__icontains=q))
        righe = list(qs[:500])
        totale = errori_qs.count()
    if request.GET.get("formato") == "csv":
        return _patch_pc_csv(vista, righe)

    pagina = Paginator(righe, PATCH_PER_PAGINA).get_page(request.GET.get("page"))
    parametri = {"vista": vista if vista != "patch" else "", "q": q, "criticita": filtri["criticita"],
                 "kev": "1" if filtri["kev"] else "", "errori": "1" if filtri["errori"] else "",
                 "comprese": "0" if filtri["nascondi_comprese"] else ""}
    query = urlencode({k: v for k, v in parametri.items() if v})
    filtrato = bool(q or filtri["criticita"] or filtri["kev"] or filtri["errori"] or filtri["nascondi_comprese"])
    attivi = {k: soc_settings.value(f"watchguard.api.{k}") for k in ("dispositivi", "software", "patch")}
    return render(request, "security/watchguard_pc.html", {
        "configurato": wg.configurato(), "attivi": attivi,
        "ultima": max((d.letto_il for d in dispositivi), default=None),
        "vista": vista, "pagina": pagina, "righe": list(pagina.object_list), "trovate": len(righe), "totale": totale,
        "patch": list(pagina.object_list) if vista == "patch" else [],
        "q": q, "filtri": filtri, "filtrato": filtrato, "query": query, "criticita_scelte": patch_mancanti.CRITICITA_FILTRO,
        "conta": {"patch": len(patch), "pc": len(per_pc), "protezione": len(protezione), "senza_agente": len(senza_agente),
                  "errori": errori_qs.count(), "kev": sum(1 for g in patch if g["kev"]),
                  "pc_kev": sum(1 for x in per_pc if x["kev"]), "gestiti": len(gestiti)},
        "ferme": dati["ferme"], "can_edit": can_manage_security_config(request.user),
    })


def _patch_pc_csv(vista: str, righe: list):
    """Export della vista di Patch e protezione, con i filtri applicati."""
    import csv

    from django.http import HttpResponse

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="patch-e-protezione-{vista}.csv"'
    resp.write("﻿")
    w = csv.writer(resp, delimiter=";")
    if vista == "patch":
        w.writerow(["Patch", "KB", "Programma", "Criticità", "Pubblicata il", "PC", "Installazioni fallite",
                    "CVE corrette", "CVE sfruttate", "Compresa in", "PC coinvolti"])
        for g in righe:
            w.writerow([g["nome"], g["kb"], g["programma"], g["criticita_label"],
                        g["rilasciata_il"].strftime("%d/%m/%Y") if g["rilasciata_il"] else "", len(g["pc"]), g["errori"],
                        " ".join(g["cve"]), " ".join(g["kev"]), " ".join(kb for kb, _ in g["compresa_in"]),
                        " ".join(r["nome"] for r in g["pc"])])
    elif vista == "pc":
        w.writerow(["PC", "Patch mancanti", "Con CVE sfruttate", "Critiche", "Installazioni fallite", "Già comprese", "CVE"])
        for x in righe:
            w.writerow([x["nome"], x["patch"], x["kev"], x["critiche"], x["errori"], x["comprese"], x["cve"]])
    elif vista == "protezione":
        w.writerow(["PC", "Sistema", "Agente", "Protezione", "Riavvio richiesto", "Ultima connessione"])
        for d in righe:
            w.writerow([d.host_display or d.host, d.sistema, d.agente, "" if d.protetto else d.protezione_label,
                        "sì" if d.riavvio_richiesto else "", d.ultima_connessione.strftime("%d/%m/%Y") if d.ultima_connessione else ""])
    elif vista == "senza_agente":
        w.writerow(["Nome", "IP", "MAC", "Scheda di rete", "Asset", "Visto il"])
        for d in righe:
            w.writerow([d.host_display, d.ip, d.mac, d.produttore_scheda, "sì" if d.hub_asset_id else "",
                        d.ultima_connessione.strftime("%d/%m/%Y") if d.ultima_connessione else ""])
    else:
        w.writerow(["PC", "Patch", "Esito", "Quando"])
        for p in righe:
            w.writerow([p.host_display or p.host, p.nome, p.esito_label,
                        timezone.localtime(p.esito_il).strftime("%d/%m/%Y %H:%M") if p.esito_il else ""])
    return resp


def watchguard_patch_installate(request):
    """Storico delle patch chiuse: PC, patch, CVE corrette e perché risultano chiuse (services/patch_storico.py)."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services import patch_storico

    dati = patch_storico.installate(
        periodo=request.GET.get("periodo") or patch_storico.PERIODO_DEFAULT,
        motivo_filtro=request.GET.get("motivo") or "",
        q=(request.GET.get("q") or "")[:100],
    )
    if request.GET.get("formato") == "csv":
        return _patch_installate_csv(request, dati)
    return render(request, "security/watchguard_patch_installate.html", {"d": dati})


def watchguard_task(request):
    """Storico dei task di installazione patch lanciati dalla console WatchGuard, con l'esito per PC."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from django.db.models import Q, Sum

    from .models import WatchGuardTask

    q = (request.GET.get("q") or "").strip()[:100]
    tasks = WatchGuardTask.objects.all()
    if q:
        tasks = tasks.filter(Q(nome__icontains=q) | Q(esiti__host__icontains=q) | Q(esiti__patch_nome__icontains=q)).distinct()
    totali = WatchGuardTask.objects.aggregate(pc=Sum("pc"), riuscite=Sum("riuscite"), errori=Sum("errori"),
                                              in_attesa=Sum("in_attesa"))
    scelto, esiti = None, []
    task_pk = request.GET.get("task") or ""
    if task_pk.isdigit():
        scelto = WatchGuardTask.objects.filter(pk=int(task_pk)).first()
        if scelto is not None:
            # l'ultimo esito per (PC, patch): un PC riprovato in un'esecuzione successiva compare una volta
            ultimi = {}
            for e in scelto.esiti.select_related("hub_asset").order_by("job_il", "pk"):
                ultimi[(e.host, e.patch_nome)] = e
            esiti = sorted(ultimi.values(), key=lambda e: (e.esito is not None and not e.esito_errore, e.esito is not None, e.host))
    from .services import watchguard_api

    evidenza = watchguard_api.evidenza_cve(scelto, esiti) if scelto is not None and esiti else None
    ultima = WatchGuardTask.objects.order_by("-letto_il").values_list("letto_il", flat=True).first()
    return render(request, "security/watchguard_task.html", {
        "tasks": tasks[:200], "conteggio": tasks.count(), "q": q, "totali": totali, "scelto": scelto, "esiti": esiti,
        "evidenza": evidenza, "ultima": ultima, "attivo": soc_settings.value("watchguard.api.patch"),
    })


def _patch_installate_csv(request, dati):
    """Tutte le righe del filtro (non solo quelle mostrate), con le celle protette dalle formule."""
    from core.audit import log_action
    from core.csv_export import csv_download_response

    risposta, w = csv_download_response(f"patch-installate-{timezone.localdate():%Y%m%d}.csv", delimiter=";")
    w.writerow(["Chiusa il", "PC", "Patch", "Programma", "Versione", "Produttore", "Criticità", "Pubblicata il",
                "Motivo", "Esito installazione", "Esito il", "CVE corrette", "CVE sfruttate (KEV)"])
    for x in dati["righe"]:
        p = x["p"]
        w.writerow([
            timezone.localtime(p.chiusa_il).strftime("%d/%m/%Y %H:%M"), p.host_display or p.host, p.nome, p.programma,
            p.versione, p.produttore, p.criticita_label, p.rilasciata_il.strftime("%d/%m/%Y") if p.rilasciata_il else "",
            x["motivo_label"], p.esito_label, timezone.localtime(p.esito_il).strftime("%d/%m/%Y %H:%M") if p.esito_il else "",
            ", ".join(x["cve"]), ", ".join(x["kev"]),
        ])
    try:
        log_action(request, "soc_patch_installate_export", "security",
                   {"righe": len(dati["righe"]), "periodo": dati["periodo"], "motivo": dati["motivo"], "q": dati["q"]})
    except Exception:  # noqa: BLE001 - l'audit non blocca l'export
        logger.exception("Audit export patch installate non registrato")
    return risposta


def dipendenze_portale(request):
    """Librerie Python del portale con vulnerabilità note (services/dipendenze_portale.py). Sola lettura."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from .models import SecurityLetturaLog
    from .services import dipendenze_portale as dp

    librerie = dp.per_pacchetto()
    ultimo = SecurityLetturaLog.objects.filter(codice="dipendenze_portale").exclude(
        stato__in=(SecurityLetturaLog.CODA, SecurityLetturaLog.IN_CORSO)).order_by("-avviata_il").first()
    return render(request, "security/dipendenze_portale.html", {
        "librerie": librerie,
        "vulnerabilita": sum(len(g["voci"]) for g in librerie),
        "gravi": sum(1 for g in librerie if g["gravita"] in ("critical", "high")),
        "risolte": dp.risolte_recenti(),
        "ultimo": ultimo,
        "controllo_attivo": soc_settings.value("dipendenze.controllo.attivo"),
        "alert_attivo": soc_settings.value("dipendenze.alert.attivo"),
    })


def watchguard_patch_tempi(request):
    """Tempi delle patch: tempo di installazione per classe, andamento settimanale, patch ferme (services/patch_sla.py)."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from datetime import date, timedelta

    from .services import patch_sla, patch_storico

    periodo = request.GET.get("periodo") or patch_storico.PERIODO_DEFAULT
    periodo = periodo if periodo in patch_storico.PERIODI else patch_storico.PERIODO_DEFAULT
    oggi = timezone.localdate()
    giorni = patch_storico.PERIODI[periodo]
    dal = oggi - timedelta(days=giorni - 1) if giorni else date(2000, 1, 1)
    ferme = patch_sla.ferme(
        oggi, classe_filtro=request.GET.get("classe") or "", stato_filtro=request.GET.get("stato") or "",
        q=(request.GET.get("q") or "")[:100],
    )
    if request.GET.get("formato") == "csv":
        return _patch_ferme_csv(request, ferme)
    return render(request, "security/watchguard_patch_tempi.html", {
        "t": patch_sla.tempi(dal, oggi, oggi), "f": ferme, "a": patch_sla.andamento(oggi=oggi),
        "periodo": periodo, "periodi": list(patch_storico.PERIODI_LABEL.items()),
        "allerta_attiva": soc_settings.value("patch.sla.attivo"), "can_edit": can_manage_security_config(request.user),
    })


def _patch_ferme_csv(request, ferme):
    """Una riga per patch e PC fermi (oltre il termine o installazione fallita), con le celle protette dalle formule."""
    from core.audit import log_action
    from core.csv_export import csv_download_response

    risposta, w = csv_download_response(f"patch-ferme-{timezone.localdate():%Y%m%d}.csv", delimiter=";")
    w.writerow(["Patch", "Programma", "Classe", "Pubblicata il", "Termine (giorni)", "Scadenza", "PC", "Oltre il termine",
                "Giorni di ritardo", "Ultimo esito installazione", "Esito il", "CVE corrette", "CVE sfruttate (KEV)"])
    for g in ferme["righe"]:
        for v in g["pc"]:
            p = v["p"]
            w.writerow([
                p.nome, p.programma, v["etichetta"], p.rilasciata_il.strftime("%d/%m/%Y") if p.rilasciata_il else "",
                v["giorni"], v["scadenza"].strftime("%d/%m/%Y") if v["scadenza"] else "", p.host_display or p.host,
                "sì" if v["scaduta"] else "no", v["giorni_ritardo"] or "", p.esito_label,
                timezone.localtime(p.esito_il).strftime("%d/%m/%Y %H:%M") if p.esito_il else "",
                ", ".join(p.cve_lista), ", ".join(v["kev"]),
            ])
    try:
        log_action(request, "soc_patch_ferme_export", "security",
                   {"patch": len(ferme["righe"]), "classe": ferme["classe"], "stato": ferme["stato"], "q": ferme["q"]})
    except Exception:  # noqa: BLE001 - l'audit non blocca l'export
        logger.exception("Audit export patch ferme non registrato")
    return risposta


# --- Letture automatiche: stato, storico, «Esegui ora» --------------------------------------

def letture_page(request):
    """Impostazioni › Letture automatiche: una scheda per lettura con ultimo giro, cosa ha letto e storico."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services import letture

    contesto = {**letture.stato_pagina(), "can_edit": can_configure_soc(request)}
    if request.GET.get("parziale") == "1":
        return render(request, "security/partials/letture_contenuto.html", contesto)
    return render(request, "security/letture.html", contesto)


def battito_page(request):
    """Impostazioni › Battito del SOC: ogni lettura e lavoro automatico, ultimo e prossimo giro, mappa di 14 giorni."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services import battito

    return render(request, "security/battito.html", battito.stato())


@require_POST
def lettura_esegui(request, codice):
    """«Esegui ora»: mette in coda un giro della lettura (solo chi configura il SOC)."""
    if not can_configure_soc(request):
        return _denied(request)
    from .services import letture

    if codice not in letture.PER_CODICE:
        raise Http404
    ok, testo = letture.accoda(codice, request.user)
    (messages.success if ok else messages.error)(request, testo)
    return redirect(reverse("security:letture") + f"#lettura-{codice}")
