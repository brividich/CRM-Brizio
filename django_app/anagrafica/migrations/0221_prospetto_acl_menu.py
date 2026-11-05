"""Prospetto dei cambiamenti: binding ACL copiati dalla Struttura organizzativa (schema della 0192) e voce di menu.
Nelle view restano i controlli propri: vedere come la Struttura, preparare e applicare solo l'amministrazione."""
from django.db import migrations

ROTTE = (
    "anagrafica:prospetti", "anagrafica:prospetto_crea", "anagrafica:prospetto", "anagrafica:prospetto_aggiungi",
    "anagrafica:prospetto_togli", "anagrafica:prospetto_soglie", "anagrafica:prospetto_applica",
    "anagrafica:prospetto_annulla",
)
SORELLA = "anagrafica:struttura_org"
NOTA = "[PROSPETTO_0221] copiato da anagrafica:struttura_org"
VOCE = "anagrafica:prospetti"


def binding(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    modello = None
    for candidata in (SORELLA, "anagrafica:mansionario", "anagrafica:dipendenti_list"):
        modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
        if modello is not None:
            break
    if modello is None:
        return
    for rotta in ROTTE:
        if not Binding.objects.filter(route_name=rotta).exists():
            Binding.objects.create(
                route_name=rotta, path_pattern="", match_strategy=modello.match_strategy, permission_id=modello.permission_id,
                source_app="anagrafica", priority=modello.priority, is_active=True, note=NOTA,
            )


def voce_menu(apps, schema_editor):
    """Voce in Persone → Organizzazione, subito dopo Esplora la struttura."""
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    if Link.objects.filter(url_value=VOCE).exists():
        return
    vicina = (Link.objects.filter(url_value="anagrafica:esplora_struttura").order_by("id").first()
              or Link.objects.filter(url_value="anagrafica:aree_list").order_by("id").first())
    cat = vicina.categoria if vicina else Cat.objects.filter(nome="Persone").order_by("id").first()
    if cat is None:
        return
    Link.objects.create(
        url_value=VOCE, url_type="named", etichetta="Prospetto dei cambiamenti", icona="",
        gruppo=vicina.gruppo if vicina else "Organizzazione", categoria=cat, ordine=vicina.ordine if vicina else 144,
        active_view_names=",".join(ROTTE), is_active=True, is_sistema=False,
    )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(note=NOTA).delete()
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=VOCE, is_sistema=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0220_prospetto_struttura"),
    ]

    operations = [
        migrations.RunPython(binding, indietro),
        migrations.RunPython(voce_menu, migrations.RunPython.noop),
    ]
