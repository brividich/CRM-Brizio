"""Impostazioni dei moduli: azione propria nella matrice dei ruoli (come le assenze in 0096).

Per ogni modulo di ``core/permessi/impostazioni.py`` (fotografia qui sotto):

- crea il permesso delle impostazioni se e' nuovo;
- lega le rotte delle impostazioni al permesso (binding per nome rotta), dove
  oggi condividono il permesso con pagine che non sono impostazioni;
- per il sistema dei ruoli spento: copia ai ruoli storici le concessioni del
  vecchio permesso della rotta, cosi' nessuno perde l'accesso;
- copia ogni cella «gestire» del modulo su «impostazioni» e accende i permessi
  delle impostazioni ai ruoli che ce l'hanno, come farebbe «Salva matrice».

Nessuno perde l'accesso: poi si mette «No» sulle impostazioni dei ruoli che non
devono vederle.
"""
from django.db import migrations

AZIONE = "impostazioni"
NOTA = "[CORE_0097] impostazioni con azione propria"
NOTA_MATRICE = "matrice ruoli"

# (modulo della matrice, permessi delle impostazioni, rotte legate al primo, etichetta se nuovo, modulo ACL)
MODULI = [('anomalie', ('anomalie.configurazione.manage',), ('anomalie_configurazione_page',), '', 'anomalie'),
 ('ticket_manutenzione',
  ('tickets.impostazioni.view', 'tickets.impostazioni.manage'),
  (),
  '',
  'ticket_manutenzione'),
 ('diario_preposto',
  ('diario_preposto.impostazioni.view', 'diario_preposto.impostazioni.manage'),
  (),
  '',
  'diario_preposto'),
 ('rilevazione_incidenti',
  ('rilevazione_incidenti.impostazioni.view', 'rilevazione_incidenti.impostazioni.manage'),
  (),
  '',
  'rilevazione_incidenti'),
 ('automazioni', ('automazioni.automazioni_settings.view',), (), '', 'automazioni'),
 ('timbri', ('timbri.configurazione.view',), (), '', 'timbri'),
 ('dpi',
  ('dpi.impostazioni.view',
   'dpi.categoria_nuova.view',
   'dpi.categoria_modifica.view',
   'dpi.categoria_elimina.view'),
  ('dpi:tipo_nuovo',
   'dpi:tipo_modifica',
   'dpi:modello_nuovo',
   'dpi:modello_modifica',
   'dpi:taglia_nuova',
   'dpi:taglia_modifica'),
  '',
  'dpi'),
 ('assets',
  ('assets.gestione_admin.view',),
  ('assets:reporting_settings',
   'assets:reporting_edit',
   'assets:reporting_run',
   'assets:reporting_retry',
   'assets:maintenance_impostazioni'),
  '',
  'assets'),
 ('kickoff',
  ('tasks.impostazioni.manage',),
  ('tasks:impostazioni', 'tasks:impostazioni_kickoff_delete', 'tasks:impostazioni_task_delete'),
  'Kickoff · impostazioni',
  'tasks'),
 ('rentri', ('rentri.impostazioni.manage',), ('rentri_impostazioni',), 'RENTRI · impostazioni', 'rentri'),
 ('carichi_macchina',
  ('gestione_carichi_macchina.impostazioni.manage',),
  ('gestione_carichi_macchina:impostazioni',),
  'Carichi macchina · impostazioni macchine',
  'gestione_carichi_macchina'),
 ('notizie',
  ('notizie.impostazioni.manage',),
  ('notizie_gestione_admin',),
  'Notizie · impostazioni e gestione interna',
  'notizie'),
 ('anagrafica',
  ('anagrafica.impostazioni.manage', 'anagrafica.widget_permissions.view'),
  ('anagrafica:impostazioni',
   'anagrafica:impostazioni_permessi_save',
   'anagrafica:impostazioni_acl_role_grants_save',
   'anagrafica:impostazioni_acl_user_override_save',
   'anagrafica:avviso_it_save',
   'anagrafica:workflow_campo_create',
   'anagrafica:workflow_campo_update',
   'anagrafica:workflow_campo_delete',
   'anagrafica:retention',
   'anagrafica:rettifiche',
   'anagrafica:viste_elenco',
   'anagrafica:vista_elenco_nuova',
   'anagrafica:vista_elenco_modifica',
   'anagrafica:vista_elenco_azione',
   'anagrafica:vista_elenco_anteprima',
   'anagrafica:skm_impostazioni',
   'anagrafica:sicurezza_operativa_config'),
  'Anagrafica · impostazioni e cataloghi',
  'anagrafica'),
 ('formazione',
  ('formazione.impostazioni.manage',),
  ('anagrafica:attestato_impostazioni',
   'anagrafica:formazione_elearning_settings',
   'anagrafica:elearning_impostazioni_corsi',
   'anagrafica:formazione_scansioni_impostazioni'),
  'Formazione · impostazioni (attestati, e-learning, scansioni)',
  'anagrafica'),
 ('visite_mediche',
  ('visite_mediche.impostazioni.manage',),
  ('anagrafica:referti_impostazioni',),
  'Visite mediche · impostazioni referti',
  'anagrafica'),
 ('schede_sicurezza',
  ('schede_sicurezza.impostazioni.manage',),
  ('schede_sicurezza:etichetta_impostazioni',),
  'Schede di sicurezza · impostazioni etichetta',
  'schede_sicurezza'),
 ('sistema_gestione',
  ('sistema_gestione.impostazioni.manage',),
  ('sistema_gestione:audit_impostazioni',),
  'Sistema di gestione · impostazioni audit',
  'sistema_gestione'),
 ('contatori',
  ('contatori.impostazioni.manage',),
  ('contatori:impostazioni',),
  'Contatori · impostazioni',
  'contatori'),
 ('checklist_operativa',
  ('checklist_operativa.impostazioni.manage',),
  ('checklist_operativa:configurazione',
   'checklist_operativa:task_nuovo',
   'checklist_operativa:task_modifica',
   'checklist_operativa:task_toggle'),
  'Checklist operativa · configurazione dei task',
  'checklist_operativa')]

