from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0023_workorder_periodic_verification_workorder_supplier_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetHeaderTool",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True)),
                ("label", models.CharField(max_length=120)),
                ("description", models.CharField(blank=True, default="", max_length=255)),
                ("is_active", models.BooleanField(default=True, help_text="Se disattivo, il pulsante non appare a nessuno.")),
                (
                    "admin_only",
                    models.BooleanField(
                        default=False,
                        help_text="Se attivo, visibile solo agli amministratori asset. Altrimenti visibile a tutti gli utenti autenticati.",
                    ),
                ),
                ("sort_order", models.IntegerField(default=100)),
            ],
            options={"ordering": ["sort_order", "code"]},
        ),
    ]
