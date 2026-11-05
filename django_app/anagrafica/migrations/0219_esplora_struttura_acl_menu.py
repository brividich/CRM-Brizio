"""«Esplora la struttura»: binding ACL copiato dalla Struttura organizzativa (schema della 0192) e voce di menu."""
from django.db import migrations

ROTTA = "anagrafica:esplora_struttura"
SORELLA = "anagrafica:struttura_org"
NOTA = "[ESPLORA_0219] copiato da anagrafica:struttura_org"


def binding(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if Binding.objects.filter(route_name=ROTTA).exists():
        return
    modello = None
    for candidata in (SORELLA, "anagrafica:mansionario", "anagrafica:dipendenti_list"):
        modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
        if modello is not None:
            break
    if modello is None:
        return
    Binding.objects.create(
        route_name=ROTTA, path_pattern="", match_strategy=modello.match_strategy, permission_id=modello.permission_id,
        source_app="anagrafica", priority=modello.priority, is_active=True, note=NOTA,
    )


def voce_menu(apps, schema_editor):
    """Voce in Persone → Organizzazione, prima di Reparti."""
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    if Link.objects.filter(url_value=ROTTA).exists():
        return
    reparti = Link.objects.filter(url_value="anagrafica:aree_list").order_by("id").first()
    cat = reparti.categoria if reparti else Cat.objects.filter(nome="Persone").order_by("id").first()
    if cat is None:
        return
    Link.objects.create(
        url_value=ROTTA, url_type="named", etichetta="Esplora la struttura", icona="",
        gruppo=reparti.gruppo if reparti else "Organizzazione", categoria=cat,
        ordine=(reparti.ordine - 1) if reparti else 144,
        active_view_names=ROTTA, is_active=True, is_sistema=False,
    )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name=ROTTA, note=NOTA).delete()
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=ROTTA, is_sistema=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0218_report_centri_costo_predefinito"),
    ]

    operations = [
        migrations.RunPython(binding, indietro),
        migrations.RunPython(voce_menu, migrations.RunPython.noop),
    ]
