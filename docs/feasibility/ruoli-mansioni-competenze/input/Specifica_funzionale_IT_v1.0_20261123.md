<!-- Specifica funzionale v1.0 della Qualità, ricevuta il 23/11/2026 come documento Word. Trascrizione del testo:
     i nomi di persona sono sostituiti dalla funzione. Sostituisce la specifica v2 di questa cartella. -->

# Portale HR – Specifica funzionale per l'IT: formazione, competenze e skill matrix (v1.0)
Nov 23, 2026 · Qualità

Questa specifica unisce il flusso definito con la Qualità e la specifica v2 elaborata con Copilot; in caso di conflitto vale la decisione presa nella chat di lavoro.
### Scopo, principi e fonti
Il portale governa il percorso di ogni dipendente da anagrafica a skill matrix, tracciando chi chiede, chi approva e chi valuta ogni formazione. Questo documento è la specifica da consegnare all'IT; sostituisce la bozza v0.1.

Principi
- La competenza descrive ciò che la persona sa fare; la mansione descrive ciò che è formalmente autorizzata a svolgere. Una competenza soddisfatta non equivale a una mansione assegnata.
- Ogni formazione su una mansione parte da una richiesta approvata, così resta traccia di chi l'ha chiesta e perché.
- La skill matrix è la fotografia corrente delle mansioni assegnate; lo storico delle competenze e delle sessioni non si sovrascrive mai.
- Il responsabile di reparto fa il minimo: vede chi è in formazione, monitora, richiede e valuta.
- Il livello di mansione (M) si calcola dai livelli di competenza (C) tramite una matrice; tutto il resto è automatico attorno a quella matrice.

Fonti e precedenza
- Decisioni prese nella chat di lavoro con la Qualità (prevalgono sempre).
- Specifica funzionale v2 elaborata con Copilot: adottata dove non contraddice il punto 1 (confronto nella sezione dedicata).
- Riferimenti aziendali: MT CN 06 Rev.21, MOD.040, MOD.053, MOD.187 e catalogo MEGA MANSIONI v9.
### Oggetti, identificativi e relazioni
La nomenclatura segue la specifica v2 (SF, RAM, CRS) con una terza richiesta, RAC, proposta per la richiesta di acquisizione competenza; i nomi sono da confermare.

| Oggetto | Funzione | Identificativo | Campi principali |
| --- | --- | --- | --- |
| Dipendente | Anagrafica, inquadramento, reparto | id; matricola alla chiusura della formazione in ingresso | nome, cognome, data assunzione, inquadramento (Operatore, Impiegato Tecnico, Impiegato Amministrativo), reparto, stato |
| Cartella di formazione | Raccoglitore di tutte le formazioni del dipendente | uno per dipendente | stato, data apertura |
| Catalogo Mansioni | Mansioni da MEGA MANSIONI v9 | id | ruolo, reparto, processo, abilitazione |
| Catalogo Competenze | Competenze valutabili | Kxxx | descrizione, tipo (trasversale, tecnica, abilitazione), valutatore (reparto o Qualità) |
| Matrice C→M | Livello C richiesto per ogni livello M di ogni mansione | composta | mansione, livello M, competenza, livello C minimo |
| Catalogo Corsi | Modelli didattici riutilizzabili | CRS-NNN | titolo, programma, materiale, competenze alimentabili, durata, valutazione, periodicità |
| Richiesta Aggiornamento Mansione | Aggiunta, sospensione o rimozione di una mansione | RAM-AAAA-NNNN | persona, mansione, livello M, richiedente, motivazione, stato, approvatore |
| Richiesta Acquisizione Competenza | Richiesta di acquisire o rafforzare una competenza | RAC-AAAA-NNNN | persona o gruppo, competenza, livello C, richiedente, stato, approvatore |
| Sessione Formativa | Evento che documenta l'aggiornamento di livello C o M | SF-AAAA-NNNN | richiesta collegata, partecipanti, righe per competenza e reparto, esito, firme di chiusura |
| Riga di sessione | Una competenza, per un partecipante e un reparto | id | modalità (P, A, C), livello C, valutatore, evidenze |
| Registro affiancamento MOD.040 | Allegato alle righe in modalità A | allegato | tutor, periodo, ore, attività, livello, file |
| Assegnazione mansione | Riga della skill matrix | persona + mansione | livello M (I, U…), stato (attiva, sospesa, rimossa), data ultimo cambio |
| Approvazione periodica skill matrix | Conferma di CEO o RDD | id | data, approvatore, perimetro |
| MOD.053 dinamico | Output stampabile dello storico della persona | report, non evento | aggregazione di sessioni e competenze |
| Contatore matricola | Numerazione progressiva per prefisso | prefisso | CNO, T, A; ultimo numero assegnato |
| Log di audit | Registro append-only | id | utente, data/ora, oggetto, valore prima e dopo, motivazione, firma |

