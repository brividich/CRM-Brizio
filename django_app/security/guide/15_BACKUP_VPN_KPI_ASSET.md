# Backup, VPN, KPI e asset

Le pagine del gruppo **Analisi** del menu SOC: cosa mostrano e come si leggono. Le vulnerabilità hanno un capitolo a parte: [Automatismi e vulnerabilità](/soc/docs/12-automatismi-e-vulnerabilita/#impatto-cve-sugli-asset).

## Backup

La pagina **Backup** legge i report dei backup già arrivati (Synology Active Backup, Veeam). Scegli il periodo: 7, 30 o 90 giorni.

### In alto

- **Esecuzioni riuscite**: percentuale e conteggio di riuscite, con avvisi e fallite.
- **PC e server protetti**: quanti dispositivi compaiono nei report e quanti sono **senza backup riuscito** oltre la soglia (3 giorni di default, si cambia in Impostazioni).
- **Job**: quanti job e quanti **job attesi non arrivati**. I job attesi si definiscono in Configurazione › Backup.
- **Dati trasferiti** e **durata media**.

### Da controllare

L'elenco delle cose da sistemare: job attesi mancanti, PC con l'ultimo backup fallito, PC senza un backup riuscito recente. Se è vuoto, tutti i PC hanno un backup riuscito recente.

### Per PC e server

Una riga per dispositivo, con in cima i casi peggiori. La **striscia** mostra le ultime esecuzioni, dalla più vecchia a sinistra alla più recente a destra, con i colori della legenda (riuscito, con avvisi, fallito). Selezionando più PC, **Apri un ticket per questi PC** crea un solo ticket per tutti.

Un clic sul nome apre la **scheda PC** (backup, alert, vulnerabilità e protezione di quel dispositivo). **Log completo** elenca ogni esecuzione con filtri per esito, job, periodo e PC.

### Una cosa da sapere

- **Veeam** dà l'esito di ogni singola macchina.
- **Synology Active Backup** dà solo l'esito del job intero: tutti i PC del job ne ereditano l'esito e la pagina lo segnala con «esito del job». Un job fallito per un solo PC fa risultare fallito anche gli altri.

Se un PC non compare, il report del job non lo elenca: controlla la configurazione del job sul NAS o su Veeam.

### Lettura diretta da Veeam

Con la lettura dall'API di Veeam accesa ([Impostazioni](/soc/docs/16-impostazioni-e-ai/#backup-letti-direttamente-da-veeam)) compare il riquadro **Lettura diretta da Veeam**: stato del collegamento («collegata», «errore» con il motivo), esito dell'ultimo giro e lo **spazio libero di ogni repository**, dal più pieno. Le righe sotto la soglia sono evidenziate e hanno un alert «Repository di backup quasi pieno».

### Prove di ripristino

Un backup vale solo se si riesce a ripristinare (ISO 27001 8.13). In **Backup › Prove di ripristino** si registra ogni prova: data, sistema, job, cosa è stato ripristinato (file, cartella, macchina intera, database), esito **Riuscita** o **Fallita**, durata, chi l'ha fatta, note e un allegato facoltativo (verbale, schermata). In alto: ultima prova riuscita, entro quando serve la prossima (cadenza di **90 giorni** di default, in Impostazioni) e se siamo **in ritardo**.

- Prova **fallita**: il SOC apre da solo un alert alto «Prova di ripristino fallita» collegato alla prova.
- Prova **in ritardo** (o mai fatta): con l'avviso acceso in [Impostazioni](/soc/docs/16-impostazioni-e-ai/#avvisi-automatici) parte un promemoria, uno per scadenza.

## Accessi VPN

**Accessi VPN** raccoglie ogni accesso consentito o negato letto dai report di autenticazione del firewall. Il tipo distingue VPN, accessi al firewall e rete Guest.

- I numeri in alto sono confrontati con il periodo precedente (▲ in aumento, ▼ in calo).
- **Accessi per giorno**: un clic su un giorno lo seleziona e confronta con il giorno prima.
- **Accessi per ora**: le ore notturne sono evidenziate.
- **Utenti più attivi** e **IP di origine**: un clic filtra il registro.
- **Registro accessi**: utente, IP, accesso, uscita, durata, tipo. Filtri per utente, IP, esito, tipo e date.

### I segnali «Da controllare»

| Segnale | Quando compare | Cosa fare |
| --- | --- | --- |
| Accesso riuscito dopo molti rifiuti | Almeno 10 accessi negati da un IP che poi ottiene un accesso | Verificare subito che l'utente sia legittimo |
| Accessi negati da un IP | Almeno 10 rifiuti dallo stesso IP | Possibile tentativo di forza bruta: valutare il blocco dell'IP |
| Accessi in orario notturno | Accessi riusciti tra le 22 e le 6 | Normale per reperibilità o account di servizio, altrimenti da verificare |
| Utente da molti indirizzi | Lo stesso utente da 5 o più IP diversi | Possibili credenziali condivise o in uso da altri |
| Sessioni oltre 8 ore | Sessioni rimaste aperte a lungo | Capire se gli utenti si disconnettono |

Ogni segnale ha un link che filtra il registro sugli accessi interessati.

## KPI e trend

**KPI** mostra gli indicatori ricavati dai report (malware bloccati, PC protetti, backup, accessi VPN, vulnerabilità…) per il periodo scelto, confrontati con il periodo precedente. Con **Fino al** guardi un periodo passato.

Un clic su un indicatore apre il **dettaglio**: andamento giorno per giorno e **Da dove arriva il numero**, cioè i report usati, con l'indicazione di quelli scartati perché doppioni.

Come si contano:

- gli indicatori di **stato** (per esempio «computer senza protezione») mostrano l'**ultimo valore**, mai la somma dei giorni;
- gli indicatori di **quantità** (malware bloccati, accessi) mostrano il **totale del periodo**;
- se lo stesso report arriva due volte, o due report coprono gli stessi giorni, vengono contati una volta sola.

Su tutti i grafici del SOC, passando sopra a un giorno compare il dettaglio; un clic porta all'elenco di quel giorno.

## Dispositivi

**Dispositivi › Elenco** è l'elenco unico dei PC e dei server: una riga per dispositivo con **tutto ciò che lo riguarda**. Prima erano due pagine separate («PC e fonti» e «Asset»): ora sono una sola, e il vecchio indirizzo `/soc/assets/` porta qui. Backup e vulnerabilità sono attività del dispositivo: si vedono sulla sua riga, il dettaglio sta nella sua scheda.

Le colonne:

- **Intune**, **WatchGuard**, **Defender**: ✓ la fonte vede il dispositivo, ✕ non lo vede. WatchGuard e Defender si ricavano dall'inventario software.
- **Backup**: l'esito dell'ultimo backup negli ultimi 30 giorni («Riuscito», «Con avvisi», «Fallito»); in rosso se è fallito o se non c'è un backup riuscito da troppi giorni (la soglia è in Impostazioni). «nessuno» se il dispositivo non compare nei report di backup.
- **Vulnerabilità**: quante CVE lo colpiscono secondo l'inventario software, e quante sono **gravi** (già sfruttate, KEV, o CVSS 9 e oltre). Se il dispositivo è collegato a un asset, il clic apre il pannello con le CVE raggruppate per software.
- **Stato Intune**: «Conforme», oppure i problemi aperti (disco non cifrato, non conforme ai criteri, non si sincronizza).
- **Asset del registro**: il codice dell'asset del portale collegato. **Proposto** vuol dire che c'è un asset con lo stesso IP o lo stesso nome: lo confermi con **Conferma**, oppure tutti insieme con **Conferma le N proposte**; **scollega** se il collegamento è sbagliato. Per i PC di Intune «da collegare» porta alla **riconciliazione dispositivi** del modulo Asset. Collegare e scollegare richiede il permesso di configurazione del SOC.

I filtri **Senza asset**, **Backup ko**, **Con CVE**, **Problemi Intune**, **Non in Intune**, **Senza WatchGuard** e **Senza backup** mostrano accanto quanti dispositivi trovano; il numero è sempre uguale alle righe che si aprono. «Senza backup» non è un errore: non tutti i PC devono avere un backup, è un elenco da controllare.

In cima ci sono i dispositivi con backup ko, poi quelli con problemi Intune, poi quelli con CVE gravi, poi quelli visti da meno fonti. Il dispositivo si riconosce dal nome, senza dominio e senza maiuscole: «PC-01.dominio.local» e «pc-01» sono lo stesso. Gli apparati di rete letti via SNMP non compaiono, e nemmeno i dispositivi non più presenti in Intune.

Un clic sulla riga apre l'anteprima; il nome apre la scheda completa del dispositivo. Le pagine **Backup** e **Vulnerabilità** restano per il lavoro trasversale (job di backup e log, CVE per programma), e ogni dispositivo lì porta alla stessa scheda.

Sotto il nome compare l'**indirizzo IP** letto dal DHCP o dal DNS di Windows Server (prima quello collegato all'asset, poi quello con lo stesso nome) e, se uno switch monitorato vede il suo MAC, **switch e porta**. Il clic sull'IP apre **Rete (IP)** filtrata su quel dispositivo; la ricerca dell'elenco trova anche IP e MAC. Lo stesso dato è in cima alla scheda del dispositivo.

