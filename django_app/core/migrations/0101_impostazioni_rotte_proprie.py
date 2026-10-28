"""Le pagine Impostazioni rimaste sul permesso condiviso: binding per nome rotta.

La 0097 aveva dato a ogni modulo l'azione «impostazioni», ma per diario
preposto, rilevazione incidenti, ticket, timbri e la pagina principale delle
impostazioni DPI la rotta restava protetta dal vecchio permesso (prefisso della
lista o permesso legacy acceso solo da «gestire»). Effetti: la sotto-riga
«Impostazioni del modulo» non apriva la pagina, e il permesso della lista
«ereditava» le impostazioni e sembrava amministrazione (il Preposto non vedeva
il Diario preposto).

Qui ogni rotta passa al primo permesso delle impostazioni del modulo
(``core/permessi/impostazioni.py``). Per il sistema dei ruoli spento si copiano
ai ruoli storici le concessioni del permesso che il gate della view controllava
(o del vecchio permesso della rotta), cosi' nessuno perde l'accesso.
"""
from django.db import migrations

NOTA = "[CORE_0101] impostazioni con rotta propria"

# (rotta, permesso a cui legarla, permessi le cui concessioni storiche valgono anche qui, modulo ACL)
ROTTE = [
    ("diario_preposto:impostazioni", "diario_preposto.impostazioni.view",
     ("diario_preposto.impostazioni.manage",), "diario_preposto"),
    ("rilevazione_incidenti:impostazioni", "rilevazione_incidenti.impostazioni.view",
     ("rilevazione_incidenti.impostazioni.manage",), "rilevazione_incidenti"),
    ("tickets:impostazioni", "tickets.impostazioni.view", ("tickets.impostazioni.manage",), "tickets"),
    ("tickets:api_impostazioni", "tickets.impostazioni.view", ("tickets.impostazioni.manage",), "tickets"),
    ("dpi:impostazioni", "dpi.impostazioni.view", ("legacy.dpi.dpi_impostazioni",), "dpi"),
    ("timbri:configurazione", "timbri.configurazione.view", ("legacy.timbri.timbri_import",), "timbri"),
]



def avanti(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    RoleGrant = apps.get_model("core", "RolePermissionGrant")

    esistenti = set(Permission.objects.values_list("code", flat=True))
    for rotta, principale, fonti, modulo_acl in ROTTE:
        if principale not in esistenti:
            continue  # permesso mai creato su questo database: lo crea il bootstrap del modulo
        binding = Binding.objects.filter(route_name=rotta, path_pattern="").first()
        if binding is None:
            Binding.objects.create(
                route_name=rotta, path_pattern="", match_strategy="exact", permission_id=principale,
                source_app=modulo_acl, note=NOTA, priority=80, is_active=True,
            )
        elif binding.permission_id != principale or not binding.is_active:
            vecchio = binding.permission_id
            binding.permission_id = principale
            binding.is_active = True
            binding.note = ((binding.note or "") + f" {NOTA} (era {vecchio})").strip()[:255]
            binding.save(update_fields=["permission", "is_active", "note"])
        for g in RoleGrant.objects.filter(permission_id__in=[f for f in fonti if f in esistenti], enabled=True):
            RoleGrant.objects.get_or_create(
                legacy_role_id=g.legacy_role_id, permission_id=principale,
                defaults={"enabled": True, "note": NOTA},
            )


class Migration(migrations.Migration):
    dependencies = [("core", "0100_assets_it_fornitori_permessi")]
    operations = [migrations.RunPython(avanti, migrations.RunPython.noop)]
