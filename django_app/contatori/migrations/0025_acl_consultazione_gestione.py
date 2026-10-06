"""ACL v2 del modulo Contatori: consultazione e gestione separate.

- `contatori.modulo.view`: consultazione (Centrale, analisi, riconciliazione,
  monitor, schede). `contatori.gestione.manage`: ogni scrittura, verificata anche
  dentro le view (`contatori/permessi.py`).
- Binding per route **solo se mancanti** (con ACL_STRICT_CANONICAL una route senza
  binding e' negata ai non superuser): le route gia' mappate non si toccano.
- Grant iniziali che non tolgono accesso a nessuno: view a chi vede gia' la
  Centrale (`contatori.dashboard.view`), gestione a chi poteva gia' modificare le
  MFC (`contatori.macchina.edit`). Ruoli, utenti e gruppi; create-only.
"""
from django.db import migrations

VIEW = "contatori.modulo.view"
GESTIONE = "contatori.gestione.manage"

PERMESSI = {
    VIEW: ("Contatori - Consultazione",
           "Centrale, stampanti MFC, riconciliazione, analisi, consumabili e monitor SNMP in sola lettura."),
    GESTIONE: ("Contatori - Gestione",
               "Letture, fatture, lettura SNMP massiva, anagrafica MFC/dispositivi/sonde/profili, "
               "discovery e configurazione SNMP globale."),
}

ROUTE_VIEW = [
    "dashboard", "riconciliazione", "riconciliazione_trim", "macchina", "macchine",
    "macchina_test_snmp", "snmp_centrale", "snmp_interroga_tutti", "snmp_profili",
    "snmp_dispositivo", "snmp_dispositivo_interroga", "macchina_consumabili", "consumabili",
    "consumabili_riepilogo", "consumabili_aggiorna", "analisi", "export_analisi", "export_riconciliazione",
]
ROUTE_GESTIONE = [
    "importa_lettura", "letture_proposte", "lettura_edit", "lettura_elimina", "fattura_nuova", "fattura_edit",
    "fattura_elimina", "leggi_snmp", "macchina_nuova", "macchina_edit", "discovery",
    "discovery_applica_ip", "snmp_profilo_nuovo", "snmp_profilo_edit",
    "snmp_profilo_colonna_nuova", "snmp_profilo_colonna_edit", "snmp_dispositivo_nuovo",
    "snmp_dispositivo_edit", "snmp_dispositivo_applica_profilo", "snmp_sonda_nuova",
    "snmp_sonda_edit",
]
# Codice da cui ereditare chi deve ricevere il nuovo permesso.
SORGENTI = {VIEW: "contatori.dashboard.view", GESTIONE: "contatori.macchina.edit"}
NOTA = "[CONTATORI_0025] ereditato da {}"


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    GrantRuolo = apps.get_model("core", "RolePermissionGrant")
    GrantUtente = apps.get_model("core", "UserPermissionGrant")
    GrantGruppo = apps.get_model("core", "GroupPermissionGrant")

    for code, (label, descr) in PERMESSI.items():
        Permesso.objects.get_or_create(code=code, defaults={
            "module": "contatori", "label": label, "description": descr, "is_active": True})

    # Un binding a prefisso su /contatori/ copre gia' tutto il modulo: un exact per
    # route lo scavalcherebbe cambiando chi accede, quindi in quel caso non si crea nulla.
    coperto = Binding.objects.filter(is_active=True, match_strategy="prefix",
                                     path_pattern__in=["/contatori/", "/contatori"]).exists()
    for codici, code in (() if coperto else ((ROUTE_VIEW, VIEW), (ROUTE_GESTIONE, GESTIONE))):
        for nome in codici:
            route = f"contatori:{nome}"
            # Anche un binding disattivato a mano va rispettato (e vale l'unicita' route+path).
            if Binding.objects.filter(route_name=route).exists():
                continue
            Binding.objects.create(route_name=route, path_pattern="", match_strategy="exact",
                                   permission_id=code, source_app="contatori", priority=80,
                                   is_active=True, note="[CONTATORI_0025] binding consultazione/gestione")

    for code, sorgente in SORGENTI.items():
        nota = NOTA.format(sorgente)
        for g in GrantRuolo.objects.filter(permission_id=sorgente, enabled=True):
            GrantRuolo.objects.get_or_create(legacy_role_id=g.legacy_role_id, permission_id=code,
                                             defaults={"enabled": True, "note": nota})
        for g in GrantUtente.objects.filter(permission_id=sorgente, enabled=True):
            GrantUtente.objects.get_or_create(legacy_user_id=g.legacy_user_id, permission_id=code,
                                              defaults={"enabled": True, "note": nota})
        for g in GrantGruppo.objects.filter(permission_id=sorgente, enabled=True):
            GrantGruppo.objects.get_or_create(group_id=g.group_id, permission_id=code,
                                              defaults={"enabled": True, "note": nota})


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Binding.objects.filter(note="[CONTATORI_0025] binding consultazione/gestione").delete()
    # Permessi e grant restano: eliminarli toglierebbe accessi concessi a mano dopo il deploy.


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0024_snmp_v3_versione"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
