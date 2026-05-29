docs/ai/AUTOMATION_PACKAGE_REFERENCE.md# NOVICROM HUB — Guida generazione Automation Package JSON

> **A chi è rivolto questo documento**
> Questo è un reference completo e autonomo per generare file `.automation_package.json`
> importabili nel sistema Automazioni di NOVICROM HUB.
> Puoi incollarlo integralmente in qualsiasi AI (Claude, ChatGPT, Codex, ecc.) come contesto,
> poi descrivere il workflow desiderato e richiedere il JSON pronto all'import.

---

## 1. Struttura del package

Un package è un file JSON con questa struttura radice:

```json
{
  "flow_name": "Nome descrittivo del workflow",
  "package_version": "1.0",
  "source_candidate": {
    "source_code": "<codice_sorgente>"
  },
  "proposed_rules": [ ...lista di regole... ]
}
```

Campi opzionali utili:

```json
{
  "approved_field_mapping": {},
  "compatibility": true,
  "issues": []
}
```

---

## 2. Struttura di una regola

Ogni elemento di `proposed_rules` è un oggetto con questi campi:

```json
{
  "code": "slug-univoco-regola",
  "name": "Nome leggibile della regola",
  "description": "Descrizione opzionale",
  "source_code": "<codice_sorgente>",
  "operation_type": "insert | update",
  "trigger_scope": "all_inserts | all_updates | specific_field | any_change",
  "watched_field": "nome_campo",
  "stop_on_first_failure": false,
  "is_active": false,
  "is_draft": true,
  "conditions": [ ...lista condizioni... ],
  "actions": [ ...lista azioni... ]
}
```

**Regole su `operation_type` e `trigger_scope`:**

| `operation_type` | `trigger_scope` consentiti |
|---|---|
| `insert` | solo `all_inserts` |
| `update` | `all_updates`, `specific_field`, `any_change` |

Quando `trigger_scope = "specific_field"` il campo `watched_field` è obbligatorio e deve essere un campo valido della sorgente.

> Le regole vengono **sempre importate come draft inattive** indipendentemente dai valori di `is_active`/`is_draft`.

---

## 3. Condizioni

```json
{
  "order": 1,
  "field_name": "nome_campo_sorgente",
  "operator": "<operatore>",
  "expected_value": "valore_atteso",
  "value_type": "string | int | float | bool | date | datetime",
  "compare_with_old": false,
  "is_enabled": true
}
```

### Operatori disponibili

| Operatore | Significato |
|---|---|
| `equals` | uguale a `expected_value` |
| `not_equals` | diverso da `expected_value` |
| `contains` | contiene la stringa |
| `startswith` | inizia con |
| `endswith` | termina con |
| `gt` | maggiore di |
| `gte` | maggiore o uguale |
| `lt` | minore di |
| `lte` | minore o uguale |
| `is_true` | campo booleano è true (nessun `expected_value`) |
| `is_false` | campo booleano è false (nessun `expected_value`) |
| `in_csv` | il valore è in una lista separata da virgola in `expected_value` |
| `not_in_csv` | il valore NON è nella lista |
| `is_empty` | il campo è vuoto/null |
| `is_not_empty` | il campo ha un valore |
| `changed` | il campo è cambiato rispetto al vecchio valore |
| `changed_to` | il campo è cambiato e il nuovo valore == `expected_value` |
| `changed_from_to` | il campo è cambiato dal vecchio al nuovo — `expected_value` formato `"VECCHIO->NUOVO"` |

`compare_with_old: true` fa confrontare la condizione col valore precedente del campo (utile con `changed_from_to`).

---

## 4. Azioni

Ogni azione ha questa struttura base:

```json
{
  "order": 1,
  "action_type": "<tipo_azione>",
  "description": "Descrizione opzionale",
  "is_enabled": true,
  "config_json": { ...configurazione specifica... }
}
```

---

### 4.1 `send_email`

