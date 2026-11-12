# Automatismi e vulnerabilità

Questo capitolo spiega tre funzioni che riducono il lavoro ripetitivo del SOC senza nascondere i problemi veri:

- la **soppressione appresa**: il sistema smette di aprire un alert che il team ha già scartato più volte;
- gli **automatismi di rientro**: l'alert si chiude da solo quando un dato successivo prova che il problema non c'è più;
- l'**impatto CVE sugli asset**: per ogni vulnerabilità si vede quali PC la hanno davvero, partendo dall'inventario software.

Le pagine si trovano nel menu del SOC: **Vulnerabilità** (voce **Dispositivi**) e **Soppressioni** (voce **Impostazioni**) per tutti; in **Impostazioni › Configurazione** le schede **Automatismi di rientro** e **Inventario software** (da cui si apre **Software e CPE**) per chi ha il permesso di configurazione.

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

Elenca le soppressioni manuali e quelle apprese. Per ognuna mostra ambito, motivo, quante volte ha fermato un evento (**Volte applicata**), **Ultima volta** e scadenza. I filtri «Apprese / Manuali» e «Attive / In scadenza / Scadute o revocate» aiutano la revisione periodica: conviene guardare almeno una volta al mese le regole **in scadenza** e quelle applicate molte volte. In fondo alla pagina ci sono le ultime disattivazioni registrate.

### Soppressioni in scadenza

**14 giorni** prima della scadenza di una soppressione attiva (manuale o appresa) nasce un alert di attenzione «Soppressione manuale (o appresa) in scadenza fra N giorni: nome della regola», uno per regola e scadenza, che arriva sui canali come ogni alert nuovo: si decide se prolungarla o lasciarla scadere. Se la scadenza viene spostata in avanti, il promemoria riparte per la nuova data. I giorni si cambiano in Impostazioni › **Soppressioni in scadenza** («Promemoria prima della scadenza») e valgono anche per il filtro **In scadenza** e il numero «in scadenza entro N giorni» della pagina Soppressioni; l'interruttore «Alert quando una soppressione sta per scadere» arriva acceso (spento, il numero resta e accanto compare «senza alert»). Sulla data in giallo, il passaggio del mouse dice quando è partito il promemoria. Il controllo gira con il ciclo del SOC ogni 15 minuti, insieme alle accettazioni del rischio, e resta nell'audit del portale.

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
| CVE critica corretta con prove | Alert «PC con versione vulnerabile» (inventario, CVE critica o KEV) | Nessun PC più impattato né da verificare; ogni PC che era esposto ha **2 prove concordi** tra inventario recente, patch WatchGuard e Defender. Vedi «Chiusura con prove» | Accesa |

### Simulare prima di accendere

Nella pagina **Configurazione › Automatismi di rientro** ogni regola ha il pulsante **Simula 30 giorni**: mostra quali alert degli ultimi 30 giorni la regola avrebbe chiuso, con il motivo, **senza chiudere nulla**. Un alert che il team ha chiuso per altri motivi ma che la regola avrebbe chiuso è un buon segnale; un alert ancora in lavorazione che la regola avrebbe chiuso è un campanello d'allarme.

Una regola si può **accendere solo se è stata simulata negli ultimi 7 giorni**. Accensioni e spegnimenti finiscono nel registro audit. Per spegnere tutte le chiusure automatiche in un colpo solo si imposta `SECURITY_AUTO_RESOLVE_ENABLED` a `false` in Configurazione › Impostazioni generali.

## Impatto CVE sugli asset

### Da dove arrivano i dati

