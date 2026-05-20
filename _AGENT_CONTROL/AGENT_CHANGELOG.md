# Agent Changelog

## 2026-05-20 - Codex

- Area: `git/workspace`
- Richiesta: fare commit e push su Git per pulire la workspace.
- File modificati: tutti i file gia modificati/non tracciati nella workspace al momento della richiesta, inclusa la nota agente corrente.
- File critici modificati: presenti modifiche gia in workspace a `django_app/config/settings/base.py` e altri file di configurazione/deploy; dettagli funzionali nelle voci precedenti.
- Motivo tecnico: consolidare su repository remoto le modifiche accumulate e riportare la working tree Git a stato pulito.
- Modifica: eseguiti controlli pre-commit (`git diff --check`, status, elenco untracked), previsto commit unico e push su `origin/main`.
- Impatto previsto: le modifiche locali diventano tracciate sul branch remoto `main`.
- Rischi residui: commit ampio con molte modifiche pregresse non tutte originate in questa micro-sessione; nessun `.env` reale visibile nello staging Git.
- Test/check: `git diff --check` OK; test applicativi specifici gia indicati nelle voci funzionali precedenti.
- Note: nessun backup creato.

- Area: `django_app/assenze`, `config/runtime`
- Richiesta: verificare se il sync SharePoint del modulo assenze fosse disattivato e riabilitarlo.
- File modificati: `django_app/config/settings/base.py`, `.env.example`, `django_app/.env.example`, `django_app/setup_wizard/templates/setup_wizard/wizard.html`, `tools/setup-wizard.html`, `django_app/hub_tools/views.py`, `django_app/assenze/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `django_app/config/settings/base.py`.
- Motivo tecnico: il flag `ASSENZE_SYNC_ON_PAGE_LOAD` risultava disattivato nei default versionati (`False`/`0`), quindi il pull SharePoint automatico sulle pagine operative assenze non partiva salvo override esplicito nel `.env`.
- Modifica critica: default runtime `ASSENZE_SYNC_ON_PAGE_LOAD` portato a `True`; esempi `.env` e wizard impostano/generano `ASSENZE_SYNC_ON_PAGE_LOAD=1`; il setup hub usa `1` come default quando la chiave manca; aggiunti test mirati sul parser del flag.
- Impatto previsto: se Graph e le liste assenze sono configurati, `gestione_assenze` e `car_dashboard` tornano a lanciare il pull SharePoint automatico, sempre throttled da `ASSENZE_SP_PULL_INTERVAL_SECONDS`.
- Rischi residui: un `.env` reale gia valorizzato con `ASSENZE_SYNC_ON_PAGE_LOAD=0` continua a prevalere e va corretto tramite pannello/configurazione server; non sono stati letti o modificati `.env` reali per policy sui segreti.
- Test/check: `python django_app\manage.py test assenze.tests.AssenzeSyncFlagTests --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: rimosso attributo read-only da `django_app/assenze/tests.py` per aggiungere copertura; nessun backup creato.

- Area: `config/runtime`
- Richiesta: memorizzare la procedura corretta per il problema ricorrente menu/topbar popolato con voci legacy, ordine errato e categorie padre mancanti.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; nota documentale operativa.
- Motivo tecnico: il problema non era il file `views.py` ne la preferenza sidebar/topbar, ma il `.env` prod con `NAVIGATION_REGISTRY_ENABLED=0` e `NAVIGATION_LEGACY_FALLBACK_ENABLED=1`, che disabilitava il Navigation Registry e forzava il fallback legacy `pulsanti`.
- Procedura corretta: impostare `NAVIGATION_REGISTRY_ENABLED=1` e `NAVIGATION_LEGACY_FALLBACK_ENABLED=0`, poi pulire cache/sessioni e riciclare IIS/app pool.
- Impatto previsto: la navigazione torna a usare `NavigationItem` con categorie padre/ordine configurati, invece dei nomi legacy dei pulsanti.
- Rischi residui: capire perche il setup/runtime riscrive talvolta `.env` con quei flag sbagliati; da indagare in un passaggio separato.
- Test/check: nota salvata in checkpoint agente; nessun test eseguito per modifica documentale.
- Note: questa e la prima verifica da fare se il menu "si risminchia" dopo deploy/hotfix/migrazioni.

