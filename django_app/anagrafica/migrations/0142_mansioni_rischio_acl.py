"""Binding ACL v2 delle pagine delle mansioni di rischio, copiati dalle rotte sorelle.

Stesso schema della 0135: con ACL_STRICT_CANONICAL una route senza binding è
negata ai non superuser, e i binding di anagrafica vivono nel DB. Le nuove rotte
ereditano il binding della rotta che fa la stessa cosa; dentro le view restano i
cancelli (amministrazione anagrafica / dati HR / permesso visite).

Create-only e idempotente: un binding già presente (anche disattivato) non si
tocca; se la sorella non ha binding proprio (coperta da prefisso) non si crea nulla.
"""
from django.db import migrations

ROTTE = {
    "anagrafica:mansioni_rischio_list": "anagrafica:mansione_requisiti",
    "anagrafica:mansione_rischio_dettaglio": "anagrafica:mansione_requisiti",
    "anagrafica:mansione_rischio_nuova": "anagrafica:mansione_requisiti",
    "anagrafica:mansione_rischio_modifica": "anagrafica:mansione_requisiti",
    "anagrafica:sicurezza_operativa_config": "anagrafica:mansione_requisiti",
    "anagrafica:organigramma_mansioni_rischio": "anagrafica:organigramma",
    "anagrafica:dipendente_sicurezza_panel": "anagrafica:dipendente_conformita_panel",
    "anagrafica:dipendente_override_aggiungi": "anagrafica:dipendente_assegnazione_modifica",
    "anagrafica:dipendente_override_revoca": "anagrafica:dipendente_assegnazione_modifica",
    "anagrafica:dipendente_deroga_aggiungi": "anagrafica:dipendente_assegnazione_modifica",
    "anagrafica:dipendente_deroga_revoca": "anagrafica:dipendente_assegnazione_modifica",
}
NOTA = "[MANSIONI_RISCHIO_0142] copiato da {}"


def avanti(apps, schema_editor):
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


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0141_adempimento_chiave_unique"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
