# HANDOFF — Implementazione flussi automazioni

> **Per il prossimo Claude / collega che riprende il lavoro.**
> Questo file è il passaggio di consegne. Leggilo tutto prima di continuare.
> Aggiornalo a ogni avanzamento (è la fonte di verità dello stato di avanzamento).

Ultimo aggiornamento: **2026-05-29** (batch 5: AU-GAP1 completato + trigger anomalie + AU42b per ruolo; 27 pacchetti + 4 command + trigger) · Branch: `main`

---

## Contesto

L'utente (italiano — rispondere SEMPRE in italiano) ha chiesto di implementare i flussi
automazioni descritti nel backlog [docs/ai/11_FEATURE_BACKLOG.md](../../../docs/ai/11_FEATURE_BACKLOG.md)
(sezioni `AU1`–`AU52` + `AU-GAP1`), "mano a mano tutti", partendo dai più sicuri.

L'utente si assenta: lavoro in **autonomia**. Allowlist permessi già configurata in
`.claude/settings.local.json` (allow: comandi Django sicuri + git non distruttivo + Edit/Write;
deny: rm -rf, git reset --hard, push --force, manage.py flush/reset_db/dbshell, DROP; ask: git push, WebFetch).

## Decisioni architetturali prese (NON ridiscutere)

1. **Modo di creazione regole** = **package `.automation_package.json`** (NON data migration, NON solo doc).
   Il pattern canonico è l'import via `package_importer.py`. I pacchetti vivono in questa cartella
   (`django_app/automazioni/packages/`).
2. **Ambiente** = **solo dev / SQLite** (`config.settings.dev`). NON toccare SQL Server test/prod.
   NON lanciare migrate su DB reali.
3. **Canale approvazioni** = **Email** (no Teams per ora; Telegram solo ipotesi futura).
4. **Le regole importate nascono SEMPRE draft + disattive** (forzato da package_importer righe ~1410-1414):
   l'utente le attiverà a mano dal designer. Quindi importare è sicuro, non parte nulla da solo.

## Schema del formato pacchetto (verificato da package_importer.py + tests.py)

Top-level: `package_version`, `input.flow_name`, `source_candidate.{source_code,label}`,
`compatibility.{compatible,status}`, `issues`, `target_context`, `approved_field_mapping` (opzionale),
e `proposed_rules` (alias accettato: `rules`).

Ogni rule: `code`, `name`, `description`, `source_code`, `operation_type` (insert|update),
`trigger_scope` (all_inserts|all_updates|specific_field|any_change), `watched_field` (solo se specific_field),
`is_active:false`, `is_draft:true`, `conditions[]`, `actions[]`.

Condition: `{field, operator, value, value_type}` (operatori in `AutomationConditionOperator`).
Action send_email: `{action_type:"send_email", to, from_email, subject_template, body_text_template, body_html_template}`.
Placeholder nei template: `{nome_campo}` risolti dal payload (vedi source_registry per i campi disponibili).

Vincoli importanti:
- `operation_type=insert` ⇒ `trigger_scope` DEVE essere `all_inserts` (vedi models.py clean()).
- `specific_field` richiede `watched_field`; gli altri scope NON devono averlo.
- I campi devono esistere nel `source_registry.py` per la sorgente scelta (o sono alias noti).

## ⚠️ Prerequisito tecnico per far SCATTARE le regole (non solo importarle)

Una regola scatta solo se un **trigger SQL** sulla tabella sorgente popola `automation_event_queue`,
e se `process_automation_queue` (management command) gira. In dev/SQLite questo va verificato:
vedi `management/commands/apply_sql_triggers.py` e `process_automation_queue.py`.
Per il TEST in dev di solito si usa il **dry-run** dell'import (azione `dry_run`) con un payload JSON
di esempio — NON serve il trigger reale. Vedi `tests.py::_run_dry_run`.

## ✅ LIMITI RISOLTI (estensione motore — 2026-05-29)

