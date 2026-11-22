# Proposte di miglioramento — 22/11/2026

Elenco numerato da cui scegliere cosa implementare. Le sigle fra parentesi rimandano a [AUDIT_PORTALE_2026-11-22.md](AUDIT_PORTALE_2026-11-22.md). **Sforzo:** S = fino a mezza giornata, M = uno o due giorni, L = più giorni. **Mig.** = serve una migrazione del database.

## Priorità 1 — correzioni di difetti certi

| N. | Modulo | Proposta | Beneficio | Sforzo | Mig. |
|---|---|---|---|---|---|
| 1 | Anomalie | Link mail: salvare solo l'impronta del segreto, controllare scadenza e revoca anche sul riepilogo, correggere la descrizione del modello (S1) | Una copia del database non dà più link utilizzabili | M | Sì |
| 2 | Anomalie | Link mail: chiedere l'accesso al portale quando il destinatario ha un account, lasciando il link libero solo per chi non lo ha (S1) | La decisione è attribuita a una persona identificata | M | No |
| 3 | Anomalie | Riepilogo decisioni: blocco sulla riga durante l'invio, svuotare l'elenco dopo l'invio, non perdere la decisione arrivata durante l'invio (A1, A2, A3) | Niente doppie mail né decisioni ripetute | M | No |
| 4 | Segnalazioni | Indice infortuni sulle ore effettivamente trascorse nell'anno; avviso visibile se l'organico non è disponibile (G1, G2) | Indicatore corretto in ogni mese | S | No |
| 5 | Segnalazioni | Eliminazione come archiviazione con motivo e «Ripristina», come nel diario del preposto (G3) | Nessuna segnalazione persa, tracciabilità | M | Sì |
| 6 | SOC | Elenco dei passaggi di stato ammessi e blocco sulla riga nel cambio stato (C1) | Due operatori non si sovrascrivono | M | No |
| 7 | SOC | Una sola scala di gravità usata da ordinamento e postura (C2) | Stessa priorità in ogni pagina | S | No |
| 8 | Schede di sicurezza | «Da rivedere» dalla data di revisione del fornitore, con la data di caricamento come ripiego (H1) | Le schede vecchie emergono davvero | S | No |
| 9 | Schede di sicurezza | «Ho letto tutte» dalla mail: pagina di conferma con pulsante (S6) | La presa visione è un atto volontario | S | No |
| 10 | Calendari | Un solo calcolo dei festivi (`core/calendario_it`) per assenze, scadenze, RENTRI e carichi macchina, con santo patrono impostabile una volta (K1, K2, K3) | Stessi giorni lavorativi ovunque; termine RENTRI corretto | M | No |
| 11 | Core | Reindirizzamenti: usare l'helper già esistente nei due punti scoperti (S2) | Chiusa una via di phishing | S | No |
| 12 | Admin | Download del pacchetto: accettare solo file dentro la cartella dei pacchetti (S3) | Nessun percorso libero | S | No |
| 13 | Automazioni | Neutralizzare i valori inseriti nel corpo HTML delle mail (S4) | Mail non alterabili da testo libero | M | No |
| 14 | Specifiche | Controllo del permesso dentro ogni vista di amministrazione, legame per «Sincronizzazione», validazione del file del timbro (S5) | Protezione che non dipende da una sola riga di configurazione | S | No |
| 15 | Report | Report pianificati: far avanzare la data prima dell'invio e bloccare la riga (R1) | Nessun report rispedito | S | No |
| 16 | Procedure | Promemoria di presa visione: «entro la soglia e non ancora inviato» invece di «giorno esatto» (R2) | Promemoria recuperati dopo un fermo | S | No |
| 17 | Diario preposto | «In ritardo» con l'ora italiana (D1) | Conteggio corretto a cavallo di mezzanotte | S | No |
| 18 | Schede di sicurezza | Cambio di versione corrente in transazione con vincolo unico (H2) | Mai due versioni correnti | S | Sì |

## Priorità 2 — miglioramenti dei sette moduli indicati

### SOC
| N. | Proposta | Beneficio | Sforzo | Mig. |
|---|---|---|---|---|
| 19 | Un solo motore di postura con pesi in Impostazioni, usato per azienda e per PC (C3) | Voti confrontabili, una sola regola da mantenere | L | No |
| 20 | Spiegazione del voto: per ogni punto perso, la causa e il link all'avviso | Il voto diventa una lista di cose da fare | M | No |
| 21 | Andamento del voto nel tempo con le cause dei cali | Si vede se la sicurezza migliora | M | Sì |
| 22 | Test automatico che ogni pagina SOC rifiuti chi non ha il permesso (S8) | Nessuna pagina scoperta per dimenticanza | S | No |
| 23 | Regole di soppressione lette una volta per giro e valutazione a blocchi | Ciclo più veloce con molti eventi | S | No |
| 24 | Avviso quando una vulnerabilità sta per superare il tempo massimo (a 3 giorni dal termine) | Si interviene prima dello sforamento | S | No |

### Contatori SNMP
| N. | Proposta | Beneficio | Sforzo | Mig. |
|---|---|---|---|---|
| 25 | Riconciliazione con letture e macchine caricate in blocco (N1) | Pagina veloce anche con molti contratti | S | No |
| 26 | Letture scartate visibili in una pagina «Da verificare» con il motivo | Si capisce perché manca un dato | M | No |
| 27 | Previsione toner con margine (data più vicina e più lontana) e ordine suggerito per tempo di consegna | Meno cartucce finite, meno scorte inutili | M | No |
| 28 | Avviso di consumo anomalo: copie molto sopra la media della macchina | Guasti e usi impropri emergono subito | M | No |