```json
{
  "action_type": "send_email",
  "config_json": {
    "from_email": "noreply@costruzioninovicrom.it",
    "to": "{richiedente_email}",
    "cc": "responsabile@esempio.com",
    "bcc": "",
    "reply_to": "",
    "subject_template": "Notifica: {titolo}",
    "body_text_template": "Ciao {richiedente_nome},\n\nil tuo ticket {numero_ticket} è stato aggiornato a {stato}.",
    "body_html_template": "",
    "fail_silently": false
  }
}
```

- `to`, `cc`, `bcc`, `reply_to`: stringa email singola, lista separata da virgola, o placeholder `{campo}`
- Almeno uno tra `to`, `cc`, `bcc` deve essere valorizzato
- `body_text_template` o `body_html_template`: almeno uno

---

### 4.2 `write_log`

```json
{
  "action_type": "write_log",
  "config_json": {
    "message_template": "Regola eseguita per ticket {numero_ticket} - nuovo stato: {stato}"
  }
}
```

---

### 4.3 `send_approval`

Sospende il flusso e attende la decisione umana. Dopo la decisione esegue le azioni del ramo corrispondente.

```json
{
  "action_type": "send_approval",
  "config_json": {
    "delivery_mode": "email",
    "to_template": "{capo_email}",
    "subject_template": "Approvazione richiesta assenza - {dipendente_nome}",
    "message_template": "Il dipendente {dipendente_nome} ha richiesto {tipo_assenza} dal {data_inizio} al {data_fine}.\n\nMotivazione: {motivazione_richiesta}",
    "expiry_days": 7,
    "approve_label": "Approva",
    "reject_label": "Rifiuta",
    "approval_email_template_code": "",
    "approved_actions": [
      {
        "order": 1,
        "action_type": "send_email",
        "description": "Notifica approvazione al dipendente",
        "config_json": {
          "to": "{dipendente_email}",
          "subject_template": "La tua richiesta di assenza è stata approvata",
          "body_text_template": "Ciao {dipendente_nome},\nla tua richiesta è stata approvata."
        }
      }
    ],
    "rejected_actions": [
      {
        "order": 1,
        "action_type": "send_email",
        "description": "Notifica rifiuto al dipendente",
        "config_json": {
          "to": "{dipendente_email}",
          "subject_template": "La tua richiesta di assenza è stata rifiutata",
          "body_text_template": "Ciao {dipendente_nome},\nla tua richiesta è stata rifiutata."
        }
      }
    ]
  }
}
```

**`delivery_mode` valori:**

| Valore | Descrizione |
|---|---|
| `email` | Approvazione via link in email |
| `teams_webhook_legacy` | Legacy Teams webhook |
| `teams_chat_flow` | Teams chat via Flow (richiede `teams_flow_endpoint_id`) |
| `email_and_teams_chat_flow` | Entrambi |

> `send_approval` non può essere annidata dentro `approved_actions` o `rejected_actions`.

---

### 4.4 `update_record`

Aggiorna un record nel database tramite whitelist configurata dall'admin.

```json
{
  "action_type": "update_record",
  "config_json": {
    "target_table": "nome_tabella",
    "where_field": "id",
    "where_value_template": "{id}",
    "update_fields": {
      "moderation_status": "1",
      "approvazione_datetime": "{__now__}"
    }
  }
}
```

---

### 4.5 `insert_record`

Inserisce un nuovo record in una tabella (whitelist admin).

```json
{
  "action_type": "insert_record",
  "config_json": {
    "target_table": "nome_tabella",
    "field_mappings": {
      "campo1": "{valore_da_payload}",
      "campo2": "valore_fisso"
    }
  }
}
```

---

### 4.6 `teams_webhook`

```json
{
  "action_type": "teams_webhook",
  "config_json": {
    "webhook_url": "https://...",
    "title_template": "Notifica: {titolo}",
    "message_template": "Il ticket {numero_ticket} è ora in stato {stato}."
  }
}
```

---

### 4.7 `http_request`

