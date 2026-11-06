"""Collegamento «Guida di questa pagina» per audit interni e Registro OFI."""
from django import template
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def sg_guida_link(context):
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    if not match:
        return ""
    from sistema_gestione.guida import link_pagina

    try:
        url = link_pagina(match.view_name)
    except NoReverseMatch:
        return ""
    if not url:
        return ""
    return format_html(
        '<p class="sg-guida-link"><a href="{}" target="_blank" rel="noopener" '
        'title="Apre in una nuova scheda il capitolo della guida che spiega questa pagina">'
        '<span aria-hidden="true">?</span> Guida di questa pagina</a></p>', url)


_SEZIONI = [
    ("panoramica", "Panoramica", "sistema_gestione:index"),
    ("audit", "Audit interni", "sistema_gestione:audit_index"),
    ("certificazioni", "Certificazioni e audit esterni", "sistema_gestione:esterni_elenco"),
    ("riesame", "Riesame", "sistema_gestione:riesame_elenco"),
    ("auditor", "Auditor", "sistema_gestione:auditor_elenco"),
    ("processi", "Processi", "sistema_gestione:processi_catalogo"),
    ("checklist", "Checklist", "sistema_gestione:checklist_norme"),
    ("soa", "SoA 27001", "sistema_gestione:soa"),
]
_SOTTO = {
    "audit": [
        ("Elenco", "sistema_gestione:audit_index"),
        ("Priorità e proposte", "sistema_gestione:audit_priorita"),
        ("Calendario", "sistema_gestione:audit_calendario"),
        ("Cicli triennali", "sistema_gestione:programma_cicli"),
        ("Cruscotto", "sistema_gestione:audit_cruscotto"),
        ("I miei rilievi", "sistema_gestione:audit_miei_rilievi"),
        ("Indicatori MT CN 13", "sistema_gestione:procedura_kpi"),
        ("Guida", "sistema_gestione:audit_guida"),
        ("Impostazioni", "sistema_gestione:audit_impostazioni"),
    ],
    "soa": [
        ("Dichiarazione di applicabilità", "sistema_gestione:soa"),
        ("Threat intelligence", "sistema_gestione:threat_intelligence"),
    ],
}
# Moduli collegati: si mostrano solo a chi li può aprire.
_COLLEGATI = [
    ("Registro OFI", "registro_ofi:lista", "?modulo=sistema_gestione"),
    ("Qualifiche", "anagrafica:qualifiche_dashboard", ""),
    ("Scadenzario", "scadenze_globali", "?sorgente=sgi"),
]


def _sezione(nome_vista: str) -> str:
    nome = nome_vista.split(":")[-1]
    if nome == "index":
        return "panoramica"
    if nome.startswith("esterni_"):
        return "certificazioni"
    if nome.startswith("riesame_"):
        return "riesame"
    if nome.startswith("auditor_"):
        return "auditor"
    if nome.startswith(("processi_", "processo_", "checklist_processo")):
        return "processi"
    if nome.startswith("checklist_"):
        return "checklist"
    if nome.startswith(("soa", "threat_")):
        return "soa"
    return "audit"


@register.inclusion_tag("sistema_gestione/components/_menu.html", takes_context=True)
def sg_menu(context):
    """Menu del modulo: le voci che chi guarda può aprire. Ogni vista ricontrolla comunque il permesso."""
    from core.middleware import acl_allows_path
    from sistema_gestione.acl_bootstrap import _ROUTE_BINDINGS
    from sistema_gestione.views import _has_perm

    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    vista = match.view_name if match else ""
    sezione = _sezione(vista)
    permessi: dict[str, bool] = {}

    def puo(rotta: str) -> bool:
        codice = _ROUTE_BINDINGS.get(rotta)
        if not codice:
            return False
        if codice not in permessi:
            permessi[codice] = bool(_has_perm(request, codice))
        return permessi[codice]

    def puo_aprire_altrove(url: str) -> bool:
        try:
            return bool(acl_allows_path(url, django_user=request.user, request=request))
        except Exception:
            return False

    sezioni = [{"etichetta": e, "url": reverse(r), "attiva": s == sezione} for s, e, r in _SEZIONI if puo(r)]
    sotto = [{"etichetta": e, "url": reverse(r), "attiva": r == vista} for e, r in _SOTTO.get(sezione, []) if puo(r)]
    collegati = []
    for etichetta, rotta, query in _COLLEGATI:
        try:
            url = reverse(rotta)
        except NoReverseMatch:
            continue
        if puo_aprire_altrove(url):
            collegati.append({"etichetta": etichetta, "url": url + query})
    return {"sezioni": sezioni, "sotto": sotto, "collegati": collegati}
