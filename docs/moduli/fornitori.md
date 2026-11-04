# `fornitori` — anagrafica fornitori (modulo dedicato)

Area **Operations** · URL `/fornitori/` · codice [`django_app/fornitori/`](../../django_app/fornitori/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

**Anagrafica Fornitori** (modulo e permessi ACL separati da Anagrafica HR): dashboard KPI spesa/ordini/asset, lista filtrabile, scheda fornitore con documenti / ordini / valutazioni qualità / asset assegnati. I modelli restano in `anagrafica.models` per compatibilità con le FK storiche di assets

## Dettaglio

Modulo dedicato all'anagrafica fornitori, scorporato da `anagrafica` per separare nettamente la gestione HR da quella commerciale/operativa. URL prefix `/fornitori/` con namespace `fornitori:*`; nel catalogo permessi admin usa il modulo `fornitori` separato da `anagrafica` e binding ACL v2 compatibili con i permessi legacy `legacy.fornitori.*`.

- **Dashboard** `/fornitori/` con hero verde, KPI (attivi/inattivi/spesa totale/ordini/asset assegnati), ultimi fornitori e top 5 spesa per categoria con barre orizzontali
- **Lista filtrabile** `/fornitori/elenco/` con ricerca per ragione sociale/P.IVA/città, filtro categoria, filtro stato attivo, paginazione
- **Scheda fornitore** `/fornitori/<id>/` con anagrafica completa, **documenti** allegati (PDF/Office/immagini, validazione MIME+estensione, 15MB max), **ordini** con stato e importo (somma in spesa totale), **valutazioni qualità** (qualità/puntualità/comunicazione su 5 stelle, media calcolata), **asset assegnati** (collegamento al modulo `assets`)
- **CRUD** completo `+nuovo` / modifica / toggle attivo, con form Django `FornitoreForm` (ragione sociale, P.IVA, codice fiscale, indirizzo, contatti, PEC, website, categoria)
- **Compatibilità DB**: i modelli `Fornitore`, `FornitoreDocumento`, `FornitoreOrdine`, `FornitoreValutazione`, `FornitoreAsset` restano fisicamente in `anagrafica.models` (tabelle `anagrafica_fornitore*` invariate) perché referenziati da ForeignKey storiche in `assets.models` (`PeriodicVerification.supplier`, `WorkOrder.supplier`, `AssistanceContract.supplier`). La separazione è quindi a livello di app Django (URL/views/forms/templates/ACL), non di schema database
- **Accessi esterni** `/fornitori/accessi-esterni/` (dal 04/11/2026): visitatori, fornitori e consulenti registrati al chiosco della reception (**GuestPortal**, applicazione separata PHP + MySQL). «Presenti ora» + storico del periodo con filtri; l'azienda si collega alla scheda fornitore se la ragione sociale coincide. Lettura diretta in sola lettura (`fornitori/guestportal.py`, PyMySQL, `SET SESSION TRANSACTION READ ONLY`), **nessuna copia** nelle tabelle HUB: la pulizia GDPR del GuestPortal resta valida. Massimo 500 righe di storico, con avviso esplicito. Permesso `legacy.portale_esterno.portale_esterno` (migrazione `fornitori/0003`)
- **Apri GuestPortal** `/fornitori/guestportal/apri/`: redirect a `public/admin/sso.php` del GuestPortal con token HMAC-SHA256 (60 s, nonce a uso singolo registrato in `AuditLog` del GuestPortal); l'autorizzazione resta in `AdminUsers` del GuestPortal, il master non entra da SSO. Rotta condivisa (`core/middleware.py`, come il vecchio link diretto). La voce di menu `accessi` («Accessi azienda») punta qui se aveva ancora l'URL originale. Senza `GUESTPORTAL_SSO_SECRET` porta al login normale del pannello
- **Presenze in azienda della ditta** (dal 04/11/2026): riquadro HTMX in ticket MAN (scheda Interventi di `tickets:gestione_detail`) e OdL esterni (`assets:wo_view`) — `fornitori:presenze_intervento` / `presenze_collega` / `presenze_scollega`, rotte condivise con controllo nella view (gestore del ticket; per l'OdL chi apre la pagina e, per collegare, `can_execute_maintenance`). Propone gli ingressi della ditta delegata (`Ticket.delegato_fornitore` / `WorkOrder.supplier`) dal giorno prima dell'apertura alla chiusura (max 90 giorni); collegamento a mano per giorno. Tabella `fornitori_ingressointervento` con fotografia dell'ingresso (giorno, entrata, uscita, tecnico, badge): resta dopo la pulizia GDPR del GuestPortal. Nei ticket confronto ore interventi vs presenza (avviso oltre 15 minuti). Colonna «Incaricato per» in Accessi esterni. Servizio `fornitori/ingressi.py`
- **Ditte GuestPortal** `/fornitori/guestportal/ditte/`: abbinamento una tantum `Suppliers.SupplierID` → fornitore HUB (`fornitori_dittaguestportal`), proposta per nome uguale; permesso copiato da «Modifica fornitore» (migrazione `0005`)
- **Configurazione** (`.env`): `GUESTPORTAL_ADMIN_URL`, `GUESTPORTAL_SSO_URL`, `GUESTPORTAL_SSO_SECRET`, `GUESTPORTAL_DB_HOST/PORT/NAME/USER/PASSWORD`. Lato GuestPortal e utente MySQL in sola lettura: [docs/integrazioni/guestportal/README.md](../integrazioni/guestportal/README.md)
