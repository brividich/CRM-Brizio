# Riepilogo lavori e collaudo 05-06/11/2026

Versione completa con schermate: `Riepilogo_collaudo_20261105-06.pdf`.

## Stato

- **Periodo analizzato**: dal 05/11/2026 ore 08:38 al 06/11/2026 ore 12:45
- **Quantità**: 64 commit di lavoro, 560 file, 30 migrazioni
- **main**: 3a819e8c, contenuto identico a release/prod 6a060250
- **Ultimo pacchetto**: 06/11 ore 12:00 da 67463dcf: non contiene Sistema di gestione (629607ad), Qualifiche per centro (34f1e78a), Approva/Rifiuta nella mail (b8515845), ingressi su manutenzione e scadenze (0c9a075a)
- **Produzione**: Secondo gli appunti, tutto questo risulta non ancora deployato. Non verificato: l'unità Y: non è raggiungibile da questa sessione. Controlla Y:\current\BUILD_INFO.json.
- **Fuori da questa prova**: feature/tasks-fai-storico (73129cb1): non è in main. Il server di sviluppo su :8000 può girare da quel ramo: per le prove serve un'installazione da release/prod.

## Difetti trovati

- **D1** (ALTO · confermato): Il verbale di evacuazione dà errore 500 se un esterno non è stato contato. Il modello legge p.reparto come argomento del filtro default, ma nei dati degli esterni quella chiave non viene salvata. Basta un visitatore non spuntato alla chiusura: è proprio il caso che il verbale deve documentare. Provato con DEBUG spento su dati finti: 500 con un esterno non contato, 200 con tutti contati; PDF e stampa rispondono 200. I 36 test di presenti passano: il caso non è coperto. Dove: presenti/templates/presenti/verbale.html:51 e presenti/views.py:177. Non corretto: la richiesta era di analisi.
- **D2** (BASSO · confermato): Il titolo della scheda del browser su «Le mie richieste» dice «Impostazioni Assenze».
- **D3** (BASSO · da guardare): /automazioni/mail-inviate/ risulta larga 1445 px con finestra da 1440: probabile piccolo scorrimento laterale della barra delle schede.
- **D4** (AMBIENTE): 2 test di scadenzario sono rossi perché pymysql manca nel venv locale, non per il codice. In prod il pacchetto serve al GuestPortal: controllare che sia installato.
- **D5** (BASSO · test rosso): assets.tests_part145: test_pagina_ricerca_unica_e_kpi cerca data-fm-table-skip="1" nella pagina di ricerca Part 145 e non lo trova. Era già annotato come rosso il 05/11. Causa non analizzata: da guardare se la ricerca e i KPI di quella pagina si comportano come previsto.

## Prove su tutto il portale

- [ ] GEN-01 [A] Su SQL Server: migrate di tutte le 30 migrazioni. → Nessun errore, anche quelle che caricano dati (anagrafica 0216, fornitori 0010).
- [ ] GEN-02 [A] Ogni pagina nuova da dipendente semplice, con ACL strict. → Le rotte di lavoro non sono negate per errore; quelle riservate rispondono 403; le API danno JSON, mai redirect.
- [ ] GEN-03 [A] Task pianificati dopo il riavvio di qcluster. → Vedi dpi_avvisi_consegna, fornitori_avvisi_ingressi_non_in_regola, scadenzario_foto_giornaliera, presenti_avvisi_uscite nell'elenco e con esito positivo.
- [ ] GEN-04 [A] Mail vere in un ambiente di prova, poi Mail inviate. → Ogni mail attesa è registrata; nessuna mail a destinatari reali durante le prove.
- [ ] GEN-05 [M] Giro delle pagine in tema scuro e su telefono a 390 px. → Testi leggibili, nessuno scorrimento laterale (noto: dettaglio incontro KICK-OFF).
- [ ] GEN-06 [M] Ogni pulsante «? Guida» sulle pagine nuove. → Apre la guida del modulo; etichette uguali a quelle a video.
- [ ] GEN-07 [M] Schermi 4K o zoom del browser. → Le pagine a colonne usano l'altezza disponibile.

## Passi per il deploy

- Pacchetto nuovo da release/prod, perché quello delle 12:00 non basta.
- migrate: anagrafica 0214-0222, assenze 0014, core 0109-0110, dpi 0017-0018, fornitori 0008-0012, presenti 0002, scadenzario 0003-0004, sistema_gestione 0022, tasks 0051-0056, tickets 0016.
- collectstatic (guide, tasks.css, tech_refs.js, bundle anomalie, ruoli_portale.css, hub-form-bozza.js).
- setup_q_schedules e riavvio di qcluster. bootstrap_acl_v2 --apply.
- Variabili .env persistenti: SOLARI_DB_* con login in sola lettura, GUESTPORTAL_* se mancano.
- scadenzario_foto; archivia_notifiche_scadenza_errate --fino-al <data>, poi --apply; importa_incarichi_presenze --ini ... --apply.

## Presenti in azienda

`/presenti/` · commit 135da2d0, 917d1539, 45cd5994, 941d2d9b, 3764a6b4, 81f9b1da, ecf43ffd

### Cosa è stato fatto

