# Registro accessi (log dei server e amministratori di sistema)

Il Registro accessi raccoglie i log dei server Windows, dei controller di dominio, di ESXi e vCenter, degli switch, del firewall e del NAS. Tutto finisce in un **archivio sigillato** che vale come registro degli accessi degli amministratori di sistema (provvedimento del Garante del 27/11/2008) e come evidenza per la ISO/IEC 27001 (controlli 5.18, 5.28, 8.2, 8.15, 8.16, 8.17). Sostituisce un prodotto di log management esterno.

Si apre dal menu del SOC: **Registro accessi**.

## Panoramica

In alto lo stato della raccolta:

- **Raccolta attiva** (pallino verde): il raccoglitore ha dato un segnale negli ultimi 5 minuti. Accanto: righe archiviate oggi e se il syslog è in ascolto.
- **Raccoglitore fermo** (rosso): nessun segnale da oltre 5 minuti. Finché non riparte i log non vengono raccolti; il periodo diventa un'interruzione.
- **Raccoglitore mai partito** (giallo): va installato come servizio (vedi «Fonti e impostazioni»).
- **Raccolta spenta**: l'interruttore «Raccolta accesa» in Fonti è spento.

Il riquadro **Come iniziare** elenca i passi che mancano perché il registro valga per il Garante e la ISO 27001, ognuno con il pulsante «Vai». Sparisce quando sono tutti fatti.

I cinque riquadri numerici (accessi degli amministratori, accessi non riusciti, eventi critici nelle ultime 24 ore, fonti che rispondono, stato dell'archivio) si cliccano e aprono l'elenco filtrato. «Da guardare» mostra gli ultimi eventi importanti; «Continuità della raccolta» le interruzioni in corso.

## Eventi

Gli eventi importanti estratti dall'archivio. Viste rapide: **Accessi degli amministratori**, **Fuori orario**, **Non riusciti**, **Modifiche ad account e gruppi**, **Critici**. Filtri per periodo (da 24 ore a un anno), tipo di evento, fonte e testo (account, server, IP).

Cosa entra nell'elenco (il resto resta solo nell'archivio):

- accessi alla console, in desktop remoto, sblocchi della sessione; gli accessi di rete solo per gli account amministratori;
- accessi non riusciti (con il motivo: password sbagliata, utente inesistente, account bloccato…), anche Kerberos e NTLM dei controller di dominio;
- account creati, eliminati, abilitati, disabilitati, bloccati, password reimpostate;
- aggiunte e rimozioni dai gruppi (critico se il gruppo è di amministratori: Domain Admins, Administrators, Enterprise Admins, Backup Operators…);
- registro eventi cancellato, criteri di audit modificati, servizi installati, attività pianificate create, orologio cambiato, avvii e arresti;
- da syslog: accessi SSH e alla console di gestione (ESXi, vCenter, switch Cisco e Aruba, firewall WatchGuard, NAS Synology), accessi rifiutati, SSH o shell abilitati, comandi `sudo`.

Etichette: **admin** = account di un amministratore di sistema o con privilegi; **fuori orario** = fuori dall'orario di lavoro impostato in Fonti, o nel fine settimana. Lo stesso accesso ripetuto entro 10 minuti compare una volta sola (nell'archivio restano tutti).

Clic sulla data di una riga: dettaglio con l'**evento originale** com'è stato ricevuto (campi del registro di Windows o testo del syslog) e gli altri eventi dello stesso account. La lettura della riga d'archivio resta nell'audit del portale.

## Amministratori di sistema

L'elenco richiesto dal Garante: nome, dipendente o fornitore esterno (con la società), **account usati** (separati da virgola), sistemi che amministra, data di nomina, **lettera di nomina in PDF**, prossima revisione, data di revoca. Un amministratore non si cancella: quando smette si mette la data di revoca, così resta nella verifica dell'anno.

Gli account scritti qui servono a riconoscere i loro accessi (etichetta «admin») e a trovare chi ha privilegi senza nomina.

## Account AD

Gli account di Active Directory letti via LDAP ogni 6 ore (lettura «Account di Active Directory» in Impostazioni › Letture automatiche, con «Esegui ora»), in sola lettura, con la stessa connessione LDAP del login. Ogni account è abbinato alla persona dell'anagrafica per email o nome utente.

Il riquadro **Da sistemare**:

- **Ex dipendenti con l'account ancora attivo** (critico): persona cessata in anagrafica, account abilitato. Con l'interruttore acceso diventa anche un alert del SOC.
- **Amministratori senza nomina**: account in un gruppo di amministratori (anche tramite gruppi annidati) ma non nell'elenco degli amministratori di sistema.
- **Account senza una persona**: da abbinare o da segnare come «Account di servizio».
- **Account di servizio senza responsabile**.
- **Account non usati da oltre 90 giorni**.
- **Password che non scadono** (persone).
- **Password di krbtgt più vecchia di 180 giorni**.

