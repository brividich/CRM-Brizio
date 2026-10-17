from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anomalie', '0017_anomaliacontrollo_promemoria_mail_fine'),
    ]

    operations = [
        migrations.AddField(
            model_name='anomaliacontrollo',
            name='bozza',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='anomaliacontrollo',
            name='bozza_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
