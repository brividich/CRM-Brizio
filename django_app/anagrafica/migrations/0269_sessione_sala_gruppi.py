"""Percorso «Prepara la sessione», seconda parte (28/11/2026): sala aziendale
sulla sessione, prenotazione Outlook per giornata e permesso della rotta delle
azioni del percorso (gruppi, sala, programma, copia giornate), copiato da
«Prepara la sessione»."""
import django.db.models.deletion
from django.db import migrations, models

NOTA = "[SESSIONE_PREPARA_0269] copiato dalla rotta sorella"
ROTTA = "anagrafica:formazione_sessione_prepara_azione"
SORELLE = ("anagrafica:formazione_sessione_prepara", "anagrafica:formazione_sessione_edit",
           "anagrafica:formazione_sessione_create")


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if Binding.objects.filter(route_name=ROTTA).exists():
        return
    for sorella in SORELLE:
        modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
        if modello is not None:
            Binding.objects.create(
                route_name=ROTTA, path_pattern="", match_strategy=modello.match_strategy,
                permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
                is_active=True, note=NOTA,
            )
            return


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name=ROTTA, note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0268_sessione_prepara_binding"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
        ("tasks", "0075_capocommessa_unico"),
    ]

    operations = [
        migrations.AddField(
            model_name="trainingsession",
            name="sala",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="sessioni_formazione", to="tasks.meetingroom", verbose_name="Sala",
            ),
        ),
        migrations.AddField(
            model_name="traininglesson",
            name="outlook_event_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="traininglesson",
            name="outlook_organizer_email",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.RunPython(avanti, indietro),
    ]
