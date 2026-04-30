from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0048_seed_calendario_asset_sidebar_button"),
    ]

    operations = [
        migrations.AddField(
            model_name="workmachine",
            name="photo",
            field=models.ImageField(blank=True, null=True, upload_to="assets/work_machines/photos/"),
        ),
    ]
