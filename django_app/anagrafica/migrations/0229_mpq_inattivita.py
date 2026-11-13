from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0228_subnav_mpq_matrice"),
    ]

    operations = [
        migrations.AddField(
            model_name="processoqualificato",
            name="inattivita_mesi",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="Riesame dopo mesi senza attività",
                help_text="Vuoto = nessun riesame per inattività. Es. 6: chi non lavora il processo da 6 mesi non è più qualificato finché non si registra un'attività o un riesame."),
        ),
        migrations.AddField(
            model_name="abilitazioneprocesso",
            name="ultima_attivita",
            field=models.DateField(blank=True, null=True, verbose_name="Ultima attività sul processo"),
        ),
    ]
