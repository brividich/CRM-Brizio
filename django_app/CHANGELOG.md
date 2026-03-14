# Changelog

## 0.7.0 — 2026-03-13

### Setup Wizard & Rebrand BrizioHUB

- **[feature] Setup Wizard integrato in Django** (`setup_wizard/`): al primo avvio il portale reindirizza automaticamente a `/setup/`, un wizard guidato a 9 step che configura l'intero ambiente di produzione senza toccare file a mano.
- **[feature] Branding &amp; Identità** (Step 1): il wizard permette di scegliere il nome istanza (es. "Portale Novicrom"), caricare il logo aziendale e il favicon. Logo e favicon vengono salvati in `core/static/core/img/` e referenziati via `BRANDING_LOGO` / `BRANDING_FAVICON` nel `.env`.
- **[feature] Configurazione SQL Server in-browser** (Step 4): il wizard include un tool live per testare la connessione al database SQL Server tramite l'API `/setup/api/test-db/` (usa pyodbc direttamente, risponde in tempo reale con la versione del server).
- **[feature] Test live connessioni** (Steps 4/5/7): pulsanti "Testa connessione" per SQL Server (pyodbc), LDAP/AD (ldap3 + fallback porta TCP) e SMTP (smtplib + STARTTLS).
- **[feature] Salvataggio configurazione server-side**: al termine del wizard, `/setup/api/save/` scrive `django_app/.env` e `config.ini` sul server e imposta `SETUP_COMPLETED=1`. Il middleware non reindirizzerà più al wizard.
- **[feature] `SetupRequiredMiddleware`**: middleware file-based (legge `.env` direttamente, senza DB) che intercetta ogni richiesta e reindirizza a `/setup/` finché `SETUP_COMPLETED≠1`.
- **[rebrand] BrizioHUB**: nome del software su GitHub cambiato in **BrizioHUB**. Il nome istanza è ora configurabile per-deployment tramite `INSTANCE_NAME` in `.env` (default `BrizioHUB`, override suggerito al primo avvio del wizard). Aggiornati: header wizard, `INSTALLED_APPS`, log dir (`briziohub_logs`), `.env.example`.
- **[infra] `INSTANCE_NAME`, `BRANDING_LOGO`, `BRANDING_FAVICON`** aggiunti a `base.py` settings e `.env.example`.
- **[infra] `/setup/`** aggiunto a `MIDDLEWARE_EXEMPT_PREFIXES` (ACL e session middleware non intercettano il wizard).
- **[tool] `tools/setup-wizard.html`**: wizard standalone HTML (zero dipendenze) per generare `.env` / `config.ini` offline; mantenuto come tool di supporto alternativo.
- **[versioning]** Bump versione `0.6.40-dev` → `0.7.0`.

## 0.6.40-dev — 2026-03-12

- **[fix] Automazioni Assenze -> `capo_email` nel payload runtime**: il designer ora espone il placeholder `{capo_email}` tra i campi suggeriti della sorgente `assenze`, il preset "Avviso al responsabile" lo usa direttamente nel destinatario email e il worker automazioni arricchisce payload e old payload risolvendo l'email dal caporeparto selezionato. Aggiornati anche i trigger SQL della queue `assenze` per serializzare `capo_email` nei nuovi eventi.
- **[feature] Anagrafica centrale dipendenti**: la pagina `anagrafica/dipendenti/` non e' piu' solo in lettura. Ora consente l'inserimento diretto di dipendenti con stato `attivo` / `non attivo`, mantenendo i dipendenti non attivi senza account operativo ma sempre presenti nell'anagrafica centrale.
- **[feature] Admin Portale -> anagrafica unica**: creazione, aggiornamento, attivazione/disattivazione e bulk action sugli utenti legacy sincronizzano la tabella `anagrafica_dipendenti`. Se un account viene disattivato, il dipendente resta in anagrafica e viene sganciato come account operativo.
- **[feature] Timbri -> reset e rebuild da anagrafica**: aggiunto in configurazione il pulsante `Reset tabella`, che svuota i dati locali del modulo `timbri` lasciando intatta la configurazione SharePoint e ricreando solo i nominativi dalla tabella anagrafica centrale.
- **[fix] Timbri -> deduplica nominativi duplicati**: la lista dipendenti di `timbri` ora deduplica le anagrafiche doppie con stesso nominativo, preferisce il record anagrafico "buono" non tutto maiuscolo e recupera dal duplicato storico i dati mancanti (es. matricola/ruolo) per evitare doppi in UI.
- **[fix] Anagrafica centrale -> bonifica duplicati reali**: introdotta la deduplica anche lato `anagrafica/dipendenti/` e una bonifica dati reale sulla tabella `anagrafica_dipendenti`, con merge dei campi utili dal record storico al record preferito e rimozione dei duplicati maiuscoli/non collegati.
- **[test] Copertura regressioni anagrafica/admin/timbri**: aggiunti test su inserimento dipendente non attivo senza account, sync anagrafica da disattivazione account e reset/deduplica del modulo `timbri`.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.40-dev`.

## 0.6.39-dev - 2026-03-11

- **[feature] Automazioni — designer visuale affiancato**: aggiunta la vista `/admin-portale/automazioni/regole/<id>/designer/` e la creazione `/admin-portale/automazioni/regole/nuova/designer/`, senza introdurre motori o schemi paralleli. Il designer lavora sugli stessi modelli `AutomationRule`, `AutomationCondition`, `AutomationAction`, con riepilogo umano `TRIGGER -> CONDIZIONI -> AZIONI`, trigger card, card condizioni/azioni, test rapido collegato e link dedicati da lista, dettaglio e builder classico.
- **[ux] Automazioni — preset visuali e suggerimenti guidati**: il designer ora propone basi suggerite e preset visuali compatti per condizioni e azioni, con specializzazione `assenze` (approvazione/rifiuto, avviso responsabile, notifiche interne, metriche, log audit, condizioni su `moderation_status`, esclusione `Malattia`, controllo capo reparto). Aggiunti anche controlli dimensione `S / M / L` per mantenere i preset leggibili ma non invasivi.
- **[fix] Assenze — insert SQL Server compatibile con trigger**: corretto il salvataggio locale e il pull SharePoint verso la tabella `assenze` sostituendo il recupero PK via `OUTPUT INSERTED.id` con la sequenza `INSERT` + `SELECT CAST(SCOPE_IDENTITY() AS int)`, necessaria quando sulla tabella sono presenti trigger abilitati. Aggiunti test di regressione sul flusso di insert SQL Server.
- **[docs] Guida Automazioni Designer**: aggiunti documento HTML e PDF riepilogativo delle modifiche implementate sul modulo `automazioni`, in stile guida interna, con overview architetturale, UX del designer, preset, reorder, test e stato finale della fase.
- **[test] Automazioni — copertura designer e reorder**: estesi i test Django per pagina designer, route `nuova/designer`, summary umano, link al designer, endpoint reorder condizioni/azioni e presenza dei cataloghi preset renderizzati.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.39-dev`.

## 0.6.38-dev - 2026-03-11

- **[feature] Automazioni — modulo completo v1 SSR**: completata l'introduzione del modulo `automazioni` con catalogo sorgenti/campi, modelli dominio (`AutomationRule`, `AutomationCondition`, `AutomationAction`, `AutomationRunLog`, `AutomationActionLog`, `DashboardMetricValue`), runtime regole, executor controllati, worker queue e builder finale SSR per creare, modificare, attivare e testare manualmente le regole.
- **[feature] Automazioni — queue SQL Server su `assenze`**: aggiunta l'infrastruttura tecnica con tabella `automation_event_queue` e trigger `AFTER INSERT` / `AFTER UPDATE` su `assenze`, con payload JSON coerente al source registry e processamento demandato al worker Django.
- **[feature] Automazioni — plancia operativa admin**: aggiunte pagine operative SSR per queue e run log in area `admin_portale`, con filtri, dettaglio evento, collegamento ai log applicativi, reset a `pending` e retry controllato del singolo evento.
- **[feature] Automazioni — builder regole con pannello campi sempre visibile**: introdotte le pagine `/admin-portale/automazioni/regole/` con form SSR, formset condizioni/azioni, configurazione umana di `send_email`, `write_log`, `update_dashboard_metric`, `insert_record`, `update_record` e pannello laterale `Contenuti / Colonne disponibili` sempre visibile e coerente con il source registry.
- **[feature] Admin Portale — `Config SRV`**: la precedente area `Diagnostica LDAP` e' stata rinominata lato UI in `Config SRV` e ora centralizza configurazione/test di LDAP / Active Directory e SMTP nello stesso pannello, con persistenza su `config.ini`.
- **[infra] SMTP nei settings Django**: aggiunto supporto a `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `EMAIL_TIMEOUT` e `DEFAULT_FROM_EMAIL`, letti da environment oppure dalla nuova sezione `[SMTP]` di `config.ini`.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.38-dev`.


## 0.6.37-dev - 2026-03-10

- **[feature] Modulo Ticket — app `tickets/`**: nuovo modulo nativo che sostituisce le due app PowerApps ("Ticket IT" e "Ticket MAN"). Gestisce richieste di intervento su asset informatici e macchinari con ciclo di vita Aperta → In carico → Risolto → Chiuso, priorità (Bassa/Media/Alta/Urgente), flag di sicurezza sul lavoro (forza URGENTE non modificabile), categorie configurabili, allegati file, commenti pubblici e note interne.
- **[feature] Ticket — numerazione automatica**: ogni ticket riceve un numero progressivo per anno nel formato `IT-YYYY-NNNN` / `MAN-YYYY-NNNN`, con reset annuale automatico.
- **[feature] Ticket — collegamento asset**: i ticket possono essere collegati a un asset del catalogo (FK su `assets.Asset`) oppure a descrizione libera per asset non censiti.
- **[feature] Ticket — delega a fornitore esterno**: i gestori possono delegare un ticket a un fornitore esterno selezionato dall'anagrafica fornitori (`anagrafica.Fornitore`).
- **[feature] Ticket — impostazioni admin**: sezione `/tickets/impostazioni/` (solo admin) per configurare List ID SharePoint, team gestori (nome + email), ACL apertura e ACL gestione per ciascun tipo (IT e MAN), tutto modificabile in-page senza toccare il codice.
- **[feature] Ticket — ACL configurabile**: chi può aprire e chi può gestire i ticket di ciascun tipo è definito nelle impostazioni. Vuoto = aperto a tutti / solo admin. L'admin portale bypassa sempre.
- **[infra] `tickets` aggiunto a INSTALLED_APPS e MODULE_VERSIONS**: migrazione `0001_initial` applicata su dev (tabelle: `tickets_ticket`, `tickets_ticketcommento`, `tickets_ticketallegato`, `tickets_ticketimpostazioni`).
- **[core] Reparto → Capo Reparto escalation**: `_resolve_default_capo_for_user()` in `assenze/views.py` ora usa `UserExtraInfo.caporeparto` come sorgente primaria (da `RepartoCapoMapping`), lo storico SP come fallback, e `anagrafica_dipendenti.reparto` come last resort.

## 0.6.36-dev - 2026-03-10

- **[feature] Certificazione Presenza — flusso admin con push SharePoint**: aggiunta la nuova sezione `/assenze/certificazione-presenza/` (accesso tramite subnav assenze), riservata agli utenti con ruolo admin/HR. Consente l'inserimento diretto della presenza giornaliera di un dipendente con turno mattina (obbligatorio) e turno pomeriggio (opzionale, attivabile con toggle). L'inserimento è auto-approvato (`consenso = Approvato`), crea automaticamente un record nella tabella `assenze` e tenta il push alla lista SharePoint "Certificazione presenza" tramite Power Automate.
- **[feature] Certificazione Presenza — flusso utente via richiesta assenze**: aggiunta l'opzione "Certifica presenza" nel selettore tipo nella pagina `/assenze/richiesta/`. Quando selezionato, il form standard (data inizio/fine) viene nascosto e compare una sezione dedicata con: banner esplicativo, input data, selettori ora:minuto per entrata/uscita mattina, toggle pomeriggio e selettori condizionali. Al submit JS assembla i campi nascosti compatibili con il backend; il record viene salvato in `assenze` con `consenso = In attesa` e inviato al Capo Reparto per approvazione.
- **[feature] Certificazione Presenza — modello Django e migrazioni**: aggiunto `CertificazionePresenza` nell'app `assenze` (`assenze/models.py`) con campi: nome dipendente, data, entrata/uscita mattina, flag turno pomeriggio, entrata/uscita pomeriggio (nullable), note, consenso (In attesa/Approvato/Rifiutato), capo_reparto_email, salta_approvazione, origine (utente/admin), assenza_id, inserito_da, sharepoint_item_id. Applicate migrazioni `0001_initial_certificazione_presenza` e `0002_add_consenso_origine_to_certificazione`.
- **[feature] Anagrafica — dashboard personalizzabile**: la dashboard `/anagrafica/` supporta ora la modalità "Personalizza" (solo admin), analoga alle altre dashboard del portale. Tre widget (`kpi`, `moduli`, `ultimi`) sono nascondibili, riordinabili con drag-and-drop e le preferenze sono persistite in `localStorage` con chiave `ana_dash_prefs_v1`. Pulsante "Personalizza" nel hero; barra edit con Salva/Reset/Chiudi.
- **[infra] `list_id_presenza` in `config.ini`**: aggiunta la chiave `list_id_presenza = 7B15a131b8-...` nella sezione `[AZIENDA]` di `config.ini` per la lista SharePoint "Certificazione presenza".
- **[ux] Subnav assenze — voce Certifica presenza**: aggiunto link "Certifica presenza" nella barra di navigazione secondaria del modulo assenze (`assenze/components/subnav.html`) con highlight attivo sulla pagina corrente.
- **[ux] Menu assenze — card Certifica presenza**: aggiunta card di accesso rapido nel menu del modulo assenze (`assenze/pages/menu.html`).