- **Inventario software**: export dei software installati per PC, da WatchGuard EPDR (Panda) o da BusinessLog, caricato a mano in CSV o Excel.
- **Microsoft Defender for Endpoint**: con «Leggi il software dei PC» acceso (Impostazioni › Alert di Microsoft Defender) il software dei PC collegati a Defender arriva da solo ogni mattina alle 06:20, come un import (compare nell'elenco degli import con il nome «Microsoft Defender for Endpoint (API)»). Non serve caricare file per quei PC.

**Una riga sola, anche con più fonti.** Lo stesso software sullo stesso PC visto da WatchGuard e da Defender (stesso produttore, prodotto e versione) è **una riga**, non due: la scheda del PC e i conteggi non si raddoppiano. Se una fonte non lo vede più ma l'altra sì, resta «rilevato»; diventa «non più rilevato» solo quando nessuna fonte lo vede. Ogni fonte può togliere solo ciò che ha letto: un import Defender non cancella nulla sui PC che Defender non conosce.

**Release diverse dello stesso prodotto.** Le versioni restano righe distinte (servono al confronto con le CVE), ma si raggruppano per prodotto: nel catalogo e nella scheda del PC il prodotto è uno, con l'elenco delle versioni e i PC per versione. Anni diversi nel nome («Office 2016», «Office 2019») sono prodotti diversi, perché hanno CVE diverse.

**Nomi diversi tra le fonti.** Defender usa nomi brevi («chrome», «edge»), WatchGuard quelli completi («Google Chrome»): l'import li abbina da solo quando, sullo stesso PC e con la **stessa versione**, il nome senza il produttore coincide («chrome» = «Google Chrome» di Google) oppure uno è contenuto nell'altro con al massimo due parole in più e senza numeri. Non si abbinano prodotti con produttori diversi, versioni diverse («Edge» ≠ «Edge WebView2 Runtime», «Office» ≠ «Office 2019») né i casi dubbi, cioè due candidati alla pari: in quei casi restano due righe e si decide con un alias. Il nome della riga resta quello della prima fonte.

**Doppioni già importati e alias.** Per le righe già in archivio: `manage.py software_fonti_unisci` mostra le coppie che fonderebbe (anteprima, non scrive) e con `--applica` le fonde, tenendo la riga più vecchia. Per i nomi che non si abbinano da soli, `manage.py software_fonti_confronto` elenca, sui PC visti da entrambe le fonti, i prodotti presenti in una sola e propone l'alias più simile da inserire in Inventario software › Alias.
- **Firmware da monitoraggio SNMP**: per ogni dispositivo del Monitor SNMP con produttore, modello e versione firmware letta, il portale aggiunge da solo una riga «<modello> firmware» all'inventario (fonte «Firmware da monitoraggio SNMP», host = IP del dispositivo). Non si carica a mano: si aggiorna a ogni interrogazione e una versione nuova sostituisce la precedente. Per il confronto con le CVE va collegata al CPE come gli altri software (i CPE NVD dei firmware finiscono in `_firmware`). Se il dispositivo viene disattivato, eliminato o cambia IP la riga diventa «non più rilevata»; se viene collegato a un altro asset, firmware e impatti CVE passano subito su quell'asset. In «Host più esposti» un host che è un apparato di Contatori IT mostra il nome dell'apparato e apre la sua scheda; le CVE del firmware compaiono anche nel riquadro «Sicurezza» della scheda dell'apparato.
- **Eventi di sicurezza del portale** (Impostazioni → «Eventi di sicurezza del portale»): i momenti del portale che il SOC deve vedere arrivano tutti nella sorgente «Portale · accessi» da un canale unico (`core/eventi_sicurezza.py`): accesso bloccato per troppe password sbagliate, verifica in due passaggi bloccata, PIN di una postazione condivisa bloccato, sessione di una postazione usata da un altro PC, impersonazione avviata, accessi da dispositivi nuovi e «Non ero io». Per ogni tipo che può aprire un alert c'è un interruttore «Alert: …» (acceso di default); spento, l'evento resta come KPI. Gli eventi a raffica (lo stesso blocco ripetuto) diventano uno ogni ora; la stessa situazione (stessa persona, stesso PC) riusa l'alert finché è aperto.
- **Apparati di rete non raggiungibili** (Impostazioni → «Apparati di rete (Contatori IT)»): firewall, switch, server, storage, UPS e videoregistratori del Monitor SNMP che non rispondono per 2 controlli di fila (uno ogni 5 minuti; il numero si cambia) creano l'evento «apparato_irraggiungibile» (fonte «Contatori IT · apparati di rete») e un alert per apparato, severità alta per i firewall. Alla prima risposta l'evento «apparato_raggiungibile» chiude l'alert da solo. Stampanti, telecamere e sensori restano nel solo Contatori IT; un apparato «non verificato» non genera eventi.
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

### Dalla CVE al lavoro di correzione

Nella scheda di una CVE con PC colpiti, **Apri il lavoro di correzione** crea un caso a tuo nome con un'attività per PC e la versione a cui arrivare, se NVD la indica. A ogni ricalcolo degli impatti l'attività di un PC non più esposto si spunta da sola, quella di un PC di nuovo esposto si riapre e un PC nuovo aggiunge un'attività. Con l'ultimo PC il caso si chiude da solo, salvo attività aggiunte a mano ancora da fare. La scheda della CVE dice «N PC su M corretti».

### Collegare i software alle CVE (CPE)

NVD descrive i prodotti con un codice chiamato **CPE** (produttore e prodotto, per esempio `7-zip:7-zip`). Per sapere se una CVE riguarda un software dell'inventario, ogni coppia produttore/prodotto va collegata al suo CPE una volta sola, in **Configurazione › Inventario software › Software e CPE**.

**Una volta per programma.** Software e CPE ha una riga per programma, non per nome: la decisione vale per tutti i nomi e le release del programma, e una release nuova prende da sola il CPE già confermato. Con due CPE diversi nello stesso programma non si estende nulla. Le unioni fatte a mano nel Catalogo software non estendono il CPE.

**Non controllato.** Un programma senza CPE né «non applicabile» compare come «non controllato» nel Catalogo software, nella scheda del PC e nel cruscotto. Il SOC confronta i programmi collegati con le CVE che ha già scaricato, non con tutte quelle esistenti.

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
- **Alias** unisce nomi diversi dello stesso produttore o prodotto (per esempio «Microsoft Corporation» e «Microsoft»). Salvando un alias, le righe che diventano uguali si fondono subito in una sola, anche se arrivano da fonti diverse.
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

### Windows: release riconosciuta dalla build

L'NVD descrive Windows **per release** (Windows 10 21H2, Windows 11 24H2, Server 2022…), mentre l'inventario dice il nome del sistema e la **build** (`10.0.26200.6899`). Senza abbinamento ogni CVE di Windows lascia tutti i PC Windows «da verificare», e i PC che WatchGuard chiama per esteso («Windows 11 Pro 64 bits Version 25H2») non vengono proprio confrontati.

Con **Riconosci la release di Windows dalla build** acceso (Impostazioni › Avvisi e automatismi › Impatto CVE sugli asset) il SOC fa così, CVE per CVE:

1. legge i criteri Windows della CVE e, per ognuno, la release dalla build della versione limite (`10.0.22631.5472` → Windows 11 23H2);
2. riconosce i PC Windows (il sistema operativo, non Defender, Web Experience Pack o simili): **client o server dal nome** (la build 17763 è sia Windows 10 1809 sia Server 2019), **release dalla build**;
3. confronta ogni PC **solo** con i criteri della sua famiglia e release:
   - criterio trovato → confronto della versione completa: **impatta** o **non impatta** come per gli altri programmi;
   - la CVE non elenca la sua release → **non impatta** («la CVE non riguarda questa release», con le release colpite);
   - versione non leggibile, inventario vecchio o un criterio di cui non si riconosce la release → **da verificare**, con il motivo.

Nella spiegazione compare «Release riconosciuta dalla build: Windows 11 24H2». I PC che passano da «da verificare» a «non impatta» compaiono fra le uscite come «Rivalutata»: non sono correzioni.

**Prima di accenderla** si lancia sul server `manage.py cve_windows_anteprima`: dice, senza scrivere niente, quanti esiti cambiano e quali CVE aprirebbero un alert (PC che diventano «impatta» su CVE critiche o sfruttate). Al primo ricalcolo dopo l'accensione quegli alert si aprono tutti insieme: è previsto, sono esposizioni vere.

### Proposte dell'AI locale sui casi da verificare

I casi «da verificare» bloccano la chiusura automatica delle CVE. L'AI locale del portale (lo stesso server interno dell'Assistente AI: nessun dato esce dall'azienda) può esaminarli e **proporre** una risposta; decide sempre una persona.

Due tipi di proposta:

| Tipo | Quando | Cosa propone | Dove si decide |
| --- | --- | --- | --- |
| **Collegamento CPE** | software in **Da decidere** (senza CPE confermato, con almeno una CVE dal nome simile) | un CPE scelto **solo fra quelli delle CVE già nel sistema**, oppure «Non applicabile», oppure «Resta da verificare» | **Software e CPE**, colonna Suggerimenti, filtro **Proposte AI (N)** |
| **Esito CVE su un PC** | riga «da verificare» con CPE confermato: versione non confrontabile (es. `24.08 R2`, `1.1.1b`) o CVE valida solo in una configurazione | «Impatta», «Non impatta» o «Resta da verificare» | **scheda CVE**, colonna Spiegazione |

Ogni proposta ha una **motivazione** di una frase e una **confidenza** (0-100). Le risposte vengono controllate prima di essere mostrate: un CPE che non è fra i candidati, un esito che cita versioni assenti dai dati, una confidenza sotto la **Confidenza minima** (60 di serie) vengono scartati e il caso resta da verificare. Un software vecchio nell'inventario (oltre 30 giorni) o senza CPE candidati non viene chiesto all'AI: lì serve un inventario nuovo o una decisione a mano.

- **Accetta** su un CPE fa esattamente ciò che fa **Conferma** (o **N/A**) a mano: mappatura confermata da te, riga nel registro audit con «proposta AI #n accettata», impatti in ricalcolo. **Accetta** su un esito registra che **tu** hai verificato quel PC per quella CVE: l'esito vale finché la versione installata resta la stessa e nella spiegazione restano chi, quando e la motivazione. Se la versione cambia, il PC torna «da verificare».
- **Rifiuta** scarta la proposta; l'AI non la ripropone finché i dati del caso (candidati, versioni, range) non cambiano.
- «Resta da verificare» si può solo rifiutare: l'AI non ha preso posizione.
- Quando il caso si risolve in altro modo (software confermato a mano, PC aggiornato), la proposta diventa «superata» e sparisce.

**Quando gira.** La lettura **cpe_ai** (Impostazioni › Letture automatiche, gruppo Vulnerabilità) gira ogni 6 ore ed è **spenta di serie**: si accende in **Impostazioni › Proposte AI su CPE ed esiti da verificare**, dove si scelgono anche il **Massimo per giro** (5 casi di serie: in produzione ogni risposta impegna l'AI 15-40 secondi) e la **Confidenza minima**. Il pulsante **Proponi con l'AI ora** in Software e CPE (ed «Esegui ora» nelle Letture automatiche) lancia un giro subito, anche con il giro automatico spento. Prima i CPE dei software più diffusi, poi gli esiti delle CVE più gravi. Se Ollama non risponde il giro si ferma senza fare richieste e la scheda della lettura lo dice. Ogni richiesta è nel registro AI del SOC.

**Limiti.** Il modello sceglie fra nomi: può confondere prodotti della stessa famiglia (es. due edizioni dello stesso programma) o giudicare una versione dal formato insolito. Per questo la proposta non è mai applicata da sola, le CVE sfruttate (KEV) e critiche non si chiudono comunque in automatico e la motivazione va letta prima di accettare.

### Dove si vede

- **Vulnerabilità**: CVE che impattano o da verificare, ordinate per KEV, CVSS, EPSS e numero di PC impattati, con gravità, programmi coinvolti, «esposta dal», termine di correzione e PC corretti negli ultimi 90 giorni. Filtri: testo (CVE, descrizione, programma o PC), gravità, esito (impatta / solo da verificare), termine (oltre il termine, in scadenza entro 7 giorni, con rischio accettato) e «Solo sfruttate (KEV)». Clic sulla riga: il pannello della CVE. In più gli **Asset più esposti** (i 20 con più CVE, con «tutti» verso Dispositivi › Con CVE; clic sulla riga: pannello del PC; selezionali per aprire un ticket) e i software ancora da collegare. «PC oltre il termine» dice il totale vero; il riquadro ne elenca i primi 15, con il link a tutte le CVE oltre il termine. La tabella delle CVE mostra le prime 500; **Scarica CSV** accanto ai filtri dà l'elenco completo del filtro (CVE, gravità, CVSS, EPSS, KEV, programmi, PC impattati e da verificare, esposta dal, termine, PC oltre il termine, in scadenza e con rischio accettato, corretti in 90 giorni).
- **Correzioni CVE** (Dispositivi › Correzioni CVE): le CVE chiuse dagli aggiornamenti, vedi «Correzioni CVE» qui sotto.
- **Scheda CVE**: l'esito PC per PC con la spiegazione. Clic sulla riga: il pannello del PC; il nome apre la scheda PC. Seleziona più PC per **Apri un ticket per questi PC**, **Accetta il rischio** (stessi campi e permesso dell'accettazione singola: un'accettazione per PC) o **Conferma le proposte dell'AI** (solo i PC con una proposta da applicare).
- **Scheda alert e ticket** di una CVE: il riquadro «Impatto sugli asset» e, se non ci sono PC impattati, la proposta di chiusura. La proposta **non compare mai** per CVE sfruttate (KEV) o critiche.
- **Scheda asset** del modulo Asset: la sezione «Vulnerabilità» con le CVE che riguardano quel PC e la scheda **Software** con tutti i programmi installati, le versioni precedenti, la licenza collegata e le CVE per programma.
- **Pannello laterale delle CVE**: nel Catalogo software (colonna CVE e scheda del programma) e nella scheda asset (riquadro «Vulnerabilità» e colonna CVE della scheda Software) il numero di CVE è un bottone che apre un pannello a destra, senza lasciare la pagina. Vedi «Il pannello delle CVE» qui sotto.
- **Licenze software** del modulo Asset: per le licenze collegate a un software dell'inventario, su quanti PC è installato rispetto ai posti acquistati.

### Il pannello delle CVE

Il pannello si apre dal bottone rosso «N CVE» (arancione per «da verificare») e si chiude con <kbd>Esc</kbd> o con la ×.

- **Dal Catalogo software** mostra le CVE del programma su tutti i PC che lo hanno oggi, anche quando le fonti lo chiamano in modo diverso. In cima tre numeri: CVE che **colpiscono**, quante sono **gravi** (sfruttate attivamente, cioè in CISA KEV, oppure con CVSS 9 o più) e quante sono **da verificare**. Le CVE sono in ordine di **priorità** (vedi sotto). Ogni riga dice quanti PC sono colpiti, quali versioni e, se l'NVD lo indica, da quale versione è corretta. Le «da verificare» sono in un gruppo chiuso a parte.
- **Nella scheda del programma** una fascia in alto dice quante CVE lo colpiscono e la tabella «Versioni presenti» ha la colonna **CVE**: quante CVE colpiscono ciascuna versione. Le versioni con «nessuna nota» sono quelle a cui aggiornare.
- **Dalla scheda asset** mostra le CVE del PC raggruppate per software installato; aperto dalla riga di un software della scheda Software, quel software è in cima ed è l'unico aperto.
- **Clic su una CVE** apre la scheda breve nel pannello: gravità e CVSS, se è sfruttata attivamente (con la scadenza CISA), la descrizione, **Cosa fare** (la versione da installare, se nota), la probabilità di attacco (EPSS), i PC colpiti o da verificare con la versione (il PC da cui si arriva è evidenziato «questo PC») e i range vulnerabili letti dall'NVD. «Torna all'elenco» riporta all'elenco; «Scheda completa» apre la pagina della CVE nel SOC; «Apri su NVD» apre il sito NVD.

**Priorità.** Ogni CVE ha una priorità, scritta in «Cosa fare»:

- **Subito**: sfruttata attivamente (CISA KEV) oppure con probabilità di attacco alta (EPSS 10% o più nei prossimi 30 giorni). Nell'elenco ha l'etichetta «Sfruttata» o «Probabile attacco».
- **Presto**: CVSS 9 o più, oppure CVSS 7 o più con EPSS almeno 1%.
- **Normale**: tutto il resto.

KEV ed EPSS si leggono con «Arricchisci le CVE da NVD e CISA KEV» e «Leggi anche il punteggio EPSS» (Impostazioni › Avvisi e automatismi › Impatto CVE sugli asset): senza, la priorità usa solo il CVSS.

**Patch WatchGuard.** Con la lettura delle patch accesa (vedi «Patch e protezione (WatchGuard)»), la riga della CVE dice «patch WatchGuard pronta su N PC», «Cosa fare» lo ripete e ogni PC ha l'etichetta della patch con il suo stato (da installare, attende il riavvio, errore di installazione…).

**Calcolo ibrido con Defender.** Con «Confronta le CVE con Defender» e «Usa le CVE di Defender nel calcolo» accese, le CVE critiche e alte che Defender vede entrano nell'elenco del SOC. Su un PC che Defender vede, la sua segnalazione vale «impatta» anche senza CPE collegato; se il calcolo sulle versioni dice che il PC è a posto, l'esito è «da verificare». NVD aggiunge i range di versione, così il SOC controlla la stessa CVE anche sui PC che Defender non vede. I programmi letti da Defender risultano «controllati». Se Defender nomina un programma che sul PC non si riconosce, resta nel confronto come «solo Defender». Le CVE medie e basse restano solo nel confronto.

**Confronto con Defender.** Con «Confronta le CVE con Defender» acceso (riquadro Microsoft Defender), ogni PC della scheda breve dice «Defender conferma» o «Defender non la vede»; un gruppo chiuso elenca i PC su cui Defender la vede e il SOC no. Il pannello di un PC ha «Confronto con Defender»: in comune, solo SOC, solo Defender. Dove i due non coincidono la CVE va guardata: di solito è un programma fuori dall'inventario WatchGuard, un CPE sbagliato o una versione letta male. Il confronto vale solo per i PC che Defender conosce.

I numeri del pannello sono gli stessi del catalogo: contano solo i software ancora presenti sui PC, dall'ultimo calcolo d'impatto (il pannello non legge l'NVD in diretta). Pannello e numeri compaiono solo a chi vede il Security Center; il server lo controlla a ogni apertura.

### Quando un PC viene aggiornato

Non si chiude niente a mano. Il giro è questo:

1. Il PC viene aggiornato (a mano, da Windows Update, dal patch management).
2. Il primo inventario dopo l'aggiornamento (export WatchGuard o lettura Defender) vede la versione nuova: la riga della versione vecchia diventa «non più rilevata».
3. Il ricalcolo degli impatti (parte da solo dopo ogni import) non trova più il PC esposto e scrive la **risoluzione**: CVE, PC, programma, versione prima e dopo, da quando era esposto, quando è uscito.

Nel pannello (programma, PC, scheda breve della CVE) la sezione **Risolte negli ultimi 90 giorni** elenca queste uscite. Il motivo:

- **Programma aggiornato**: sul PC c'è ancora il programma, con un'altra versione (mostrata «prima → dopo»).
- **Programma disinstallato**: il PC c'è nell'inventario, il programma no.
- **PC non più nell'inventario**: il PC non compare più nell'export. Non è una correzione verificata: può essere spento, dismesso o fuori dall'ultimo export.
- **Rivalutata**: la versione è la stessa ma non risulta più vulnerabile (l'NVD ha corretto i range, o una regola N/A).

Solo le prime due contano come **corrette**, e solo se oggi il PC non è di nuovo esposto alla stessa CVE (un PC tornato vulnerabile esce dalle risolte e torna fra i PC colpiti). La regola è la stessa in tutte le pagine: pannello, elenco delle Vulnerabilità, «Dalla segnalazione alla correzione», «Tempi di correzione», Correzioni CVE e Conformità ISO 27001. Ogni PC esposto ha anche «esposto dal»: la data passa da un ricalcolo all'altro (per le righe che c'erano prima di questa funzione è la data dell'ultimo ricalcolo).

Nella scheda asset, la riga **Visto da** in cima alla Panoramica dice quali fonti vedono il PC (Intune, WatchGuard, Defender, Security Center, SNMP) e quando: un PC senza WatchGuard né Defender non ha inventario software, quindi il SOC non può controllarne le CVE.

### Correzioni CVE

Dispositivi › **Correzioni CVE** (anche dal pulsante in cima all'elenco delle Vulnerabilità) è il registro di quello che si è chiuso: ogni PC uscito da una CVE, con il motivo e le versioni.

Come si contano, perché i numeri reggano a un audit:

- per ogni CVE e PC conta solo l'**ultima** uscita del periodo (un PC può uscire, rientrare e uscire di nuovo);
- un PC che oggi è **di nuovo esposto** alla stessa CVE (versione vulnerabile reinstallata, o tornato «da verificare») non conta come corretto: compare con l'etichetta rossa «Di nuovo esposto»;
- contano come correzioni solo «Programma aggiornato» e «Programma disinstallato». «PC non più nell'inventario» e «Rivalutata» dicono solo che il PC non risulta più esposto.

**In cima**: PC corretti (aggiornati e disinstallati), CVE **chiuse con gli aggiornamenti**, CVE **senza PC esposti ma non tutte verificate**, CVE **ancora aperte** su altri PC, giorni medi da «esposta dal» alla correzione, percentuale **corretta nel termine** (vedi «Tempi di correzione») e PC corretti e poi di nuovo esposti.

**Stato di oggi di una CVE** (vista per CVE):

- **Chiusa con gli aggiornamenti**: nessun PC impattato né da verificare, e ogni PC uscito nel periodo è stato aggiornato o ha disinstallato il programma.
- **Nessun PC esposto**: nessun PC impattato né da verificare, ma almeno un PC è uscito senza correzione verificata (sparito dall'inventario, rivalutata, oppure di nuovo esposto e poi uscito). Va guardato prima di considerarla chiusa.
- **Ancora aperta**: ci sono ancora PC impattati o da verificare (indicati sotto).

**Filtri**: periodo (30 giorni, 90 giorni, 12 mesi, tutto), **Come** (corrette, solo aggiornate, solo disinstallate, uscite senza correzione verificata, tutte) e ricerca per CVE, PC o programma. Il filtro «Come» si applica all'ultima uscita di ogni PC.

**Vista per CVE** (predefinita): stato di oggi, PC corretti e come, programmi «versione prima → dopo», giorni medi, ultima correzione. Clic sul numero di PC corretti: la vista PC per PC di quella CVE. **Vista PC per PC**: data, CVE, PC, programma, versione prima → dopo, come, esposta dal, giorni e **nel termine / in ritardo**; a video al massimo 2.000 righe (un avviso lo dice), i numeri in cima e il CSV le contano tutte.

Clic sulla riga: il pannello della CVE. **Scarica CSV** scarica tutte le righe del filtro, con le celle protette dalle formule di Excel, e resta nell'audit del portale. Una correzione compare dopo il primo import dell'inventario che vede la versione nuova.

### Patch e protezione (WatchGuard)

Pagina **Dispositivi › Patch e protezione**. Legge l'API di WatchGuard Cloud (Endpoint Security, sola lettura): serve collegare WatchGuard una volta, da **Impostazioni › Avvisi e automatismi**:

1. In WatchGuard Cloud › Amministrazione › **Managed Access** abilitare l'accesso API; copiare URL API (dipende dalla regione, per esempio `https://api.deu.cloud.watchguard.com`), **Access ID** e **password** (meglio quelli di sola lettura) e l'**API Key**. L'ID account (ACC-… o WGC-…) è in **My Account**.
2. Incollarli nel riquadro **Credenziali API WatchGuard** e **Salva le credenziali** (password e API Key restano cifrate e non si rivedono), poi **Prova la connessione**: dice quanti PC vede l'account.
3. Accendere le letture nel riquadro **WatchGuard Endpoint Security (API)**: PC e protezione, software dei PC, patch mancanti e, se serve, «Cerca le patch comprese in una più recente (Microsoft)». Girano alle 06:10 e alle 13:10. La lettura Microsoft scarica un documento al mese dall'API pubblica `api.msrc.microsoft.com` (decine di MB ciascuno) solo quando Microsoft lo aggiorna, al massimo una volta al giorno: il server del portale deve poter uscire su HTTPS verso quell'indirizzo.

Cosa c'è nella pagina:

- **Patch mancanti**: una riga per patch con i PC che ne hanno bisogno. In cima le patch che correggono una CVE sfruttata (CISA KEV), poi per criticità WatchGuard (Critica, Importante…) e per numero di PC. Aprendo la riga: le CVE che corregge (clic = scheda breve) e i PC con lo stato. Una patch esce dall'elenco quando WatchGuard non la segnala più: installata o non più necessaria; il ricalcolo CVE poi registra la risoluzione con la versione nuova.
- **Cerca**: per KB (es. KB5134133), CVE, nome della patch, programma o PC. Cercando una CVE escono la patch che la corregge e quella più recente che la comprende.
- **KB e download**: accanto al nome c'è la KB Microsoft (presa dal nome o dal file della patch); aprendo la riga, «Scarica a mano» porta al file della patch quando WatchGuard lo dà, e «può riavviare il PC da sola» avvisa delle patch con riavvio automatico.
- **Patch comprese in una più recente**: WatchGuard elenca le patch Microsoft una per una, anche quando un aggiornamento cumulativo comprende quelli prima. Il SOC lo riconosce in due modi:
  - **dal build di Windows nel nome**: «KB5134133 (OS Builds 26200.9725 and 26100.9725)» comprende «KB5127648 (OS Builds 26200.9711 and 26100.9711)», perché stesso ramo (26100) e revisione più alta (9725 > 9711). Vale anche per i fuori ciclo; le anteprime («Preview», facoltative) non vengono mai proposte al posto di un'altra patch;
  - **dal Security Update Guide di Microsoft**, con l'interruttore «Cerca le patch comprese in una più recente (Microsoft)»: Microsoft dice quale KB sostituisce quale, anche a catena; serve per .NET, SQL Server e Office, dove il nome non porta il build. Contiene solo gli aggiornamenti di sicurezza.

  Una patch è «compresa» solo se quella più recente manca **sullo stesso PC**. La patch compresa ha l'etichetta «Compresa in KB…» e va in fondo all'elenco; quella più recente dice «Comprende anche: KB… (N PC)» e «+N CVE delle precedenti», e prende la priorità delle CVE che chiude (una CVE sfruttata della vecchia la porta in cima). Lo stesso si vede nel riquadro «Patch» della scheda asset e nel pannello CVE («si chiude con KB…»).
- **Spiega con l'AI**: aprendo una patch, l'AI locale dice cosa corregge, quanto è urgente, cosa sapere prima di installare (riavvio, installazioni già fallite) e come procedere (se è compresa in una più recente, installare quella). Con **Cerca anche sul web** legge l'articolo Microsoft della KB e riporta i **problemi noti**. Lo stesso pulsante c'è nel pannello di ogni CVE: cos'è, se ci riguarda, come si corregge e cosa fare se non si può correggere subito.
- **Installazioni non riuscite**: l'esito dei task di installazione WatchGuard degli ultimi 14 giorni (errore di download, di installazione…).
- **Protezione da sistemare**: PC con l'agente ma protezione spenta, in errore, non aggiornata, con riavvio richiesto o non connessi da più di 7 giorni.
- **In rete senza agente**: dispositivi che le sonde WatchGuard hanno trovato in rete senza agente. Stampanti e apparati sono normali; un PC qui non è protetto.

La lettura del **software** sostituisce l'export WatchGuard caricato a mano: entra nell'inventario come fonte WatchGuard, con la stessa procedura. Le patch **si installano dalla console WatchGuard**: l'API non permette di comandarle dal portale.

Nella scheda asset la riga **Visto da** usa questi dati: «WatchGuard · protezione attiva · 3 patch mancanti», rosso se la protezione non va o se il PC è in rete senza agente.

### Patch installate

Pagina **Dispositivi › Patch installate** (anche dal riquadro «patch chiuse» di Patch e protezione): lo storico delle patch WatchGuard che non sono più mancanti, la più recente in cima. Per ogni riga: quando si è chiusa, PC, patch e programma, criticità, le **CVE che ha corretto** (con «CVE sfruttata» se è nel catalogo CISA KEV) e il **motivo**:

- **Installata (esito del task WatchGuard)**: un task di installazione di Patch Management ha registrato «Installata» o «Era già installata». È la prova più forte.
- **Non più segnalata da WatchGuard**: il PC c'è ancora ma WatchGuard non segnala più la patch, senza un esito di installazione: installata da Windows Update o dall'utente, oppure sostituita da una patch più recente.
- **PC non più in WatchGuard**: il PC è uscito dai dispositivi WatchGuard; la patch è sparita con lui. Non dice che sia stata installata.

Filtri: periodo (30, 90 giorni, un anno, tutto), motivo, ricerca per PC, patch, programma o CVE. In cima: patch chiuse, PC, CVE corrette, quante sfruttate (KEV), quante critiche e il conteggio per motivo. La tabella mostra le prime 500 righe e lo dice; **Scarica CSV** contiene tutte le righe del filtro ed è registrato nell'audit. Lo storico parte dalla prima lettura delle patch: una patch che ricompare (per esempio dopo una disinstallazione) torna fra le mancanti ed esce dallo storico.

Per sapere se la CVE è davvero chiusa sul PC conta la pagina **Correzioni CVE**, che guarda la versione del programma nell'inventario: la patch chiusa è il «perché», la correzione CVE è la verifica.

### Installazioni da console

Pagina **Dispositivi › Installazioni da console**: i task di installazione patch lanciati dalla console WatchGuard (Endpoints › Tasks, quelli come «Install Firefox patch on 37 computers»), l'ultima esecuzione in cima. Il SOC li conserva anche dopo che vengono cancellati dalla console.

- **Quando si legge**: ogni ora dalle 07:40 alle 19:40, dal lunedì al venerdì, e insieme alla lettura completa delle 06:10 e 13:10. Serve l'interruttore «Patch» della sezione «WatchGuard Endpoint Security (API)». Si leggono i task con un'esecuzione negli ultimi 30 giorni, fino a 300 per giro, le ultime 10 esecuzioni di ciascuno.
- **Per ogni task**: PC coinvolti, **Riuscite**, **Errori** (errore di download, di installazione, di disinstallazione) e **In attesa** (il PC non ha ancora risposto: il task in WatchGuard è «In progress»). Un PC riprovato in un'esecuzione successiva conta una volta, con l'ultimo esito.
- **Aprendo un task**: l'esito per PC e patch, prima gli errori, poi i PC in attesa.
- Un task con tutti gli esiti e l'ultima esecuzione più vecchia di 24 ore non si rilegge più: resta com'è nello storico.

**Verifica dopo l'installazione.** Quando un task finisce (nessun PC in attesa e almeno un'installazione riuscita, ultima esecuzione negli ultimi 2 giorni), la lettura successiva rilegge subito da WatchGuard le **patch mancanti** e il **software dei PC**, senza aspettare le 06:10 o le 13:10. La lettura del software fa ripartire il ricalcolo delle CVE e la **chiusura con prove** degli alert «PC con versione vulnerabile»: le regole restano quelle (2 prove concordi per le CVE critiche o sfruttate, nel dubbio l'alert resta aperto). Una sola lettura per giro anche se finiscono più task; se il software è stato letto da meno di 50 minuti si usa quello. Con l'interruttore «Software dei PC» spento la verifica è «saltata» e lo dice. La colonna **Verifica** della tabella mostra cosa è stato fatto e quando.

**Evidenza.** Aprendo un task, sopra la tabella ci sono i conteggi delle CVE corrette dalle sue patch e, per ogni PC, la colonna **CVE della patch** con lo stato di ognuna nel calcolo del SOC:

- **Corretta**: l'inventario ha visto il programma aggiornato o disinstallato dopo l'inizio del task;
- **Ancora vulnerabile** / **Da verificare**: il PC risulta ancora esposto (di solito l'inventario WatchGuard non si è ancora aggiornato: si ricontrolla alla lettura dopo);
- **Non nel calcolo del SOC**: la CVE non risultava sul PC (programma non collegato al catalogo CVE o versione mai vista vulnerabile).

Nella timeline dell'alert della CVE e nel suo pannello, la prova della patch dice anche quale task l'ha installata: «patch WatchGuard «…» installata il 12/11 dal task «Install … patch on 37 computers» della console».

L'esito arriva anche sulla patch mancante («Errore di installazione il 12/11» in Patch e protezione). La patch esce dalle mancanti quando WatchGuard non la segnala più: con la verifica, già alla lettura oraria dopo la fine del task.

### Tempi delle patch

Pagina **Dispositivi › Tempi delle patch** (anche dall'avviso «patch ferme» di Patch e protezione): quanto ci mettiamo a installare le patch e quali sono ferme. È la prova che chiede l'audit ISO 27001 8.8 (e NIS2) per le patch, accanto ai tempi di correzione delle CVE.

Ogni patch mancante su un PC ha un **termine** che parte da **«pubblicata il»** (la data del produttore che dà WatchGuard) e dipende dalla **classe** della patch:

| Classe | Quando | Termine (predefinito) |
| --- | --- | --- |
| Corregge una CVE sfruttata (KEV) | almeno una delle sue CVE è nel catalogo CISA KEV | 7 giorni |
| Critica | criticità «Critica» di WatchGuard | 14 giorni |
| Importante | criticità «Importante» | 30 giorni |
| Moderata e altre | moderata, bassa, service pack, non specificata | 90 giorni |

I giorni si cambiano in **Impostazioni › Avvisi e automatismi › Patch: tempi di installazione (ISO 27001 8.8)**. Una patch senza data di pubblicazione non ha termine.

La pagina ha quattro parti:

- **In cima**: patch installate nel periodo scelto (30, 90 giorni, un anno, tutto), **tempo medio di installazione** in giorni, quante **entro il termine**, e adesso: patch mancanti (una per patch e PC), oltre il termine (quante KEV o critiche), con l'installazione fallita.
- **Per classe**: termine, installate, giorni medi e mediana, entro il termine e in ritardo, mancanti e oltre il termine adesso. Il numero «oltre il termine» porta all'elenco delle patch ferme di quella classe.
- **Andamento**: due grafici delle ultime 26 settimane. «Patch installate per settimana» viene dalle date di chiusura; «Patch mancanti a fine settimana» viene da una fotografia scritta a ogni lettura WatchGuard (06:10 e 13:10), quindi parte dal giorno in cui la funzione è stata installata.
- **Patch ferme**: patch mancanti **oltre il termine** o con l'**ultima installazione fallita** (errore di download o di installazione nel task WatchGuard), una riga per patch con i PC, il ritardo e le CVE. Seleziona le patch e **Apri un ticket per questi PC**: un'attività per ogni PC delle patch scelte. Il nome del PC apre il suo pannello. Filtri per classe, cosa (oltre il termine, installazione fallita o tutte e due) e testo. **Scarica CSV** ha una riga per patch e PC ed è registrato nell'audit (`soc_patch_ferme_export`).

Il **tempo di installazione** è da «pubblicata il» al giorno in cui WatchGuard non segnala più la patch. Le patch sparite perché il PC è uscito da WatchGuard non contano: non sono installazioni.

**Alert**: con l'interruttore «Segnala le patch oltre il termine» acceso, a ogni ciclo del SOC nasce un alert per ogni patch oltre il termine (uno per patch e termine, con i PC nel dettaglio): severità alta per KEV e critiche, media per le altre. Si chiude da solo quando la patch non manca più oltre il termine su nessun PC. Ogni apertura e chiusura va nell'audit sigillato. L'interruttore è **spento di default**: alla prima accensione ogni patch vecchia apre subito il suo alert, quindi conviene guardare prima la pagina.

Gli stessi numeri sono nel **report periodico** (sezione «Patch (WatchGuard)», anche nel PDF), nel controllo **8.8** della pagina Conformità ISO 27001 e nel **pacchetto mensile** di evidenze, e nel riquadro **Patch** della scheda asset.

### Librerie del portale

Pagina **Dispositivi › Librerie del portale**: le vulnerabilità note nelle librerie Python installate nel portale stesso (il server di NOVICROM HUB). Ogni mattina alle **06:50** le librerie dell'ambiente Python del portale si confrontano con il database pubblico **OSV** (osv.dev), lo stesso che usa pip-audit nel controllo prima del pacchetto. Così una vulnerabilità pubblicata dopo il deploy si vede il giorno dopo, non al pacchetto successivo.

- **Da aggiornare**: una riga per libreria con la versione installata, la gravità più alta, le vulnerabilità (link al bollettino OSV) e **«Aggiornare almeno a»**, la versione più bassa che le corregge tutte. Le voci che OSV dà con più codici (PYSEC, GHSA, CVE dello stesso problema) contano una volta.
- **Gravità**: quella del bollettino GitHub (GHSA) se c'è, altrimenti il CVSS della CVE già letta da NVD; senza nessuna delle due è «Media» con la nota «gravità non classificata».
- **Risolte negli ultimi 90 giorni**: si chiudono da sole quando la libreria è aggiornata **nell'ambiente del portale** (`pip install -r requirements.txt` e riavvio). Cambiare solo `requirements.txt` non basta: il controllo guarda quello che è installato.
- **Alert**: uno per libreria e versione installata, con la severità della vulnerabilità più grave; si chiude da solo dopo l'aggiornamento. Apertura e chiusura vanno nell'audit sigillato.
- **Se OSV non risponde** (server senza accesso a Internet verso api.osv.dev) la lettura va in **errore** in Impostazioni › Letture automatiche e la pagina lo dice: l'elenco resta quello del controllo precedente, non vuol dire «nessuna vulnerabilità».

Interruttori in **Impostazioni › Avvisi e automatismi › Librerie del portale (ISO 27001 8.8)**: «Controlla le librerie del portale ogni mattina» e «Alert per le librerie vulnerabili», tutti e due accesi di default. «Esegui ora» è in Letture automatiche. Le vulnerabilità aperte contano nella Panoramica e nel report periodico come le altre (un dispositivo esposto: il server del portale); nel controllo **8.8** della Conformità ISO 27001 una libreria con gravità alta o critica porta l'esito da «ok» ad «attenzione».

### Patch nella scheda asset

Nella scheda di un PC che WatchGuard conosce c'è il riquadro **Patch** (accanto a «Vulnerabilità»; solo per chi vede il Security Center): patch mancanti, oltre il termine, con l'installazione fallita e chiuse nell'ultimo anno con le CVE corrette. La tabella elenca le prime 10 patch mancanti con classe, data di pubblicazione e termine («entro il …» o «scaduto da N gg»); sotto, le patch chiuse nell'ultimo anno con i giorni dalla pubblicazione, le CVE e il motivo. «Storico completo di questo PC» apre Patch installate già filtrata sul PC.

### Alert e ticket automatici

Quando l'inventario dice che un PC ha una versione vulnerabile di una CVE **critica** (CVSS 9 o più) o **sfruttata attivamente** (CISA KEV), il SOC apre un alert critico, senza aspettare che lo segnali Defender.

- **Un alert per CVE**, con il numero di PC impattati e il prodotto nel titolo. Se al giro dopo altri PC risultano impattati, l'alert si aggiorna; non ne nasce uno nuovo.
- L'alert nasce solo per i PC che **diventano** impattati: lo stesso PC già segnalato non lo fa ripartire. Se chiudi l'alert e il PC resta vulnerabile, l'alert non si riapre da solo finché non si aggiunge un altro PC.
- **Ticket di rimedio**: si apre insieme all'alert. Se per quella CVE c'è già un ticket aperto (per esempio nato da Defender), l'alert si collega a quello, senza un secondo ticket.
- Le notifiche sono quelle degli altri alert e ticket, sugli stessi canali.
- Le CVE alte, medie e basse non aprono alert: si guardano nella pagina **Vulnerabilità**.

Si accende e si spegne in **Configurazione › Avvisi e automatismi › Impatto CVE sugli asset**: «Apri un alert quando un PC risulta impattato» e «Apri anche il ticket di rimedio». Arrivano accese, ma funzionano solo con l'arricchimento CVE acceso e un inventario importato.

### Chiusura con prove

«Come so che l'aggiornamento (patch management o Windows Update) ha davvero corretto la CVE segnalata, così che l'alert si chiuda da solo?» Il giro si chiude così.

**Il titolo segue i PC.** A ogni ricalcolo degli impatti l'alert dice quanti PC restano: «CVE-X sfruttata attivamente (CISA KEV): 3 PC su 5 ancora con versione vulnerabile di Prodotto». Ogni PC che esce lascia una voce nella timeline dell'alert, con quello che si sapeva in quel momento: «PC-01: aggiornato da 1.2 a 1.4 il 27/10/2026, prove: inventario del 27/10/2026 + patch WatchGuard «…» installata (aggiornato e confermato)».

**Il riquadro «Chiusura con prove»** nella scheda dell'alert mostra lo stato di ogni PC che è stato esposto:

| Stato | Significato | Conta per la chiusura? |
| --- | --- | --- |
| **Ancora vulnerabile** | l'inventario vede ancora la versione nel range | No |
| **Da verificare** | versione non confrontabile o inventario più vecchio di 30 giorni | No |
| **Aggiornamento rilevato, in attesa di conferma** | una prova sola (per esempio solo l'inventario), oppure una prova contraria (patch WatchGuard ancora mancante, Defender che la vede ancora) | No |
| **Aggiornato e confermato** | almeno **2 prove concordi** | Sì |
| **Non verificabile** | PC non più nell'inventario o non visto da N giorni: non si può dire se è corretto | No, finché una persona non lo esclude |
| **Escluso dalla verifica** | una persona con il permesso di configurazione lo ha escluso, con motivo (es. PC dismesso) | Non blocca |

Le **prove** sono tre, e ne servono due concordi per ogni PC (una per le CVE non critiche, che però oggi non aprono alert):

1. **Inventario recente** (export WatchGuard o lettura Defender degli ultimi 30 giorni): il programma c'è in una versione fuori dal range vulnerabile, oppure è stato disinstallato. È la riga «Programma aggiornato» / «disinstallato» di «Risolte negli ultimi 90 giorni».
2. **Patch WatchGuard** (con «Leggi le patch mancanti» acceso): la patch che corregge quella CVE su quel PC non è più tra le mancanti, oppure il task di installazione dice «Installata». Se è **ancora mancante**, il PC resta in attesa anche se l'inventario dice il contrario.
3. **Defender** (con «Confronta le CVE con Defender» acceso): nell'ultima lettura Defender non segnala più quella CVE su quel PC. Vale solo per i PC che Defender conosce. Se **la vede ancora**, il PC resta in attesa.

Quando **tutti** i PC sono «Aggiornato e confermato» (o esclusi da una persona) e nessuno è impattato, da verificare o non verificabile, la regola **CVE critica corretta con prove** chiude l'alert come Risolto, con il motivo e il rimando alle prove PC per PC nella timeline. Il **ticket** della CVE si chiude a sua volta se non ha attività aperte (come per gli altri rientri). Gira dopo ogni ricalcolo degli impatti e nel ciclo del SOC ogni 15 minuti.

La regola arriva **accesa**: chiude solo con due fonti indipendenti d'accordo su ogni singolo PC, mai per assenza di dati, e lascia tutto scritto nella timeline. Senza la lettura delle patch WatchGuard né il confronto con Defender resta una prova sola (l'inventario): gli alert restano «in attesa di conferma» e li chiude una persona, come prima. Si spegne in **Configurazione › Automatismi di rientro**, oppure tutte insieme con `SECURITY_AUTO_RESOLVE_ENABLED`.

**Escludere un PC dalla verifica.** Un PC non più nell'inventario (dismesso, spento da settimane, uscito dall'azienda) bloccherebbe la chiusura per sempre. Chi ha il permesso di configurazione del SOC lo esclude dal riquadro con il pulsante **Escludi dalla verifica** e un motivo obbligatorio; l'azione resta nella timeline con nome e motivo, e si può annullare. Si esclude solo un PC «Non verificabile»: un PC ancora vulnerabile o in attesa non si può escludere.

**Recidiva.** Se entro **90 giorni** dalla chiusura automatica la versione vulnerabile ricompare su un PC (reinstallazione, ripristino di un'immagine), non nasce un alert nuovo senza storia: si **riapre lo stesso alert**, con il titolo «Recidiva · …», il motivo («versione vulnerabile ricomparsa su 1 PC 12 giorni dopo la chiusura automatica del …») e la voce in timeline. Le chiusure fatte a mano non contano come recidiva: in quel caso nasce un alert nuovo.

**Dalla segnalazione alla correzione.** In cima alla pagina **Vulnerabilità** il riquadro con i numeri degli ultimi 90 giorni: PC corretti, giorni medi da «esposto dal» alla correzione (anche solo per le CVE critiche o sfruttate), alert CVE chiusi con la quota di chiusure automatiche e di chiusure a mano, recidive, alert ancora aperti.

### Tempi di correzione

La norma ISO/IEC 27001:2022 (controllo 8.8, gestione delle vulnerabilità tecniche) chiede che ogni vulnerabilità venga corretta **entro un tempo stabilito** in base al rischio, e che si sappia dimostrare quando è stata vista, quando è stata corretta e cosa si è deciso nel frattempo. Il SOC lo fa da solo.

Ogni PC esposto (esito **Impatta**) ha un **termine di correzione** che parte da «esposto dal» e dipende dalla **classe** della CVE:

| Classe | Quando | Termine (di serie) |
| --- | --- | --- |
| **Sfruttata (CISA KEV)** | la CVE è nel catalogo CISA delle vulnerabilità sfruttate | la data chiesta da CISA, se c'è; altrimenti **14 giorni** |
| **Critica** | CVSS 9 o più | **15 giorni** |
| **Alta** | CVSS 7 o più | **30 giorni** |
| **Media** | CVSS 4 o più | **90 giorni** |
| **Bassa** | sotto 4, o senza punteggio | **180 giorni** |

I giorni si cambiano in **Impostazioni › Avvisi e automatismi › Vulnerabilità: tempi di correzione (ISO 27001 8.8)**. Gli esiti «da verificare» non hanno termine: prima si decide se impattano (a mano o accettando una proposta dell'AI).

**Stiamo migliorando?** Il riquadro «Tempi di correzione» della pagina Vulnerabilità si apre con tre tessere: **PC corretti nel termine** (percentuale, verde da 80%, rosso sotto 50%), **giorni mediani** da «esposto dal» alla correzione (metà dei PC corretti ci ha messo meno di così: la mediana non si sposta per un solo PC dimenticato per mesi, la media sì) e **PC oltre il termine** sulle esposizioni aperte. Sotto il numero, la variazione rispetto ai 90 giorni precedenti (▲ ▼, verde = meglio, giallo = peggio; «senza confronto» se in uno dei due periodi non ci sono correzioni; il periodo esatto compare passando il mouse) e una linea delle ultime 8 settimane. Nella tabella per classe la colonna **Nel termine** è una barra verde/rossa con «nel termine / corrette» e la colonna **Mediana** dà lo stesso numero per classe.

Dove si vede:

- **Scheda CVE**: il riquadro «Tempi di correzione e accettazione del rischio» dice la classe e i giorni; la colonna **Termine** della tabella degli host dice per ogni PC «entro il …» con i giorni che restano, **«Oltre il termine di N giorni»** o «Rischio accettato fino al …».
- **Pannello laterale della CVE** (catalogo software, scheda asset): in «Cosa fare» la classe e il termine, con quanti PC sono oltre; per ogni PC la riga «Da correggere entro il …» o «Oltre il termine di N giorni».
- **Vulnerabilità**: il riquadro **Tempi di correzione** con, per classe, i PC corretti negli ultimi 90 giorni divisi tra **nel termine** e **in ritardo**, le esposizioni aperte e quelle oltre il termine, più la percentuale complessiva di correzioni nel termine e l'elenco dei PC oltre il termine. Una correzione è «nel termine» se la data della risoluzione (programma aggiornato o disinstallato, vedi «Quando un PC viene aggiornato») non supera il termine calcolato da «esposto dal».

**Cosa succede da solo.** Nel ciclo del SOC (ogni 15 minuti), per ogni PC oltre il termine senza accettazione del rischio attiva nasce l'evento «CVE oltre il termine di correzione» (**uno per CVE, PC e termine**: lo stesso ritardo non lo ripete, un termine nuovo, per esempio dopo una recidiva, sì) e un alert **per CVE**: se la CVE ha già l'alert «PC con versione vulnerabile» il PC oltre il termine si scrive nella sua timeline, altrimenti nell'alert «Oltre il termine di correzione: CVE, N PC», dove ogni PC corretto lascia la riga «PC rientrato nel termine» (vedi Impostazioni e AI › Meno rumore; con «Meno rumore» spento, un alert per CVE, PC e termine come prima). Severità **alta** per le CVE sfruttate o critiche, **media** per le altre. L'alert si chiude da solo quando il ricalcolo degli impatti non vede più esposto nessuno dei suoi PC oppure quando qualcuno accetta il rischio, con il motivo scritto. L'interruttore «Segnala le esposizioni oltre il termine di correzione» arriva **acceso**; la regola facoltativa `cve_sla_scaduta` in Configurazione › Regole alert permette di cambiarne la severità.

### Accettazione del rischio

Quando la correzione non si può fare nel termine (il produttore non ha una patch, la macchina comanda un impianto e non si può toccare, il programma gira isolato) la norma chiede un'**eccezione formale**: chi decide, perché, con quali misure compensative e fino a quando. Nel SOC è l'**accettazione del rischio**.

- Si crea dalla **scheda CVE**, riquadro «Tempi di correzione e accettazione del rischio», pulsante **Accetta il rischio** (o per più PC insieme, selezionandoli nella tabella «Esito per host»): solo chi ha il **permesso di configurazione** del SOC. Si sceglie il PC (o **tutti i PC**), si scrive il **motivo** (almeno 20 caratteri, obbligatorio), le **misure compensative** (facoltative ma consigliate: rete isolata, funzione disattivata, monitoraggio rafforzato) e la **scadenza**, al massimo **12 mesi**: dopo va riesaminata, non si rinnova da sola.
- Finché è **attiva**, il PC non fa scattare l'alert «oltre il termine»; se l'alert era già aperto si chiude da solo con il riferimento all'accettazione. Nelle pagine il PC compare come «Rischio accettato fino al …» e nel riquadro Tempi di correzione conta tra le esposizioni «con rischio accettato».
- **30 giorni prima** della scadenza (si cambia in Impostazioni) nasce un alert di attenzione «Accettazione del rischio in scadenza fra N giorni». Alla **scadenza** l'accettazione finisce da sola: alert «Accettazione del rischio scaduta: … torna da correggere» e, se il PC è ancora esposto oltre il termine, l'alert «oltre il termine» riparte. L'interruttore «Alert quando un'accettazione del rischio sta per scadere o è scaduta» arriva acceso.
- La pagina **Dispositivi › Rischi accettati** elenca tutte le accettazioni con lo stato (**attiva**, **scaduta**, **revocata**), la scadenza (evidenziata se entro 30 giorni), chi ha approvato, motivo e misure. **Revoca** (con motivo) la chiude prima: l'esposizione torna a contare subito.
- Non si può accettare due volte lo stesso ambito (stessa CVE, stesso PC o «tutti i PC») finché la prima è attiva, né accettare il rischio su un PC che non è tra quelli valutati per la CVE.

**Traccia sigillata.** Creazione, revoca, promemoria e scadenza delle accettazioni, gli alert «oltre il termine» e i loro rientri, ogni chiusura automatica degli alert e dei casi, l'esclusione di un PC dalla verifica, le recidive e anche le decisioni a mano sugli alert e sui casi (presa in carico, chiusura, falso positivo, silenzio, riapertura) finiscono nel **registro audit del portale** (modulo «security»), oltre che nella timeline del SOC. Il registro viene sigillato ogni mese e non si modifica: è ciò che si mostra in un audit ISO 27001 per dimostrare chi ha deciso cosa e quando. In ogni riga restano solo identificativi, regola, motivo, riferimento alla prova e chi ha deciso («system» per gli automatismi): mai il contenuto delle mail o dati personali.

## Software non conforme

Nel modulo Asset il **Catalogo software** raccoglie le decisioni dell'azienda su ogni programma dell'inventario (i nomi diversi dello stesso programma sono una riga sola e il dettaglio mostra le versioni presenti): **Consentito**, **Da rimuovere**, **Non autorizzato**, ed eventualmente una **versione minima**. Il SOC confronta l'inventario con queste decisioni dopo ogni import dell'inventario e ogni modifica al catalogo.

- **Un alert per software e per caso**: software non autorizzato (severità alta), software da rimuovere, versione sotto la minima (solo per i software consentiti). Il titolo dice il prodotto e su quanti PC è.
- L'alert nasce solo quando **nuovi** PC entrano nel caso; se altri PC si aggiungono dopo, lo stesso alert si aggiorna.
- Una versione scritta in modo non confrontabile (per esempio «2023 R2») non viene mai contata come vecchia.
- Quando il software sparisce dall'inventario l'alert **non** si chiude da solo: lo chiude chi ha verificato la rimozione.
- Riepilogo nella pagina **Vulnerabilità**, riquadro **Software non conforme**, con il link al catalogo già filtrato.

Si accendono e si spengono in **Configurazione › Avvisi e automatismi › Software non conforme** (tre interruttori, accesi di default). Senza software classificati nel catalogo non nasce nessun alert.

**Programma mai visto prima.** Un programma che compare per la prima volta su un PC dell'azienda e che non ha una decisione nel catalogo (né sul programma né da una regola per produttore) è un possibile caso di shadow IT: dopo ogni import nasce **un alert per programma**, severità avviso, una volta sola («Programma nuovo: X su N PC»), raggruppato in Proposte AI come gli altri. Si chiude da solo quando il programma riceve una decisione nel catalogo o sparisce da tutti i PC. Un programma è «nuovo» per 14 giorni dalla prima comparsa (**Un programma è «nuovo» per**, stessa sezione delle impostazioni); una versione nuova di un programma già visto non conta. Nel Catalogo software gli stessi programmi hanno l'etichetta «nuovo dal gg/mm» e il filtro **Nuovi**.

## Domande frequenti

**Ho disattivato tre volte lo stesso alert ma la regola non è nata.** Controlla nella scheda dell'alert il conteggio e il motivo: probabilmente l'alert è critico, riguarda una CVE sfruttata o una minaccia, il tipo è escluso, oppure nessuna delle tre disattivazioni è stata fatta da chi ha il permesso di configurazione.

**Una soppressione appresa nasconde un problema vero.** Riapri l'alert o promuovi l'evento soppresso: la regola si spegne subito e il conteggio riparte. Per spegnere del tutto la funzione: Configurazione › Avvisi e automatismi › Soppressione appresa.

**Un PC risulta «da verificare» per tutte le CVE.** L'inventario di quel PC è più vecchio di 30 giorni (la soglia si cambia in Impostazioni): carica un export aggiornato.

**Tutti i PC sono aggiornati ma l'alert della CVE non si chiude.** Guarda il riquadro «Chiusura con prove» nella scheda dell'alert: dice per ogni PC cosa manca. Di solito è una prova sola (accendi la lettura delle patch WatchGuard o il confronto con Defender, oppure chiudi a mano dopo verifica), oppure un PC «non verificabile» che non compare più nell'inventario: se è dismesso, escludilo dalla verifica con il motivo.

**La dashboard Vulnerabilità è vuota.** Verifica che l'arricchimento sia acceso in Impostazioni, che sia stato importato almeno un inventario e che i software principali abbiano il CPE confermato. Il job gira ogni ora.
