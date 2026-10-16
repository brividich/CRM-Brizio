from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anomalie', '0016_anomaliacontrollo_destinatari_extra'),
    ]

    operations = [
        migrations.AddField(
            model_name='anomaliacontrollo',
            name='promemoria_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='anomaliacontrollo',
            name='mail_mode',
            field=models.CharField(choices=[('subito', 'A ogni salvataggio'), ('fine', 'Unica mail a fine controllo')], default='fine', max_length=10),
        ),
    ]