- Esterni del GuestPortal nella lista, nell'appello di evacuazione e nel PDF.
- Uscite non timbrate: il controllo guarda l'intera giornata (uscita mancante, verso sbagliato, sequenza irregolare, turni di notte fino a 16 ore). Una persona con U·U risulta presente «da verificare».
- Mail e notifica al capo solo per l'uscita mancante: gli altri problemi di timbratura restano solo in pagina.
- Verbale di evacuazione: tempi, contatori al 50/90/100%, chi ha contato, non contati, osservazioni, PDF. Le esercitazioni si possono eliminare.
- Andamento per reparto: persone dentro ora per ora, solo numeri, senza nomi.
- Pallino «In azienda» anche nell'organigramma ad albero e in «Il mio team».
- Comando di import incarichi: accetta un config.ini salvato con BOM e segnala il file mancante.

### Cosa resta da fare

- Correggere il difetto D1 sul verbale prima di usarlo in un'evacuazione vera.
- Al deploy: variabili SOLARI_DB_* con un login in sola lettura, migrazioni, pianificazioni, riavvio di qcluster, import degli incarichi.
- Dopo le prove: attivare la pubblicazione del PDF e spegnere il vecchio programma ReportPresenze.
- Scelta rimandata: appello senza rete, da valutare più avanti.

### Checklist

- [ ] PRE-01 [A] Chiudi un appello lasciando non contato un esterno, poi apri il verbale. → La pagina si apre. Oggi dà errore 500: difetto D1.
- [ ] PRE-02 [A] Avvia un appello da due dispositivi e spunta persone diverse. → Ognuno vede le spunte dell'altro entro pochi secondi; i contatori coincidono.
- [ ] PRE-03 [A] Scarica il PDF del verbale e la stampa dell'appello. → Dati uguali alla pagina; esterni presenti con la ditta.
- [ ] PRE-04 [M] Elimina un'esercitazione, poi prova con un appello che non è un'esercitazione. → La prima sparisce; per la seconda il comando non c'è. Chi non l'ha avviata non può eliminarla.
- [ ] PRE-05 [A] Cerca una giornata con un'uscita mancante. → Il capo riceve notifica e mail.
- [ ] PRE-06 [A] Cerca una giornata con due uscite di seguito. → Riga «solo in questa pagina, nessun avviso»: nessuna mail al capo.
- [ ] PRE-07 [M] Controlla una persona del turno di notte entrata ieri sera. → Risulta presente; non è segnalata come uscita mancante.
- [ ] PRE-08 [M] Apri «Andamento per reparto» e confronta la colonna «Adesso» con la lista dei presenti. → Stessi numeri per reparto; nessun nome visibile.
- [ ] PRE-09 [B] Apri l'organigramma ad albero e «Il mio team». → Il pallino compare solo su chi è in azienda.
- [ ] PRE-10 [M] Entra da un utente senza permessi speciali. → Vede la lista (scelta decisa il 04/11) ma non le uscite di tutta l'azienda.

## Scadenzario

`/scadenze` · commit cd674dcf, f6a6c53f, 589fc926, c75c1835, 72bcf3ef, 85ef589d, 89ddcdd5, 414c4279

### Cosa è stato fatto

- Vista calendario del mese come apertura, poi anno, agenda, elenco e andamento. Festivi e patrono segnati.
- Schermo intero per il monitor, con aggiornamento automatico; stampa A4 orizzontale.
- Filtri multipli per fascia, fonte e reparto più ricerca; viste salvate con predefinita; «Solo le mie».
- Azioni sulla voce: «Me ne occupo io» con nota, «Assegna» con notifica, «Rinnovato oggi» per le scadenze generiche.
- Gestione più semplice: riquadro «Da sistemare», ricerca nell'albero, frase su chi vede la voce, regole dentro la categoria, modifica di più attività insieme.
- Anteprima avvisi del prossimo invio, anche col comando scadenzario_avvisi.
- Collega e Unisci alle cose già presenti nel portale; Separa annulla. Riquadro «Scadenze di questa scheda» in dipendente, corso, asset, verifica impianto, fornitore, certificazione, audit, incidente.
- Nuove fonti: OFI, anomalie e NC, attività proprie, Suggestion Corner, attrezzature, ingressi e cambi mansione, manutenzione programmata (spenta di serie), termini NIS2/GDPR.
- Le mie scadenze in Cose da gestire, senza dati sanitari, con cache di 5 minuti.
- Correzione importante: le notifiche di visite e formazione finivano sull'account sbagliato. Ora vanno alla persona giusta.
- Guida completa con immagini e PDF.

### Cosa resta da fare

- Dopo il deploy, in ordine: archivia_notifiche_scadenza_errate --fino-al <giorno prima del deploy>, controllo, poi --apply. Non cancella; riguarda le 430 notifiche visita inviate con l'id sbagliato dal 13/10.
- Decidere con chi segue la privacy se serve altro per quelle notifiche.
- Spegnere lo scheduler sul NAS; assegnare le categorie ai ruoli: senza regole le generiche le vedono solo pannello e responsabile.
- Da concordare con HR e RSPP: ritiro di visite_mediche_digest e riordino delle mail.
- Non fatti: filtro per team, ricerca AI e Ctrl+K. Il filtro per centro di costo non c'è nello Scadenzario generale.
- Il promemoria OFI resta a comando manuale: i vecchi reminder_inviato sono falsi e vanno riesaminati prima di pianificarlo.
- La fonte manutenzione programmata è spenta: si accende da Gestione (in prod sono 212 voci).

### Checklist

