import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('automazioni', '0011_approvalemailtemplate'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApprovalMailboxMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('internet_message_id', models.CharField(
                    db_index=True,
                    help_text='Header RFC 2822 Message-ID. Chiave di deduplica globale.',
                    max_length=512,
                    unique=True,
                )),
                ('graph_message_id', models.CharField(
                    blank=True,
                    default='',
                    help_text='ID opaco Graph API (usato per PATCH mark-as-read, move, ecc.).',
                    max_length=255,
                )),
                ('mailbox', models.CharField(
                    db_index=True,
                    help_text='Indirizzo mailbox letta (es. avviso@costruzioninovicrom.it).',
                    max_length=255,
                )),
                ('folder_name', models.CharField(blank=True, default='', help_text='Cartella di provenienza.', max_length=255)),
                ('subject_raw', models.TextField(blank=True, default='', help_text='Oggetto grezzo del messaggio.')),
                ('from_email', models.CharField(blank=True, default='', help_text='Indirizzo mittente estratto.', max_length=255)),
                ('received_at', models.DateTimeField(
                    blank=True,
                    db_index=True,
                    help_text='Data/ora ricezione.',
                    null=True,
                )),
                ('command_detected', models.CharField(
                    blank=True,
                    default='',
                    help_text="Comando rilevato: 'approvo', 'rifiuto' oppure vuoto se nessuno.",
                    max_length=20,
                )),
                ('token_found', models.CharField(
                    blank=True,
                    default='',
                    help_text='UUID token approvazione estratto dal messaggio.',
                    max_length=36,
                )),
                ('processing_status', models.CharField(
                    choices=[
                        ('pending', 'In attesa'),
                        ('processed', 'Processato'),
                        ('ignored', 'Ignorato'),
                        ('error', 'Errore'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=20,
                )),
                ('processing_error', models.TextField(blank=True, default='', help_text='Dettaglio errore se status=error.')),
                ('excerpt', models.TextField(blank=True, default='', help_text='Estratto body (max 500 car.) per diagnostica.')),
                ('linked_approval', models.ForeignKey(
                    blank=True,
                    help_text="Approvazione collegata, se il messaggio è stato processato con successo.",
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='mailbox_messages',
                    to='automazioni.automationapproval',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Messaggio mailbox approvazione',
                'verbose_name_plural': 'Messaggi mailbox approvazione',
                'ordering': ['-received_at', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='approvalmailboxmessage',
            index=models.Index(
                fields=['processing_status', 'received_at'],
                name='autom_mbmsg_status_rcv_idx',
            ),
        ),
    ]
