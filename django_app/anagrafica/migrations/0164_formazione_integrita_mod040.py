"""Formazione: integrità dei dati, approvazione MOD.040, annullamento motivato.

Prima dei vincoli nuovi una bonifica deterministica (i vincoli fallirebbero su
dati storici fuori regola): date di edizione invertite scambiate, percentuali
e punteggi riportati in 0-100, ore negative azzerate. Nulla viene cancellato.
I doppioni (persona, corso, data) restano a `pulisci_scadenze_hr --doppioni`. Poi i binding ACL delle rotte nuove, copiati dalle
rotte sorelle (schema 0156/0163: create-only, idempotente).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


ROTTE = {
    "anagrafica:formazione_sessione_approva": "anagrafica:formazione_sessione_edit",
    "anagrafica:formazione_sessione_riapri": "anagrafica:formazione_sessione_edit",
    "anagrafica:formazione_sessione_verifica_nc": "anagrafica:formazione_sessione_edit",
    "anagrafica:formazione_sessione_mod040": "anagrafica:formazione_sessione_fascicolo",
    "anagrafica:formazione_record_annulla": "anagrafica:formazione_iscrizione_edit",
    "anagrafica:formazione_integrita": "anagrafica:formazione_dashboard",
    "anagrafica:formazione_guida": "anagrafica:formazione_dashboard",
}
NOTA = "[FORMAZIONE_0164] copiato da {}"


def bonifica(apps, schema_editor):
    from django.db.models import F

    Session = apps.get_model("anagrafica", "TrainingSession")
    Enrollment = apps.get_model("anagrafica", "TrainingEnrollment")
    Attendance = apps.get_model("anagrafica", "TrainingLessonAttendance")
    Record = apps.get_model("anagrafica", "TrainingEmployeeRecord")

    for s in Session.objects.filter(data_fine__lt=F("data_inizio")):
        s.data_inizio, s.data_fine = s.data_fine, s.data_inizio
        s.save(update_fields=["data_inizio", "data_fine"])
    for Model in (Enrollment, Record):
        Model.objects.filter(percentuale_presenza__gt=100).update(percentuale_presenza=100)
        Model.objects.filter(percentuale_presenza__lt=0).update(percentuale_presenza=0)
        Model.objects.filter(ore_frequentate__lt=0).update(ore_frequentate=0)
    Enrollment.objects.filter(punteggio__gt=100).update(punteggio=100)
    Enrollment.objects.filter(punteggio__lt=0).update(punteggio=0)
    Attendance.objects.filter(ore_effettive__lt=0).update(ore_effettive=0)


def binding_avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
        if modello is None:
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def binding_indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('anagrafica', '0163_avviso_it_acl'),
        ('core', '0074_admin_subnav_accessi_negati'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='trainingemployeerecord',
            name='annullato_da',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='trainingemployeerecord',
            name='annullato_da_nome',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='trainingemployeerecord',
            name='annullato_il',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='trainingemployeerecord',
            name='annullato_motivo',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='trainingsession',
            name='approvata_da',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='trainingsession',
            name='approvata_da_nome',
            field=models.CharField(blank=True, default='', help_text="Snapshot di chi ha approvato: resta leggibile anche se l'utenza sparisce.", max_length=200),
        ),
        migrations.AddField(
            model_name='trainingsession',
            name='approvata_il',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='trainingsession',
            name='approvazione_note',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='trainingsession',
            name='verifica_nc_da',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='trainingsession',
            name='verifica_nc_da_nome',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='trainingsession',
            name='verifica_nc_esito',
            field=models.CharField(blank=True, choices=[('SI', 'Sì, nessuna NC'), ('NO', 'No, NC riconducibili alla formazione'), ('NA', 'Non applicabile')], default='', max_length=2),
        ),
        migrations.AddField(
            model_name='trainingsession',
            name='verifica_nc_il',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='trainingsession',
            name='verifica_nc_note',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='trainingcourse',
            name='quiz_punteggio_minimo',
            field=models.PositiveSmallIntegerField(default=70, help_text="Percentuale minima per superare la verifica finale: quiz e-learning e soglia proposta per la verifica d'aula."),
        ),
        migrations.AlterField(
            model_name='trainingexportlog',
            name='tipo',
            field=models.CharField(choices=[('PIANI', 'Elenco piani formativi'), ('CORSI', 'Elenco corsi'), ('ISCRITTI', 'Iscritti sessione'), ('PRESENZE', 'Presenze lezione'), ('STORICO_DIP', 'Storico dipendente'), ('SCADENZARIO', 'Scadenzario formazione'), ('MATRICE', 'Matrice dipendente × corso'), ('KPI', 'Report KPI direzionale'), ('REPORT_FIRMA', 'Report firma lezione PDF'), ('ATTESTATO', 'Attestato di completamento'), ('MOD040', 'MOD.040 Registro Corsi')], max_length=20),
        ),
        migrations.RunPython(bonifica, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='trainingemployeerecord',
            constraint=models.CheckConstraint(condition=models.Q(('ore_frequentate__gte', 0)), name='training_record_ore_non_negative'),
        ),
        migrations.AddConstraint(
            model_name='trainingemployeerecord',
            constraint=models.CheckConstraint(condition=models.Q(('percentuale_presenza__isnull', True), models.Q(('percentuale_presenza__gte', 0), ('percentuale_presenza__lte', 100)), _connector='OR'), name='training_record_percentuale_0_100'),
        ),
        migrations.AddConstraint(
            model_name='trainingenrollment',
            constraint=models.CheckConstraint(condition=models.Q(('ore_frequentate__gte', 0)), name='training_enrollment_ore_non_negative'),
        ),
        migrations.AddConstraint(
            model_name='trainingenrollment',
            constraint=models.CheckConstraint(condition=models.Q(('percentuale_presenza__isnull', True), models.Q(('percentuale_presenza__gte', 0), ('percentuale_presenza__lte', 100)), _connector='OR'), name='training_enrollment_percentuale_0_100'),
        ),
        migrations.AddConstraint(
            model_name='trainingenrollment',
            constraint=models.CheckConstraint(condition=models.Q(('punteggio__isnull', True), models.Q(('punteggio__gte', 0), ('punteggio__lte', 100)), _connector='OR'), name='training_enrollment_punteggio_0_100'),
        ),
        migrations.AddConstraint(
            model_name='traininglessonattendance',
            constraint=models.CheckConstraint(condition=models.Q(('ore_effettive__isnull', True), ('ore_effettive__gte', 0), _connector='OR'), name='training_attendance_ore_non_negative'),
        ),
        migrations.AddConstraint(
            model_name='trainingsession',
            constraint=models.CheckConstraint(condition=models.Q(('data_fine__gte', models.F('data_inizio'))), name='training_session_fine_dopo_inizio'),
        ),
        migrations.RunPython(binding_avanti, binding_indietro),
    ]