I 4 limiti architetturali scoperti sono stati affrontati. Modifiche a `models.py`, `services.py`,
`package_importer.py`, `source_registry.py` + migrazione `0015_alter_automationcondition_operator`.
`manage.py check` OK; regressione su tutti i pacchetti OK; test profondita' OK.

1. **`send_approval` annidate — ABILITATE (catena, max 3 totali).** `_validate_embedded_action_list`
   ora valida ricorsivamente i rami con un `depth` e blocca oltre `MAX_APPROVAL_CHAIN_DEPTH=3`
   (radice + 2 annidate). Il runtime gia' le supportava (`process_approval_decision` → `_execute_inline_action`).
   ⇒ **AU13** (caporeparto→HR) e **AU3** (RLS→RSPP) ora sono a doppia firma reale. Aggiornati e validati.

2. **`insert_record` ticket — NON modificato per scelta utente.** Resta consentito solo su `core_notifica`.
   Motivo: l'insert usa SQL raw e bypassa `Ticket.save()` che genera `numero_ticket` (unique) → un insert
   raw violerebbe il vincolo. Decisione utente: i flussi "crea ticket" restano **notifiche** (email/core_notifica).
   Per ticket automatici reali servirebbe un nuovo action_type `create_ticket` via ORM — non fatto.

3. **Operatori su date/durate — AGGIUNTI.** Nuovi operatori in `AutomationConditionOperator`:
   - `days_from_now_lte` / `days_from_now_gte`: confronta (campo_data − oggi) in giorni con un intero.
     Es. scadenza entro 60gg ⇒ `days_from_now_lte` con expected `60`. Usato in **AU12**.
   - `days_span_gt` / `days_span_gte`: confronta (campo_data − altro_campo) in giorni; expected nel
     formato `"altro_campo:N"` (es. `data_inizio:10` ⇒ (data_fine − data_inizio) > 10). Usato in **AU13**.
   Testati in dev. ⇒ "ferie > 10 giorni" ora esprimibile.

4. **`for_each`/`branch`/`do_until` — VALIDAZIONE AGGIUNTA** in `_validate_action_structure`:
   for_each verifica `source_code`/`filter_field` sul registry e valida `loop_actions`; branch valida
   `then_actions`/`else_actions` e segnala `run_if` mancante; do_until richiede `check_field`. I rami
   embedded sono validati ricorsivamente. NB: il dry-run completo di questi flussi resta meglio nel designer.

## ✅ FIX CONTROLLO-FLUSSO (batch 2 — 2026-05-29)

Implementando i for_each sono emerse **3 divergenze** che facevano passare la validazione ma rendevano
il flusso inerte (o sbagliato) a runtime. Corrette in `package_importer.py` + `services.py`, provate
end-to-end in dev con backend email `locmem`. `manage.py check` OK.

1. **Validazione placeholder cross-source** (`_validate_action_structure`, package_importer): il check
   top-level dei placeholder per i container (`for_each`/`branch`/`do_until`/`send_approval`) ora **esclude**
   i placeholder dentro le liste figlie (`loop_actions`/`actions`/`approved_actions`/`rejected_actions`/
   `then_actions`/`else_actions`). Quelli sono validati ricorsivamente con la sorgente giusta — per for_each
   la sorgente **iterata**. Prima un for_each cross-source (es. offboarding→dpi) era sempre bocciato perché
   i campi del corpo loop (`{numero}`,`{categoria_id}`) appartengono alla sorgente iterata, non alla regola.

2. **Runtime `for_each`** (`execute_action`, services): le azioni loop sono accettate anche come
   `loop_actions`/`actions` (schema pacchetti), non solo `each_actions`; aggiunto `max_iterations` alias di
   `max_items`. Senza questo, un pacchetto valido girava con loop **vuoto** (0 azioni eseguite).

3. **Runtime `branch`** (`execute_action`, services): accetta lo schema dei pacchetti
   `run_if`+`then_actions`/`else_actions` oltre allo storico `condition_*`+`if_true/false_actions`.

