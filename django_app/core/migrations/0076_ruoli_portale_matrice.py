"""Ruoli del portale: flag sui gruppi (amministratore, vede tutto, preset) e matrice.

Vedi core/permessi e docs/ai/PERMESSI_RUOLI.md. Nessun effetto sugli accessi
finche' l'interruttore «sistema dei ruoli attivo» resta spento.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0075_notifica_archivio"),
    ]

    operations = [
        migrations.AddField(
            model_name="accessgroup",
            name="amministratore",
            field=models.BooleanField(
                default=False,
                help_text="Chi ha questo ruolo e' amministratore del portale: vede e fa tutto.",
            ),
        ),
        migrations.AddField(
            model_name="accessgroup",
            name="vede_tutto",
            field=models.BooleanField(
                default=False,
                help_text="Vede ed esporta i dati di tutti i moduli (es. Direzione), senza poter modificare.",
            ),
        ),
        migrations.AddField(
            model_name="accessgroup",
            name="preset",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Preset da cui nasce il ruolo (vuoto = ruolo creato a mano).",
                max_length=40,
            ),
        ),
        migrations.CreateModel(
            name="RuoloPermessoModulo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("modulo", models.CharField(db_index=True, max_length=80)),
                ("azione", models.CharField(max_length=40)),
                (
                    "ambito",
                    models.CharField(
                        choices=[("propri", "Propri"), ("team", "Propri e del team"), ("tutti", "Tutti")],
                        default="tutti",
                        max_length=10,
                    ),
                ),
                ("consentito", models.BooleanField(default=True)),
                ("note", models.CharField(blank=True, default="", max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "ruolo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="permessi_modulo",
                        to="core.accessgroup",
                    ),
                ),
            ],
            options={
                "verbose_name": "Permesso di ruolo sul modulo",
                "verbose_name_plural": "Permessi di ruolo sui moduli",
                "ordering": ["ruolo_id", "modulo", "azione"],
                "unique_together": {("ruolo", "modulo", "azione")},
            },
        ),
    ]
