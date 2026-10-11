# Backup, VPN, KPI e asset

Le pagine del gruppo **Analisi** del menu SOC: cosa mostrano e come si leggono. Le vulnerabilità hanno un capitolo a parte: [Automatismi e vulnerabilità](/soc/docs/12-automatismi-e-vulnerabilita/#impatto-cve-sugli-asset).

## Backup

La pagina **Backup** legge i report dei backup già arrivati (Synology Active Backup, Veeam). Scegli il periodo: 7, 30 o 90 giorni.

### In alto

- **Esecuzioni riuscite**: percentuale e conteggio di riuscite, con avvisi e fallite.
- **PC e server protetti**: quanti dispositivi compaiono nei report e quanti sono **senza backup riuscito** oltre la soglia (3 giorni di default, si cambia in Impostazioni).
- **Job**: quanti job e quanti **job attesi non arrivati**. I job attesi si definiscono in Config › Backup.
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

## Asset

I report citano dei dispositivi (nei backup, nella protezione endpoint). La pagina **Asset** serve a collegarli agli **asset del portale**, così sulla scheda dell'asset compaiono backup, rilevamenti, minacce e vulnerabilità.

- Il collegamento viene **proposto** quando il nome è identico a quello di un asset: lo confermi tu con **Conferma**, oppure tutti insieme con **Conferma tutti … con nome identico**.
- I filtri **Da collegare**, **Collegati** e **Tutti** aiutano a finire il lavoro.
- **Scollega** se il collegamento è sbagliato.

Un dispositivo non collegato funziona comunque nel SOC (scheda PC, backup, alert); manca solo il riepilogo sulla scheda dell'asset.

## Stato elaborazione

**Elaborazione** (gruppo Gestione) dice se i dati stanno arrivando. Il SOC lavora da solo: ogni 15 minuti legge le caselle mail, riconosce i report, applica le regole e calcola i KPI. Di solito non c'è niente da premere.

- **Lettura automatica attiva** con l'ora del prossimo giro: tutto in ordine. Se compare **Lettura automatica NON registrata**, va registrato lo schedule `security_cycle` dalla Centrale di comando.
- **Da guardare**: mail o allegati che non sono stati elaborati, con il motivo. Dopo aver corretto un parser o una configurazione, **Config › Parser › Rielabora** li ripropone.
- **Esegui a mano**: solo per verifiche. Per leggere subito le caselle usa **Leggi ora** in Caselle mail.