4. **Azioni inline** (`_execute_inline_action`, services): se l'azione embedded ha i parametri come chiavi
   top-level (schema pacchetti: `{"action_type":"send_email","to":...}`) invece che sotto `config_json`,
   le chiavi non-meta vengono **promosse** a config. Prima l'azione inline girava con config vuota → email
   senza destinatario/corpo.

**Prove runtime** (dev, locmem): for_each cross-source = 2 record → 2 email coi placeholder iterati risolti;
for_each+branch run_if `is_false` = 3 record → solo i 2 inadempienti notificati; gate escalation run_if
`is_empty` = azione eseguita se campo vuoto, **saltata** se valorizzato.

## ✅ PRIMITIVA `count_branch` + ESCALATION + DIGEST (batch 4 — 2026-05-29)

**Nuovo action_type `count_branch`** (models.py enum + migrazione `0016`): conta i record di una
sorgente registrata filtrando per `filter_field`/`filter_value_template` e, opzionalmente, su una
finestra temporale (`window_field >= oggi - window_days`), poi confronta il totale con `threshold`
tramite `operator` (gte/gt/lte/lt/eq) ed esegue `then_actions`/`else_actions`. Implementazione:
`_count_source` in services (SQL `COUNT(*)` parametrizzato; table_name/filter_field/window_field
validati contro il registry; MSSQL/SQLite); ramo runtime in `execute_action`; validazione import
dedicata in `_validate_action_structure`. ⇒ sblocca le soglie "N eventi in M giorni" che il `for_each`
NON sapeva esprimere (non espone un conteggio aggregato a valle).
Schema azione (parametri sotto `config_json`): `{source_code, filter_field, filter_value_template,
window_field, window_days, threshold, operator, then_actions[], else_actions[]}`.
NB: then/else_actions girano sul payload del record TRIGGER, non sui record contati.
Provato a runtime: count=3 (≥3) → ramo then (1 email); count=2 (<3) → ramo else (0 email).

**Pacchetti count_branch**: AU36 (≥3 DPI/richiedente in 30gg), AU37 (UPGRADE: ≥3 ticket/asset in 90gg
→ send_approval annidata), AU38 (≥3 incidenti/reparto in 60gg → alert RSPP).
**Pacchetti escalation**: AU49 (assenza non evasa: send_approval + delay 24h + reinoltro HR),
AU50 (incidente Accident non chiuso: 24h/72h/7gg con run_if `chiusura_rspp is_false`).

**Scaffold management command (job schedulati Windows — NON regole designer)**: i digest vanno
implementati come command + Task Scheduler (pattern `send_dpi_expiry_reminders`/`send_sla_reminders`),
NON come pacchetti. Creati 4 scaffold, tutti scoperti da Django e ok in `--dry-run`:
- `anagrafica/.../send_visite_mediche_digest.py` (AU45) — query reale VisitaMedica.
- `anagrafica/.../send_formazione_audit_digest.py` (AU47) — query reale TrainingEmployeeRecord; TODO P2 % per reparto.
- `tickets/.../send_ticket_daily_digest.py` (AU52) — ticket assegnati in scadenza, raggruppati per assegnato_email.
- `core/.../send_caporeparto_morning_digest.py` (AU51) — scaffold cross-modulo; TODO aggregazione per-capo.
Tutti usano `core.email_utils.send_hub_mail(subject, body, recipients, email_type=..., section_label=..., fail_silently=...)`.

## ✅ AU-GAP1 COMPLETATO + TRIGGER ANOMALIE (batch 5 — 2026-05-29)

Il prerequisito AU-GAP1 (esporre "chi/ruolo modifica" nel payload anomalie) è stato chiuso a livello
motore/app/trigger. Catena completa:

1. **Trigger SQL** `automazioni/migrations/trg_anomalie_automation.sql` (AFTER INSERT/UPDATE su `dbo.anomalie`):
   insert → proietta il record; update → proietta `i.*` + `old_avanzamento`/`old_chiudere` e accoda SOLO se
   cambia `avanzamento` o `chiudere`. Guard se la queue non esiste. **Auto-applicato** da
   `python manage.py apply_sql_triggers` (lo scopre tra i `trg_*.sql`; idempotente; skip se tabella assente).
   NON referenzia esplicitamente `modified_by_user_id` (per non invalidare il trigger su schemi che non hanno
   la colonna): la espone tramite `i.*` se presente.