```json
{
  "action_type": "http_request",
  "config_json": {
    "method": "POST",
    "url": "https://api.esempio.com/webhook",
    "headers": { "Authorization": "Bearer TOKEN" },
    "body_template": "{\"ticket_id\": \"{id}\", \"stato\": \"{stato}\"}"
  }
}
```

---

### 4.8 `update_dashboard_metric`

```json
{
  "action_type": "update_dashboard_metric",
  "config_json": {
    "metric_code": "codice_metrica",
    "operation": "increment",
    "value_template": "1"
  }
}
```

`operation`: `set`, `increment`, `decrement`.

---

### 4.9 `write_log`

Vedi §4.2.

---

### 4.10 `split_assenza_giornaliera`

Action dedicata alla sorgente `assenze`. Crea record giornalieri derivati per
richieste multi-giorno, replicando il pattern Power Automate `Do until` +
`addDays` sul DB SQL Server del portale.

```json
{
  "action_type": "split_assenza_giornaliera",
  "config_json": {
    "source_code": "assenze",
    "start_field": "data_inizio",
    "end_field": "data_fine",
    "days_count_fields": ["giorni_permesso", "giornipermesso", "Giornipermesso", "giorni"],
    "max_days": 60,
    "tipo_assenza_template": "Permesso",
    "salta_approvazione": true,
    "moderation_status": 0,
    "consenso_template": "Approvato",
    "include_first_day": false,
    "dedupe": true,
    "set_approval_datetime": true
  }
}
```

Note operative:
- `include_first_day=false` mantiene il record originale come primo giorno e crea solo i giorni successivi.
- Se uno dei `days_count_fields` e' presente nel payload, quel valore guida lo split; altrimenti viene usata la differenza tra `data_inizio` e `data_fine`.
- `dedupe=true` evita reinserimenti se una retry queue o una riesecuzione trova gia' righe equivalenti.

---

## 5. Placeholder nei template

Qualsiasi campo della sorgente può essere usato come `{nome_campo}` nei template di email, messaggi e azioni. Usa esattamente il `name` del campo come appare nella tabella campi della sorgente.

---

## 6. Sorgenti disponibili

### 6.1 `assenze` — Richieste assenza

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `dipendente_id` | int | FK dipendente |
| `dipendente_nome` | string | Nome visualizzato (virtuale) |
| `data_inizio` | datetime | Inizio assenza |
| `data_fine` | datetime | Fine assenza |
| `tipo_assenza` | string | Ferie, Permesso, Malattia, ecc. |
| `motivazione_richiesta` | string | Testo libero motivazione |
| `moderation_status` | int | Stato approvazione (0=in attesa, 1=approvato, 2=rifiutato) |
| `approvazione_datetime` | datetime | Timestamp approvazione |
| `capo_reparto_id` | int | FK approvatore |
| `capo_email` | string | Email caporeparto (virtuale) |
| `dipendente_email` | string | Email dipendente |
| `salta_approvazione` | bool | True = bypass flusso approvativo |

---

