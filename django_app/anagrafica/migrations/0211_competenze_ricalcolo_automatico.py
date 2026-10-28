"""Livelli sulle mansioni con competenze ricalcolati da soli (28/10/2026).

1. Nuova fonte «Ricalcolo automatico» nello storico delle abilitazioni.
2. Binding ACL v2 della cella della matrice persone × competenze, copiato da
   «Assegna» della scheda mansione (stesso permesso di «Valuta»).
"""
from django.db import migrations, models

ROTTA = "anagrafica:mansionario_voce_livello"
SORELLE = ("anagrafica:mansionario_valuta", "anagrafica:mansionario_assegna", "anagrafica:mansionario")
NOTA = "[MANSIONARIO_0211] copiato da anagrafica:mansionario_valuta"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if Binding.objects.filter(route_name=ROTTA).exists():
        return
    modello = None
    for candidata in SORELLE:
        modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
        if modello is not None:
            break
    if modello is None:
        return
    Binding.objects.create(
        route_name=ROTTA, path_pattern="", match_strategy=modello.match_strategy,
        permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
        is_active=True, note=NOTA,
    )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name=ROTTA, note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0210_mansionario_assegnazione_multipla_acl"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="abilitazionemacchinastorico",
            name="fonte",
            field=models.CharField(choices=[("import", "Import baseline"), ("refresh", "Refresh semestrale"),
                                            ("manuale", "Manuale"), ("automatico", "Ricalcolo automatico")],
                                   default="import", max_length=10),
        ),
        migrations.RunPython(avanti, indietro),
    ]