Relazioni
- Una RAM o una RAC approvata apre sempre una sessione formativa; una sessione ha una sola richiesta di origine.
- Una sessione può coinvolgere più partecipanti (per esempio un corso collettivo); le righe e le valutazioni restano per persona.
- Un corso di catalogo può alimentare più competenze ed essere richiamato da molte sessioni.
- Una competenza condivisa tra reparti ha una riga per ogni reparto, e ogni responsabile dà il suo livello.
### Attori, richieste e approvazioni
RDD approva le richieste su mansioni, MSO quelle su competenze, e nessuno approva la propria richiesta. Gli utenti esatti di ogni passo verranno definiti a flusso chiuso.

| Ruolo | Cosa fa nel flusso |
| --- | --- |
| Amministrazione | Crea l'anagrafica e imposta l'inquadramento |
| HR | Apre la cartella; in onboarding crea la richiesta con mansioni e livello M; apre e gestisce le sessioni insieme alla Qualità; gestisce il catalogo corsi |
| Responsabile di reparto (CAR) | Vede i nominativi del proprio reparto in formazione; crea richieste (aggiunta, sospensione, rimozione, competenza); valuta le competenze del proprio reparto; ha la responsabilità della valutazione |
| Qualità | Costruisce e gestisce le sessioni, raccoglie i documenti; valuta le competenze trasversali; decide quando i livelli dei reparti sono discordanti |
| MSO | Approva le richieste su competenze; può richiedere sospensione e rimozione; firma di chiusura delle sessioni su competenze; benestare del MOD.040 |
| RDD | Approva onboarding e richieste su mansioni (aggiunta, sospensione, rimozione); firma di chiusura delle sessioni su mansioni; benestare del MOD.040 |
| CEO | Approvazione periodica della skill matrix, in alternativa a RDD |
| Dipendente | Legge la propria cartella ed è informato; firma solo alla chiusura della sessione |

Chi può creare cosa

| Richiesta | Chi la crea | Chi approva |
| --- | --- | --- |
| Onboarding (mansioni e livello M) | HR | RDD |
| Aggiunta mansione o cambio livello M | Responsabile, HR, Direzione | RDD |
| Sospensione o rimozione | Responsabile o MSO | RDD |
| Acquisizione competenza | Responsabile, HR, MSO | MSO |

### I cinque flussi
Ogni flusso parte da una richiesta, passa da un'approvazione e si chiude con una sessione formativa firmata, tranne sospensione e rimozione che aggiornano la skill matrix direttamente.

Flusso 1 – Onboarding
- Amministrazione crea il dipendente con l'inquadramento; HR riceve la notifica.
- HR apre la cartella di formazione e crea la richiesta con le mansioni e il livello M da raggiungere.
- RDD approva; il sistema crea le assegnazioni in skill matrix con livello I (in formazione, non può firmare).
- Dalla matrice C→M il sistema ricava le competenze e il livello C richiesto; Qualità/HR apre la sessione con una riga per competenza e per reparto.
- Il responsabile vede il nominativo nel cruscotto, sceglie la modalità (P, A, C) e valuta.
- Alla chiusura (firma RDD e firma del dipendente) le mansioni passano ad autonomo e viene generata la matricola in base all'inquadramento: CNO per Operatore, T per Impiegato Tecnico, A per Impiegato Amministrativo, numerazione progressiva per prefisso.
- Esito negativo: la sessione si chiude come negativa con il motivo (per esempio la mancata conferma del contratto); il dipendente resta senza matricola.

Flusso 2 – Aggiornamento mansione (aggiunta)
- Il responsabile (o HR, Direzione) crea la RAM con mansione e livello M dal tasto “nuova richiesta”.
- RDD approva; il sistema apre la sessione con la griglia delle competenze e dei livelli C richiesti, precompilando come già soddisfatte quelle per cui il profilo ha un livello valido.
- Per le competenze mancanti il responsabile sceglie P, A o C e valuta; se le ha già acquisite (competenze “per osmosi”) spunta P con livello e nota.
- Chiusura con firma RDD e firma del dipendente; la skill matrix cambia il livello M. Nessun passaggio di livello avviene senza RAM approvata.

