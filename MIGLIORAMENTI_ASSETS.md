# MIGLIORAMENTI ASSETS

Analisi statica dell'app `django_app/assets` (inventario asset/attrezzature, manutenzione, licenze, contratti, planimetrie, QR, report).
Data analisi: 2026-07-14. Nessuna modifica applicata; test non eseguiti. Sola lettura, file per file.

Coordinata con: **ANALISI_01** (F4 download IDOR, F11 monolite — entrambi verificati e ampliati qui), **MIGLIORAMENTI_CONTATORI_HUB** (P2-5 sovrapposizione AssetMeter), e il **refactor in corso di fusione asset_type/asset_category** in un'altra sessione (qui si segnalano solo le dipendenze, nessuna proposta confliggente).

## Executive summary

Il modulo è il più grande del portale (`views.py`: ~17.6k righe fisiche, ~448 funzioni — erano 373 al tempo di ANALISI_01: il monolite **cresce**) ma non è un modulo "marcio": l'overhaul manutenzione ha prodotto un motore scadenzario unificato ben fatto (`maintenance.py`), con il principio sano "ciò che vedi = ciò che viene generato", buona copertura test (`tests.py` 7.5k righe) e un'ergonomia da officina sopra la media dell'HUB (QR landing pubblica, presa in carico, checklist HTMX, segnalazione rapida).

I problemi seri stanno in tre punti:

1. **Sicurezza documenti** — F4 è ancora aperto e il problema è più ampio di quanto mappato in ANALISI_01: oltre all'IDOR sul download, i file di `AssetDocument` e `WorkOrderAttachment` vivono in `MEDIA_ROOT`, che in produzione IIS serve **in anonimo**; la landing QR pubblica distribuisce quegli URL a visitatori non autenticati. In più, alcune azioni di **scrittura** (import Excel, bulk update, cancellazione documenti) sono gate-ate dal solo login, in contrasto con le azioni sorelle che verificano l'admin.
2. **Coerenza generatore/scadenzario** — la registrazione di un'esecuzione dal scadenzario crea un OdL `origin=MANUAL`, ma il generatore automatico calcola la prossima scadenza solo dagli OdL `origin=PERIODIC`: probabile rigenerazione spuria di OdL subito dopo una registrazione manuale.
3. **Dark mode** — 2.416 colori hex hardcoded in 50 template, tema scuro ottenuto con 942 regole di override `body.theme-dark` in soli 24 file: ~26 pagine con colori fissi restano senza alcun override (stesso pattern già visto in formazione).

L'AI ha **un** caso d'uso forte (riepilogo storico interventi per asset, tool-live) e uno medio (RAG sui manuali); la manutenzione predittiva, a questa scala e con questi dati, **non** è un caso d'uso reale.

## Tabella severità × effort

| ID | Finding | Dimensione | Severità | Effort |
|----|---------|------------|----------|--------|
| S1 | F4 confermato: `asset_document_download` senza controllo per-oggetto (IDOR) | Sicurezza | **Alta** | Basso |
| S2 | `AssetDocument`/`WorkOrderAttachment` su MEDIA servita anonima da IIS; URL esposti dalla QR landing pubblica (pattern F3) | Sicurezza | **Alta** | Medio |
| S3 | Scritture gate-ate dal solo login: import Excel, bulk update, upload/delete documenti | Sicurezza | **Alta** | Basso |
| S4 | Audit `asset_meter_update` chiamato con firma sbagliata → audit perso in silenzio | Sicurezza/Osservabilità | Media | Basso |
| S5 | API JSON assets assenti da `API_ACL_GATE_PATHS` (verifica strict-mode + 401/403 JSON) | Sicurezza | Media | Basso |
| S6 | Export completi (inventario, OdL, dettaglio) a qualsiasi utente autenticato | Sicurezza | Bassa | Basso |
| C1 | Drift generatore/scadenzario: esecuzione registrata = `origin=MANUAL`, generatore guarda solo `PERIODIC` | Correttezza | **Alta** | Basso |
| C2 | Generatore OdL idempotente solo in-process: run concorrenti possono duplicare | Concorrenza | Media | Basso |
| C3 | `WorkOrder.close()` non atomico, senza guard doppia chiusura, con `except: pass` | Concorrenza | Media | Medio |
| C4 | `AssetMeter.update_value` read-modify-write senza lock né validazione monotonia | Concorrenza/Dati | Bassa | Basso |
| C5 | `workorder_claim` last-write-wins su presa in carico | Concorrenza | Bassa | Basso |
| C6 | `_generate_asset_tag` scan O(N) di tutte le tag a ogni creazione | Efficienza | Bassa | Basso |
| D1 | `Asset.status` CharField senza transizioni, validazioni né log | Modello dati | Media | Medio |
| D2 | Dipendenze del refactor fusione tipo/categoria (solo mappa, nessuna proposta) | Modello dati | — | — |
| D3 | `WorkMachine.next_maintenance_date` denormalizzato, aggiornato solo per regole a giorni | Modello dati | Media | Medio |
| D4 | `AssetMeter` vs modulo `contatori`: sovrapposizione solo concettuale — NON fondere | Architettura | Bassa | — |
| F11 | Monolite `views.py` in crescita (+75 funzioni da ANALISI_01); scomposizione per domini fattibile | Debito | **Alta** (abilitante) | Alto |
| U1 | Dark mode: 2.416 hex hardcoded, 942 override, ~26 pagine senza copertura dark | UI | Media | Alto (incrementale) |
| U2 | Tre ingressi scadenzario (hub, prossime, calendario) con semantica sovrapposta | Fruibilità | Bassa | Medio |
| U3 | Liste separate per scadenze amministrative e verifiche legacy | Fruibilità | Bassa | Basso |
| A1 | AI: riepilogo storico interventi per asset (tool-live) | AI | Valore alto | Medio |
| A2 | AI: RAG sui manuali asset per manutentori | AI | Valore medio | Medio |
| A3 | AI: manutenzione predittiva / suggerimento categoria — **da NON fare** | AI | — | — |

