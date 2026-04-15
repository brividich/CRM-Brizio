import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('automazioni', '0010_automationdeliveryendpoint'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ApprovalEmailTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=120, unique=True, verbose_name='Codice univoco')),
                ('name', models.CharField(max_length=255, verbose_name='Nome')),
                ('description', models.TextField(blank=True, default='', verbose_name='Descrizione')),
                ('is_enabled', models.BooleanField(db_index=True, default=True, verbose_name='Abilitato')),
                ('delivery_mode', models.CharField(
                    choices=[
                        ('portal_links', 'Link portale (HTTP)'),
                        ('mail_reply', 'Risposta email (mailto:)'),
                        ('hybrid', 'Ibrido (link portale + mailto:)'),
                    ],
                    default='portal_links',
                    max_length=20,
                    verbose_name='Modalità recapito',
                )),
                ('subject_template', models.CharField(
                    default='Richiesta di approvazione #{id}',
                    help_text='Supporta placeholder {campo}.',
                    max_length=512,
                    verbose_name='Oggetto email',
                )),
                ('title_template', models.CharField(
                    blank=True,
                    default='',
                    help_text='Titolo grande visualizzato in cima al corpo email.',
                    max_length=512,
                    verbose_name='Titolo / intestazione mail',
                )),
                ('intro_template', models.TextField(
                    blank=True,
                    default='',
                    help_text='Paragrafo introduttivo sopra i facts. Supporta placeholder.',
                    verbose_name='Testo introduttivo',
                )),
                ('body_template', models.TextField(
                    blank=True,
                    default='',
                    help_text='Corpo HTML opzionale a sostituzione completa di intro+facts. Se compilato, intro_template e facts vengono ignorati.',
                    verbose_name='Corpo libero (HTML)',
                )),
                ('include_facts', models.BooleanField(
                    default=True,
                    help_text='Se attivo, mostra una tabella facts nella mail (ignorato se body_template è compilato).',
                    verbose_name='Includi facts / riepilogo',
                )),
                ('facts_lines', models.TextField(
                    blank=True,
                    default='',
                    help_text='Una riga per fatto: Etichetta | {placeholder}',
                    verbose_name='Righe facts',
                )),
                ('approval_label', models.CharField(default='Approva', max_length=100, verbose_name='"Approva" label')),
                ('rejection_label', models.CharField(default='Rifiuta', max_length=100, verbose_name='"Rifiuta" label')),
                ('include_mailto_actions', models.BooleanField(
                    default=False,
                    help_text='Genera link mailto: verso la mailbox tecnica. Attivo solo per delivery_mode mail_reply o hybrid.',
                    verbose_name='Includi CTA mailto:',
                )),
                ('mailto_mailbox', models.CharField(
                    blank=True,
                    default='',
                    help_text='Es. approvazioni@cnovicrom.local — sovrascrive il default globale se compilato.',
                    max_length=255,
                    verbose_name='Mailbox tecnica approvazioni',
                )),
                ('approval_mailto_subject_template', models.CharField(
                    blank=True,
                    default='CMD APPROVO RID {approval_token}',
                    help_text='Deterministic subject per il parser. Usa {approval_token} come identificatore univoco.',
                    max_length=512,
                    verbose_name='Oggetto mailto Approva',
                )),
                ('approval_mailto_body_template', models.TextField(
                    blank=True,
                    default='CMD: APPROVO\nRID: {approval_token}',
                    verbose_name='Corpo mailto Approva',
                )),
                ('rejection_mailto_subject_template', models.CharField(
                    blank=True,
                    default='CMD RIFIUTO RID {approval_token}',
                    help_text='Deterministic subject per il parser. Usa {approval_token} come identificatore univoco.',
                    max_length=512,
                    verbose_name='Oggetto mailto Rifiuta',
                )),
                ('rejection_mailto_body_template', models.TextField(
                    blank=True,
                    default='CMD: RIFIUTO\nRID: {approval_token}\nMOTIVO: ',
                    verbose_name='Corpo mailto Rifiuta',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='approval_email_templates_created',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('updated_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='approval_email_templates_updated',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Template email approvazione',
                'verbose_name_plural': 'Template email approvazioni',
                'ordering': ['name'],
            },
        ),
    ]
