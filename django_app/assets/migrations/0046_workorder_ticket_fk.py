from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0045_update_sidebar_software_licenses"),
        ("tickets", "0007_ticket_costi_componenti"),
    ]

    operations = [
        migrations.AddField(
            model_name="workorder",
            name="ticket",
            field=models.ForeignKey(
                blank=True,
                help_text="Ticket manutenzione che ha originato questo OdL (opzionale)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="workorders_generati",
                to="tickets.ticket",
            ),
        ),
    ]