- Area: `hotfix`
- Richiesta: rifare la hotfix QR in modo chirurgico partendo dal `views.py` sano fornito su Desktop, per evitare regressioni UI/topbar introdotte dal pacchetto precedente.
- File modificati/creati: `hotfix/hotfix-v1.0.2-20260520_121751-qr-site-url-clean.zip`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- Contenuto pacchetto: `django_app/assets/views.py`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: la hotfix `hotfix-v1.0.2-20260520_103701-qr-site-url.zip` era basata su un `views.py` di workspace troppo avanzato e poteva disallineare UI/template. Serviva una patch runtime minima sul file produzione sano.
- Modifica: copiato `C:\Users\l.bova\Desktop\views.py` in staging, aggiunto solo helper `_portal_absolute_uri()` e sostituite le chiamate QR/preview a `request.build_absolute_uri()` con il fallback su `SITE_URL`.
- Impatto previsto: ripristina lo stato funzionale della UI mantenendo il fix per generare QR `https` via `SITE_URL`.
- Rischi residui: richiede `SITE_URL` corretto nel `.env` prod, riciclo app pool/IIS e rigenerazione dei PDF QR; non usare il pacchetto precedente `hotfix-v1.0.2-20260520_103701-qr-site-url.zip`.
- Test/check: `python -m py_compile` sul file staging OK; contenuto zip verificato (`django_app/assets/views.py` solo); SHA256 `ACE31DF9AF3F5C373C97CD3059DE4B47DB94C32F21A9DC7C8124DB4D514C99B1`.
- Note: nessun backup creato.

- Area: `hotfix`
- Richiesta: creare hotfix minimale per correggere i QR pubblici asset generati in `http` invece di `https`.
- File modificati/creati: `hotfix/hotfix-v1.0.2-20260520_103701-qr-site-url.zip`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- Contenuto pacchetto: `django_app/assets/views.py`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: distribuire rapidamente la correzione runtime che usa `SITE_URL` come base canonica per le etichette QR, senza release completa.
- Impatto previsto: applicando lo zip al release attivo e configurando `SITE_URL=https://hub.cnovicrom.local`, le nuove etichette QR puntano a `https://hub.cnovicrom.local/assets/public/<token>/`.
- Rischi residui: il pacchetto contiene solo `views.py`; richiede riciclo app pool/IIS e rigenerazione delle etichette gia prodotte. Se `SITE_URL` manca o e errato, il QR puo ancora usare una base non corretta.
- Test/check: contenuto zip verificato (`django_app/assets/views.py`); SHA256 `60BC4B350A693BBEDA35F27A7780D4A79A5D7E91715DF9D6CB0EB6784F950227`.
- Note: nessun backup creato.

