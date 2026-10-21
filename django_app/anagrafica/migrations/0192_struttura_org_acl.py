"""Binding ACL delle pagine «Struttura organizzativa» (struttura della Qualità),
copiati da quello del Mansionario (schema della 0185). Nelle view restano i
controlli propri: modifica = amministrazione anagrafica, emissione = solo MSM,
conferma rischi = HSE."""
from django.db import migrations

ROTTE = {
    "anagrafica:struttura_org": "anagrafica:mansionario",
    "anagrafica:struttura_reparto_salva": "anagrafica:mansionario",
    "anagrafica:struttura_area_salva": "anagrafica:mansionario",
    "anagrafica:struttura_ruolo_salva": "anagrafica:mansionario",
    "anagrafica:struttura_processo_salva": "anagrafica:mansionario",
    "anagrafica:struttura_revisioni": "anagrafica:mansionario",
    "anagrafica:struttura_revisione": "anagrafica:mansionario",
    "anagrafica:struttura_revisione_pdf": "anagrafica:mansionario",
    "anagrafica:struttura_rischi": "anagrafica:mansionario",
}
NOTA = "[STRUTTURA_ORG_0192] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = None
        for candidata in (sorella, "anagrafica:dipendenti_list"):
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
    """Voce «Struttura organizzativa» nel pilastro Persone, accanto all'Organigramma."""
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    cat = Cat.objects.filter(nome="Persone").order_by("id").first()
    if cat is None or Link.objects.filter(url_value="anagrafica:struttura_org").exists():
        return
    Link.objects.create(
        url_value="anagrafica:struttura_org", url_type="named", etichetta="Struttura organizzativa",
        icona="", gruppo="", categoria=cat, ordine=116,
        active_view_names=",".join(ROTTE),
        is_active=True, is_sistema=False,
    )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value="anagrafica:struttura_org").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0191_struttura_qualita"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
        migrations.RunPython(voce_menu, migrations.RunPython.noop),
    ]
