"""«Le mie assenze» (/assenze/le-mie-richieste/) ha un permesso suo.

Stava sotto ``assenze.assenze.manage`` insieme a gestione amministrativa e
impostazioni: il permesso risultava «amministrazione» e il ruolo base, che sulle
assenze vede e crea le proprie, non lo riceveva mai (accessi negati in produzione).

- crea ``assenze.mie_richieste.view`` (lettura, vedi ``assenze/registro_permessi.py``);
- sposta lì il binding della rotta ``assenze_gestione``;
- copia le concessioni che c'erano sul vecchio permesso, così nessuno perde l'accesso
  prima di «Sincronizza i permessi delle pagine», che poi lo dà al ruolo base.
"""
from django.db import migrations

NUOVO = "assenze.mie_richieste.view"
VECCHIO = "assenze.assenze.manage"
ROTTA = "assenze_gestione"
NOTA = "[CORE_0094] da assenze.assenze.manage"


def avanti(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    GroupGrant = apps.get_model("core", "GroupPermissionGrant")
    UserGrant = apps.get_model("core", "UserPermissionGrant")
    binding = Binding.objects.filter(route_name=ROTTA, permission_id=VECCHIO).first()
    if binding is None:
        return
    Permission.objects.get_or_create(code=NUOVO, defaults={
        "label": "Assenze · le mie richieste", "module": "assenze",
        "description": "Pagina personale delle proprie richieste di assenza.", "is_active": True,
    })
    binding.permission_id = NUOVO
    binding.note = ((binding.note or "") + " " + NOTA).strip()[:255]
    binding.save(update_fields=["permission", "note"])
    for g in GroupGrant.objects.filter(permission_id=VECCHIO):
        GroupGrant.objects.get_or_create(group_id=g.group_id, permission_id=NUOVO,
                                         defaults={"enabled": g.enabled, "note": g.note})
    for u in UserGrant.objects.filter(permission_id=VECCHIO):
        UserGrant.objects.get_or_create(legacy_user_id=u.legacy_user_id, permission_id=NUOVO,
                                        defaults={"enabled": u.enabled, "note": u.note})


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Binding.objects.filter(route_name=ROTTA, permission_id=NUOVO).update(permission_id=VECCHIO)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0093_postazioni_pc_operatori"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