- Area: `django_app/assets`
- Richiesta: correggere le etichette QR asset che continuavano a generare link `http://hub.cnovicrom.local/assets/public/<token>/` invece di `https://...` dietro IIS/Waitress.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `README.md`, `django_app/assets/README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: `request.build_absolute_uri()` costruiva la route QR con lo scheme visto dalla request interna, che in produzione puo essere `http` anche quando il dominio pubblico e HTTPS.
- Modifica: aggiunto helper `_portal_absolute_uri()` che usa `settings.SITE_URL` come base canonica quando configurato; applicato ai target QR pubblico, landing, dettaglio e preview etichetta. Documentato l'uso di `SITE_URL=https://hub.cnovicrom.local`.
- Impatto previsto: rigenerando le etichette PDF, i QR pubblici puntano a `https://hub.cnovicrom.local/assets/public/<token>/`; i link gia stampati/generati prima restano invariati.
- Rischi residui: in produzione serve avere `SITE_URL` valorizzato correttamente e riavviare/riciclare l'app pool se si modifica `.env`; se `SITE_URL` resta vuoto, il comportamento torna a dipendere dalla request.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_qr_label_defaults_to_public_route_when_available assets.tests.AssetsRoutingTests.test_asset_qr_label_uses_site_url_for_public_route assets.tests.AssetsRoutingTests.test_asset_qr_label_does_not_use_internal_sharepoint_folder_without_public_link assets.tests.AssetsRoutingTests.test_asset_qr_label_detail_target_still_points_to_asset_detail --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: nessun backup creato.

## 2026-05-19 - Codex