### 6.2 `tasks` — Task / KICK-OFF

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `title` | string | Titolo task |
| `status` | string | TODO, IN_PROGRESS, DONE, CANCELLED |
| `old_status` | string | Stato precedente (virtuale, payload update) |
| `priority` | string | LOW, MEDIUM, HIGH, CRITICAL |
| `description` | string | Testo descrittivo |
| `assigned_to_id` | int | Utente assegnatario |
| `old_assigned_to_id` | int | Assegnatario precedente (virtuale) |
| `project_id` | int | Progetto/Kickoff |
| `due_date` | date | Scadenza |
| `old_due_date` | date | Scadenza precedente (virtuale) |
| `next_step_due` | date | Scadenza prossimo step |
| `next_step_text` | string | Descrizione prossimo step |
| `tags` | string | Tag/etichette |
| `created_by_id` | int | Utente creatore |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.3 `tickets` — Ticket IT/manutenzione

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `numero_ticket` | string | Es. TKT-2026-0001 |
| `tipo` | string | GUASTO, MANUTENZIONE, IT |
| `titolo` | string | Titolo ticket |
| `descrizione` | string | Descrizione problema |
| `categoria` | string | Categoria ticket |
| `priorita` | string | BASSA, MEDIA, ALTA, CRITICA |
| `stato` | string | APERTA, IN_CARICO, IN_ATTESA, CHIUSA, ANNULLATA |
| `old_stato` | string | Stato precedente (virtuale, payload update) |
| `incide_sicurezza` | bool | Impatti sicurezza |
| `asset_id` | int | Asset collegato |
| `asset_descrizione_libera` | string | Descrizione asset libera |
| `richiedente_nome` | string | Nome richiedente |
| `richiedente_email` | string | Email richiedente |
| `richiedente_legacy_user_id` | int | ID legacy richiedente |
| `assegnato_a` | string | Nome assegnatario |
| `old_assegnato_a` | string | Assegnatario precedente (virtuale) |
| `assegnato_email` | string | Email assegnatario |
| `delegato_fornitore_id` | int | Fornitore delegato |
| `note_interne` | string | Note tecniche riservate |
| `componente` | string | Componente/sotto-sistema |
| `causa_radice` | string | Causa radice a chiusura |
| `tipo_fermo` | string | NESSUNO, PARZIALE, TOTALE |
| `ore_fermo_macchina` | float | Ore fermo produzione |
| `data_presa_in_carico` | datetime | Prima presa in carico |
| `data_primo_intervento` | datetime | Primo intervento |
| `risolto_da_nome` | string | Tecnico risolutore |
| `ricorrente` | bool | Evento ricorrente |
| `data_prevista_risoluzione` | date | ETA risoluzione |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |
| `closed_at` | datetime | Data chiusura |

---

### 6.4 `assets` — Assets

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `asset_tag` | string | Codice univoco asset |
| `name` | string | Nome asset |
| `asset_type` | string | Tipo classificazione |
| `asset_category_id` | int | Categoria asset |
| `status` | string | Stato ciclo di vita |
| `manufacturer` | string | Produttore |
| `model` | string | Modello |
| `serial_number` | string | Numero seriale |
| `assignment_location` | string | Sede/Posizione |
| `assignment_reparto` | string | Reparto assegnazione |
| `assignment_to` | string | Nome assegnatario |
| `assigned_legacy_user_id` | int | ID legacy assegnatario |
| `reparto` | string | Reparto appartenenza |
| `notes` | string | Note |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.5 `anomalie` — Anomalie produzione

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `ex_op_nominativo` | string | Ordine di produzione (OP) |
| `op_lookup_id` | int | Lookup tecnico OP |
| `seriale` | string | PN / Seriale |
| `avanzamento` | string | Stato avanzamento |
| `chiudere` | bool | Flag da chiudere |
| `created_by` | int | Utente autore |
| `ordine_id` | int | Ordine interno |

---

### 6.6 `notizie` — Notizie/bacheca

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `titolo` | string | Titolo notizia |
| `stato` | string | bozza, pubblicata, archiviata |
| `obbligatoria` | bool | Richiede conferma lettura |
| `versione` | int | Numero versione |
| `creato_da_id` | int | Utente creatore |
| `corpo` | string | Testo completo |
| `pubblicato_il` | datetime | Data prima pubblicazione |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.7 `dpi` — Richieste DPI

Workflow: `INVIATA → APPROVATA → CONSEGNATA`

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `numero` | string | Es. DPI-2026-0001 |
| `stato` | string | INVIATA, APPROVATA, CONSEGNATA, RIFIUTATA, ANNULLATA |
| `richiedente_legacy_id` | int | ID legacy richiedente |
| `richiedente_nome` | string | Nome richiedente |
| `richiedente_email` | string | Email richiedente |
| `richiedente_reparto` | string | Reparto richiedente |
| `quantita` | int | Unità DPI richieste |
| `motivazione` | string | Motivazione richiesta |
| `categoria_id` | int | Categoria DPI |
| `note_gestione` | string | Note gestore |
| `created_by_id` | int | Utente creatore |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.8 `diario_preposto` — Segnalazioni sicurezza

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `codice_identificativo` | string | Es. PREP-2026-001 |
| `titolo` | string | Titolo segnalazione |
| `preposto` | string | Nome preposto responsabile |
| `chi_segnala` | string | Nome segnalante |
| `data_segnalazione` | datetime | Data/ora segnalazione |
| `descrizione` | string | Testo descrittivo |
| `creato_da_id` | int | Utente creatore |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.9 `rilevazione_incidenti` — Incidenti/sicurezza