## Rete (IP)

**Dispositivi › Rete (IP)** è la stessa vista di **Asset › Indirizzi IP**: gli indirizzi della rete letti ogni ora dal DHCP e dal DNS di Windows Server, una riga per IP, incrociati con switch, WatchGuard e Intune. I server DHCP e DNS si configurano solo nella pagina Asset.

I riquadri in testa sono anche filtri:

- **Indirizzi attivi**: visti nell'ultima lettura.
- **Non censiti**: nessun asset del registro ha quel MAC, IP o nome. Contano i lease DHCP e gli **IP fissi** presenti solo nel DNS; non contano i record DNS vecchi.
- **Da collegare**: c'è un asset proposto (con il motivo: MAC, IP, nome, nome già collegato in un altro modulo).
- **Senza antivirus**: WatchGuard vede il dispositivo **in rete senza agente**, oppure è un PC del registro (PC, portatile, server, macchina virtuale) che non compare né in WatchGuard né nell'inventario Defender. Senza nessun dato antivirus nel SOC la pagina non giudica.
- **DNS da pulire**: record dinamici fermi da oltre 30 giorni senza lease DHCP.

Ogni riga dice **switch, porta e VLAN** dove si vede il MAC (dalla tabella MAC degli switch letta via SNMP) e **Visto da**: DHCP, DNS, Switch, WatchGuard (rosso se senza agente), Intune. Le azioni sulla riga sono **Conferma** (collega all'asset proposto), **Scollega** e, sui non censiti, **Crea asset** (modulo del nuovo asset già compilato con nome, IP, MAC, switch e porta). Richiedono i permessi degli asset, non quelli del SOC, e restano nell'audit. **Excel** scarica le righe mostrate.

Gli ambiti DHCP mostrano l'occupazione: **Quasi pieno** dal 90%, **Disattivato** se l'ambito non assegna indirizzi.

### Dispositivo sconosciuto nuovo in rete

Quando un MAC **mai visto prima** prende un indirizzo dal DHCP e nessun asset lo spiega, arriva l'evento **Dispositivo sconosciuto nuovo in rete** (sorgente «Portale · accessi», gravità avviso) con IP, MAC, nome, ambito, switch e porta. Regole:

- la prima lettura in assoluto non segnala niente (tutti i MAC sarebbero «nuovi»);
- i MAC **privati** dei telefoni e dei tablet (seconda cifra 2, 6, A o E) non si segnalano: cambiano da soli;
- al massimo **10** per lettura e mai due volte lo stesso MAC.

L'alert si accende o spegne in **Impostazioni › Avvisi e automatismi**, sezione «Eventi di sicurezza del portale».

## Stato elaborazione

**Elaborazione** (voce **Impostazioni**) dice se i dati stanno arrivando. Il SOC lavora da solo: ogni 15 minuti legge le caselle mail, riconosce i report, applica le regole e calcola i KPI. Di solito non c'è niente da premere.

- **Lettura automatica attiva** con l'ora del prossimo giro: tutto in ordine. Se compare **Lettura automatica NON registrata**, va registrato lo schedule `security_cycle` dalla Centrale di comando.
- **Da guardare**: mail o allegati che non sono stati elaborati, con il motivo. Dopo aver corretto un parser o una configurazione, **Configurazione › Parser › Rielabora** li ripropone.
- **Esegui a mano**: solo per verifiche. Per leggere subito le caselle usa **Leggi ora** in Caselle mail.
