from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0040_move_periodic_verifications_under_maintenance"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="periodicverification",
            options={
                "ordering": ["name", "id"],
                "verbose_name": "Manutenzione periodica",
                "verbose_name_plural": "Manutenzioni periodiche",
            },
        ),
        migrations.AlterField(
            model_name="assetdetailsectionlayout",
            name="code",
            field=models.CharField(
                choices=[
                    ("SPECS", "Specifiche tecniche"),
                    ("TIMELINE", "Timeline ciclo di vita"),
                    ("MAINTENANCE", "Registro manutenzione"),
                    ("TICKETS", "Ticket collegati"),
                    ("PROFILE", "Profilo asset"),
                    ("PERIODIC", "Manutenzione periodica"),
                    ("QR", "QR asset"),
                    ("SHAREPOINT", "Archivio SharePoint"),
                    ("QUICK_ACTIONS", "Azioni rapide"),
                    ("ASSIGNMENT", "Responsabile attuale"),
                    ("MAP", "Posizione in officina"),
                    ("DOCUMENTS", "Documenti"),
                ],
                max_length=24,
                unique=True,
            ),
        ),
    ]
