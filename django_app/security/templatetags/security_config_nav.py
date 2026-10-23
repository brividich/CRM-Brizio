"""Un solo ingresso «Configurazione» nel menu SOC, con le sezioni come schede.

Prima Config, Impostazioni, Autoconfig e Caselle mail erano quattro voci di menu separate per
la stessa cosa. Ora il menu ha una voce e ogni pagina di configurazione mostra la stessa barra
di schede. La barra è solo navigazione: i permessi restano controllati dalle view.
"""
from django import template
from django.urls import reverse

from security.services.configuration import can_manage_security_config

register = template.Library()

# (rotta, etichetta, prefissi/rotte che accendono la scheda, solo per chi configura)
CONFIG_TABS = [
    ("admin_config", "Panoramica", ("admin_config", "admin_config_general", "admin_config_backups", "admin_config_ticketing",
                                    "admin_config_suppressions", "admin_diagnostics", "admin_docs", "admin_addons", "admin_addon_detail"), True),
    ("soc_settings", "Avvisi e automatismi", ("soc_settings",), False),
    ("admin_mailbox_sources_list", "Caselle mail", ("admin_mailbox_sources_list", "admin_mailbox_source_detail"), True),
    ("admin_config_sources", "Sorgenti e parser", ("admin_config_sources", "admin_config_parsers"), True),
    ("admin_config_alert_rules", "Regole alert", ("admin_config_alert_rules",), True),
    ("admin_config_notifications", "Notifiche", ("admin_config_notifications",), True),
    ("automation", "Automatismi di rientro", ("automation",), True),
    ("inventory", "Inventario software", ("inventory", "inventory_map", "software_mapping"), True),
    ("admin_autoconfig", "Autoconfigurazione", ("admin_autoconfig",), True),
    ("admin_config_audit", "Audit", ("admin_config_audit",), True),
]
CONFIG_ROUTES = {name for _route, _label, names, _admin in CONFIG_TABS for name in names}


def is_config_page(url_name):
    return (url_name or "") in CONFIG_ROUTES


@register.simple_tag
def soc_is_config_page(url_name):
    return is_config_page(url_name)


@register.simple_tag(takes_context=True)
def soc_config_home_url(context):
    """La voce di menu porta alla panoramica; chi non configura vede solo le impostazioni (in lettura)."""
    request = context.get("request")
    user = getattr(request, "user", None)
    return reverse("security:admin_config" if user and can_manage_security_config(user) else "security:soc_settings")


@register.inclusion_tag("security/admin_config/_tabs.html", takes_context=True)
def soc_config_tabs(context, url_name):
    request = context.get("request")
    user = getattr(request, "user", None)
    can_configure = bool(user and can_manage_security_config(user))
    tabs = [
        {"url": reverse(f"security:{route}"), "label": label, "active": url_name in names}
        for route, label, names, admin_only in CONFIG_TABS
        if can_configure or not admin_only
    ]
    return {"tabs": tabs, "show": is_config_page(url_name) and len(tabs) > 1}


# --- Menu del SOC: 5 voci, le pagine di ogni voce come seconda riga -------------------------
# (etichetta, rotta di ingresso, [(etichetta scheda, rotta, rotte che la accendono, solo per chi configura)])
MENU = [
    ("Da fare", "dashboard", [
        ("Panoramica", "dashboard", ("dashboard", "security_dashboard"), False),
        ("Tutto ciò che è aperto", "my_work", ("my_work",), False),
    ]),
    ("Segnalazioni", "segnalazioni", [
        ("Tutte", "segnalazioni", ("segnalazioni",), False),
        ("Alert", "alerts_list", ("alerts_list", "alert_detail"), False),
        ("Ticket", "tickets_list", ("tickets_list", "case_detail", "case_create"), False),
        ("Incidenti", "incidents", ("incidents", "incident_create", "incident_detail", "incident_edit"), False),
        ("Eventi", "events", ("events", "event_detail"), False),
    ]),
    ("Dispositivi", "pc_copertura", [
        ("Elenco", "pc_copertura", ("pc_copertura", "pc_detail", "assets"), False),
        ("Backup", "backup", ("backup", "backup_device", "backup_log"), False),
        ("Patch e protezione", "watchguard_pc", ("watchguard_pc",), False),
        ("Vulnerabilità", "vulnerabilities", ("vulnerabilities", "cve_detail"), False),
        ("Accessi VPN", "vpn_history", ("vpn_history",), False),
    ]),
    ("Report", "report", [
        ("Report", "report", ("report",), False),
        ("Storico", "history", ("history",), False),
        ("KPI", "kpis", ("kpis", "kpi_detail"), False),
    ]),
    ("Impostazioni", None, [
        ("Configurazione", None, tuple(CONFIG_ROUTES), False),
        ("Letture automatiche", "letture", ("letture",), False),
        ("Elaborazione", "pipeline", ("pipeline",), True),
        ("Soppressioni", "suppressions", ("suppressions",), False),
        ("Guida", "help", ("help", "doc_detail"), False),
    ]),
]


ICONE = {"Da fare": "todo", "Segnalazioni": "bell", "Dispositivi": "monitor", "Report": "chart", "Impostazioni": "gear"}
# Numeri sulle voci: dalla barra di stato (in cache 60 s), nessuna query in più. Solo se c'è qualcosa.
BADGE = {"Segnalazioni": ("urgenti",), "Dispositivi": ("backup",), "Impostazioni": ("sources",)}


def _badges(user):
    try:
        from security.services.live_status import live_status

        items = {i["key"]: i for i in live_status(user)["items"]}
    except Exception:  # noqa: BLE001 - un conteggio rotto non toglie il menu
        return {}
    out = {}
    for voce, chiavi in BADGE.items():
        presenti = [items[k] for k in chiavi if k in items and items[k]["value"]]
        if presenti:
            tone = "critical" if any(i["tone"] == "critical" for i in presenti) else "warning"
            out[voce] = {"value": sum(i["value"] for i in presenti), "tone": tone, "title": " · ".join(f"{i['value']} {i['label']}" for i in presenti)}
    return out


@register.inclusion_tag("security/_menu.html", takes_context=True)
def soc_menu(context, url_name):
    request = context.get("request")
    user = getattr(request, "user", None)
    can_configure = bool(user and can_manage_security_config(user))
    badges = _badges(user)
    voci, sezione = [], None
    for label, entry, pagine in MENU:
        tabs = []
        for tab_label, route, names, admin_only in pagine:
            if admin_only and not can_configure:
                continue
            if route is None and is_config_page(url_name):
                # Dentro la configurazione le sue sezioni prendono il posto della scheda unica: una riga sola, non due.
                tabs += [
                    {"label": t_label, "url": reverse(f"security:{t_route}"), "active": url_name in t_names}
                    for t_route, t_label, t_names, t_admin in CONFIG_TABS if can_configure or not t_admin
                ]
                tabs[-1]["sep_after"] = True
                continue
            url = reverse(f"security:{route}") if route else reverse("security:admin_config" if can_configure else "security:soc_settings")
            tabs.append({"label": tab_label, "url": url, "active": url_name in names})
        attiva = any(t["active"] for t in tabs)
        voce = {"label": label, "icon": ICONE.get(label, "shield"), "badge": badges.get(label),
                "url": reverse(f"security:{entry}") if entry else (tabs[0]["url"] if tabs else "#"), "active": attiva, "tabs": tabs}
        if attiva:
            sezione = voce
        voci.append(voce)
    return {"voci": voci, "sezione": sezione, "url_name": url_name}
