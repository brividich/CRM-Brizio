from django.db import migrations

SESSIONI_VIEWS = [
    "anagrafica:qualifica_sessioni_list",
    "anagrafica:qualifica_sessione_create",
    "anagrafica:qualifica_sessione_detail",
]


def _tokens(value):
    return [t.strip() for t in (value or "").split(",") if t.strip()]


def add_sessioni(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    link = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:formazione_dashboard").first()
    if not link:
        return
    tokens = _tokens(link.active_view_names)
    for v in SESSIONI_VIEWS:
        if v not in tokens:
            tokens.append(v)
    link.active_view_names = ",".join(tokens)
    link.save(update_fields=["active_view_names"])


def remove_sessioni(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    link = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:formazione_dashboard").first()
    if not link:
        return
    tokens = [t for t in _tokens(link.active_view_names) if t not in SESSIONI_VIEWS]
    link.active_view_names = ",".join(tokens)
    link.save(update_fields=["active_view_names"])


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0046_qualificasessione_dipendentequalifica_sessione"),
    ]

    operations = [
        migrations.RunPython(add_sessioni, remove_sessioni),
    ]
