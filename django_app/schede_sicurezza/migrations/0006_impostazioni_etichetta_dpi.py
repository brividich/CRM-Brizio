from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('schede_sicurezza', '0005_impostazioni_etichetta'),
    ]

    operations = [
        migrations.AddField(
            model_name='impostazionietichetta',
            name='mostra_dpi',
            field=models.BooleanField(default=True, help_text='Segnali di obbligo blu accanto ai pittogrammi, dai «DPI obbligatori» del prodotto.', verbose_name='Mostra i DPI obbligatori'),
        ),
    ]
