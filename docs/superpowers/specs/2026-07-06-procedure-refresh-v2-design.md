# Procedure Refresh v2 — Motore scadenze, sync SGI, segnalazioni modifica, ACL v2

**Data**: 2026-07-06
**Modulo**: `django_app/procedure_refresh` (+ tocchi mirati a `automazioni/schedules.py`, `core/middleware.py`, `ai_assistant`)
**Branch**: `feature/skill-matrix-mod187` (branch di prod)
**Stato**: approvato a voce in sessione, in attesa di revisione spec

## Contesto e vincolo normativo

La presa visione delle procedure è un requisito **ISO 9001 §7.5.3 / EN 9100**
(controllo delle informazioni documentate): distribuzione controllata con evidenza,
disponibilità della revisione corrente ai punti di uso, prevenzione dell'uso di
documenti obsoleti, ciclo di modifica tracciato. Il modulo oggi registra bene le
conferme (audit trail su `ProcedureReadEvent` + `log_action`) ma ha quattro buchi:

1. **Il "motore tempo" non esiste**: lo stato `OVERDUE` è previsto ovunque nella UI
   ma niente lo imposta mai; `REMINDER_SENT` è previsto ma nessun flusso invia
   solleciti. KPI "Scadute" sempre a 0.
2. **L'import SGI dalla share è manuale** (`import_sgi_da_share --apply`): il
   watchdog notturno rileva il drift ma la sincronizzazione resta un'azione umana
   ricorrente.
3. **Nessun canale di feedback sul documento**: chi legge non può proporre
   modifiche in modo tracciato (ciclo di miglioramento ISO non dimostrabile).
4. **ACL binario legacy**: `_is_manager` = superuser o admin legacy; le 11 risorse
   granulari già bootstrappate (`pr_admin`, `pr_campaigns`, …) non sono usate.
   Chi gestisce qualità/RSPP deve essere admin di portale.

In più un **bug reale**: `campaign_remove_document` referenzia la variabile
inesistente `campaign` nel log (`views.py:929`) → 500 NameError dopo la delete.

## Decisioni prese col committente

- **Niente mail automatica all'assegnazione**: la comunicazione iniziale la manda
  il supporto IT a mano. Resta la Notifica in dashboard portale (costo zero) e un
  helper "copia elenco destinatari" nel dettaglio campagna per comporre la mail
  manuale.
- **Solleciti automatici sì, ciclo completo**: pre-scadenza, post-scadenza,
  digest gestore. Tutto configurabile e disattivabile da SiteConfig.
- **Sync SGI**: automatica notturna (perimetro sicuro) **+** pulsante "Sincronizza
  ora" nella dashboard admin. La parte presa-visione resta sotto firma umana.
- **Niente quiz-gate**: il quiz resta com'è. Al suo posto, **segnalazioni di
  modifica per documento** con stati e chiusura del ciclo (evidenza audit).
- **ACL v2 canonico** con binding delle route alle risorse esistenti e ruolo
  "Gestore procedure" non-admin.
- Mail sempre su `email_notifica` (via `resolve_notification_email`), mai sul
  campo `email` legacy (che è il login).

## Fase 0 — Bugfix immediato

- `campaign_remove_document`: `campaign_id=campaign.pk` → `campaign_id=pk`.
- Rimozione import inutilizzato `UtenteLegacy` in `_is_manager`.
- Test di regressione sulla rimozione documento da campagna.

## Fase A — Motore scadenze e solleciti

### Task `run_assignment_lifecycle` (nuovo, `procedure_refresh/tasks.py`)

Schedulato in `automazioni/schedules.py` (CRON giornaliero mattutino, es. 06:45,
mai schedule di tipo "S"/SECONDS). A ogni run, fail-safe come gli altri task:

1. **Marca OVERDUE**: assegnazioni `assigned`/`opened` di campagne `published`
   con `due_date < oggi` → `status=overdue` + `ProcedureReadEvent` (nuovo tipo
   `ReadEventType.OVERDUE_MARKED = "overdue_marked"`) — la transizione resta
   nell'audit trail.
2. **Sollecito pre-scadenza** al dipendente: per assegnazioni pendenti con
   `due_date` tra oggi e N giorni (soglie configurabili, default `7,2`), mail su
   `email_notifica` + Notifica dashboard. Un solo invio per soglia (dedup su
   `REMINDER_SENT` con soglia nei `meta_json`).
3. **Sollecito post-scadenza** al dipendente: per assegnazioni `overdue`, mail con
   cadenza configurabile (default ogni 7 giorni; dedup: nessun invio se esiste un
   `REMINDER_SENT` più recente della cadenza).
