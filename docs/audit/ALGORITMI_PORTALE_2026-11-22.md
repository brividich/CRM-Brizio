# Algoritmi interni di NOVICROM HUB

Catalogo rilevato sul codice il 22/11/2026 (main `07b18cc67`). Generato da `tools/gen_algoritmi_pdf.py` a partire da `tools/algoritmi_dati.py`: non modificare a mano. Percorsi relativi a `django_app/`.

## SOC - Sicurezza informatica

### Motore delle regole

Ogni evento raccolto (antivirus, firewall, backup, vulnerabilità) viene confrontato con le regole e, se serve, diventa un avviso per l'IT.

- **Dove:** `security/services/rule_engine.py` · `evaluate_security_rules` · riga 21
- **Flusso:** Evento raccolto → Regole per quel tipo di evento → Confronto con le soglie → Avviso creato o aggiornato
- **Regole e soglie:**
  - Confronti possibili: maggiore, minore, uguale, diverso, contiene, espressione, scostamento dalla norma
  - Una vulnerabilità è critica con CVSS da 9 in su e almeno un dispositivo esposto
  - Se il dato non si riesce a leggere, l'avviso scatta comunque (meglio un avviso in più)
- **Dettaglio tecnico:** Smistamento per event_type tramite _HANDLERS; un savepoint per evento; ogni decisione scrive decision_trace; su eccezione si registra evaluation_error. _rule_matches: gt, gte, lt, lte, eq, neq, contains, regex, baseline_deviation. _evaluate_vulnerability è fail-closed.
- **Limiti noti:** L'ordine delle gravità in _rango (attenzione sotto medio) è opposto a quello delle penalità di postura.

### Un solo avviso per lo stesso problema

Lo stesso problema, anche se segnalato cento volte, resta un solo avviso aperto che si aggiorna.

- **Dove:** `security/services/rule_engine.py` · `_get_or_create_active_alert` · riga 1136
- **Flusso:** Nuovo evento → Calcolo dell'impronta → Esiste un avviso attivo? → Aggiorna quello oppure creane uno
- **Regole e soglie:**
  - L'avviso è riconosciuto da sorgente più impronta del problema
  - Vale finché l'avviso è attivo: chiuso l'avviso, un nuovo evento ne apre uno nuovo
  - Se due elaborazioni arrivano insieme, la seconda adotta l'avviso creato dalla prima
- **Dettaglio tecnico:** Indice unico parziale su (source, dedup_hash) per gli stati attivi; la creazione avviene in un savepoint e su IntegrityError si rilegge l'avviso vincente.

### Punteggio di postura dell'azienda

Un voto da 0 a 100 che riassume lo stato di sicurezza: si parte da 100 e si toglie per ogni problema aperto.

- **Dove:** `security/services/posture.py` · `ALERT_PENALTY` · riga 36
- **Flusso:** Avvisi aperti → Vulnerabilità aperte → Sorgenti mute → 100 meno le penalità → Voto e giudizio
- **Regole e soglie:**
  - Avviso critico -30, alto -15, attenzione -8, medio -5, basso -2
  - Vulnerabilità critica -25, alta -10, media -3
  - Sorgente che non manda più dati: -20
  - Giudizio a fasce: 90, 75, 50
  - Contano solo gli avvisi nuovi, aperti, presi in carico o in lavorazione: quelli rimandati o silenziati no
- **Dettaglio tecnico:** ALERT_PENALTY, FINDING_PENALTY, SILENT_SOURCE_PENALTY; _clamp porta il risultato fra 0 e 100; _grade assegna la fascia. Backup: (completati + 0,5 x avvisi) / totale sugli ultimi 7 giorni.
- **Limiti noti:** Esiste un secondo motore (postura.py, per PC) con pesi propri: i due voti non sono confrontabili.

### Punteggio di ogni PC

Ogni computer ha il suo voto da 0 a 100, per capire a colpo d'occhio quali macchine sistemare prima.

- **Dove:** `security/services/postura.py` · `punteggio` · riga 101
- **Flusso:** Dati del PC → Backup, avvisi, vulnerabilità → Supporto e aggiornamenti → Voto e colore
- **Regole e soglie:**
  - Backup fallito -25
  - Avvisi: 20 per ogni critico e 5 per gli altri, fino a -30
  - Vulnerabilità gravi: 5 l'una, fino a -25
  - Sistema operativo fuori supporto -20
  - Aggiornamenti mancanti: fino a -15
  - Colore: verde da 80, giallo da 50, rosso sotto
- **Dettaglio tecnico:** Penalità con tetto per categoria (min(30, ...), min(25, ...), min(15, ...)); protezione WatchGuard -15 / -20 / -5 secondo lo stato; tono_di restituisce la fascia 80/50.

### Tempo massimo per correggere una vulnerabilità

Ogni vulnerabilità ha una data entro cui va corretta, tanto più vicina quanto più è grave.

