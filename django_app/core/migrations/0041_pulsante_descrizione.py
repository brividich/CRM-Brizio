from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0040_alter_modulecategory_icon_alter_navigationitem_icon"),
    ]

    operations = [
        migrations.AddField(
            model_name="pulsante",
            name="descrizione",
            field=models.TextField(blank=True, null=True),
        ),
    ]
