# `tickets` — ticket interni IT/manutenzione

Area **HR & Workflow** · URL `/tickets/` · codice [`django_app/tickets/`](../../django_app/tickets/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Ticket interni con interventi, fermo macchina, ticket ricorrenti; allegati caricabili da pagina web e dal QR della macchina, con **validazione del team gestore** (coda «Allegati da validare» in gestione, valida/rifiuta motivato)

## Dettaglio

Sistema ticket per richieste interne con capabilities analitiche avanzate.

- **8 modelli**: Ticket, TicketCommento, TicketAllegato, TicketImpostazioni, CategoriaTicket, TicketStatoLog, TicketIntervento, TicketSharePointOutbox
- **Campi analitici**: componente guasto, causa radice, tipo fermo, ore fermo macchina, data presa in carico, data primo intervento, risolto_da
- **Ticket ricorrenti** con FK `ticket_origine` per tracciare serie di problemi correlati
- **Interventi tecnici** come sessioni di lavoro multiple sullo stesso ticket
- **Log cambio stato** completo con timestamp, autore, motivazione
- **Categorie ticket** configurabili con SLA
- **Reminder SLA & escalation** (due flussi complementari): (1) `manage.py send_sla_reminders` avvisa l'**assegnatario** dei ticket con SLA scaduto; (2) escalation automatica dei ticket **URGENTI ancora aperti e senza assegnatario** oltre soglia (task django-q2 `tickets.tasks.run_tickets_escalation`, schedule orario, command `run_tickets_escalation --dry-run/--force-email`): promemoria in dashboard (`core.Notifica`) per team gestori + richiedente a ogni run, e resoconto email al team gestori nei giorni lavorativi all'ora configurata. Config da `/tickets/impostazioni/` (on/off, soglia ore default 4, ora invio default 8; `SiteConfig`, default off)
- **Import CSV/Excel** da `/tickets/impostazioni/` (`api/import-csv/`, formato interno o export SharePoint IT/MAN): deduplica per `numero_ticket` o `ID` SharePoint, «Aggiorna ticket esistenti» per sovrascrivere. L'import è silenzioso: gira in un'unica transazione e marca `done` gli eventi di `automation_event_queue` dei ticket importati, quindi nessuna automazione/mail parte. Stato da `stato` (anche in italiano), poi `Chiuso` (1/Sì/Vero/x), poi data di chiusura presente = CHIUSO. CSV solo con virgola: dall'Excel italiano caricare l'`.xlsx`
- **Sincronizzazione bidirezionale ticket MAN ↔ SharePoint** (`tickets/sharepoint_man.py`, come le assenze): lista «Ticket» del sito CNManutenzioni via Graph. Ogni salvataggio di un ticket MAN entra in `TicketSharePointOutbox` (segnale `post_save`); il job django-q `tickets_man_sharepoint_sync` (ogni 5 minuti, `tickets.tasks.run_ticket_man_sharepoint_sync`) invia la coda e poi legge le modifiche con delta query (deltaLink in cache). Campi: Title, Description, Priority, Status, Tipologiaproblema, Macchinario, Note, Impattosusicurezza, Chiuso, Datachiusuraticket (+ DateReported alla creazione); `Datafinelavori` letta come data di chiusura di riserva. Stati: APERTA=Nuovo, IN_CARICO=In corso, IN_ATTESA=Bloccato/Da progettazione, RISOLTO=Completato, CHIUSO=Completato+Chiuso, ANNULLATO=Non implementabile/Duplica. «Nuovo» (predefinito della lista, mai toccato) non cambia uno stato aperto del portale: la chiusura passa da `Chiuso`, togliere `Chiuso` riapre. Prima lettura completa (o token delta scaduto): crea solo gli elementi non collegati, i ticket già collegati non si toccano. Ticket in coda = vince il portale; le scritture della lettura non tornano in coda, non fanno partire automazioni e registrano il cambio stato (autore «SharePoint»). Elemento eliminato su SharePoint = ticket scollegato, non cancellato. Commenti/allegati/interventi solo sul portale. Configurazione in `/tickets/impostazioni/` (MAN): List ID, Site ID, interruttore (`TicketImpostazioni.sharepoint_site_id`/`sharepoint_sync_attivo`, migration `0013`); credenziali Graph da `.env`
- **Upload allegati hardening** con validazione MIME reale (non solo estensione)
- **Download autenticato** via view Django (non da `/media/tickets/` diretto)
- **Audit log download** allegati sensibili (non loggati path fisici, contenuto file, token o segreti)
- **Integrazione registro manutenzione asset**: i ticket MAN con flag `include_in_maintenance_register=True` e asset collegato compaiono nel registro manutenzione dell'asset come interventi straordinari (PATCH 21E)

## Ruoli del portale

Con il sistema dei ruoli attivo ([PERMESSI_RUOLI.md](../ai/PERMESSI_RUOLI.md)) Ticket IT e Ticket manutenzione sono **due moduli distinti** in matrice (`ticket_it`, `ticket_manutenzione`): gestire uno non dà la gestione dell'altro, e la lista di gestione mostra solo i tipi gestiti. Ognuno vede i propri ticket; preposti e responsabili anche quelli del team d'organigramma (manutenzione), la Direzione tutti. Le liste di utenti «apertura/gestione» nelle impostazioni valgono solo a sistema spento. Sempre, anche a sistema spento: il richiedente si riconosce solo da account, id utente o email aziendale (mai dal nome), e la ricerca globale mostra solo i ticket visibili.