---

## 1. CODICE

### Numeri del modulo

- `views.py` ~17.6k righe fisiche / **~448 funzioni** (ANALISI_01 contava 373: +75 in ~5 settimane — il monolite cresce, non si stabilizza). `models.py` 2.540 righe / 31 modelli; `forms.py` 2.535; `tests.py` 7.535 (copertura reale, punto di forza); 74 migrazioni; 22 management command; `maintenance.py` + `services/` già estratti (il pattern di scomposizione esiste e funziona).

### 1.1 S1 · ALTA — F4 confermato: download documenti asset ancora senza controllo per-oggetto

`views.py:3102-3142` — `asset_document_download` è invariato rispetto ad ANALISI_01: `@login_required` + `get_object_or_404(AssetDocument, pk=document_id)` e il file viene servito a **qualsiasi utente autenticato** iterando `document_id`. Il contrasto interno resta: la vista sorella `admin_deadline_attachment_download` (`views.py:3422-3478`) verifica `_is_assets_admin` e **logga il diniego**.

Censimento delle altre superfici di download (richiesto dal follow-up F4):

| Superficie | Gate | Note |
|---|---|---|
| `asset_document_download` (views.py:3102) | solo login | **IDOR — da sanare** |
| `admin_deadline_attachment_download` (views.py:3422) | admin + audit + storage privato cifrato | riferimento corretto |
| `WorkOrderAttachment` | **nessuna view**: il template linka `attachment.file.url` (workorder_detail.html:312) | vedi S2: file su MEDIA anonima |
| `AssetReportTemplate` | `row.file.url` diretto (report_template_admin.html:280) | pagina admin, contenuto poco sensibile |
| Export xlsx/pdf (`asset_list_export` views.py:13319, `workorder_list_export`:13393, `asset_detail_export_xlsx`:16476, report PDF:16433) | solo login | vedi S6 |

**Proposta (P0, effort basso):** riusare in `asset_document_download` lo stesso predicato di visibilità dell'asset (oggi di fatto: utente autenticato ⇒ tutto; quindi almeno gate admin/manutentore come la sorella, o un check "l'utente vede l'asset" se/quando nascerà uno scope). Aggiungere il log del diniego come a `views.py:3428-3442`.

### 1.2 S2 · ALTA — Documenti e allegati OdL in webroot servito anonimo (pattern F3)

- `AssetDocument.file` (`models.py:1511`) e `WorkOrderAttachment.file` (`models.py:2094`) usano lo **storage di default** → `MEDIA_ROOT/assets_documents/<asset_tag>/...` e `MEDIA_ROOT/assets_workorders/...`.
- In produzione IIS serve `/media/` **in anonimo** (`deployment/config/web.config.httpplatform.template:144-163`); le uniche eccezioni sono `media/tickets` (deny, righe 165-176) e `media_private` (deny totale, righe 185+). I percorsi asset **non** sono esclusi: chi conosce l'URL scarica senza autenticazione.
- Aggravante: la **landing QR pubblica** (senza login per design) espone proprio quegli URL: `views.py:10162` `open_url = ... or doc.file.url` dentro `_render_asset_qr_landing`, raggiungibile da `asset_qr_public_landing` (`views.py:10078`). Un visitatore anonimo con il QR di una macchina riceve link diretti ai documenti (SPECIFICHE/INTERVENTI/MANUALI) in webroot.
- Il rimedio è già stato costruito due volte nel progetto: storage privato cifrato con fallback legacy (`assets/storage.py:13-76` + migrazione `0060` + command `migrate_admin_deadline_attachments_private.py`) e il deny IIS di `media/tickets`.

**Proposta (P0, effort medio):** (a) aggiungere subito il deny IIS per `media/assets_documents` e `media/assets_workorders` (modifica al template web.config, come tickets); (b) sulla QR landing pubblica passare da `doc.file.url` alla route protetta `assets:asset_document_download` (che per i visitatori anonimi → login) o omettere i documenti locali quando `qr_public=True`; (c) in seconda battuta, migrare i due FileField a uno storage privato riusando il pattern 0060. Nota deploy: la modifica web.config deve arrivare anche su `release/prod`.

