# Flussi dei moduli nel designer Automazioni

Stato al 30 settembre 2026: implementazione sul branch `feature/automazioni-check-produzione`, non ancora distribuita. Il controllo produzione e l'inventario per modulo sono in [AUDIT_AUTOMAZIONI_PROD_2026-09-29.md](AUDIT_AUTOMAZIONI_PROD_2026-09-29.md).

## Cosa cambia

Il designer del portale rimane quello esistente. I 49 processi pianificati (48 censiti più la riconciliazione delle approvazioni scadute) e le dieci notifiche applicative censite diventano altrettante regole, collegate tramite `ManagedFlow`. Non è una migrazione a Microsoft Power Automate.

- `Tutti i flussi` raggruppa anche i processi nativi per modulo. Pianificazioni e notifiche su evento rimandano al relativo designer.
- Ogni flusso ha attivazione, condizioni, azioni e storico nel motore esistente. La bozza non viene eseguita.
- I processi pianificati espongono intervallo o calendario cron a cinque campi, nel fuso del portale. Modifiche e disattivazioni sopravvivono al deploy.
- L'azione `Esegui processo del modulo` richiama esclusivamente il processo registrato. Mantiene validazioni, destinatari e regole operative già presenti nel modulo. Argomenti e risultati privati non vengono copiati nel payload del designer.
- I campi del contesto dei processi nativi sono codice flusso, modulo, ora e giorno della settimana. I parametri di dominio e i destinatari rimangono nelle impostazioni del modulo; i singoli passaggi Python interni non vengono trasformati automaticamente in nodi visuali.
- Le dieci notifiche collegate riguardano gap idoneità, onboarding mansione/rischio, le tre tappe DPI (richiesta, approvazione e consegna), sospensione timbri, refresh qualifiche, nuove specifiche, reminder OFI e Suggestion Corner. Disattivare la notifica non impedisce il salvataggio dei dati aziendali.

`setup_q_schedules` installa idempotentemente i collegamenti. `install_managed_flows` consente l'anteprima e l'installazione esplicita con `--apply`. Nessuno dei due sovrascrive azioni/condizioni già personalizzate. Le regole collegate non si eliminano: si disattivano, per non lasciare un processo orfano.

L'azione nativa richiede il contesto sincrono di origine: una simulazione non la esegue; una ripresa differita fuori contesto viene rifiutata. Per inserire approvazioni o ritardi prima del processo nativo occorre prima progettare un ingresso persistente specifico del modulo. Le normali regole su eventi SQL mantengono i loro payload e le azioni differite esistenti.

## Affidabilità e limiti

- Il broker accorpa soltanto i tick ricorrenti riconoscibili dello stesso flusso, lasciando separati task manuali, argomenti personalizzati e callback. `catch_up=False` impedisce la raffica di ricorrenze perse al riavvio.
- Un lease di dieci minuti evita invocazioni concorrenti dello stesso processo; il timeout cluster attuale è due minuti. Il lease non costituisce garanzia di esecuzione esattamente una volta: crash e side effect esterni richiedono comunque l'idempotenza del modulo. Il processore legacy Windows condivide lo stesso flusso e non ripete il tick entro 45 secondi; conserva `--limit`.
- Gli errori restituiti da una regola non raggruppata portano l'evento SQL in errore. Dopo una decisione approvativa, un errore nelle azioni successive compare nello storico e rispetta `stop_on_first_failure`; una seconda approvazione mantiene lo stato in attesa.
- Ogni 15 minuti si riconciliano le richieste scadute, senza approvarle/rifiutarle e senza chiudere esecuzioni con altre richieste ancora pendenti.
- `automation_health` e la pagina Pianificazioni segnalano coda presente senza completamenti da dieci minuti. Il comando è esterno al worker e termina con codice 2 in questo caso. È un indicatore da verificare, non una prova automatica della causa.
- Il launcher Windows drena stdout/stderr su file distinti per avvio, preserva l'exit code e usa un mutex per impedire due launcher sullo stesso ambiente. Serve una politica operativa di conservazione dei log; questi file restano privati sul server.

