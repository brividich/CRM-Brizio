from django.db import migrations, models

import assets.models
import assets.storage


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0059_workorder_origin_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assetadministrativedeadlinecompletionattachment",
            name="file",
            field=models.FileField(
                storage=assets.storage.PrivateAssetAdministrativeDeadlineStorage(),
                upload_to=assets.models._admin_deadline_completion_attachment_upload_to,
            ),
        ),
    ]
