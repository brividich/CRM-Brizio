# `dpi` — Dispositivi Protezione Individuale

Area **Sicurezza** · URL `/dpi/` · codice [`django_app/dpi/`](../../django_app/dpi/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Dispositivi Protezione Individuale: catalogo gerarchico, richieste, approvazione, consegna firmata, report conformita, reminder scadenze; **raccoglitore «Documenti»** (certificati, attestati, manuali d'uso, ciascuno legato al suo DPI del catalogo, senza categorie di documento: i gestori caricano/eliminano, tutti consultano; storage privato cifrato con audit); **flusso di richiesta**: dipendente (o il suo responsabile per suo conto) → approvazione del responsabile/preposto (vede solo i propri dipendenti) → avviso di consegna a Magazzino e Amministrazione (email configurabili in Impostazioni) → consegna registrata dal magazzino → report di consegna con PDF all'Amministrazione; **Magazzino DPI**: giacenza per modello come somma di movimenti (carico DDT inserito a mano, scarico automatico alla consegna, rettifica inventario), scorta minima con stato «Da riordinare/Esaurito»; **report magazzino** (consumi per mese/reparto/modello, coperture in giorni, elenco «da riordinare» con quantita' suggerita, export CSV); **«Prima di decidere»** nella gestione richieste (storico consegne, media reparto, proposta AI che impara dalle decisioni del gestore)

## Dettaglio

Ciclo completo DPI dal magazzino alla consegna firmata al dipendente.

- **8 modelli**: CategoriaDPI (con immagine, vita utile e flag obbligatorio mansionario), TipoDPI (sottocategoria), ModelloDPI (codice, produttore, immagine, vita utile override), TagliaDPI (valore taglia), DPIImpostazioni (singleton), RichiestaDPI, ConsegnaDPI (1:1 con firma PNG base64), RichiestaDPICommento
- **Gerarchia DPI**: Categoria → Tipo → Modello → Taglia gestibile da `/dpi/impostazioni/`, con immagine modello e attivazione/disattivazione record
- **Icona categoria**: selezionabile da un set di 11 icone SVG line-style (sprite `dpi/components/_dpi_icons.html`, filtro `dpi_extras.dpi_icon_key`) al posto di un'emoji libera; sostituibile con un'immagine caricata. Le emoji storiche già salvate restano visualizzate correttamente tramite mappatura automatica. L'icona «Mascherina / respiratore» (`mask`) è una semimaschera con due filtri vista di fronte (21/10/2026); la migrazione `dpi 0013` assegna `mask` alle categorie con «respir»/«mascher» nel nome rimaste sull'icona predefinita (gilet)
- **Richieste** con **card-picker grafico** per la categoria e selezione opzionale di tipo/modello/taglia; resta supportata la richiesta con sola categoria
- **Numerazione univoca** `DPI-YYYY-NNNN`
- **Stati workflow**: creata → approvata → consegnata → rifiutata/annullata
- **Approvazione** da parte del responsabile sicurezza con commenti
- **Consegna** con firma dipendente via canvas HTML5, data e ricevuta firmata; una nuova consegna dello stesso `tipo_dpi` già in carico allo stesso dipendente sostituisce automaticamente la precedente (che resta in storico, uscendo dai conteggi "in uso"/scadenze)
- **Vita utile** DPI tracciata per categoria/modello: il modello, se valorizzato, sovrascrive la vita utile categoria nel calcolo della scadenza consegna; lista e dettaglio mostrano il semaforo scadenza. Cambiando la vita utile di categoria o modello, le consegne in uso con scadenza automatica si riallineano subito (`segnali_scadenze.py`); restano quelle con scadenza inserita a mano e quelle già sostituite
- **Report conformita** per dipendente su `/dpi/report-conformita/`, con filtro categorie obbligatorie e stato OK/scaduto/mancante
- **Reminder scadenze** schedulabile con `python manage.py send_dpi_expiry_reminders --dry-run`
- **Storico** completo per dipendente con export PDF
- **KPI dashboard** su consumi, costi, scadenze imminenti
- **Leggi un DDT** (Magazzino, scheda accanto a «Carico da DDT»): PDF o foto del DDT → `core.lettura_documenti` (testo nativo, OCR Tesseract per le scansioni) → `dpi/lettura_ddt.py` propone numero, data, fornitore e una riga per ogni codice `ModelloDPI` attivo trovato nel testo, con la quantità della stessa riga (prima «PZ 24», poi «24 PZ»; «da controllare» se incerta). Il gestore spunta e corregge; `azione=carico_ddt` registra un `magazzino.carica_ddt` per riga. Stessa URL `/dpi/magazzino/` (azioni POST `leggi_ddt`, `carico_ddt`), stesso controllo `_is_gestore`; il file non resta sul server.

## Ruoli del portale

Con il sistema dei ruoli attivo ([PERMESSI_RUOLI.md](../ai/PERMESSI_RUOLI.md)): «gestire» apre consegne, magazzino, catalogo e impostazioni (Sicurezza, Magazzino); «approvare» approva sul perimetro del ruolo, per preposti e responsabili il team d'organigramma; nessuno approva la propria richiesta, ma la richiesta inserita da un CAR/preposto (chi ha almeno un dipendente in `flusso.dipendenti_di_approvatore`), per sé o per un suo dipendente, è **approvata automaticamente**. Dashboard e dettaglio mostrano proprie, del team o tutte secondo «vedere». Ciclo e destinatari: nuova richiesta → responsabile/co-responsabili/preposto del dipendente (ripiego `dpi_car_emails`) + referenti DPI se è spuntato «Email ai referenti… per ogni nuova richiesta»; approvata → «Da consegnare» al solo Magazzino; il magazzino preme «Pronto per il ritiro» (`/dpi/gestione/<id>/pronta/`, campi `pronta_ritiro_il`/`_da_nome`, lo stato resta APPROVATA e si mostra «Pronta al ritiro») → mail (evento `dpi_pronta_ritiro`) e notifica al dipendente; con `DPIImpostazioni.avviso_ritiro_all_approvazione` l'avviso parte già all'approvazione; rifiutata dopo l'approvazione → «Consegna annullata» al Magazzino (evento `dpi_consegna_annullata`); consegnata → report con PDF al responsabile/preposto del dipendente + Amministrazione solo se `CategoriaDPI.avvisa_amministrazione_consegna` (default sì). Promemoria scadenze (`dpi_expiry_reminders`, 07:10): elenco completo ai referenti DPI + `dpi_reminder_emails` (ripiego ADMINS/superuser); al responsabile/preposto solo la sua squadra e al dipendente in-app, solo nei giorni di avviso (30/7/1/0 giorni prima, poi il giorno dopo la scadenza e ogni 7 giorni); le consegne sostituite non contano. Sempre: la notifica in-app di approvazione, rifiuto e consegna va all'account del richiedente (prima riceveva l'id anagrafica come id utente e poteva arrivare a un'altra persona).

## Banco consegne (02/11/2026)

`/dpi/banco/` (`dpi:banco`, gate `_is_gestore`, perimetro «gestire» con i ruoli attivi): richieste `APPROVATA` raggruppate per richiedente, ricerca client-side, giacenza per modello (`magazzino.giacenze`). Azioni POST sulla stessa URL: `pronta` (avviso di ritiro per le spuntate non ancora pronte), `consegna` (una firma per tutte le spuntate, ognuna passa da `_registra_consegna`, lo stesso percorso di `/dpi/gestione/<id>/consegna/`), `diretta` (crea la richiesta già `APPROVATA` per un dipendente di `_dipendenti_selezionabili`, solo modelli di categorie con `consegna_diretta`; nessuna mail fino alla consegna). `CategoriaDPI.consegna_magazzino` (default sì; migrazione `0015` la spegne per le calzature): il banco mostra solo queste (le altre con `?tutte=1`) e `flusso.destinatari_consegna` manda «Da consegnare»/«Consegna annullata» al Magazzino oppure ai referenti DPI.

## Conferma della ricevuta via mail (02/11/2026)

Consegna senza firma né «Ricevuta firmata su carta» (banco o scheda) → `conferme.richiedi(consegne)`: una `ConfermaConsegnaDPI` per le consegne fatte insieme alla persona, una mail con link personale (`LinkConfermaDPI`, solo hash) al dipendente se la sua `email_notifica` è di `DPIImpostazioni.domini_email_aziendali` (vuoto = qualunque), altrimenti a `flusso.email_preposti`, in mancanza ai referenti DPI. Pagina pubblica `/approval-actions/dpi/<segreto>/<conferma|contesta>/` (`views_conferma.conferma_ricevuta`, `@risposta_pubblica_con_form`, CSRF esente come i link di approvazione: GET mostra, POST decide una volta). Contestata → mail a `flusso.destinatari_consegna`. `conferme.sollecita()` dal task `run_dpi_expiry_reminders`: un promemoria dopo 3 giorni, link rigenerati. URL pubblica nuova ma sotto un prefisso già in `MIDDLEWARE_EXEMPT_PREFIXES`; con token inesistente risponde 404 (nessuna voce in `PUBLIC_VIEWS`).

## Banco in home, link nella mail, PDF di consegna (03/11/2026)

- Home (`home_portale`, stanza «Oggi»): riquadro «Banco consegne DPI» da `dpi/pannello_home.riepilogo_banco(request)`, solo se `_is_gestore` (stesso gate e perimetro del banco, stesse funzioni `_banco_queryset`/`_banco_persone`/`_banco_conferme_qs`). Riquadro `banco_dpi` in `HOME_RIQUADRI`, proposto in «Personalizza» solo a chi gestisce (`_riquadri_offerti`); chi non lo vede non ne cambia lo stato salvando. Link per persona `/dpi/banco/#apri-<chiave>` (apre la consegna), ricerca `GET /dpi/banco/?cerca=` (filtra e, con un solo risultato, apre la consegna), `#diretta`, `#conferme`.
- Mail «Da consegnare» (`flusso.notifica_approvata`): pulsante «Apri il Banco consegne» (`flusso.link_banco`, via `core.accounts.portal_links.portal_link`: `SITE_URL` + accesso Windows) sulla scheda della persona; `?tutte=1` per le categorie non del magazzino. Senza `SITE_URL` niente pulsante.
- PDF (`dpi/pdf.py`): celle che vanno a capo, colonne Richiesta/DPI/Modello (con codice)/Taglia/Q.tà/Scadenza, dati in tabelle etichetta-valore, motivazione e note, riquadro «Ricevuta» (firma, esito della conferma via mail o riga per la firma su carta solo se non c'è né l'una né l'altra). Testo utente escapato.

Nessuna migrazione, nessun permesso nuovo (la home è già aperta a tutti, il riquadro dipende da «gestire» DPI).

## KPI coerenti e in tempo reale (02/11/2026)

«In scadenza» e «Scadute» della dashboard sulle consegne delle richieste visibili.

## Dashboard «Da fare» e richiesta guidata (05/11/2026)

- Dashboard: i vecchi contatori sono sostituiti da **«Da fare»** (`views._da_fare`): «In attesa di approvazione» e «DPI scaduti»/«In scadenza (30 gg)» sul perimetro di `_gestione_scope` (lo stesso di `/dpi/gestione/`), «Da consegnare» (come il banco, con la nota «+ N non del magazzino») e «Da riordinare» (`magazzino.da_riordinare`, zero se il magazzino non ha movimenti) solo per chi gestisce. Ogni numero apre la lista che lo mostra uguale; nuovo filtro `/dpi/gestione/?scadenza=scaduti|in_scadenza`.
- **«La mia dotazione»** (`dpi/dotazione.py`, per chi ha un'anagrafica): DPI previsti dalla mansione e mancanti, richieste in corso con il passo, consegne attive dalla più urgente, con «Richiedi il ricambio» (link alla richiesta compilata) o «Rotto o perso?». Scadenza da `ConsegnaDPI.semaforo_scadenza`; le consegne sostituite non contano.
- **Nuova richiesta**: ricerca su categoria, tipo, modello e codice (trova anche i DPI fuori profilo, con motivo obbligatorio); stato sulla scheda; i campi compaiono dopo la scelta e solo se hanno opzioni, con compilazione automatica delle scelte uniche; avvisi su richiesta già aperta e DPI ancora valido (non bloccano); «Uguale all'ultima volta»; motivi rapidi. Parametri `?categoria=&tipo=&modello=&taglia=&motivo=scadenza|prima`. Un errore di invio non perde quanto scritto.
- Corretti: chi gestisce perdeva il menu completo in Nuova richiesta; senza anagrafica collegata «Richiesta per» partiva dal primo dipendente in elenco, a cui finiva la richiesta (ora «Me stesso»).

Nessuna migrazione, nessun permesso nuovo.

## Scarpe al negozio: convenzione e fuori convenzione (05/11/2026)

`CategoriaDPI.si_ordina_al_negozio` (migrazione `0017`, accesa per le calzature) fa scegliere nella richiesta `RichiestaDPI.modalita_negozio`. Le altre categorie e le richieste già aperte (modalità vuota) seguono il flusso di prima. Logica in `dpi/negozio.py`, pagina `/dpi/negozio/` (`views_negozio.py`, gate `_is_gestore`, voce «Scarpe»: l'operatore deve avere «gestire» DPI).

- Approvazione → mail all'operatore incaricato (`DPIImpostazioni.negozio_operatore_emails`, ripiego referenti DPI), non al magazzino; vale anche per «Consegna annullata». Niente avviso di ritiro automatico all'approvazione.
- **Convenzione**: l'operatore manda il riepilogo con «Invia l'ordine» (`OrdineNegozioDPI`, regola `dpi_ordine_negozio`, mail a `negozio_email` e in copia a lui) o lo segna se ha scritto a parte. Le righe contengono nome del dipendente, modello, taglia, quantità e numero richiesta. Promemoria dal task `dpi_expiry_reminders` passati `negozio_giorni_riepilogo` giorni (15), ripetuto ogni 3 (regola `dpi_promemoria_ordine_scarpe`). Ordinate: entrano nel banco con `?tutte=1` e si chiudono come gli altri DPI, conferma di ricevuta compresa.
- **Fuori convenzione**: «Negozio avvisato» avvisa il dipendente; si chiude con fattura + spunta (`FatturaNegozioDPI`, storage privato cifrato, audit, download solo per chi gestisce). La data fattura è la data di consegna; nessuna conferma di ricevuta. Banco e scheda non la chiudono.
- Nessuno scarico di magazzino per le scarpe con modalità; i modelli di queste categorie escono da pagina e report Magazzino e da «Da riordinare» (`magazzino.modelli_di_magazzino`).

Al deploy: `migrate` (dpi 0017), `setup_q_schedules` per le regole nuove, poi in Impostazioni DPI mail del negozio e operatore; dare all'operatore «gestire» DPI.

## Banco consegne più veloce (05/11/2026)

Elenco delle persone a sinistra, scheda a destra (`dpi/components/_banco_lavoro.html`). Azioni con fetch dalla pagina aperta: con `X-Requested-With: XMLHttpRequest` `dpi:banco` risponde con la sola parte di lavoro e l'header `X-Banco-Apri` (persona da riaprire), i toast li consegna `FlashMessagesDeliveryMiddleware`; senza quell'header resta il redirect. Ricerca su nome, reparto, numero e modello; una sola persona trovata apre la scheda; pulsante «Consegna N DPI a…» senza passaggio intermedio; filtri sui riquadri numerici; tastiera (`/`, frecce, Invio, Esc); aggiornamento ogni 60 secondi solo a banco fermo; «+ Consumabile» apre la consegna diretta con la persona scelta. Stesse azioni e stessi controlli di prima, nessuna migrazione.

## Strumenti del banco e bozza d'ordine (05/11/2026)

- **Annulla consegna**: la consegna dal banco resta nel browser per 6 secondi (`ATTESA_SECONDI` in `banco.html`), poi parte il POST; fino ad allora il server non sa nulla, quindi nessuna mail e nessuno scarico. Una nuova azione o l'uscita dalla pagina la mandano subito (`sendBeacon`). Senza JavaScript resta l'invio immediato.
- **Cambia modello**: `azione=cambia` su `dpi:banco` (`_banco_cambia_modello`): stessa categoria, modello e taglia attivi, perimetro del banco; commento nella richiesta e `log_action`. Non vale per le scarpe al negozio.
- **Badge**: la ricerca riconosce `DipendenteAnagraficaAziendale.badge` (corrispondenza esatta) come lo digita un lettore a tastiera; chi non ha richieste aperte viene riconosciuto se è tra i dipendenti selezionabili.
- **Lista di prelievo** `/dpi/banco/prelievo/` (`dpi:banco_prelievo`, gate `_is_gestore`): richieste non ancora pronte sommate per modello e taglia, stampabile, avviso di ritiro in blocco.
- **Bozza d'ordine** `/dpi/magazzino/riordino/` (`dpi:magazzino_riordino`, gate `_is_gestore`): `magazzino.bozza_ordine`, l'elenco `riordino` del report diviso per ultimo fornitore. Solo testo da copiare o aprire nella posta.

Nessuna migrazione, nessun permesso nuovo.