Trigger chiave: `chiusura_rspp` (chiusura), `approvazione_rls` (approvazione RLS).

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `nominativo` | string | Dipendente coinvolto |
| `tipologia_scheda` | string | Unsafe Condition, Unsafe Act, Near Miss, Accident |
| `reparto` | string | Reparto evento |
| `data_segnalazione` | datetime | Data segnalazione |
| `approvazione_rls` | string | Stato approvazione RLS |
| `chiusura_rspp` | bool | Flag chiusura RSPP |
| `data_chiusura_rspp` | date | Data chiusura RSPP |
| `descrizione_attivita` | string | Attività svolta |
| `descrizione_avvenimento` | string | Descrizione accaduto |
| `usa_macchina` | bool | Stava usando una macchina |
| `nome_macchina` | string | Macchina coinvolta |
| `utilizzo_dpi` | bool | Indossava DPI |
| `prima_volta` | bool | Prima occorrenza |
| `causa_evento` | string | Causa principale |
| `misure_tecniche` | bool | Necessarie misure tecniche |
| `quali_misure` | string | Descrizione misure correttive |
| `note_preposto` | string | Note preposto |
| `note_rspp` | string | Note RSPP |
| `why_1` … `why_5` | string | Analisi 5-Whys |

---

### 6.10 `rentri` — Registro rifiuti RENTRI

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `id_registrazione` | string | Es. 2026/001 |
| `tipo` | string | C=carico, O=scarico, M=rettifica, R=rettifica scarico |
| `data` | date | Data movimento |
| `codice` | string | Codice CER/EWC |
| `quantita` | float | Quantità |
| `rentri_si_no` | bool | Da trasmettere a RENTRI |
| `carico_scarico` | string | Direzione movimento |
| `pericolosita` | string | Classificazione pericolosità |
| `inserito_da` | string | Operatore inserimento |
| `salva` | bool | Consolidato definitivamente |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.11 `procedure_campagne` — Campagne procedure MT/MTSI

Stati: `draft → published → closed → archived`

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `name` | string | Nome campagna |
| `status` | string | draft, published, closed, archived |
| `start_date` | date | Data inizio |
| `due_date` | date | Scadenza |
| `published_at` | datetime | Data pubblicazione |
| `closed_at` | datetime | Data chiusura |
| `description` | string | Descrizione |
| `created_by_id` | int | Utente creatore |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.12 `procedure_assegnazioni` — Assegnazioni procedure

Workflow: `assigned → opened → read_confirmed` (o `overdue/cancelled`)

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `status` | string | assigned, opened, read_confirmed, overdue, cancelled |
| `user_id` | int | Utente assegnato |
| `campaign_id` | int | Campagna |
| `due_date` | date | Scadenza conferma |
| `first_opened_at` | datetime | Prima apertura documento |
| `read_confirmed_at` | datetime | Conferma lettura |
| `read_confirmed_flag` | bool | Flag conferma lettura |
| `revision_id` | int | Revisione documento |
| `assigned_by_id` | int | Chi ha assegnato |
| `assigned_at` | datetime | Data assegnazione |
| `last_opened_at` | datetime | Ultima apertura |
| `open_count` | int | Numero aperture |
| `user_note` | string | Nota utente |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.13 `anagrafica_qualifiche` — Qualifiche dipendenti

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `legacy_anagrafica_id` | int | ID legacy dipendente |
| `tipo_id` | int | FK TipoQualifica |
| `data_conseguimento` | date | Data ottenimento qualifica |
| `data_scadenza` | date | Scadenza (null = nessuna) |
| `note` | string | Note libere |
| `created_at` | datetime | Data creazione |

