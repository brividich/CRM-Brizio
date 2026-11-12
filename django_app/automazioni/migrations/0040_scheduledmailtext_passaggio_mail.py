from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0039_indice_django_q_task"),
    ]

    operations = [
        migrations.AddField(
            model_name="scheduledmailtext",
            name="aggiungi_a",
            field=models.TextField(blank=True, default="", help_text="Indirizzi aggiunti in A a ogni mail del flusso."),
        ),
        migrations.AddField(
            model_name="scheduledmailtext",
            name="aggiungi_cc",
            field=models.TextField(blank=True, default="", help_text="Indirizzi aggiunti in CC a ogni mail del flusso."),
        ),
        migrations.AddField(
            model_name="scheduledmailtext",
            name="escludi",
            field=models.TextField(blank=True, default="", help_text="Indirizzi tolti da A e CC."),
        ),
        migrations.AddField(
            model_name="scheduledmailtext",
            name="sostituisci_destinatari",
            field=models.BooleanField(default=False, help_text="Se vero, le mail vanno solo agli indirizzi di «aggiungi_a» (i destinatari del modulo non ricevono)."),
        ),
        migrations.AddField(
            model_name="scheduledmailtext",
            name="mail_disattivata",
            field=models.BooleanField(default=False, help_text="Se vero, il flusso gira ma non manda mail."),
        ),
    ]
