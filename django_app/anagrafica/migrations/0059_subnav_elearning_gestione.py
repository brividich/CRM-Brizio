from django.db import migrations


def seed_elearning_hub_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.get_or_create(
        url_value="anagrafica:formazione_elearning_hub",
        defaults=dict(
            etichetta="Gestione e-learning",
            icona="🎓",
            url_type="named",
            active_view_names=(
                "anagrafica:formazione_elearning_hub,"
                "anagrafica:formazione_corso_elearning"
            ),
            ordine=62,
            is_sistema=True,
            is_active=True,
        ),
    )


def remove_elearning_hub_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:formazione_elearning_hub").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0058_trainingslide_immagine"),
    ]

    operations = [
        migrations.RunPython(seed_elearning_hub_link, remove_elearning_hub_link),
    ]