## 0.6.35-dev - 2026-03-09

- **[ux] Wizard permessi ruolo — flag inline e pulsante Tutto**: i flag "Può modificare / eliminare / approvare" sono ora sempre visibili nella riga, senza espansione "+dettagli". Ogni riga ha un pulsante "Tutto" che seleziona/deseleziona in blocco visibilità e tutti e tre i flag. I pulsanti "Tutto ON / OFF" di modulo gestiscono ora anche i flag extra, non solo la visibilità.
- **[ux] Wizard permessi ruolo — pre-caricamento diretto allo step 2**: quando il wizard viene aperto con `?ruolo_id=X` (es. da link "Modifica"), i permessi esistenti vengono caricati e la pagina salta direttamente allo step 2, senza passare per la selezione manuale del ruolo.
- **[feature] Assets — modifica in blocco da tabella inventario**: aggiunta selezione multipla nella tabella asset tramite checkbox per riga e checkbox "seleziona tutti" nell'intestazione. Quando almeno un asset è selezionato compare una toolbar con il pulsante "Modifica in blocco" che apre un modale per impostare Stato, Reparto, Produttore, Modello e Note su tutti gli asset selezionati in una sola operazione. Aggiunto endpoint backend `POST /assets/bulk-update/` (`assets:asset_bulk_update`).
- **[feature] Assets — card KPI personalizzate nel widget manager**: nel pannello "Widget dashboard — visibilità & collegamenti", nella sezione KPI principali, è ora possibile aggiungere card personalizzate con titolo, valore testuale, sottotitolo e collegamento. Le card vengono salvate in `localStorage` e appaiono nella riga KPI come widget standard (draggabili, nascondibili). Le card custom sono removibili dal manager con un pulsante "Rimuovi".

## 0.6.34-dev - 2026-03-09

- **[feature] Categorie asset dinamiche gestibili da `/assets/`**: introdotte le nuove entita `AssetCategory` e `AssetCategoryField`, con studio admin interno per creare categorie business come `Allarme`, `TVCC`, `Pompa di calore`, scegliere la famiglia tecnica di base e definire i campi dedicati senza nuove modifiche al codice.
- **[ux] Form asset e macchine con campi categoria dinamici**: le schermate di creazione/modifica mostrano ora i campi configurati in base alla categoria selezionata, salvandone i valori in `extra_columns["_category_fields"]` e mantenendo separati i campi custom globali gia esistenti.
- **[ux] Dettaglio asset con titoli sezione personalizzabili per categoria**: la scheda dettaglio legge ora anche i titoli configurati sulla categoria (`Specifiche`, `Profilo`, `Responsabile`, `Timeline`, `Manutenzione`) e integra automaticamente i campi categoria marcati per il dettaglio.
- **[db] Migrazione categorie asset applicata**: aggiunta e applicata `assets.0022_assetcategory_asset_asset_category_and_more` per introdurre FK categoria su `Asset` e la struttura dei campi categoria.
- **[qa] Copertura test estesa su categorie asset**: aggiunti test per la creazione admin di una categoria, per il salvataggio dei valori categoria da form asset e per il rendering nel dettaglio di titoli e campi categoria.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.34-dev`.

## 0.6.33-dev - 2026-03-09

- **[feature] Dettaglio asset configurabile da studio admin**: aggiunta la nuova entita `AssetDetailField`, con gestione da `/assets/` per controllare quali dati compaiono nelle sezioni `Metriche`, `Specifiche tecniche`, `Profilo asset` e `Responsabile attuale`, con ordine, ambito (`tutti`, `asset standard`, `macchine di lavoro`) e formato valore.
- **[ux] Scheda dettaglio guidata da configurazione**: la pagina `/assets/view/<id>/` legge ora la configurazione admin e mostra anche campi custom dentro il dettaglio, mantenendo fallback sicuro solo quando non esiste ancora una configurazione valida per il tipo asset aperto.
- **[db] Migrazioni dettaglio asset applicate**: aggiunte e applicate `assets.0020_assetdetailfield` e `assets.0021_seed_asset_detail_fields`, con seed iniziale dei campi che replica la scheda dettaglio predefinita e la rende subito modificabile.
- **[qa] Test amministrazione dettaglio e rendering custom**: aggiunta copertura per la creazione dei campi dettaglio da pannello admin e per il rendering in scheda asset di un campo custom configurato.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.33-dev`.

## 0.6.32-dev - 2026-03-09

- **[ux] Tabelle inventario e macchine piu compatte**: ridotti padding righe, dimensione badge, blocchi nome/tag e densita generale delle tabelle principali di `/assets/` e `/assets/work-machines/`, cosi la lista mostra piu record senza allungare inutilmente la pagina.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.32-dev`.

## 0.6.31-dev - 2026-03-09

- **[ux] Layout assets non piu stirato in altezza**: la shell condivisa del modulo `assets` e la dashboard `/assets/` non forzano piu un'altezza minima a viewport piena, cosi le schermate con poco contenuto non restano artificialmente lunghe.
- **[ux] Sidebar e contenuto allineati al contenuto reale**: il layout usa ora `align-items:start`, evitando che menu laterale e contenuto si trascinino verticalmente fra loro quando una pagina ha piu o meno elementi delle altre.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.31-dev`.

## 0.6.30-dev - 2026-03-09

- **[feature] Sidebar assets gestibile con gerarchia parent/child**: il pannello admin interno di `/assets/` permette ora di definire anche la voce padre della singola voce menu, cosi puoi controllare direttamente posizione, sezione e sottocategoria senza dover intervenire nel codice.
- **[feature] Planimetrie multiple per categoria impianto**: il sistema planimetrie supporta ora piu mappe attive in parallelo, ciascuna con categoria dedicata (ad esempio `Officina`, `TVCC`, `Sistema allarme`), con selettore categoria nella vista utenti e nell'editor.
- **[db] Migrazioni sidebar e planimetrie allineate**: aggiunte `assets.0018_alter_plantlayout_options_assetsidebarbutton_parent_and_more` e `assets.0019_seed_sidebar_parents_and_layout_categories` per introdurre parent menu e categoria planimetria anche sugli ambienti esistenti.
- **[qa] Copertura test estesa**: aggiunti test per la creazione di voci sidebar figlie da pannello admin e per il cambio categoria nella vista planimetrie.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.30-dev`.

## 0.6.29-dev - 2026-03-09

- **[ux] Verifiche periodiche piu compatte e configurabili**: la pagina `/assets/verifiche-periodiche/` usa ora un form piu corto e largo, con layout selezionabile dall'utente (`Compatta`, `Bilanciata`, `Ampia`) persistito in `localStorage`, cosi la schermata non resta inutilmente lunga.
- **[ux] Ricerca live sugli asset coinvolti**: il multiselect asset supporta filtro istantaneo per tag/nome, contatore selezioni e azioni rapide `Seleziona visibili` / `Pulisci`, rendendo gestibile anche una lista macchine ampia.
- **[qa] Test pagina verifiche periodiche esteso**: aggiunta copertura sul rendering dei nuovi controlli UI della pagina (`layout switch` e ricerca asset).
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.29-dev`.

## 0.6.28-dev - 2026-03-09

- **[feature] Verifiche periodiche nel modulo assets**: introdotta la nuova entita `PeriodicVerification` con fornitore collegato da `anagrafica.Fornitore`, cadenza in mesi, date ultima/prossima verifica, stato attivo e collegamento multi-asset, cosi ogni macchina o bene puo appartenere a piu cicli di verifica contemporaneamente.
- **[ux] Gestione verifiche integrata nel layout assets**: aggiunta la nuova pagina `/assets/verifiche-periodiche/` dentro il shell standard del modulo, con KPI, form di gestione, lista verifiche e collegamenti diretti da scheda asset, dettaglio asset e form macchine di lavoro.
- **[db] Migrazioni e ACL verifiche periodiche**: create `assets.0016_periodicverification` e `assets.0017_seed_periodic_verifications_sidebar_button`, registrato il modello in admin e aggiunta la voce ACL/sidebar `periodic_verifications` per gli ambienti gia esistenti.
- **[qa] Copertura test asset aggiornata**: aggiunti test per creazione verifica periodica con fornitore e asset multipli, oltre all'assegnazione di piu verifiche sul singolo asset.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.28-dev`.

## 0.6.27-dev - 2026-03-08

- **[fix] Login SQL Server realmente resiliente senza `core_siteconfig`**: `SiteConfig.get_many()` ora materializza la queryset dentro il blocco `try`, cosi l'errore `ProgrammingError` viene assorbito anche quando SQL Server fallisce solo in fase di esecuzione e `/login/` torna ai default applicativi invece di rispondere 500.
- **[qa] Test allineato al comportamento reale di SQL Server**: il test sul login simula ora una queryset che esplode in iterazione, coprendo il caso che aveva bucato la prima correzione.
- **[db] Merge migrazioni core completato**: aggiunta la migration `core.0018_merge_0016_navigationitem_parent_code_0017_loginbanner` per chiudere davvero il conflitto tra i leaf `0016` e `0017` e ripristinare l'esecuzione di `migrate` e dei test.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.27-dev`.

## 0.6.26-dev - 2026-03-08