### 1.3 S3 · ALTA — Azioni di scrittura gate-ate dal solo login (incoerenza interna)

Nel POST dispatcher di `asset_list` **tutte** le azioni amministrative verificano `can_manage_custom_fields = _is_assets_admin(request)` (`views.py:8406`, poi 8436, 8446, 8456, 8466, 8476, 8486, 8496, 8506)… **tranne** `import_excel` (`views.py:8428-8434`): qualsiasi utente autenticato può caricare un Excel che con `update_existing` default a `1` (`views.py:8256`) **crea e sovrascrive asset reali** via `call_command("import_assets_excel")`. Vista la simmetria con le altre azioni, sembra una svista, non una scelta.

Altri punti con lo stesso pattern:
- `asset_bulk_update` (`views.py:17139-17201`): endpoint JSON solo login che consente a chiunque autenticato di modificare in blocco `status`, `asset_category_id`, `notes`, assegnazioni di **qualunque** asset. Whitelist campi ben fatta (17156-17161) ma nessun check admin e **nessun audit log**.
- `asset_detail` POST `upload_asset_documents` / `delete_asset_document` (`views.py:9099-9157`): upload e **cancellazione** documenti (anche dal record SharePoint) per qualsiasi utente autenticato; la sola azione `add_asset_document_folder` è protetta (`views.py:9159`).
- `assignment_set`, `workorder_close`, `workorder_checklist_*`, `asset_meter_update`: solo login. Per l'operatività d'officina può essere una scelta ("ogni operatore registra"), ma va **dichiarata**; oggi convive con azioni gemelle admin-only senza criterio visibile.

**Proposta (P0 per import_excel e bulk_update, P1 per i documenti):** allineare al check admin/`user_can_modulo_action("assets", "admin_assets")`; audit log su bulk_update (oggi assente). Le route sono censite nei pulsanti ACL legacy (`acl_bootstrap.py:42` per bulk-update) ma il gate in-code manca: con ACL v2 strict la copertura dipende dai binding a DB — da verificare con `acl_fallback_report --only-unbound`.

### 1.4 S4 · MEDIA — Audit di `asset_meter_update` rotto (firma sbagliata)

`views.py:15326-15332` chiama `log_action(request.user, "asset_meter_update", f"Contatore ...", asset)`, ma la firma è `log_action(request, azione, modulo, dettaglio)` (`core/audit.py:13`). Il primo argomento è un `User` (non ha `.user`), il modulo è una stringa descrittiva e il dettaglio è un oggetto `Asset`: essendo fire-and-forget ("eventuali errori DB sono loggati ma non propagati", `core/audit.py:16`), **l'audit dell'aggiornamento contatori si perde in silenzio** — proprio il dato che pilota la generazione di OdL a soglia. Fix da una riga; aggiungere un test che verifichi la riga di AuditLog (senza `count()` globale — trappola nota).

### 1.5 S5 · MEDIA — API JSON non censite nel gate ACL

`API_ACL_GATE_PATHS` (`core/middleware.py:17-27`) non contiene i path assets: `/api/assets/dashboard/config/` (`urls.py:126`), `/api/assets/calendario/json/` (127-130), `/assets/bulk-update/`. Regola di progetto (memoria + CLAUDE.md): endpoint API/AJAX protetti devono rispondere JSON 401/403 e ogni route API va nel gate o la strict-mode la nega. Da verificare in test config con `ACL_STRICT_CANONICAL=True`: o si mappano, o si documenta perché sono esenti.

### 1.6 S6 · BASSA — Export integrali a ogni utente autenticato

`asset_list_export` (`views.py:13319`), `workorder_list_export` (13393), `work_machine_export_*` (13425, 13479), `asset_detail_export_xlsx` (16476): l'inventario completo con assegnatari, seriali, reparti esce in xlsx per chiunque abbia un login. Non è dato personale sensibile, ma è la fotografia completa del parco aziendale: valutare il gate `assets` di modulo (le route sono già pulsanti ACL: `acl_bootstrap.py`).

**Aspetti positivi (sicurezza)** da preservare: validazione upload centralizzata estensione+MIME+size (`views.py:3165-3172`), sanitizzazione nomi/percorsi SharePoint (2341-2427), token QR opachi uuid4 con flag di abilitazione (`models.py:157-158`), landing pubblica volutamente read-only con shell separata (`views.py:10198-10203`), storage privato **cifrato** per gli allegati scadenze con `url()` che solleva `NotImplementedError` (`storage.py:73-76`), audit sui download/delete documenti.

### 1.7 C1 · ALTA — Drift generatore ↔ scadenzario sulla registrazione esecuzioni

