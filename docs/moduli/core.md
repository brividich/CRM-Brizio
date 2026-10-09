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
- **CAPA — Azioni Correttive/Preventive** (`/capa/`): modello trasversale `ActionItem` collegato a un evento di origine (incidente/anomalia/audit, schema `source_code`+`source_pk`), workflow **APERTA → IN_CORSO → CHIUSA (con evidenza) → VERIFICATA** con chiusura ed efficacia separate (quattro occhi). Lista filtrabile + export CSV/XLSX, gating fail-closed (gestore `core.capa_manage` vs responsabile assegnato), pannello "Azioni collegate" embeddabile nei detail (già nel dettaglio incidente), alimenta lo Scadenzario Globale e il Centro notifiche; sorgente automazioni `core_actionitem` con trigger SQL
- **Export riusabile CSV/XLSX** con `core.exporting.ExportMixin` e helper per liste filtrate
- **Legacy models managed** su SQL Server: `Ruolo`, `UtenteLegacy`, `AnagraficaDipendente`, `Pulsante`, `Permesso`
- **Impersonation** admin → utente con middleware dedicato e session key
- **23 modelli Django** (Profile, AuditLog, SiteConfig, Notifica, Checklist*, OptioneConfig, ecc.)
- **Ricerca unificata** Ctrl+K (o barra «Cerca o vai a…» in topnav): pagine recenti, salto a qualsiasi pagina di navigazione (ACL-filtrata) e ricerca dati su 7 sorgenti (dipendenti, asset, ticket, progetti, task, procedure, DPI), con modulo e preview risultato
- **Topnav**: voci in eccesso raccolte in «Altro», hamburger da ≤1100px, menu utente (profilo, preferenze, tema chiaro/scuro, segnala problema, esci), approvazioni assenze in attesa come «N da approvare». Struttura: Per me · Tickets · Produzione · Persone · Sicurezza e ambiente · Qualità · IT · Suggestion Corner, con sottocategorie da `NavigationItem.group`; si applica con `python manage.py riorganizza_topbar --apply` (dry-run senza `--apply`)
- **Messaggi di conferma subito e uguali in tutti i moduli** (`core/flash_messages.py`, `core/js/hub-flash.js`, `core/css/hub-flash.css`): toast in basso a destra; successo/info spariscono dopo 7 s (pausa al passaggio del mouse), avvisi/errori restano fino alla ×. Messaggi identici raggruppati con «×N», messaggi lunghi riassunti alla prima frase con «Dettagli», al massimo 5 visibili con «+N altri» e «Chiudi tutti», Esc li chiude. Consegna: pagina intera via `{% flash_messages_fallback %}` in `core/base.html`; HTMX/fetch/XHR via header `X-Hub-Flash` (`FlashMessagesDeliveryMiddleware`, dopo `MessageMiddleware`, solo i messaggi della richiesta stessa); download via cookie `hub_flash`. Se la pagina cambia subito dopo un'azione asincrona, il messaggio ricompare nella successiva. I riquadri messaggi propri dei moduli sono stati tolti (restano login e scheda QR pubblica). Regole per sviluppatori: `docs/ai/04_FRONTEND_DIRECTION.md`.

## Hardening ottobre 2026

- Helper di sicurezza: `core.net.client_ip` (IP client, `X-Forwarded-For` solo da `TRUSTED_PROXY_IPS`), `core.redirects.safe_next` (redirect di ritorno validati sull'host), filtro template `js_json` (`{% load safe_json %}`, dati negli `<script>` senza XSS), `core.private_attachments.PrivateAttachmentStorage` (allegati privati cifrati con lettura dei file storici). In produzione `LEGACY_AUTH_ENABLED=0` blocca l'avvio senza `ACL_DISABLE_ACKNOWLEDGED=1`; DRF ha default espliciti (sessione + utente autenticato).
- Audit 09/10 (Fase 0): l'enrollment TOTP self-service è ammesso solo al primo accesso o dopo un reset admin (`force_setup`), con mail di avviso all'utente; superuser e staff sono soggetti al 2FA anche senza Profile; la sincronizzazione legacy non aggancia più in automatico un superuser/staff senza Profile. `core.download_security.harden_file_response` serve i file caricati con Content-Type dal nome file: inline solo PDF e immagini, il resto come allegato con `nosniff` e `CSP: sandbox`. `seed_acl_uat` non ha più una password fissa (`--password`, `UAT_SEED_PASSWORD` o casuale) e non gira con settings di produzione.
- Audit 09/10 (Fase 1): `core/ldap_conn.py` costruisce le connessioni LDAP con certificato verificato su `ldaps://` (`LDAP_CA_CERT_FILE`) e `receive_timeout` (`LDAP_RECEIVE_TIMEOUT`); `validate_deployment` segnala `ldap://`. Lockout axes per username+IP con IP da `core.net.client_ip`. Il 2FA «solo da rete esterna» tratta come esterne le richieste da `TWOFA_EXTERNAL_HOSTS` (default `*.msappproxy.net`) e `TWOFA_EXTERNAL_PROXY_IPS`. `config.env_config.update_env_file_values` rifiuta a-capo e nomi non validi.
- Audit 09/10 (Fase 2): blocco TOTP per utente con anti-replay e limite ai codici email; allowlist gruppi AD anche al login/SSO (`LDAP_GROUP_ALLOWLIST_ON_LOGIN`); utente disattivato = sessioni chiuse; rotazione della chiave documenti con `DOCUMENT_ENCRYPTION_OLD_KEYS` + `rotate_document_encryption_key --apply`; `backup_portale` non copia il `.env` accanto ai dati (`BACKUP_ENV_DIR` per la copia separata); versione cache ACL basata sul tempo; log separati `app.log`/`qcluster.log`/`commands.log`; CSP senza host esterni; niente SVG negli upload serviti da `/media/`.