- **Dove:** `security/services/cve_sla.py` · `scadenza` · riga 97
- **Flusso:** Vulnerabilità rilevata → Gravità ed elenco KEV → Data limite → In tempo o fuori tempo
- **Regole e soglie:**
  - Già sfruttata da attaccanti (elenco KEV): 14 giorni
  - Critica: 15 giorni
  - Alta: 30 giorni
  - Media: 90 giorni
  - Bassa: 180 giorni
- **Dettaglio tecnico:** Termini letti dalle impostazioni SOC (soc_settings.py), modificabili da Impostazioni.

### Il sistema impara cosa è rumore

Se l'IT chiude più volte lo stesso avviso come non rilevante, il portale propone da solo di non mostrarlo più.

- **Dove:** `security/services/learned_suppression.py` · `_maybe_learn` · riga 264
- **Flusso:** Avviso chiuso come non rilevante → Conta nelle ultime 13 settimane → Terza volta? → Regola di silenzio a tempo
- **Regole e soglie:**
  - 3 chiusure dello stesso avviso in 90 giorni creano una regola di silenzio
  - La regola dura 180 giorni
  - Mai per avvisi critici, vulnerabilità già sfruttate o minacce
  - Se qualcuno riapre l'avviso a mano, la regola si spegne
- **Dettaglio tecnico:** Conteggio protetto da select_for_update; soglie in soc_settings.py; on_manual_reopen disattiva la regola.

### Ciclo di vita di un avviso

Ogni avviso segue un percorso: nuovo, preso in carico, in lavorazione, poi chiuso, risolto o falso allarme. Ogni passaggio resta scritto.

- **Dove:** `security/services/alert_lifecycle.py` · `_transition_alert` · riga 136
- **Flusso:** Nuovo → Preso in carico → In lavorazione → Chiuso / risolto / falso allarme
- **Regole e soglie:**
  - Stati attivi: nuovo, aperto, preso in carico, in lavorazione, rimandato, silenziato
  - Stati finali: chiuso, risolto, falso positivo, soppresso
  - Ogni cambio finisce nel registro dell'avviso e nell'audit sigillato del portale
  - Una sorgente è considerata muta dopo 6 ore senza dati
- **Dettaglio tecnico:** Scrive status, status_reason e date; crea SecurityAlertActionLog; chiama traccia.registra e ai_proposte.registra_decisione (errore non bloccante).
- **Limiti noti:** Nessun controllo che il passaggio sia ammesso e nessun blocco: due operatori insieme si sovrascrivono.

## Contatori stampanti (SNMP)

### Lettura automatica delle stampanti

Il portale interroga da solo stampanti e apparati di rete e ne registra contatori e stato.

- **Dove:** `contatori/tasks.py` · `run_poll_snmp` · riga 73
- **Flusso:** Ogni 5 minuti → Un lavoro per apparato → Interrogazione SNMP → Stato: OK, attenzione, errore
- **Regole e soglie:**
  - Un giro ogni 5 minuti, un lavoro separato per ogni apparato
  - Lo stesso apparato non viene interrogato due volte insieme (blocco di 240 secondi)
  - Ogni lettura ha al massimo 110 secondi, con 2 tentativi
  - Una stampante spenta viene lasciata in pace per 15 minuti
- **Dettaglio tecnico:** Lock in cache per apparato (_enqueue), timeout job 110 s; budget SNMP in snmp.py: 2 tentativi UDP, poll 80 s, walk 10 s e massimo 256 righe, scansione rete con 32 richieste in parallelo.

### Controllo di qualità della lettura

Prima di salvare un contatore il portale verifica che il dato sia credibile.

- **Dove:** `contatori/snmp.py` · `verifica_lettura_mfc` · riga 687
- **Flusso:** Lettura arrivata → Matricola giusta? → Numeri coerenti? → Non è sceso? → Salvata o scartata
- **Regole e soglie:**
  - Scartata se la matricola letta non è quella in anagrafica
  - Scartata se la somma dei contatori supera il totale pagine di oltre 50
  - Scartata se un valore è negativo o fuori scala
  - Un contatore non può scendere, salvo cali spiegati (es. scheda sostituita)
- **Dettaglio tecnico:** TOLLERANZA_PAGINE = 50; limite superiore 2^31-1. La monotonia è in contatori/services.py (verifica_progressione, controllo_monotonia).

### Confronto con la fattura del fornitore

Le copie fatturate dal fornitore vengono confrontate con quelle lette dal portale, per trovare gli scarti.

- **Dove:** `contatori/services.py` · `riconcilia` · riga 130
- **Flusso:** Fattura caricata → Macchine del contratto → Letture interne del trimestre → Scarto ed esito
- **Regole e soglie:**
  - Confronto per contratto e per tipo di copia
  - Se il fornitore conta più del portale, la riga è segnata da contestare
  - Se manca la lettura di una macchina del contratto, il confronto resta sospeso
  - Nei primi 7 giorni di un trimestre la lettura vale per il trimestre appena chiuso
- **Dettaglio tecnico:** Per fatture a totali o per formato cambiano i campi confrontati (_CONFRONTO_TOTALI / _CONFRONTO_FORMATO). Trimestre di competenza: trimestre_lettura_snmp.
- **Limiti noti:** Una query sulle letture e una sulle macchine per ogni riga di fattura.

