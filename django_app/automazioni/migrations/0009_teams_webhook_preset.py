from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0008_approval_and_flow_actions"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamsWebhookPreset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True, verbose_name="Nome canale")),
                ("webhook_url", models.TextField(verbose_name="Webhook URL")),
                ("description", models.CharField(blank=True, max_length=255, verbose_name="Descrizione")),
                ("is_active", models.BooleanField(default=True, verbose_name="Attivo")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Preset webhook Teams",
                "verbose_name_plural": "Preset webhook Teams",
                "ordering": ["name"],
            },
        ),
    ]
