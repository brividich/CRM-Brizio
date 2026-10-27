from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0012_allegato_validazione"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticketimpostazioni",
            name="sharepoint_site_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="ticketimpostazioni",
            name="sharepoint_sync_attivo",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="TicketSharePointOutbox",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("queued_at", models.DateTimeField(auto_now=True)),
                ("tentativi", models.PositiveIntegerField(default=0)),
                ("ultimo_errore", models.TextField(blank=True)),
                ("ticket", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="sharepoint_outbox", to="tickets.ticket")),
            ],
            options={
                "verbose_name": "Ticket da inviare a SharePoint",
                "verbose_name_plural": "Ticket da inviare a SharePoint",
            },
        ),
    ]
