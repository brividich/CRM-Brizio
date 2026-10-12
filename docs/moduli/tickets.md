# `tickets` — ticket interni IT/manutenzione

Area **HR & Workflow** · URL `/tickets/` · codice [`django_app/tickets/`](../../django_app/tickets/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Ticket interni con interventi, fermo macchina, ticket ricorrenti; allegati caricabili da pagina web e dal QR della macchina, con **validazione del team gestore** (coda «Allegati da validare» in gestione, valida/rifiuta motivato)

## Dettaglio

Sistema ticket per richieste interne con capabilities analitiche avanzate.

- **7 modelli**: Ticket, TicketCommento, TicketAllegato, TicketImpostazioni, CategoriaTicket, TicketStatoLog, TicketIntervento
- **Campi analitici**: componente guasto, causa radice, tipo fermo, ore fermo macchina, data presa in carico, data primo intervento, risolto_da
- **Ticket ricorrenti** con FK `ticket_origine` per tracciare serie di problemi correlati
- **Interventi tecnici** come sessioni di lavoro multiple sullo stesso ticket
- **Log cambio stato** completo con timestamp, autore, motivazione
- **Categorie ticket** configurabili con SLA
- **Reminder SLA & escalation** (due flussi complementari): (1) `manage.py send_sla_reminders` avvisa l'**assegnatario** dei ticket con SLA scaduto; (2) escalation automatica dei ticket **URGENTI ancora aperti e senza assegnatario** oltre soglia (task django-q2 `tickets.tasks.run_tickets_escalation`, schedule orario, command `run_tickets_escalation --dry-run/--force-email`): promemoria in dashboard (`core.Notifica`) per team gestori + richiedente a ogni run, e resoconto email al team gestori nei giorni lavorativi all'ora configurata. Config da `/tickets/impostazioni/` (on/off, soglia ore default 4, ora invio default 8; `SiteConfig`, default off)
- **Upload allegati hardening** con validazione MIME reale (non solo estensione)
- **Download autenticato** via view Django (non da `/media/tickets/` diretto)
- **Audit log download** allegati sensibili (non loggati path fisici, contenuto file, token o segreti)
- **Integrazione registro manutenzione asset**: i ticket MAN con flag `include_in_maintenance_register=True` e asset collegato compaiono nel registro manutenzione dell'asset come interventi straordinari (PATCH 21E)

## Ruoli del portale

Con il sistema dei ruoli attivo ([PERMESSI_RUOLI.md](../ai/PERMESSI_RUOLI.md)) Ticket IT e Ticket manutenzione sono **due moduli distinti** in matrice (`ticket_it`, `ticket_manutenzione`): gestire uno non dà la gestione dell'altro, e la lista di gestione mostra solo i tipi gestiti. Ognuno vede i propri ticket; preposti e responsabili anche quelli del team d'organigramma (manutenzione), la Direzione tutti. Le liste di utenti «apertura/gestione» nelle impostazioni valgono solo a sistema spento. Sempre, anche a sistema spento: il richiedente si riconosce solo da account, id utente o email aziendale (mai dal nome), e la ricerca globale mostra solo i ticket visibili.