- **[feature] Mappa officina su planimetria PNG/JPG**: aggiunte nuove entita `PlantLayout`, `PlantLayoutArea` e `PlantLayoutMarker` nel modulo `assets`, con vista utenti interattiva (`/assets/work-machines/map/`) ed editor admin (`/assets/work-machines/map/editor/`) per disegnare reparti e posizionare macchine di lavoro sopra la planimetria.
- **[ux] Collegamento rapido alla mappa officina**: inseriti accessi diretti alla nuova mappa dalle schermate `Dashboard officina` e `Macchine di lavoro`, piu seed sidebar `plant_layout_map` per ambienti con menu assets configurabile.
- **[fix] Login resiliente senza `core_siteconfig`**: `SiteConfig` ora degrada in fallback sicuro se la tabella non esiste ancora nel DB e la pagina `/login/` usa un fetch unico con default applicativi invece di generare `ProgrammingError`.
- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.26-dev`.

## 0.6.25-dev - 2026-03-08

- **[feature] Subnav centralizzata e configurabile da admin**: la barra secondaria (subnav bianca) è ora gestita dal Navigation Builder anziché essere hardcodata in ogni app. L'admin può aggiungere, modificare e riordinare le voci subnav per ogni sezione direttamente dall'interfaccia, senza toccare il codice.
- **[feature] Navigation Builder — sezione `subnav`**: aggiunta la sezione `subnav` alle voci di navigazione. Ogni voce subnav ha un campo `parent_code` (es. `dashboard`, `assenze`, `anagrafica`) che determina in quale sezione appare.
- **[feature] Drag-and-drop riordino voci**: nel Navigation Builder è ora possibile trascinare le righe della tabella per riordinarle; l'ordine viene salvato automaticamente tramite il nuovo endpoint `/api/navigation/reorder`.
- **[infra] `get_subnav_nodes()` in navigation_registry**: aggiunta funzione dedicata che restituisce le voci subnav filtrate per `parent_code` e ruolo utente, con cache versioned.
- **[infra] Context processor aggiornato**: `legacy_nav()` inietta ora anche `subnav_items` (lista voci subnav per la sezione corrente) in ogni request; il rilevamento della sezione avviene tramite `request.resolver_match.app_name`.
- **[db] Migrazione `core.0014`**: aggiunto campo `parent_code` a `NavigationItem`.

## 0.6.24-dev - 2026-03-08

- **[feature] Nuova app `anagrafica`**: creata sezione autonoma separata da `admin_portale`, con dashboard, lista dipendenti (sola lettura da legacy SQL Server) e gestione completa fornitori.
- **[feature] Gestione fornitori CRUD**: creazione/modifica/disattivazione fornitore con categorizzazione (MATERIALI, SERVIZI, ATTREZZATURE, LOGISTICA, IT, MANUTENZIONE, ALTRO), dati anagrafici completi, filtri e paginazione.
- **[feature] Allegati fornitore**: upload documenti per fornitore (`FornitoreDocumento`) con tipologia (contratto, visura, DURC, certificato, offerta, ecc.) e cancellazione con cleanup file su disco.
- **[feature] Storico ordini fornitore**: `FornitoreOrdine` con numero ordine, data, importo, stato (bozza/confermato/consegnato/annullato) e aggiornamento stato inline.
- **[feature] Valutazioni fornitore**: `FornitoreValutazione` con rating 1-5 su qualità, puntualità, comunicazione; calcolo automatico punteggio medio e rendering barre grafiche.
- **[feature] Asset assegnati a fornitore**: modello `FornitoreAsset` che collega `Fornitore` → `assets.Asset` con tipo relazione (manutenzione/assistenza/noleggio/fornitura), date e stato attivo/scaduto; FK unidirezionale da `anagrafica` verso `assets` senza modificare l'app assets.
- **[ux] UI moderna con sistema `ana-*`**: tutte le pagine anagrafica (lista fornitori, dettaglio fornitore, form fornitore, lista dipendenti) riscritte con design system `ana-*` CSS: KPI cards, tabelle moderne, badge categoria, barre rating, layout a colonne responsive.
- **[ux] Dashboard fornitore a tabs**: pagina `fornitore_detail` con hero header, 4 metriche KPI (ordini/spesa/rating/asset), tab switcher vanilla JS (Ordini/Documenti/Valutazioni/Asset), sidebar contatti e rating bars.
- **[ux] Form fornitore moderno**: `fornitore_form` riscritto con sezioni collassate (Dati aziendali / Contatti / Indirizzo / Altro), griglia 4 colonne responsive, validazione inline.
- **[db] Migrazioni anagrafica**: applicate `anagrafica.0001_initial` e `anagrafica.0002_fornitoreasset` su dev (SQLite) e prod (SQL Server).
- **[infra] Componenti template autonomi**: `anagrafica/components/` con subnav, page_header, flash_messages indipendenti da `admin_portale`.

## 0.6.23-dev - 2026-03-07

- **[fix] Assenze CAR riallineate a SharePoint**: corretta la lettura dello stato richieste quando `Consenso` e gia `Approvato/Rifiutato` ma `_ModerationStatus` resta incoerente su `In attesa`, evitando il ritorno in pending delle stesse pratiche il giorno successivo.
- **[ux] Diagnostica sync assenze**: aggiunto pulsante `Diagnostica sync` nella dashboard CAR con pannello di confronto tra stato locale, `Consenso` SharePoint, `_ModerationStatus` e stato effettivo letto dal portale, piu feedback immediato dopo `Approva/Rifiuta`.
- **[fix] Riconciliazione pendenti assenze lato dashboard**: prima di mostrare le richieste in attesa il portale ricontrolla i pendenti visibili su SharePoint e aggiorna subito il DB locale se il record remoto risulta gia chiuso.
- **[feature] Template etichette assets multi-livello**: introdotta gestione template QR su tre scope (`generale`, `per tipologia asset`, `per singolo asset`) con risoluzione `override asset -> tipologia -> generale`.
- **[ux] Configurazione etichette spostata in admin assets**: `assets/gestione/?tab=config` ora espone il template generale, la matrice per categoria asset con assegnazione/configurazione dedicata e l'elenco override personali direttamente dalla sezione admin.
- **[admin+db] AssetLabelTemplate esteso**: aggiunti campi `scope`, `asset_type` e relazione `asset` con migration `assets.0014_assetlabeltemplate_scope_asset_and_more`; aggiornato anche il Django admin per filtrare e cercare i template per ambito.
- **[test] Copertura aggiornata**: estesi `assenze.tests` e `assets.tests` con casi su incoerenza SharePoint, riconciliazione pendenti, precedenza template etichette e gestione dal tab configurazione admin.

## 0.6.22-dev - 2026-03-06

- **[ux] Versione visibile in dashboard**: aggiunto piè di pagina nella dashboard con versione portale, data release corrente e conteggio moduli versionati.
- **[ux] Area admin con release notes**: il pannello amministrazione ora espone una card `Versioning e Release Notes` con versione portale, versioni dei moduli e riepilogo ultima release.
- **[feature] Supporto versioning per modulo**: introdotta configurazione `MODULE_VERSIONS` con override dedicati via environment (`APP_VERSION_CORE`, `APP_VERSION_ASSETS`, `APP_VERSION_TASKS`, ecc.) mantenendo una versione globale unica come default.
- **[infra] Registry versioni centralizzato**: aggiunto `core.versioning` e nuovo context processor per rendere disponibili versione app, changelog corrente e versioni moduli nei template.
- **[test] Copertura UI versioning**: aggiunti test su footer dashboard e card versioning admin.
## 0.6.21-dev - 2026-03-06

- **[feature] Officina su modulo Assets**: introdotto profilo dedicato `WorkMachine` collegato `1:1` ad `Asset`, con import Excel macchine di lavoro, lista dedicata, create/edit manuale, dettaglio tecnico e dashboard officina.
- **[ux] Assets resi configurabili lato utente**: sistemata la tabella inventario (`record` click fix) e aggiunte funzioni smart con colonne selezionabili/ridimensionabili/riordinabili, widget drag & drop, popup `Admin Studio` e layout persistito in `localStorage`.
- **[feature] Documentazione macchina estesa**: aggiunti allegati reali `AssetDocument`, gestione manuali/specifiche/interventi nel form macchina, campo esplicito `prossima manutenzione`, reminder dashboard su soglia e vista scadenze officina.
- **[feature] SharePoint + QR per asset/macchine**: nuovi campi cartella SharePoint su asset, pulsanti diretti da dettaglio, predisposizione sync upload via Microsoft Graph e nuova stampa etichetta PDF con QR code verso scheda asset o cartella SharePoint.
- **[db] Migrazioni assets**: applicate `assets.0007`-`assets.0011` per tipi macchina, sidebar/dashboard officina, manutenzione esplicita, allegati documentali e metadati SharePoint.
- **[test] Copertura assets aggiornata**: suite `assets.tests` estesa fino a 23 test con verifica import officina, form macchina, dashboard reminder, dettaglio SharePoint e PDF QR.
## 0.6.20-dev - 2026-03-05

- **[feature] Check sovrapposizione impegni su assegnazione task**: in create/edit task viene verificata la presenza di altre task attive gia assegnate allo stesso operatore nello stesso intervallo pianificato (`next_step_due`/`due_date`).
- **[ux] Alert operativo su carico incaricato**: dopo salvataggio task vengono mostrati warning con riepilogo impegni sovrapposti (titoli task e finestre data) per evitare sovraccarico pianificazione.
- **[feature] Scelta gestione conflitto con priorita**: introdotto campo form `Se l'operatore ha altri impegni nello stesso periodo` con opzione di rialzo automatico priorita a `High` in caso di conflitto.
- **[test] Copertura creazione task aggiornata**: aggiunti test su alert conflitto assegnazione e su auto-aggiornamento priorita (`LOW -> HIGH`) quando selezionato.
## 0.6.19-dev - 2026-03-05

- **[fix] Drag Gantt allineato al cursore**: riscritta la logica di trascinamento task su timeline con aggancio alla cella sotto il mouse (non piu solo delta pixel), supporto pointer capture e auto-scroll orizzontale ai bordi tabella.
- **[validation] Regola date task resa stretta**: `data fine` ora deve essere strettamente successiva a `data inizio/next step` (`due_date > next_step_due`) su model/form e update rapido Gantt.
- **[ux] Evidenza intervallo non valido**: le celle timeline di task con range incoerente sono colorate in rosso/stripes con avviso esplicito in riga e legenda.
- **[test] Copertura Gantt estesa**: aggiunti test su blocco update con `fine == inizio` e su rendering classe `is-invalid-range` in vista progetto Gantt.

## 0.6.18-dev - 2026-03-05

- **[ux] Sezione assets completamente in italiano**: tradotti titoli pagina, pulsanti, filtri, card KPI, tabella inventario, etichette dettaglio e testi operativi delle pagine asset/workorder/report.
- **[ux] Shell assets italiana**: aggiornati branding shell, placeholder ricerca, etichetta ruolo utente e call-to-action principale.
- **[ux] Sidebar e azioni italianizzate**: tradotte voci menu predefinite, etichette pulsanti azione e fallback runtime per configurazioni legacy con label inglesi gia salvate.
- **[model] Etichette `choices` italiane**: aggiornate scelte visibili per tipi/stati asset, stati/tipi intervento, sezioni sidebar, zone/azioni/stili pulsanti.
- **[form] Form assets rietichettati**: introdotte label italiane su create/edit/assegnazione asset e su form interventi (creazione/chiusura).
- **[ops] Seed nav/ACL riallineati**: default label navigation e descrizioni ACL aggiornate in italiano per le nuove installazioni/seeding.
- **[qa] Verifiche superate**: eseguiti `manage.py check` e `manage.py test assets.tests` (SQLite/dev) con esito OK.
## 0.6.17-dev - 2026-03-05

- **[feature] Asset import Excel ricostruito e reso tollerante**: ripristinato `import_assets_excel` con rilevamento automatico header riga, matching fogli flessibile (case-insensitive/fuzzy) e fallback su tutti i fogli disponibili.
- **[feature] Supporto nuovi dataset inventario**: esteso import a scenari con fogli/ambiti aggiuntivi (`Telefonia`, `SIM Telefonica`, `TVCC`, ecc.) e colonne non uniformi tra tipi macchinario.
- **[feature] Colonne dinamiche auto-create**: i campi non mappati vengono creati automaticamente come `AssetCustomField` e salvati in `Asset.extra_columns` con tipizzazione base (testo/numero/data/si-no).
- **[security] Sanitizzazione campi sensibili in import**: password/PIN/PUK/PSW non vengono mai salvati in chiaro; viene registrato solo flag di presenza (`... (presente)`).
- **[docs+test] Documentazione e copertura aggiornate**: README assets aggiornato con nuove opzioni (`--all-sheets`) e aggiunti test su colonne dinamiche, campi sensibili e matching foglio fuzzy.
## 0.6.16-dev - 2026-03-05

- **[feature] Progetti Task estesi con anagrafica commessa**: aggiunti campi progetto `cliente`, `project_manager`, `capocommessa`, `programmatore`, `metodo di controllo`, `P/N`, `lavorazione simile` (progetto esistente) e `lavorazione simile` libera.
- **[db] Migrazione tasks**: nuova migration `tasks.0006_project_capo_commessa_project_client_name_and_more` con i nuovi campi strutturali su `Project`.
- **[ux] Form task aggiornato per creazione progetto completa**: nella sezione creazione nuovo progetto ora sono presenti tutti i metadati operativi richiesti; supportata sia selezione lavorazione simile esistente sia inserimento ex-novo.
- **[feature] Controllo assenze su pianificazione task**: su create/edit/update date task viene verificata la sovrapposizione con ferie/permessi dell'assegnatario (tabella `assenze`) e viene emesso warning non bloccante.
- **[feature] Gantt progetto con conflitti assenze**: giorni in conflitto con assenza assegnatario sono evidenziati in riga task con sfondo rosso e marker `X`, tooltip dettaglio e contatore conflitti in metadati riga.
- **[ux] Pagine progetto arricchite**: metadati progetto estesi visibili in dettaglio task, lista progetti e header Gantt.
- **[test] Copertura estesa**: aggiunti test per metadati progetto in creazione task e per rilevamento conflitti assenze + rendering marker nel Gantt.
## 0.6.15-dev - 2026-03-05

- **[ux] Task form create/edit ristrutturato**: pagina di inserimento task riscritta con sezioni operative (`Contesto e Progetto`, `Definizione attivita`, `Pianificazione`, `Responsabilita e visibilita`) e terminologia piu chiara per utenti non tecnici.
- **[ux] Terminologia task allineata al processo**: label/help dei campi aggiornati in `TaskForm` (es. `Data prevista conclusione`, `Operatore incaricato`, `Prossima azione`) con indicazioni esplicite su overdue e coerenza date.
- **[feature] Task dashboard admin estesa**: aggiunta `Control room amministrativa` nella lista task (solo `tasks_admin`) con KPI operativi (`non assegnate`, `senza data`, `task singole`, `scadenza 7 giorni`, `in corso ferme`) e riepilogo progetti piu critici.
- **[feature] Filtri task avanzati**: nuovi filtri lista `unassigned`, `without_due_date`, `without_project` con applicazione server-side.
- **[feature] Asset Admin Studio potenziato**: sezione admin inventario arricchita con metriche configurazione, pannello check di consistenza e operazioni rapide inline.
- **[feature] Export configurazione admin assets**: nuova azione `export_admin_snapshot` con download JSON di campi custom, liste, action button e sidebar button.
- **[test] Copertura aggiornata**: aggiunti test su nuovi filtri task e su export snapshot admin assets (permessi + payload).
## 0.6.14-dev - 2026-03-05

- **[security] Task edit esteso a admin/capo progetto**: la modifica completa task (/tasks/<id>/edit/) e le azioni operative di dettaglio (status, subtasks, allegati) ora consentono accesso anche al capo progetto (Project.created_by) oltre a tasks_admin e tasks_edit.
- **[feature] Data prevista conclusione aggiornabile da incaricato/admin**: nuova route POST tasks/<id>/update-due-date/ con form dedicato in dettaglio task; autorizzati tasks_admin, capo progetto, ruoli con tasks_edit e assegnatario task.
- **[audit] Tracciamento update scadenza**: aggiornamenti su due_date tramite nuovo form generano evento TaskEventType.EDIT con payload modifiche.
- **[ux] Dettaglio task migliorato**: campo Scadenza task ora include azione rapida Aggiorna data prevista senza entrare nel form completo.
- **[security] Gantt progetto coerente con ruolo capo progetto**: edit schedule Gantt esteso anche al creator del progetto (capo progetto), mantenendo ACL server-side e anti-IDOR.
- **[test] Copertura permessi estesa**: aggiunti test su modifica task da capo progetto, blocco edit per non autorizzati, update due date per assegnatario/admin e blocco per viewer in scope.
## 0.6.13-dev - 2026-03-05

- **[ux] Gantt ridimensionabile via drag**: colonne sinistra (WBS, Nome attivita, Durata, Inizio, Fine) ora ridimensionabili trascinando il bordo header; layout salvato in localStorage per progetto.
- **[ux] Altezza/larghezza celle regolabili live**: aggiunti slider Zoom giorni e Altezza righe con aggiornamento immediato del diagramma.
- **[feature] Drag & drop timeline giorni**: trascinando una cella attiva di task sul diagramma viene eseguito shift orizzontale delle date (next_step_due, due_date) con persistenza server-side.
- **[security] Endpoint shift protetto ACL**: nuova route POST tasks/projects/<id>/gantt/tasks/<task_id>/shift/ con controllo scope progetto e regole edit (tasks_admin oppure tasks_edit + assegnazione).
- **[audit] Tracciamento shift date**: lo spostamento via drag genera eventi audit EDIT con payload modifiche date.
- **[test] Copertura Gantt estesa**: aggiunti test su shift consentito, negato e out-of-scope.
## 0.6.12-dev - 2026-03-05

- **[ux] Gantt con colonne personalizzabili**: aggiunta barra "Opzioni vista" in pagina progetto per mostrare/nascondere colonne WBS/Durata/Inizio/Fine.
- **[ux] Timeline molto piu ampia**: introdotti preset finestra temporale (1 mese, 2 mesi, 3 mesi, 4 mesi, Auto) per estendere la colonna giorni in formato quasi mensile.
- **[ux] Dimensioni colonna configurabili**: scelta larghezza celle giorni (Compatta/Standard/Ampia) e larghezza colonna "Nome attivita".
- **[ux] Persistenza configurazione vista**: salvataggio task Gantt e commenti progetto mantengono i parametri di visualizzazione correnti.
## 0.6.11-dev - 2026-03-05

