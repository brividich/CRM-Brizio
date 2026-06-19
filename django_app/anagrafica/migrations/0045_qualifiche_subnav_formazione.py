from django.db import migrations


def _set_tokens(active_view_names: str, *, remove: str) -> str:
    tokens = [t.strip() for t in (active_view_names or "").split(",") if t.strip()]
    tokens = [t for t in tokens if t != remove]
    return ",".join(tokens)


def _add_token(active_view_names: str, *, add: str, after: str) -> str:
    tokens = [t.strip() for t in (active_view_names or "").split(",") if t.strip()]
    if add in tokens:
        return ",".join(tokens)
    if after in tokens:
        idx = tokens.index(after)
        tokens.insert(idx + 1, add)
    else:
        tokens.append(add)
    return ",".join(tokens)


def _move(link_qs, url_value, *, add=None, remove=None, after=None):
    link = link_qs.filter(url_value=url_value).first()
    if not link:
        return
    if remove:
        link.active_view_names = _set_tokens(link.active_view_names, remove=remove)
    if add:
        link.active_view_names = _add_token(link.active_view_names, add=add, after=after or url_value)
    link.save(update_fields=["active_view_names"])


def qualifiche_to_formazione(apps, schema_editor):
    """``qualifiche_list`` diventa la "casa" delle qualifiche nel modulo
    Formazione (catalogo unico, viste filtrate). Toglie l'highlight da
    Impostazioni e lo aggancia a Formazione, evitando il doppio-highlight
    (stesso criterio della 0044 per ``mansioni_list``)."""
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    _move(SubnavLinkAnagrafica.objects, "anagrafica:impostazioni",
          remove="anagrafica:qualifiche_list")
    _move(SubnavLinkAnagrafica.objects, "anagrafica:formazione_dashboard",
          add="anagrafica:qualifiche_list", after="anagrafica:formazione_dashboard")


def qualifiche_back_to_impostazioni(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    _move(SubnavLinkAnagrafica.objects, "anagrafica:formazione_dashboard",
          remove="anagrafica:qualifiche_list")
    _move(SubnavLinkAnagrafica.objects, "anagrafica:impostazioni",
          add="anagrafica:qualifiche_list", after="anagrafica:impostazioni")


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0044_impostazioni_no_mansioni_highlight"),
    ]

    operations = [
        migrations.RunPython(qualifiche_to_formazione, qualifiche_back_to_impostazioni),
    ]
