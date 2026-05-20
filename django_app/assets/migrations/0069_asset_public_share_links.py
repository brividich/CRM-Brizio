import uuid

from django.db import migrations, models


def populate_public_qr_tokens(apps, schema_editor):
    Asset = apps.get_model("assets", "Asset")
    for asset in Asset.objects.filter(public_qr_token__isnull=True).iterator():
        asset.public_qr_token = uuid.uuid4().hex
        asset.save(update_fields=["public_qr_token"])


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0068_assetdocument_relative_folder"),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="sharepoint_drive_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="asset",
            name="sharepoint_item_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="asset",
            name="sharepoint_public_url",
            field=models.CharField(blank=True, default="", max_length=1000),
        ),
        migrations.AddField(
            model_name="asset",
            name="sharepoint_public_link_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="asset",
            name="sharepoint_public_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="asset",
            name="sharepoint_public_created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="asset",
            name="sharepoint_public_last_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="asset",
            name="sharepoint_public_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="asset",
            name="public_qr_token",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="asset",
            name="public_qr_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(populate_public_qr_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="asset",
            name="public_qr_token",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, unique=True),
        ),
    ]