- **[ux] Gantt progetto in formato classico tabellare**: la vista tasks/projects/<id>/gantt/ ora usa una griglia timeline giornaliera (intestazioni mese/giorno, colonne WBS/Nome attivita/Durata/Inizio/Fine) con rendering tipo diagramma Gantt tradizionale.
- **[ux] Evidenza stato su timeline**: le celle attive della griglia sono colorate per stato task (TODO, IN_PROGRESS, DONE, CANCELED) con evidenza giorno corrente e weekend.
- **[ux] Gestione separata dalla timeline**: aggiunta sezione Modifica rapida timeline sotto al diagramma per aggiornare next_step_due, due_date, status senza perdere la leggibilita della matrice.
## 0.6.10-dev - 2026-03-05

- **[feature] Tasks: Gantt Progetti**: aggiunte viste `tasks/projects/` e `tasks/projects/<id>/gantt/` con timeline visuale delle task di progetto.
- **[security] Edit Gantt con regola dedicata**: modifica timeline consentita solo a `tasks_admin` oppure utenti con `tasks_edit` assegnati ad almeno una task del progetto.
- **[feature] Commenti con notifica target utente**: esteso `TaskComment` con `target_user` e aggiunto `ProjectComment` con notifica in-app (`Notifica`, tipo `generico`) all'utente selezionato.
- **[feature] Commenti progetto**: nuova area commenti nel Gantt progetto con invio notifica opzionale a utente specifico.
- **[ux] Navigazione Tasks estesa**: aggiunti link rapidi alla sezione Progetti/Gantt da dashboard lista task e dettaglio task.
- **[db] Migrazione tasks**: aggiunta migration `tasks.0005_taskcomment_target_user_projectcomment`.
- **[test] Copertura estesa tasks**: aggiunti test su accesso/anti-IDOR Gantt, regole edit schedule e notifiche commenti task/progetto.
## 0.6.9-dev - 2026-03-05

- **[feature] Tasks: Progetti come contenitore**: introdotto modello Project e collegamento opzionale Task.project per gestire task singole o raggruppate in progetto.
- **[feature] Tasks: scelta create/edit "Task singolo" o "Task in progetto"**: il form task supporta selezione tipologia con opzione progetto esistente o creazione nuovo progetto inline.
- **[feature] Tasks: Allegati task/progetto**: introdotto modello TaskAttachment, upload file da dettaglio task con destinazione task corrente o progetto collegato.
- **[feature] Audit trail esteso**: aggiunto evento ATTACHMENT_ADDED su upload allegati con payload (attachment_id, target, file_name, riferimenti task/progetto).
- **[ux] Dashboard/lista/dettaglio estesi**: filtro lista per progetto, evidenza progetto su card task, sezione allegati in dettaglio con storico upload.
- **[admin] Backoffice tasks aggiornato**: registrati in Django admin i modelli Project e TaskAttachment; TaskAdmin esteso con campo/filtro progetto.
- **[db] Migrazione tasks**: aggiunta migration tasks.0004_alter_taskevent_type_project_task_project_and_more.
- **[test] Copertura estesa**: test aggiunti per create task singola/progetto, selezione progetto esistente, upload allegati (task/progetto), audit attachment e anti-IDOR endpoint upload.
## 0.6.8-dev - 2026-03-05

- **[feature] Tasks: tag leggeri e filtrabili**: aggiunto campo `Task.tags` (comma-separated), gestione in create/edit e filtro `tag` in lista task.
- **[feature] Tasks: rollup stato da subtasks**: quando lo stato subtasks evolve, la task principale viene riallineata automaticamente (`TODO/IN_PROGRESS/DONE/CANCELED`) con evento audit `STATUS_CHANGE` marcato `source=subtask_rollup`.
- **[ux] Task UI migliorata**: tag visibili in lista/dettaglio e campo dedicato nel form.
- **[test] Copertura estesa tasks**: aggiunti test su filtro tag e su aggiornamento automatico stato task tramite subtasks.
- **[ux] Task dashboard operativa anche a lista vuota**: aggiunti KPI, quick links alle sottosezioni (mie/in corso/overdue/completate), pannello azioni gestione e messaggi ACL espliciti per i pulsanti non autorizzati.
## 0.6.7-dev - 2026-03-05

- **[feature] Nuova app `tasks` (MVP solido)**: introdotto modulo task completo con modelli Django dedicati (`Task`, `SubTask`, `TaskComment`, `TaskEvent`) e campi operativi richiesti (`title`, `description`, `status`, `priority`, `due_date`, `next_step_text`, `next_step_due`, `created_by`, `assigned_to`, `subscribers`, timestamp).
- **[feature] Enum e ordinamento task**: stati/priorita/eventi implementati con `TextChoices`; ordinamento default task impostato a `next_step_due ASC NULLS LAST`, poi `due_date ASC`, poi `updated_at DESC`.
- **[feature] Audit trail obbligatorio task/subtask**: tracciati eventi `STATUS_CHANGE`, `ASSIGNMENT_CHANGE`, `EDIT`, `COMMENT_ADDED`, `SUBTASK_ADDED`, `SUBTASK_STATUS_CHANGE` con payload JSON e actor.
- **[security] ACL legacy per azione + scope anti-IDOR**: introdotto controllo server-side per `tasks_view`, `tasks_create`, `tasks_edit`, `tasks_comment`, `tasks_admin`; scope visibilita applicato (creator/assignee/subscriber o globale con `tasks_admin`) su lista/dettaglio/azioni e protezione 404 su accesso fuori scope.
- **[feature] UI task + PRG**: nuove pagine `tasks/list.html`, `tasks/detail.html`, `tasks/form.html` con filtri (mie task default, status, priority, overdue, range scadenza, assigned_to), dettaglio completo (timeline eventi, commenti, subtasks) e azioni `POST` con redirect.
- **[feature] Bootstrap ACL legacy tasks**: aggiunto bootstrap idempotente `tasks/acl_bootstrap.py` per registrazione pulsanti legacy (`tasks_view/create/edit/comment/admin`) e metadati topbar.
- **[feature] Navigation Registry v2 integrato**: migration `tasks.0002_nav_entry` aggiunge voce topbar `Task`; filtro runtime in `core/context_processors.py` vincola la visibilita della voce al permesso ACL `tasks_view`.
- **[infra] Wiring progetto**: aggiunta app `tasks` in `INSTALLED_APPS` e include URL namespace `tasks` in `config/urls.py`.
- **[test] Copertura modulo tasks**: aggiunti test per permessi/scope admin vs non-admin, anti-IDOR (detail/edit/status), audit events (status/comment/subtask), filtri lista.
## 0.6.6-dev - 2026-03-05

- **[ux] Asset sidebar fix (pulsanti non piu "giganti")**: corretta la resa della colonna sinistra in `/assets/` rimuovendo lo stretching verticale delle voci menu e riducendo dimensioni/spaziatura dei pulsanti.
- **[feature] Menu sidebar dinamico su DB**: introdotto nuovo modello `AssetSidebarButton` con gestione completa di voci (etichetta, sezione, ordine, sottovoce, visibilita, URL target, match attivo), render dinamico e stato `active` coerente.
- **[feature] Admin Studio inline completo in pagina Asset**: nella dashboard asset aggiunte sezioni operative direttamente modificabili senza uscire dalla pagina:
  - Campi custom (`create/update/delete`)
  - Liste suggerite (`create/update/delete`)
  - Pulsanti azione dettaglio asset (`create/update/delete`)
  - Menu sidebar (`create/update/delete/visibile`)
- **[ux] Tutorial utilizzo Admin Studio**: aggiunto pulsante `Tutorial utilizzo` con popup guida rapida (chiusura via bottone, click esterno, `Esc`) per spiegare workflow e placeholder supportati.
- **[fix] Link Admin Studio**: rimossi i link diretti che portavano fuori contesto verso admin-portale/admin; i pulsanti ora aprono/scrollano le sezioni interne di configurazione.
- **[feature] Seed menu sidebar default modificabile**: aggiunto comando interno dalla UI (`seed_sidebar_buttons`) per generare le voci base editabili quando il menu custom non e ancora presente.
- **[ux] Layout assets uniformato**: esteso layout shell comune (`assets/base_shell.html`) alle principali pagine dell'app (`asset_detail`, `asset_form`, `asset_assignment`, `workorder_*`, `reports_dashboard`) per coerenza visiva e navigazione unificata.
- **[db] Migrazione assets**: nuova migration `assets.0006_assetsidebarbutton` per persistenza configurazione menu sidebar.
## 0.6.5-dev - 2026-03-05

- **[ux] Asset Inventory UI refresh**: pagina `/assets/` resa più fluida e moderna con hero header, quick links, card KPI, layout responsive e tabella click-to-open per accesso rapido al dettaglio asset.
- **[feature] Pulsanti di collegamento rapidi**: aggiunti pulsanti diretti a Inventario, Work Orders, Report e Nuovo Asset nella toolbar superiore della sezione assets.
- **[feature] Upload Excel da interfaccia web**: aggiunto box `Import Excel` nella pagina inventario con selezione file `.xlsx/.xlsm`, scelta fogli CSV, opzioni `dry-run`, `include optional`, `update existing`; avvio import senza terminale.
- **[feature] Smart interactions**: introdotto JS dedicato assets per autosubmit filtri (select + ricerca con debounce), stato di caricamento bottone import e navigazione riga-tabella al click.
- **[refactor] Styling assets separato**: introdotti file statici `assets/css/assets.css` e `assets/js/assets.js`; riduzione inline style e componentizzazione messaggi.
## 0.6.4-dev - 2026-03-04

- **[feature] Nuova app `assets` (Asset Inventory)**: introdotta app Django dedicata all'inventario asset IT/Produzione con modelli normalizzati (`Asset`, `AssetEndpoint`, `AssetITDetails`, `WorkOrder`, `WorkOrderLog`), admin completo, pagine web minime (lista, dettaglio, create/edit, assegnazione, workorder, report).
- **[feature] URL ACL-friendly namespaced**: aggiunte route namespace `assets` con prefissi stabili per ACL legacy:
  - `/assets/`, `/assets/view/<id>/`, `/assets/new/`, `/assets/edit/<id>/`, `/assets/assign/<id>/`
  - `/assets/workorders/`, `/assets/workorders/new/<id>/`, `/assets/workorders/view/<id>/`, `/assets/workorders/close/<id>/`
  - `/assets/reports/`
- **[feature] Seed ACL legacy**: nuovo command `python manage.py seed_assets_acl` che crea/aggiorna in modo idempotente i pulsanti legacy su tabella `pulsanti` (`modulo=assets`) con URL `django:assets:<route_name>`, e invalida cache ACL con `bump_legacy_cache_version()`.
- **[feature] Seed topbar navigation**: nuovo command opzionale `python manage.py seed_assets_nav` per creare/aggiornare `NavigationItem(code="assets", label="Asset", route_name="assets:asset_list", section="topbar")` e accessi ruolo opzionali.
- **[feature] Import massivo Excel asset**: nuovo command `python manage.py import_assets_excel` con supporto `--file`, `--sheets`, `--dry-run`, `--update/--no-update`, `--include-optional`, header row 5, upsert via `source_key` SHA1 e import endpoint/details/manutenzioni.
- **[security] Sanitizzazione campi sensibili import**: durante l'import non viene mai salvato alcun segreto in chiaro (es. `PSW BIOS`); viene persistito solo flag booleano `bios_pwd_set` (ed eventuale `vault_ref` testuale lato modello).
- **[infra] Wiring progetto**: aggiunta app `assets` a `INSTALLED_APPS`, include URL in `config/urls.py` prima di `core.urls`, documentazione operativa in `assets/README.md`.
- **[test] Copertura minima `assets`**: aggiunti test per route `/assets/` (legacy auth OFF), idempotenza seed ACL, dry-run import, import mock riga con creazione `Asset + Endpoint + ITDetails`.
- **[deps] Excel parser**: aggiunto `openpyxl==3.1.5` in `django_app/requirements.txt`.
## 0.6.3-dev - 2026-03-04

- **[config] Validazione cartella allegati da pannello**: `POST /api/anomalie/config/liste` ora valida `attachments_dir` prima del salvataggio (cartella esistente, directory valida e scrivibile). Se non valida, il salvataggio viene bloccato con errore esplicito.
- **[sync] Coda allegati con retry verso SharePoint**: introdotti metadati per file allegato (`pending/synced/error`, retry count, last error, timestamp ultimo tentativo/sync) e push allegati durante `POST /api/anomalie/sync`. Aggiunto pass extra per processare anche allegati pendenti di record già sincronizzati.
- **[permessi] Allegati in sola lettura**: separati i permessi allegati. `list/open/download` consentiti in view mode, mentre `upload/delete` restano consentiti solo agli editori OP (capocommessa/CAR/autorizzati/admin).
- **[ops] Cleanup orfani schedulabile**: nuovo comando `python manage.py cleanup_anomalie_allegati` con modalità report (default) o cancellazione reale (`--delete`), filtro età (`--older-than-days`) e limite (`--limit`).
- **[audit] Tracciamento completo allegati**: audit events aggiunti per upload, delete, open e download allegati (`log_action` su modulo `anomalie`).
- **[ux] Stato sync per-file in UI gestione anomalie**: ripristinata visualizzazione allegati anche in sola lettura e aggiunto stato per file (`Sync SP OK`, `In coda sync`, `Errore sync` con dettaglio errore).
## 0.6.2-dev - 2026-03-03

