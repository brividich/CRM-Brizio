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
