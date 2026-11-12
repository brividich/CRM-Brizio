"""Pannello Reception assegnabile da «Ruoli e permessi» con azioni distinte.

Prima tutte le pagine stavano sotto ``legacy.portale_esterno.portale_esterno`` (classificato
amministrazione: lo accendeva solo «Chiudere / gestire») e il modulo si chiamava «Portale ospiti
(Wi-Fi)». Ora (modulo ``portale_ospiti``, «Reception e visitatori», core/registro_permessi.py):

- ``legacy.portale_esterno.portale_esterno`` resta alle pagine di consultazione, «Vedere»;
- ``reception.pannello.manage`` (nuovo): registrare e gestire, «Creare / Modificare / Cancellare»;
- ``reception.impostazioni.manage`` (nuovo): Reception → Impostazioni, azione «Impostazioni».

Si spostano solo i binding creati da reception 0002/0004 e ancora sul permesso di partenza
(personalizzazioni a mano preservate). Nessuno perde l'accesso: le concessioni del permesso di
partenza si copiano sui nuovi, e i ruoli con la cella «gestire» ricevono anche le celle nuove,
così «Sincronizza i permessi delle pagine» non toglie niente.
"""
from django.db import migrations

PARTENZA = "legacy.portale_esterno.portale_esterno"
GESTIONE = "reception.pannello.manage"
IMPOSTAZIONI = "reception.impostazioni.manage"
NUOVI = {
    GESTIONE: ("Reception · registrare e gestire",
               "Ingressi e uscite a mano, pre-registrazioni, richieste di appuntamento, referenti, ditte, cartellini."),
    IMPOSTAZIONI: ("Reception · impostazioni", "Avviso al chiosco e cancellazione dei dati oltre il termine."),
}
ROTTE = {
    "reception:registra": GESTIONE,
    "reception:visita_uscita": GESTIONE,
    "reception:preregistrazioni": GESTIONE,
    "reception:preregistrazione_azione": GESTIONE,
    "reception:referenti": GESTIONE,
    "reception:ditte": GESTIONE,
    "reception:cartellini": GESTIONE,
    "reception:richiesta_azione": GESTIONE,
    "reception:impostazioni": IMPOSTAZIONI,
}
MODULO = "portale_ospiti"
CELLE_DA_GESTIRE = ("vedere", "creare", "modificare", "cancellare", "impostazioni")
NOTA = "[RECEPTION_0006]"


def avanti(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    GroupGrant = apps.get_model("core", "GroupPermissionGrant")
    UserGrant = apps.get_model("core", "UserPermissionGrant")
    RoleGrant = apps.get_model("core", "RolePermissionGrant")
    Cella = apps.get_model("core", "RuoloPermessoModulo")

    for code, (label, descrizione) in NUOVI.items():
        Permission.objects.get_or_create(code=code, defaults={
            "label": label, "module": "portale_esterno", "description": descrizione, "is_active": True,
        })
    for rotta, code in ROTTE.items():
        for b in Binding.objects.filter(route_name=rotta, permission_id=PARTENZA, note__startswith="[RECEPTION_"):
            b.permission_id = code
            b.note = f"{b.note} {NOTA} da {PARTENZA}"[:255]
            b.save(update_fields=["permission", "note"])
    if not Permission.objects.filter(code=PARTENZA).exists():
        return
    for code in NUOVI:
        for g in GroupGrant.objects.filter(permission_id=PARTENZA):
            GroupGrant.objects.get_or_create(group_id=g.group_id, permission_id=code, defaults={"enabled": g.enabled, "note": NOTA})
        for u in UserGrant.objects.filter(permission_id=PARTENZA):
            UserGrant.objects.get_or_create(legacy_user_id=u.legacy_user_id, permission_id=code, defaults={"enabled": u.enabled, "note": NOTA})
        for r in RoleGrant.objects.filter(permission_id=PARTENZA):
            RoleGrant.objects.get_or_create(legacy_role_id=r.legacy_role_id, permission_id=code, defaults={"enabled": r.enabled, "note": NOTA})
    for cella in Cella.objects.filter(modulo=MODULO, azione="gestire", consentito=True):
        for azione in CELLE_DA_GESTIRE:
            Cella.objects.get_or_create(ruolo_id=cella.ruolo_id, modulo=MODULO, azione=azione,
                                        defaults={"ambito": cella.ambito, "consentito": True, "note": NOTA})


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for b in Binding.objects.filter(note__contains=NOTA):
        b.permission_id = PARTENZA
        b.note = b.note.replace(f" {NOTA} da {PARTENZA}", "")
        b.save(update_fields=["permission", "note"])
    apps.get_model("core", "RuoloPermessoModulo").objects.filter(note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [("reception", "0005_referente_da_anagrafica")]
    operations = [migrations.RunPython(avanti, indietro)]
