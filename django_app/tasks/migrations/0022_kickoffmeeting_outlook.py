from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0021_kickoffmeeting"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="kickoffmeeting",
            name="partecipanti_utenti",
            field=models.ManyToManyField(
                blank=True,
                related_name="kickoff_meetings_as_partecipante",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Partecipanti portale",
            ),
        ),
        migrations.AddField(
            model_name="kickoffmeeting",
            name="partecipanti_email_extra",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Un indirizzo email per riga (per partecipanti non presenti nel portale).",
                verbose_name="Email aggiuntive",
            ),
        ),
        migrations.AlterField(
            model_name="kickoffmeeting",
            name="partecipanti_testo",
            field=models.TextField(blank=True, default="", verbose_name="Note partecipanti"),
        ),
        migrations.AddField(
            model_name="kickoffmeeting",
            name="sync_outlook",
            field=models.BooleanField(
                default=False,
                help_text="Se attivo, invia/aggiorna un evento calendario a tutti i partecipanti con email.",
                verbose_name="Crea/aggiorna evento Outlook",
            ),
        ),
        migrations.AddField(
            model_name="kickoffmeeting",
            name="outlook_organizer_email",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Lascia vuoto per usare l'email dell'utente che salva l'incontro.",
                max_length=254,
                verbose_name="Email organizzatore (Outlook)",
            ),
        ),
        migrations.AddField(
            model_name="kickoffmeeting",
            name="outlook_event_id",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AddField(
            model_name="kickoffmeeting",
            name="outlook_event_web_link",
            field=models.CharField(blank=True, default="", max_length=1024),
        ),
    ]
