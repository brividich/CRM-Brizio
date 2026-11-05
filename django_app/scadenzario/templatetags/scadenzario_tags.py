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


@register.simple_tag(takes_context=True)
def sz_permessi(context):
    """Quali voci del menu dello scadenzario mostrare (la decisione vera resta nelle viste)."""
    from scadenzario.permessi import categorie_gestibili, puo_gestire_pannello

    request = context.get("request")
    if request is None:
        return {"pannello": False, "categorie": False}
    pannello = puo_gestire_pannello(request)
    return {"pannello": pannello, "categorie": pannello or bool(categorie_gestibili(request))}


@register.simple_tag(takes_context=True)
def qs_cambia(context, **cambi):
    """Querystring della pagina con i parametri cambiati (vuoto = tolto)."""
    from django.http import QueryDict

    request = context.get("request")
    dati = request.GET.copy() if request is not None else QueryDict(mutable=True)
    for chiave, valore in cambi.items():
        dati.pop(chiave, None)
        if valore not in ("", None):
            dati[chiave] = valore
    dati.pop("format", None)
    return dati.urlencode()