- La registrazione di un'esecuzione dallo scadenzario (`maintenance_schedule` POST, `views.py:11898-11911`) crea l'OdL via `_build_execution_workorder` (`views.py:3285-3322`), che **non imposta `origin`** → resta il default `ORIGIN_MANUAL` (`models.py:1878-1884`).
- Il generatore automatico (`generate_scheduled_workorders.py:140-163`) calcola la prossima scadenza a giorni **solo** dagli OdL `origin=ORIGIN_PERIODIC` chiusi; se non ne trova, `next_due = today`.
- Conseguenza attesa: registro oggi un'esecuzione manuale (lo scadenzario si aggiorna correttamente, perché legge `AssetMaintenanceRuleState` via `sync_workorder_maintenance_state`, `views.py:11911`), ma il run delle 06:00 di domani non la vede e **genera comunque un OdL periodico** per la stessa coppia (asset, regola). Due fonti di verità diverse per la stessa domanda "quando è stata fatta l'ultima volta?": `AssetMaintenanceRuleState.last_execution_date` per la UI, "ultimo WO periodico DONE" per il generatore.

**Proposta (P0, effort basso):** far leggere al generatore lo stesso `AssetMaintenanceRuleState` usato dallo scadenzario (o, minimale, togliere il filtro `origin=PERIODIC` dalla query dell'ultimo WO DONE con quella regola). Aggiungere un test: registra esecuzione → run generatore → nessun OdL creato. *(Da confermare con un test prima del fix: l'analisi è statica.)*

### 1.8 C2 · MEDIA — Generatore idempotente solo dentro il singolo processo

L'anti-duplicazione è il set in memoria `open_periodic_pairs` caricato a inizio run (`generate_scheduled_workorders.py:86-91`, aggiornato a 232). Due esecuzioni concorrenti (task django-q `run_generate_scheduled_workorders` + lancio manuale del command, o doppio schedule) possono creare OdL duplicati: nessun vincolo DB impedisce due `WorkOrder` OPEN/PERIODIC per la stessa coppia. **Proposta (P1):** lock applicativo (cache lock) o constraint condizionale (`UniqueConstraint(fields=["asset","maintenance_rule"], condition=Q(status="OPEN", origin="PERIODIC"))` — supportato da mssql-django? in alternativa `get_or_create` su chiave `reference_batch`). Nota N+1: nonostante i precaricamenti, restano 1-2 query per coppia (asset, regola) (`_get_override`:253-259 e la query last_wo per ciascuna coppia) — accettabile oggi, da tenere d'occhio.

### 1.9 C3 · MEDIA — `WorkOrder.close()`: non atomico, richiudibile, con `except: pass`

`models.py:1986-2078`: (a) nessuna `transaction.atomic` attorno a save + effetti collaterali; (b) nessun guard sullo stato: due tab (o un doppio submit) richiudono un OdL già DONE riscrivendo `closed_at`/costi — la view `workorder_close` (`views.py:15193`) non verifica `status == OPEN`; (c) il blocco P1.3 che aggiorna `WorkMachine.next_maintenance_date` termina con `except Exception: pass` (`models.py:2077-2078`) — in contrasto con la regola di progetto "log prima del pass" (ANALISI_01 F13). **Proposta (P1):** guard `if self.status != STATUS_OPEN: raise ValidationError`, `transaction.atomic` nella view attorno a close+sync+allegati+log, e almeno `logger.exception` al posto del `pass`.

### 1.10 C4/C5/C6 · BASSE — Concorrenza minore

- `AssetMeter.update_value` (`models.py:2277-2287`): read-modify-write senza lock; due aggiornamenti simultanei producono history incrociata. Manca inoltre qualsiasi validazione di **monotonia**: per ore/cicli un valore che scende è quasi sempre un refuso (il modulo contatori ha `controllo_monotonia`, qui nulla) e sposta lo stato dello scadenzario a soglia. Proposta: warning non bloccante in `asset_meter_update` se `new_value < current_value`.
- `workorder_claim` (`views.py:15180-15181`): ultimo che clicca vince. Fix atomico: `WorkOrder.objects.filter(pk=id, assigned_to__isnull=True).update(assigned_to=...)` + messaggio "già preso in carico da X".
- `_generate_asset_tag` (`models.py:139-152`): scan di **tutte** le tag del prefisso a ogni creazione + retry su IntegrityError. Corretto ma O(N); con l'inventario che cresce conviene una sequenza per prefisso (tabella contatori o MAX SQL con lock).

### 1.11 D1 · MEDIA — `Asset.status` senza macchina a stati né traccia

`models.py:49-58`: 4 stati liberi, nessuna validazione di transizione (IN_USE→RETIRED→IN_USE senza vincoli), nessun timestamp/log del cambio (il `bulk_update` li cambia in massa senza audit, vedi S3). Il generatore filtra correttamente `STATUS_IN_USE` (`generate_scheduled_workorders.py:108`), ma un asset RETIRED resta assegnabile a OdL manuali e conserva scadenze attive. **Proposta (P2):** non serve una FSM completa; bastano (a) log del cambio stato (riusare `log_action`), (b) side-effect esplicito su RETIRED (chiudi/disattiva scadenze e verifiche collegate, o almeno warning in UI), (c) vincolo soft in `WorkOrderForm` su asset dismessi.

