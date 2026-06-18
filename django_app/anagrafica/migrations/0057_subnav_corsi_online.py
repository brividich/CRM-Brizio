from django.db import migrations


def seed_corsi_online_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.get_or_create(
        url_value="anagrafica:formazione_online_catalog",
        defaults=dict(
            etichetta="Corsi online",
            icona="🎓",
            url_type="named",
            active_view_names=(
                "anagrafica:formazione_online_catalog,"
                "anagrafica:formazione_online_player,"
                "anagrafica:formazione_online_quiz"
            ),
            ordine=61,
            is_sistema=True,
            is_active=True,
        ),
    )


def remove_corsi_online_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:formazione_online_catalog").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0056_elearning_microcorsi"),
    ]

    operations = [
        migrations.RunPython(seed_corsi_online_link, remove_corsi_online_link),
    ]
