# Automatismi e vulnerabilità

Questo capitolo spiega tre funzioni che riducono il lavoro ripetitivo del SOC senza nascondere i problemi veri:

- la **soppressione appresa**: il sistema smette di aprire un alert che il team ha già scartato più volte;
- gli **automatismi di rientro**: l'alert si chiude da solo quando un dato successivo prova che il problema non c'è più;
- l'**impatto CVE sugli asset**: per ogni vulnerabilità si vede quali PC la hanno davvero, partendo dall'inventario software.

Le pagine si trovano nel menu del SOC: **Soppressioni** e **Vulnerabilità** per tutti; in **Configurazione** le schede **Automatismi di rientro** e **Inventario software** (da cui si apre **Software e CPE**) per chi ha il permesso di configurazione.

## Soppressione appresa

### Come funziona

1. Ogni alert ha un'**impronta**: sorgente, tipo di evento e i campi che identificano il soggetto (per esempio job e dispositivo per un backup, CVE e prodotto per una vulnerabilità, utente o IP per la VPN). Data, ora, numeri di riga e conteggi non fanno parte dell'impronta.
2. Quando qualcuno **disattiva** un alert, la disattivazione viene contata su quell'impronta.
3. Alla **terza disattivazione in 90 giorni** nasce da sola una regola di soppressione sull'impronta esatta. Soglia e finestra si cambiano in Impostazioni.
4. Dalla **quarta occorrenza** l'alert non nasce più: l'evento resta comunque registrato in **Eventi › Soppressi**, con la regola che lo ha fermato.
5. La regola **scade dopo 180 giorni**. Ogni nascita di regola finisce nel registro audit e, se configurato, arriva come avviso sul canale SOC.

### Cosa conta come disattivazione

| Azione sull'alert | Conta? |
| --- | --- |
| Falso positivo | Sì |
| Chiudi con esito «Non rilevante» | Sì |
| Chiudi con esito «Rischio accettato» | Sì |
| Silenzia | Sì |
| Chiudi con esito «Risolto» | No: il problema era vero ed è stato sistemato |
| Chiusura automatica (rientro) | No |
| Posticipa, Prendi in carico | No |

Per ogni disattivazione il **motivo è obbligatorio**: è quello che si legge poi nella regola appresa. Un'azione massiva (più alert insieme, o la chiusura di un ticket come falso positivo) conta **una volta sola**.

Nella scheda dell'alert il riquadro del ciclo di vita mostra a che punto è il conteggio, per esempio «2/3 disattivazioni»: la prossima disattivazione farà nascere la regola.

### I limiti di sicurezza

La soppressione appresa **non scatta mai** in questi casi (impostazioni attive di default):

- **severità critica**, anche quando l'evento arriva come «alto» ma ha un punteggio CVSS di 9 o più;
- **CVE sfruttate** (presenti nel catalogo CISA KEV). Se il catalogo KEV non è aggiornato da più di 48 ore, il sistema si comporta come se la CVE fosse sfruttata;
- **minacce**: malware, ransomware, botnet e simili;
- **aggravamento**: se un'occorrenza arriva con severità più alta di quelle disattivate, l'alert nasce comunque;
- **impronte troppo generiche**: se l'alert non ha un campo che identifica il soggetto (dispositivo, utente, prodotto…), non si impara nulla;
- **tipi di evento esclusi**: elenco libero in Impostazioni.

Inoltre la regola nasce solo se **almeno una** delle disattivazioni è stata fatta da chi ha il permesso di configurazione del SOC. Chi ha la sola lettura può disattivare gli alert, ma da solo non può creare una soppressione.

### Come si annulla

La regola si spegne e il conteggio riparte da zero quando:

- qualcuno **riapre a mano** un alert di quell'impronta;
- qualcuno **promuove ad alert** un evento che la regola aveva soppresso (da Eventi › Soppressi);
- chi ha il permesso di configurazione la **revoca** dalla pagina **Soppressioni**, indicando il motivo.