- [ ] SCA-01 [A] Confronta i contatori in alto con il calendario e con l'elenco. → Stessi totali; un clic su un contatore mostra le stesse voci.
- [ ] SCA-02 [A] Filtra per fonte + reparto + fascia, ricarica la pagina. → I filtri restano e i contatori si adeguano.
- [ ] SCA-03 [M] Usa «Me ne occupo io» con una nota, poi «lascia». → La nota compare e sparisce; la voce resta dopo il ricaricamento.
- [ ] SCA-04 [A] «Assegna» una voce a un collega. → Il collega riceve la notifica e la voce gli compare in «Le mie scadenze».
- [ ] SCA-05 [M] «Rinnovato oggi» su una generica con validità. → Nuova data calcolata; il pulsante non compare se la validità manca.
- [ ] SCA-06 [M] Salva una vista e impostala come predefinita. → Aprendo /scadenze senza filtri si riparte da quella vista.
- [ ] SCA-07 [B] Schermo intero, Esc, stampa. → Il calendario riempie lo schermo; Esc esce; la stampa sta in A4 orizzontale.
- [ ] SCA-08 [A] Collega un'attività a una certificazione, poi Unisci, poi Separa. → Con Unisci resta una voce con la data del modulo; Separa riporta due voci.
- [ ] SCA-09 [M] Apri una scheda dipendente, asset e fornitore. → Il riquadro «Scadenze di questa scheda» rispetta i permessi.
- [ ] SCA-10 [A] Scadenza di visita medica in promemoria. → La notifica arriva alla persona giusta, mai a un altro account.
- [ ] SCA-11 [A] Da un utente senza permessi HR, guarda «Le mie scadenze». → Nessun dato sanitario di altri.
- [ ] SCA-12 [M] Modifica in blocco di 3 attività; apri l'anteprima avvisi. → Cambiano tutte e 3; l'anteprima elenca destinatari coerenti, senza invii.
- [ ] SCA-13 [B] Apri la guida e scarica il PDF. → Immagini visibili (serve collectstatic); capitoli corrispondono alla pagina.

## Fornitori e Accessi esterni

`/fornitori/` · commit 76c5f65f, 0e868a09, dbbc75d4, ce558c34, 0c9a075a

### Cosa è stato fatto

- Requisiti di sicurezza per chi lavora in sede (art. 26): visura, idoneità, DURC, DUVRI, polizza, con scadenze anche nello Scadenzario.
- Avviso a RSPP/ASPP se entra una ditta non in regola: solo notifica, mai mail.
- Scheda della ditta con Manutenzione, Copie MFC, Scadenze e Tecnici. Tutto facoltativo: ogni scheda segue il permesso del modulo di origine.
- Pagina iniziale «Da guardare»; elenco con filtro documenti ed export CSV; corretto «Solo attivi».
- Registro dei tecnici: si registrano da soli all'ingresso o quando l'ingresso è collegato a un intervento, oppure a mano. Il tecnico non diventa un utente HUB: niente login (decisione del 06/11).
- «+ Crea fornitore» da Accessi esterni, senza doppioni.
- Collega… ora anche a manutenzione ordinaria, scadenza dell'asset e attività dello Scadenzario. Il collegamento è solo una prova di presenza: non registra e non rinnova.
- Corretto l'errore 500 della scheda Scadenze con un'attività senza data. Guida in-app nuova.

### Cosa resta da fare

- guestportal.tecnici_ditta non è mai stata eseguita sul database vero: testata solo con simulazioni. È la prima prova da fare dopo il deploy.
- Dopo il deploy riavviare qcluster, altrimenti il task dei 10 minuti non registra i tecnici e non manda gli avvisi.
- Abbinare le ditte da pagina: in prod risultavano 0 abbinate. Impostare i ruoli da avvisare (fornitori_requisiti_ruoli).
- Da confermare: il registro tecnici si vede con la scheda fornitore, permesso più largo di Accessi esterni.
- Fuori dal lavoro: collegamento alle verifiche impianti.
- Lato IT sul GuestPortal restano: rotazione dei segreti, root MySQL, HTTPS, LDAPS, cookie, restrizione IP del chiosco.

### Checklist

- [ ] FOR-01 [A] Apri la sezione Tecnici di una ditta reale, dopo il deploy. → Si carica senza errori e i nominativi corrispondono al GuestPortal (query mai provata sul vero).
- [ ] FOR-02 [A] Fai entrare una ditta con documenti mancanti. → Entro 10 minuti notifica a RSPP/ASPP; nessuna mail. Etichetta «Documenti non in regola».
- [ ] FOR-03 [A] Da Accessi esterni usa «+ Crea fornitore» su una ditta nuova. → Fornitore creato col nome del GuestPortal, tecnico registrato. Su una ditta già presente, anche non attiva, nessun doppione.
- [ ] FOR-04 [A] Verifica che il tecnico registrato non abbia un accesso. → Nessuna riga utente, nessun login.
- [ ] FOR-05 [M] «+ Nuovo tecnico», «Registra», «Registra tutti», disattiva. → Un tecnico disattivato resta tale se rientra; uno eliminato si registra di nuovo.
- [ ] FOR-06 [M] Carica un DURC con scadenza entro 30 giorni. → Stato aggiornato in scheda; voce nello Scadenzario.
- [ ] FOR-07 [A] Collega un ingresso a manutenzione ordinaria, a scadenza asset e a un'attività. → Riquadro nelle tre pagine; nessuna manutenzione risulta eseguita e nessuna scadenza rinnovata.
- [ ] FOR-08 [A] Apri la scheda con un utente che ha solo «fornitori». → Le schede di altri moduli rispondono negate, senza errori; ingressi e ore non visibili.
- [ ] FOR-09 [M] Apri la scheda Scadenze di un fornitore con un'attività senza data. → Nessun errore 500.
- [ ] FOR-10 [B] Elenco: togli «Solo attivi», filtro documenti, esporta CSV. → Compaiono anche gli inattivi; il CSV contiene le stesse righe.