4. **Digest gestore**: elenco aggregato degli inadempienti (per campagna e
   reparto), cadenza configurabile (default settimanale, lunedì), destinatari da
   elenco email in SiteConfig.

Ogni invio logga `ProcedureReadEvent(REMINDER_SENT)` con esito; errori SMTP non
fanno fallire il run (log warning, si riprova al giro successivo).

### Configurazione (SiteConfig, pattern `tickets_escalation_*`)

| Chiave | Default | Significato |
|---|---|---|
| `pr_reminder_attivo` | `False` | Interruttore generale solleciti email |
| `pr_reminder_pre_giorni` | `7,2` | Soglie giorni pre-scadenza |
| `pr_reminder_post_cadenza_giorni` | `7` | Cadenza sollecito agli scaduti |
| `pr_reminder_digest_giorno` | `lun` | Giorno del digest gestore (vuoto = off) |
| `pr_reminder_digest_destinatari` | `""` | Email gestori, separate da virgola |

La marcatura OVERDUE gira **sempre** (anche con solleciti spenti): è lo stato dei
dati, non una notifica. Card impostazioni nella dashboard admin del modulo
(stesso posto del branding), POST gestito nella view `admin_dashboard`.

### Notifica portale all'assegnazione + helper mail manuale

- `assign_users`: crea Notifiche dashboard (`core.notifiche`) per gli assegnati —
  una per utente per azione, non una per documento.
- `campaign_detail`: pulsante "Copia elenco destinatari" (clipboard JS) con
  `Nome Cognome <email_notifica>` degli assegnati pendenti, per la mail manuale IT.
  Gli utenti senza `email_notifica` sono evidenziati nell'elenco.

## Fase B — Sync SGI automatica + pulsante

### Task `run_sgi_auto_sync` (nuovo, `procedure_refresh/tasks.py`)

Schedulato alle **03:00** (prima del re-index RAG delle 03:30, che così indicizza
già i documenti nuovi della stessa notte). Dietro flag SiteConfig
`pr_sgi_auto_sync_attivo` (default `False`). Riusa `scan_share_candidates` +
`_upsert` (estratto dal Command in funzione modulare riusabile).

**Perimetro sicuro — auto-applica il candidato solo se:**
- il nome file è riconosciuto dal parser (`fallback=False`), **e**
- il documento è nuovo (codice assente in DB), **oppure** esiste ed è interamente
  "figlio dell'import": tutte le revisioni `source_type=fileserver`,
  `requires_acknowledgement=False`, zero assegnazioni su qualunque sua revisione.

