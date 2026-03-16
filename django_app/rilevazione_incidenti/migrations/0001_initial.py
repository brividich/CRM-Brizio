from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SicurezzaImpostazioni",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "sharepoint_site_id",
                    models.CharField(
                        blank=True,
                        help_text="ID sito SharePoint (es. tuodominio.sharepoint.com,{guid},{guid})",
                        max_length=300,
                    ),
                ),
                (
                    "sharepoint_list_id",
                    models.CharField(
                        blank=True,
                        default="7B90d47760-aa13-459c-86e5-ba1fd97bdddc",
                        help_text="ID lista SharePoint delle rilevazioni sicurezza",
                        max_length=200,
                    ),
                ),
                (
                    "acl_preposti",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Lista di username o email autorizzati alla creazione/modifica segnalazioni (capireparto, preposti). Lasciare vuoto = accesso aperto a tutti.",
                    ),
                ),
                (
                    "acl_rspp",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Lista di username o email RSPP/ASPP abilitati all'approvazione e chiusura. Lasciare vuoto = nessuno (solo admin).",
                    ),
                ),
            ],
            options={
                "verbose_name": "Impostazioni Sicurezza",
                "verbose_name_plural": "Impostazioni Sicurezza",
            },
        ),
    ]