Flusso 3 – Acquisizione competenza
- Il responsabile, HR o MSO crea la RAC con competenza e livello C da raggiungere; vale anche per aggiornamenti generali (FOD, nuove procedure, corsi SGI) su più persone.
- MSO approva; Qualità e responsabile concordano la modalità P, A o C.
- Si apre la sessione; chiusura con firma MSO e firma del dipendente; il livello C si aggiorna.
- Se il nuovo livello C basta per un livello M superiore, la skill matrix segnala “idoneità potenziale” senza modificare la mansione; per ufficializzarla serve una RAM.

Flusso 4 – Sospensione e rimozione
- Il responsabile o MSO crea la RAM di tipo sospensione o rimozione, con motivazione obbligatoria.
- RDD approva; la skill matrix si aggiorna in automatico, senza sessione.
- Sospensione: la persona non opera più su quella mansione; per riattivarla si apre una RAM con sessione in cui si può selezionare P (pregresso).
- Rimozione: motivo grave (non conformità, problema); la rimozione si annulla solo con un iter formativo completo, in A o C.

Flusso 5 – Rivalutazione annuale
- Il portale genera ogni anno la scadenza per il responsabile con l'elenco dei dipendenti da rivalutare; le mansioni sospese non compaiono.
- Il responsabile conferma, oppure crea una RAM di aggiunta (competenze maturate) o di sospensione (dipendente ormai fuori reparto).
- CEO o RDD approvano periodicamente la skill matrix nel suo complesso.
### Sessione formativa: modalità P, A, C e catalogo corsi
P, A e C sono modalità di raccolta dell'evidenza, non livelli; il livello corrente deriva dall'ultima valutazione valida.

| Modalità | Registrazione minima | Evidenza | Riga positiva quando |
| --- | --- | --- | --- |
| P – Pregressa | Descrizione, verifica, data, valutatore, livello | Esperienza precedente o interna, osservazione, prova pratica, colloquio tecnico | Verifica confermata e livello sufficiente; può restare parcheggiata |
| A – Affiancamento | Tutor, periodo, attività, data, ore (somma automatica), livello e riassunto | MOD.040 stampato e caricato, allegato alla sessione | Registro caricato, livello indicato, benestare di MSO o RDD alla chiusura |
| C – Corso | ID corso (CRS), data, docente o ente, partecipanti, esito, livello | Attestato, test oppure conferma del responsabile | Una delle tre verifiche con esito positivo |

Regole
- P, A e C sono eventi multipli e storicizzati e possono coesistere sulla stessa competenza; nessuna sovrascrittura dello storico.
- Il responsabile può cambiare la modalità di una riga solo verso C (P→C, A→C): richiede conferma esplicita e scrive nel log data, firma, nota, valore prima e dopo.
- Competenze trasversali (per esempio disegno tecnico, ISO 27001): le valuta la Qualità, non il reparto.
- Competenza condivisa tra reparti: una riga per reparto e ogni responsabile dà il suo livello; se diversi, decide la Qualità.
- Una competenza soddisfatta da una sessione precedente (stesso profilo, livello valido) viene riutilizzata: la riga appare già chiusa con il riferimento alla sessione di origine e non va rivalutata.

Catalogo corsi
- Un corso non a catalogo si crea una sola volta con ID stabile (CRS-NNN), titolo, programma, materiale, competenze alimentabili, durata, valutazione e periodicità, e si associa alle competenze.
- Ogni erogazione è una sessione distinta con data, docente, partecipanti ed esito.
- L'associazione competenza→corso si completa dopo aver chiuso il catalogo delle competenze.
### Livelli C e M, matrice C→M e skill matrix
Il livello M di una mansione si calcola dai livelli C delle sue competenze secondo la matrice C→M; l'automazione dell'intero portale dipende da questa matrice.

| Livello | Cosa indica | Dove vive |
| --- | --- | --- |
| Livello C | Livello di una singola competenza | Profilo competenze della persona, aggiornato solo da una sessione chiusa |
| Livello M | Livello di una mansione: I (principiante), U… (scala di MT CN 06 §8.3, da confermare) | Skill matrix, aggiornato alla chiusura di una sessione collegata a una RAM approvata |