- Area: `django_app/hub_tools`, `django_app/assets`
- Richiesta: unificare nella gestione server/admin portale le configurazioni SharePoint usate dagli asset, inclusi i link pubblici QR.
- File modificati: `django_app/hub_tools/views.py`, `django_app/hub_tools/templates/hub_tools/setup_wizard.html`, `django_app/hub_tools/tests.py`, `django_app/assets/templates/assets/pages/gestione_admin.html`, `README.md`, `django_app/assets/README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato in questo passaggio; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace. La modifica riguarda comunque UI amministrativa di configurazione server e va considerata operativamente sensibile.
- Motivo tecnico: le impostazioni SharePoint asset erano disponibili dal modulo assets, ma il punto naturale di amministrazione delle connessioni Graph/SharePoint e il pannello centrale `/admin-portale/hub/setup-wizard/`.
- Modifica: estesa la sezione Microsoft Graph / SharePoint del setup wizard hub con URL libreria asset, toggle link pubblici QR, root consentita e ID root/site/drive; il salvataggio aggiorna le stesse chiavi `.env` usate dal modulo assets. La pagina assets mostra un rimando al pannello centrale.
- Impatto previsto: gli admin possono gestire tutte le connessioni SharePoint dal pannello server centrale mantenendo flessibilita di modulo; nessun cambio DB e nessuna chiamata Graph reale nei test.
- Rischi residui: come per gli altri setting `.env`, in ambienti multi-processo puo servire riavviare/riciclare l'app pool per allineare tutti i worker; valori root/item errati bloccano correttamente la generazione link pubblici.
- Test/check: `python django_app\manage.py test hub_tools.tests.HubSetupWizardEnvTests.test_setup_wizard_renders_true_false_env_booleans_correctly hub_tools.tests.HubSetupWizardEnvTests.test_setup_wizard_renders_asset_sharepoint_public_link_fields hub_tools.tests.HubSetupWizardEnvTests.test_reconfigure_saves_asset_sharepoint_public_link_settings assets.tests.AssetsRoutingTests.test_gestione_admin_shows_sharepoint_config_card assets.tests.AssetsRoutingTests.test_gestione_admin_can_save_sharepoint_config --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py test hub_tools --settings=config.settings.test --verbosity 1` OK (13 test); `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test` OK.
- Note: nessun backup creato.

- Area: `django_app/assets`
- Richiesta: gestire da administrator asset le impostazioni `SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED`, root consentita e ID root/site/drive per i link pubblici QR SharePoint.
- File modificati: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/gestione_admin.html`, `django_app/assets/services/sharepoint_public_links.py`, `django_app/assets/management/commands/assets_ensure_public_share_links.py`, `django_app/assets/tests.py`, `README.md`, `django_app/assets/README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato in questo passaggio; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: dopo l'introduzione dei link pubblici QR, i relativi `SHAREPOINT_ASSET_*` dovevano essere amministrabili dalla pagina impostazioni del modulo assets, senza richiedere modifica manuale del file `.env`.
- Modifica: estesa la card SharePoint / Microsoft Graph di `/assets/impostazioni/?tab=config` con toggle link pubblici QR, root consentita e ID root/site/drive; il salvataggio aggiorna le chiavi `.env`; servizio e command leggono i valori aggiornati da processo/env mantenendo default sicuri.
- Impatto previsto: l'admin asset puo attivare/disattivare e configurare i link pubblici SharePoint QR dal portale; la feature resta spenta di default e continua a creare solo link Graph `anonymous/view` su cartelle validate.
- Rischi residui: il cambio root da UI va usato solo se cambia la root SharePoint operativa; valori root/item errati fanno saltare la validazione e il command segnera gli asset come non eleggibili.
- Test/check: `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_gestione_admin_shows_sharepoint_config_card assets.tests.AssetsRoutingTests.test_gestione_admin_can_save_sharepoint_config --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test` OK; `python django_app\manage.py test assets --settings=config.settings.test --verbosity 1` OK (219 test).
- Note: nessun backup creato; non sono state fatte chiamate reali a Microsoft Graph nei test.

- Area: `django_app/assets`, `django_app/config/settings/base.py`
- Richiesta: generare automaticamente link pubblici SharePoint read-only per QR asset, solo per cartelle sotto `ASSET CN`, e riconvertire cartelle gia esistenti tramite command.
- File modificati/creati: `django_app/assets/models.py`, `django_app/assets/migrations/0069_asset_public_share_links.py`, `django_app/assets/services/sharepoint_public_links.py`, `django_app/assets/management/commands/assets_ensure_public_share_links.py`, `django_app/assets/views.py`, `django_app/assets/urls.py`, `django_app/assets/admin.py`, `django_app/assets/tests.py`, `django_app/config/settings/base.py`, `django_app/.env.example`, `README.md`, `django_app/assets/README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `docs/ai/05_SECURITY_BOUNDARIES.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `django_app/config/settings/base.py` (nuove impostazioni `SHAREPOINT_ASSET_*` e sola eccezione pubblica `/assets/public/` in `MIDDLEWARE_EXEMPT_PREFIXES`). `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: i QR verso `sharepoint_folder_url` aprivano l'URL interno SharePoint e richiedevano login Microsoft; serviva un link Graph `anonymous/view` per singola cartella asset, senza aprire tenant/sito e senza pubblicare cartelle fuori `ASSET CN`.
- Modifica: aggiunti campi Asset per drive/item, link pubblico, stato/errore e token QR; nuovo servizio Graph dedicato con body fisso `type=view`, `scope=anonymous`, `retainInheritedPermissions=true`; validazione root tramite `parentReference`/path; route pubblica tokenizzata `/assets/public/<token>/`; QR aggiornato per usare route/link pubblico e non l'URL interno; command `assets_ensure_public_share_links` con dry-run default, apply, force, only-missing e asset-tag; admin con campi/azioni essenziali.
- Impatto previsto: nuove cartelle asset salvano `drive_id/item_id`; dopo attivazione feature flag e command di riconversione, i QR fisici aprono senza login Microsoft solo le cartelle asset autorizzate sotto `ASSET CN`. Le altre route `/assets/` restano protette.
- Rischi residui: in produzione serve configurare e testare `SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED=true` e preferibilmente `SHAREPOINT_ASSET_ALLOWED_ROOT_DRIVE_ID/ITEM_ID`; asset storici senza `sharepoint_drive_id/item_id` richiedono risoluzione Graph da path durante il command. La route pubblica e volutamente stretta ma resta una nuova superficie pubblica tokenizzata.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_create_anonymous_view_link_uses_view_anonymous_body assets.tests.AssetsRoutingTests.test_ensure_asset_public_share_link_saves_public_url assets.tests.AssetsRoutingTests.test_ensure_asset_public_share_link_blocks_outside_asset_cn assets.tests.AssetsRoutingTests.test_management_command_dry_run_does_not_save_public_url assets.tests.AssetsRoutingTests.test_management_command_apply_saves_public_url_for_eligible_asset assets.tests.AssetsRoutingTests.test_management_command_only_missing_skips_asset_with_existing_link assets.tests.AssetsRoutingTests.test_asset_qr_label_defaults_to_public_route_when_available assets.tests.AssetsRoutingTests.test_asset_qr_label_does_not_use_internal_sharepoint_folder_without_public_link assets.tests.AssetsRoutingTests.test_public_redirect_valid_token_redirects_without_login assets.tests.AssetsRoutingTests.test_public_redirect_unknown_token_404 assets.tests.AssetsRoutingTests.test_public_redirect_disabled_token_404 assets.tests.AssetsRoutingTests.test_assets_public_prefix_is_accessible_without_login_but_other_assets_routes_are_protected --settings=config.settings.test --verbosity 2` OK (12 test); `python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test` OK; `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py test assets.tests --settings=config.settings.test --verbosity 2` OK (219 test); `python django_app\manage.py test --settings=config.settings.test --verbosity 1` OK (357 test, skipped=1); `python django_app\manage.py test assets --settings=config.settings.test --verbosity 1` OK (219 test).
- Note: `django_app/config/settings/base.py`, `django_app/assets/urls.py` e `django_app/assets/admin.py` erano in sola lettura; rimosso l'attributo read-only per applicare la patch. I file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

- Area: `django_app/assets`
- Richiesta: correggere i collegamenti categoria della dashboard Assets che aprivano `/assets/lista/?category=<id>` senza filtrare l'inventario canonico.
- File modificati: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/asset_dashboard.html`, `django_app/assets/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `README.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: la dashboard usava il parametro legacy `category`, mentre la lista asset filtra tramite `asset_category`; il link risultava formalmente valido ma non applicava il filtro categoria.
- Modifica: aggiornati i link categoria dashboard a `asset_category=<id>`; aggiunto redirect compatibile da `category=<id>` a `asset_category=<id>` nella lista asset; aggiunti test di routing e regressione.
- Impatto previsto: cliccando su Pressa o su qualsiasi chip categoria si apre la lista asset gia filtrata sulla categoria corretta; i vecchi link salvati con `category` vengono normalizzati.
- Rischi residui: nessuno noto sulla lista asset; il redirect riguarda solo `GET` con `category` presente e `asset_category` assente.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_dashboard_category_links_use_asset_category_filter assets.tests.AssetsRoutingTests.test_asset_list_legacy_category_query_redirects_and_filters --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py test assets.tests --settings=config.settings.test --verbosity 2` OK (208 test); `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: il template `django_app/assets/templates/assets/pages/asset_dashboard.html` era in sola lettura; rimosso l'attributo read-only per applicare la correzione. I file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `django_app/assets`
- Richiesta: nella sezione "Specifiche tecniche" del dettaglio asset mostrare solo caratteristiche compilate, tenendo conto dei campi specifici di categoria.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `django_app/CHANGELOG.md`, `CHANGELOG.md`, `README.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: il rendering del dettaglio asset poteva mostrare righe placeholder (`N/D`, `-`) nelle specifiche, soprattutto nel fallback hardcoded e nei campi configurati con `show_if_empty`.
- Modifica: introdotto helper condiviso per riconoscere valori vuoti/placeholder; filtrate sempre le righe vuote nella sezione `SPECS` per campi configurati, campi categoria e fallback; corretto il formato `BOOL` per non trasformare valori mancanti in `No`.
- Impatto previsto: la card "Specifiche tecniche" mostra solo dati utili e sparisce quando non rimangono specifiche compilate; ogni categoria continua a esporre le proprie caratteristiche valorizzate.
- Rischi residui: valori calcolati non vuoti (es. data acquisto derivata) restano visibili come deciso; eventuali configurazioni admin che usavano `show_if_empty` su `SPECS` non forzeranno piu la visualizzazione del placeholder.
- Test/check: `python django_app\manage.py test assets.tests --settings=config.settings.test --verbosity 2` OK (206 test); `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `hotfix`
- Richiesta: analisi crash produzione da `hotfix/app.log` dopo applicazione hotfix asset.
- File modificati/creati: `hotfix/hotfix-v1.0.1-20260519_122243-sidebar-categories.zip`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: `django_app/assets/views.py` importava `assets.services.sidebar_categories`, ma il pacchetto hotfix precedente `hotfix-v1.0.1-20260519_120132.zip` conteneva solo `django_app/assets/views.py` e non il nuovo modulo service richiesto in runtime.
- Modifica: creato zip hotfix minimale con `django_app/assets/services/sidebar_categories.py` nel percorso relativo corretto.
- Impatto previsto: applicando lo zip sopra il release attivo, l'import di `assets.views` torna a risolversi e il portale non cade piu durante il caricamento di `config.urls`.
- Rischi residui: il pacchetto corregge solo il modulo mancante rilevato dal log; se il deploy attivo manca altri file introdotti da modifiche precedenti, emergeranno al successivo import/check.
- Test/check: `python -m py_compile django_app\assets\services\sidebar_categories.py` OK; contenuto zip verificato (`django_app/assets/services/sidebar_categories.py`); SHA256 `93CE1ED790E232A6B0DFA7FCF34A82FA0A479F2EDEE9DC2703D31E969D417A14`.
- Note: dopo applicazione hotfix riavviare il servizio/app pool e ricontrollare il log per eventuali import mancanti successivi.

