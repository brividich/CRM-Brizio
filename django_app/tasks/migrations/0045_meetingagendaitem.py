"""Punti ODG come righe: crea la tabella (dati copiati in 0046, JSON rimosso in 0047)."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0044_taskimpostazioni_cc_predefiniti'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MeetingAgendaItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ordine', models.PositiveIntegerField(default=0, verbose_name='Ordine')),
                ('item_id', models.CharField(max_length=255, verbose_name='Id punto')),
                ('titolo', models.CharField(max_length=240, verbose_name='Titolo')),
                ('nota', models.TextField(blank=True, default='', verbose_name='Nota')),
                ('source', models.CharField(blank=True, default='', max_length=40, verbose_name='Origine')),
                ('locked', models.BooleanField(default=False, verbose_name='Bloccato')),
                ('done', models.BooleanField(default=False, verbose_name='Trattato')),
                ('task_label', models.CharField(blank=True, default='', max_length=200)),
                ('responsabile_label', models.CharField(blank=True, default='', max_length=150)),
                ('durata_minuti', models.PositiveIntegerField(blank=True, null=True, verbose_name='Durata prevista (min)')),
                ('tempo_effettivo_minuti', models.PositiveIntegerField(blank=True, null=True, verbose_name='Tempo effettivo (min)')),
                ('custom_fields', models.JSONField(blank=True, default=list, verbose_name='Campi aggiuntivi')),
                ('action', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='tasks.meetingactionitem', verbose_name='Azione')),
                ('issue', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='tasks.meetingissue', verbose_name='Problema')),
                ('meeting', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agenda_rows', to='tasks.kickoffmeeting', verbose_name='Incontro')),
                ('responsabile', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Responsabile')),
                ('task', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='tasks.task', verbose_name="Attivita'")),
            ],
            options={
                'verbose_name': 'Punto ordine del giorno',
                'verbose_name_plural': 'Punti ordine del giorno',
                'ordering': ['meeting', 'ordine', 'id'],
                'constraints': [models.UniqueConstraint(fields=('meeting', 'item_id'), name='tasks_agendaitem_meeting_item_uniq')],
            },
        ),
    ]