Regole
- La matrice C→M definisce, per ogni mansione e livello M, le competenze richieste e il livello C minimo. La regola di combinazione (minimo, soglie, media) è da definire.
- Il livello I compare in skill matrix solo per le persone con formazione aperta; significa che la persona è in quella mansione ma in formazione e non può firmare.
- La skill matrix mostra solo lo stato corrente delle mansioni assegnate (attive, sospese, rimosse), con storico dei cambi.
- Mansioni potenziali: dopo una sessione su competenze, il sistema segnala le mansioni i cui requisiti risultano soddisfatti, senza assegnarle. Per ufficializzare serve una RAM approvata.
- Il passaggio da livello I ad autonomo avviene solo alla chiusura della sessione collegata, mai con un cambio manuale isolato.
- L'idoneità a firmare non richiede altro atto oltre alla firma della richiesta, alla firma di chiusura di RDD e all'approvazione periodica della skill matrix.
- Le qualifiche obbligatorie o a scadenza (per esempio P11TF12, PART 145) restano fuori da questo flusso e richiedono le evidenze specifiche previste.
### Stati, chiusura e log di audit

| Oggetto | Stati | Note |
| --- | --- | --- |
| Richiesta (RAM, RAC) | bozza → in approvazione → approvata / respinta → evasa | Evasa alla chiusura della sessione, o subito per sospensione e rimozione |
| Sessione formativa | aperta → in corso → chiusa positiva / chiusa negativa | Negativa: il motivo è obbligatorio; per proseguire la sessione resta aperta fino all'esito positivo |
| Riga di sessione | da assegnare → in acquisizione (P parcheggiata, A in corso, C richiesta) → valutata positiva | Già chiusa se riutilizza una sessione precedente |
| Cartella di formazione | aperta → formazione in ingresso → chiusa | Si chiude con la sessione di onboarding |
| Assegnazione mansione | attiva (I, U…), sospesa, rimossa | Lo storico delle transizioni non si cancella |