2. **App**: `anomalie/views.py` (salvataggio anomalia) popola `modified_by_user_id` su insert+update SE la
   colonna esiste (`if "modified_by_user_id" in cols`), col legacy_user.id — stesso pattern di created_by_user_id.
3. **Runtime**: `_enrich_anomalie_payload` (services) deriva `modified_by_role` (CC/CAR) da
   `modified_by_id`/`modified_by_user_id`, risolvendo `Profile.legacy_user_id` → `AnomalieRoleAssignment`
   (CC>CAR). Registrato nel dispatcher `_enrich_payload_for_source`.
4. **Registry**: campi virtuali `old_avanzamento`/`old_chiudere` + alias `modified_by_user_id` su `modified_by_id`.
5. **Pacchetto** `au42_anomalia_avanzamento_per_ruolo` (AU42b): condizione `modified_by_role in_csv "CC,CAR"`.

Testato in dev (transazione + rollback): utente con ruolo CC → `modified_by_role=CC`; senza ruolo → None.

⚠️ **PREREQUISITO DDL PROD**: per far funzionare AU42b in produzione, la tabella legacy `anomalie` deve avere
la colonna **`modified_by_user_id`** (INT NULL). Senza, il codice resta inerte (difensivo) e vale AU42 "per campo".
Aggiungere la colonna con una migration SQL legacy o uno script DDL, poi rilanciare `apply_sql_triggers`.

⚠️ **Promemoria generale**: i pacchetti si IMPORTANO ma scattano solo se il trigger SQL della sorgente
alimenta `automation_event_queue` E gira `process_automation_queue`. Per anomalie ora il trigger c'è; per le
altre sorgenti verificare i rispettivi `trg_*.sql` (esistono per tickets/tasks/assenze).

## ✅ FIX run_if AZIONE (batch 3 — 2026-05-29)

`_resolve_action_run_if` (services) ora accetta il valore atteso del `run_if` di azione sia come
`expected_value` (schema storico) sia come `value` (schema usato dalle condition dei pacchetti e dal
run_if di branch). Prima un `run_if` con `value` (es. AU35 `equals IN_CORSO`) confrontava una stringa
vuota → azione **sempre saltata**. Provato a runtime: `equals IN_CORSO` con `value` esegue su IN_CORSO,
salta su CHIUSA. **Promemoria per i pacchetti**: nel `run_if` di azione usa pure `value` (uniforme con le
condition); gli operatori senza valore (`is_true`/`is_false`/`is_empty`/`is_not_empty`) non lo richiedono.

### AU-GAP1 — campi esposti (resta da popolare lato DB)
Aggiunti a `source_registry` (sorgente `anomalie`) i campi virtuali `modified_by_id` e `modified_by_role`.
Sono `is_virtual`: il **trigger SQL / codice che alimenta `automation_event_queue` deve popolarli** perche'
AU42 "per ruolo" funzioni davvero. Finche' non popolati, AU42 resta nella versione "per campo".

## AU-GAP1 (prerequisito per AU42 "per ruolo")

Il payload `anomalie` NON espone "chi ha modificato" (solo `created_by` = autore).
Per la notifica "solo quando CAPOCOMMESSA/CAR modificano" serve aggiungere un campo
`modified_by_id`/`modified_by_role` a `source_registry.py` (sorgente `anomalie`) E popolarlo dal
trigger SQL. NOTA: è appena arrivata in `main` la feature "fonte ruoli CR/Capocommessa configurabile"
(`tasks.TaskImpostazioni.roles_source`, ruolo `CR`) — utile per risolvere il ruolo.
Finché AU-GAP1 non è fatto, AU42 si implementa nella versione "notifica al cambio del campo `avanzamento`".

## STATO DI AVANZAMENTO (todo persistente — aggiornare qui)

