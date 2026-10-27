"""Calendario Outlook su richiesta: più caselle per la stessa assenza, modo «su richiesta» / «tutte»."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assenze', '0010_assenzaserie'),
    ]

    operations = [
        migrations.AlterField(
            model_name='assenzaoutlook',
            name='assenza_id',
            field=models.IntegerField(db_index=True),
        ),
        migrations.AddField(
            model_name='assenzaoutlook',
            name='richiesto_da',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddConstraint(
            model_name='assenzaoutlook',
            constraint=models.UniqueConstraint(fields=('assenza_id', 'email'), name='assenze_outlook_assenza_email_uniq'),
        ),
        migrations.AddField(
            model_name='assenzeimpostazionihr',
            name='outlook_capo_modo',
            field=models.CharField(choices=[('richiesta', 'Solo quando lo si chiede'), ('tutte', 'Tutte le assenze approvate')], default='richiesta', max_length=20, verbose_name='Quali assenze mettere nel calendario Outlook'),
        ),
    ]