Azioni alla chiusura di una sessione (in un'unica transazione)
- Verifica che ogni riga sia positiva con livello sufficiente; altrimenti blocca e indica le righe mancanti.
- Verifica la firma di chiusura: RDD per le sessioni su mansioni, MSO per quelle su competenze.
- Se c'è una riga in modalità A, verifica il benestare di MSO o RDD sul MOD.040.
- Verifica la firma del dipendente.
- Aggiorna il profilo competenze; ricalcola il livello M dalla matrice C→M e aggiorna la skill matrix solo se esiste una RAM approvata.
- In onboarding genera la matricola in base all'inquadramento, se non presente.
- Segnala le mansioni potenziali; chiude la richiesta; scrive il log con prima e dopo di ogni livello.

Log di audit

Append-only: nessun utente, nemmeno amministratore, può modificare o cancellare una riga. Ogni evento registra utente, data e ora, oggetto, valore prima e dopo, motivazione e firma.
- Creazione, approvazione e rifiuto di richieste; apertura e chiusura di sessioni.
- Cambio di modalità di una riga, con conferma esplicita.
- Valutazione di una competenza e firme di chiusura.
- Cambio di livello M, sospensione, rimozione e riattivazione.
- Modifica dell'inquadramento e generazione della matricola, che dopo la generazione non è più modificabile.
- Approvazione periodica della skill matrix.

Validazioni
- Una sola cartella per dipendente; nessuno approva la propria richiesta.
- Il pulsante di apertura di una sessione è abilitato solo a Qualità e HR su richieste approvate.
- Modalità A: ore totali uguali alla somma delle attività e registro caricato prima della valutazione.
- Modalità C: almeno una verifica tra attestato, test e conferma del responsabile.
- Il responsabile vede e modifica solo righe di dipendenti del proprio reparto.
- Sospensione e rimozione richiedono la motivazione in testo libero.
### Cruscotti e notifiche
Il responsabile deve vedere poco: chi ha in formazione, e un tasto per chiedere. Il dettaglio si apre solo cliccando sul nominativo.

| Vista | Cosa mostra |
| --- | --- |
| Responsabile di reparto | Elenco dei dipendenti del proprio reparto in formazione (tre o quattro nomi), sessioni aperte, competenze da valutare, mansioni potenziali, scadenza della rivalutazione annuale, tasto “nuova richiesta” |
| Qualità | Tutto il personale in formazione diviso per reparto; sessioni da costruire; livelli discordanti da decidere |
| HR | Stessa vista della Qualità, più richieste di onboarding e cartelle aperte |
| RDD | Richieste su mansioni da approvare; chiusure di sessione da firmare |
| MSO | Richieste su competenze da approvare; MOD.040 da benestariare |
| Profilo persona | Ruolo, reparto, mansioni, competenze e livelli, evidenze P, A, C, storico delle sessioni |
| MOD.053 dinamico | Storico aggregato e stampabile della persona, sempre aggiornato |
| Skill matrix | Solo lo stato corrente delle mansioni assegnate e il loro livello |

Notifiche
- Ogni apertura, avanzamento o chiusura di sessione avvisa il responsabile interessato, così nessun corso viene aperto senza che il caporeparto lo sappia.
- Una nuova richiesta avvisa l'approvatore (RDD o MSO) e il responsabile del reparto, se il richiedente è un altro.
- La scadenza annuale della rivalutazione avvisa il responsabile con l'elenco dei dipendenti.
- Il dipendente è informato di apertura e chiusura delle proprie sessioni.
### Confronto con la specifica v2 (Copilot)
La v2 e questa specifica coincidono sull'impianto; dove divergono vale la decisione della chat di lavoro.

| Tema | Specifica v2 (Copilot) | Decisione adottata |
| --- | --- | --- |
| Separazione competenza e mansione | Sessione formativa modifica le competenze, richiesta modifica la mansione | Adottata |
| Nomenclatura e ID | SF-AAAA-NNNN, RAM-AAAA-NNNN, CRS-NNN | Adottata; aggiunta RAC-AAAA-NNNN per la richiesta competenza |
| Catalogo corsi con competenze alimentabili | Sì | Adottato |
| MOD.053 dinamico come output | Sì | Adottato |
| P, A, C storicizzati e coesistenti | Sì | Adottato |
| Una RAM può chiudersi senza sessione se i requisiti sono già soddisfatti | Sì | Non adottata: ogni RAM approvata apre una sessione, con le competenze già soddisfatte riutilizzate e già chiuse, così la chiusura resta firmata da RDD e dal dipendente |
| Sessione senza richiesta (aggiornamento normativo, crescita professionale) | Ammessa | Non adottata: serve sempre una RAC approvata da MSO, che può coprire più persone |
| Sessione con più persone | Ammessa | Adottata, con righe e valutazioni per persona |
| Mansioni potenziali segnalate, non assegnate | Sì | Adottato |
| Onboarding, matricola, inquadramenti | Non trattati | Definiti in questa specifica |
| Sospensione e rimozione di mansione | Non trattate | Definite in questa specifica, senza sessione |
| Approvazioni (RDD, MSO, CEO) e firme | Genericamente “approvatore” | RDD su mansioni, MSO su competenze, firma del dipendente alla chiusura |
| Livello M | Non definito | Calcolato dai livelli C tramite matrice C→M |
| Esito negativo | Non trattato | Sessione chiusa come negativa con motivo tracciato |
| Cruscotto del responsabile | SF aperte, RAM da proporre, persone idonee | Più semplice: nominativi in formazione e tasto di richiesta; il resto nel dettaglio |

### Punti aperti
Sette punti restano da decidere; il primo blocca la costruzione del motore automatico.
- ☐ Matrice C→M: livello C richiesto per ogni livello M di ogni mansione e regola di combinazione (minimo, soglie, media). Il dato da cui dipende l'automazione.
- ☐ Competenze condivise e livello M: come conta nel calcolo di M una competenza con livelli diversi tra reparti, dopo la decisione della Qualità.
- ☐ Utenti di ogni passo: da definire nel dettaglio a flusso chiuso (RDD, MSO, CEO, Qualità, HR, responsabili).
- ☐ Approvazione periodica della skill matrix (CEO o RDD): frequenza e contenuto.
- ☐ Matricola: punto di partenza del contatore per ciascun prefisso.
- ☐ Nomi: conferma di “sessione formativa” (SF), “richiesta aggiornamento mansione” (RAM) e della nuova “richiesta acquisizione competenza” (RAC).
- ☐ Scala dei livelli M: conferma che I, U… coincide con MT CN 06 §8.3 e quali livelli esistono (principiante, autonomo, insegna).
