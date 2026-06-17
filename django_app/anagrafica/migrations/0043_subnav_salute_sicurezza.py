from django.db import migrations


SAFETY_VIEWS = ",".join([
    "anagrafica:sicurezza_hub",
    "anagrafica:sicurezza_wizard",
    "anagrafica:fattori_rischio_list",
    "anagrafica:categorie_corso_list",
    "anagrafica:esposizioni_rischio_list",
    "anagrafica:mansioni_list",
    "anagrafica:mansione_requisiti",
    "anagrafica:conformita_report",
    "anagrafica:matrice_competenze",
])


def seed_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.get_or_create(
        url_value="anagrafica:sicurezza_hub",
        defaults=dict(
            etichetta="Salute e Sicurezza",
            icona="🛡",
            url_type="named",
            active_view_names=SAFETY_VIEWS,
            ordine=58,  # subito prima di Formazione (60)
            is_sistema=True,
            is_active=True,
        ),
    )


def remove_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:sicurezza_hub").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0042_mansione_livello_rischio"),
    ]

    operations = [
        migrations.RunPython(seed_link, remove_link),
    ]
