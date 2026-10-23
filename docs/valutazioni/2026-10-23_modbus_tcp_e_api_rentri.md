# Valutazione: Modbus TCP e API RENTRI (23/10/2026)

Due integrazioni chieste «da valutare» dopo la scelta dei nuovi connettori (MTConnect, Veeam REST, DHCP/DNS: fatti). Qui cosa darebbero al portale, cosa serve, i rischi e la proposta. Nessun codice scritto.

## 1. Modbus TCP (energia, compressori, impianti)

### Cosa darebbe

| Apparato tipico | Dato | Dove finisce nel portale |
|---|---|---|
| Compressori (controllori con Modbus TCP o gateway) | ore di marcia e a carico, pressione, allarmi | contatori Ore dei piani di manutenzione (come MTConnect), allarme sulla mappa officina |
| Multimetri di energia nei quadri | kWh, potenza, cos φ per quadro o macchina | consumi per reparto o macchina, costo energia per centro di costo |
| Gruppi frigo, centrali termiche, aspirazioni | stato, ore, allarmi | manutenzione a contatore, stato sulla mappa |

### Come si farebbe

- Stesso schema di MTConnect: il **portale legge** a intervalli (5-15 minuti per l'energia, 2 per gli allarmi), nessuna superficie in ingresso.
- **Solo letture**: codici funzione 03/04 (holding/input register). Le scritture (05, 06, 15, 16) non esisterebbero nel codice: Modbus non ha autenticazione, quindi la protezione sta nel non saper scrivere.
- **Profili di registri** per modello (indirizzo, tipo, scala, unità), come i preset SNMP di Contatori IT: il lavoro vero è qui, un profilo per ogni modello di apparato.
- Collocazione naturale: modulo **Contatori IT** (ha già wizard «Nuovo apparato», preset e monitor) per gli impianti; i contatori ore vanno sugli asset come per MTConnect.
- Libreria: la lettura Modbus TCP è semplice (socket + 12 byte di richiesta); si può evitare una dipendenza nuova o usare `pymodbus` in sola lettura.

### Rischi e prerequisiti

- **Rete OT**: gli apparati stanno di solito su una rete di officina separata. Serve un solo flusso consentito, server del portale → apparato o gateway, porta 502, da decidere con chi gestisce firewall e segmentazione (NIS2: la segmentazione non va indebolita).
- **Documentazione dei registri**: senza la mappa dei registri del produttore non si legge niente di affidabile.
- **Volume dati**: l'energia ogni 15 minuti fa circa 35.000 righe l'anno per misuratore: serve una tabella a serie temporale con aggregati giornalieri e retention.

### Proposta

**Da fare, a una condizione**: ci sono almeno compressori o misuratori con Modbus TCP raggiungibili con un flusso dedicato. Ordine consigliato:

1. **Compressori**: ore → contatori di manutenzione e allarmi → mappa. Riusa la logica dei contatori «per differenza, una volta all'ora» di MTConnect. Sforzo: medio, una sessione per il motore e una per profilo.
2. **Energia**: consumi per reparto e macchina, poi il costo. Sforzo: medio-alto, per la serie temporale e i report.

**Serve dall'azienda**: l'elenco degli apparati con marca e modello, se parlano Modbus TCP o solo RTU (seriale, quindi con gateway), la mappa dei registri e il via libera al flusso di rete.

## 2. API RENTRI (interoperabilità)

### Situazione oggi

Il modulo `rentri` tiene il **registro di carico e scarico** del portale (movimenti C/O/M/R, codici EER, caratteristiche HP, formulari, giacenze, scadenzario). I dati sul RENTRI nazionale vanno messi a parte: o li reinserisce qualcuno sul portale RENTRI, o li trasmette un altro gestionale o un consulente.

### Cosa offre il RENTRI

Il RENTRI espone API REST per i gestionali, con un ambiente **demo** per le prove, autenticate con un **certificato rilasciato dal RENTRI all'operatore** (dall'area riservata), che firma le richieste. I servizi principali:

- **registri**: vidimazione digitale del registro e trasmissione dei movimenti di carico e scarico, con esito asincrono (si invia, poi si legge l'esito della transazione);
- **formulari (FIR digitale)**: emissione e gestione del formulario digitale, con i ruoli di produttore, trasportatore e destinatario;
- **codifiche**: tabelle ufficiali (EER, caratteristiche di pericolo, operazioni R/D, unità di misura).

Tempi e scaglioni degli obblighi (registro digitale, FIR digitale) dipendono dalla categoria e dal numero di dipendenti: **vanno verificati sul sito del RENTRI** prima di decidere le priorità.

### Opzioni

| Opzione | Cosa fa | Valore | Sforzo |
|---|---|---|---|
| A. Trasmissione dei movimenti | ogni movimento registrato nel portale parte verso il RENTRI, lo stato (inviato, accettato, scartato con motivo) si vede sul movimento | toglie il doppio inserimento, che è il valore principale | medio-alto: client con firma, mappatura dei campi, coda ed esiti, numerazione allineata, pagina degli scarti |
| B. Solo codifiche | il portale usa le tabelle ufficiali per EER, HP, R/D | dati più puliti | basso |
| C. FIR digitale | emissione del formulario dal portale | alto solo se il FIR lo emette l'azienda e non il trasportatore | alto (ruoli, firme, flussi con terzi) |

### Rischi

- **Doppia trasmissione**: se un consulente o il gestionale del trasportatore trasmette già i movimenti, la stessa cosa arriverebbe due volte. È la prima cosa da chiarire.
- **Certificato**: il certificato dell'operatore è un segreto vero. Andrebbe nello storage privato cifrato o nel certificato di macchina, mai nel repository, con rotazione e scadenza nello scadenzario.
- **Fonte di verità**: con la trasmissione attiva un movimento accettato dal RENTRI non si modifica più liberamente nel portale: serve la rettifica (che il wizard già prevede).

### Proposta

1. **Subito, sforzo basso**: chiarire chi trasmette oggi al RENTRI e come. Se nessuno, o se lo si fa a mano, l'opzione A ha senso.
2. **Opzione B** (codifiche) come primo passo tecnico: prepara la mappatura che serve ad A.
3. **Opzione A in ambiente demo**: client, firma, invio di movimenti sintetici, lettura degli esiti, stato sul movimento. Si passa all'ambiente reale solo dopo il collaudo con chi gestisce i rifiuti.
4. **Opzione C** solo se l'azienda emette i propri FIR.

**Serve dall'azienda**: chi gestisce oggi la trasmissione al RENTRI, l'iscrizione e le unità locali, la richiesta del certificato per l'interoperabilità (ambiente demo e reale) e un referente HSE per il collaudo.
