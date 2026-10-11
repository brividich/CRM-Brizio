"""Domande del quiz tipizzate (prompt 05, fase 2): singola, multipla, vero/falso.

Le domande esistenti con più risposte giuste diventano «multipla» (prima il quiz
le correggeva già come insieme); tutte le altre «singola». Più il binding ACL
dell'import da Excel, copiato dalla rotta sorella (schema 0148).
"""
from django.db import migrations, models

ROTTE = {"anagrafica:formazione_question_import": "anagrafica:formazione_question_save"}
NOTA = "[ELEARNING_0150] copiato da {}"


def tipizza(apps, schema_editor):
    Domanda = apps.get_model("anagrafica", "TrainingQuizQuestion")
    Opzione = apps.get_model("anagrafica", "TrainingQuizOption")
    conteggi = {}
    for did in Opzione.objects.filter(corretta=True).values_list("domanda_id", flat=True):
        conteggi[did] = conteggi.get(did, 0) + 1
    multiple = [did for did, n in conteggi.items() if n > 1]
    if multiple:
        Domanda.objects.filter(pk__in=multiple).update(tipo="MULTIPLA")


def binding(apps, schema_editor):
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
        ("anagrafica", "0149_elearning_self_service_e_limiti"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.AddField(
            model_name="trainingquizquestion",
            name="tipo",
            field=models.CharField(
                choices=[("SINGOLA", "Risposta singola"), ("MULTIPLA", "Risposta multipla"),
                         ("VERO_FALSO", "Vero / falso")],
                default="SINGOLA", max_length=10,
            ),
        ),
        migrations.RunPython(tipizza, migrations.RunPython.noop),
        migrations.RunPython(binding, binding_indietro),
    ]