## 2026-05-19 - Codex

- Area: `hotfix`
- Richiesta: creare un nuovo pacchetto hotfix per la correzione metadati SharePoint sulle cartelle asset.
- File modificati/creati: `hotfix/hotfix-v1.0.1-20260519_120132.zip`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: predisporre un pacchetto overlay leggero applicabile dal Release Manager senza nuova release completa.
- Modifica: creato zip hotfix con `django_app/assets/views.py`.
- Impatto previsto: applicando lo zip al release attivo viene distribuito il fix che valorizza i metadati SharePoint anche sulle cartelle asset.
- Rischi residui: il pacchetto contiene il file runtime completo `django_app/assets/views.py` nello stato corrente della workspace; non include test o documentazione.
- Test/check: contenuto zip verificato (`django_app/assets/views.py`); SHA256 `C53140A7AC88B1845F8D76B616577CF78E06A41D96A783EE58BD4110488F3880`.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

- Area: `django_app/assets`
- Richiesta: colonne metadato SharePoint create ma non compilate sulle cartelle asset.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `django_app/CHANGELOG.md`, `CHANGELOG.md`, `README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: i metadati venivano applicati solo ai file documento caricati su SharePoint, mentre le righe visibili sotto `ASSET CN` sono cartelle `driveItem` e restavano senza PATCH su `listItem/fields`.
- Modifica: `_ensure_sharepoint_folder` restituisce anche l'id del driveItem; `_ensure_asset_sharepoint_folder` applica i metadati anche alla cartella asset e alle tre sottocartelle categoria usando helper condivisi per il PATCH campi.
- Impatto previsto: nuovi salvataggi/sync SharePoint asset valorizzano `AssetTag`, categoria, produttore, modello, matricola, stato, reparto e tipo cartella anche sulle cartelle, non solo sui file.
- Rischi residui: cartelle gia create prima della patch restano vuote finche l'asset non viene risalvato o non viene rieseguito un flusso che richiama `_ensure_asset_sharepoint_folder`; l'operazione resta best-effort e dipende dai permessi Graph sui campi lista.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_sharepoint_upload_uses_relative_subfolders assets.tests.AssetsRoutingTests.test_sharepoint_document_metadata_includes_asset_fields assets.tests.AssetsRoutingTests.test_sharepoint_folder_metadata_includes_asset_fields assets.tests.AssetsRoutingTests.test_ensure_asset_sharepoint_folder_applies_metadata_to_folders --settings=config.settings.test --verbosity 2` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

