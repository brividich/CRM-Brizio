"""Percorso «Prepara la sessione» (27/11/2026): permesso copiato da «Modifica
sessione» (stesse persone che creano e modificano le edizioni) e voce di menu
attiva come per «Nuova sessione». Idempotente, nessun cambio di schema."""
from django.db import migrations

NOTA = "[SESSIONE_PREPARA_0268] copiato dalla rotta sorella"
ROTTA = "anagrafica:formazione_sessione_prepara"
SORELLE = ("anagrafica:formazione_sessione_edit", "anagrafica:formazione_sessione_create",
           "anagrafica:formazione_sessione_detail")


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if not Binding.objects.filter(route_name=ROTTA).exists():
        modello = None
        for sorella in SORELLE:
            modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
            if modello is not None:
                break
        if modello is not None:
            Binding.objects.create(
                route_name=ROTTA, path_pattern="", match_strategy=modello.match_strategy,
                permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
                is_active=True, note=NOTA,
            )
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    for link in Link.objects.all():
        nomi = [n.strip() for n in (link.active_view_names or "").split(",") if n.strip()]
        if "anagrafica:formazione_sessione_create" in nomi and ROTTA not in nomi:
            nomi.append(ROTTA)
            valore = ",".join(nomi)
            if len(valore) <= 500:
                link.active_view_names = valore
                link.save(update_fields=["active_view_names"])


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name=ROTTA, note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0267_togli_assegnazioni_doppie_edizione"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
