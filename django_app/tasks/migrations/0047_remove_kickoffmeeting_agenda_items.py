"""Rimuove il JSON dei punti ODG: i dati vivono in MeetingAgendaItem (0046)."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0046_agenda_items_json_to_righe"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="kickoffmeeting",
            name="agenda_items",
        ),
    ]