- [x] **Setup**: allowlist permessi configurata; schema pacchetto studiato; cartella packages/ creata.
- [x] **AU41** — anomalia creata → notifica email. Pacchetto: `au41_anomalia_creata_notifica.automation_package.json`.
      Validato in dev (analyze_package_dict: importable 1/1, 0 errori) + dry-run render template OK.
- [x] **AU42** — avanzamento anomalia cambiato → notifica (versione "per campo", operator `changed` su `avanzamento`).
      Pacchetto: `au42_anomalia_avanzamento_cambiato_notifica.automation_package.json`. Validato (1/1, 0 errori).
      Versione "per ruolo" dipende da AU-GAP1.
- [x] **AU43** — anomalia chiusa (`chiudere` changed_to true) → conferma. Pacchetto:
      `au43_anomalia_chiusa_conferma_autore.automation_package.json`. Validato (1/1, 0 errori).
- [x] **AU13** — ferie >10gg → **doppia firma cascata** caporeparto→HR (LIMITE 1 risolto; durata via `days_span_gt`).
      Pacchetto `au13_ferie_lunghe_doppia_approvazione.automation_package.json`. Validato (1/1, 0 errori).
- [x] **AU14** — DPI INVIATA → approvazione caporeparto, poi notifica magazzino.
      Pacchetto `au14_dpi_approvazione_caporeparto_magazzino.automation_package.json`. Validato (1/1, 0 errori).
      Limite residuo: "solo se richiedente non capo/preposto" non esprimibile (ruolo non nel payload dpi).
- [x] **AU6** — offboarding aperto → 3 notifiche email (IT/magazzino/HR). Senza ticket/for_each (vedi LIMITE 2).
      Pacchetto `au6_offboarding_checklist_notifiche.automation_package.json`. Validato (1/1, 0 errori).
- [x] **AU3** — incidente → **doppia firma cascata** RLS→RSPP/ASPP, poi notifica direzione (LIMITE 1 risolto).
      Pacchetto `au3_incidente_approvazione_rls_rspp.automation_package.json`. Validato (1/1, 0 errori).
- [x] **AU8** — guasto ricorrente → `update_trigger_record` priorita'=CRITICA + nota ricorrenza.
      Pacchetto `au8_guasto_ricorrente_arricchimento.automation_package.json`. Validato (1/1, 0 errori).
- [x] **AU10** — notizia obbligatoria pubblicata → broadcast email.
      Pacchetto `au10_notizia_obbligatoria_broadcast.automation_package.json`. Validato (1/1, 0 errori).
- [x] **AU11** — procedura overdue → sollecito + delay 3gg + escalation responsabile (run_if read_confirmed_flag).
      Pacchetto `au11_procedura_overdue_escalation.automation_package.json`. Validato (1/1, 0 errori).
- [x] **AU12** — qualifica scadenza entro 60gg → notifica HR (usa `days_from_now_lte`).
      Pacchetto `au12_qualifica_scadenza_notifica.automation_package.json`. Validato (1/1, 0 errori).
- [x] **AU23** — offboarding CHIUSA → for_each `dpi` (cross-source) → notifica magazzino per richiesta.
      Pacchetto `au23_offboarding_chiuso_foreach_dpi`. Validato + provato a runtime (2 record → 2 email).
- [x] **AU24** — campagna `closed` → for_each `procedure_assegnazioni` + branch run_if `read_confirmed_flag is_false`
      → sollecito inadempienti. Pacchetto `au24_campagna_chiusa_foreach_inadempienti`. Validato + runtime (3→2).
- [x] **AU30** — asset `dismissed` → for_each `tickets` + branch su ticket aperto. Pacchetto
      `au30_asset_dismesso_foreach_ticket`. Validato. ⚠️ run_if singola condizione: filtra `stato=APERTA`.
- [x] **AU37** — ticket ricorrente (`ricorrente`+`ticket_origine_id`) → `send_approval` manutenzione straord.
      Pacchetto `au37_ticket_ricorrente_approvazione_manutenzione`. ⚠️ soglia "count≥3" NON esprimibile
      (for_each non espone conteggio aggregato a valle); usato il flag `ricorrente`.