Chi configura il SOC può cambiare il tipo (Persona, Account di servizio, Da classificare) e scrivere il responsabile.

## Verifica annuale

Una volta l'anno il titolare verifica l'operato degli amministratori (Garante, punto 4.4). Si sceglie l'anno; la pagina calcola la **lista di controllo**:

- elenco degli amministratori presente e ogni nomina allegata;
- nessun account con privilegi senza nomina;
- registro completo per l'anno (giorni sigillati su giorni attesi) e archivio integro;
- seconda copia dell'archivio;
- interruzioni di almeno 30 minuti giustificate;
- nessuna cancellazione dei registri né modifica dell'audit.

Sotto: per ogni amministratore accessi, accessi fuori orario, non riusciti, modifiche sensibili e sistemi più usati; le modifiche critiche; lo stato dell'archivio. **Scarica il PDF** produce il verbale con l'impronta SHA-256 del riepilogo. Chi verifica scrive data, nome, esito (Conforme, Conforme con rilievi, Non conforme), rilievi e azioni e preme **Registra la verifica**.

## Archivio e integrità

Ogni giorno ha un file (`registro-AAAA-MM-GG.jsonl`, compresso a fine giornata) in cui ogni riga porta l'impronta della riga prima. Dopo mezzanotte il giorno riceve un **sigillo** legato a quello del giorno prima: cambiare, togliere o aggiungere una riga, o un giorno intero, rompe la catena.

- **Integro**: ricalcolo riuscito. **Non integro**: va spiegato subito (alert del SOC se acceso). **Da verificare**: non ancora ricontrollato.
- Ogni giorno vengono ricontrollati i 7 giorni verificati da più tempo; **Verifica gli ultimi 2 mesi adesso** fa il controllo su richiesta.
- **Seconda copia**: file e sigillo copiati su una cartella di rete e/o su SharePoint (cartella dell'audit, sottocartella «registro-log»).
- **File** e **Sigillo**: download per l'auditor (solo chi configura, resta nell'audit). Le regole per rifare il calcolo senza il portale sono in «Come si verifica senza il portale».
- Oltre la **conservazione** (minimo 6 mesi, consigliati 12) il file viene eliminato; il sigillo resta con la data di eliminazione.

**Interruzioni della raccolta**: raccoglitore fermo, fonte senza messaggi oltre la soglia, lettura non riuscita, eventi sovrascritti sul server prima della lettura, messaggi scartati per eccesso, file riparato dopo un arresto. Ognuna si giustifica con una frase (es. «manutenzione programmata del server»): entra nella verifica annuale.

## Server e virtualizzazione

vCenter (o i singoli host ESXi, se non c'è vCenter) e i controller iLO/iDRAC dei server fisici, letti ogni ora in sola lettura. Per ognuno si vede l'ultima fotografia e le cose da guardare:

- ESXi/vCenter: host non connessi o con allarmi, **SSH o ESXi Shell accesi**, NTP non configurato, lockdown disattivato, datastore sotto il 15% libero, **snapshot più vecchi di 3 giorni**;
- iLO/iDRAC: salute dell'hardware diversa da «OK», server spento.

Le versioni di ESXi, vCenter e dei firmware dei controller entrano nell'inventario software del SOC (fonte «Server e virtualizzazione») e passano dal calcolo delle CVE. Utente consigliato: ruolo «Sola lettura»; password salvata cifrata.

## Indagini: file, stampe e USB

Accessi ai file dei file server, stampe e dispositivi USB sono **controlli sull'attività delle persone** (art. 4 dello Statuto dei lavoratori, GDPR). Per questo:

- si accendono sulle fonti solo dopo la conferma **«Informativa ai dipendenti e accordi verificati»** in Fonti › Impostazioni (con un riferimento: documento, data, chi ha verificato). Chi conferma e quando resta salvato; togliendo la spunta si spengono su tutte le fonti;
- vengono raccolti e sigillati nell'archivio come il resto, ma **non compaiono** in Panoramica, Eventi, dettagli o verifica annuale;
- si consultano **solo dentro un'indagine** (Registro accessi › Indagini, solo chi configura il SOC), da aprire quando è stato rilevato un problema, ad esempio un sospetto furto di file o di proprietà intellettuale.

**Aprire un'indagine**: motivo (almeno una frase), riferimento (es. numero dell'incidente), persone (account; vuoto = tutti), periodo, testo facoltativo da cercare nel percorso del file, nella stampante o nel dispositivo. Dentro l'indagine: riquadri con accessi ai file (e quante eliminazioni), stampe (e pagine), dispositivi USB; elenco con data, chi, cosa, sistema; ogni riga apre l'evento originale sigillato (la prova da allegare); **Scarica CSV**. Apertura, consultazioni, export e chiusura restano nell'audit del portale. **Chiudi l'indagine** con l'esito: da quel momento i dati non si consultano più da lì.

