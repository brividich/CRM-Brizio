# `core` — fondamenta del portale

Area **Core** · URL — (`/capa/`) · codice [`django_app/core/`](../../django_app/core/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Middleware ACL, navigation registry, auth backends, audit, notifiche, export, ricerca globale, legacy models, **azioni CAPA** correttive/preventive trasversali

## Dettaglio

### Limiti di upload (`core/upload_limits.py`)

Un solo limite per file vale per tutti gli upload di documenti e allegati: assets, anagrafica, anomalie e NC, tickets, tasks, DPI, SDS, diario preposto, RENTRI, fornitori, notizie, sistema di gestione e bacheca. Lo stesso limite vale per l'import dell'archivio HR.

| Variabile `.env` | Default | Effetto |
|---|---|---|
| `UPLOAD_MAX_FILE_MB` | 100 | Dimensione massima del singolo file; i testi «max N MB» nelle pagine la leggono da `upload_max_mb` (context processor `app_meta`). |
| `DATA_UPLOAD_MAX_NUMBER_FILES` | 1000 | File per singolo invio (caricamento di una cartella intera). |

Il tetto sull'intera richiesta lo applica IIS: `maxAllowedContentLength` nel `web.config` (template: 104857600 = 100 MB). Va tenuto >= `UPLOAD_MAX_FILE_MB`, altrimenti IIS risponde 404.13 prima di Django. Il `web.config` di produzione non viene ridistribuito con il pacchetto: va aggiornato a mano sul server.

Restano fuori, con i limiti dedicati: loghi e immagini di branding, foto/planimetrie, import Excel/CSV/JSON, upload anonimi dalla landing QR pubblica (15 MB) e caselle SOC.

L'app trasversale che fa funzionare tutto il resto. Contiene middleware, resolver ACL, legacy models, auth backends, audit trail e context processors.

- **ACL middleware** con resolver canonico v2 + fallback legacy, logging throttled delle decisioni
- **Navigation registry** (`NavigationItem`, `NavigationRoleAccess`, `UserNavigationOverride`) con visibilita derivata dai permission code canonici e fallback legacy solo per voci ancora non mappate
- **Sidebar a 3° livello (sotto-moduli)**: un modulo della sidebar (es. Anagrafica) si espande in accordion mostrando i propri sotto-moduli. Le voci figlie sono `NavigationItem section='subnav'` con `parent_code` = `code` del modulo topbar, con ACL ereditata dalla stessa compilazione delle subnav; gestibili dal NavBuilder (section subnav + modulo padre). Il click sul nome naviga alla home del modulo, la freccia espande; lo stato attivo si propaga al padre
- **Fallback navigazione legacy** con deduplica visuale per modulo, cosi i restore/import non duplicano in sidebar le azioni `pulsanti` dello stesso modulo
- **Restore navigazione controllato** con `restore_navigation_registry`: dry-run di default, backup snapshot in apply e ripristino solo di categorie/menu/fallback ruoli da `fixtures/nav_acl_snapshot.json`
- **4 auth backend in cascata**: `AxesStandaloneBackend` → `SQLServerLegacyBackend` → `LDAPBackend` → `ModelBackend`
- **Header delle superfici pubbliche** (`core.public_headers`): le rotte fuori dal perimetro autenticato (`MIDDLEWARE_EXEMPT_PREFIXES`) si decorano con `@risposta_pubblica`, che aggiunge `X-Robots-Tag: noindex, nofollow, noarchive`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff` e `Cache-Control: no-store`. Sulle tre rotte **a token** (approvazioni automazioni, proxy Entra, azioni via mail sulle anomalie) `no-referrer` evita che il token nell'URL viaggi nell'header `Referer`
- **Audit trail** fire-and-forget via `core.audit.log_action()` su tabella `AuditLog`, con **aggancio opzionale al record** (`oggetto=<istanza>`, oppure `oggetto_tipo`/`oggetto_id` per le tabelle legacy senza modello Django): `core.audit.storico_oggetto()` ne ricava lo **storico modifiche del singolo record**, reso dal partial `core/components/_storico_modifiche.html`. Agganciarlo a una scheda costa due righe (kwarg nella `log_action` + include nel template); già attivo sulle scadenze amministrative degli asset, visibile in fondo a `/assets/<id>/`
- **Centro notifiche** unificato con campanella, badge, pannello HTMX, popup live in-app via polling leggero e sorgenti scadenze asset/DPI/SLA ticket
- **Pagina `/notifiche/`**: viste Attive / Da leggere / Archiviate con contatori, filtro per categoria, ricerca nel testo, paginazione; per notifica «Apri» (la segna letta, come da campanella/banner/popup), «✓ Letta», «Archivia» / «Ripristina» e data di archiviazione automatica; «Archivia le lette» in blocco. API: `api/notifiche/<id>/leggi`, `api/notifiche/<id>/archivia` (`?azione=ripristina`), `api/notifiche/archivia-lette/`
- **Archiviazione automatica** (`core/notifiche_archivio.py`, punto unico): ogni notte alle 02:30 (schedule `notifiche_archivio`) archivia le non lette da 30 giorni e le lette da 14 (data `letta_il`, fallback `created_at`), elimina le archiviate da 365. Soglie in SiteConfig `notif_archivio_non_lette_giorni` / `_lette_giorni` / `_elimina_giorni` (0 = mai), gestite da Admin → Gestione notifiche. Comando `archivia_notifiche [--dry-run]`. Le query di badge/non lette devono filtrare `archiviata=False`; i dedup dei promemoria dei moduli (su `letta=False`) contano anche le archiviate, di proposito
- **Canali delle notifiche** (`/notifiche/impostazioni/`, rotta ACL-shared: solo i dati dell'utente collegato): per ogni categoria «Portale» (campanella, `UserOnboarding.notifiche_config`) e «Push» (`NotificaCanali.push_categorie`, spuntabile solo con la categoria accesa); «Riepilogo scadenze via mail» (`NotificaCanali.digest_scadenze`, 7 o 30 giorni). Migrazione `core` 0083 (`NotificaCanali`, `PushIscrizione`).
- **Notifiche push su telefono e PC** (`core/push.py`, `core/views_push.py`): Web Push con firma VAPID ES256 fatta con `cryptography`, nessuna dipendenza nuova. Il segnale parte **senza contenuto**; il service worker `/sw-notifiche.js` legge il testo da `api/notifiche/push/ultime/` con la sessione dell'utente, che non segna niente come letto. Dal servizio push non passa nessun dato personale. Gli endpoint sono accettati solo verso i servizi push noti (FCM, Mozilla, WNS, Apple; anti-SSRF), al massimo 10 dispositivi per utente. Un'iscrizione si disattiva da sola su 404/410 o dopo 5 errori di fila. L'invio parte da `invia_notifica` (`push.notifica_creata`) ed è accodato su django-q (`core.push.task_push_utente`). API: `api/notifiche/push/iscrizione/`, `revoca/`, `prova/`, `ultime/` (JSON, 401 senza sessione). Configurazione: `VAPID_PRIVATE_KEY` e `VAPID_SUBJECT` nel `.env` (comando `genera_chiavi_vapid [--verifica]`); se la chiave è vuota le push sono spente. Prerequisiti: portale in https e uscita 443 verso i servizi push.
- **Riepilogo scadenze personale** (`dashboard/scadenze_digest.py`, schedule `scadenze_digest_personale` lun-ven 07:30): voci dello Scadenzario globale valutate con i permessi del destinatario. Niente mail se non c'è niente, al massimo una al giorno; destinatario `email_notifica` dell'anagrafica, altrimenti l'email dell'account.
- **Audit sigillato** (`core/audit_sigilli.py`, modello `AuditSigillo`, migrazione `core` 0086): un sigillo per mese concluso con `hash_righe` (SHA-256 delle righe in JSON canonico, ordine id), `hash_precedente` e `hash_sigillo` (catena). Copre le azioni esplicite (`azione` non `auto_*`): le righe tecniche restano a `audit_archive`. Schedule `audit_sigilli` (giorni 1 e 2 alle 03:40): sigilla, verifica tutta la catena (`mail_admins` se rotta), esporta su SharePoint `audit-AAAA-MM.jsonl.gz` + `audit-AAAA-MM.sigillo.json` (`core/sharepoint_upload.py`, `conflictBehavior=fail`, upload a sessione oltre 4 MB) nella cartella di SiteConfig `audit_export_sp_drive_id` / `audit_export_sp_cartella`. Comando `audit_sigilli [--sigilla] [--verifica] [--esporta] [--file AAAA-MM --out DIR]`. Mesi oltre la soglia dell'archiviazione business: «in archivio». **Destinazione dell'export** dal link della cartella: `audit_sigilli --cartella-sharepoint "<link>"` (barra degli indirizzi o «Copia collegamento»; risolto con l'API `/shares` di Graph, prova di scrittura con `LEGGIMI-portale-audit.txt`, poi SiteConfig `audit_export_sp_*`).
- **CAPA — Azioni Correttive/Preventive** (`/capa/`): modello trasversale `ActionItem` collegato a un evento di origine (incidente/anomalia/audit, schema `source_code`+`source_pk`), workflow **APERTA → IN_CORSO → CHIUSA (con evidenza) → VERIFICATA** con chiusura ed efficacia separate (quattro occhi). Lista filtrabile + export CSV/XLSX, gating fail-closed (gestore `core.capa_manage` vs responsabile assegnato), pannello "Azioni collegate" embeddabile nei detail (già nel dettaglio incidente), alimenta lo Scadenzario Globale e il Centro notifiche; sorgente automazioni `core_actionitem` con trigger SQL
- **Export riusabile CSV/XLSX** con `core.exporting.ExportMixin` e helper per liste filtrate
- **Legacy models managed** su SQL Server: `Ruolo`, `UtenteLegacy`, `AnagraficaDipendente`, `Pulsante`, `Permesso`
- **Impersonation** admin → utente con middleware dedicato e session key
- **23 modelli Django** (Profile, AuditLog, SiteConfig, Notifica, Checklist*, OptioneConfig, ecc.)
- **Ricerca unificata** Ctrl+K (o barra «Cerca o vai a…» in topnav): pagine recenti, salto a qualsiasi pagina di navigazione (ACL-filtrata) e ricerca dati su 7 sorgenti (dipendenti, asset, ticket, progetti, task, procedure, DPI), con modulo e preview risultato
- **Topnav**: voci in eccesso raccolte in «Altro», hamburger da ≤1100px, menu utente (profilo, preferenze, tema chiaro/scuro, segnala problema, esci), approvazioni assenze in attesa come «N da approvare». Struttura: Per me · Tickets · Produzione · Persone · Sicurezza e ambiente · Qualità · IT · Suggestion Corner, con sottocategorie da `NavigationItem.group`; si applica con `python manage.py riorganizza_topbar --apply` (dry-run senza `--apply`)
- **Messaggi di conferma subito e uguali in tutti i moduli** (`core/flash_messages.py`, `core/js/hub-flash.js`, `core/css/hub-flash.css`): toast in basso a destra; successo/info spariscono dopo 7 s (pausa al passaggio del mouse), avvisi/errori restano fino alla ×. Messaggi identici raggruppati con «×N», messaggi lunghi riassunti alla prima frase con «Dettagli», al massimo 5 visibili con «+N altri» e «Chiudi tutti», Esc li chiude. Consegna: pagina intera via `{% flash_messages_fallback %}` in `core/base.html`; HTMX/fetch/XHR via header `X-Hub-Flash` (`FlashMessagesDeliveryMiddleware`, dopo `MessageMiddleware`, solo i messaggi della richiesta stessa); download via cookie `hub_flash`. Se la pagina cambia subito dopo un'azione asincrona, il messaggio ricompare nella successiva. I riquadri messaggi propri dei moduli sono stati tolti (restano login e scheda QR pubblica). Regole per sviluppatori: `docs/ai/04_FRONTEND_DIRECTION.md`.

## Schermi 4K (ottobre 2026)

Sopra i 3000px di larghezza (monitor/TV 4K a scala 100%) `theme.css` applica `zoom:1.5` a tutto il portale: la pagina si impagina come su 2560px, contenuto fino a 2280px. Con lo zoom le unità `vh` valgono 1,5 schermi, quindi **nel codice nuovo non usare `Nvh` ma `calc(N * var(--vh, 1vh))`** (`--vh` è definita solo sotto zoom; il fallback `1vh` lascia invariati gli schermi normali). Le unità `vw` vanno bene dentro `min()`/`clamp()`. La barra admin (`.subnav.subnav-wrap`) va a capo sopra i 700px invece di uscire dalla pagina.

## Tema scuro leggibile ovunque (ottobre 2026)

Con il tema scuro capitava di trovare scritte scure su sfondo scuro: colori «chiari» scritti a mano nei template (inline `style="color:#0f172a"` o nei `<style>` di pagina) che il tema non poteva ribaltare. Due rimedi, entrambi solo sotto `body.theme-dark` (il tema chiaro non cambia): `core/static/core/css/dark-safety.css` (generato da `tools/gen_dark_safety.py`) intercetta i colori inline più diffusi e li porta ai token del tema; `tools/gen_dark_block.py` ha accodato a ~250 pagine e CSS di modulo il blocco gemello scuro per le regole che mancavano. Regole per gli sviluppatori: `docs/ai/04_FRONTEND_DIRECTION.md` («Tema scuro»); test di allineamento `core.test_dark_safety`.

## Politica dell'audit automatico (ottobre 2026)

L'audit automatico di insert/update/delete segue `core/audit_policy.py` (versione 1): classe A (default) audit completo; classe B (registri tecnici: `AutomationRunLog`, `AutomationExecution`, `SecurityCveImpact`, `RilevazioneSNMP`…) esclusa, senza listener; classe C (`SecuritySourceFile`, `SecurityMailboxMessage`, `SecurityReport`, `SgiTestoEstratto`) solo metadati e nomi dei campi; classe D (`AutomationRule`, `ManagedFlow`, `DispositivoSNMP`, `SecurityCveRecord`, `Notifica`) senza righe quando cambiano solo campi tecnici. Nessuna riga per update senza modifiche reali, valori oltre 500 caratteri troncati con lunghezza e impronta SHA-256. `log_action` e `login_fallito` invariati. Check `core.W002`/`core.W003` su chiavi e campi della politica.

Comandi:

- `audit_archive` (dry-run `--plan` di default; `--run --archive-dir <UNC>` archivia in `auditlog\<AAAA-MM>\part-*.jsonl.gz` + `manifest.json` verificati e poi pulisce; `--category business --older-than-months 60`; `--restore` in tabella separata; `--prune-archives` oltre 120 mesi).
- `hub_backup_doctor` (solo lettura: capacità del DB rispetto al limite di SQL Express, top tabelle, crescita dell'audit, previsione di saturazione, cache su DB; le sezioni di backup arrivano con il motore di backup).
- `hub_db_tuning --query-store-max-mb 100 [--apply]` (limite del Query Store, dry-run di default; spento resta spento senza `--enable`) e `hub_db_tuning --compatibility-level 170 [--apply]` (dopo la migrazione a SQL Server 2025, vedi [docs/dr/SQL2025_MIGRAZIONE.md](../dr/SQL2025_MIGRAZIONE.md)).

Il monitoring ha il nuovo check `audit_growth` (warning oltre 500 MB/mese, fail sotto 60 giorni dalla saturazione, mai critical). Dettaglio, motivazioni e ordine operativo: [docs/dr/AUDIT_POLICY.md](../dr/AUDIT_POLICY.md).

## Motore di backup verificabile (ottobre 2026)

Package `core/backup_engine/` e comandi `hub_backup` (`full`, `log`, `files`, `host`, `retention`, `all`; exit 0/1/2), `hub_backup_verify`, `hub_backup_set_recovery`, `hub_backup_doctor`; `backup_portale` è un wrapper compatibile. Ogni set ha un manifest con SHA-256, viene verificato (`RESTORE VERIFYONLY`) e copiato con hash controllato su `BACKUP_TARGET` (share del NAS); stato in `status.json` anche a DB spento; retention GFS. Task con `deployment\scripts\register-backup-tasks.ps1`. Dettaglio, impostazioni e ordine di attivazione: [docs/dr/BACKUP_MOTORE.md](../dr/BACKUP_MOTORE.md).

## Recovery Kit e reinstallazione (ottobre 2026)

`hub_recovery_kit export|verify|import` gestisce il kit cifrato con `.env` e certificato HTTPS (passphrase di almeno 5 parole, scrypt + AES-256-GCM, impronte delle chiavi nell'intestazione). `hub_recovery_selfcheck` verifica un ambiente appena ripristinato. La reinstallazione di una macchina nuova si fa con `deployment\scripts\restore-host.ps1` (12 fasi, `-WhatIf`, `-Resume`, report con RTO). Dettaglio: [docs/dr/RECOVERY_KIT.md](../dr/RECOVERY_KIT.md), [docs/dr/RIPRISTINO_HOST.md](../dr/RIPRISTINO_HOST.md).

## Pulizia pre go-live (`pulizia_pre_golive`)

Comando una tantum per partire in produzione senza i log accumulati in sviluppo e collaudo. Dry-run di default (solo conteggi); `--esegui` cancella a batch da 2000 righe e scrive una riga `AuditLog` (`azione=pulizia_pre_golive`) con i numeri; `--solo` accetta i codici separati da virgola.

| Codice | Cosa svuota |
|---|---|
| `run_log` | `AutomationRunLog` e, a cascata, `AutomationActionLog` |
| `coda_automazioni` | `automation_event_queue` con stato `done`/`error` (solo SQL Server; le pending restano) |
| `notifiche` | `Notifica` (campanella, archiviate comprese) |
| `email_anomalie` | `AnomalieEmailLog` |
| `pending_anomalie` | `AnomaliaPendingNotification` già inviate (`notified=True`) |
| `chat_assistente` | `AiConversation` e messaggi dell'assistente AI |
| `chat_security` | `security.AIConversation` e messaggi |
| `ingestion_security` | `SecurityMailboxIngestionRun` concluse |
| `task_django_q` | esiti dei task django-q (non la coda né gli schedule) |
| `sessioni_scadute` | sessioni Django scadute |

Non tocca, per scelta: `AuditLog`, `AclDenialEvent`, log admin Django, Axes, `AnomaliaActionLog`, `WorkOrderLog`, `CandidatoLog`, `TicketStatoLog`, `SgiSyncLog`, `SecurityNotificationLog` (anche fonte del cooldown), audit di configurazione SOC, messaggi di casella usati per la deduplica (approvazioni e SOC), outbox SharePoint delle assenze e tutti i dati di dominio.

Dopo la pulizia, i promemoria in-app ancora validi (anomalie da gestire, RDC da aprire, SLA ticket) ricompaiono al giro successivo dei job: la loro deduplica si basa sulle notifiche non lette e non manda email.

Procedura: backup del DB → `pulizia_pre_golive` (verificare i conteggi) → `pulizia_pre_golive --esegui`. I log su file (`logs\*.log` dell'istanza) si archiviano a parte, con il sito fermo, perché Waitress e il qcluster li tengono aperti.

## Hardening ottobre 2026

- Helper di sicurezza: `core.net.client_ip` (IP client, `X-Forwarded-For` solo da `TRUSTED_PROXY_IPS`), `core.redirects.safe_next` (redirect di ritorno validati sull'host), filtro template `js_json` (`{% load safe_json %}`, dati negli `<script>` senza XSS), `core.private_attachments.PrivateAttachmentStorage` (allegati privati cifrati con lettura dei file storici). In produzione `LEGACY_AUTH_ENABLED=0` blocca l'avvio senza `ACL_DISABLE_ACKNOWLEDGED=1`; DRF ha default espliciti (sessione + utente autenticato).
- Audit 09/10 (Fase 0): l'enrollment TOTP self-service è ammesso solo al primo accesso o dopo un reset admin (`force_setup`), con mail di avviso all'utente; superuser e staff sono soggetti al 2FA anche senza Profile; la sincronizzazione legacy non aggancia più in automatico un superuser/staff senza Profile. `core.download_security.harden_file_response` serve i file caricati con Content-Type dal nome file: inline solo PDF e immagini, il resto come allegato con `nosniff` e `CSP: sandbox`. `seed_acl_uat` non ha più una password fissa (`--password`, `UAT_SEED_PASSWORD` o casuale) e non gira con settings di produzione.
- Audit 09/10 (Fase 1): `core/ldap_conn.py` costruisce le connessioni LDAP con certificato verificato su `ldaps://` (`LDAP_CA_CERT_FILE`) e `receive_timeout` (`LDAP_RECEIVE_TIMEOUT`); `validate_deployment` segnala `ldap://`. Lockout axes per username+IP con IP da `core.net.client_ip`. Il 2FA «solo da rete esterna» tratta come esterne le richieste da `TWOFA_EXTERNAL_HOSTS` (default `*.msappproxy.net`) e `TWOFA_EXTERNAL_PROXY_IPS`. `config.env_config.update_env_file_values` rifiuta a-capo e nomi non validi.
- Audit 09/10 (Fase 2): blocco TOTP per utente con anti-replay e limite ai codici email; allowlist gruppi AD anche al login/SSO (`LDAP_GROUP_ALLOWLIST_ON_LOGIN`); utente disattivato = sessioni chiuse; rotazione della chiave documenti con `DOCUMENT_ENCRYPTION_OLD_KEYS` + `rotate_document_encryption_key --apply`; `backup_portale` non copia il `.env` accanto ai dati (`BACKUP_ENV_DIR` per la copia separata); versione cache ACL basata sul tempo; log separati `app.log`/`qcluster.log`/`commands.log`; CSP senza host esterni; niente SVG negli upload serviti da `/media/`.
- Audit 09/10 (finding fuori roadmap): `ForcedPasswordChangeMiddleware` impone il cambio password obbligatorio; password di almeno 12 caratteri con i validatori Django; logout via GET da altri siti ignorato; `core/numbering_retry.save_with_next_number` per le numerazioni `MAX()+1` con retry; token Graph cifrato in cache; wizard `/setup/` sempre chiuso con settings di produzione.

## Centro guide (`/guide/`)

Una guida per ogni modulo, scritta a passi numerati con le etichette vere dei pulsanti, più il **Manuale di emergenza** per chi amministra il portale in assenza del referente.

- Contenuti in `core/guide_moduli/contenuti/<modulo>.py` (dizionario `GUIDA`), registro e ordine in `core/guide_moduli/__init__.py`. Tre parti: `uso` (tutti), `admin` e `problemi` (superuser, staff o amministratori del portale; per gli altri 403). `solo_admin=True` riserva l'intera guida (Manuale di emergenza).
- Rotte `guide_indice` (`/guide/`) e `guida_modulo` (`/guide/<slug>/?vista=uso|admin|problemi`, `&pdf=1` per il PDF). Prefisso `/guide/` condiviso in `core/middleware.py`: aperto a chi ha fatto l'accesso.
- Icona «?» in topnav e sidebar (`{% guida_corrente %}` in `core/templatetags/guide_tags.py`): guida del modulo dal prefisso più lungo dell'indirizzo (`prefissi`), altrimenti il Centro guide.
- Le guide di dettaglio già presenti nei moduli si collegano con `dettaglio`.
- Assistente AI (`ai_assistant/guide_portale.py::_guide_centro`): parte `uso` come `centro-<modulo>` per tutti (solo moduli senza `dettaglio`, gli altri sono già indicizzati dalla guida di dettaglio); parti `admin` + `problemi` come `centro-<modulo>-admin` e il Manuale di emergenza come `centro-emergenza`, con `solo_admin=True`: `guide_consentite` le dà solo a chi passa `puo_vedere_admin`.
- Quando cambia una funzione visibile si aggiorna anche il file del modulo qui (regola «guida in-app» di `CLAUDE.md`). Test: `core.tests_guide_moduli` (rotte, guide di dettaglio, render di ogni parte, permessi, PDF).

## I miei report (`/report/`)

Pagina personale (voce «I miei report» nel menu utente, rotta condivisa in `_ACL_SHARED_ROUTE_NAMES`): elenca le voci del catalogo del Centro report la cui pagina l'utente può aprire (`core.report_centro.accesso.voci_accessibili`, stessa politica del middleware via `acl_allows_path`), i report pianificati che riceve per mail e i propri scaricamenti degli ultimi 90 giorni da `ReportEmissione`. Guida in-app con `?guida=1`. Il permesso vero resta quello della pagina e della route di export.
- **Letture Microsoft Graph centralizzate** (19/10/2026, `core/m365_graph.py`): credenziali cercate ovunque nello stesso ordine (settings → variabili d'ambiente/.env → impostazioni SOC), token, paginazione `@odata.nextLink`, solo URL `graph.microsoft.com`, 403 tradotto nel permesso mancante. Usato da `core/account_m365.py`, dal SOC (`entra_signals`) e dal controllo `graph_token` del readyz.
- **Impostazioni notifiche, calendario Outlook delle scadenze** (19/10/2026): riquadro «Le mie scadenze nel calendario Outlook» (campi `NotificaCanali.outlook_scadenze`, `outlook_calendario_id`, `outlook_ultimo_sync`, `outlook_errore`; modello `ScadenzaOutlook`, migrazione `core 0089`). `core.m365_graph.scrivi` per POST/PATCH/DELETE su Graph (404 = oggetto sparito, non errore).
- **Accessi da un dispositivo nuovo + push nel primo accesso** (20/10/2026, `core/dispositivi.py`, modello `DispositivoAccesso`, migrazione `core 0090`): al login (segnale `user_logged_in`) cookie firmato `nh_dev` (numero casuale, nel DB solo SHA-256; scritto da `DispositivoCookieMiddleware`, 2 anni, HttpOnly, SameSite Lax); browser/PC mai usato dalla persona = notifica `accesso_nuovo_dispositivo` (nuova categoria «Sicurezza dell'account», sempre visibile), mail se `NotificaCanali.sicurezza_mail` (default sì), evento SOC `accesso_nuovo_dispositivo` (sorgente «Portale · accessi», KPI). Il primo dispositivo non avvisa; l'impersonazione non conta. Impostazioni notifiche → «I miei accessi» con «Non ero io» (chiude la sessione di quel dispositivo, evento `accesso_non_riconosciuto` → alert alto, audit). Wizard di primo accesso: riquadro «Notifiche anche su questo telefono o PC» e push per categoria (`NotificaCanali.push_categorie`); `push_service_worker` raggiungibile durante il primo accesso.
