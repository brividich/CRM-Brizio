from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_optioneconfig_legacy_user_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="navigationitem",
            name="icon",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Emoji o icona breve mostrata accanto alla label (es. 🏠, 📊).",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="navigationitem",
            name="group",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Gruppo visivo per separatori nella subnav (es. accessi, navigazione, hub).",
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name="navigationitem",
            name="active_patterns",
            field=models.CharField(
                blank=True,
                default="",
                help_text="View name Django separati da virgola per rilevamento stato attivo.",
                max_length=500,
            ),
        ),
        migrations.AlterField(
            model_name="navigationitem",
            name="description",
            field=models.CharField(
                blank=True,
                default="",
                max_length=500,
            ),
        ),
    ]
