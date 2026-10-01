# Console deploy qcluster

Correzione account Windows: il nome breve mostrato dal task puo rappresentare un account di dominio. Il confronto credenziali usa ora il SID del task esportato, non il nome visualizzato. Specificare `DOMINIO\utente` nella richiesta credenziali. Per una console gia aperta e configurata, sostituire solo `current/deployment/scripts/install-qcluster-watchdog.ps1` con la versione corretta (con backup), quindi ripetere 5 e, dopo successo, 6. Non occorre ripetere migrazioni o deploy.

Guida stampabile: [Guida_deploy_qcluster.pdf](docs/Guida_deploy_qcluster.pdf).

Da PowerShell amministrativa sul server, dalla directory del nuovo pacchetto:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deployment\scripts\qcluster-console.ps1 -Environment test -PortaleRoot C:\PortaleNovicrom
```

Per produzione usare `-Environment prod`. Il default e TEST. La console legge
l'azione del task `\PortaleNovicrom\QCluster_<ENV>`, verifica ambiente/radice e
aggiorna il launcher realmente usato. Non richiede nuove dipendenze.

1. Backup SQL e manutenzione del portale secondo procedura aziendale; arrestare
   e disabilitare i processori legacy. La console non esegue queste operazioni.
2. Menu **2**: conferma esplicita ambiente, backup launcher/task, pausa watchdog
   due ore, disabilitazione/arresto worker e verifica processi residui.
3. Lasciare aperta la console, distribuire **e attivare** il pacchetto con il
   wizard/deploy abituale. Il deploy puo ricreare il poller legacy: verificarlo
   e disabilitarlo nuovamente prima di continuare. Non riavviare il qcluster.
4. Menu **9**: esegue in sequenza **3-4-5-6**: migrate completo, trigger,
   pianificazioni, check/migrate --check, backup/copia launcher verificata con
   hash, installazione watchdog e avvio/controllo worker. Si ferma al primo errore.
5. Controllare dopo due minuti salute, ultimo controllo watchdog e avanzamento
   coda. Collaudare allarme/ripristino email in TEST prima della riapertura.

Le opzioni 3, 4, 5 e 6 sono disponibili singolarmente. L'opzione 1 mostra lo
stato; L indica i log. Il recupero precedente di Assenze/broker e separato:
usare **3-7-8-4-5-6**, esaminando l'anteprima 7 prima di confermare 8. Non e
incluso nel percorso ordinario 9. Entrambi i comandi apply richiedono worker
realmente fermi; interrompere al primo errore e conservare il batch di recupero.

## Comportamento in caso di errore

- Nessun kill automatico dei worker, cambio credenziali/.env o reset delle code.
  I task gia disabilitati restano disabilitati se la preparazione fallisce.
- I progressi indicano i passi conclusi; nessun 100% dichiarato se un comando
  fallisce. Migrazioni/trigger gia eseguiti non sono annullati dalla console.
- Se current cambia dopo la verifica, ripetere 3. Chiudendo la console si
  perdono i flag della sessione: ripartire da 2, senza riavvio implicito all'uscita.
- Prima dell'avvio servono configurazione, launcher e watchdog verificati nella
  sessione. Tre sonde salute sono limitate a 20s ciascuna (intervallo 10s).
  Solo la sonda read-only e i suoi figli vengono terminati in caso di timeout.
- Dopo le sonde, il watchdog viene riattivato anche se il worker non e sano,
  per segnalare il guasto. La console restituisce un errore operativo: non
  riaprire il portale solo perche e stata accettata la richiesta di avvio.
- Output dei comandi visibile sul server; nessuna trascrizione automatica di
  stdout/stderr potenzialmente riservati. I file temporanei delle sonde vengono
  rimossi. I backup launcher/XML task sono in ENV/logs/qcluster-deploy-backups.
- Account Password: credenziale richiesta dall'installer, non salvata nei file.
  Account interattivo non ammesso. Verificare diritti SQL/SMTP/task, soprattutto S4U.

Il PDF contiene anche comandi manuali, controlli, riferimenti log e rollback.
La console non invia email di prova; la consegna va collaudata in TEST.
Un guasto dell'intero server richiede sorveglianza su un'altra macchina.

## Verifiche e generazione PDF

```powershell
powershell -NoProfile -File deployment/tests/test-qcluster-console.ps1
powershell -NoProfile -File deployment/tests/test-qcluster-console-process.ps1 -VenvPath <venv-esistente>
python tools/build_qcluster_deploy_guide.py
```

Il generatore usa ReportLab gia presente nel progetto e i font Arial/Consolas
di Windows. Non installa librerie. QA con rendering di tutte e sei le pagine;
fixture/immagini sintetiche sotto .tmp_tests, escluse da Git.