### La pagina Soppressioni

Elenca le soppressioni manuali e quelle apprese. Per ognuna mostra ambito, motivo, quante volte ha fermato un evento (hit), ultima volta e scadenza. I filtri «Apprese / Manuali» e «Attive / In scadenza / Scadute o revocate» aiutano la revisione periodica: conviene guardare almeno una volta al mese le regole **in scadenza entro 14 giorni** e quelle con molti hit. In fondo alla pagina ci sono le ultime disattivazioni registrate.

## Automatismi di rientro

Un automatismo di rientro chiude un alert come **Risolto** quando un dato successivo **dimostra** che il problema è rientrato. Nel dubbio l'alert resta aperto. Ogni chiusura automatica compare nella timeline dell'alert come «Risolto automaticamente», con il motivo e il riferimento al dato che la prova.

### Le regole

| Regola | Si applica a | Prova richiesta | Stato iniziale |
| --- | --- | --- | --- |
| Backup tornato a buon fine | Backup fallito | Stesso job sullo stesso dispositivo completato dopo il fallimento | Accesa |
| CVE senza più dispositivi esposti | CVE critica esposta (Defender) | Stessa CVE e stesso prodotto riletti con 0 dispositivi esposti; l'assenza dal report non basta | Accesa |
| Sorgente di nuovo regolare | Sorgente silenziosa | Report e lettura della casella di nuovo nei tempi attesi | Accesa |
| VPN tornata nei limiti | Riconnessioni brevi, accessi negati | Per N giorni interi (default 7) dati VPN presenti **ogni giorno** e conteggi sotto soglia ogni giorno | Spenta |
| CVE con patch installata | CVE non critica e non in KEV | Inventario recente: il prodotto c'è solo in versioni non vulnerabili, nessun PC impattato o da verificare | Spenta |

### Simulare prima di accendere

Nella pagina **Configurazione › Automatismi di rientro** ogni regola ha il pulsante **Simula 30 giorni**: mostra quali alert degli ultimi 30 giorni la regola avrebbe chiuso, con il motivo, **senza chiudere nulla**. Un alert che il team ha chiuso per altri motivi ma che la regola avrebbe chiuso è un buon segnale; un alert ancora in lavorazione che la regola avrebbe chiuso è un campanello d'allarme.

Una regola si può **accendere solo se è stata simulata negli ultimi 7 giorni**. Accensioni e spegnimenti finiscono nel registro audit. Per spegnere tutte le chiusure automatiche in un colpo solo si imposta `SECURITY_AUTO_RESOLVE_ENABLED` a `false` in Configurazione › Impostazioni generali.

## Impatto CVE sugli asset

### Da dove arrivano i dati

- **Inventario software**: export dei software installati per PC, da WatchGuard EPDR (Panda) o da BusinessLog, caricato a mano in CSV o Excel.
- **NVD** (National Vulnerability Database): per ogni CVE, quali prodotti e quali versioni sono vulnerabili.
- **CISA KEV**: l'elenco delle CVE sfruttate attivamente.
- **EPSS** (FIRST.org): la probabilità che una CVE venga sfruttata nei prossimi 30 giorni.

NVD, KEV ed EPSS vengono letti da un job in background ogni ora, solo se in **Configurazione › Avvisi e automatismi › Impatto CVE sugli asset** è acceso «Arricchisci le CVE da NVD e CISA KEV». Nessuna pagina del portale chiama questi servizi mentre la si apre.

### Importare un inventario