Quattro trigger mancanti collegano visite mediche, diario preposto, RENTRI e rilevazione incidenti alla coda SQL. Sono set-based e proiettano campi espliciti. Nessun allegato o nota clinica viene inserito: per compatibilità dei template, `prescrizioni` contiene soltanto il testo fisso «Consultare la scheda riservata nel portale.». Le condizioni sul contenuto clinico non sono supportate da questo evento.

## Unione dei due flussi Assenze

Su richiesta dell'utente, `merge_assenze_flows` prepara un'unica regola `assenze-approvazione-unificata` a partire da:

- `assenze-pa-richiesta-approvazione-caporeparto`;
- `au-assenze-unico-branch-per-tipo`.

La nuova regola conserva i percorsi per tipo/durata e gli approvatori del flusso ramificato; usa le condizioni del flusso semplice (non saltare l'approvazione, stato pendente, caporeparto disponibile). Gli aggiornamenti di stato, la suddivisione giornaliera e la scrittura dello storico del flusso semplice vengono inseriti nei rami terminali. Per una catena di due approvazioni, l'esito positivo si registra soltanto dopo la seconda. Le comunicazioni terminali sono quelle del flusso ramificato, per evitare di aggiungere le email equivalenti del semplice. Per gli altri tipi di assenza si usa il flusso semplice completo come fallback.

Le due regole originali restano conservate, con azioni/condizioni/storico intatti, ma disattivate nella stessa transazione che attiva quella nuova. Le approvazioni già inviate mantengono i loro snapshot originali e non vengono annullate. Strutture diverse da quelle riconosciute bloccano la conversione; nessuna configurazione privata viene stampata dal comando. Una seconda esecuzione non ricrea o sovrascrive il flusso unificato.

## Rilascio e recupero sul server

Il controllo del 30/09 ha confermato produzione sul commit `5871b10`, broker a 13.688 elementi e ultimo completamento django-q il 29/09 alle 12:49 locali. Il processore eventi Windows aveva heartbeat corrente. WinRM non raggiungibile e interrogazione remota dei task Windows negata: nessun worker è stato fermato/riavviato da questa sessione, nessuna conversione o modifica al database di produzione è stata eseguita.

Eseguire i passaggi seguenti **localmente sul server, come amministratore**, durante una finestra concordata. Il flag `--workers-stopped` è una dichiarazione dell'operatore, non un rilevamento automatico.

1. Integrare il commit verificato in `release/prod`; produrre il pacchetto dal commit con i gate di release ordinari. Versione mantenuta in Unreleased in attesa del bump coordinato.
2. Inventariare da Utilità di pianificazione i task che lanciano `start_qcluster.ps1`, `manage.py qcluster` e `process_automation_queue`. Annotare nomi, azioni e stato iniziale; disabilitarne i trigger e fermarli. Verificare che i relativi processi e figli siano terminati. Non fermare indiscriminatamente altri Python o servizi. Arrestare temporaneamente le scritture del portale durante la conversione.
3. Creare il backup SQL secondo la procedura aziendale e copiare il launcher attualmente usato in un file datato. Conservare percorsi/identificativo del backup nel registro del rilascio; non esportare payload in repository.
4. Distribuire il pacchetto con la procedura ordinaria. Applicare le migrazioni `automazioni.0025` e `0026`. Copiare `deployment/start_qcluster.ps1` della nuova release **nel percorso effettivamente configurato nel task Windows**: cambiare solo la copia sotto `current` non aggiorna un task che usa un launcher esterno.
5. Con worker e processore legacy ancora fermi, da `prod/current/django_app`, usare il Python di `prod/venv` ed eseguire i comandi sotto. Controllare l'exit code di ogni comando; interrompere al primo errore. Il deploy storico considera alcuni errori setup/trigger non bloccanti: non saltare questa verifica esplicita.

```powershell
# Dalla cartella prod/current/django_app; adattare solo il percorso verificato del venv.
$portalPython = "C:\PortaleNovicrom\prod\venv\Scripts\python.exe"
& $portalPython manage.py migrate --settings=config.settings.prod
& $portalPython manage.py apply_sql_triggers --settings=config.settings.prod
& $portalPython manage.py setup_q_schedules --settings=config.settings.prod
& $portalPython manage.py merge_assenze_flows --settings=config.settings.prod
& $portalPython manage.py recover_automation_broker --settings=config.settings.prod
```

6. Verificare le anteprime. Applicare prima l'unione Assenze, poi il recupero del broker:

```powershell
& $portalPython manage.py merge_assenze_flows --apply --workers-stopped --settings=config.settings.prod
& $portalPython manage.py recover_automation_broker --apply --workers-stopped --settings=config.settings.prod
& $portalPython manage.py check --settings=config.settings.prod
```

Il recupero conserva in `BrokerRecoveryEntry` ogni pacchetto modificato/eliminato, con firma, lock, ID originale e batch, nella stessa transazione. Lascia un tick per flusso ricorrente noto e aggiorna il riferimento al designer. Preserva job manuali, sconosciuti, firme invalide e interi flussi con job ancora bloccati. Se ci sono lock futuri, attendere la loro scadenza a worker fermi e rieseguire l'anteprima; non forzare i lock alla cieca. Annotare il batch restituito.

7. Riavviare un solo launcher/cluster, poi riabilitare i trigger dei task previsti e il portale. Il processo legacy è ora instradato nello stesso flusso; i suoi heartbeat da soli non certificano la salute del cluster.
8. Eseguire `automation_health --settings=config.settings.prod` e controllare a distanza di alcuni minuti: completamenti recenti, coda in diminuzione, nessun doppio launcher, pianificazioni/cadenze corrette e due disabilitazioni AI precedenti conservate. Verificare nel designer i 59 collegamenti, la sola regola Assenze unificata attiva e lo storico del processo approvazioni scadute.
9. Collaudare su dati sintetici in ambiente test SQL Server prima della riapertura completa: insert/update singoli e multipli per i quattro trigger, Assenze Ferie brevi/lunghe, Permesso/Flessibilità/altro tipo, rifiuto, salta approvazione, due livelli e destinatario mancante. Non usare `Esegui ora` sui flussi di invio reali come semplice health check.

## Ripristino

Prima di qualsiasi ripristino fermare nuovamente i produttori/consumatori interessati e confrontare gli esiti già eseguiti. Non reinserire automaticamente tutti i pacchetti archiviati: riprodurrebbe email o azioni già completate. Il batch archivio permette un ripristino selettivo amministrativo solo per elementi accertati come non eseguiti; un rollback completo richiede il backup SQL coordinato con il codice.

Per annullare la sola unione Assenze, disattivare la nuova regola e ripristinare le attivazioni delle originali in una finestra a processori fermi. Questo reintroduce il rischio di doppia richiesta presente prima dell'intervento. Le decisioni già registrate restano valide e non si ripristinano con il solo cambio delle regole.

## Verifiche effettuate e attività residue

Verificati i test del modulo Automazioni, la conversione della struttura reale in sola lettura, il salvataggio della cadenza tramite browser con dati sintetici e il launcher con oltre un MB di stdout/stderr ed exit code 7, senza blocco delle pipe. Colonne dei trigger confrontate con lo schema SQL Server reale in sola lettura. I dettagli dei test conclusivi sono nel registro agente.

Restano necessari il rilascio, il recupero amministrativo, il collaudo dei trigger su SQL Server e la verifica delle consegne reali. Le configurazioni destinatari assenti non sono state riempite inventando indirizzi: i fallback esistenti restano operativi e vanno confermati nelle impostazioni con i referenti. Il perimetro comprende tutti i processi censiti nell'audit, non ogni chiamata Python o job figlio interno ai moduli.
