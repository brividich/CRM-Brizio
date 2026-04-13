from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0006_ticket_data_prevista_risoluzione"),
    ]

    operations = [
        # Nuovi campi costo su TicketIntervento
        migrations.AddField(
            model_name="ticketintervento",
            name="costo_manodopera_eur",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Costo manodopera per questa sessione (\u20ac)",
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="ticketintervento",
            name="materiali_costo_eur",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Costo materiali/ricambi per questa sessione (\u20ac)",
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="ticketintervento",
            name="numero_rapportino",
            field=models.CharField(
                blank=True,
                help_text="Numero rapportino fornitore (opzionale)",
                max_length=50,
            ),
        ),
        # Nuovo modello TicketComponenteSostituito
        migrations.CreateModel(
            name="TicketComponenteSostituito",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(help_text="Nome componente/ricambio", max_length=200)),
                ("codice_parte", models.CharField(blank=True, help_text="Codice parte / P/N", max_length=100)),
                ("quantita", models.PositiveIntegerField(default=1)),
                (
                    "costo_unitario_eur",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Costo unitario (\u20ac)",
                        max_digits=10,
                        null=True,
                    ),
                ),
                ("note", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "intervento",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="componenti_sostituiti",
                        to="tickets.ticketintervento",
                    ),
                ),
            ],
            options={
                "verbose_name": "Componente sostituito",
                "verbose_name_plural": "Componenti sostituiti",
                "ordering": ["created_at"],
            },
        ),
    ]