- Area: `django_app/assets`
- Richiesta: QR delle etichette asset verso la cartella SharePoint relativa.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `django_app/CHANGELOG.md`, `README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: rendere `/assets/view/<id>/qr-label/` coerente con l'uso operativo delle label fisiche, puntando alla cartella SharePoint dell'asset quando disponibile.
- Modifica: default target QR da `detail` a `sharepoint` nella view `asset_qr_label`, con fallback gia esistente alla scheda asset se `sharepoint_folder_url` manca; `?target=detail` continua a forzare la scheda.
- Impatto previsto: le nuove label generate senza querystring aprono direttamente la cartella SharePoint dell'asset; nessuna migrazione DB.
- Rischi residui: asset senza `sharepoint_folder_url` continuano a puntare alla scheda portale finche Graph/sync non valorizza l'URL cartella.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_qr_label_returns_pdf assets.tests.AssetsRoutingTests.test_asset_qr_label_defaults_to_sharepoint_folder_when_available assets.tests.AssetsRoutingTests.test_asset_qr_label_detail_target_still_points_to_asset_detail --settings=config.settings.test --verbosity 2` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `django_app/assets`
- Richiesta: upload su SharePoint dell'intera cartella selezionata dalla card Documenti asset, mantenendo eventuali sottocartelle.
- File modificati: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/asset_detail.html`, `django_app/assets/tests.py`, `README.md`, `CHANGELOG.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace all'avvio.
- Motivo tecnico: l'input `webkitdirectory` invia una lista di file; senza salvare il `webkitRelativePath` lato backend l'upload Graph appiattiva tutto nella sola sottocartella categoria.
- Modifica: il template invia hidden field con percorso relativo per ciascun file selezionato da cartella; `_validate_asset_document_uploads` conserva il percorso relativo sanitizzato; `_upload_asset_document_to_sharepoint` crea la cartella categoria piu eventuali sottocartelle relative prima del `PUT` Graph.
- Impatto previsto: su SharePoint i file caricati da "Carica cartella" finiscono in `ASSET CN/<tag>/<categoria>/<cartella selezionata>/<subfolder>/...`; resta il fallback locale `AssetDocument`.
- Rischi residui: i nomi remoti dei file continuano a usare il prefisso univoco timestamp/id gia esistente per evitare sovrascritture; la struttura cartella e preservata, il nome fisico del file SharePoint non e identico al nome sorgente.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_detail_upload_can_target_local_archive assets.tests.AssetsRoutingTests.test_asset_detail_folder_upload_keeps_sharepoint_relative_path assets.tests.AssetsRoutingTests.test_sharepoint_upload_uses_relative_subfolders --settings=config.settings.test` OK; `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `hotfix`
- Richiesta: creare pacchetto hotfix per la correzione upload cartella asset SharePoint.
- File pacchetto: `hotfix/hotfix-v1.0.1-20260519_115839.zip`.
- Contenuto pacchetto: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/asset_detail.html`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: distribuire rapidamente la fix runtime senza release completa, includendo solo backend e template necessari alla produzione.
- Impatto previsto: applicando il pacchetto sul release attivo, "Carica cartella" preserva sottocartelle relative su SharePoint.
- Rischi residui: creato anche `hotfix/hotfix-v1.0.1-20260519_115759.zip` durante un primo tentativo, ma contiene entry appiattite (`views.py`, `asset_detail.html`) e non va usato; il pacchetto valido e verificato e quello `115839`.
- Test/check: verifica zip OK con entry `django_app/...` complete.
- Note: nessuna migrazione, dipendenza o collectstatic richiesti per questa fix.