### Previsione del toner

Dal ritmo di consumo il portale stima fra quanti giorni finirà il toner e quando ordinarlo.

- **Dove:** `contatori/services.py` · `_stima_giorni` · riga 1654
- **Flusso:** Livelli letti → Ritmo di consumo → Giorni all'esaurimento → Da ordinare?
- **Regole e soglie:**
  - Il ritmo si calcola dalle letture dopo l'ultima sostituzione
  - Sotto il 15% la cartuccia è da ordinare
  - Oltre 100 giorni senza letture la macchina è segnata da aggiornare
- **Dettaglio tecnico:** Stima lineare sui livelli percentuali; soglia d'ordine e soglia di lettura vecchia sono costanti del modulo.

## Diario del preposto

### Numero progressivo e modifiche protette

Ogni annotazione riceve un numero unico dell'anno e due persone non possono sovrascriversi a vicenda.

- **Dove:** `diario_preposto/models.py` · `next_codice_identificativo` · riga 100
- **Flusso:** Nuova annotazione → Numero successivo → Salvataggio → Modifica solo sull'ultima versione
- **Regole e soglie:**
  - Formato DP-anno-numero, un progressivo per anno
  - Se due annotazioni nascono insieme, il portale riprova fino a 5 volte
  - Chi salva una scheda che nel frattempo è stata cambiata da altri viene avvisato
  - L'eliminazione archivia con un motivo: la scheda si può ripristinare
- **Dettaglio tecnico:** Massimo + 1 con ritentativo su IntegrityError nel save. Blocco ottimistico in views.modifica: select_for_update più confronto del campo versione.

### Registrazioni in ritardo e ispezioni

Il cruscotto segnala le annotazioni scritte troppo tardi e quando è dovuta la prossima ispezione.

- **Dove:** `diario_preposto/cruscotto.py` · `_in_ritardo` · riga 83
- **Flusso:** Data del fatto → Data di inserimento → Oltre 2 giorni? → Segnalata in ritardo
- **Regole e soglie:**
  - In ritardo se scritta oltre 2 giorni dopo il fatto
  - Prossima ispezione = ultima ispezione più la frequenza stabilita
  - Andamento sugli ultimi 12 mesi
- **Dettaglio tecnico:** GIORNI_RITARDO_REGISTRAZIONE = 2; stato_ispezioni usa ispezione_frequenza_giorni.
- **Limiti noti:** Il confronto usa la data in UTC e non l'ora italiana: vicino a mezzanotte può sbagliare di un giorno.

## Segnalazioni di sicurezza

### Indici di sicurezza

Dalle segnalazioni il portale calcola gli indicatori usati per la sicurezza sul lavoro.

- **Dove:** `rilevazione_incidenti/services.py` · `get_safety_kpis` · riga 52
- **Flusso:** Segnalazioni dell'anno → Classificazione per tipo → Organico attivo → Indici e andamento
- **Regole e soglie:**
  - Indice infortuni (TRIR) = incidenti x 200.000 / ore lavorate
  - Ore lavorate stimate: persone in organico x 2.000 ore l'anno
  - Giorni trascorsi dall'ultimo infortunio
  - Conteggi dell'anno per condizione pericolosa, quasi incidente, incidente
  - Andamento sugli ultimi 12 mesi
- **Dettaglio tecnico:** active_headcount esclude chi è fuori dai conteggi dell'organico; normalize_tipo_evento riconduce i tipi a tre classi.
- **Limiti noti:** Gli incidenti da inizio anno sono divisi per le ore di un anno intero: a inizio anno l'indice è sottostimato. Se l'anagrafica non risponde l'organico vale 0 e l'indice sparisce senza avviso.

### Stato della segnalazione

Lo stato non si sceglie a mano: deriva dalle approvazioni raccolte.

- **Dove:** `rilevazione_incidenti/views.py` · `_deriva_stato` · riga 398
- **Flusso:** Aperta → Approvata dal RLS → Chiusa dal RSPP
- **Regole e soglie:**
  - Aperta finché nessuno ha approvato
  - Approvata quando il rappresentante dei lavoratori (RLS) approva
  - Chiusa quando il responsabile della sicurezza (RSPP) chiude
  - Il preposto può modificare solo finché è aperta
- **Dettaglio tecnico:** Stato calcolato dai campi Approvazione_RLS e Chiusura_RSPP, non salvato. Doppia sorgente dati: SharePoint tramite Graph oppure database locale (_use_local).
- **Limiti noti:** L'eliminazione è definitiva (nel diario preposto invece si archivia).

## Schede di sicurezza

### Lettura automatica della scheda

Caricato il PDF del fornitore, il portale ne estrae da solo le informazioni di pericolo.

- **Dove:** `schede_sicurezza/services/ingestion.py` · `estrai_sds` · riga 142
- **Flusso:** PDF caricato → Divisione in sezioni → Ricerca di pittogrammi e frasi → Scheda compilata
- **Regole e soglie:**
  - Divide il documento nelle 16 sezioni previste
  - Riconosce pittogrammi di pericolo, frasi di rischio (H, EUH) e consigli di prudenza (P)
  - Esito: completa, parziale o fallita, sempre correggibile a mano
