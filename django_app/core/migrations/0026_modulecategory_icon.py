from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0025_portal_branding_siteconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="modulecategory",
            name="icon",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Emoji o icona breve mostrata nella sidebar per la categoria.",
                max_length=20,
            ),
        ),
    ]
