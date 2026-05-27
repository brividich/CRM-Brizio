from django.db import migrations


def remove_onboarding_link(apps, schema_editor):
    SubnavLinkAnagrafica = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:onboarding_offboarding").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0027_add_risk_models"),
    ]

    operations = [
        migrations.RunPython(remove_onboarding_link, migrations.RunPython.noop),
    ]