- **Dettaglio tecnico:** _split_sections sul titolo «SEZIONE n»; espressioni regolari per GHS, H, EUH e P.
- **Limiti noti:** L'estrazione gira dentro la richiesta dell'utente: con PDF grandi la pagina resta in attesa.

### Chi deve leggere quali schede

Ogni persona vede le schede dei prodotti che usa per la sua mansione e conferma di averle lette.

- **Dove:** `schede_sicurezza/services/assegnazioni.py` · `profilo_sds_utente` · riga 115
- **Flusso:** Mansione della persona → Prodotti di quella mansione → Schede correnti → Da leggere / lette
- **Regole e soglie:**
  - Le schede dovute derivano dalle mansioni a rischio della persona
  - Una conferma per persona e per versione della scheda
  - Con una versione nuova la conferma va rifatta
  - Il report mostra la percentuale di presa visione per mansione
- **Dettaglio tecnico:** sds_da_leggere_per_dipendente calcola l'elenco; reports.matrice_presa_visione la percentuale.
- **Limiti noti:** La conferma «ho letto tutte» dal link della mail avviene con una semplice apertura di pagina (GET).

### Versione corrente e revisione

Per ogni prodotto vale una sola scheda; le vecchie restano in archivio. Le schede datate sono segnalate.

- **Dove:** `schede_sicurezza/models.py` · `SCADENZA_SDS_GIORNI` · riga 124
- **Flusso:** Nuova versione caricata → Diventa corrente → La precedente va in archivio → Dopo 3 anni: da rivedere
- **Regole e soglie:**
  - Una sola versione corrente per prodotto
  - Da rivedere dopo 1.095 giorni (circa 3 anni)
  - Il codice QR sul contenitore apre sempre la versione corrente
  - L'etichetta stampata adatta i pittogrammi fra 6 e 16 mm
- **Dettaglio tecnico:** SchedaSicurezza.save toglie is_corrente alle altre; la proprietà scaduta confronta data_caricamento.
- **Limiti noti:** I 3 anni partono dal caricamento nel portale e non dalla data di revisione del fornitore; il cambio di versione corrente non è in transazione.

## Gestione anomalie

### Tempi misurati in ore lavorate

Quanto tempo resta ferma un'anomalia si misura in ore di lavoro vere, non di calendario.

- **Dove:** `anomalie/tempi_service.py` · `ore_lavorate` · riga 80
- **Flusso:** Apertura → Solo ore 8-18 dei giorni lavorativi → Somma delle ore → Giorni lavorativi
- **Regole e soglie:**
  - Contano solo le ore fra le 8 e le 18
  - Solo dal lunedì al venerdì
  - Festivi nazionali esclusi
  - Le ore si convertono in giorni lavorativi
- **Dettaglio tecnico:** Usa core.calendario_it (festivi_tra, is_lavorativo); fascia oraria da escalation_config.

### Solleciti automatici

Se un'anomalia resta senza risposta il portale sollecita da solo chi deve decidere.

- **Dove:** `anomalie/tasks.py` · `run_anomalie_escalation` · riga 81
- **Flusso:** Controllo ogni ora → Anomalie ferme oltre soglia → Giorno e ora giusti? → Mail di sollecito
- **Regole e soglie:**
  - Sollecito dopo 24 ore senza risposta, inviato alle 6 dal lunedì al venerdì
  - Stesso codice pezzo con 3 anomalie in 30 giorni: avviso di ricorrenza
  - Richiesta di deroga senza numero da 3 giorni: avviso
  - Ordine completato da 48 ore con anomalie aperte: avviso
- **Dettaglio tecnico:** Soglie in escalation_config.py; le automazioni collegate sono in automazioni_service.py.
- **Limiti noti:** La ricerca delle ricorrenze legge tutte le anomalie della finestra, senza limite.

### Una sola mail per tante decisioni

Quando si decidono più anomalie dello stesso ordine, il portale aspetta che si finisca e manda un solo riepilogo.

- **Dove:** `anomalie/mail_action_service.py` · `flush_pending_update_notifications` · riga 866
- **Flusso:** Decisione salvata → Messa in attesa → Pausa senza nuove modifiche → Una mail di riepilogo
- **Regole e soglie:**
  - Le decisioni si accumulano per ordine di produzione
  - La mail parte dopo alcuni minuti di quiete, oppure subito con «Invia ora»
  - Se l'invio fallisce si riprova; esauriti i tentativi vengono avvisati i supervisori
- **Dettaglio tecnico:** AnomaliaPendingNotification con updates_snapshot; controllo ogni minuto; MAX_FLUSH_ATTEMPTS poi dead-letter.
- **Limiti noti:** Nessun blocco fra «Invia ora» e il controllo automatico (possibile doppia mail); l'elenco delle decisioni non viene svuotato dopo l'invio.