1. Apri **Configurazione › Inventario software**, scegli la provenienza (WatchGuard, BusinessLog, altro) e carica il file CSV o XLSX.
2. Associa le colonne del file ai campi: **PC**, **prodotto** e **versione** (obbligatori), **produttore** e **data di rilevamento** (facoltativi). Il sistema propone l'associazione leggendo le intestazioni; se compili **Salva come preset**, la volta dopo le colonne si associano da sole.
3. Premi **Aggiorna anteprima**: vedi le righe valide e quelle scartate, ognuna con il motivo (PC vuoto, versione vuota, riga duplicata…). In Excel formatta la colonna versione come **testo**: una versione salvata come numero («2.10» diventa 2.1) viene scartata.
4. Premi **Importa**. Le installazioni già note vengono aggiornate; quelle che non compaiono più nel nuovo export dello stesso tipo vengono segnate come **non più rilevate**.

**Export di WatchGuard EPDR**: serve l'elenco dei software **suddiviso per PC**, con la colonna `Computer`. L'elenco aggregato, che per ogni software riporta solo il numero di computer, non dice quali PC sono esposti e non si può usare. Il file si carica così com'è. Associa **PC** a `Computer` (non a `Computer type`), **prodotto** a `Name`, **produttore** a `Publisher` e **versione** a `Version`. Lascia vuota la **data di rilevamento**: `Installation date` è la data di installazione, non quella del rilevamento. L'aggiornamento dell'inventario si misura dalla data dell'import. Le righe senza versione vengono scartate: è normale per alcuni programmi.

Il file caricato resta in un'area privata e cifrata solo fino all'import e non è mai scaricabile dal browser. Se abbandoni un'importazione a metà, **Annulla e elimina il file**; in ogni caso le anteprime non confermate vengono cancellate dopo 2 giorni.

### Collegare i software alle CVE (CPE)

NVD descrive i prodotti con un codice chiamato **CPE** (produttore e prodotto, per esempio `7-zip:7-zip`). Per sapere se una CVE riguarda un software dell'inventario, ogni coppia produttore/prodotto va collegata al suo CPE una volta sola, in **Configurazione › Inventario software › Software e CPE**.

**Collegamento automatico.** Dopo ogni giro dell'arricchimento CVE e dopo ogni import dell'inventario il sistema collega **da solo** i software il cui nome coincide senza dubbi con un CPE delle CVE scaricate:

- produttore e prodotto uguali (per esempio «google» + «google chrome» ↔ `google:chrome`);
- oppure il prodotto uguale a un nome NVD che nessun altro produttore usa, di almeno 4 caratteri (per esempio «7-zip» ↔ `7-zip:7-zip`).

Questi collegamenti hanno il badge **automatico** e nella spiegazione degli esiti compare «collegamento automatico a …». Se uno è sbagliato, **Azzera**: il sistema non lo rifà più. Le decisioni prese da una persona (confermato, N/A) non vengono mai cambiate. **Collega automaticamente ora** lo esegue subito.

**Cosa c'è da fare davvero.** I CPE candidati sono solo quelli che compaiono nelle CVE già presenti nel sistema (arrivate dagli alert e arricchite da NVD): il sistema non cerca CVE partendo dall'inventario. Per questo la pagina divide i software in filtri:

| Filtro | Cosa contiene | Cosa fare |
| --- | --- | --- |
| **Da decidere** | software con almeno una CVE dal nome simile (proposta) | confermare il CPE giusto o segnare **N/A** |
| **Senza CVE note** | nessuna CVE nel sistema ha un nome simile | niente: se più avanti arriva una CVE che li riguarda, passano da soli in **Da decidere** |
| **Collegati in automatico** | collegati dal sistema (badge **automatico**) | controllare a campione; **Azzera** se sbagliati |
| **Non applicabili** | segnati N/A a mano, in blocco o da una regola | niente |

Il vecchio filtro «Da mappare» (tutto ciò che non era deciso) non c'è più: un link salvato con `?stato=da_mappare` apre **Da decidere**.

**Azioni in blocco.**

