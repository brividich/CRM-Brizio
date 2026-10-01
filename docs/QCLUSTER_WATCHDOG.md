# Sorveglianza qcluster

Per il deploy usare la [console PowerShell a menu](../deployment/README_QCLUSTER_CONSOLE.md)
oppure seguire la [guida PDF stampabile](../deployment/docs/Guida_deploy_qcluster.pdf).
Menu 2 prima del deploy, wizard abituale per distribuire/attivare il pacchetto,
menu 9 dopo il deploy. Backup SQL e manutenzione del portale restano manuali;
il recupero Assenze/broker e disponibile separatamente nelle opzioni 7/8.

Il watchdog gira **fuori da django-q**, tramite un task Windows ogni minuto.
Controlla il segnale della sentinella anche quando la coda è vuota. Il broker
salva il segnale nel database ogni 15 secondi; dopo 120 secondi senza un worker
attivo la salute è negativa. Una coda non vuota senza completamenti da 10 minuti
è segnalata come bloccata. Il segnale prova la vitalità della sentinella, non
garantisce il buon esito di ogni processo aziendale: restano gli errori dei job
nel monitoraggio esistente.

In Automazioni → Task pianificati compaiono allarmi per worker/coda e per
watchdog mai eseguito o senza controllo da oltre cinque minuti. La pagina
riflette la situazione all'apertura/ricaricamento. Nessun nuovo permesso o URL.

## Avvisi e recupero

- Segnalazione critica nel monitoraggio, email sincrona agli amministratori
  secondo la cascata esistente `MONITORING_ADMIN_EMAILS` → `ADMINS` → superuser.
  Nessuna email passa dal qcluster sorvegliato.
- Una email iniziale, promemoria secondo `MONITORING_EMAIL_RATE_LIMIT_SECONDS`
  (default 30 minuti, minimo un minuto) e una email al ripristino. Il limite è
  persistente in DB, funziona anche con processi separati e cache locale.
- Invio fallito ritentato al controllo successivo. Destinatari assenti, email
  disabilitate o trasporto fallito sono errori espliciti nel log Windows.
- Task worker `Ready`, heartbeat assente e nessun processo qcluster residuo:
  richiesta di avvio, massimo tre tentativi in 30 minuti. Il prossimo controllo
  verifica l'esito; nessun successo dichiarato solo perché l'avvio è accettato.
- Task `Running` con worker bloccato, processo residuo, accesso ai processi
  insufficiente o DB irraggiungibile: allarme, nessun arresto forzato. La ripresa
  di operazioni con effetti esterni richiede verifica per evitare duplicati.
- Tre minuti di tolleranza quando il task worker è appena partito. Task worker
  disabilitato rispettato e segnalato; nessuna riabilitazione automatica.

## Attivazione sul server

Questi passaggi sono un deploy esplicito; sviluppare il codice non installa task
e non abilita invii sul server. Non registrare il watchdog dentro django-q.

1. Distribuire la release con migrazione Automazioni **0027**, eseguire `migrate`
   nell'ambiente target, aggiornare anche la copia di `start_qcluster.ps1` usata
   dal task esistente e riavviare quel worker. Conservare backup del launcher e
   del database secondo la procedura di deploy. I task devono puntare alla
   stessa radice/ambiente e il broker deve restare `automazioni.broker.FlowBroker`.
2. Verificare il task `\PortaleNovicrom\QCluster_PROD` (oppure `QCluster_TEST`):
   account non interattivo con accesso a DB, filesystem, SMTP e gestione del
   proprio task. Se è stato creato con un nome/percorso diverso, allinearlo
   prima dell'installazione. L'installer non altera il task worker.
3. Da PowerShell amministrativa, nella release:

   ```powershell
   .\deployment\scripts\install-qcluster-watchdog.ps1 -Environment prod -PortaleRoot C:\PortaleNovicrom
   ```

   Per un task worker con logon `Password`, fornire lo stesso account:

   ```powershell
   .\deployment\scripts\install-qcluster-watchdog.ps1 -Environment prod -Credential (Get-Credential)
   ```

   Il watchdog eredita l'identità del worker. Nessuna password viene salvata nei
   file; la credenziale è consegnata a Task Scheduler. `ServiceAccount` e `S4U`
   usano il principal esistente (S4U può non accedere a risorse di rete: verificarlo).
   I principal interattivi sono rifiutati, perché il controllo deve sopravvivere
   al logout. L'installer registra `QClusterWatchdog_PROD/TEST`, crea la sorgente
   Event Log `NovicromQCluster`, copia lo script in `shared/scripts`, conserva
   una copia `.bak` se lo script esiste e pianifica il primo controllo entro un
   minuto. Rieseguirlo a ogni aggiornamento del watchdog.
