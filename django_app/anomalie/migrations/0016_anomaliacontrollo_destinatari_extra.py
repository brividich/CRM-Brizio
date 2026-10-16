from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anomalie', '0015_controllo_blocchi'),
    ]

    operations = [
        migrations.AddField(
            model_name='anomaliacontrollo',
            name='destinatari_extra',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
