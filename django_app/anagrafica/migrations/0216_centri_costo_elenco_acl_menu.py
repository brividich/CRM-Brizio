"""Centri di costo: elenco dell'azienda, binding ACL (schema della 0201) e voce di menu.

L'elenco si carica solo dove la struttura esiste già: su un database vuoto (test,
nuova installazione) non crea aree che nessuno ha chiesto.
"""
from django.db import migrations

from anagrafica.centri_costo_dati import carica_elenco

ROTTE = {
    "anagrafica:centri_costo": "anagrafica:aree_list",
    "anagrafica:centro_costo_crea": "anagrafica:aree_list",
    "anagrafica:centro_costo_modifica": "anagrafica:aree_list",
    "anagrafica:centro_costo_elimina": "anagrafica:aree_list",
    "anagrafica:centro_costo_reparto_salva": "anagrafica:aree_list",
}
NOTA = "[CENTRI_COSTO_0216] copiato da {}"
VOCE = "anagrafica:centri_costo"


def elenco(apps, schema_editor):
    Area = apps.get_model("anagrafica", "AreaAziendale")
    if not Area.objects.exists():
        return
    carica_elenco(
        apps.get_model("anagrafica", "CentroDiCosto"), Area,
        apps.get_model("anagrafica", "Reparto"), apps.get_model("anagrafica", "RuoloOperativo"),
    )


def binding(apps, schema_editor):
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
    """Voce «Centri di costo» in Persone → Organizzazione, subito dopo Reparti."""
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    if Link.objects.filter(url_value=VOCE).exists():
        return
    reparti = Link.objects.filter(url_value="anagrafica:aree_list").order_by("id").first()
    cat = reparti.categoria if reparti else Cat.objects.filter(nome="Persone").order_by("id").first()
    if cat is None:
        return
    Link.objects.create(
        url_value=VOCE, url_type="named", etichetta="Centri di costo", icona="",
        gruppo=reparti.gruppo if reparti else "Organizzazione", categoria=cat,
        ordine=(reparti.ordine + 1) if reparti else 146,
        active_view_names=VOCE, is_active=True, is_sistema=False,
    )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=VOCE, is_sistema=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0215_centro_di_costo"),
    ]

    operations = [
        migrations.RunPython(elenco, migrations.RunPython.noop),
        migrations.RunPython(binding, indietro),
        migrations.RunPython(voce_menu, migrations.RunPython.noop),
    ]
