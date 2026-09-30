# Reportistica Asset programmata

## Uso dal portale

Aprire **Asset → Impostazioni → Reportistica** (`/assets/impostazioni/reportistica/`).
Creare un piano con nome, tipo/categoria/reparto (vuoti = tutti), inclusione MFC/SNMP,
PDF e/o Excel, prima scadenza e frequenza: una tantum, giornaliera, settimanale o mensile.
Gli orari usano il fuso del portale. Il giorno 31 viene mantenuto come riferimento:
a febbraio si usa l'ultimo giorno, a marzo si torna al 31.

**Estrai ora** accoda una copia senza spostare la scadenza programmata.
**Modifica → Attiva** permette di sospendere le estrazioni future; quelle già accodate
rimangono in lavorazione. Le programmazioni non vengono create automaticamente al deploy.

L'**Archivio report** (`/assets/reports/archivio/`, raggiungibile anche da Reports)
mostra esiti, dettagli, download e confronto delle ultime 12 estrazioni dello stesso
piano e perimetro. Modificare i filtri avvia una serie distinta. I report completati
conservano dati e file originali: modifiche successive all'inventario non li riscrivono.
In caso di errore è disponibile **Riprova** per i gestori; i tentativi automatici
sono limitati a tre. Se lo snapshot è già stato acquisito, il retry lo conserva.

## Contenuto e limiti

- Inventario: codice, nome, tipo, categoria, reparto, stato, seriale, produttore,
  modello, ubicazione e IP. Non comprende allegati, credenziali o dati HR.
- MFC: ultima lettura mensile disponibile dei contatori cumulativi, con mese e
  timestamp effettivo; SNMP: ultimo controllo e valori delle sonde dei dispositivi collegati.
- La reportistica **non interroga gli apparati**: legge quanto raccolto dai job Contatori.
  Per includere la lettura mensile del giorno 1 alle 08:00, programmare il report più tardi
  e controllare il timestamp della lettura. Non c'è una dipendenza rigida tra i due job.
- Andamento: numero asset, in uso, in riparazione ed errori SNMP. Non è un calcolo
  dei consumi MFC né una ricostruzione retroattiva. Dati mancanti restano mancanti.
- PDF con tema condiviso del portale; Excel con fogli Riepilogo, Asset, MFC, SNMP,
  Andamento, filtri e grafico. I valori testuali sono esportati come testo, mai formule.
- Massimo 10.000 asset per estrazione; per parchi grandi usare piani per reparto/categoria.
  Un'elaborazione ha timeout di 110 secondi: la dimensione pratica dipende dal server.
- Snapshot e file risiedono nel database, non in una cartella media pubblica.
  Non è prevista cancellazione/retention automatica: includerli nei backup e monitorare
  crescita del database. Disattivare un piano conserva tutto lo storico.

## Attivazione dopo il rilascio del codice

Il commit deve essere integrato nella release distribuita, non basta eseguire una migrazione.
Dal virtualenv dell'ambiente, nella directory `current\django_app`:

```powershell
python manage.py migrate --settings=config.settings.prod
python manage.py setup_q_schedules --settings=config.settings.prod
python manage.py help leggi_contatori_mensili --settings=config.settings.prod
```

Riavviare **il worker qcluster già esistente** e il processo web con la normale procedura
di rilascio. Non aggiungere un secondo task Windows. In **Automazioni → Task pianificati**
verificare `assets_reportistica`: controlla le scadenze ogni minuto e accoda i singoli report.
Il risultato del dispatcher indica accodamento, non completamento dei PDF/Excel.
Un'abilitazione disattivata manualmente in Task pianificati resta disattivata anche dopo setup.

Migrazioni nuove: `assets 0119` (piani e archivio), `0120` (binding ACL, dipende anche da
`contatori 0007`). I job SNMP e mensili restano quelli del
[runbook Contatori](CONTATORI_AUTOMAZIONI.md).

Se compare `Unknown command: leggi_contatori_mensili`, il codice di Contatori non è
presente nell'installazione/interprete selezionato. Controllare release, percorso e
virtualenv: il comando è nel commit `716010f5` e negli antenati di questa funzionalità.
Non sostituirlo con `leggi_contatori`: quello aggiorna lo storico trimestrale.

## Affidabilità e accessi

Vincolo univoco piano/scadenza, lock di database e accodamento compare-and-set limitano
i doppioni. Il dispatcher recupera estrazioni rimaste senza worker dopo 10 minuti.
Se il servizio resta spento per più scadenze, acquisisce un solo snapshot corrente e
porta la prossima data nel futuro: non inventa report passati. Scadenza richiesta e
data effettiva sono entrambe visibili.

Configurazione/esecuzione/retry: `legacy.assets.admin_assets`; archivio/dettaglio/download:
`legacy.assets.assets_reports`, con bypass amministrativo esistente. La migrazione
non concede nuovi grant a ruoli o utenti. Accesso ai report trasversale agli asset del
perimetro: concedere il permesso Reports solo a chi può consultarli. Download protetti,
tracciati in audit e `private, no-store`; nessun nuovo percorso pubblico.

Collaudo dopo deploy in TEST: piano una tantum su dati di prova, attesa esito Disponibile,
apertura PDF/Excel, seconda estrazione per il grafico, prova con ruolo autorizzato e
ruolo negato. Verificare SQL Server e stato del worker: i test locali usano SQLite.