- [x] **AU25** — ticket `CHIUSA` → 2× `update_dashboard_metric` increment (contatore + downtime).
      Pacchetto `au25_ticket_chiuso_kpi_live`. ⚠️ i codici metrica vanno creati in dashboard.
- [x] **AU48** — ticket `CRITICA` → escalation 3 livelli (delay 2h + run_if `data_presa_in_carico is_empty`).
      Pacchetto `au48_ticket_critico_escalation_3_livelli`. Validato + gate run_if provato a runtime.
- [x] **AU33** — anomalia aperta (`chiudere=false`) → delay 7gg → sollecito (run_if `chiudere is_false`).
      Pacchetto `au33_anomalia_aperta_troppo_sollecito`. ⚠️ autore=ID legacy → destinatario configurabile.
- [x] **AU34** — segnalazione preposto → delay 14gg → promemoria RSPP. Pacchetto
      `au34_segnalazione_preposto_followup_rspp`. ⚠️ run_if "nessuna azione" non esprimibile (payload).
- [x] **AU35** — offboarding → delay until `{ultimo_giorno_operativo}` → **alert IT** se `IN_CORSO`.
      Pacchetto `au35_offboarding_non_chiuso_alert_it`. Validato + run_if `value` provato a runtime.
- [x] **AU31** — scarico rifiuti `tipo=O` senza `arrivo_fir` → notifica resp. ambientale (no `salva=false`).
      Pacchetto `au31_scarico_senza_fir_notifica`.
- [x] **AU29** — visita `esito` → `NON_IDONEO_TEMP` → SOLO notifica resp. formazione (no for_each).
      Pacchetto `au29_visita_non_idonea_notifica`.
- [x] **AU36/AU37/AU38** — soglie "N eventi in M giorni" via `count_branch` (motore esteso, batch 4).
      AU37 upgradato da flag a soglia reale. Validati + runtime.
- [x] **AU49/AU50** — escalation (assenza non evasa; incidente Accident non chiuso). Validati in dev.
- [x] **AU45/AU47/AU51/AU52** — scaffold management command (job Windows). --dry-run OK. Da rifinire/schedulare.
- [x] **AU-GAP1** — trigger `trg_anomalie_automation.sql` + `modified_by_user_id` (view) + `_enrich_anomalie_payload`
      (ruolo CC/CAR) + registry old_avanzamento/old_chiudere. ⚠️ resta solo la DDL prod: colonna `modified_by_user_id`.
- [x] **AU42b** — versione "per ruolo" (`au42_anomalia_avanzamento_per_ruolo`, `modified_by_role in_csv CC,CAR`).
- [ ] **DDL prod AU-GAP1**: aggiungere colonna `modified_by_user_id` (INT NULL) alla tabella legacy `anomalie`,
      poi rilanciare `apply_sql_triggers`.
- [ ] A seguire: rifinire i 4 digest (destinatari reali, aggregazione per-capo AU51, % per reparto AU47) e
      schedularli come Task Windows. AU21/22/44/46 = NO; AU39/40 = NO/per ora no.

