# `admin_portale` — pannello admin custom

Area **Core** · URL `/admin-portale/` · codice [`django_app/admin_portale/`](../../django_app/admin_portale/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Pannello admin custom: ACL canonico, diagnostica, mappa permessi, attivita utente, log notifiche, branding e template PDF

## Dettaglio

Sostituisce il Django admin nativo con un pannello ritagliato sulle operazioni reali del portale.

- **Home catalogo** (`/admin-portale/`): tutte le pagine del pannello sono elencate come schede nelle sezioni Utenti & Accessi, Navigazione & Menu, Automazioni, Monitoraggio, Configurazione, Sistema & Diagnostica, Hub Tools, Pannelli Moduli, Deploy e Versioning — comprese Gestione Ruoli, Matrice Permessi, Import Utenti LDAP, Wizard Pulsante, Mappa Permessi/Navigazione, Branding & Favicon, Gestione Notifiche, Bacheca, ACL Canonico, ACL Route Coverage, Log Notifiche e FAQ & Knowledge AI
- **Gestione accessi** semplici canonico-first con toggle per modulo su `RolePermissionGrant`
- **Accessi negati** (`/admin-portale/accessi-negati/`): ogni «Accesso negato» ricevuto dagli utenti, una riga per persona e pagina, con il motivo in chiaro e lo stato di eccezione personale / gruppo / ruolo (Consentito · Negato esplicitamente · Non impostato). **Consenti** o **Non consentire** su tutto il ruolo o sulla sola persona: scrive i grant canonici, lascia l'audit e verifica l'esito. Lo stesso pannello compare sulla pagina 403 quando un amministratore sta impersonando qualcuno, così il blocco si risolve senza uscire dall'impersonazione
- **ACL canonico** con 5 tab (Permission, Binding, Role grant, User override, Nav override)
- **ACL route coverage** report con stati e export CSV
- **ACL diagnostica** combinata legacy + canonical con una sola decisione finale chiara e trace completo (CLI equivalente: `python manage.py acl_diagnose --user <email|alias|id> --path </route/>`)
- **Avviso "ACL canonico"** nella pagina permessi legacy: i moduli con binding canonico attivo sono marcati e segnalano che i permessi legacy lì sono ignorati a runtime (linkano ad ACL canonico/diagnostica)
- **Mappa permessi/navigazione** visuale con drill-down cliccabile e toggle live dei grant
- **Navigation Builder** con vista tabellare + **vista drag&drop orizzontale** per sezione
- **Vista attività utente** (`/admin-portale/attivita-utenti/`) sugli ultimi 30 giorni da `AuditLog`, con filtri utente/modulo/testo e export CSV/XLSX
- **Log notifiche** (`/admin-portale/notifiche-log/`): elenco **cross-utente** di tutte le notifiche in-app con destinatario risolto, etichetta/icona dal registro tipi, filtri (tipo/utente/stato/giorni), **conteggi per tipo** ed export CSV/XLSX — per verificare cosa parte e a chi (`Notifica` registrata anche nel Django admin)
- **Gestione notifiche** (`/admin-portale/notifiche-config/`): interruttore admin **globale** per accendere/spegnere ciascuna categoria di notifica (assenze/comunicazioni/scadenzari/ticket/operatività) per tutti; enforcement reale via `core.notifiche_prefs.should_notify` in `invia_notifica`. L'utente gestisce le proprie preferenze da **`/notifiche/impostazioni/`** (l'admin ha la precedenza)
- **Export audit/notifiche**: audit log, attività utente e centro notifiche mantengono i filtri GET negli export CSV/XLSX
- **LDAP settings** + sync/import utenti AD con service account effettivo; nei deploy TEST/PROD salva sul `config/.env` persistente, non sul `.env` della release attiva
- **Branding portale** (favicon, logo, login banner, pagina login personalizzabile)
- **Module Manager** integrato per abilitazione moduli runtime
- **Automazioni admin**: impostazioni runtime, queue list, log mailbox, convertitore Power Automate
- **Eliminazione massiva utenti** (`/admin-portale/utenti/`): pulsante "Elimina selezionati" nella toolbar con confirm JS sul numero righe; per ciascun ID chiama `_delegate_legacy_user_with_dependencies` (release asset, pulizia override/dashboard/profilo Django, unlink anagrafica), salta l'utente corrente, aggrega contatori `deleted`/`errors`/`skipped_self` e registra nell'audit log
- **Crea Release** (`/admin-portale/crea-release/`) con package zip, riavvio IIS TEST/PROD automatico via task schedulato elevato `\PortaleNovicrom\IISRestart_TEST/PROD` e terminale web con preset Django/ACL sull'ambiente selezionato