- **Conferma selezionati**: conferma la prima proposta delle righe spuntate (le righe senza proposta vengono ignorate). La casella nell'intestazione della tabella spunta tutte le righe della pagina.
- **N/A selezionati**: segna non applicabili le righe spuntate.
- **Conferma tutte le proposte a candidato unico (N)**: conferma, su tutte le pagine della vista corrente, i software che hanno **una sola** proposta. Chiede conferma prima di procedere.
- **N/A tutti i risultati di «testo» (N)**: compare quando cerchi almeno 3 caratteri; segna non applicabili tutti i software ancora aperti trovati dalla ricerca, su tutte le pagine (per esempio cerca `redistributable` o `driver`). Chiede conferma prima di procedere.

Ogni modifica in blocco resta nel registro audit, una riga per software.

**Regole «non applicabile».** In fondo alla pagina, **Regole «non applicabile»** esclude in modo permanente i software il cui nome **contiene** un testo (almeno 3 caratteri), eventualmente solo di un produttore: **Salva e applica** la applica subito e poi a ogni import dell'inventario. Una regola:

- non cambia mai i software già confermati o segnati N/A;
- non esclude i software che hanno una CVE dal nome simile: quelli restano in **Da decidere**;
- se più avanti arriva una CVE dal nome simile per un software che aveva escluso, il software torna in **Da decidere** con la nota «è arrivata una CVE dal nome simile: decidi».

**Elimina** una regola e i software che aveva escluso tornano da valutare.

Per il resto:

- **Cerca in NVD** propone i CPE più simili; **Conferma** quello giusto. Serve solo per i casi dubbi: non va fatto riga per riga.
- **N/A** per i software senza CVE da seguire (driver, componenti interni): non verranno più proposti.
- **Alias** unisce nomi diversi dello stesso produttore o prodotto (per esempio «Microsoft Corporation» e «Microsoft»).
- **Ricalcola impatti** riapplica tutte le regole dopo una serie di modifiche.

Finché un software non ha il CPE confermato, le CVE che potrebbero riguardarlo risultano **da verificare**, mai «non impatta». Parti da **Da decidere**: le righe sono ordinate per numero di PC, quindi le prime sono le più importanti.

La **API key NVD** è facoltativa: senza key NVD accetta 5 richieste ogni 30 secondi, con la key molte di più. Si inserisce nella stessa pagina, viene salvata cifrata e si rimuove solo con **Rimuovi la key**.

### Come si legge l'esito