### Tutti i pacchetti pronti (cartella packages/) — 27 pacchetti + 4 management command + 1 trigger SQL
| Pacchetto | Flusso | Stato |
|-----------|--------|-------|
| au41_anomalia_creata_notifica | AU41 | validato, da importare |
| au42_anomalia_avanzamento_cambiato_notifica | AU42 (per campo) | validato, da importare |
| au43_anomalia_chiusa_conferma_autore | AU43 | validato, da importare |
| au13_ferie_lunghe_doppia_approvazione | AU13 (doppia firma) | validato, da importare |
| au14_dpi_approvazione_caporeparto_magazzino | AU14 | validato, da importare |
| au6_offboarding_checklist_notifiche | AU6 (solo notifiche) | validato, da importare |
| au3_incidente_approvazione_rls_rspp | AU3 (doppia firma) | validato, da importare |
| au8_guasto_ricorrente_arricchimento | AU8 | validato, da importare |
| au10_notizia_obbligatoria_broadcast | AU10 | validato, da importare |
| au11_procedura_overdue_escalation | AU11 | validato, da importare |
| au12_qualifica_scadenza_notifica | AU12 | validato, da importare |
| au23_offboarding_chiuso_foreach_dpi | AU23 (for_each cross-source) | validato + runtime, da importare |
| au24_campagna_chiusa_foreach_inadempienti | AU24 (for_each + branch) | validato + runtime, da importare |
| au30_asset_dismesso_foreach_ticket | AU30 (for_each + branch) | validato, da importare |
| au37_ticket_ricorrente_approvazione_manutenzione | AU37 (send_approval) | validato, da importare |
| au25_ticket_chiuso_kpi_live | AU25 (2× metrica) | validato, da importare |
| au48_ticket_critico_escalation_3_livelli | AU48 (delay + run_if) | validato + runtime, da importare |
| au33_anomalia_aperta_troppo_sollecito | AU33 (delay 7gg + run_if) | validato, da importare |
| au34_segnalazione_preposto_followup_rspp | AU34 (delay 14gg) | validato, da importare |
| au35_offboarding_non_chiuso_alert_it | AU35 (delay until + run_if) | validato + runtime, da importare |
| au31_scarico_senza_fir_notifica | AU31 (solo notifica) | validato, da importare |
| au29_visita_non_idonea_notifica | AU29 (solo notifica) | validato, da importare |
| au36_dpi_consumo_anomalo_count | AU36 (count_branch) | validato + runtime, da importare |
| au37_ticket_ricorrente_approvazione_manutenzione | AU37 (count_branch + approval) | validato + runtime, da importare |
| au38_incidenti_ripetuti_reparto_audit | AU38 (count_branch) | validato, da importare |
| au49_assenza_non_evasa_sollecito_reinoltro | AU49 (approval + escalation) | validato, da importare |
| au50_incidente_non_chiuso_escalation_normativa | AU50 (escalation 24/72h/7gg) | validato, da importare |
| au42_anomalia_avanzamento_per_ruolo | AU42b (per ruolo, AU-GAP1) | validato + enrich testato, da importare |

**Management command (NON pacchetti — job schedulati Windows):**
| Command | Flusso | Stato |
|---------|--------|-------|
| anagrafica/.../send_visite_mediche_digest.py | AU45 | scaffold, --dry-run OK |
| anagrafica/.../send_formazione_audit_digest.py | AU47 | scaffold, --dry-run OK |
| tickets/.../send_ticket_daily_digest.py | AU52 | scaffold funzionante, --dry-run OK |
| core/.../send_caporeparto_morning_digest.py | AU51 | scaffold (aggregazione per-capo TODO) |

### Come l'utente attiva i pacchetti pronti
Admin → Automazioni → Importa Package → carica il file `.automation_package.json` da questa cartella →
rivede in preview → conferma import. La regola entra **draft+disattiva**: va aperta nel designer,
sostituito il destinatario `to` (placeholder `DESTINATARIO_DA_CONFIGURARE@...`) e attivata.
Perché scatti davvero serve anche il trigger SQL sulla tabella `anomalie` (vedi apply_sql_triggers.py).

## Come riprendere (passi concreti)

1. Leggi questo file + le righe AU* nel backlog (con le NOTE inline dell'utente già recepite nelle righe AU1-AU20).
2. Apri un pacchetto esistente in questa cartella come template.
3. Crea/modifica il pacchetto successivo seguendo lo schema sopra.
4. Valida con la shell Django in dev (esempio comando nel README di questa cartella, se presente, o:
   `python manage.py shell -c "from automazioni.package_importer import analyze_package_dict; import json; ..."`).
5. Aggiorna lo STATO qui sopra + `CHANGELOG.md` (OBBLIGATORIO) e il backlog.
6. NON attivare le regole sul DB; NON toccare prod/test; commit solo se l'utente lo chiede.