---

### 6.14 `anagrafica_visite_mediche` — Visite mediche

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `legacy_anagrafica_id` | int | ID legacy dipendente |
| `tipo_id` | int | FK TipoVisitaMedica |
| `data_svolgimento` | date | Data visita |
| `data_scadenza` | date | Scadenza idoneità |
| `esito` | string | IDONEO, IDONEO_MANS, IDONEO_PRESCR, IDONEO_LIM, IDONEO_LIM_PRESCR, NON_IDONEO_TEMP, NON_IDONEO_DEF |
| `prescrizioni` | string | Testo prescrizioni |
| `medico_competente` | string | Nome medico |
| `note` | string | Note |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.15 `anagrafica_formazione_enrollment` — Iscrizioni corsi

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `sessione_id` | int | FK sessione formativa |
| `legacy_anagrafica_id` | int | ID legacy dipendente |
| `assignment_id` | int | FK assegnazione corso |
| `stato` | string | ISCRITTO, IN_CORSO, COMPLETATO, NON_IDONEO, ASSENTE, RITIRATO |
| `ore_frequentate` | float | Ore frequentate |
| `percentuale_presenza` | float | % presenze |
| `idoneo` | bool | Idoneità finale |
| `esito_esame` | string | Risultato esame |
| `data_completamento` | date | Data completamento |
| `created_at` | datetime | Data iscrizione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

### 6.16 `anagrafica_formazione_record` — Record completamento formazione

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `corso_id` | int | FK corso completato |
| `sessione_id` | int | FK sessione |
| `legacy_anagrafica_id` | int | ID legacy dipendente |
| `data_completamento` | date | Data completamento |
| `ore_frequentate` | float | Ore totali |
| `idoneo` | bool | Superato |
| `data_scadenza` | date | Scadenza abilitazione (null = una tantum) |
| `course_code_snapshot` | string | Codice corso (storico) |
| `course_title_snapshot` | string | Titolo corso (storico) |
| `plan_code_snapshot` | string | Codice piano (storico) |
| `plan_name_snapshot` | string | Nome piano (storico) |
| `teacher_name_snapshot` | string | Nome docente (storico) |
| `created_at` | datetime | Data creazione |

---

### 6.17 `anagrafica_offboarding` — Pratiche offboarding

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `legacy_anagrafica_id` | int | ID legacy dipendente |
| `dipendente_nome` | string | Nome dipendente (snapshot) |
| `reparto` | string | Reparto |
| `mansione` | string | Mansione |
| `motivo` | string | licenziamento, dimissioni, fine_contratto, pensionamento, altro |
| `data_cessazione_prevista` | date | Data prevista cessazione |
| `ultimo_giorno_operativo` | date | Ultimo giorno in azienda |
| `stato` | string | IN_CORSO, CHIUSA, CHIUSA_CON_ECCEZIONI, ANNULLATA |
| `note_hr` | string | Note HR |
| `created_at` | datetime | Data apertura pratica |
| `updated_at` | datetime | Ultimo aggiornamento |
| `closed_at` | datetime | Data chiusura |

---

### 6.18 `anagrafica_fornitori` — Fornitori

| Campo | Tipo | Note |
|---|---|---|
| `id` | int | PK |
| `ragione_sociale` | string | Denominazione fornitore |
| `piva` | string | Partita IVA |
| `email` | string | Email principale |
| `pec` | string | PEC |
| `telefono` | string | Telefono |
| `categoria` | string | MATERIALI, SERVIZI, ATTREZZATURE, LOGISTICA, IT, MANUTENZIONE, ALTRO |
| `is_active` | bool | Attivo/disattivo |
| `note` | string | Note |
| `created_at` | datetime | Data creazione |
| `updated_at` | datetime | Ultimo aggiornamento |

