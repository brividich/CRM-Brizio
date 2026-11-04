from django import template

register = template.Library()


@register.filter
def voce(voci_cfg, chiave):
    """VoceConfig della chiave (o None)."""
    return (voci_cfg or {}).get(chiave)


@register.filter
def n_regole(regole_per_chiave, chiave):
    return len((regole_per_chiave or {}).get(chiave, ()))


@register.filter
def startswith_key(chiave, prefisso):
    """La chiave è il prefisso o sta sotto di lui (per aprire i rami dell'albero)."""
    chiave, prefisso = str(chiave or ""), str(prefisso or "")
    return chiave == prefisso or chiave.startswith(prefisso + "|")


@register.filter
def stato_giorni(giorni):
    if giorni is None:
        return ("sz-off", "senza data")
    if giorni < 0:
        return ("sz-scaduta", f"scaduta da {abs(giorni)} gg")
    if giorni <= 30:
        return ("sz-vicina", "oggi" if giorni == 0 else f"tra {giorni} gg")
    return ("sz-ok", f"tra {giorni} gg")