### Decidere dal link della mail

Il capocommessa può decidere sulle anomalie direttamente dal link ricevuto, senza entrare nel portale.

- **Dove:** `anomalie/mail_action_views.py` · `mail_action_view` · riga 43
- **Flusso:** Mail con link → Pagina delle anomalie dell'ordine → Decisione → Registro e avviso a chi ha segnalato
- **Regole e soglie:**
  - Il link vale 48 ore
  - Le azioni che cambiano lo stato si possono fare una volta sola
  - Mostra sempre le anomalie aperte dell'ordine in quel momento
  - Controllo ordine: promemoria dopo 15 minuti, invio automatico dopo 60, link valido 72 ore
- **Dettaglio tecnico:** Consumo del token con UPDATE condizionato (is_used=False, non revocato, non scaduto).
- **Limiti noti:** Il link è l'unica autorizzazione: chi lo possiede decide e carica file senza identificarsi.

## Calendari e scadenze

### Festivi e giorni lavorativi

Il portale sa quali giorni sono lavorativi: sabati, domeniche e feste nazionali sono esclusi, Pasqua compresa.

- **Dove:** `core/calendario_it.py` · `pasqua` · riga 25
- **Flusso:** Anno → Calcolo della Pasqua → Elenco dei festivi → Giorno lavorativo sì / no
- **Regole e soglie:**
  - Feste nazionali a data fissa più Pasqua e Lunedì dell'Angelo, calcolati per ogni anno
  - Santo patrono dove impostato (assenze, calendario scadenze)
  - Usato per tempi delle anomalie, durata delle assenze, pianificazione attività
- **Dettaglio tecnico:** Algoritmo gregoriano anonimo (Meeus/Jones/Butcher); festivi_nazionali, festivi_tra, is_lavorativo.
- **Limiti noti:** Lo stesso calcolo è riscritto in assenze/hr.py e scadenzario/calendario.py; carichi macchina e verifiche RENTRI contano i giorni senza togliere i festivi.

### Avvisi di scadenza

Per ogni scadenza (documenti, verifiche, rinnovi) il portale avvisa per tempo i responsabili.

- **Dove:** `scadenzario/avvisi.py` · `da_avvisare` · riga 75
- **Flusso:** Scadenza a calendario → Mancano 30 giorni? → Avviso → Ripeti ogni 7 giorni → Rinnovo
- **Regole e soglie:**
  - Primo avviso 30 giorni prima
  - Ripetuto ogni 7 giorni finché non è gestita
  - Riepilogo con le scadenze dei prossimi 60 giorni
  - Al rinnovo la scadenza successiva si calcola dalla validità in mesi
- **Dettaglio tecnico:** Costanti di preavviso, ripetizione e riepilogo in testa al modulo; scatta_foto salva la fotografia giornaliera per la vista andamento.
- **Limiti noti:** L'ultimo avviso riuscito è cercato con una query per ogni scadenza.

### Scadenze nel calendario di Outlook

Le scadenze personali compaiono anche nel calendario Outlook di ciascuno, tenute allineate dal portale.

- **Dove:** `dashboard/scadenze_calendario.py` · `sincronizza_utente` · riga 168
- **Flusso:** Scadenze della persona → Confronto con Outlook → Crea, aggiorna o togli → Impronta salvata
- **Regole e soglie:**
  - Orizzonte di 90 giorni
  - Un evento cancellato dall'utente non viene ricreato
  - Se Outlook restituisce un elenco incompleto, il portale non cancella nulla
  - Allineamento ogni mattina alle 6:30, cominciando da chi è aggiornato da più tempo
- **Dettaglio tecnico:** Impronta del contenuto per evitare scritture inutili; transactionId idempotente verso Graph; sincronizza_tutti ha un budget di 90 secondi.

### Ricorrenza delle manutenzioni

Dopo ogni intervento il portale calcola da solo la data del successivo.

- **Dove:** `assets/services/recurrence.py` · `add_recurrence` · riga 158
- **Flusso:** Intervento chiuso → Regola di ricorrenza → Data successiva → Nuova scadenza a calendario
- **Regole e soglie:**
  - Due modi: dalla data in cui il lavoro è stato fatto, oppure a calendario fisso
  - Se manca il dato di un modo si usa l'altro
  - Le scadenze vengono create solo entro la finestra di preavviso del piano
- **Dettaglio tecnico:** Limite di sicurezza di 2.000 iterazioni nel calcolo delle date successive.

## Permessi e servizi comuni

### Chi può fare cosa

A ogni clic il portale decide se la persona può aprire quella pagina o fare quell'azione.

- **Dove:** `core/acl_resolver.py` · `resolve_permission_decision` · riga 181
- **Flusso:** Richiesta → Eccezione personale? → Gruppo? → Ruolo? → Sì oppure no
- **Regole e soglie:**
  - 1. Amministratore di sistema: sempre sì
  - 2. Eccezione assegnata alla singola persona
  - 3. Gruppo con priorità più alta
  - 4. Permesso del ruolo
  - 5. Se nessuna regola concede, la risposta è no
  - La voce nel menu non conta: decide sempre il server