---

## 7. Esempi completi

### Esempio A — Notifica email al cambio stato ticket

```json
{
  "flow_name": "Ticket → notifica cambio stato al richiedente",
  "package_version": "1.0",
  "source_candidate": { "source_code": "tickets" },
  "proposed_rules": [
    {
      "code": "ticket-cambio-stato-email-richiedente",
      "name": "Email richiedente al cambio stato ticket",
      "source_code": "tickets",
      "operation_type": "update",
      "trigger_scope": "specific_field",
      "watched_field": "stato",
      "stop_on_first_failure": false,
      "conditions": [
        {
          "order": 1,
          "field_name": "richiedente_email",
          "operator": "is_not_empty",
          "expected_value": "",
          "value_type": "string",
          "is_enabled": true
        }
      ],
      "actions": [
        {
          "order": 1,
          "action_type": "send_email",
          "description": "Notifica cambio stato al richiedente",
          "config_json": {
            "to": "{richiedente_email}",
            "subject_template": "[{numero_ticket}] Aggiornamento stato: {stato}",
            "body_text_template": "Ciao {richiedente_nome},\n\nil tuo ticket {numero_ticket} - \"{titolo}\" è stato aggiornato.\n\nNuovo stato: {stato}\n\nGrazie."
          }
        }
      ]
    }
  ]
}
```

---

### Esempio B — Approvazione assenza con email al capo