Tutto il resto (fallback, conflitti, documenti ibridi toccati a mano o usati in
campagne) **non viene scritto**: finisce nel report per il watchdog. Così l'import
automatico non può mai scavalcare la revisione corrente di un documento in presa
visione (`_upsert` forza `is_current=True`: su documenti gestiti a mano sarebbe un
hijack silenzioso dell'evidenza ISO).

Esito di ogni run salvato in SiteConfig `pr_sgi_last_sync` (JSON: timestamp,
creati/aggiornati/saltati/anomalie) e mostrato nella dashboard admin.

### Pulsante "Sincronizza ora" (dashboard admin)

POST dedicato → `async_task` django-q con la stessa funzione + trigger di
`ai_assistant.tasks.run_index_sgi_documents` a valle (di notte non serve: ci pensa
lo schedule delle 03:30). Banner "sincronizzazione avviata", esito nella card
`pr_sgi_last_sync` al refresh. Route protetta dal medesimo ACL admin del modulo.

### Watchdog 04:30 ricalibrato (`run_sgi_share_check`)

- Se l'auto-sync è attivo, la Issue segnala solo le **anomalie residue**: candidati
  fallback, conflitti, documenti ibridi esclusi dal perimetro sicuro.
- **Novità — documenti spariti dalla share**: attivi in DB, interamente
  `fileserver`, il cui `source_path` non esiste più o è finito sotto `SUPERATO`.
  Solo notifica (severità LOW), **mai disattivazione automatica**: la decisione
  resta umana, ma il requisito ISO "prevenire l'uso di obsoleti" è presidiato.

## Fase C — Segnalazioni di modifica per documento

### Modello `ProcedureChangeRequest` (nuova migrazione)

| Campo | Tipo | Note |
|---|---|---|
| `document` | FK `ProcedureDocument` (PROTECT) | indicizzato con `status` |
| `revision` | FK `ProcedureRevision` (PROTECT, null) | la revisione letta quando è nata la proposta |
| `assignment` | FK `ProcedureAssignment` (SET_NULL, null) | aggancio all'evidenza di lettura |
| `created_by` | FK utente (SET_NULL, null) | proponente |
| `testo` | TextField | la proposta di modifica |
| `status` | choices: `aperta` / `in_carico` / `recepita` / `respinta` | default `aperta` |
| `risposta_gestore` | TextField blank | motivazione chiusura |
| `gestita_da` / `gestita_il` | FK utente / DateTime null | chi e quando ha chiuso |
| `recepita_in_revisione` | FK `ProcedureRevision` (SET_NULL, null) | chiusura del ciclo: "recepita in Rev.X" |
| `created_at` / `updated_at` | auto | |

Le segnalazioni **non si cancellano mai** (sono evidenza): solo cambi di stato,
tutti loggati con `log_action`.

### UI

- **Dettaglio assegnazione**: sezione "Proponi modifiche a questo documento"
  (textarea + invio, elenco delle proprie segnalazioni con stato). Distinta dalla
  `user_note` esistente, che resta com'è.
- **Vista gestore** (nuova pagina `admin/segnalazioni/`): elenco filtrabile per
  documento/stato, azioni di cambio stato con risposta e selezione "recepita in
  Rev.X". Nuova risorsa ACL `pr_change_requests` nel bootstrap.
- **Dashboard admin**: KPI "Segnalazioni aperte". **Elenco documenti**: badge
  conteggio segnalazioni aperte per documento.

## Fase D — ACL v2 canonico + pulizia UX

### ACL

- Binding canonico delle route del modulo alle risorse già bootstrappate
  (`pr_view`, `pr_assignment_detail`, `pr_admin`, `pr_documents`, `pr_campaigns`,
  `pr_report_*`, `pr_revision_quiz`, `pr_export_csv`, + nuova `pr_change_requests`).
- `_is_manager` sostituito da un check ACL v2 canonico sulle risorse admin del
  modulo, con fallback legacy (superuser / admin legacy) finché la copertura non è
  completa — pattern coerente con la migrazione ACL in corso.
- **`api_parse_sharepoint_url` mappata in `core/middleware.py`
  `API_ACL_GATE_PATHS`** verso una risorsa bound (senza, `ACL_STRICT_CANONICAL`
  nega 403 ai non-superuser; i test con superuser non lo scoprirebbero).
- Risultato: ruolo "Gestore procedure" assegnabile a qualità/RSPP dalla matrice
  permessi, senza admin di portale.
- Verifica post-fase: `acl_coverage_report` e `acl_fallback_report --only-unbound`.

### UX (convivenza presa-visione / corpus RAG)

- `document_list`: tab "Presa visione" / "Corpus AI" su `requires_acknowledgement`
  (default: Presa visione) + ricerca semplice per codice/titolo.
- Picker "aggiungi documento a campagna" (`campaign_detail`): solo documenti
  `requires_acknowledgement=True` e **solo revisioni correnti** (oggi elenca tutte
  le revisioni di tutti i documenti attivi: centinaia di voci dopo l'import SGI).

## Fuori perimetro (esplicito)

- Quiz: nessuna modifica (resta facoltativo post-conferma, tentativo unico).
- Mail automatica all'assegnazione: esclusa, la manda il supporto IT.
- Campagne "delta" automatiche alla nuova revisione: non richieste, eventuale
  iterazione futura.
- Disattivazione automatica dei documenti spariti dalla share: mai automatica.
- Storage dei PDF nel portale: il modulo resta a puntatori (SharePoint/UNC).

## Ordine di esecuzione e qualità

0 → A → B → C → D. Un commit per fase sul branch, test scoped
`python django_app\manage.py test django_app.procedure_refresh --keepdb
--settings=config.settings.test` per fase (Fase B: anche i test del watchdog
esistenti; Fase D: verifica coverage ACL). CHANGELOG.md + README.md aggiornati a
ogni fase; version bump (checklist `docs/ai/06`) a fine lavoro perché la
funzionalità è user-facing. Flag nuovi tutti default-off → deploy sicuro sul
branch di prod.

## Rischi e mitigazioni

- **Solleciti duplicati** se il task gira due volte: dedup su `REMINDER_SENT`
  per (assegnazione, soglia, finestra) — idempotente by design.
- **Share irraggiungibile di notte**: skip fail-safe già collaudato dal watchdog.
- **Hijack revisioni in presa visione da auto-sync**: impedito dal perimetro
  sicuro (criterio "interamente figlio dell'import").
- **403 API con strict canonical**: mappatura `API_ACL_GATE_PATHS` inclusa nella
  Definition of Done della Fase D, testata con utente non-superuser.
