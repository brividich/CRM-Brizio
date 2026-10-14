# `admin_portale` — pannello admin custom

Area **Core** · URL `/admin-portale/` · codice [`django_app/admin_portale/`](../../django_app/admin_portale/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Pannello admin custom: ACL canonico, diagnostica, mappa permessi, attivita utente, log e archiviazione notifiche, branding e template PDF

## Dettaglio

Sostituisce il Django admin nativo con un pannello ritagliato sulle operazioni reali del portale.

- **Home catalogo** (`/admin-portale/`): tutte le pagine del pannello sono elencate come schede nelle sezioni Utenti & Accessi, Navigazione & Menu, Automazioni, Monitoraggio, Configurazione, Sistema & Diagnostica, Hub Tools, Pannelli Moduli, Deploy e Versioning — comprese Gestione Ruoli, Matrice Permessi, Import Utenti LDAP, Wizard Pulsante, Mappa Permessi/Navigazione, Branding & Favicon, Gestione Notifiche, Bacheca, ACL Canonico, ACL Route Coverage, Log Notifiche e FAQ & Knowledge AI
- **Ruoli e permessi** (`/admin-portale/ruoli-portale/`): sistema unico dei permessi (`core/permessi`, dettagli in [PERMESSI_RUOLI.md](../ai/PERMESSI_RUOLI.md)). Schede: **Persone** (ruoli di ogni persona, più ruoli per persona, nota nel registro), **Matrice dei ruoli** (ruolo × modulo × azione: vedere, creare, modificare, approvare, chiudere/gestire, esportare, cancellare; valore — / Propri / Team / Tutti / No; proprietà del ruolo, ordine, flag «Amministratore» e «Vede ed esporta tutto», nuovo ruolo, ripristino preset), **Cosa vede questa persona** (per modulo, azioni consentite, ambito e ruolo che decide, team d'organigramma), **Registro modifiche** (chi, cosa, quando), **Sistema** (interruttore generale, sincronizzazione dei permessi delle pagine, preset mancanti), **Guida**. Fra più ruoli decide quello con ordine più alto che si esprime; il ruolo base «Dipendente» vale per tutti; Amministratore e Direzione vedono tutto. 13 preset pronti (Amministratore, Direzione, Sicurezza, HR, Qualità, Tecnico IT, Tecnico Manutenzione, Ufficio Tecnico, Magazzino, Amministrazione, Responsabile, Preposto, Dipendente). Comandi: `permessi_ruoli`, `permessi_utenti_prova`. Deploy: `migrate core` (0076, 0077)
- **Gestione accessi** semplici canonico-first con toggle per modulo su `RolePermissionGrant`
- **Accessi** (`/admin-portale/accessi/`): gruppi e ruoli, un grant canonico per permesso. I permessi sono ordinati per **area → modulo → natura (configurazione/operativo) → categoria**: moduli con nome leggibile e alias riuniti (es. `sicurezza` in Rilevazione incidenti, micro-moduli tecnici in «Piattaforma e servizi comuni»), categorie da `core/permission_categories.py` (regole scritte sul catalogo reale; un permesso nuovo che non corrisponde a nessuna regola finisce in «Altre funzioni» e si sistema aggiungendo una regola), etichette tecniche rese leggibili. Il pannello **Verifica dei collegamenti** dice per ogni permesso se apre pagine (rotte nel tooltip), comanda solo voci di menu, è di sezione o è **oscurato** (binding attivi che nessuna rotta sceglie), con l'elenco dei binding morti da correggere in ACL canonico e un filtro per tipo di collegamento. Solo presentazione: non cambia nessuna decisione ACL
- **Accessi negati** (`/admin-portale/accessi-negati/`): ogni «Accesso negato» ricevuto dagli utenti, una riga per persona e pagina, con il motivo in chiaro e lo stato di eccezione personale / gruppo / ruolo (Consentito · Negato esplicitamente · Non impostato). **Consenti** o **Non consentire** su tutto il ruolo o sulla sola persona: scrive i grant canonici, lascia l'audit e verifica l'esito. Lo stesso pannello compare sulla pagina 403 quando un amministratore sta impersonando qualcuno, così il blocco si risolve senza uscire dall'impersonazione
- **ACL canonico** con 5 tab (Permission, Binding, Role grant, User override, Nav override)
- **ACL route coverage** report con stati e export CSV
- **ACL diagnostica** combinata legacy + canonical con una sola decisione finale chiara e trace completo (CLI equivalente: `python manage.py acl_diagnose --user <email|alias|id> --path </route/>`)
- **Avviso "ACL canonico"** nella pagina permessi legacy: i moduli con binding canonico attivo sono marcati e segnalano che i permessi legacy lì sono ignorati a runtime (linkano ad ACL canonico/diagnostica)
- **Mappa permessi/navigazione** visuale con drill-down cliccabile e toggle live dei grant
- **Navigation Builder** con vista tabellare + **vista drag&drop orizzontale** per sezione
- **Vista attività utente** (`/admin-portale/attivita-utenti/`) sugli ultimi 30 giorni da `AuditLog`, con filtri utente/modulo/testo e export CSV/XLSX
- **Log notifiche** (`/admin-portale/notifiche-log/`): elenco **cross-utente** di tutte le notifiche in-app con destinatario risolto, etichetta/icona dal registro tipi, filtri (tipo/utente/stato/giorni), **conteggi per tipo** ed export CSV/XLSX — per verificare cosa parte e a chi (`Notifica` registrata anche nel Django admin)
- **Gestione notifiche** (`/admin-portale/notifiche-config/`): interruttore admin **globale** per accendere/spegnere ciascuna categoria di notifica (assenze/comunicazioni/scadenzari/ticket/operatività) per tutti; enforcement reale via `core.notifiche_prefs.should_notify` in `invia_notifica`. L'utente gestisce le proprie preferenze da **`/notifiche/impostazioni/`** (l'admin ha la precedenza). Nella stessa pagina le **regole di archiviazione automatica** (giorni per non lette / lette / conservazione dell'archivio, 0 = mai), i contatori attive/non lette/archiviate e «Esegui ora»; il Log notifiche filtra anche le archiviate
- **Export audit/notifiche**: audit log, attività utente e centro notifiche mantengono i filtri GET negli export CSV/XLSX
- **LDAP settings** + sync/import utenti AD con service account effettivo; nei deploy TEST/PROD salva sul `config/.env` persistente, non sul `.env` della release attiva
- **Branding portale** (favicon, logo, login banner, pagina login personalizzabile)
- **Module Manager** integrato per abilitazione moduli runtime
- **Automazioni admin**: impostazioni runtime, queue list, log mailbox, convertitore Power Automate
- **Eliminazione massiva utenti** (`/admin-portale/utenti/`): pulsante "Elimina selezionati" nella toolbar con confirm JS sul numero righe; per ciascun ID chiama `_delegate_legacy_user_with_dependencies` (release asset, pulizia override/dashboard/profilo Django, unlink anagrafica), salta l'utente corrente, aggrega contatori `deleted`/`errors`/`skipped_self` e registra nell'audit log
- **Crea Release** (`/admin-portale/crea-release/`) con package zip, riavvio IIS TEST/PROD automatico via task schedulato elevato `\PortaleNovicrom\IISRestart_TEST/PROD` e terminale web con preset Django/ACL sull'ambiente selezionato
- **Impersonazione e 2FA degli amministratori**: impersonare un amministratore (admin legacy o account superuser/staff) e modificarne il 2FA (attiva/disattiva, reset, metodo, email OTP) è riservato ai superuser; i tentativi negati finiscono nell'audit (`impersonation_denied`, `twofa_user_change_denied`)
- **Utenti disattivati**: la disattivazione (singola o massiva) chiude anche le sessioni aperte. **Upload immagini** (logo, favicon, icone menu, card): solo PNG/JPEG/GIF/WebP (e ICO per favicon/icone), verificati sul contenuto reale; niente SVG

- **Ruoli e permessi, matrice**: il menu «Tutta la riga…» sotto ogni modulo imposta in un colpo tutte le sue azioni (Propri / Team / Tutti / No / svuota). Solo lato pagina: il salvataggio resta quello della matrice. Le azioni proprie del modulo (righe «↳») non sono incluse.
- **Accessi, guida in-app**: pulsante «? Guida» nella plancia (`?guida=1`, stessa rotta e permesso della pagina); guida e guida di «Ruoli e permessi» indicizzate dall'assistente AI.
- **Ruoli e permessi, stato reale delle pagine**: sotto ogni cella della matrice il badge «pagine N/M» (tutte / alcune / nessuna, elenco nel tooltip) e «· a mano» se i permessi sono stati cambiati dalla pagina Accessi; in Accessi l'etichetta «da matrice» sui permessi accesi dalla matrice, con link al ruolo. Sola lettura.
- **Ruoli e permessi, «Riepilogo per modulo»**: scheda in sola lettura (`?tab=modulo&modulo=<chiave>`) con le azioni concesse da ogni ruolo e la tabella pagine/API × ruoli (matrice, a mano, negato, amministratore); evidenzia le pagine non aperte a nessun ruolo.
- **Accessi (unificata)**: interruttore di ogni permesso a sinistra del nome; sotto il codice le prime 3 rotte governate (+N), tutte nel suggerimento.
- **Accessi, catalogazione**: scomparto «Configurazione e amministrazione» esteso ai moduli amministrativi e alle pagine di import/template/mailbox/backup; code legacy letti dal nome pagina (`core/permission_taxonomy.py::nature_for_code`).
- **Accessi, preset per modulo**: «Salva come preset…» / «Elimina preset» nella barra di ogni modulo; i preset compaiono nel menu «Livello». Endpoint JSON `admin_portale:accessi_preset` (POST). Tabella `core.PresetPermessiModulo` (migrazione 0079).