## DPI

`/dpi/` · commit f5261daa, 4f405d9b, d6428194, d69affbf, 8c50077d, 8b4fcf8c

### Cosa è stato fatto

- Dashboard «Da fare»: ogni numero apre la lista che lo mostra uguale. «La mia dotazione» con mancanti, richieste in corso, scadenze e ricambio.
- Nuova richiesta guidata: ricerca, campi progressivi, avvisi su doppioni e DPI ancora validi, «Uguale all'ultima volta», motivi rapidi.
- Scarpe: in convenzione e fuori convenzione, pagina dedicata, riepilogo al negozio con promemoria ogni 15 giorni.
- Banco consegne senza ricaricare la pagina: persone e scheda affiancate, tastiera, ricerca per numero, modello e badge.
- Consegna salvata subito: per 6 secondi aspettano solo mail e PDF, «Annulla» li toglie e lascia traccia. Con giacenza insufficiente il server chiede il motivo.
- Lista di prelievo stampabile con avviso di ritiro in blocco; Bozza d'ordine per fornitore; cambio modello al banco.
- Report con Conformità di tutte le persone, Registro consegne, Consumi e magazzino; export Excel e PDF, pianificabili dal Centro report.
- Corretti: dettaglio persona fuori perimetro, elenco fermo a 100 senza avviso, categorie non dovute date per mancanti, richiesta finita al primo dipendente, errore 500 in Magazzino.

### Cosa resta da fare

- Da decidere: anagrafica/services/conformita.py conta in modo diverso dal nuovo report (solo obbligatorie). Oggi i due numeri possono non coincidere.
- Lettore badge 3022L: protocollo capito, un solo badge provato, non ancora collegato al portale. Da provare altri badge; da confermare quale levetta SW1 attiva l'uscita dati. Serve HTTPS per la lettura da browser.
- Report pianificati: mai provati con un invio reale.
- Al deploy: migrazioni, setup_q_schedules, riavvio di qcluster, mail di negozio e operatore nelle Impostazioni, permesso «gestire» all'operatore, caricare le quantità.
- Le richieste di scarpe già aperte restano sul flusso vecchio.

### Checklist

- [ ] DPI-01 [A] Clicca ogni numero della dashboard «Da fare». → La lista aperta ha lo stesso conteggio.
- [ ] DPI-02 [A] Consegna dal Banco, poi «Annulla» entro 6 secondi. → Consegna annullata con traccia; nessuna mail né PDF.
- [ ] DPI-03 [A] Consegna e chiudi subito il browser. → Mail e PDF partono comunque, dal task o alla riapertura del Banco, una volta sola.
- [ ] DPI-04 [A] Consegna con giacenza insufficiente, dal banco e dalla scheda. → Il motivo è obbligatorio e finisce nel registro («Consegne senza giacenza»).
- [ ] DPI-05 [M] Con il lettore o digitando: cerca per badge col fuoco su un pulsante. → Il codice finisce nella ricerca; una sola persona trovata si apre da sola.
- [ ] DPI-06 [M] Banco solo da tastiera: / cerca, frecce, Invio consegna, Esc. → Tutto funziona senza mouse; dopo la consegna il cursore torna sulla ricerca.
- [ ] DPI-07 [A] Scarpe in convenzione: richiesta, approvazione, ordine, arrivo, consegna. → Mail all'operatore e al negozio; avviso di arrivo; magazzino non toccato.
- [ ] DPI-08 [A] Scarpe fuori convenzione: avviso del negozio, chiusura con fattura. → Ordini spuntati e fattura allegata.
- [ ] DPI-09 [M] Nuova richiesta di un DPI ancora valido; «Uguale all'ultima volta»; errore di validazione. → Avviso sul doppione; campi precompilati; i dati non si perdono.
- [ ] DPI-10 [A] Report Conformità: controlla a mano 3 persone; esporta Excel e PDF. → Dovuti = obbligatori + mansione di rischio; export con tutte le righe filtrate.
- [ ] DPI-11 [A] Da gestore con perimetro ridotto apri il dettaglio di una persona fuori perimetro. → Accesso negato.
- [ ] DPI-12 [M] Lista di prelievo: stampa e «Pronti: avvisa gli spuntati». Bozza d'ordine: 30/90/180/365 giorni. → Avvisi solo agli spuntati; il portale non invia l'ordine da solo.

## KICK-OFF

`/tasks/` · commit b7a7f8d9, 903bd362, f01768d5, aee2b8c4, fc13a142, 0fa78b18, 41f06155, 3e403491, 4df5cb68, c853f9f7, f969a1cd

### Cosa è stato fatto