- **Dettaglio tecnico:** Ordine: superuser, admin legacy, override utente, gruppo a priorità più alta, sistema ruoli attivo = nega, permesso del ruolo, compatibilità legacy. Il middleware (core/middleware.py, ACLMiddleware) usa il legame canonico pagina-permesso e, se manca, il vecchio sistema a pulsanti.
- **Limiti noti:** Il blocco del vecchio sistema (ACL_STRICT_CANONICAL) è spento per impostazione predefinita.

### Propri, del team, di tutti

Oltre al sì o no, i permessi dicono su quali dati: solo i propri, quelli della propria squadra, o tutti.

- **Dove:** `core/permessi/motore.py` · `puo_fare` · riga 402
- **Flusso:** Azione richiesta → Ambito del permesso → Di chi è il dato? → Consentito o negato
- **Regole e soglie:**
  - Tre ambiti: propri, team, tutti
  - La squadra si ricava dall'organigramma, scendendo dai riporti diretti
  - Capo effettivo: prima la persona indicata, poi area, reparto, organigramma
- **Dettaglio tecnico:** Team calcolato in core/permessi/team.py; capo effettivo in anagrafica/services/capo_team.py con cache di 120 secondi.

### Numeri progressivi senza doppioni

Ticket, richieste DPI, registri e annotazioni ricevono un numero unico anche se nascono nello stesso istante.

- **Dove:** `core/numbering_retry.py`
- **Flusso:** Nuova registrazione → Numero successivo → Già usato? → Riprova oppure salva
- **Regole e soglie:**
  - Formato sigla-anno-numero
  - Se due registrazioni prendono lo stesso numero, la seconda riprova
  - Fino a 5 tentativi
  - RENTRI usa un contatore per anno con blocco sulla riga
- **Dettaglio tecnico:** Ritentativo su errore di unicità; rentri/numerazione.py usa select_for_update su un contatore per anno.
- **Limiti noti:** Alcuni numeratori non lo usano (numero audit, utensili MPQ); DPI e ticket ordinano il numero come testo.

### Registro delle azioni sigillato

Le azioni importanti restano in un registro che ogni mese viene sigillato, così una modifica successiva si vede.

- **Dove:** `core/audit_sigilli.py`
- **Flusso:** Azioni del mese → Impronta del mese → Unita al sigillo precedente → Nuovo sigillo
- **Regole e soglie:**
  - Ogni mese un sigillo calcolato sul contenuto del mese
  - Ogni sigillo contiene anche quello del mese precedente: è una catena
  - Cambiare un dato passato rompe tutti i sigilli successivi
- **Dettaglio tecnico:** Catena di hash SHA-256 fra i mesi.

### Promemoria e report pianificati

Il portale ricorda le scadenze con una cadenza fissa e spedisce i report periodici senza intervento.

- **Dove:** `core/report_centro/pianificazione.py` · `esegui_scadute` · riga 298
- **Flusso:** Ogni ora → Report arrivati a scadenza → Generazione e invio → Prossima data
- **Regole e soglie:**
  - Promemoria a 30, 14, 7, 1 e 0 giorni, poi ogni 7 giorni dopo la scadenza
  - Ognuno può scegliere quali notifiche ricevere
  - Report mensili: giorno del mese fino al 28
  - Allegato fino a 10 MB
- **Dettaglio tecnico:** calcola_prossima decide la data successiva; cadenza dei promemoria in core/notifiche.py.
- **Limiti noti:** La prossima data è salvata solo dopo l'invio e senza blocco: un errore a metà o due processi insieme possono rispedire lo stesso report.

## Automazioni

### La coda degli eventi

Ogni fatto registrato nel portale entra in una coda; un motore la svuota e fa partire mail e azioni.

- **Dove:** `automazioni/services.py` · `find_matching_rules` · riga 3568
- **Flusso:** Fatto registrato → Evento in coda → Regole che corrispondono → Azioni: mail, notifica, attesa
- **Regole e soglie:**
  - Ogni evento è preso da un solo elaboratore alla volta
  - Se un'azione fallisce si riprova fino a 5 volte
  - Un evento fermo da oltre 15 minuti viene rimesso in coda
  - Ogni giro lavora al massimo 90 secondi
- **Dettaglio tecnico:** Prelievo con READPAST, UPDLOCK, ROWLOCK e rispetto di execute_after; il retry salta le azioni già riuscite per lo stesso evento; chiamate HTTP con timeout massimo di 30 secondi.
- **Limiti noti:** Tutto il motore è in un unico file di oltre 6.000 righe.

### Quando scatta una regola

Una regola parte per un inserimento, una modifica, o il cambio di un campo preciso, e può aspettare prima di agire.

- **Dove:** `automazioni/services.py` · `render_template_string` · riga 1585
- **Flusso:** Evento → L'innesco corrisponde? → In pausa? → Attesa → Esecuzione
- **Regole e soglie:**
  - Inneschi: ogni inserimento, ogni modifica, qualsiasi cambio, un campo specifico
  - Attesa in minuti, ore o giorni, oppure fino a una data
  - Pausa fra due esecuzioni della stessa regola per non ripetere le mail
