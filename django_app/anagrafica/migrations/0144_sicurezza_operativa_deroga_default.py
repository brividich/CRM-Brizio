"""Visita mancante al cambio mansione: «deroga motivata» come comportamento predefinito.

Decisione del 10/10/2026: non idoneo a operare salvo deroga motivata, al
massimo 30 giorni (configurabile), rinnovabile solo con una motivazione nuova.
La riga di configurazione già creata con il vecchio predefinito (solo avviso)
viene allineata; in produzione la 0139 non è ancora stata applicata, quindi
lì la riga nasce già col valore nuovo. Reverse: nessuna modifica ai dati.
"""

from django.db import migrations, models


def allinea(apps, schema_editor):
    Config = apps.get_model("anagrafica", "ConfigSicurezzaOperativa")
    Config.objects.filter(pk=1, modalita_visita_mancante="SOLO_AVVISO").update(
        modalita_visita_mancante="DEROGA_AMMESSA",
    )


class Migration(migrations.Migration):

    dependencies = [
        ('anagrafica', '0143_adempimento_unique_solo_con_assegnazione'),
    ]

    operations = [
        migrations.AlterField(
            model_name='configsicurezzaoperativa',
            name='deroga_max_giorni',
            field=models.PositiveSmallIntegerField(default=30, help_text='Durata massima di una deroga; il rinnovo richiede una motivazione nuova.'),
        ),
        migrations.AlterField(
            model_name='configsicurezzaoperativa',
            name='modalita_visita_mancante',
            field=models.CharField(choices=[('SOLO_AVVISO', 'Solo avviso'), ('DEROGA_AMMESSA', 'Non idoneo a operare, salvo deroga motivata'), ('BLOCCO', 'Non idoneo a operare, nessuna deroga')], default='DEROGA_AMMESSA', help_text='Cosa succede se la decorrenza arriva senza la visita del cambio mansione.', max_length=20),
        ),
        migrations.RunPython(allinea, migrations.RunPython.noop),
    ]