Cosa si raccoglie:

- **File** (scheda della fonte, «Accessi ai file»): *Modifiche, eliminazioni e permessi* (consigliato) oppure *Anche le letture*. Eventi 4663 e 4670 dei file server; file temporanei di Office, `.tmp`, `desktop.ini`, `thumbs.db` e collegamenti esclusi. Sul server servono il controllo «File system» nella GPO e la voce di controllo sulle cartelle (istruzioni nella pagina Fonti).
- **Stampe** («Stampe»): evento 307 del registro PrintService/Operational del server di stampa: chi, da quale PC, su quale stampante, quante pagine. Il **nome del documento** si salva solo con «Registra anche il nome del documento»; spento, non finisce nemmeno nell'archivio.
- **USB** («Dispositivi USB»): chiavette e dischi esterni (marca, modello, numero di serie, capacità) dal registro Partition/Diagnostic e dall'evento 6416; tastiere e mouse esclusi. Le chiavette si collegano ai PC: si raccolgono con una sottoscrizione WEF dai PC verso il server del portale.

Alert nel SOC, senza nomi di file: **file eliminati o modificati a raffica** dallo stesso account (soglia in 10 minuti, default 200: furto, cancellazione o ransomware) e **dispositivo USB collegato a un server**. Da lì si apre l'indagine.

## Fonti e impostazioni

**Fonti**: da dove arrivano i log.

- **Server Windows (lettura diretta)**: il server del portale legge il registro Security e System del server indicato, senza agent. Serve l'account del raccoglitore nel gruppo **Event Log Readers** e la regola firewall «Gestione remota registro eventi (RPC)». «Cosa leggere»: **Accessi e amministrazione** (consigliato) o **Tutto il registro**.
- **Eventi inoltrati (WEF)**: i server inoltrano a questo server con una sottoscrizione di Windows Event Forwarding; una sola fonte per tutti.
- **Syslog**: ESXi, switch, firewall, NAS e server Linux mandano i messaggi al server del portale. Si indicano gli indirizzi IP degli apparati: i messaggi da altri indirizzi vengono ignorati e contati («indirizzi non configurati»).

Pulsante **Prova**: legge l'ultimo evento di ogni registro senza archiviare nulla e dice cosa non va (accesso negato, server non raggiungibile). **Avvisa se muta per più di (ore)**: oltre questa soglia senza messaggi nasce l'interruzione «Fonte senza messaggi».

**Impostazioni**: raccolta accesa, conservazione in mesi, cartella dell'archivio, seconda copia (cartella di rete, SharePoint), syslog (indirizzo, porta, TCP), orario di lavoro. Le modifiche arrivano al raccoglitore entro 5 minuti.

**Il raccoglitore come servizio di Windows**: processo sempre acceso come il qcluster (task `\PortaleNovicrom\RegistroLog_<ambiente>`, stesso account), riparte da solo dopo riavvii e aggiornamenti. Installazione: `deployment\scripts\install-registro-log-task.ps1`. Il controllo dell'infrastruttura `registro_log` (Centrale di comando) avvisa se si ferma o se l'archivio non è integro.

## Alert nel SOC

In Impostazioni › Avvisi e automatismi, sezione **Registro accessi**: interruttore generale (spento all'inizio) e uno per tipo: registro cancellato, audit modificato, aggiunta a un gruppo di amministratori, account AD attivo di un ex dipendente, account creato, account bloccato, servizio installato, configurazione di un apparato modificata, accesso di un amministratore fuori orario, accessi non riusciti a raffica (soglia in 15 minuti), raccolta interrotta o archivio non integro. Il controllo gira ogni 5 minuti; ogni evento apre al massimo un alert.

## Problemi frequenti

- **«Accesso negato al registro eventi»**: l'account del raccoglitore non è in «Event Log Readers» del server (sui controller di dominio, il gruppo di dominio).
- **«Server non raggiungibile per la lettura remota (RPC)»**: nome sbagliato o firewall del server senza la regola «Gestione remota registro eventi».
- **Interruzione «Eventi sovrascritti prima della lettura»**: il registro Security del server è troppo piccolo; portarlo ad almeno 1 GB.
- **Syslog: nessun messaggio**: porta non aperta nel firewall di Windows del server del portale, oppure indirizzo dell'apparato diverso da quello scritto nella fonte (vedi «indirizzi non configurati»).
- **Account AD vuoti**: connessione LDAP del portale non configurata nel Setup Wizard.