### Diario del preposto
| N. | Proposta | Beneficio | Sforzo | Mig. |
|---|---|---|---|---|
| 29 | Promemoria al preposto quando l'ispezione è dovuta e non registrata | Ispezioni fatte nei tempi | S | No |
| 30 | Collegamento annotazione → segnalazione di sicurezza con un pulsante | Niente doppia scrittura | M | Sì |
| 31 | Riepilogo settimanale al responsabile della sicurezza: ritardi, ispezioni saltate, temi ricorrenti | Vista d'insieme senza aprire il portale | M | No |

### Segnalazioni di sicurezza
| N. | Proposta | Beneficio | Sforzo | Mig. |
|---|---|---|---|---|
| 32 | Stato salvato con data e autore di ogni passaggio (oggi è derivato) | Tempi di chiusura misurabili | M | Sì |
| 33 | Sollecito a RLS e RSPP sulle segnalazioni ferme oltre una soglia | Nessuna segnalazione dimenticata | S | No |
| 34 | Azioni correttive con responsabile e scadenza, visibili in «Le mie attività» | La segnalazione porta a un'azione verificata | L | Sì |
| 35 | Indici completi: frequenza e gravità oltre al TRIR, con ore lavorate reali dalle presenze | Indicatori confrontabili con quelli di legge | M | No |

### Schede di sicurezza
| N. | Proposta | Beneficio | Sforzo | Mig. |
|---|---|---|---|---|
| 36 | Estrazione del PDF in background con avviso a fine lavoro | Nessuna attesa al caricamento | M | No |
| 37 | Avviso al responsabile 60 giorni prima che una scheda diventi «da rivedere» | Richiesta al fornitore per tempo | S | No |
| 38 | Confronto fra versione nuova e precedente: pittogrammi e frasi cambiati | Si vede subito cosa è cambiato | M | No |
| 39 | Report di presa visione con una sola lettura per tutte le mansioni | Report veloce | S | No |

### Gestione anomalie
| N. | Proposta | Beneficio | Sforzo | Mig. |
|---|---|---|---|---|
| 40 | Elenco unico degli stati con i passaggi ammessi (A4) | Niente stati scritti in modi diversi | M | Sì |
| 41 | Ricorrenze: ricerca limitata e con indice, più una vista «Pezzi ricorrenti» | Controllo veloce, problemi ripetuti in evidenza | M | No |
| 42 | Tempi per fase (segnalazione, decisione, chiusura) in ore lavorate, per reparto e capocommessa | Si vede dove si perde tempo | M | No |
| 43 | Riduzione delle eccezioni inghiottite: almeno una riga di log per ciascuna | Gli errori nascosti diventano visibili | M | No |

### Calendari
| N. | Proposta | Beneficio | Sforzo | Mig. |
|---|---|---|---|---|
| 44 | Chiusure aziendali (ferie collettive, ponti) impostabili una volta e rispettate da tutti i calendari | Scadenze e capacità realistiche | M | Sì |
| 45 | Avvisi di scadenza con ultimo invio letto in blocco | Controllo più veloce | S | No |
| 46 | Una vista unica «Calendario» che somma scadenze, assenze della squadra, manutenzioni e attività, con filtri | Un solo posto dove guardare | L | No |
| 47 | Outlook: stato dell'allineamento visibile all'utente (ultimo aggiornamento, eventuale errore) | Si capisce perché un evento manca | S | No |

## Priorità 3 — altri moduli

| N. | Modulo | Proposta | Beneficio | Sforzo | Mig. |
|---|---|---|---|---|---|
| 48 | Permessi | Blocco del vecchio sistema acceso per default in produzione, dopo verifica delle pagine senza legame (S7) | Nessuna pagina decisa dal vecchio sistema | M | No |
| 49 | Ticket | Tempo di risposta in ore lavorate; promemoria SLA con memoria degli invii | Tempi realistici, niente mail ripetute | M | Sì |
| 50 | Core | Numeratore sicuro anche per numero audit e utensili; ordinamento numerico per DPI e ticket | Niente doppioni né ordine sbagliato oltre 9.999 | S | No |
| 51 | Assenze | Riconciliazione con le presenze per identificativo e non per nome | Niente scambi fra omonimi | M | No |
| 52 | DPI | Se la ricerca degli approvatori è incompleta, avviso al gestore invece del solo log | Nessuna richiesta senza approvatore | S | No |
| 53 | Automazioni | Divisione del motore in moduli (coda, regole, azioni, mail) senza cambiare comportamento (R3) | Modifiche più sicure e meno conflitti | L | No |
| 54 | Automazioni | Pausa scritta male: regola fermata e segnalata invece che lasciata passare | Niente mail a raffica per un errore di configurazione | S | No |
| 55 | Assistente AI | Limite di richieste contemporanee valido per tutto il server; un solo default per ogni impostazione | Carico prevedibile | M | No |
| 56 | Caricamenti | Tutti i caricamenti dal validatore centrale, con test che lo pretende | Un solo punto di controllo dei file | M | No |
| 57 | Documentazione | Allineare `docs/ai/02_ARCHITECTURE.md` e `03_BACKEND_MODULES.md` al codice (S11) | Documenti affidabili | S | No |
| 58 | Sicurezza | CSP con nonce al posto di `'unsafe-inline'` (aperta da ottobre) | Protezione reale contro script iniettati | L | No |

## Come procedere

Indica i numeri. Consiglio di partire dal blocco 1-18: sono correzioni di difetti certi, quasi tutte piccole e senza cambi visibili per gli utenti, tranne 2, 5 e 9 che cambiano un passaggio per chi usa il portale. Le voci marcate «Pista» nel rapporto vanno prima confermate sul codice.
