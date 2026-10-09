from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Termine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('termine', models.CharField(max_length=150, verbose_name='Termine')),
                ('termine_en', models.CharField(blank=True, default='', max_length=150, verbose_name='Termine inglese')),
                ('categoria', models.CharField(choices=[('lavorazione', 'Lavorazione'), ('quotatura', 'Quotatura'), ('tolleranza_dimensionale', 'Tolleranza dimensionale'), ('gdt', 'Tolleranze geometriche (GD&T)'), ('rugosita', 'Rugosità'), ('filettatura', 'Filettatura'), ('trattamento_termico', 'Trattamento termico'), ('trattamento_superficiale', 'Trattamento superficiale'), ('materiale', 'Materiale'), ('controllo_qualita', 'Controllo qualità'), ('sgi_documentale', 'SGI documentale'), ('sigla_aziendale', 'Sigla aziendale')], db_index=True, max_length=30, verbose_name='Categoria')),
                ('definizione', models.TextField(verbose_name='Definizione')),
                ('simbolo', models.CharField(blank=True, default='', max_length=20, verbose_name='Simbolo')),
                ('esempio_disegno', models.CharField(blank=True, default='', max_length=200, verbose_name='Esempio a disegno')),
                ('norma_rif', models.CharField(blank=True, default='', max_length=60, verbose_name='Norma di riferimento')),
                ('stato', models.CharField(choices=[('bozza', 'Bozza'), ('validato', 'Validato'), ('deprecato', 'Deprecato')], db_index=True, default='bozza', max_length=10, verbose_name='Stato')),
                ('fonte', models.CharField(choices=[('manuale', 'Inserito a mano'), ('seed', 'Elenco iniziale'), ('ai_proposta', 'Proposta AI accettata'), ('import_csv', 'Import CSV')], default='manuale', max_length=20, verbose_name='Fonte')),
                ('usa_nel_rag', models.BooleanField(default=True, verbose_name="Usa nell'assistente")),
                ('note_interne', models.TextField(blank=True, default='', verbose_name='Note interne')),
                ('validato_il', models.DateTimeField(blank=True, null=True, verbose_name='Validato il')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('validato_da', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='glossario_termini_validati', to=settings.AUTH_USER_MODEL, verbose_name='Validato da')),
            ],
            options={
                'verbose_name': 'Termine',
                'verbose_name_plural': 'Termini',
                'ordering': ['termine'],
                'constraints': [models.UniqueConstraint(fields=('termine', 'categoria'), name='uq_termine_categoria')],
            },
        ),
        migrations.CreateModel(
            name='Variante',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('testo', models.CharField(max_length=150, verbose_name='Testo')),
                ('tipo', models.CharField(choices=[('sinonimo', 'Sinonimo'), ('gergo', "Gergo d'officina"), ('abbreviazione', 'Abbreviazione / sigla'), ('simbolo', 'Simbolo'), ('traduzione', 'Traduzione'), ('grafia_errata', 'Grafia errata frequente')], max_length=15, verbose_name='Tipo')),
                ('lingua', models.CharField(default='it', max_length=2, verbose_name='Lingua')),
                ('chiave', models.CharField(db_index=True, editable=False, max_length=150, unique=True)),
                ('termine', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='varianti', to='glossario_tecnico.termine')),
            ],
            options={
                'verbose_name': 'Variante',
                'verbose_name_plural': 'Varianti',
                'ordering': ['tipo', 'testo'],
            },
        ),
    ]