- VRF sul nuovo MOD.073: 9 rischi P × D, Gravità fissa, Totale Rischio con fasce (Basso fino a 35, Alto da 50, con avviso CEO), checklist, 4 azioni correttive, firme IN1/EM. Tolto il modulo a 3 fasi, mai usato.
- Kickoff più semplice: «Modifica» di dati e team, riga rapida sopra il Gantt, bozza VRF visibile, compilazione aperta anche a kickoff bloccato.
- Attività rapide dentro l'incontro: Invio salva senza ricaricare, «Più opzioni» si apre sotto la riga.
- Programmi e FAI: codici CAM, CMM e FAI con percorso di rete e responsabile, tutto facoltativo. Il clic copia il percorso, perché i browser non aprono file:// da una pagina web.
- Registro FAI (MT CN 15): una riga per articolo con il FAI più recente, causale che propone Completo o Delta, numero PFCN, controllo a 18 mesi, export CSV. Opzioni configurabili nelle Impostazioni.
- Il FAI è una proposta, non un obbligo: «Non richiesto per questo kickoff» con chi e quando, «Annulla» torna indietro.
- Attività di programmazione: il campo «Richiede» sul tipo crea o adotta la riga del programma. Nuova vista generale Programmi con filtri e CSV.
- Guida completa con immagini, due guide rapide per ruolo e PDF.

### Cosa resta da fare

- Storico FAI: non è in main. Il ramo feature/tasks-fai-storico (migrazioni 0057-0058, import di «Situazione FAI-ISIR») è fuori da questa prova. Domande aperte: significato di F0, F1, F2, SC-QC; 563 articoli in corso con FAI vecchi di oltre 2 anni; export «Spedito» di BMS per le scadenze; chi vede lo storico.
- Da confermare: significato di IN1 e EM nel VRF.
- Da decidere: il tipo generico «Programmazione» (ora senza «Richiede»); blocco vero alla chiusura senza programma; apertura diretta dei percorsi di rete, che richiede un protocollo su ogni PC.
- Se il registro sostituisce il file «Situazione FAI-ISIR» va aggiornato MT CN 15 §5.10.
- VRF per riga OIN: non iniziata, parte solo su richiesta. Proposta su storico P/N e dossier non ancora approvata.
- Noto: a 390 px la pagina dettaglio incontro scorre di lato.

### Checklist

- [ ] KIK-01 [A] Compila una VRF con P diverse. Confronta con il file MOD.073. → R = P × D; totale e fascia uguali a Excel. Da 50 in su compare l'avviso CEO.
- [ ] KIK-02 [A] Scarica la VRF compilata; carica un modulo vecchio e uno nuovo. → Celle giuste nel file; riconosciuti entrambi.
- [ ] KIK-03 [A] Compila la VRF con kickoff bloccato. → Si può compilare e il blocco si scioglie online.
- [ ] KIK-04 [M] Nell'incontro scrivi un'attività e premi Invio, più volte; apri «Più opzioni». → Salva senza ricaricare, tiene il responsabile, inizia il giorno dopo la fine appena scritta.
- [ ] KIK-05 [A] Aggiungi un programma assegnato a una persona fuori dalla commessa. → Compare in «Le mie azioni» e «Le mie attività»; quella persona vede la commessa.
- [ ] KIK-06 [B] Clicca un percorso di rete. → Il percorso è copiato negli appunti.
- [ ] KIK-07 [A] Registro FAI: nuovo FAI con causale diversa dalla proposta. → Chiede il motivo; numero PFCN automatico.
- [ ] KIK-08 [A] Articolo con ultima spedizione oltre 18 mesi. → «Oltre 18 mesi» nel registro e nel CSV.
- [ ] KIK-09 [A] «Non richiesto per questo kickoff», poi Annulla; aggiungi poi una riga FAI. → Restano chi e quando; Annulla torna indietro; con una riga FAI vale il FAI e il pulsante sparisce.
- [ ] KIK-10 [A] Attività di un tipo con «Richiede» CAM: creala, assegnala, chiudila senza codice. → Riga creata con responsabile, data e stato; la riga resta «da inserire».
- [ ] KIK-11 [M] Cancella il programma su un'attività chiusa; chiudi da «Le mie azioni»; elimina il tipo. → Attività e riga non si separano (casi del ricontrollo f969a1cd).
- [ ] KIK-12 [M] Impostazioni scheda FAI: modifica motivi, piani, stati e mesi. → Valgono subito; i mesi cambiano la scadenza calcolata.
- [ ] KIK-13 [B] Apri la guida da «? Guida» su varie pagine; scarica il PDF. → Si apre sul capitolo giusto; immagini visibili (serve collectstatic).
- [ ] KIK-14 [M] Utente senza permessi su /tasks/programmi/ e /tasks/fai/ in prod. → Con ACL strict servono i binding: verificare che il bootstrap li abbia creati.

## Anagrafica: centri di costo e struttura

`/anagrafica/` · commit 102b81fb, df133a93, 004052b7, d5c23e77, 6a773f7e, 5e96bde0, 66f15183, 61ce2a87, 34f1e78a

### Cosa è stato fatto

- Centri di costo: un centro include più reparti, un reparto sta in un solo centro. La migrazione 0216 carica l'elenco aziendale. Nuovo ruolo CAMM «CAM Manager».
- Centro di costo nei report, nella scheda, nell'elenco, in Costo orario e Storico, con filtro ed export. Filtro per centro anche su Formazione, Visite, Scadenzario HR, DPI e Qualifiche.
- Esplora la struttura: colonne centro → reparto → ruolo → mansione → competenza, percorso, «Altre strade», ricerca, passaggio tra le voci senza ricaricare.
- Prospetto dei cambiamenti: prova spostamenti senza scrivere niente, confronta Oggi e Dopo su persone, capi, costo, mansioni scoperte e carico, poi applica riga per riga.
- Soglie del sovraccarico nelle Impostazioni Skill Matrix.
- Regola unica del carico (conta chi è in forza) su Prospetto, report, Esplora, schede, Centri di costo, Mansionario, Il mio team e Home. Nuovo report Carico sulle persone.
- Qualifiche: filtro per centro su cruscotto e scadenzario, numeri allineati fra i due.