Per ogni CVE e ogni PC il sistema dà uno di tre esiti, sempre con la spiegazione in chiaro (prodotto, versione installata, range vulnerabile, fonte e data dell'inventario).

| Esito | Quando | Esempio |
| --- | --- | --- |
| **Impatta** | CPE confermato e versione installata dentro il range vulnerabile | 7-Zip 23.01 con CVE vulnerabile sotto la 24.07 |
| **Non impatta** | CPE confermato e versione fuori range, oppure inventario recente in cui il prodotto non c'è | 7-Zip 24.08 con la stessa CVE |
| **Da verificare** | CPE non confermato, versione non confrontabile (es. `21H2`, `1.1.1b`), inventario più vecchio di 30 giorni, CVE valida solo su un sistema operativo specifico | Un prodotto simile ma non ancora collegato |

Il sistema non tira mai a indovinare: quando non può dimostrare l'esito, scrive «da verificare».

### Dove si vede

- **Vulnerabilità**: CVE che impattano o da verificare, ordinate per KEV, CVSS, EPSS e numero di PC impattati; i PC più esposti; i software ancora da collegare.
- **Scheda CVE**: l'esito PC per PC con la spiegazione.
- **Scheda alert e ticket** di una CVE: il riquadro «Impatto sugli asset» e, se non ci sono PC impattati, la proposta di chiusura. La proposta **non compare mai** per CVE sfruttate (KEV) o critiche.
- **Scheda asset** del modulo Asset: la sezione «Vulnerabilità» con le CVE che riguardano quel PC e la scheda **Software** con tutti i programmi installati, le versioni precedenti, la licenza collegata e le CVE per programma.
- **Licenze software** del modulo Asset: per le licenze collegate a un software dell'inventario, su quanti PC è installato rispetto ai posti acquistati.

### Alert e ticket automatici

Quando l'inventario dice che un PC ha una versione vulnerabile di una CVE **critica** (CVSS 9 o più) o **sfruttata attivamente** (CISA KEV), il SOC apre un alert critico, senza aspettare che lo segnali Defender.

- **Un alert per CVE**, con il numero di PC impattati e il prodotto nel titolo. Se al giro dopo altri PC risultano impattati, l'alert si aggiorna; non ne nasce uno nuovo.
- L'alert nasce solo per i PC che **diventano** impattati: lo stesso PC già segnalato non lo fa ripartire. Se chiudi l'alert e il PC resta vulnerabile, l'alert non si riapre da solo finché non si aggiunge un altro PC.
- **Ticket di rimedio**: si apre insieme all'alert. Se per quella CVE c'è già un ticket aperto (per esempio nato da Defender), l'alert si collega a quello, senza un secondo ticket.
- Le notifiche sono quelle degli altri alert e ticket, sugli stessi canali.
- Le CVE alte, medie e basse non aprono alert: si guardano nella pagina **Vulnerabilità**.

Si accende e si spegne in **Configurazione › Avvisi e automatismi › Impatto CVE sugli asset**: «Apri un alert quando un PC risulta impattato» e «Apri anche il ticket di rimedio». Arrivano accese, ma funzionano solo con l'arricchimento CVE acceso e un inventario importato.

## Software non conforme

Nel modulo Asset il **Catalogo software** raccoglie le decisioni dell'azienda su ogni programma dell'inventario: **Consentito**, **Da rimuovere**, **Non autorizzato**, ed eventualmente una **versione minima**. Il SOC confronta l'inventario con queste decisioni dopo ogni import dell'inventario e ogni modifica al catalogo.

- **Un alert per software e per caso**: software non autorizzato (severità alta), software da rimuovere, versione sotto la minima (solo per i software consentiti). Il titolo dice il prodotto e su quanti PC è.
- L'alert nasce solo quando **nuovi** PC entrano nel caso; se altri PC si aggiungono dopo, lo stesso alert si aggiorna.
- Una versione scritta in modo non confrontabile (per esempio «2023 R2») non viene mai contata come vecchia.
- Quando il software sparisce dall'inventario l'alert **non** si chiude da solo: lo chiude chi ha verificato la rimozione.
- Riepilogo nella pagina **Vulnerabilità**, riquadro **Software non conforme**, con il link al catalogo già filtrato.

Si accendono e si spengono in **Configurazione › Avvisi e automatismi › Software non conforme** (tre interruttori, accesi di default). Senza software classificati nel catalogo non nasce nessun alert.

## Domande frequenti

**Ho disattivato tre volte lo stesso alert ma la regola non è nata.** Controlla nella scheda dell'alert il conteggio e il motivo: probabilmente l'alert è critico, riguarda una CVE sfruttata o una minaccia, il tipo è escluso, oppure nessuna delle tre disattivazioni è stata fatta da chi ha il permesso di configurazione.

**Una soppressione appresa nasconde un problema vero.** Riapri l'alert o promuovi l'evento soppresso: la regola si spegne subito e il conteggio riparte. Per spegnere del tutto la funzione: Configurazione › Avvisi e automatismi › Soppressione appresa.

**Un PC risulta «da verificare» per tutte le CVE.** L'inventario di quel PC è più vecchio di 30 giorni (la soglia si cambia in Impostazioni): carica un export aggiornato.

**La dashboard Vulnerabilità è vuota.** Verifica che l'arricchimento sia acceso in Impostazioni, che sia stato importato almeno un inventario e che i software principali abbiano il CPE confermato. Il job gira ogni ora.