```json
{
  "flow_name": "Assenza → richiesta approvazione caporeparto",
  "package_version": "1.0",
  "source_candidate": { "source_code": "assenze" },
  "proposed_rules": [
    {
      "code": "assenza-nuova-approvazione-capo",
      "name": "Nuova assenza — invia approvazione al capo",
      "source_code": "assenze",
      "operation_type": "insert",
      "trigger_scope": "all_inserts",
      "stop_on_first_failure": false,
      "conditions": [
        {
          "order": 1,
          "field_name": "salta_approvazione",
          "operator": "is_false",
          "expected_value": "",
          "value_type": "bool",
          "is_enabled": true
        }
      ],
      "actions": [
        {
          "order": 1,
          "action_type": "send_approval",
          "description": "Richiede approvazione al caporeparto",
          "config_json": {
            "delivery_mode": "email",
            "to_template": "{capo_email}",
            "subject_template": "Richiesta assenza da approvare — {dipendente_nome}",
            "message_template": "{dipendente_nome} ha richiesto {tipo_assenza}\ndal {data_inizio} al {data_fine}.\n\nMotivazione: {motivazione_richiesta}",
            "expiry_days": 3,
            "approve_label": "Approva",
            "reject_label": "Rifiuta",
            "approved_actions": [
              {
                "order": 1,
                "action_type": "send_email",
                "config_json": {
                  "to": "{dipendente_email}",
                  "subject_template": "La tua richiesta di {tipo_assenza} è stata approvata",
                  "body_text_template": "Ciao {dipendente_nome},\nla tua richiesta è stata approvata."
                }
              },
              {
                "order": 2,
                "action_type": "write_log",
                "config_json": {
                  "message_template": "Assenza {id} approvata per {dipendente_nome}"
                }
              }
            ],
            "rejected_actions": [
              {
                "order": 1,
                "action_type": "send_email",
                "config_json": {
                  "to": "{dipendente_email}",
                  "subject_template": "La tua richiesta di {tipo_assenza} è stata rifiutata",
                  "body_text_template": "Ciao {dipendente_nome},\nla tua richiesta è stata rifiutata. Contatta il tuo responsabile."
                }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

---

### Esempio C — Notifica scadenza qualifica dipendente

```json
{
  "flow_name": "Qualifica — avviso inserimento nuova qualifica",
  "package_version": "1.0",
  "source_candidate": { "source_code": "anagrafica_qualifiche" },
  "proposed_rules": [
    {
      "code": "qualifica-nuova-log",
      "name": "Log inserimento nuova qualifica dipendente",
      "source_code": "anagrafica_qualifiche",
      "operation_type": "insert",
      "trigger_scope": "all_inserts",
      "stop_on_first_failure": false,
      "conditions": [],
      "actions": [
        {
          "order": 1,
          "action_type": "write_log",
          "config_json": {
            "message_template": "Nuova qualifica inserita per dipendente {legacy_anagrafica_id} — tipo {tipo_id} — scadenza {data_scadenza}"
          }
        }
      ]
    }
  ]
}
```

---

### Esempio D — Offboarding aperto → notifica HR e IT

```json
{
  "flow_name": "Offboarding — notifica apertura pratica a HR e IT",
  "package_version": "1.0",
  "source_candidate": { "source_code": "anagrafica_offboarding" },
  "proposed_rules": [
    {
      "code": "offboarding-apertura-notifica",
      "name": "Nuova pratica offboarding — notifica HR e IT",
      "source_code": "anagrafica_offboarding",
      "operation_type": "insert",
      "trigger_scope": "all_inserts",
      "stop_on_first_failure": false,
      "conditions": [],
      "actions": [
        {
          "order": 1,
          "action_type": "send_email",
          "description": "Notifica HR",
          "config_json": {
            "to": "hr@costruzioninovicrom.it",
            "subject_template": "Offboarding aperto — {dipendente_nome}",
            "body_text_template": "È stata aperta una pratica di offboarding per {dipendente_nome} ({reparto}).\n\nMotivo: {motivo}\nData cessazione prevista: {data_cessazione_prevista}\n\nAccedi al portale per gestire i task."
          }
        },
        {
          "order": 2,
          "action_type": "send_email",
          "description": "Notifica IT",
          "config_json": {
            "to": "it@costruzioninovicrom.it",
            "subject_template": "Richiesta disattivazione account — {dipendente_nome}",
            "body_text_template": "Il dipendente {dipendente_nome} (reparto: {reparto}) cesserà il {data_cessazione_prevista}.\n\nPrepara la disattivazione account entro quella data."
          }
        },
        {
          "order": 3,
          "action_type": "write_log",
          "config_json": {
            "message_template": "Offboarding aperto per {dipendente_nome} - motivo: {motivo}"
          }
        }
      ]
    }
  ]
}
```

---

## 8. Regole di validazione da rispettare

1. **`source_code` deve essere identico** tra `source_candidate.source_code` e la proprietà `source_code` di ogni regola.
2. **`operation_type: "insert"` richiede `trigger_scope: "all_inserts"`**.
3. **`trigger_scope: "specific_field"` richiede `watched_field`** valorizzato con un campo reale della sorgente.
4. **`send_email` richiede almeno un destinatario** in `to`, `cc`, o `bcc`.
5. **`send_approval` non può contenere un'altra `send_approval`** in `approved_actions` o `rejected_actions`.
6. **I placeholder `{campo}` devono corrispondere** a nomi campo della sorgente selezionata.
7. **Il `code` della regola** deve essere un slug (lettere minuscole, numeri, trattini). Sarà normalizzato automaticamente.

---

## 9. Istruzioni per l'AI che genera il JSON

Quando l'utente descrive un workflow da automatizzare:

1. **Identifica la sorgente** corretta dalla lista §6.
2. **Scegli `operation_type`** (insert = record nuovo, update = record modificato).
3. **Scegli `trigger_scope`** (se il trigger riguarda un campo specifico usa `specific_field` + `watched_field`).
4. **Aggiungi condizioni** solo se il workflow deve attivarsi in un sottoinsieme di casi.
5. **Costruisci le azioni** nell'ordine logico. Usa `write_log` come ultima azione per audit.
6. **Usa placeholder** `{nome_campo}` esattamente come appaiono nelle tabelle §6.
7. Restituisci un JSON valido, ben formattato, pronto per essere salvato come `.automation_package.json` e importato nel portale.

---

*Documento generato da NOVICROM HUB — aggiornato al 2026-05-28*