4. Verificare destinatari e trasporto email **già configurati nel portale**.
   Il flag `MONITORING_NOTIFY_CRITICAL_BY_EMAIL=False` disabilita gli invii e
   produce un errore locale quando servirebbe notificare. Non considerare
   operativo l'allarme email finché non è stata verificata una consegna reale.
5. Collaudare in TEST: salute a coda vuota, arresto del worker, allarme,
   riavvio e ricezione del ripristino. Verificare anche il logout/riavvio Windows.
   Per TEST distribuito si usa `config.settings.prod`: `config.settings.test`
   è riservato ai test SQLite e non deve essere usato sul server.

Controllo manuale in sola lettura, dalla directory `current/django_app`:

```powershell
..\..\venv\Scripts\python.exe manage.py automation_health --settings=config.settings.prod
```

`--notify` registra il controllo e può inviare email reali. JSON su stdout;
exit 0 salute regolare, 2 worker/coda non sani, altri codici errore di controllo.
Il wrapper Windows restituisce 3 anche per notifiche non consegnabili.

## Manutenzione e arresto volontario

Prima di fermare il worker, sospendere il watchdog con scadenza (massimo 24 ore):

```powershell
C:\PortaleNovicrom\shared\scripts\watch_qcluster.ps1 -Environment prod -MaintenanceMinutes 60
```

Poi eseguire il deploy/arresto dal dashboard o da Task Scheduler. Al termine:

```powershell
C:\PortaleNovicrom\shared\scripts\watch_qcluster.ps1 -Environment prod -Resume
```

La scadenza riabilita automaticamente i controlli. Senza questa pausa, fermare
soltanto il task dal dashboard può farlo ripartire al controllo successivo.
Durante la pausa il banner sorveglianza diventa giallo dopo cinque minuti.

## Diagnostica e limiti

- `ENV/logs/qcluster-watchdog.log`, rotazione a 5 MB con una copia precedente;
  registro Applicazione, sorgente `NovicromQCluster`: 4101 allarme salute,
  4102 richiesta riavvio, 4103 manutenzione/configurazione, 4104 errore controllo
  o consegna, 4105 ripristino notificato. Collegare questi eventi al monitoraggio infrastrutturale esistente.
- Probe Python limitata a 45 secondi; si termina solo quella probe se scade.
  stdout/stderr temporanei rimossi senza copiare traceback nei log pubblici.
- Database irraggiungibile o credenziali SMTP inutilizzabili: il registro
  Windows resta il canale locale; la consegna email non è garantita.
- Arresto dell'intero server o di Task Scheduler: serve un monitor **su un'altra
  macchina** per un avviso proattivo. Il banner segnala un watchdog fermo solo
  quando il portale è raggiungibile. Nessuna falsa garanzia di disponibilità totale.
- Nessun recupero/cancellazione della coda, nuovo invio aziendale, grant ACL,
  modifica di `.env` o installazione di dipendenze. Heartbeat vecchi eliminati
  dopo sette giorni all'avvio di una nuova istanza; incidenti conservati nel
  monitoraggio esistente. Ritentare email dopo crash può produrre un duplicato
  se il trasporto l'aveva accettata prima del salvataggio dello stato.

Rollback operativo: disabilitare `QClusterWatchdog_<ENV>`, ripristinare launcher
e release precedenti. Le tabelle additive 0027 possono restare; nessuna coda
viene modificata dalla disinstallazione del controllo.

## Verifiche sviluppo

Test Django mirati: `automazioni.tests_cluster_watchdog`,
`automazioni.tests_managed_flows`, `automazioni.test_pianificati_page`.
Test Windows sintetici senza DB/task/email reali:
`powershell -NoProfile -File deployment/tests/test-qcluster-watchdog.ps1`.
Prova reale del launcher con `manage.py` sintetico e venv esistente in sola
lettura: `deployment/tests/test-qcluster-launcher.ps1 -VenvPath <venv>`;
verifica percorso con spazi, settings TEST distribuito, output oltre 1 MB e
conservazione dell'exit code. Nessun qcluster Django o database reale avviato.
