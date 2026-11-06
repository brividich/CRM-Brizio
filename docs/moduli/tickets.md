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

## Sezioni «I miei ticket» e «Ticket» (27/10/2026)

- **I miei ticket** (`/tickets/`, `tickets:dashboard`): solo i ticket aperti dalla persona (account, id legacy o email), per tutti, gestori compresi.
- **Ticket** (`/tickets/elenco/`, `tickets:elenco`, migration `tickets 0014` per il binding): tutti i ticket che il ruolo vede (`filtro_ticket_visibili`, «vedere» team o tutti su Ticket IT / manutenzione; a sistema ruoli spento gestori e amministratori). La voce compare solo a chi vede ticket di altri (`puo_vedere_altri_ticket`, tag `tickets_nav.vede_altri_ticket`). Sui ticket altrui il dettaglio è in sola lettura: niente riquadro commenti (l'API `api_commento` lo nega comunque). Resta l'eccezione storica degli allegati sui ticket legati a un asset (rapportino dal QR).
- **Gestione ticket**: invariata, a chi gestisce.

## KPI coerenti e in tempo reale (02/11/2026)

KPI della gestione ticket sui soli tipi gestiti dall'utente.

## Mappa degli asset nei ticket di manutenzione (03/11/2026)

- **Nuovo ticket MAN**: pulsante «Sulla mappa» (e chip «Cercalo sulla mappa») con le planimetrie attive (`assets.PlantLayout`) e gli asset non IT collocati; quelli del reparto di chi apre sono colorati, gli altri grigi («Solo il mio reparto», zoom). Clic su un punto = asset scelto. Scelta dalla lista = la pianta si apre con l'asset evidenziato («È questo?»). Clic su un punto libero = `Ticket.mappa_layout/mappa_x/mappa_y` e descrizione «Punto indicato sulla …». I ticket IT non hanno la mappa.
- **Dettaglio e gestione**: riquadro «Dove si trova» (asset o punto); in gestione un clic sceglie un altro asset da salvare con «Salva», link «Apri la mappa completa» (`assets:plant_layout_map?asset=`).
- **«Tuo reparto»** (`assets/services/mappa_ticket.py`): testo del reparto sull'asset riconosciuto per nome di reparto/area o tramite `RepartoAssetCollegato` (Impostazioni asset › Reparti e capi), più i reparti/aree di cui la persona è capo o co-capo; chi sta in un'area ha solo quell'area. In alternativa le aree disegnate sulla pianta (`PlantLayoutArea.reparto_code`). Scelta in `/tickets/impostazioni/` («Mappa asset nei ticket di manutenzione», `TicketImpostazioni.mappa_reparto_da`), con la planimetria da aprire per categoria (`CategoriaTicket.planimetria`). Lo stesso riconoscimento vale per i chip «Asset reparto» del form (prima confronto esatto del testo).
- **Ricerca con sinonimi**: `AssetCategory.sinonimi` (Impostazioni asset → categoria, «Sinonimi per la ricerca»); la migration `assets 0159` propone i sinonimi per Chiller, Bruciatori, Caldaia, carroponti, carrelli ecc. solo dove vuoti.
- Migration `assets 0159`, `tickets 0015`; file statici nuovi `tickets/css/mappa_asset.css`, `tickets/js/mappa_asset.js` (collectstatic). Su SQLite le migration sospendono e ripristinano le viste `bi_*` (`dati_bi.viste.sospendi_viste_sqlite`/`ripristina_viste_sqlite`).

## Ticket per conto di un collega (05/11/2026)

Nel «Nuovo ticket» di manutenzione chi è nel ruolo della squadra manutenzione (SiteConfig `assets_squadra_manutenzione_gruppo`, lo stesso degli interventi «Interno») o gestisce i ticket MAN vede «Per conto di»: il richiedente diventa il collega scelto (utente attivo del portale), chi compila resta in `Ticket.aperto_da_user` / `aperto_da_nome` (migrazione tickets 0016), con voce di audit `ticket_aperto_per_conto_di`. Chi l'ha compilato continua a vedere il ticket in «I miei ticket» e nel dettaglio; la scheda gestione mostra «Compilato da». Dopo un errore di invio il form conserva i campi, l'asset scelto e il collega; gli allegati vanno riscelti. L'autocompletamento asset usa la ricerca elastica del modulo Assets.

Dal 06/11/2026 vale anche per i ticket IT (chi li gestisce). Le stesse persone hanno nel form «Già risolto: registra l'intervento e chiudi il ticket»: con «Cosa è stato fatto» (obbligatorio), «Concluso il» (vuoto = adesso, mai futuro) e «Ore di lavoro» il ticket nasce `CHIUSO` con un `TicketIntervento` `COMPLETATO`, `risolto_da_nome`, un commento visibile al richiedente e la voce di audit `ticket_chiuso_al_volo`. `created_at`, `closed_at` e `data_primo_intervento` prendono le date del lavoro («Concluso il» meno le ore): l'ora di registrazione resta in `TicketStatoLog` e nell'audit. Gli eventi della coda automazioni di quel ticket non si eseguono (niente avviso di nuovo ticket), salvo `incide_sicurezza`. Il permesso è verificato sul server: da chi non è ammesso il campo viene ignorato. Nessuna migrazione.
