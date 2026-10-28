"""Assets: «IT e rete» e «Fornitori e contratti» diventano moduli della matrice ruoli (28/10/2026).

- IT e rete (``assets_it``): rete, rack, catalogo software, licenze e riconciliazione
  dei dispositivi. Sono pagine d'insieme che l'ambito non restringe: prima stavano
  nell'Inventario e un caporeparto con «Propri» vedeva la rete di tutta l'azienda.
  Ricevono la cella dell'Inventario solo i ruoli che lo hanno su «tutti».
- Fornitori e contratti (``assets_fornitori``): esce dalla Manutenzione con le
  stesse celle (stesso ambito: i contratti seguono il loro asset).
- La riconciliazione dei dispositivi (``/assets/dispositivi/riconciliazione/``) si
  lega allo stesso permesso di rete e catalogo software (assets 0130, 0147).

I permessi di pagina cambiano al primo «Salva matrice» / «Sincronizza».
"""
from django.db import migrations
from django.db.models import Q

NOTA = "[CORE_0100] assets IT e rete, fornitori e contratti"
PATH_RICONCILIAZIONE = "/assets/dispositivi/riconciliazione/"
CODICE_IT = "legacy.assets.assets_software_licenses"


def _copia(Cella, fonte, destinazione, *, solo_tutti):
    esistenti = set(Cella.objects.filter(modulo=destinazione).values_list("ruolo_id", "azione"))
    celle = Cella.objects.filter(modulo=fonte).exclude(azione="impostazioni")
    if solo_tutti:
        celle = celle.filter(ambito="tutti")
    # Una riga per volta: su SQL Server l'INSERT a lotti rompe i savepoint delle migrazioni.
    for cella in celle:
        if (cella.ruolo_id, cella.azione) in esistenti:
            continue
        Cella(
            ruolo_id=cella.ruolo_id, modulo=destinazione, azione=cella.azione,
            ambito=cella.ambito, consentito=cella.consentito, note=cella.note,
        ).save()


def avanti(apps, schema_editor):
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    _copia(Cella, "assets", "assets_it", solo_tutti=True)
    _copia(Cella, "assets_manutenzione", "assets_fornitori", solo_tutti=False)

    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    vicino = (
        Binding.objects.filter(
            Q(path_pattern__startswith="/assets/software") | Q(path_pattern__startswith="/assets/rete"),
            is_active=True,
        )
        .order_by("-priority", "path_pattern", "id")
        .first()
    )
    code = vicino.permission_id if vicino else CODICE_IT
    if not Permission.objects.filter(code=code).exists():
        return  # database senza i permessi asset: li crea il bootstrap del modulo
    Binding.objects.get_or_create(
        route_name="",
        path_pattern=PATH_RICONCILIAZIONE,
        defaults={
            "permission_id": code, "match_strategy": "prefix", "source_app": "assets",
            "priority": 100, "is_active": True, "note": NOTA,
        },
    )


def indietro(apps, schema_editor):
    apps.get_model("core", "RuoloPermessoModulo").objects.filter(modulo__in=("assets_it", "assets_fornitori")).delete()
    apps.get_model("core", "RoutePermissionBinding").objects.filter(note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0099_assets_sottomoduli_permessi")]
    operations = [migrations.RunPython(avanti, indietro)]
