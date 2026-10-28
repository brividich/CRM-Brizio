"""Ogni pagina «Impostazioni» con il permesso delle impostazioni del modulo.

Dopo 0097/0098/0101 restavano pagine di impostazioni aperte da «gestire» (o da
«vedere», o da nessuna azione):

- SOC: tutta la voce «Impostazioni» (Configurazione, Avvisi e automatismi, Battito,
  Letture, Soppressioni, Caselle mail, Inventario, Autoconfigurazione). Il modulo
  riceve l'azione «impostazioni»; la Panoramica /soc/admin/config/ passa al permesso
  nuovo ``security.impostazioni.manage`` (il vecchio ``security.config.view`` resta a
  «gestire»: le view lo usano anche per la gestione operativa);
- Anomalie: le API con cui la pagina Configurazione salva liste, notifiche, logo e
  modello del report;
- DPI: nuova, modifica ed elimina categoria;
- Anagrafica: Impostazioni della Skill Matrix e permessi dei widget statistici;
- Formazione: corsi online e regola FAD (sotto-pagine delle impostazioni e-learning);
- Checklist operativa: eventi e coda delle proposte, che si aprono solo dalla
  pagina Configurazione.

Come 0097: binding per nome rotta al primo permesso delle impostazioni del modulo,
concessioni storiche del vecchio permesso copiate (sistema dei ruoli spento), e per
il SOC copia di ogni cella «gestire» su «impostazioni» con i permessi accesi ai ruoli
gia' sincronizzati. Nessuno perde l'accesso: poi si mette «No» dove serve.
"""
from django.db import migrations

AZIONE = "impostazioni"
NOTA = "[CORE_0102] impostazioni: tutte le pagine"
NOTA_MATRICE = "matrice ruoli"

# (permesso a cui legare le rotte, etichetta se nuovo, modulo ACL, rotte)
ROTTE = [
    ("anomalie.configurazione.manage", "", "anomalie", (
        "api_anomalie_config_liste", "api_anomalie_notifiche", "api_anomalie_config_logo",
        "api_anomalie_config_logo_reset", "api_anomalie_config_report_template",
    )),
    ("dpi.impostazioni.view", "", "dpi", ("dpi:categoria_nuova", "dpi:categoria_modifica", "dpi:categoria_elimina")),
    ("anagrafica.impostazioni.manage", "", "anagrafica", ("anagrafica:skm_impostazioni", "anagrafica:widget_permissions")),
    ("formazione.impostazioni.manage", "", "anagrafica", (
        "anagrafica:elearning_impostazioni_corsi", "anagrafica:elearning_regola_corso",
    )),
    ("checklist_operativa.impostazioni.manage", "", "checklist_operativa", (
        "checklist_operativa:evento_nuovo", "checklist_operativa:evento_detail",
        "checklist_operativa:evento_chiudi", "checklist_operativa:evento_riapri",
        "checklist_operativa:voce_nuova", "checklist_operativa:voce_modifica",
        "checklist_operativa:proposte", "checklist_operativa:proposta_decidi",
    )),
    ("security.impostazioni.manage", "SOC · impostazioni e configurazione", "security", ("security:admin_config",)),
]

# Fotografia di core/permessi/impostazioni.py per il SOC (modulo nuovo nella tabella).
SOC_CODICI = (
    "security.impostazioni.manage",
    "security.soc_settings.view", "security.soc_settings.run",
    "security.watchguard_credenziali.view", "security.veeam_credenziali.view",
    "security.letture.view", "security.lettura_esegui.view", "security.battito.view",
    "security.config_general.view", "security.config_sources.view", "security.config_parsers.view",
    "security.config_alert.view", "security.config_suppressions.view", "security.config_backups.view",
    "security.config_notifications.view", "security.config_ticketing.view", "security.config_audit.view",
    "security.automation.view", "security.automation_simulate.view", "security.automation.manage",
    "security.inventory.view", "security.inventory_map.view", "security.inventory_discard.view",
    "security.software_mapping.view",
    "security.autoconfig.view", "security.autoconfig_apply.view", "security.autoconfig_fix.view",
    "security.diagnostics.view", "security.docs.view", "security.addons.view", "security.addon.view",
    "security.mailbox_sources.view", "security.mailbox_source.view",
    "security.pipeline.view", "security.pipeline.run",
    "security.suppressions.view", "security.suppression_revoke.view",
)


def avanti(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    GroupGrant = apps.get_model("core", "GroupPermissionGrant")
    RoleGrant = apps.get_model("core", "RolePermissionGrant")

    for principale, nuovo, modulo_acl, rotte in ROTTE:
        if nuovo:
            Permission.objects.get_or_create(code=principale, defaults={
                "label": nuovo, "module": modulo_acl, "is_active": True,
                "description": "Pagine di impostazioni del modulo: le apre l'azione «impostazioni» della matrice.",
            })
        if not Permission.objects.filter(code=principale).exists():
            continue  # permesso mai creato su questo database: lo crea il bootstrap del modulo
        for rotta in rotte:
            binding = Binding.objects.filter(route_name=rotta, path_pattern="").first()
            vecchio = binding.permission_id if binding else ""
            if binding is None:
                Binding.objects.create(
                    route_name=rotta, path_pattern="", match_strategy="exact", permission_id=principale,
                    source_app=modulo_acl, note=NOTA, priority=80, is_active=True,
                )
            elif vecchio != principale or not binding.is_active:
                binding.permission_id = principale
                binding.is_active = True
                binding.note = ((binding.note or "") + f" {NOTA} (era {vecchio})").strip()[:255]
                binding.save(update_fields=["permission", "is_active", "note"])
            if vecchio and vecchio != principale:
                for g in RoleGrant.objects.filter(permission_id=vecchio, enabled=True):
                    RoleGrant.objects.get_or_create(
                        legacy_role_id=g.legacy_role_id, permission_id=principale,
                        defaults={"enabled": True, "note": NOTA},
                    )

    # SOC: chi aveva «gestire» tiene le impostazioni (poi si toglie dove non servono).
    esistenti = set(Permission.objects.filter(code__in=SOC_CODICI).values_list("code", flat=True))
    gia = set(Cella.objects.filter(modulo="soc", azione=AZIONE).values_list("ruolo_id", flat=True))
    for cella in Cella.objects.filter(modulo="soc", azione="gestire").order_by("-consentito"):
        if cella.ruolo_id in gia:
            continue
        gia.add(cella.ruolo_id)
        Cella.objects.create(
            ruolo_id=cella.ruolo_id, modulo="soc", azione=AZIONE,
            ambito=cella.ambito, consentito=cella.consentito, note=NOTA,
        )
    sincronizzati = set(GroupGrant.objects.filter(note=NOTA_MATRICE).values_list("group_id", flat=True))
    consentiti = Cella.objects.filter(modulo="soc", azione=AZIONE, consentito=True, ruolo_id__in=sincronizzati)
    for ruolo_id in consentiti.values_list("ruolo_id", flat=True):
        for code in esistenti:
            GroupGrant.objects.get_or_create(
                group_id=ruolo_id, permission_id=code, defaults={"enabled": True, "note": NOTA_MATRICE},
            )


class Migration(migrations.Migration):
    dependencies = [("core", "0101_impostazioni_rotte_proprie")]
    operations = [migrations.RunPython(avanti, migrations.RunPython.noop)]
