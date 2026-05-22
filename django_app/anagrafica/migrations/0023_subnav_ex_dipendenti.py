from django.db import migrations


def seed_ex_dipendenti_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.get_or_create(
        url_value="anagrafica:ex_dipendenti_list",
        defaults=dict(
            etichetta="Ex dipendenti",
            icona="",
            url_type="named",
            active_view_names="anagrafica:ex_dipendenti_list",
            ordine=15,
            is_sistema=True,
            is_active=True,
        ),
    )


def remove_ex_dipendenti_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:ex_dipendenti_list").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0022_subnavlink_anagrafica"),
    ]

    operations = [
        migrations.RunPython(seed_ex_dipendenti_link, remove_ex_dipendenti_link),
    ]