### 1.12 D2 — Dipendenze del refactor fusione tipo/categoria (coordinamento, nessuna proposta)

La direzione è già codificata: `asset_type` derivato da `AssetCategory.base_asset_type` (`realign_asset_types.py:1-28`, euristica condivisa in `services/asset_catalog_import.classify_asset_type`). Punti che il refactor in corso deve considerare (censimento, **da non toccare in questa linea**):

- `Asset._asset_tag_prefix` (`models.py:117-137`): il prefisso della tag deriva da `asset_type` — cambiare la sorgente cambia le tag generate.
- `AssetListLayout.context_key` e `_asset_list_context(asset_type)` (`views.py:7886-7906`): i contesti lista sono keyed su tipo.
- `AssetDetailField.asset_scope` (SCOPE_WORK_MACHINE, `models.py:400-407`) e `AssetLabelTemplate.scope/asset_type` (`models.py:1594-1625`).
- Sidebar `active_match` con substring `asset_type=SERVER` (`models.py:617-622`, seed in `_default_sidebar_seed_rows`).
- Il redirect `asset_create → work_machine_create` su `asset_type=WORK_MACHINE` (`views.py:10251-10252`) e `asset_edit` (10299-10300).
- Filtri export (`_apply_asset_export_filters`, `views.py:13262`) e dispositivi IT (`device_list`).

### 1.13 D3 · MEDIA — `next_maintenance_date` denormalizzato su WorkMachine

`WorkMachine.next_maintenance_date` (`models.py:1328`) è aggiornato solo dalla chiusura OdL per regole a **giorni** (`models.py:2062-2078`, best-effort con `except: pass`) e manualmente dal form. Le dashboard macchine lo usano come fonte, ma per regole a contatore non viene mai toccato → può divergere dallo scadenzario vero (`build_maintenance_schedule_rows`). Coerente con la trappola di progetto sui campi denormalizzati. **Proposta (P2):** o si ricava sempre dal motore scadenzario (campo → property/annotazione) o si documenta il campo come "solo promemoria manuale".

### 1.14 D4 · BASSA — AssetMeter vs modulo `contatori`: due sistemi, ma non lo stesso dominio

Confermata la fotografia di MIGLIORAMENTI_CONTATORI_HUB (P2-5): esistono due sistemi "contatori" paralleli, ma la sovrapposizione è **concettuale, non funzionale**:

- `contatori.Macchina/LetturaContatori` (`contatori/models.py:9-80`): fotocopiatrici MFC Canon, 4 contatori pagine, ciclo trimestrale, riconciliazione fatture, SNMP.
- `assets.AssetMeter/AssetMeterHistory` (`models.py:2231-2313`): ore/km/cicli per trigger manutenzione, aggiornamento manuale HTMX.

Fonderli sarebbe sovraingegneria: semantiche, frequenze e consumatori diversi. La convergenza giusta è quella già in atto: l'`Asset` come punto di join (`contatori.Macchina.asset` FK, `contatori/models.py:40-46`). Unico miglioramento a basso costo (P2): mostrare nella scheda asset di una MFC collegata l'ultima lettura del modulo contatori (sola lettura), così la scheda asset resta il punto unico di consultazione.

### 1.15 F11 — Monolite `views.py`: verificato, in crescita; piano di scomposizione realistico

