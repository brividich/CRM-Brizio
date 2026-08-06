"""Rimuove l'integrazione SharePoint dagli asset.

L'archivio documenti asset e' interamente locale (``ASSETS_PRIVATE_ROOT``,
cifrato at-rest): SharePoint era solo una copia di appoggio, non la fonte.
Con la sync rimossa le colonne di percorso/URL/link pubblico non hanno piu
alcun lettore, quindi vengono eliminate insieme alla sezione "Archivio
SharePoint" della scheda asset.
"""
from django.db import migrations, models


def drop_sharepoint_section_layouts(apps, schema_editor):
    """Elimina le righe di layout che puntano alla card SHAREPOINT rimossa."""
    AssetDetailSectionLayout = apps.get_model("assets", "AssetDetailSectionLayout")
    AssetDetailSectionLayout.objects.filter(code="SHAREPOINT").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0089_ingest_periodic_verifications_into_plans"),
    ]

    operations = [
        migrations.RunPython(drop_sharepoint_section_layouts, migrations.RunPython.noop),
        migrations.RemoveField(model_name="asset", name="sharepoint_folder_url"),
        migrations.RemoveField(model_name="asset", name="sharepoint_folder_path"),
        migrations.RemoveField(model_name="asset", name="sharepoint_drive_id"),
        migrations.RemoveField(model_name="asset", name="sharepoint_item_id"),
        migrations.RemoveField(model_name="asset", name="sharepoint_public_url"),
        migrations.RemoveField(model_name="asset", name="sharepoint_public_link_id"),
        migrations.RemoveField(model_name="asset", name="sharepoint_public_enabled"),
        migrations.RemoveField(model_name="asset", name="sharepoint_public_created_at"),
        migrations.RemoveField(model_name="asset", name="sharepoint_public_last_checked_at"),
        migrations.RemoveField(model_name="asset", name="sharepoint_public_error"),
        migrations.RemoveField(model_name="assetdocument", name="sharepoint_url"),
        migrations.RemoveField(model_name="assetdocument", name="sharepoint_path"),
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
                    ("LICENSES", "Licenze software"),
                    ("PERIODIC", "Manutenzione periodica"),
                    ("QR", "QR asset"),
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
