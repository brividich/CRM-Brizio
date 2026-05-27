from django.db import migrations


def seed_formazione_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.get_or_create(
        url_value="anagrafica:formazione_dashboard",
        defaults=dict(
            etichetta="Formazione",
            icona="🎓",
            url_type="named",
            active_view_names="anagrafica:formazione_dashboard",
            ordine=60,
            is_sistema=True,
            is_active=True,
        ),
    )


def remove_formazione_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:formazione_dashboard").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0024_add_training_models"),
    ]

    operations = [
        migrations.RunPython(seed_formazione_link, remove_formazione_link),
    ]