# La pagina impostazioni dei ticket serve IT e manutenzione: conta «gestire» di entrambi.
FONTI_GESTIRE = {"ticket_manutenzione": ("ticket_manutenzione", "ticket_it")}


def avanti(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    GroupGrant = apps.get_model("core", "GroupPermissionGrant")
    RoleGrant = apps.get_model("core", "RolePermissionGrant")

    for chiave, codici, rotte, nuovo, modulo_acl in MODULI:
        principale = codici[0]
        if nuovo:
            Permission.objects.get_or_create(code=principale, defaults={
                "label": nuovo, "module": modulo_acl, "is_active": True,
                "description": "Pagine di impostazioni del modulo: le apre l'azione «impostazioni» della matrice.",
            })
        esistenti = set(Permission.objects.filter(code__in=codici).values_list("code", flat=True))
        if principale not in esistenti:
            continue  # permesso mai creato su questo database: lo crea il bootstrap del modulo
        for rotta in rotte:
            binding = Binding.objects.filter(route_name=rotta, path_pattern="").first()
            vecchio = binding.permission_id if binding else ""
            if binding is None:
                Binding.objects.create(
                    route_name=rotta, path_pattern="", match_strategy="exact", permission_id=principale,
                    source_app=modulo_acl, note=NOTA, priority=80, is_active=True,
                )
            elif vecchio != principale:
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

        gia = set(Cella.objects.filter(modulo=chiave, azione=AZIONE).values_list("ruolo_id", flat=True))
        fonti = FONTI_GESTIRE.get(chiave, (chiave,))
        for cella in Cella.objects.filter(modulo__in=fonti, azione="gestire").order_by("-consentito"):
            if cella.ruolo_id in gia:
                continue
            gia.add(cella.ruolo_id)
            Cella.objects.create(
                ruolo_id=cella.ruolo_id, modulo=chiave, azione=AZIONE,
                ambito=cella.ambito, consentito=cella.consentito, note=NOTA,
            )
        # Solo i ruoli gia' sincronizzati dalla matrice (hanno grant «matrice ruoli»):
        # gli altri li accende il primo «Salva matrice» / «Sincronizza».
        sincronizzati = set(GroupGrant.objects.filter(note=NOTA_MATRICE).values_list("group_id", flat=True))
        consentiti = Cella.objects.filter(modulo=chiave, azione=AZIONE, consentito=True, ruolo_id__in=sincronizzati)
        for ruolo_id in consentiti.values_list("ruolo_id", flat=True):
            for code in esistenti:
                GroupGrant.objects.get_or_create(
                    group_id=ruolo_id, permission_id=code, defaults={"enabled": True, "note": NOTA_MATRICE},
                )


class Migration(migrations.Migration):
    dependencies = [("core", "0096_assenze_azione_impostazioni")]
    operations = [migrations.RunPython(avanti, migrations.RunPython.noop)]