- **Dettaglio tecnico:** render_template_string sostituisce i segnaposto del modello con i valori dell'evento.
- **Limiti noti:** I valori inseriti nel corpo HTML della mail non vengono resi innocui (vedi rapporto di audit); una pausa scritta male lascia passare la regola.

## Manutenzione e asset

### Scadenze di manutenzione

Dai piani di manutenzione il portale genera da solo le scadenze di ogni macchina.

- **Dove:** `assets/services/maintenance_domain.py`
- **Flusso:** Piano → Macchine coinvolte → Date dovute → Scadenze create una volta sola
- **Regole e soglie:**
  - Vale il piano più specifico: della macchina, poi del gruppo, poi della categoria
  - Una sola scadenza per piano, macchina e data: rigenerare non crea doppioni
  - Verifiche periodiche: in scadenza oppure scaduta
- **Dettaglio tecnico:** Vincolo unico su piano, asset e scadenza; finestra pari a warning_days.

### Consumi e indicatori di manutenzione

Ore macchina, tempi di riparazione e rispetto dei piani diventano indicatori.

- **Dove:** `assets/services/meters.py`
- **Flusso:** Letture e interventi → Ultimi 30 giorni → Medie → Indicatori in cruscotto
- **Regole e soglie:**
  - Consumo medio giornaliero sugli ultimi 30 giorni, ripartendo dall'ultimo azzeramento
  - Tempo medio di riparazione sugli ultimi 30 giorni
  - Rispetto dei piani: scadenze in regola sul totale
- **Dettaglio tecnico:** MTTR in dashboard_kpi.py; conformità in maintenance_kpi.py.

## Persone: assenze, anagrafica, DPI

### Assenze: durata, residui, copertura

Per ogni richiesta il portale calcola quante ore vale, quanto residuo resta e se il reparto resta coperto.

- **Dove:** `assenze/hr.py` · `giorni_lavorativi` · riga 108
- **Flusso:** Richiesta → Ore di assenza → Residuo sufficiente? → Reparto coperto? → Al capo per l'approvazione
- **Regole e soglie:**
  - Giornata intera = giorni lavorativi per le ore della giornata
  - Permesso a ore: le ore chieste, al massimo una giornata
  - Residuo = saldo del cedolino meno le richieste già fatte
  - Avviso se gli assenti superano il massimo ammesso per il reparto
- **Dettaglio tecnico:** Orizzonte dei residui 730 giorni; soglia in SogliaCopertura.max_assenti; solleciti ripetuti secondo sollecito_ripeti_giorni.
- **Limiti noti:** La riconciliazione con le presenze abbina per nome e non per identificativo.

### Formazione e competenze

Il portale segnala la formazione in scadenza e misura le competenze di persone e squadre.

- **Dove:** `anagrafica/services/training_deadline_service.py`
- **Flusso:** Corsi e livelli → Scadenze → Confronto con il livello atteso → Mancanze da colmare
- **Regole e soglie:**
  - Formazione: avviso a 90 e a 30 giorni dalla scadenza
  - Competenza valida dal livello 2 in su
  - I pesi delle mansioni sommano esattamente a 1
- **Dettaglio tecnico:** Qualifica in skillmatrix_qualifica.py; prontezza della squadra in skillmatrix_resolver.py.

### Chi approva una richiesta di DPI

La richiesta di dispositivi di protezione arriva da sola a chi può approvarla.

- **Dove:** `dpi/flusso.py` · `approvatori_di` · riga 99
- **Flusso:** Richiesta → Ricerca degli approvatori → Escluso il richiedente → Mail di approvazione
- **Regole e soglie:**
  - Approvano: il capo o i co-capi, i responsabili di area e reparto, i preposti dell'area
  - Nessuno approva la propria richiesta
  - Dotazione in scadenza: avviso a 30 giorni
- **Dettaglio tecnico:** Numero DPI-anno-numero con ritentativo.
- **Limiti noti:** Se la ricerca fallisce in parte, l'elenco degli approvatori resta incompleto con un solo avviso nei log.

## Operatività: ticket, KICK-OFF, RENTRI, produzione

### Ticket: tempi di risposta

Ogni ticket ha un tempo massimo che dipende dalla categoria; quelli urgenti non assegnati vengono segnalati.

- **Dove:** `tickets/tasks.py`
- **Flusso:** Ticket aperto → Tempo della categoria → Urgente e non assegnato? → Segnalazione
- **Regole e soglie:**
  - Tempo massimo in ore, stabilito dalla categoria
  - Urgente, aperto e non assegnato da oltre 4 ore: segnalazione ai responsabili
  - Mail solo dal lunedì al venerdì, alle 8
- **Dettaglio tecnico:** Soglia in escalation_config.py (da 1 a 168 ore).
- **Limiti noti:** Il tempo è contato a orologio continuo, notti e festivi compresi.

### KICK-OFF: rischio della commessa