- **[feature] Gestione Anomalie — completamento modulo**: il modulo anomalie era parzialmente implementato; questa release lo porta a produzione.
  - **[nav] Fix navigazione anomalie**: `context_processors.py`, `topnav.html`, `subnav.html` (core e dashboard) e `anomalie_menu.html` aggiornati per puntare direttamente a `gestione_anomalie_page` (React app) invece della vecchia pagina intermediaria "Migrazione in corso".
  - **[db] Nuove colonne tabella `anomalie`**: aggiunte `numero_rdc NVARCHAR(100) NULL` (salva il numero RDC quando `aprire_rdc=1`) e `created_by_user_id INT NULL` (autore del record, usato per notifiche di chiusura). Script SQL da eseguire: `ALTER TABLE anomalie ADD numero_rdc NVARCHAR(100) NULL; ALTER TABLE anomalie ADD created_by_user_id INT NULL;`
  - **[feature] Allegati anomalia (immagini + documenti)**: nella pagina React `gestione_anomalie` aggiunta gestione allegati multipli con upload, elenco, preview immagini, apertura/scaricamento ed eliminazione. Endpoint introdotti: `api_anomalie_allegati`, `api_anomalie_allegati_upload`, `api_anomalie_allegati_delete`, `api_anomalie_allegati_file`. Validazioni lato server: estensioni consentite (`jpg/jpeg/png/gif/bmp/webp/pdf/doc/docx/xls/xlsx/xlsm/csv`), dimensione massima 20 MB, sanitizzazione nome file e protezione path traversal. Storage locale per record in `media/anomalie_allegati/<local_id>` (override opzionale via `config.ini` sezione `ANOMALIE.attachments_dir`).
  - **[ux] Apertura segnalazione (`/gestione-anomalie/nuova-segnalazione`)**: aggiunto pulsante `Aggiungi allegati` nel form Step 2 con coda file pre-salvataggio e upload automatico dopo il salvataggio del record (single S/N). In caso di range S/N, allegati disabilitati per evitare associazioni ambigue su più record.
  - **[ux] Gestione anomalia (`/gestione-anomalie`)**: ripristinata preview grande dell'allegato selezionato (immagine o documento) sopra la lista allegati, mantenendo azioni `Apri`, `Scarica`, `Elimina`.
  - **[config] Percorso cartella allegati gestibile da pannello**: nella pagina `gestione-anomalie/configurazione` aggiunto campo `Percorso cartella allegati`; salvataggio su `config.ini` sezione `[ANOMALIE]` chiave `attachments_dir` via API `api/anomalie/config/liste` (GET/POST).
  - **[ux] Campo Numero RDC funzionante**: l'input "Numero RDC" (visibile quando `Aprire RDC = true`) è ora collegato a state React, incluso nel payload di salvataggio e persistito in DB. Incluso anche nell'export CSV.
  - **[ux] Bottoni Aggiungi anomalia e Duplica**: il bottone "Anomalia" ora chiama `handleNewAnomalia()` (svuota form, pronto per nuovo record sull'OP selezionato). Il bottone "Duplica" mantiene i dati del form ma azzera `item_id` (force INSERT). Il bottone "Segnalazione" attiva il toggle `segnalare` e avvisa l'utente.
  - **[audit] Audit trail anomalie**: ogni salvataggio (`api_salva`) registra `anomalia_creata` o `anomalia_modificata` in `AuditLog` tramite `core.audit.log_action`. Anche `api_sync` registra l'evento `anomalie_sync`.
  - **[notifiche] Notifiche in-app anomalie**: `api_salva` emette notifiche in-app (modello `Notifica`) in due casi: (1) `segnalare_cliente=1` ? tenta lookup capocommessa su `ordini_produzione + utenti` e notifica; (2) `chiudere=1` ? notifica l'autore originale (da `created_by_user_id`) se diverso dall'utente corrente. Fire-and-forget, silente in caso di errore.
  - **[refactor] Rinominate view `api_*_placeholder`**: `api_salva_placeholder` ? `api_salva`, `api_sync_placeholder` ? `api_sync`, `api_ordini_placeholder` ? `api_ordini`, `api_anomalie_placeholder` ? `api_anomalie`, `api_campi_placeholder` ? `api_campi`. URL names invariate, nessun breaking change.
  - **[model] Notifica.TIPI estesa**: aggiunti `anomalia_segnalata` e `anomalia_chiusa` alla lista choices del modello `Notifica`. Migration `core.0011_alter_notifica_tipo`.

## 0.6.1-dev - 2026-03-03

- **[ux] Dashboard "Gestione Accessi"**: nuova pagina `/admin-portale/accessi/` — punto unico per ruoli, permessi, pulsanti e override utenti. Mostra statistiche (N ruoli / N pulsanti / N override), tabella ruoli con barra di avanzamento permessi attivi, tabella override utenti recenti con chip ON/OFF/ruolo, link rapidi agli strumenti ACL. View `accessi_dashboard` in `admin_portale/views.py`.
- **[ux] Wizard "Configura Ruolo"**: nuovo flusso guidato a 3 step in `/admin-portale/wizard-ruolo/`. Step 1: selezione ruolo con pulsanti cliccabili (pre-selezione da `?ruolo_id=X`). Step 2: card grid per modulo con toggle `can_view` per ogni pulsante + expand "dettagli" per `can_edit`/`can_delete`/`can_approve` + pulsanti "Tutto ON/OFF" per modulo. Step 3: tabella diff con solo le righe cambiate (badge ON?OFF / OFF?ON), salvataggio via `POST api_permessi_bulk mode=update`, redirect alla dashboard accessi. View `wizard_ruolo` in `admin_portale/views.py`.
- **[ux] Permessi — layout card grid**: `permessi.html` refactored da flat expandable list a griglia di card per modulo (auto-fill min 300px). Ogni card mostra icona modulo, conteggio pulsanti, badge "parziale", toggle modulo, e lista pulsanti con toggle `can_view`. Aggiunto pulsante "?? Apri Wizard ?" nella toolbar (solo modalità ruolo). Logica JS invariata (stesse API).
- **[nav] Subnav "Accessi"**: aggiunto link "Accessi" nella subnav admin (tra "Utenti" e "Permessi"), attivo per `admin_portale:accessi` e `admin_portale:wizard_ruolo`. Aggiunti testi help contestuali per entrambe le nuove pagine.
- **[nav] Home admin — card aggiornata**: card "Gestione Permessi" rinominata in "Gestione Accessi" e punta alla nuova dashboard `/admin-portale/accessi/`.
- **[fix] wizard_ruolo.html — filtro `|tojson` inesistente**: sostituito `{{ url|tojson }}` con `"{{ url|escapejs }}"` (Django built-in) per i valori `api_bulk_url` e `accessi_url`.

## 0.6.0-dev - 2026-03-02
- **[feature] App Notizie / Comunicazioni**: nuova app Django `notizie` per la gestione delle comunicazioni aziendali con prova di lettura versionata e audit trail. Modelli: `Notizia` (bozza/pubblicata/archiviata, campo `obbligatoria`), `NotiziaAudience` (audience per ruolo legacy, nessun record = visibile a tutti), `NotiziaAllegato` (upload file + link esterni, SHA-256 automatico), `NotiziaLettura` (versioned: `unique_together = (notizia, legacy_user_id, versione_letta)` per audit completo). Hash versione SHA-256 su titolo+corpo+versione+allegati (escluso `id`). Compliance: `non_letto` / `aperto` / `conforme` / `non_conforme` (nuova versione ? non conforme senza cancellare storia).
- **[feature] Notizie — Admin Django**: `NotiziaAdmin` con inline allegati e letture (read-only), azioni admin `pubblica_notizie` e `archivia_notizie`, filtri per stato/obbligatoria, ricerca per titolo.
- **[feature] Notizie — Viste e URL**: `notizie_lista` (filtri ruolo + badge compliance), `notizie_dettaglio` (tracking `opened_at` automatico), `notizie_conferma` POST idempotente con log e invalidazione cache, `notizie_obbligatorie` (safe path), `notizie_report` (solo admin/hr, filtri notizia/stato/data), `notizie_report_csv` (`StreamingHttpResponse`, encoding `utf-8-sig`).
- **[feature] Notizie — Gating middleware** (`NotizieMandatoryMiddleware`): posizionato dopo `ACLMiddleware`, blocca accesso al portale se l'utente ha notizie obbligatorie non confermate (redirect a `/notizie/obbligatorie/`). Tutta la prefix `/notizie/` è safe. Cache TTL 60s con invalidazione esplicita dopo conferma.
- **[feature] Notizie — ACL bootstrap**: pulsanti `notizie_lista` e `notizie_report` registrati via `acl_bootstrap.py` (pattern identico a `assenze`), chiamato in `AppConfig.ready()`.
- **[feature] Notizie — Navigation Registry**: voce `notizie` aggiunta in `topbar` (order 50) via data migration `0002_nav_entry`.
- **[fix] Login redirect corretto**: `LOGIN_REDIRECT_URL = "dashboard_home"` (era `"dashboard"`, causava redirect a view fittizia). Corretti anche `reverse("dashboard")` ? `reverse("dashboard_home")` in `accounts/views.py` e `windows_sso.py`.
- **[fix] `requests` aggiunto a requirements.txt**: dipendenza mancante che causava `ModuleNotFoundError` in ambienti puliti.
- **[fix] `SQL_LOG_ENABLED` default prod**: cambiato da `True` a `False` in `base.py` (evitava log query SQL massiccio in produzione per default).
- **[fix] `import tempfile` mid-file**: spostato all'inizio del file in `base.py`, rimosso duplicato.
- **[refactor] `provision_legacy_user` centralizzato**: estratto in `core/legacy_utils.py`, eliminando la duplicazione tra `LDAPBackend.authenticate()` e `windows_sso._get_or_create_user()`. Aggiunto `_normalize_principal()` in `windows_sso.py` per uniformare UPN/NTLM.
- **[refactor] `MIDDLEWARE_EXEMPT_PREFIXES` centralizzato**: tupla unica in `base.py`, entrambi i middleware (`session_middleware.py`, `middleware.py`) la leggono via `getattr(settings, ...)`.
- **[perf] `_load_ini()` singleton**: in `assenze/views.py` il parser `ConfigParser` viene istanziato una volta sola a livello di modulo invece di ogni richiesta.
- **[security] X-Forwarded-For sanitizzato**: `_get_client_ip` in `core/audit.py` usa l'header `X-Forwarded-For` solo se `REMOTE_ADDR` è in `TRUSTED_PROXY_IPS` (impostazione `base.py`). Prevenuto IP spoofing su installazioni senza reverse proxy.
- **[ops] File morti rimossi**: eliminati `rwe.py`, `test_structure.py`, `update db.py`, `users.json`, `___All_Errors.txt`, `app.spec`, `app.log`, `opzione_C.html`.
- **[test] Suite notizie**: 21 test (`HashVersioneTests`, `AudienceTests`, `ComplianceTests`, `NotizieACLTests`, `PrisaVisioneTests`, `GatingMiddlewareTests`) — verdi su SQLite (dev) e SQL Server (prod). Fix: helpers usano `Profile` come fallback (tabella `utenti` unmanaged non disponibile in test DB); `SECURE_SSL_REDIRECT=False` aggiunto agli `@override_settings` per compatibilità test su prod settings.

## 0.5.5-dev - 2026-03-02
- **[model] Relazione esplicita `utenti` ? `anagrafica_dipendenti`**: aggiunto `OneToOneField utente` (db_column `utente_id`) su `AnagraficaDipendente` con FK verso `UtenteLegacy`. Chiarito in commento che `utenti.email` è un login_id UPN (es. `l.bova@example.local`), non un'email reale.
- **[model] Campo `email_notifica` su `anagrafica_dipendenti`**: nuovo campo per l'email reale di notifica (es. `l.bova@example.com`), separata dal login_id.
- **[ops] Import CSV con provisioning FK e `email_notifica`**: `import_dipendenti_csv --sync-legacy-users` ora popola `anagrafica_dipendenti.utente_id` (FK verso `utenti.id`) e accetta colonna opzionale `EMAIL_NOTIFICA` dal CSV. `_ensure_extra_columns()` aggiunge automaticamente le colonne `mansione`, `email_notifica` e `utente_id` se assenti (SQLite e SQL Server).
- **[fix] Matching anagrafica con FK**: in `/admin-portale/utenti/` e scheda utente, `_attach_anagrafica_to_users()` e `utente_edit` ora usano il JOIN tramite `utente_id` come lookup primario, con fallback email/alias per record legacy non ancora collegati.
- **[auth] Password locale sempre attiva**: ordine `AUTHENTICATION_BACKENDS` confermato con `SQLServerLegacyBackend` prima di `LDAPBackend` — la password offline configurata localmente continua a funzionare anche quando AD è disponibile; la password AD funziona come secondo metodo tramite `LDAPBackend`.
- **[ops] Import iniziale dipendenti**: eseguito import live da `DIPENDENTI.csv` (371 righe): 139 aggiornati, 137 nuovi utenti legacy creati, 232 saltati (senza username). Colonne `email_notifica` e `utente_id` aggiunte automaticamente al DB.

## 0.5.4-dev - 2026-03-01
- **[feature] Import CSV dipendenti (anagrafica centralizzata)**: aggiunto comando `python manage.py import_dipendenti_csv <file.csv>` per importare/aggiornare `anagrafica_dipendenti` da file HR con mapping `USERNAME -> aliasusername`, normalizzazione automatica di formati `alias`, `dominio\alias`, `alias@dominio`, opzioni `--dry-run`, `--limit`, `--email-domain`, `--overwrite-email`.
- **[feature] Login offline più robusto per alias AD**: `SQLServerLegacyBackend` ora risolve l'utente legacy anche partendo da alias Windows/LDAP (`l.bova`, `EXAMPLE\l.bova`, `l.bova@example.local`) con fallback su `anagrafica_dipendenti.aliasusername -> email`.
- **[ops] Provisioning utenti legacy opzionale da import**: il comando CSV supporta `--sync-legacy-users` per creare/allineare anche la tabella `utenti` (offline login), con password iniziale esplicita via `--default-password`.
- **[model] Anagrafica legacy estesa: colonna `mansione`**: `import_dipendenti_csv` ora supporta il campo CSV `MANSIONE` e, per SQL Server/SQLite, può aggiungere automaticamente la colonna `anagrafica_dipendenti.mansione` se assente (disattivabile con `--no-ensure-schema`).
- **[feature] Sezione Organigramma**: nuova pagina `/organigramma/` con vista gerarchica reparto -> mansione -> persone, filtri per reparto/mansione/ricerca testuale e integrazione in subnav.
- **[ux] Rubrica/Profilo/Scheda Utente**: visualizzazione `mansione` aggiunta nelle pagine utente (`/rubrica/`, `/profilo/`, `/admin-portale/utenti/<id>/` tab Anagrafica) con fallback sicuro quando la colonna non è disponibile.
- **[ux] Pulsante upload CSV da UI**: in `/admin-portale/anagrafica-config/` aggiunta card `Import dipendenti (CSV)` con selezione file, dominio email e opzione dry-run; l'import lancia internamente il comando `import_dipendenti_csv` e mostra esito via flash message.
- **[ux] Tabella utenti con colonne configurabili**: in `/admin-portale/utenti/` aggiunte colonne anagrafiche (`reparto`, `mansione`, `username AD`) e nuovo pulsante `Colonne` per mostrare/nascondere le colonne visibili. La preferenza viene salvata localmente nel browser (persistenza per utente/macchina).
- **[ops] Import CSV da UI con provisioning utenti offline**: la card `Import dipendenti (CSV)` ora include opzione `Crea/Aggiorna utenti login offline` + password iniziale; quando attiva passa `--sync-legacy-users` al comando di import.
- **[fix] Matching anagrafica in lista utenti**: in `/admin-portale/utenti/` l'aggancio dati anagrafici ora usa sia email sia alias AD (local-part email), migliorando la compilazione delle colonne per domini email diversi.

## 0.5.3-dev - 2026-03-01
- **[ops] SQL log dedicato**: aggiunto logging SQL su file rotante `logs/sql.log` (logger `django.db.backends`) con configurazione via `.env` (`SQL_LOG_ENABLED`, `SQL_LOG_LEVEL`, `SQL_LOG_FORCE_DEBUG_CURSOR`, `SQL_LOG_MAX_BYTES`, `SQL_LOG_BACKUP_COUNT`). Introdotto hook `connection_created` per forzare `debug cursor` quando richiesto e tracciare query/tempi in modo consistente.
- **[model] Migration core 0009**: aggiunge il campo `categoria` ai modelli `AnagraficaVoce` (default `Campi extra`) e `ChecklistVoce` (default `Generale`).
- **[feature] Categorie per campi configurabili (Anagrafica + Checklist)**: introdotto campo `categoria` per `AnagraficaVoce` e `ChecklistVoce` con gestione da UI admin (modali create/edit). I campi sono ora visualizzati raggruppati per categoria nella scheda utente (`/admin-portale/utenti/<id>/`, tab Anagrafica) e nelle esecuzioni checklist (`/admin-portale/checklist/utenti/<id>/`).
- **[audit] Checklist con storico completo**: aggiunto audit trail su create/update/toggle/delete delle `ChecklistVoce` e su ogni esecuzione checklist (`api_checklist_esegui`) con snapshot risposte (voce, tipo, valore), utente target e metadati. Consultabile in `/admin-portale/audit/` filtrando modulo `admin_checklist`.
- **[audit] Tracciamento completo campi extra anagrafica**: aggiunto audit trail su create/update/toggle/delete delle `AnagraficaVoce`, salvataggio `UserExtraInfo` e modifiche valori `AnagraficaRisposta` (before/after, utente target, conteggio cambi). Storico consultabile in `/admin-portale/audit/` filtrando modulo `admin_anagrafica`.
- **[ux] Checklist utente - link rapido configurazione voci**: in `/admin-portale/checklist/utenti/<id>/` aggiunti link sempre visibili `+ Aggiungi/Configura voci` nelle card Check-in/Check-out, per accedere subito alla pagina di setup globale `/admin-portale/checklist/` ed evitare blocchi operativi.
- **[arch] Caporeparto locale e indipendente da SharePoint**: la card `Capireparto` in `/admin-portale/anagrafica-config/` e il campo `Caporeparto` nella scheda utente tornano a usare `OptioneConfig` locale. CRUD live riattivato per tipo `caporeparto`, senza dipendenze da SharePoint o dalla tabella legacy `capi_reparto`.
- **[feature] Gestione reparto per admin e caporeparto**: nuova pagina `/gestione-reparto/` con salvataggio AJAX per assegnare `reparto` e `caporeparto` agli utenti tramite `UserExtraInfo`. Gli admin possono impostare entrambi i valori; i capireparto possono assegnare utenti solo al proprio reparto.
- **[feature] Anagrafica configurabile â€” dropdown e campi extra**: nuova pagina admin `/admin-portale/anagrafica-config/` per configurare le liste di opzioni e i campi extra del profilo dipendente. I campi Â«RepartoÂ», Â«CaporepartoÂ» e Â«Macchina di utilizzoÂ» nel tab Anagrafica della scheda utente diventano `<select>` quando le rispettive liste sono configurate (graceful degradation a `<input text>` se vuote). Admin puÃ² aggiungere nuovi reparti, capireparto e macchine dalla pagina di config. Aggiunta sezione Â«Campi extraÂ» con pulsante Â«+ Aggiungi campoÂ» (analogo alle voci checklist): campi configurabili di tipo testo, checkbox, data o scelta da lista, visibili e compilabili nel tab Anagrafica di ogni utente. Campo `reparto` aggiunto a `UserExtraInfo` (editabile separatamente dal reparto read-only di `anagrafica_dipendenti`).
- **[model] Migration core 0008**: aggiunge `reparto` a `UserExtraInfo`, crea modelli `OptioneConfig`, `AnagraficaVoce`, `AnagraficaRisposta`.
- **[api] Nuovi endpoint anagrafica**: `api_opzione_create/update/toggle/delete`, `api_anagrafica_voce_create/update/toggle/delete`, `api_anagrafica_risposte_save`.

## 0.5.2-dev - 2026-03-01
- **[feature] Wizard Onboarding / Offboarding (Check-in / Check-out)**: nuovo sistema per tracciare assunzioni e dimissioni. Voci configurabili dall'admin (checkbox, testo libero, data, scelta da lista) via pulsante Â«+ Aggiungi voceÂ» in `/admin-portale/checklist/`. Voci globali (si applicano a tutti gli utenti). Esecuzione da `/admin-portale/checklist/utenti/<id>/` con form per check-in e check-out, storico espandibile per utente. Tab Â«ChecklistÂ» aggiunto alla scheda utente con sommario e link diretto. Vista globale `/admin-portale/checklist/` mostra stato check-in/out di tutti i dipendenti attivi.
- **[model] Migration core 0007**: aggiunge modelli `ChecklistVoce`, `ChecklistEsecuzione`, `ChecklistRisposta` al DB Django.
- **[perf] Fix N+1 in checklist_index**: il calcolo dello stato per N utenti ora usa 2 query bulk invece di 2N query individuali.

## 0.5.1-dev - 2026-03-01
- **[feature] Scheda anagrafica utente**: la scheda utente admin (`/admin-portale/utenti/<id>/`) aggiunge un 4Â° tab Â«AnagraficaÂ». Sezione in sola lettura con dati da `anagrafica_dipendenti` (nome completo, reparto, email aziendale, username AD, stato dipendente). Sezione editabile con nuovo modello `UserExtraInfo`: caporeparto, macchina di utilizzo (placeholder futura gestione asset), telefono, cellulare, note. Salvataggio AJAX via `POST /admin-portale/api/utenti/<id>/extra-info`. Dati visibili anche nel profilo personale (`/profilo/`) nella nuova card Â«Reparto & ContattiÂ» (solo sezioni compilate).
- **[model] Migration core 0006**: aggiunge modello `UserExtraInfo` al DB Django.

## 0.5.0-dev - 2026-03-01
- **[security] Fix CSRF anomalie (H1)**: rimosso `@csrf_exempt` da `api_salva_placeholder` e `api_sync_placeholder` in `anomalie/views.py`. Il template React ora legge il cookie `csrftoken` e invia l'header `X-CSRFToken` su tutti i POST. Eliminato import `csrf_exempt` non piÃ¹ utilizzato.
- **[feature] Profilo utente** (`/profilo/`): nuova pagina personale accessibile a tutti gli utenti autenticati. Mostra nome, email, username, ruolo, stato account legacy. Link diretto a Â«Cambia passwordÂ». L'avatar nella topnav Ã¨ ora un link cliccabile che porta al profilo.
- **[feature] Rubrica aziendale** (`/rubrica/`): pagina di consultazione dipendenti attivi dalla tabella `anagrafica_dipendenti`. Filtro per nome/cognome/email e per reparto. Tabella card-style con avatar iniziali, email cliccabile `mailto:`, username.
- **[feature] Centro notifiche**: nuovo modello `Notifica` (Django-managed). Triggered in `api_car_aggiorna_consenso` dopo approvazione/rifiuto assenza per notificare il richiedente (lookup per `email_esterna`). Badge campanella ðŸ”” nella topnav (con contatore rosso se non lette). Pagina `/notifiche/` con lista cronologica; le notifiche vengono marcate come lette all'apertura della pagina.
- **[feature] Audit log**: nuovo modello `AuditLog` (Django-managed). Helper `core/audit.py` â†’ `log_action()` fire-and-forget. Agganciato a: `api_car_aggiorna_consenso` (assenza_moderata), `api_user_perm_override` (override_permesso), `cambia_password` (cambio_password). Vista admin `/admin-portale/audit/` con filtri per modulo, azione e data; paginazione 50 per pagina.
- **[feature] Dashboard contestuale per ruolo**: il widget di benvenuto ora cambia contenuto in base al ruolo. CAR/Capo Reparto: lista delle prime 5 richieste in attesa del reparto con link diretto alla car_dashboard. AMMIN/Admin: prime 5 richieste in attesa globali. Operaio: stato della propria ultima richiesta con badge colorato.
- **[feature] Health check admin** (`/admin-portale/health/`): pagina diagnostica per admin con 6 check: DB Django, DB Legacy (tabella utenti), Azure MSAL config, file di log, sessioni attive, modello Notifica. Indicatori OK/Errore con dettaglio testuale; pulsante Â«AggiornaÂ».
- **[feature] Export CSV**: pulsante Â«Esporta CSVÂ» nella car_dashboard (esporta assenze reparto, incluso storico gestite) e in gestione_assenze (esporta richieste personali). Endpoint `/anomalie/export-csv` per anomalie. Usa `StreamingHttpResponse` + `csv` stdlib (nessuna dipendenza esterna). Encoding `utf-8-sig` per compatibilitÃ  Excel.
- **[model] Migration core 0005**: aggiunge modelli `Notifica` e `AuditLog` al DB Django (SQLite/SQL Server).

## 0.4.9-dev - 2026-03-01
- **[feature] Note al rifiuto (CAR)**: quando un CAR rifiuta una richiesta, puÃ² ora inserire un motivo opzionale nella textarea inline che compare sotto la riga al click di Â«RifiutaÂ». La nota viene salvata nel campo `note_gestione` della tabella `assenze` e visualizzata nella sezione Â«Ultime gestiteÂ» (colonna Â«Note rifiutoÂ»). L'utente richiedente vede la nota direttamente sotto lo stato Â«RifiutatoÂ» nella propria pagina Gestione. Aggiunto management command `aggiungi_note_gestione` per aggiungere la colonna al DB (SQLite e SQL Server).
- **[feature] Badge "in attesa" (topbar e subnav)**: il numero di richieste in attesa del proprio reparto appare accanto al link Â«SegnalazioniÂ» nel subnav assenze e come indicatore rosso nella topbar (angolo in alto a destra), visibile a tutti i CAR con richieste pendenti. Calcolato tramite context processor `legacy_nav` con query COUNT leggera per ogni richiesta autenticata.
- **[feature] Modifica richiesta Â«In attesaÂ»**: un utente puÃ² ora modificare (tipo, date, motivazione) le proprie richieste finchÃ© sono in stato Â«In attesaÂ». Pulsante Â«ModificaÂ» nella tabella personale (visibile solo per le righe In attesa); apertura modal con form, AJAX POST al nuovo endpoint `POST /assenze/api/mia/<id>/update` (`api_mia_assenza_update`). La modifica non altera il consenso e sincronizza con SharePoint. Aggiunto `tipo_raw`, `inizio_iso`, `fine_iso`, `note_gestione` all'output di `_load_personal`.

## 0.4.6-dev - 2026-03-01
- **[ux] Gestione assenze â€” elimina richiesta**: il pulsante Â«DuplicaÂ» nella tabella Â«Le tue richiesteÂ» Ã¨ stato sostituito con Â«EliminaÂ». La rimozione avviene via AJAX (nessun reload), con confirm dialog e fade-out della riga. L'API `api_evento_delete` ora permette a qualsiasi utente autenticato (`can_insert`) di eliminare le proprie richieste verificando la corrispondenza di `copia_nome`/`email_esterna`; l'amministratore puÃ² eliminare qualsiasi record. L'eliminazione propaga anche su SharePoint se configurato.

## 0.4.5-dev - 2026-03-01
- **[feature] Dashboard Segnalazioni CAR**: nuova pagina `/assenze/car/dashboard` accessibile da CAR e AMMINISTRAZIONE. I CAR vedono solo le assenze del proprio reparto; gli admin vedono tutte le richieste. Quattro sezioni: Â«Richieste in attesaÂ» (con pulsanti Approva/Rifiuta in-page), Â«Assenze oggiÂ», Â«Questa settimanaÂ», Â«Ultime gestiteÂ». L'approvazione/rifiuto avviene via AJAX e sincronizza automaticamente con SharePoint.
- **[feature] API consenso CAR**: nuovo endpoint `POST /assenze/api/car/consenso/<item_id>` (`api_car_aggiorna_consenso`) per approvare/rifiutare assenze. Accessibile da CAR (solo record del proprio reparto) e da AMMINISTRAZIONE (qualsiasi record). Aggiorna `consenso`, `moderation_status` e sincronizza su SharePoint.
- **[refactor] Helper assenze**: aggiunti `_load_gestite_for_manager`, `_load_assenze_car_periodo`, `_load_all_pending`, `_load_all_gestite`, `_load_all_assenze_periodo` per supportare le diverse viste per ruolo.
- **[ux] Subnav assenze**: aggiunto link Â«SegnalazioniÂ» visibile a CAR e AMMINISTRAZIONE (`assenze_can_edit_events`). Menu assenze aggiornato con card accesso rapido differenziata per ruolo.

## 0.4.4-dev - 2026-03-01
- **[ux] Navigation Builder â€” selezione ad elenco**: i campi Â«Route nameÂ» (form creazione, tabella inline, redirect) ora supportano selezione dall'elenco delle route Django disponibili tramite `<datalist>` (si puÃ² ancora digitare liberamente). Il campo Â«SezioneÂ» Ã¨ diventato un `<select>` con opzioni fisse (topbar/sidebar/page). Il campo Â«Ruoli abilitatiÂ» Ã¨ ora un `<select multiple>` con tutti i ruoli legacy nominati (Ctrl+click per piÃ¹ ruoli); la serializzazione CSV Ã¨ gestita in JS e compatibile con le API esistenti. Pre-selezione ruoli in tabella gestita via `data-role-ids` e inizializzazione JS.
- **[ux] Navigation Builder â€” descrizioni e semplificazione**: ogni campo e sezione ha testo esplicativo inline (`field-help`). La sezione Â«Ruoli LegacyÂ» Ã¨ collassabile (`<details>`). L'import da legacy Ã¨ stato separato in una card dedicata con pulsante Â«MergeÂ» (sicuro) e Â«Sovrascrivi tuttoÂ» (distruttivo, con confirm). Aggiunto confirm dialog su Elimina voce, Elimina redirect e Ripristina snapshot. Aggiunta colonna Â«TabÂ» nella tabella voci (open_in_new_tab precedentemente assente).

## 0.4.3-dev - 2026-03-01
- **[feature] Permessi: expand pulsante per pulsante**: cliccando su una riga modulo si espande il sottoelenco con tutti i pulsanti, ognuno con il proprio toggle. Funziona sia in modalitÃ  Ruolo che Utente. Lo stato "parziale" del modulo si aggiorna automaticamente dopo ogni modifica singola.
- **[refactor] Permessi helpers**: aggiunto `_aggregate_to_module_rows`, `_full_perm_rows_for_user`, `_build_perm_detail`; eliminata doppia query nel view `permessi`.

## 0.4.2-dev - 2026-03-01
- **[feature] Permessi per modulo**: `/admin-portale/permessi/` completamente ridisegnata. Sostituita la matrice granulare (modulo + azione) con vista semplificata a toggle per modulo: ogni riga rappresenta un modulo con un solo interruttore che abilita/disabilita l'accesso per tutti i pulsanti del modulo in un click. Lo stato "parziale" Ã¨ evidenziato in giallo.
- **[feature] Permessi per ruolo o per utente**: la pagina supporta due modalitÃ  con tab "Per Ruolo" / "Per Utente". In modalitÃ  Ruolo modifica la tabella `permessi` (impatta tutto il ruolo). In modalitÃ  Utente scrive `UserPermissionOverride` come override personale indipendente dal ruolo.
- **[feature] API modulo-level**: `POST /admin-portale/api/permessi/modulo-set` e `POST /admin-portale/api/utenti/<id>/modulo-perm-set` per bulk can_view di tutti i pulsanti di un modulo.
- **[refactor] Permessi bulk conservati**: "Tutto ON", "Tutto OFF", "Reset ruolo", "Copia da ruolo" rimangono in modalitÃ  Ruolo e riusano le API bulk esistenti.

## 0.4.1-dev - 2026-03-01
- **[fix] Dashboard reset al riavvio**: il tasto Ã— nella modalitÃ  Modifica ora salva la preferenza in `UserDashboardConfig` (modello Django, persistente con migrazioni) invece di `ui_pulsanti_meta` (raw SQL, persa se il DB viene ricreato). Il pannello "Moduli nascosti" mostra i moduli nascosti per l'utente corrente letti dalla stessa tabella.
- **[feature] Edit mode dashboard per tutti gli utenti**: il pulsante "Modifica" Ã¨ ora visibile a tutti gli utenti (non solo admin). Ogni utente puÃ² decidere autonomamente quali moduli vedere nella propria dashboard. Il tasto Ã— nasconde il modulo solo per se stessi; "Mostra" lo riabilita. La configurazione Ã¨ per-utente e persiste tra i riavvii.
- **[feature] API per-utente dashboard**: nuova API `POST /api/my-dashboard-toggle` (`api_my_dashboard_toggle`) accessibile da tutti gli utenti autenticati; gestisce hide/show personale tramite `UserDashboardConfig`. Il tasto "+ Nuovo" (wizard pulsante) rimane visibile solo agli admin.

## 0.4.0-dev - 2026-03-01
- **[feature] Navigation Registry v2 (strutturale)**: introdotti modelli Django-managed `NavigationItem`, `NavigationRoleAccess`, `NavigationSnapshot`, `LegacyRedirect` per centralizzare menu, regole ruolo, versionamento configurazione e redirect legacy configurabili.
- **[feature] Navigation Builder (no-code)**: nuova pagina admin `/admin-portale/navigation-builder/` con gestione voci menu (CRUD), mapping ruoli (CSV), publish snapshot e rollback snapshot, oltre alla gestione redirect legacy senza modifiche a codice.
- **[feature] Cache versionata navigazione**: nuovo modulo `core/navigation_registry.py` con cache per ruolo/sezione e invalidazione controllata (`bump_navigation_registry_version`) per ridurre query ripetute su topbar e migliorare stabilita' runtime.
- **[feature] Topbar con fallback robusto**: `core/context_processors.py` ora tenta prima la sorgente Navigation Registry v2 (se abilitata) e ricade automaticamente sulla logica legacy `pulsanti/ui_pulsanti_meta` in assenza dati o in caso errore.
- **[feature] Redirect legacy DB-driven**: `core/legacy_flask_views.py` supporta redirect da tabella `LegacyRedirect` prima della mappa hardcoded, migliorando gestibilita' operativa durante la transizione.
- **[feature] UI admin allineata**: aggiunti collegamenti `Navigation Builder` nella home admin e nella subnav per accesso centralizzato.
- **[infra] Flag configurazione**: aggiunto `NAVIGATION_REGISTRY_ENABLED` in settings per attivare/disattivare la nuova sorgente menu senza deploy di codice.
- **[db] Migrazione core**: aggiunta `core.0003_legacyredirect_navigationitem_navigationsnapshot_and_more`.
- **[docs] Guida moduli programma**: creato `GUIDA_MODULI_PROGRAMMA.html` (stile visual) per spiegare in modo chiaro cosa fanno i moduli e dare una visione sintetica dell'architettura/funzionamento del portale.

## 0.3.29-dev - 2026-03-01
- **[fix] Dashboard admin**: il tasto "Modifica" ora appare anche per i superuser Django senza profilo legacy (`request.user.is_superuser` usato come fallback in `is_admin`).
- **[feature] Scheda utente unificata**: la pagina `/admin-portale/utenti/<id>/` Ã¨ stata ridisegnata con tre tab â€” **Info** (dati base, invariati), **Permessi** (matrice permessi del ruolo + override personali per ogni flag), **Dashboard** (pulsanti accessibili con toggle visibilitÃ  per-utente). Le modifiche si salvano via AJAX senza ricaricare la pagina.
- **[feature] Override permessi per-utente**: nuovo modello `UserPermissionOverride` (Django-managed) che permette di sovrascrivere singoli flag (`can_view`, `can_edit`, `can_delete`, `can_approve`) per uno specifico utente, indipendentemente dal ruolo. La logica ACL in `core/acl.py` controlla prima l'override, poi il ruolo. Nuova API `POST /admin-portale/api/utenti/<id>/perm-override`.
- **[feature] Dashboard per-utente**: nuovo modello `UserDashboardConfig` (Django-managed) che permette di nascondere specifici pulsanti dalla dashboard di un singolo utente. `_module_cards()` ora filtra per configurazione utente. Nuova API `POST /admin-portale/api/utenti/<id>/dashboard-toggle`. La diagnostica ACL (`core/acl.py`) mostra anche l'override attivo nell'output di debug.

## 0.3.28-dev - 2026-03-01
- **[feature] Edit mode dashboard**: gli amministratori vedono un pulsante "Modifica" nella card "Moduli disponibili" della dashboard. In edit mode: ogni modulo mostra un Ã— per nasconderlo (imposta `enabled=false` in `ui_pulsanti_meta`), un pannello "Moduli nascosti" permette di riabilitarli, il tasto "+ Nuovo" collega al wizard. Aggiunta API `POST /admin-portale/api/pulsanti/set-enabled` che aggiorna solo il flag `enabled`. Il flag filtra i moduli mostrati a tutti gli utenti senza riavvio (cache invalidata).

## 0.3.27-dev - 2026-03-01
- **[feature] Wizard nuovo pulsante**: aggiunto flusso guidato 4 step (`/admin-portale/wizard-pulsante/`) per creare un pulsante, configurarne la posizione UI (slot/sezione/ordine/topbar/attivo) e assegnare i permessi per ogni ruolo con preset rapidi (Nessuno / Sola lettura / Lettura+Scrittura / Completo) ed espansione ai singoli flag. Il salvataggio Ã¨ atomico e invalida subito la cache ACL legacy affinchÃ© il pulsante appaia nel menu senza riavvio. Link di accesso rapido aggiunto nella pagina "Pulsanti" dell'admin portale.

## 0.3.26-dev - 2026-03-01
- **[C1] Fix dead code anomalie**: corretta funzione `_resolve_op_lookup_id` in `anomalie/views.py` â€” il lookup per titolo OP era irraggiungibile (codice dopo `return fields`); logica spostata nel posto corretto.
- **[H2] Datetime timezone-aware**: eliminato uso di `datetime.utcnow()` (deprecated, naive) in `anomalie/views.py`; standardizzato a `datetime.now(timezone.utc)` con guard `isinstance(exp, datetime)` sulla cache token. Fix anche a `datetime.now()` naive in `assenze/views.py`.
- **[H4] Shared Graph token cache**: creato `core/graph_utils.py` con `acquire_graph_token()` thread-safe condiviso; eliminata duplicazione della logica MSAL e della cache token tra `assenze/views.py` e `anomalie/views.py`. Rimosso anche `_is_placeholder_value()` duplicato.
- **[C3] TrustServerCertificate configurabile**: il flag SQL Server non Ã¨ piÃ¹ hardcoded a `yes`; ora controllato da variabile env `DB_TRUST_CERT` (default `0`/no). Dev locale imposta `DB_TRUST_CERT=1` nel `.env`.
- **[M2] Log rotation**: sostituito `logging.FileHandler` con `logging.handlers.RotatingFileHandler` (5 MB max, 5 backup) per evitare crescita illimitata di `app.log`.
- **[L1] HTTPS prod**: aggiunti in `config/settings/prod.py`: `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` (1 anno), `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`.

## 0.3.25-dev - 2026-02-27
- LDAP diagnostica fix: corretto `_ldap_test_connect` (`/admin-portale/ldap/`) per gestire il comportamento `ldap3` dove `Connection.open()` puo' restituire `None` anche con socket aperto.
- UX diagnostica LDAP: eliminato falso negativo "Connessione LDAP fallita: None"; ora la connessione viene considerata riuscita quando `conn.closed` e' `False`, con fallback errore piu' leggibile.

## 0.3.24-dev - 2026-02-27
- Stabilita' esecuzione Django: aggiunto `manage.py` in root progetto come entrypoint unico, cosi' da lanciare i comandi Django sempre da root (`python manage.py ...`) senza dipendere dalla cartella attiva.
- VS Code hardening: debug config root aggiornata per usare il nuovo `manage.py` root e task dedicati (`runserver`, `check`) con interpreter esplicito della venv.
- Workspace multiplo: allineate anche le configurazioni `.vscode` dentro `django_app/` per apertura sia della root che della sola cartella app, evitando mismatch path interpreter.

## 0.3.23-dev - 2026-02-27
- VS Code interpreter resolution fix: rimosso uso di `${workspaceFolder}` per Python path nelle configurazioni di debug/settings, sostituito con percorsi relativi stabili (`.\\.venv\\Scripts\\python.exe`).
- Workspace support: aggiunti file `.vscode` anche dentro `django_app/` per coprire sia apertura workspace root sia apertura diretta della sola cartella `django_app`.
- Terminal policy workaround: impostato `python.terminal.activateEnvironment=false` per evitare errori PowerShell su `Activate.ps1` con execution policy restrittiva.

## 0.3.22-dev - 2026-02-27
- VS Code debug fix: aggiunto `.vscode/launch.json` con configurazioni esplicite Django (`runserver` e `shell`) puntate a `django_app/manage.py`, evitando l'esecuzione accidentale di file non Python (es. `config.ini`).
- VS Code Python interpreter: impostato `python.defaultInterpreterPath` su `.venv\\Scripts\\python.exe` in `.vscode/settings.json` per allineare debug/terminal all'ambiente virtuale corretto.

## 0.3.21-dev - 2026-02-27
- LDAP Admin UI: aggiunto pulsante/azione "Sync utenti LDAP" nella pagina diagnostica LDAP (`/admin-portale/ldap/`) con esecuzione diretta del comando `sync_ldap_users`.
- Sync LDAP da web: supporto opzioni da form (`dry-run`, `limit`, override allowlist, replace memberships) e output risultato mostrato nella stessa pagina.
- Diagnostica LDAP estesa: visualizzati anche i parametri di sync (`service_user`, `base_dn`, `user_filter`, `group_allowlist`, `sync_page_size`) per ridurre ambiguita' operative.

## 0.3.20-dev - 2026-02-27
- Layout globale rifinito: contenitore principale `.content` centrato orizzontalmente con larghezza massima (`min(100%, 1600px)`), evitando il blocco UI allineato solo a sinistra su monitor larghi.

## 0.3.19-dev - 2026-02-27
- Layout globale: area contenuti principale resa full-width su tutte le pagine (`.content`), eliminando il vincolo `max-width: 1400px` per evitare sezioni "compresse".

## 0.3.18-dev - 2026-02-27
- LDAP import utenti/gruppi: nuovo comando `python manage.py sync_ldap_users` per importare utenti da AD con supporto membership multipla ai gruppi Django.
- Sync LDAP -> SQL/Django: ogni utente LDAP viene creato/aggiornato in tabella legacy `utenti` come `*AD_MANAGED*`, poi allineato su `auth_user` + `Profile` tramite `sync_django_user_from_legacy`.
- Config LDAP estesa: aggiunte impostazioni `LDAP_SERVICE_USER`, `LDAP_SERVICE_PASSWORD`, `LDAP_BASE_DN`, `LDAP_USER_FILTER`, `LDAP_GROUP_ALLOWLIST`, `LDAP_SYNC_PAGE_SIZE` (da `.env`/`config.ini`).
- Gruppi: supporto import selettivo via allowlist e opzione autoritativa `--replace-allowlist-memberships` per allineare i gruppi portale da AD.

## 0.3.17-dev - 2026-02-27
- Assenze permessi per gruppi: `UTENTI` solo inserimento (no calendario), `CAR` inserimento + calendario + modifica solo record con `caporeparto` associato al capo corrente, `AMMINISTRAZIONE` pieno controllo (view/edit/delete/sync).
- Calendario/API hardening: controlli `403` su view/API colori/eventi/sync e blocco update/delete non autorizzati lato backend (non solo UI).
- Richiesta assenza: nuovo flag `salta_approvazione` visibile solo a `CAR/AMMINISTRAZIONE`, salvato su SQL e propagato su SharePoint.
- Vincoli PowerApps portati su Django: validazione data/ora server-side e regole FlessibilitÃ  (min 9h, max 10h, max 2 richieste settimanali per persona) con warning dedicato sul caso 10h.
- UI allineata: subnav nasconde il link `Calendario` ai gruppi senza diritto e popup calendario in modalitÃ  sola lettura quando non ci sono permessi di modifica/eliminazione.

## 0.3.16-dev - 2026-02-26
- Gestione Pulsanti UX: preset rapidi UI estesi anche alla tabella `Pulsanti esistenti` (preset per riga con pulsante `Preset`, applicazione locale dei campi e salvataggio manuale successivo).
- Gestione Pulsanti JS: logica preset riutilizzata sia nel form di creazione sia nelle righe esistenti tramite helper comune (`applyPresetValuesToContainer`).
- Miglioria usabilita': guida inline aggiornata per chiarire che il preset riga non salva automaticamente (serve clic `Salva`).
## 0.3.15-dev - 2026-02-26
- Gestione Pulsanti UX: aggiunti preset rapidi UI nel form di creazione (compilazione automatica di `Slot`, `Sezione`, `Topbar`, `Attivo`) con descrizione e pulsante "Applica preset".
- Gestione Pulsanti backend: preset UI forniti da `admin_portale.views.pulsanti` (DB-driven UI piu' guidata, meno inserimento manuale ripetitivo).
- Uniformazione schermate Admin: nuovo componente `card_head.html` e applicazione progressiva ai card header statici (Pulsanti/ACL/LDAP/Schema Dati) per layout piu' coerente.
## 0.3.14-dev - 2026-02-26
- Uniformazione schermate Admin Portale: introdotti componenti template condivisi `page_header.html` e `flash_messages.html` per standardizzare header pagina e messaggi.
- Refactor template admin: applicati i componenti comuni alle schermate principali (`Home`, `Utenti`, `Permessi`, `Pulsanti`, `ACL`, `LDAP`, `Schema Dati`) e messaggi unificati anche su `utente_edit` / `permessi effettivi`.
- Obiettivo UX/manutenzione: ridurre differenze visive tra schermate e semplificare modifiche future a layout/testi comuni.
## 0.3.13-dev - 2026-02-26
- Admin Portale: nuova pagina `Schema Dati Admin` (`/admin-portale/schema-dati/`) con mappa semplice delle tabelle principali (legacy + Django), responsabilita', gestione dal portale e conteggi live.
- UI Admin: aggiunti collegamenti route-safe a `Schema Dati` in subnav e home admin per ridurre confusione su dove sono salvati ruoli/permessi/pulsanti.
- Obiettivo UX: chiarire la separazione tra dati nel DB SQL Server legacy (`utenti`, `ruoli`, `permessi`, `pulsanti`) e tabelle di supporto Django (`auth_user`, `core_profile`, `ui_pulsanti_meta`).
## 0.3.12-dev - 2026-02-26
- Gestione Pulsanti UX: aggiunti menu a tendina con suggerimenti (`datalist`) per `Modulo`, `Slot UI`, `Sezione UI` e `Icona` sia in creazione sia nella tabella dei pulsanti esistenti (restano ammessi valori personalizzati).
- Gestione Pulsanti: aggiunte guide rapide inline per spiegare `Slot`, `Sezione` e `Ord UI` e migliorare la compilazione dei metadati UI.
- Admin Portale: aggiunta descrizione contestuale ("cosa fa / come usarla") nella subnav per le principali pagine admin (`Home`, `Utenti`, `Permessi`, `Pulsanti`, `ACL`, `LDAP`).
## 0.3.11-dev - 2026-02-26
- Admin Portale: nuova pagina `Diagnostica ACL` (`/admin-portale/acl/`) per analizzare i `403` mostrando utente legacy, ruolo, path normalizzato, pulsante matchato e record in tabella `permessi`.
- Diagnostica ACL: supporto test su utente corrente o su un `legacy_user_id` specifico (utile per verificare un utente LDAP appena creato/assegnato a un ruolo).
- UI Admin: aggiunti link route-safe a `Diagnostica ACL` in subnav e home admin.
## 0.3.10-dev - 2026-02-26
- ACL middleware/permessi: supporto ai `pulsanti.url` configurati come `route:nome_route` / `django:nome_route` anche nel matcher ACL (reverse della route prima del controllo permesso).
- Fix autorizzazioni DB-driven: evitati `403` falsi positivi quando i link menu sono gestiti dal portale con route Django invece di path statici.
## 0.3.9-dev - 2026-02-26
- Fix login LDAP auto-provision: `LDAPBackend` non passa piu' il campo `ruoli` se il modello/tabella legacy `utenti` non lo supporta (compatibilita' con schemi legacy diversi).
- Backend LDAP: create utente legacy resa piu' robusta filtrando i campi in base ai campi effettivi del modello `UtenteLegacy`.
## 0.3.8-dev - 2026-02-26
- Fix Admin Portale home (`/admin-portale/`): card `Diagnostica LDAP` resa route-safe con `{% url ... as ... %}` per evitare `NoReverseMatch` durante reload parziali del dev server.
- Coerenza template admin: comportamento allineato alla subnav (`admin_subnav.html`) gia' protetta con reverse opzionale.
## 0.3.7-dev - 2026-02-26
- Fix subnav Admin: link `LDAP` reso route-safe (`{% url ... as ... %}`) per evitare `NoReverseMatch` in caso di reload parziale / route non ancora registrata nel processo Django.
- Nota operativa: verificata la route `admin_portale:ldap_diagnostica` (`/admin-portale/ldap/`) correttamente registrata a runtime.
## 0.3.6-dev - 2026-02-26
- Admin Portale: nuova pagina `Diagnostica LDAP` (`/admin-portale/ldap/`) con test connessione LDAP e test bind utente (UPN + fallback NTLM `DOMINIO\\utente`).
- Admin Portale: aggiunti link a `Diagnostica LDAP` in subnav e home admin.
- Gestione Pulsanti (DB-driven UI): create/update salvano metadati UI persistenti in `ui_pulsanti_meta` (`ui_slot`, `ui_section`, `ui_order`, `visible_topbar`, `enabled`).
- Gestione Pulsanti: UI estesa con campi Slot/Sezione/Ord UI/Topbar/Attivo per gestire i pulsanti per posizione e contesto dal portale.
- Topbar dinamica: utilizza i metadati `ui_pulsanti_meta` quando presenti (filtri slot/topbar/attivo e ordine UI), con fallback ai campi legacy.
## 0.3.5-dev - 2026-02-26
- Gestione Pulsanti (DB-driven avanzato): introdotti metadati UI persistenti in tabella `ui_pulsanti_meta` (slot, sezione, ordine UI, visibile in topbar, attivo) gestiti dal portale.
- Gestione Pulsanti: create/update salvano anche i metadati UI; lista pulsanti mostra e modifica `Slot`, `Sezione`, `Ord UI`, `Topbar`, `Attivo`.
- Topbar dinamica: ora usa i metadati UI (`enabled`, `visible_topbar`, `ui_slot=topbar/toolbar`, `ui_order`) se presenti, con fallback ai campi legacy.
- LDAP/AD (Django): parametri LDAP ora letti con priorita' da `config.ini` (`[ACTIVE_DIRECTORY]`) invece di essere bloccati dai default in `.env`.
- LDAP/AD backend: aggiunto fallback `NTLM` per bind `DOMINIO\\utente` (oltre al bind UPN), migliorando compatibilita' con Active Directory Windows.
## 0.3.4-dev - 2026-02-26
- Admin Portale / Gestione Pulsanti: aggiunto filtro `Area UI` (posizione/funzione) per gestire meglio i pulsanti per contesto (`toolbar`, assenze, calendario assenze, anomalie, admin, utenti, permessi, richieste, altro).
- Gestione Pulsanti: nuova colonna `Area UI` (derivata automaticamente da codice/modulo/url/route) per rendere piu' chiara la collocazione dei pulsanti.
- Migliorata usabilita' gestione pulsanti: approccio orientato alla posizione UI, non solo per modulo tecnico.
## 0.3.3-dev - 2026-02-26
- Admin Portale / Gestione Pulsanti: aggiunto catalogo delle route Django disponibili (nome route + path + valore pronto `route:...`).
- Gestione Pulsanti: filtro client-side e pulsante copia per compilare velocemente il campo URL dei pulsanti topbar/menu.
- Backend admin_portale: catalogo route generato dal resolver Django (ricorsivo, include namespace come `admin_portale:*`).
## 0.3.2-dev - 2026-02-26
- Topbar DB-driven: il campo `pulsanti.url` supporta ora `route:nome_route_django` (o `django:nome_route`) per puntare alle route Django senza modificare il codice.
- Topbar/nav: supporto anche a URL esterni `http(s)://...` dal DB; il mapping Python rimane come fallback per i pulsanti legacy non configurati.
- Admin Portale / Gestione Pulsanti: validazione `url` aggiornata per accettare `route:`, `django:` e URL esterni senza forzare `/`.
- Admin Portale / Gestione Pulsanti: aggiunto hint UI su come configurare i link topbar dal portale (`route:gestione_anomalie_page`, ecc.).
## 0.3.1-dev - 2026-02-26
- Anomalie sync (DB-first): `POST /api/anomalie/sync` ora esegue push SQL Server -> SharePoint (create dei record locali non sincronizzati, update opzionale con `include_updates`).
- Anomalie frontend React legacy in Django: compatibilita' migliorata sulle API `/api/anomalie/ordini` e `/api/anomalie/anomalie` con fallback su DB locale.
- API anomalie: `GET /api/anomalie/db/anomalie` restituisce anche `local_id` e `item_id` sintetico `local:<id>` per record non ancora sincronizzati.
- Sicurezza/compatibilita': endpoint POST anomalie (`salva`, `sync`) mantenuti `csrf_exempt` per supportare il frontend JS legacy durante la migrazione.
## 0.3.0-dev - 2026-02-26
- Migrazione Django step frontend+API: nuova app `dashboard` con route `/dashboard`, `/richieste`, `/anomalie-menu` e redirect root `/`.
- Migrazione Django step assenze: nuova app `assenze` con pagine GET (`/assenze/*`) e API locale `/assenze/api/eventi` su SQL Server.
- Migrazione Django step anomalie: nuova app `anomalie` con pagina `/gestione-anomalie` (frontend React legacy portato in Django).
- API anomalie DB-first: `GET /api/anomalie/db/ordini`, `GET /api/anomalie/db/anomalie` e fallback compatibile su `/api/anomalie/ordini` e `/api/anomalie/anomalie`.
- API anomalie DB-first: `POST /api/anomalie/salva` salva/aggiorna su tabella SQL Server `anomalie` con `item_id` locale (`local:<id>`) se non sincronizzato su SharePoint.
- ACL/menu legacy aggiornati per puntare alle nuove route Django (`assenze`, `anomalie-menu`).
- Note: sync SharePoint e POST avanzati (`assenze`, `anomalie/sync`) restano placeholder per i prossimi step.
## 0.2.0-dev â€” 2026-02-25
- Admin portale: dashboard, gestione utenti (CRUD + bulk), gestione permessi (toggle + bulk + copy), gestione pulsanti (CRUD).
- Menu dinamico aggiornato per puntare alle nuove route admin-portale.
- Harden CSRF su API admin.
