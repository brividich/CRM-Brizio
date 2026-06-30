# Generated for Gestione Carichi Macchina: turni estesi (entrambi/H24) + etichette fasi.
# Solo metadati (choices/label): nessuna modifica allo schema fisico delle colonne.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestione_carichi_macchina', '0003_commessa_kickoff_project_pianificazione_kickoff_task_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pianificazione',
            name='turno',
            field=models.CharField(
                choices=[
                    ('giorno', '1° turno (6-14)'),
                    ('t2', '2° turno (14-22)'),
                    ('entrambi', 'Entrambi (6-22)'),
                    ('notte', 'Notturno (22-6)'),
                    ('h24', 'H24'),
                ],
                default='giorno',
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name='pianificazione',
            name='fase',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', '—'),
                    ('fin', 'Finitura'),
                    ('sgr', 'Sgrossatura'),
                    ('ass', 'Assieme'),
                    ('rip', 'Ripristino'),
                ],
                default='',
                max_length=8,
            ),
        ),
    ]