Prima di partire, ogni commessa riceve un punteggio di rischio che decide quanto approfondire.

- **Dove:** `tasks/vrf_catalog.py`
- **Flusso:** Voci di rischio → Probabilità per danno → Somma → Basso, medio o alto
- **Regole e soglie:**
  - Rischio di ogni voce = probabilità per danno
  - Totale fino a 35: rischio basso
  - Totale da 50: rischio alto, serve la Direzione
  - Prontezza: 4 criteri; con 4 è pronta, con almeno 2 quasi pronta
- **Dettaglio tecnico:** Prontezza in tasks/readiness.py.
- **Limiti noti:** La documentazione tecnica riporta soglie diverse da quelle del codice.

### RENTRI: registro rifiuti

Il registro di carico e scarico è numerato e controllato sui termini di legge.

- **Dove:** `rentri/numerazione.py`
- **Flusso:** Movimento → Numero di registro → Controllo dei termini → Avvisi
- **Regole e soglie:**
  - Un progressivo per anno, senza buchi né doppioni
  - Annotazione entro 10 giorni lavorativi
  - Quarta copia del formulario entro 90 giorni
  - Deposito temporaneo: attenzione a 75 giorni, limite a 90
  - Promemoria di scarico a 60 giorni, poi ogni 7
- **Dettaglio tecnico:** Contatore per anno con select_for_update; controlli in rentri/verifica.py; giacenze in giacenze.py.
- **Limiti noti:** I 10 giorni lavorativi escludono sabato e domenica ma non i festivi.

### Chi è presente in azienda

Dalle timbrature il portale ricava chi è dentro in questo momento e segnala le giornate irregolari.

- **Dove:** `presenti/solari.py` · `analizza_giornata` · riga 250
- **Flusso:** Timbrature del giorno → Ultima timbratura → Entrata? → Presente / assente / da verificare
- **Regole e soglie:**
  - Presente se l'ultima timbratura è un'entrata
  - Turno di notte: si considera dalle 18, per al massimo 16 ore
  - Segnala uscita mancante, verso sbagliato, sequenza irregolare
- **Dettaglio tecnico:** Connessione 10 secondi, query 15 secondi, risultato in cache per 60 secondi.

### Carico delle macchine

Il portale confronta le ore pianificate con la capacità di ogni macchina e prevede i ritardi.

- **Dove:** `gestione_carichi_macchina/saturazione.py` · `calcola_saturazione` · riga 19
- **Flusso:** Ordini pianificati → Ore previste → Capacità della macchina → Saturazione e rischio ritardo
- **Regole e soglie:**
  - Capacità = ore al giorno per giorni lavorativi per turni
  - Ore previste: dal tempo ciclo, poi dallo storico della macchina, poi della famiglia di pezzi
  - I dati recenti pesano di più: il peso si dimezza ogni 180 giorni
- **Dettaglio tecnico:** Previsioni in previsioni.py.
- **Limiti noti:** I giorni lavorativi non tolgono i festivi: nelle settimane con festa la capacità è sovrastimata.

## Sistema di gestione e assistente AI

### Rischio dei processi

Per ogni rischio del sistema di gestione il portale calcola quanto ne resta dopo le misure adottate.

- **Dove:** `sistema_gestione/services/rischio.py`
- **Flusso:** Rischio iniziale → Vulnerabilità residua → Calcolo → Fascia di rischio
- **Regole e soglie:**
  - Rischio residuo = rischio iniziale per vulnerabilità, diviso 4
  - Fasce a 10, 20, 30 e 40
- **Dettaglio tecnico:** Arrotondamento all'intero.

### Presa visione dei documenti

Quando una procedura cambia, chi deve leggerla riceve l'incarico e i promemoria fino alla conferma.

- **Dove:** `procedure_refresh/tasks.py`
- **Flusso:** Documento aggiornato → Incarichi di lettura → Promemoria → Conferma di lettura
- **Regole e soglie:**
  - Promemoria 7 e 2 giorni prima della scadenza
  - Dopo la scadenza, ogni 7 giorni
  - Una mail sola per persona con tutti i documenti
- **Dettaglio tecnico:** Soglie in reminder_config.py.
- **Limiti noti:** Il promemoria parte solo il giorno esatto: se quel giorno il controllo non gira, è perso.

### Come l'assistente AI trova i documenti

Alla domanda di un utente l'assistente cerca i passaggi più pertinenti nei documenti aziendali, in due modi insieme.

- **Dove:** `ai_assistant/services.py`
- **Flusso:** Domanda → Ricerca per parole → Ricerca per significato → Fusione delle classifiche → Risposta con le fonti
- **Regole e soglie:**
  - Ricerca per parole, con più peso se la parola è nel titolo
  - Ricerca per significato
  - Le due classifiche vengono fuse in una
  - Al massimo 3 domande elaborate insieme
- **Dettaglio tecnico:** BM25 con k1 = 1,5 e b = 0,75, +2,5 sul titolo; fusione RRF con k = 60.
- **Limiti noti:** Il limite di 3 vale per singolo processo del server, non in totale.
