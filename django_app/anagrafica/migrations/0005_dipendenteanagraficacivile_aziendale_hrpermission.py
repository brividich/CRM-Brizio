import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anagrafica', '0004_mansione_tipoqualifica_dipendentequalifica'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DipendenteAnagraficaCivile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('legacy_anagrafica_id', models.IntegerField(db_index=True, unique=True)),
                ('data_nascita', models.DateField(blank=True, null=True)),
                ('luogo_nascita', models.CharField(blank=True, default='', max_length=200)),
                ('genere', models.CharField(blank=True, choices=[('M', 'Maschile'), ('F', 'Femminile'), ('A', 'Non specificato')], default='', max_length=1)),
                ('indirizzo_residenza', models.CharField(blank=True, default='', max_length=300)),
                ('citta_residenza', models.CharField(blank=True, default='', max_length=100, verbose_name='Città residenza')),
                ('provincia_residenza', models.CharField(blank=True, default='', max_length=5)),
                ('nazione_residenza', models.CharField(blank=True, default='Italia', max_length=100)),
                ('cap_residenza', models.CharField(blank=True, default='', max_length=10, verbose_name='CAP residenza')),
                ('indirizzo_domicilio', models.CharField(blank=True, default='', max_length=300)),
                ('citta_domicilio', models.CharField(blank=True, default='', max_length=100, verbose_name='Città domicilio')),
                ('nazione_domicilio', models.CharField(blank=True, default='', max_length=100)),
                ('cap_domicilio', models.CharField(blank=True, default='', max_length=10, verbose_name='CAP domicilio')),
                ('codice_fiscale', models.CharField(blank=True, default='', max_length=16)),
                ('titolo_studio', models.CharField(blank=True, choices=[('PRIMO_GRADO', 'Istruzione primo grado'), ('SECONDO_GRADO', 'Istruzione secondo grado'), ('LAUREA_TRIENNALE', 'Laurea triennale'), ('LAUREA_MAGISTRALE', 'Laurea magistrale'), ('LAUREA_CICLO_UNICO', 'Laurea magistrale ciclo unico')], default='', max_length=20)),
                ('email_privata', models.EmailField(blank=True, default='', max_length=254)),
                ('telefono_privato', models.CharField(blank=True, default='', max_length=30)),
                ('patente_auto', models.BooleanField(default=False)),
                ('nome_banca', models.CharField(blank=True, default='', max_length=200)),
                ('iban', models.CharField(blank=True, default='', max_length=34, verbose_name='IBAN')),
                ('intestatario_conto', models.CharField(blank=True, default='', max_length=200)),
                ('categoria_protetta', models.BooleanField(default=False)),
                ('categoria_disabili', models.BooleanField(default=False)),
                ('percentuale_disabilita', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, verbose_name='Percentuale disabilità')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='anagrafica_civile_aggiornate', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Anagrafica civile dipendente',
                'verbose_name_plural': 'Anagrafiche civili dipendenti',
            },
        ),
        migrations.CreateModel(
            name='DipendenteAnagraficaAziendale',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('legacy_anagrafica_id', models.IntegerField(db_index=True, unique=True)),
                ('area', models.CharField(blank=True, default='', max_length=100, verbose_name='Area di appartenenza')),
                ('ruolo_aziendale', models.CharField(blank=True, default='', max_length=200, verbose_name='Ruolo aziendale')),
                ('taglia_scarpe', models.CharField(blank=True, default='', max_length=10)),
                ('taglia_pantalone', models.CharField(blank=True, default='', max_length=20)),
                ('taglia_maglia', models.CharField(blank=True, choices=[('XS', 'XS'), ('S', 'S'), ('M', 'M'), ('L', 'L'), ('XL', 'XL'), ('XXL', 'XXL'), ('XXXL', 'XXXL')], default='', max_length=10)),
                ('consenso_privacy', models.BooleanField(default=False)),
                ('data_consenso_privacy', models.DateField(blank=True, null=True)),
                ('data_prima_assunzione', models.DateField(blank=True, null=True)),
                ('prova_data_inizio', models.DateField(blank=True, null=True, verbose_name='Inizio periodo di prova')),
                ('prova_data_fine', models.DateField(blank=True, null=True, verbose_name='Fine periodo di prova')),
                ('tipologia_contratto', models.CharField(blank=True, choices=[('INDETERMINATO', 'Tempo indeterminato'), ('DETERMINATO', 'Tempo determinato'), ('APPRENDISTATO', 'Apprendistato'), ('SOMMINISTRAZIONE', 'Somministrazione'), ('COLLABORAZIONE', 'Collaborazione'), ('STAGE', 'Stage / Tirocinio'), ('ALTRO', 'Altro')], default='', max_length=20)),
                ('livello_inquadramento', models.CharField(blank=True, default='', max_length=50)),
                ('email_aziendale', models.EmailField(blank=True, default='', max_length=254)),
                ('telefono_aziendale', models.CharField(blank=True, default='', max_length=30)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='anagrafica_aziendale_aggiornate', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Anagrafica aziendale dipendente',
                'verbose_name_plural': 'Anagrafiche aziendali dipendenti',
            },
        ),
        migrations.CreateModel(
            name='AnagraficaHRPermission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('accesso', models.CharField(choices=[('TUTTI', 'Tutti gli utenti autenticati'), ('ADMIN', 'Solo amministratori'), ('RUOLI', 'Ruoli ACL specifici')], default='ADMIN', max_length=20)),
                ('ruolo_ids', models.JSONField(blank=True, default=list, help_text='Lista ruolo_id ACL legacy abilitati (usato solo se accesso=RUOLI)')),
            ],
            options={
                'verbose_name': 'Permessi dati HR riservati',
                'verbose_name_plural': 'Permessi dati HR riservati',
            },
        ),
    ]
