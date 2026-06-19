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


def drop_mansioni_from_impostazioni(apps, schema_editor):
    """``mansioni_list`` ora appartiene a "Salute e Sicurezza": toglilo dagli
    active_view_names di Impostazioni così non si accendono entrambe le voci."""
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    link = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:impostazioni").first()
    if not link:
        return
    link.active_view_names = _set_tokens(link.active_view_names, remove="anagrafica:mansioni_list")
    link.save(update_fields=["active_view_names"])


def restore_mansioni_to_impostazioni(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    link = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:impostazioni").first()
    if not link:
        return
    link.active_view_names = _add_token(
        link.active_view_names, add="anagrafica:mansioni_list", after="anagrafica:impostazioni"
    )
    link.save(update_fields=["active_view_names"])


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0043_subnav_salute_sicurezza"),
    ]

    operations = [
        migrations.RunPython(drop_mansioni_from_impostazioni, restore_mansioni_to_impostazioni),
    ]
