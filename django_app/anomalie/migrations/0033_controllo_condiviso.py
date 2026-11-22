from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Controllo condiviso: più persone sullo stesso controllo, ognuna con la sua bozza."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("anomalie", "0032_mail_action_token_hash"),
    ]

    operations = [
        migrations.AddField(
            model_name="anomaliablocco",
            name="creato_da_display",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="anomaliacontrollo",
            name="operatore_visto_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="AnomaliaControlloPartecipante",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(blank=True, default="", max_length=200)),
                ("bozza", models.JSONField(blank=True, default=dict)),
                ("bozza_at", models.DateTimeField(blank=True, null=True)),
                ("visto_at", models.DateTimeField(blank=True, null=True)),
                ("entrato_at", models.DateTimeField(auto_now_add=True)),
                ("controllo", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="partecipanti", to="anomalie.anomaliacontrollo")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Partecipante al controllo OP",
                "verbose_name_plural": "Partecipanti ai controlli OP",
                "ordering": ["entrato_at", "id"],
                "constraints": [models.UniqueConstraint(fields=("controllo", "user"), name="anomalie_controllo_partecipante_unico")],
            },
        ),
    ]