Verifica di ANALISI_01: allora 17.394 righe/373 funzioni; oggi ~17.6k fisiche/**~448 funzioni**. Il refactor manutenzione ha estratto bene `maintenance.py` (563 righe, pura logica testabile) e `services/` — la strada è dimostrata, va percorsa fino in fondo. Funzioni oltre ogni soglia ragionevole:

- `asset_detail` ~830 righe (`views.py:9079-9908`) — dispatcher POST documenti + costruzione di ~10 sezioni.
- `maintenance_schedule` ~545 (`views.py:11783-12327`) — lista + 3 flussi POST di registrazione esecuzione.
- `asset_list` ~449 (`views.py:8404-8853`) — dispatcher di 10 action POST admin + filtri + layout colonne.
- `periodic_verification_list` ~444 (13733), `gestione_admin` ~360 (16779), `maintenance_hub` ~355 (15497), `assistance_contract_list` ~311 (12328), `software_license_list` ~295 (12639).

Scomposizione per domini **senza toccare le URL** (i blocchi sono già contigui nel file, segno che i domini esistono):

| Modulo proposto | Contenuto (righe attuali) | Peso |
|---|---|---|
| `services/sharepoint.py` | helper Graph/SharePoint `views.py:2233-3100` (30+ funzioni autonome, zero request) | ~900 |
| `views/documents.py` | download/upload/delete documenti 3011-3230 + azioni doc di asset_detail | ~400 |
| `views/labels_reports.py` | label designer, QR, PDF report 559-2230, 9908-10250, 16200-16780 | ~2.500 |
| `views/admin_config.py` | gli `_handle_*_request` + seed sidebar/detail-field/layout 4400-7810 | ~3.400 |
| `views/maintenance.py` | template/regole/override/schedule/hub 11062-12330, 14628-16200 | ~2.900 |
| `views/inventory.py` | asset_list/device/work_machine/export 7813-8860, 12933-13590 | ~1.500 |
| `views/calendar.py` | eventi Outlook/calendario 3866-4410, 17439-17600 | ~700 |

Nota dimensionante: quasi **metà** del file è il "configuratore UI da DB" (sidebar, detail field, layout liste, header tool, action button — 7 modelli di configurazione). È il primo candidato all'estrazione perché è autocontenuto e cambia raramente. Effort alto ma abilitante (merge-conflict e blast-radius sono il costo ricorrente oggi, con più sessioni parallele sul repo).

**Coupling** (fotografia): `Asset` è l'hub di 12+ app — `tickets` (FK `WorkOrder.ticket`, `models.py:1867`), `tasks`, `contatori`, `gestione_carichi_macchina` (`Macchina` OneToOne→Asset, `gestione_carichi_macchina/models.py:61`), `security`, `schede_sicurezza`, `rilevazione_incidenti`, `ai_assistant`, `dashboard`, `timbri`, `anagrafica`. La direzione è sana (gli altri puntano ad assets; assets importa da anagrafica `Fornitore` e dipendenti via `_anagrafica_employee_options` `views.py:1499`, e da tickets dentro le funzioni, pattern lazy corretto). Qualunque rinomina/spostamento di `Asset`/`AssetCategory` durante il refactor fusione ha blast-radius su tutte queste app.

---

## 2. FRUIBILITÀ

### 2.1 Chi lo usa e per cosa

Tre popolazioni con flussi distinti e ben riconoscibili nel codice: **manutenzione/officina** (macchine, OdL, scadenzario, QR sulle macchine, checklist), **IT** (dispositivi, endpoint di rete, licenze software, dettagli sicurezza `AssetITDetails`), **qualità/amministrazione** (scadenze amministrative con allegati, contratti assistenza, budget per categoria AS3, report PDF mensili). La sidebar per categorie e i contesti lista separano bene i mondi.

### 2.2 Scadenzario: c'è davvero, ed è la parte migliore del modulo

Non è "solo liste": `maintenance_schedule` ("Prossime manutenzioni") è uno scadenzario unico che fonde regole a giorni **e a contatore** con lo stesso motore usato dal generatore automatico (`maintenance.py:316-373` — il commento dice esplicitamente "così ciò che si vede coincida con ciò che viene generato": principio giusto, minato solo dal bug C1). Il Centro Manutenzione (`maintenance_hub`, `views.py:15496-15851`) è un cockpit "Da fare" con KPI cliccabili, OdL scaduti >21gg separati, e — dettaglio ben pensato — i **non-admin vedono solo i propri interventi** (`views.py:15536-15537`). Stati chiari a 4 livelli (scaduta/in scadenza/pianificata/da pianificare) con etichette parlanti ("Scaduta da N gg").

Punti deboli:
- **Tre ingressi sovrapposti** (U2): hub "Da fare", "Prossime", "Calendario asset" (+ dashboard widget). I redirect dai vecchi URL sono gestiti (`views.py:15517-15523` — bene), ma un utente nuovo non sa quale sia "il" posto. Basterebbe una riga di orientamento in testa a ciascuna pagina ("Questo è il cockpit operativo; lo scadenzario completo è in Prossime").
- **Liste ancora separate** (U3): scadenze amministrative (`asset_administrative_deadline_list`) e verifiche periodiche legacy hanno pagine proprie; licenze e contratti hanno le scadenze solo dentro le rispettive liste. Il calendario le aggrega, la vista tabellare no.
- Le verifiche legacy sono correttamente marcate `is_legacy` ed escluse dai conteggi (`models.py:1365-1373`, `views.py:15578-15585`) — migrazione in corso pulita; completarla per eliminare il doppio concetto.

### 2.3 Onboarding di un nuovo asset: un form solo, ben guidato

`asset_create` (`views.py:10250-10291`): form unico con campi dinamici per categoria (gruppi `category_field_groups`), suggerimenti sui campi a lista, tag generata automaticamente, QR token automatico, opzioni "crea cartella SharePoint" e "aggiungi in planimetria" nello stesso passaggio; redirect automatico al form macchine per le work machine. Le regole di manutenzione si **ereditano dalla categoria** senza passi aggiuntivi (ottimo). L'indicatore di completezza scheda (`Asset.completeness`, `models.py:186-236`) dice cosa manca. Unico buco reale: se la categoria ha regole a contatore, nessuno ti dice che devi creare l'`AssetMeter` — lo scopri dallo stato "Contatore mancante" nello scadenzario (`maintenance.py:331-340`). Proposta piccola (P2): hint nel form/dettaglio "questa categoria ha regole a ore/km: aggiungi il contatore".

### 2.4 Ergonomia officina: sopra la media

QR landing pubblica per tecnici/ispettori esterni senza login (`views.py:10078`, sola lettura, con scadenze azionabili e link "registra intervento" dietro login), segnalazione rapida per operatori (`asset_quick_report`, `views.py:15355`, crea ticket MAN precompilato), "prendi in carico" a un click (`workorder_claim`), checklist HTMX con toggle (`workorder_checklist_toggle`), aggiornamento contatore inline HTMX (`asset_meter_update`). È il modulo giusto da cui copiare per gli altri. Resta da verificare la resa **tablet/mobile** delle tabelle dense (hub e scadenzario) — coerente con l'audit responsività di portale già in memoria.

---

## 3. OPPORTUNITÀ AI

Contesto: esiste già il tool `assets_summary` nell'assistente HUB (`ai_assistant/tools.py:93-100`) con routing semantico e keyword dedicate (`_ASSET_KEYWORDS`, righe 339+). Ollama on-prem su 10.0.0.34, pipeline RAG bge-m3/TEI già in produzione per il SGI.

### A1 · Valore ALTO — Riepilogo storico interventi per asset (tool-live, non RAG)

Il dato c'è ed è testo libero accumulato: `WorkOrder.description/resolution/notes` + costi + downtime + `WorkOrderLog`. I casi d'uso reali: il manutentore che prende in carico un OdL ("cosa è stato fatto su questa macchina negli ultimi 2 anni? problemi ricorrenti?") e il responsabile che valuta una sostituzione ("quanto ci è costata questa macchina in fermi e interventi?"). Un riassunto LLM on-demand nel dettaglio asset (sezione manutenzione) o nella pagina di presa in carico, alimentato **solo** da query live sul DB (pattern già codificato nel guardrail skill-matrix: fonti tool-live, mai RAG per dati operativi), con fallback grazioso se Ollama è giù. Effort medio: il tool `assets_summary` è la base da estendere con il drill-down per singolo asset.

### A2 · Valore MEDIO — RAG sui manuali asset

`AssetDocument` categoria MANUALI (+ cartelle SharePoint) contiene i manuali macchina. Domande da officina ("coppia di serraggio del mandrino", "significato allarme E-123") oggi = sfogliare PDF. La pipeline RAG esiste già (SGI); l'estensione è indicizzare i manuali con metadato asset/categoria e rispondere con citazione del documento. Condizioni di valore: PDF testuali (non scansioni), e risposta **sempre** con link al documento (il manuale resta la fonte). Effort medio; da fare **dopo** S2 (non ha senso indicizzare documenti la cui esposizione non è ancora sanata).

### A3 — Dove l'AI NON serve (esplicitamente)

- **Manutenzione predittiva da storico OdL**: no. Gli OdL preventivi sono generati da regole (quindi lo "storico" riflette le regole stesse, non i guasti), i correttivi sono pochi per asset, e i contatori sono aggiornati a mano con frequenza irregolare. Qualsiasi modello — LLM o ML — qui produrrebbe numeri d'apparenza. Se serve un indicatore, un MTBF/costo-per-anno calcolato in SQL è più onesto e già alla portata di `reports_dashboard`.
- **Suggerimento categoria/tipo da descrizione libera**: no. Il catalogo categorie è piccolo e navigabile a dropdown, e l'euristica keyword esiste già dove serve (import massivo: `classify_asset_type` in `services/asset_catalog_import.py`, riusata da `realign_asset_types`). Un LLM aggiungerebbe latenza e non-determinismo a un problema risolto.
- **Chatbot dentro il modulo**: no. L'assistente HUB centrale instrada già le domande asset (`_wants_asset_context`, `ai_assistant/tools.py:834`); duplicare la superficie conversazionale nel modulo moltiplicherebbe i punti di manutenzione del routing.

---

## 4. UI

### 4.1 U1 · MEDIA — Dark mode: il debito più grande e misurabile del modulo

Numeri (grep sui template del modulo):
- **2.416** colori hex hardcoded in **50** template.
- Il tema scuro è realizzato con **942** regole di override `body.theme-dark ...` distribuite in soli **24** file: il light theme è hardcoded e il dark è una patch per-selettore (es. `base_shell.html:267-280`).
- **~26 pagine** hanno colori hardcoded e **zero** override dark: tra le più usate `asset_admin_deadline_list` (39 hex), `assistance_contract_list` (20), `software_license_list` (17), `maintenance_rule_list` (19), `asset_form` (12), `asset_label_designer` (28), `plant_layout_editor` (36), `reports_dashboard` (30) e tutte le pagine report. In dark mode queste pagine restano chiare o miste.

È lo stesso problema già diagnosticato in formazione. Rimedio incrementale (P1, per pagina): sostituire gli hex con i token di `theme.css` ricordando la trappola nota che `--surface-alt`/`--thead-bg`/`--tbody-hover` esistono **solo** in `body.theme-dark` (usare sempre `var(--token, fallback)`). Ogni pagina migrata elimina il proprio blocco di override. Non riscrivere il layout: il microsistema `as-`/`ad-` funziona, è solo il **colore** a dover diventare token.

### 4.2 Chiarezza delle viste principali: buona, con eccezioni

- **Dashboard asset** (`asset_dashboard.html`): widget drag&drop personalizzabili per utente (`AssetDashboardConfig`), KPI cliccabili che portano alle liste filtrate, stati colorati semantici (ok/warn/danger). Allineata al pattern KPI del portale.
- **Lista asset**: colonne configurabili per contesto + layout per utente, suggerimenti, endpoint summary. Densa ma coerente. Attenzione: il POST dispatcher da 10 azioni la rende anche "pannello admin" — la scomposizione F11 aiuterà anche la UX (pagina admin separata).
- **Dettaglio asset**: sezioni interamente configurabili da DB (`AssetDetailSectionLayout`, `AssetDetailField`) — potente ma è anche il motivo delle ~830 righe di view; la resa dipende dalla qualità della configurazione a DB, il che rende il comportamento difficile da prevedere tra installazioni.
- **Scadenzario/hub**: vedi §2.2 — le viste sono chiare; l'unica confusione è *quale* vista usare.

### 4.3 Coerenza col design system del portale

Il modulo usa una shell propria (`base_shell.html:1` estende `core/base.html` ma ridefinisce sidebar, card, badge, form con prefisso `as-`) invece dei token/componenti `hub-` usati in anagrafica. Non è un difetto da sanare con una riscrittura (regola di progetto: preservare il tema, riusare i token): la convergenza pragmatica è (a) colori → token (U1), (b) raggi/spaziature allineati ai valori del tema dove già coincidono, (c) nessun nuovo microsistema per le pagine future — usare `hub-`.

### 4.4 Ergonomia reparto/officina

Le pagine operative (hub, QR landing, quick report, checklist) hanno target click generosi e azioni primarie evidenti. Le tabelle dello scadenzario e delle liste sono pensate per desktop: su tablet da officina servono min-width + scroll orizzontale controllato (verificare, fa parte dell'audit responsive di portale). La QR landing pubblica è la pagina giusta per il muletto/telefono: leggera, senza shell, azioni essenziali.

---

## Proposte prioritizzate

**P0 — subito (sicurezza + correttezza, effort basso/medio):**
1. S1 — gate per-oggetto/admin su `asset_document_download` + log del diniego (views.py:3102). *Quick win identico a quanto già suggerito in ANALISI_01.*
2. S3 — check admin su `import_excel` (views.py:8428) e `asset_bulk_update` (views.py:17139) + audit log sul bulk.
3. S2(a,b) — deny IIS su `media/assets_documents` e `media/assets_workorders` (web.config template) e via `doc.file.url` dalla QR landing pubblica (views.py:10162). Ricordare `release/prod`.
4. C1 — allineare il generatore allo stato scadenzario (generate_scheduled_workorders.py:140-163) con test di non-rigenerazione.
5. S4 — fix firma `log_action` in `asset_meter_update` (views.py:15326).

**P1 — a seguire:**
6. S2(c) — migrazione `AssetDocument`/`WorkOrderAttachment` a storage privato (riusare pattern 0060 + command di migrazione).
7. C2/C3 — lock o vincolo condizionale sul generatore; guard doppia chiusura + atomic + log del `pass` in `WorkOrder.close()`.
8. S5 — censire le API assets nel gate ACL / verificare strict-mode; `acl_fallback_report --only-unbound` sulle route di scrittura.
9. U1 — migrazione colori→token a pagine, partendo dalle 26 senza override dark (prima le più usate: scadenze amministrative, licenze, contratti).
10. S3(b) — decidere e dichiarare il modello autorizzativo delle azioni operative (upload/delete documenti, close, claim): "tutti gli operatori" o ruolo manutentore.

**P2 — pianificati:**
11. F11 — scomposizione incrementale di views.py per domini (ordine suggerito: `services/sharepoint.py` → `views/admin_config.py` → `views/maintenance.py`), senza cambiare URL. Da sequenziare **dopo** la fusione tipo/categoria per non creare conflitti.
12. D1/D3 — log cambio stato asset + side-effect su RETIRED; chiarire la natura di `WorkMachine.next_maintenance_date`.
13. A1 — riepilogo AI storico interventi (estensione tool-live di `assets_summary`); poi A2 (RAG manuali) dopo la bonifica S2.
14. C4/C5/C6 — monotonia contatori (warning), claim atomico, sequenza tag.
15. D4 — lettura MFC del modulo contatori in sola lettura nella scheda asset collegata.

---

*Fonti principali: `django_app/assets/{models,views,forms,urls,storage,maintenance,tasks,acl_bootstrap}.py`, `services/`, `management/commands/`, template `assets/`, `core/{audit,middleware}.py`, `deployment/config/web.config.httpplatform.template`, `contatori/models.py`, `gestione_carichi_macchina/models.py`, `ai_assistant/tools.py`. Righe citate verificate al commit corrente di `main` (working tree condiviso, non modificato).*
