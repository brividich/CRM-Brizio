"""Mansionario fase 2: dati.

1. Ogni abilitazione su macchina (e il suo storico) si collega alla colonna della
   skill matrix del suo asset (``competenza``). Idempotente: tocca solo le righe
   ancora senza colonna.
2. Binding ACL v2 delle pagine del Mansionario, copiati dalla matrice macchina
   della skill matrix (schema della 0168): chi apre la skill matrix apre il
   Mansionario. Le modifiche restano protette dal cancello in-view.
"""
from django.db import migrations

ROTTE = {
    "anagrafica:mansionario": "anagrafica:skill_matrix_macchina",
    "anagrafica:mansionario_mansione": "anagrafica:skill_matrix_macchina",
    "anagrafica:mansionario_assegna": "anagrafica:skill_matrix_macchina",
    "anagrafica:mansionario_togli": "anagrafica:skill_matrix_macchina",
}
NOTA = "[MANSIONARIO_0171] copiato da {}"


def collega_abilitazioni(apps, schema_editor):
    Competenza = apps.get_model("anagrafica", "CompetenzaSkm")
    Abilitazione = apps.get_model("anagrafica", "AbilitazioneMacchina")
    Storico = apps.get_model("anagrafica", "AbilitazioneMacchinaStorico")
    per_asset: dict[int, int] = {}
    for pk, asset_id in (Competenza.objects.filter(tipo="macchina", asset__isnull=False)
                         .order_by("pk").values_list("pk", "asset_id")):
        per_asset.setdefault(asset_id, pk)
    for asset_id, comp_id in per_asset.items():
        Abilitazione.objects.filter(asset_id=asset_id, competenza__isnull=True).update(competenza_id=comp_id)
        Storico.objects.filter(asset_id=asset_id, competenza__isnull=True).update(competenza_id=comp_id)


def binding_acl(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = None
        for candidata in (sorella, "anagrafica:index"):
            modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
            if modello is not None:
                break
        if modello is None:
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def voce_menu(apps, schema_editor):
    """Voce «Mansionario» nel pilastro Competenze, gruppo Skill Matrix (idioma della 0072)."""
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    cat = Cat.objects.filter(nome="Competenze").order_by("id").first()
    if cat is None or Link.objects.filter(url_value="anagrafica:mansionario").exists():
        return
    Link.objects.create(
        url_value="anagrafica:mansionario", url_type="named", etichetta="Mansionario",
        icona="", gruppo="Skill Matrix", categoria=cat, ordine=275,
        active_view_names="anagrafica:mansionario,anagrafica:mansionario_mansione",
        is_active=True, is_sistema=False,
    )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value="anagrafica:mansionario").delete()


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0170_mansionario_mansione_skm")]
    operations = [
        migrations.RunPython(collega_abilitazioni, migrations.RunPython.noop),
        migrations.RunPython(binding_acl, indietro),
        migrations.RunPython(voce_menu, migrations.RunPython.noop),
    ]
