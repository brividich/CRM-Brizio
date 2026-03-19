from django.db import migrations


def seed_portal_branding_config(apps, schema_editor):
    SiteConfig = apps.get_model("core", "SiteConfig")
    defaults = {
        "portal_name": ("Portale Novicrom", "Nome portale visualizzato nella shell."),
        "portal_subtitle": ("", "Sottotitolo del branding globale del portale."),
        "brand_logo_full": ("", "URL logo esteso usato in topbar/sidebar."),
        "brand_logo_compact": ("", "URL logo compatto usato nella sidebar collassata."),
        "brand_favicon": ("", "URL favicon del portale."),
    }
    for chiave, (valore, descrizione) in defaults.items():
        SiteConfig.objects.update_or_create(
            chiave=chiave,
            defaults={
                "valore": valore,
                "descrizione": descrizione,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_uipreferences"),
    ]

    operations = [
        migrations.RunPython(seed_portal_branding_config, migrations.RunPython.noop),
    ]