### Cosa resta da fare

- Al deploy la 0216 crea 11 aree vuote e riattiva Taratura. Le aree attive fuori elenco (CLG, CN5G, CONTROLLO QUALITA', LIQUIDI PENETRANTI, UFFICIO TECNICO) restano senza centro: le persone le smista l'utente.
- In prod le competenze delle mansioni sono 0: l'ultima colonna di Esplora resta vuota finché non si caricano.
- Il carico è un segnale, non una misura: il portale non ha le ore per mansione.
- Non c'è storico del centro: vale il centro di oggi anche sui mesi passati del costo.
- Resta fuori dal filtro per centro lo Scadenzario generale. In «Chiedi un report» senza AI il centro vale solo se scritto «centro di costo X» o «cdc X».

### Checklist

- [ ] ANA-01 [A] Dopo la 0216 confronta l'elenco centri e reparti con quello aziendale. → 25 centri, nessuna area rinominata, persone al loro posto.
- [ ] ANA-02 [A] Sposta un reparto su un altro centro; controlla report e Costo orario. → Il dipendente segue il centro in report, scheda, costo e storico.
- [ ] ANA-03 [A] Report «Centri di costo»: somma persone e costo orario, confronta con Esplora. → Stessi numeri; le colonne economiche solo per chi ha il permesso HR.
- [ ] ANA-04 [A] Da utente senza permessi HR apri Centri di costo ed Esplora. → RML e costo non visibili, neppure nell'export.
- [ ] ANA-05 [M] Esplora: scendi fino alla mansione, risali dal percorso, usa la ricerca e «Altre strade». → Passaggio senza ricaricare; scelte conservate; frecce avanti/indietro funzionano.
- [ ] ANA-06 [A] Prospetto: aggiungi 4 cambiamenti e controlla che in anagrafica non cambi niente. → Nessuna scrittura fino ad «Applica».
- [ ] ANA-07 [A] Applica riga per riga, una anche non più valida. → Esito per ogni riga e fotografia; i valori «Dopo» coincidono col risultato reale.
- [ ] ANA-08 [M] Confronta due prospetti; esporta Excel e PDF. → Stessi valori di pagina.
- [ ] ANA-09 [M] Cambia le soglie nelle Impostazioni Skill Matrix. → Valgono per tutti i prospetti; quelli applicati conservano i vecchi valori.
- [ ] ANA-10 [A] Filtro centro su Formazione, Visite, Scadenzario HR, DPI, Qualifiche. → Pagina ed export hanno le stesse righe; compare «Senza centro di costo».
- [ ] ANA-11 [M] Qualifiche: confronta cruscotto e scadenzario. → Stessi conteggi.
- [ ] ANA-12 [M] Una persona con cessati nella lista mansione: confronta Carico e Copertura. → Carico conta solo chi è in forza; Mansionario lo segnala in «Liste da ripulire».

## Assenze

`/assenze/` · commit c1ba2408, ed6ba396, 9af28393, b8515845

### Cosa è stato fatto

- Ore del permesso nel calendario: «Permesso - 8h», le stesse ore che scala il saldo.
- «Sollecita» in «Le mie richieste», con le impostazioni di Area HR; manuale e automatico non si sommano.
- Mail al capo neutra: non dice che è un sollecito né chi l'ha chiesto.
- Approva e Rifiuta nella mail, con link personale, se l'approvazione è aperta e non scaduta e il capo è fra gli approvatori. Il clic apre una conferma: la decisione avviene nel passo dopo, così gli scanner di posta non approvano da soli.
- Cambio capo reparto: sezione in Impostazioni. Elenco vuoto = tutti, come prima. Gli altri hanno il campo bloccato; chi non ha un capo sceglie comunque dall'elenco, verificato sul server.

### Cosa resta da fare

- Da rivedere: non c'è attesa minima prima del primo sollecito manuale (scelta tecnica, non chiesta).
- Non verificato sui dati di prod quante richieste ferme abbiano un'approvazione valida: oltre i 7 giorni la mail non ha i pulsanti.
- HR deve spuntare chi può cambiare il capo: finché l'elenco è vuoto non cambia niente.
- L'ultimo commit (Approva/Rifiuta) non è nel pacchetto delle 12:00.

### Checklist

- [ ] ASS-01 [A] Sollecita una richiesta in attesa, poi riprova subito. → Una mail; il secondo sollecito è bloccato secondo «ripeti ogni N giorni».
- [ ] ASS-02 [A] Lascia girare anche il sollecito automatico. → Il capo non riceve mail doppie.
- [ ] ASS-03 [A] Leggi la mail ricevuta dal capo. → Oggetto «Richiesta di assenza da approvare»; nessuna parola «sollecito» o «promemoria»; nessun nome di chi ha sollecitato.
- [ ] ASS-04 [A] Clicca Approva dalla mail, ma non confermare. → Si apre la conferma; la richiesta non cambia finché non confermi.
- [ ] ASS-05 [A] Conferma; riapri poi lo stesso link. → Decisione registrata; al secondo clic risulta già gestita.
- [ ] ASS-06 [A] Link di un'approvazione scaduta o inoltrato a un'altra persona. → Nessuna decisione possibile.
- [ ] ASS-07 [M] Mail per un capo che non è fra gli approvatori. → Solo il link al portale, nessun pulsante.
- [ ] ASS-08 [A] Spunta una persona in «Cambio capo reparto»; prova con lei e con un altro. → Lei cambia il capo; l'altro ha il campo bloccato. Con elenco vuoto tutti possono.
- [ ] ASS-09 [A] Utente non abilitato senza capo assegnato; prova a forzare un capo fuori elenco. → Sceglie solo dai capi in elenco; il server rifiuta gli altri.
- [ ] ASS-10 [M] Permesso di 4 ore e di una giornata nel calendario. → «Permesso - 4h» e «- 8h»; uguali al saldo; 0 in giorno non lavorativo.

## Sistema di gestione: audit e certificazioni

`/sistema-gestione/` · commit 629607ad

### Cosa è stato fatto

- Menu unico al posto dei pulsanti che schiacciavano il titolo.
- Pagina iniziale «Da fare adesso» con certificati, sorveglianze, piani azioni e programma audit.
- Scheda del certificato con copia PDF e storico, qualifiche collegate, audit e scadenze. Si apre dallo Scadenzario anche in sola lettura.
- Qualifiche di Formazione collegate a certificati e auditor, in sola lettura: si rimanda alla Formazione, non si duplica.
- Risultati degli enti nel riesame (MT CN 19 §6.4 f). Report certificazioni e audit esterni.

### Cosa resta da fare

- RSGI: scegliere in Impostazioni la qualifica «auditor» e caricare i PDF.
- Inserire a mano le certificazioni, nessun seed: EN 9100/ISO 9001, 45001, PdR 125 con TÜV SÜD; 27001 con DEKRA.
- Proposti e non fatti: verbale di riesame MOD.062 con obiettivi (MT CN 19 §6.4-6.5), audit degli ambienti di lavoro (MT CN 12 §5.4), RL3 negli audit CND-PT.
- Da decidere con l'RDD: incongruenza MT CN 12 §6 / MT CN 06 Rev.21 sui requisiti degli auditor.
- Questo lavoro non è nel pacchetto delle 12:00.

### Checklist

- [ ] SGI-01 [A] Inserisci certificati: scaduto, entro 60 giorni, valido. Controlla «Da fare adesso». → Ordine per urgenza; un clic apre la voce giusta; i numeri coincidono con le tabelle.
- [ ] SGI-02 [A] Carica una copia PDF, poi una seconda. → La nuova è in vista; la precedente è nello storico, scaricabile.
- [ ] SGI-03 [A] Scarica il PDF con un utente senza permesso. → Accesso negato.
- [ ] SGI-04 [M] Collega una qualifica a un certificato; imposta la qualifica auditor. → Conteggi uguali alla Formazione; dal SGI non si modifica.
- [ ] SGI-05 [M] Apri la scheda dallo Scadenzario con un utente in sola lettura. → Si legge, nessun comando di modifica.
- [ ] SGI-06 [M] Registra un audit esterno con piano azioni; guarda il riesame. → Risultati dell'ente nel riesame; scadenza del piano in «Da fare adesso».
- [ ] SGI-07 [B] Finestra stretta e tema scuro. → Il menu non schiaccia il titolo.

## Anomalie

`/gestione-anomalie` · commit 9b191ea1, 4414a46d, 417b0ae1, 3fd402cc

### Cosa è stato fatto

- «Elimina» di una singola anomalia: solo chi l'ha inserita, solo senza avanzamenti.
- «Taglia»: sposta su altro S/N dello stesso OP o su altro OP; anche chi può modificare l'OP.
- Cambio OP / P/N dalla pagina di inserimento: chip cliccabili in alto. Nato da un errore reale del 05/11, dati inseriti sull'OP sbagliato.
- Testi incollati molto larghi non allargano più il controllo.
- Guide rapide per ruolo allineate; immagini rifatte sulla pagina attuale.

### Cosa resta da fare

- Sul database SQLite di questa prova le tabelle storiche delle anomalie sono vuote: non ho rifatto queste pagine dal vivo. Vanno provate sull'ambiente con SQL Server.
- Al deploy: collectstatic (bundle della gestione) e riavvio. Nessuna migrazione.

### Checklist

- [ ] ANO-01 [A] Elimina una tua anomalia senza avanzamenti. → Conferma; sparisce; allegati spostati in _eliminate, recuperabili dall'amministratore.
- [ ] ANO-02 [A] Elimina un'anomalia inserita da un altro. → Comando assente; la chiamata diretta è rifiutata.
- [ ] ANO-03 [A] Prova Elimina e Taglia su un'anomalia già gestita (risposta, CAR, terzista, esito). → Bloccate con il motivo.
- [ ] ANO-04 [A] Taglia su altro S/N: già esistente e nuovo. → Va nel blocco che ha quel S/N, altrimenti in un blocco nuovo.
- [ ] ANO-05 [A] Taglia su altro OP. → Passa alla NC di quell'OP e il capocommessa lo trova nel riepilogo.
- [ ] ANO-06 [A] Cambia OP con controllo in corso e un blocco non salvato. → Le anomalie salvate passano all'OP scelto; il blocco in scrittura resta.
- [ ] ANO-07 [M] Incolla un testo con righe lunghissime. → Il controllo non si allarga.
- [ ] ANO-08 [B] Guide rapide del controllore e del capocommessa. → Immagini e testi uguali alle pagine attuali, compresi i comandi nuovi.

## Manutenzione, ticket e planimetrie

`/tickets/ e /assets/` · commit af15b557, 689b3bf3

### Cosa è stato fatto

- Ticket «Per conto di» un collega, per squadra manutenzione e gestori.
- Ricerca asset elastica: «dixi 80» = «DIXI80» = «80 dixi», anche nelle tabelle.
- «Chiudi intervento» delle straordinarie essenziale: Rapporto/documento e Altri dettagli, galleria foto, «Chiudi definitivamente» in fondo.
- «Modifica» anche sugli interventi chiusi o annullati: era la causa di «Modifica sparita».
- Anteprima delle foto nel form di apertura; la bozza dei form regge i POST respinti.
- Leggi planimetria / Valida asset: sezione «Da associare a mano» e «Aggiungi un asset a mano» con un clic sulla pianta.

### Cosa resta da fare

- Da confermare con la manutenzione: codici guasto e costi non si compilano più nella chiusura straordinaria, e «Modifica» non li ha.
- La bozza non copre i modali di modifica con destinazione impostata da JS (formazione, retribuzioni, aree, mansioni, qualifiche, ruoli).
- Nessuna schermata di «Da associare a mano» in questo report: l'unica disponibile mostra la pianta vera dello stabilimento.
- Al deploy: migrazione tickets 0016, collectstatic. Test rosso: vedi D5.

### Checklist

- [ ] MAN-01 [A] Da squadra manutenzione apri un ticket «Per conto di» un collega. → Richiedente = collega; chi l'ha aperto è registrato; entrambi lo vedono; aggiornamenti al collega.
- [ ] MAN-02 [A] Da utente normale apri un nuovo ticket; ticket IT da squadra. → Il campo «Per conto di» non c'è.
- [ ] MAN-03 [M] Cerca «dixi 80», «DIXI80», «80 dixi» nel form e nelle tabelle. → Stessi risultati.
- [ ] MAN-04 [A] Chiudi una straordinaria con foto. → Galleria in chiusura e in dettaglio; chiusura solo dal pulsante in fondo.
- [ ] MAN-05 [A] «Modifica» su un intervento chiuso e uno annullato. → Il comando c'è e i valori nascosti (costi, codici) non si perdono.
- [ ] MAN-06 [A] Invia un form con errore e ricarica. → La bozza resta e l'avviso è visibile.
- [ ] MAN-07 [A] Leggi planimetria su un PDF vero: associa a mano una sigla ambigua, aggiungi un asset col clic. → Posizione corretta sulla mappa; le quote («1400mm») e i numeri di macchina del fondo non sono proposti.

## Home e Le mie attività

`/ e /mie-attivita` · commit 1eebf63a, a360b320

### Cosa è stato fatto

- «Le mie attività» ridisegnata: riepilogo cliccabile, filtri per modulo, ricerca, vista per urgenza, gruppi richiudibili, chiusura dalla riga con Annulla.
- Stesso blocco nella Home, stanza «Oggi».
- Corretto il doppio conteggio: una voce già in una sezione non si ripete in «Le mie scadenze».

### Cosa resta da fare

- Nessun punto aperto dagli appunti di sviluppo. Va provato con un utente che abbia voci vere in più moduli.

### Checklist

- [ ] HOM-01 [A] Confronta il totale «Da gestire» con la somma delle voci. → Coincidono; nessuna voce contata due volte.
- [ ] HOM-02 [A] Confronta Home e /mie-attivita. → Stessi numeri e voci.
- [ ] HOM-03 [M] Chiudi una voce dalla riga, poi Annulla; ricarica. → Annulla ripristina; dopo il ricaricamento lo stato è giusto.
- [ ] HOM-04 [B] Filtri per modulo, ricerca, «Per modulo» / «Per urgenza», gruppi richiusi. → Riepilogo e lista coerenti; moduli vuoti in una riga sola.

## Permessi e Mail inviate

`/admin-portale/ruoli-portale/ e /automazioni/mail-inviate/` · commit 50b1edf8, 5274399e

### Cosa è stato fatto

- Matrice dei ruoli: il campo «Cerca un modulo, una pagina o il suo percorso» sostituisce la ricerca della tabella. Con una «/» risolve il percorso come il controllo accessi. Filtra soltanto: il form salva anche le righe nascoste.
- Mail inviate: registrate anche le mail di send_hub_mail (scadenzario, visite, contratti, formazione, DPI, manutenzioni, ticket, riepilogo). Un errore del registro non ferma la mail.

### Cosa resta da fare

- Al deploy: collectstatic (ruoli_portale.css), riavvio, bootstrap_acl_v2 --apply per la rotta nuova.

### Checklist

- [ ] ALT-01 [A] Cerca /dpi/banco/, filtra, cambia una spunta su una riga visibile e salva. → Salva, e le righe nascoste dal filtro non perdono i permessi.
- [ ] ALT-02 [M] Cerca un percorso inesistente e il nome di un modulo. → Messaggio chiaro; senza «/» filtra in pagina.
- [ ] ALT-03 [A] Fai partire una mail da DPI, ticket e scadenzario. → Compaiono con origine, destinatari, oggetto, esito.
- [ ] ALT-04 [M] Controlla chi può aprire Mail inviate. → Solo gli amministratori: il registro contiene destinatari e oggetti.
