from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0003_categoriaticket"),
    ]

    operations = [
        # 1. Nuovo stato IN_ATTESA — aggiunta a StatoTicket.choices (solo validatori,
        #    nessuna DDL necessaria per CharField senza CHECK constraint)

        # 2. Nuovi choices TipoFermo ed EsitoIntervento — nessuna DDL aggiuntiva

        # 3. Campi analitici su Ticket
        migrations.AddField(
            model_name="ticket",
            name="componente",
            field=models.CharField(blank=True, help_text="Componente/sotto-sistema interessato (es. Mandrino, Inverter, PLC)", max_length=200),
        ),
        migrations.AddField(
            model_name="ticket",
            name="causa_radice",
            field=models.CharField(blank=True, help_text="Causa radice identificata a chiusura", max_length=500),
        ),
        migrations.AddField(
            model_name="ticket",
            name="tipo_fermo",
            field=models.CharField(
                choices=[("NESSUNO", "Nessun fermo"), ("PARZIALE", "Fermo parziale"), ("TOTALE", "Fermo totale")],
                default="NESSUNO",
                help_text="Tipo di fermo produzione causato dal guasto",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="ore_fermo_macchina",
            field=models.DecimalField(blank=True, decimal_places=2, help_text="Ore di fermo macchina totali", max_digits=7, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="data_presa_in_carico",
            field=models.DateTimeField(blank=True, help_text="Timestamp automatico del primo passaggio IN_CARICO", null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="data_primo_intervento",
            field=models.DateTimeField(blank=True, help_text="Timestamp del primo TicketIntervento registrato", null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="risolto_da_nome",
            field=models.CharField(blank=True, help_text="Tecnico/manutentore che ha risolto il ticket", max_length=200),
        ),
        migrations.AddField(
            model_name="ticket",
            name="ricorrente",
            field=models.BooleanField(default=False, help_text="Il problema si è già verificato in passato"),
        ),
        migrations.AddField(
            model_name="ticket",
            name="ticket_origine",
            field=models.ForeignKey(
                blank=True,
                help_text="Ticket precedente da cui deriva (se ricorrente)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ticket_ricorrenti",
                to="tickets.ticket",
            ),
        ),

        # 4. Nuovo modello TicketStatoLog
        migrations.CreateModel(
            name="TicketStatoLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("da_stato", models.CharField(blank=True, max_length=15)),
                ("a_stato", models.CharField(max_length=15)),
                ("utente_nome", models.CharField(max_length=200)),
                ("utente_email", models.CharField(blank=True, max_length=200)),
                ("nota", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stato_log", to="tickets.ticket")),
            ],
            options={
                "verbose_name": "Log stato ticket",
                "verbose_name_plural": "Log stati ticket",
                "ordering": ["created_at"],
            },
        ),

        # 5. Nuovo modello TicketIntervento
        migrations.CreateModel(
            name="TicketIntervento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("tecnico_nome", models.CharField(max_length=200)),
                ("tecnico_email", models.CharField(blank=True, max_length=200)),
                ("data_inizio", models.DateTimeField()),
                ("data_fine", models.DateTimeField(blank=True, null=True)),
                ("ore_lavorate", models.DecimalField(blank=True, decimal_places=2, help_text="Ore effettive di lavoro (calcolate o manuali)", max_digits=6, null=True)),
                ("descrizione_lavoro", models.TextField(blank=True, help_text="Cosa è stato fatto")),
                ("componente_interessato", models.CharField(blank=True, help_text="Componente lavorato in questa sessione", max_length=200)),
                ("azioni_svolte", models.TextField(blank=True, help_text="Elenco azioni/procedure eseguite")),
                ("esito", models.CharField(
                    choices=[
                        ("IN_CORSO", "In corso"),
                        ("COMPLETATO", "Completato"),
                        ("SOSPESO", "Sospeso"),
                        ("RICHIEDE_RICAMBI", "Richiede ricambi"),
                    ],
                    default="IN_CORSO",
                    max_length=20,
                )),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="interventi", to="tickets.ticket")),
            ],
            options={
                "verbose_name": "Intervento ticket",
                "verbose_name_plural": "Interventi ticket",
                "ordering": ["data_inizio"],
            },
        ),
    ]
