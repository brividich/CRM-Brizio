import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registro_log', '0004_pc_dominio_cartelle_raccoglitori'),
    ]

    operations = [
        migrations.CreateModel(
            name='OperazioneManutenzione',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('backup_db', 'Backup del database del registro'), ('copia', 'Copia sulla seconda copia'), ('conservazione', 'Conservazione applicata'), ('alleggerisci', 'Catalogo alleggerito'), ('ricataloga', "Catalogo rifatto dall'archivio")], max_length=20)),
                ('parametri', models.JSONField(blank=True, default=dict)),
                ('stato', models.CharField(choices=[('attesa', 'In attesa'), ('in_corso', 'In corso'), ('ok', 'Riuscita'), ('errore', 'Non riuscita')], default='attesa', max_length=10)),
                ('esito', models.CharField(blank=True, default='', max_length=1000)),
                ('dettaglio', models.JSONField(blank=True, default=dict)),
                ('avviata_da', models.CharField(blank=True, default='', max_length=150)),
                ('avviata_il', models.DateTimeField(default=django.utils.timezone.now)),
                ('finita_il', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Operazione di manutenzione',
                'verbose_name_plural': 'Operazioni di manutenzione',
                'ordering': ['-avviata_il', '-id'],
            },
        ),
        migrations.CreateModel(
            name='AttivitaRaccolta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quando', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('tipo', models.CharField(choices=[('lettura', 'Lettura di un server'), ('pc', 'Lettura di un PC'), ('avvio', 'Raccoglitore avviato'), ('arresto', 'Raccoglitore fermato'), ('catalogo', 'Catalogo rifatto'), ('cartella', 'Archivio spostato'), ('sigillo', 'Giorno sigillato'), ('giornaliero', 'Lavori giornalieri')], db_index=True, max_length=12)),
                ('esito', models.CharField(choices=[('ok', 'Riuscita'), ('avviso', 'Da guardare'), ('errore', 'Non riuscita')], default='ok', max_length=7)),
                ('fonte_id', models.IntegerField(blank=True, null=True)),
                ('fonte_nome', models.CharField(blank=True, default='', max_length=120)),
                ('sistema', models.CharField(blank=True, default='', max_length=255)),
                ('righe', models.IntegerField(default=0)),
                ('durata_ms', models.IntegerField(blank=True, null=True)),
                ('messaggio', models.CharField(blank=True, default='', max_length=500)),
            ],
            options={
                'verbose_name': 'Attività della raccolta',
                'verbose_name_plural': 'Attività della raccolta',
                'ordering': ['-quando', '-id'],
                'indexes': [models.Index(fields=['tipo', 'quando'], name='reglog_att_tipo_quando')],
            },
        ),
    ]
