# Automazioni MFC e SNMP

La centrale usa lo scheduler **django-q2 già presente nel portale**. Windows avvia il worker persistente `qcluster`; le cadenze sono definite in `django_app/automazioni/schedules.py`, registrate da `setup_q_schedules` e gestibili da **Automazioni → Task pianificati**, `/admin-portale/automazioni/pianificati/`.

| Lavoro | Cadenza | Risultato |
| --- | --- | --- |
| `contatori_poll_snmp` | Ogni 5 minuti | Stato e storico sonde dei dispositivi attivi del Monitor SNMP |
| `contatori_letture_mensili` | Giorno 1 alle 08:00, fuso del portale (predefinito Europe/Rome) | Una lettura cumulativa per MFC attiva con IP e mese |

Non occorre creare altri task Windows. Se era stato creato un task separato per `poll_snmp_devices`, disabilitarlo quando si attiva questa integrazione, per evitare rilevazioni doppie.

## Attivazione dopo il deploy

Dal virtualenv di produzione, nella cartella `current/django_app`:

```powershell
python manage.py migrate contatori --settings=config.settings.prod
python manage.py setup_q_schedules --settings=config.settings.prod
```

La migrazione nuova è `contatori 0007` (dipende da 0006). Riavviare il **worker qcluster esistente** dopo il deploy perché carichi le nuove funzioni. Non avviarne una seconda copia. `setup_q_schedules` aggiorna il catalogo degli schedule del portale e rispetta le disattivazioni salvate dalla Centrale di comando. La registrazione cron iniziale calcola la prossima scadenza; per una prima lettura immediata usare **Esegui ora**.

Nella pagina Task pianificati verificare che entrambi i nomi risultino registrati e abilitati, con una prossima esecuzione. **Esegui ora** accoda i lavori: richiede che qcluster sia in esecuzione. Ogni apparato ha un job indipendente (timeout 110 secondi), così la durata della flotta non viene sommata in un solo job. Un lock nella cache condivisa limita gli accodamenti duplicati; scade dopo un'ora in caso di worker interrotto. La configurazione cache di produzione deve essere condivisa tra i processi, come il DatabaseCache del portale.

## Letture mensili e trimestri

Lo storico mensile conserva la **prima lettura riuscita del mese**, con data e ora effettive, e compare nella scheda MFC (ultimi 24 mesi). Il mese è quello della rilevazione: una lettura il 1 ottobre è lo snapshot di ottobre, non una lettura retrodatata al 30 settembre. I numeri sono contatori cumulativi, non il consumo del singolo mese.

Le letture trimestrali e la riconciliazione fatture restano separate: il vecchio `leggi_contatori` aggiorna una sola riga per macchina/trimestre e non va schedulato come raccolta mensile. Nessuna lettura trimestrale manuale viene sostituita dal nuovo job.

In caso di errore SNMP non viene creato uno snapshot con valori fittizi. Il job del singolo apparato fallisce nello storico django-q, il cluster applica i retry configurati e le altre macchine proseguono. **Esegui ora** sul job mensile riprova soltanto le macchine ancora senza lettura del mese corrente. Una lettura riuscita non viene sovrascritta; non è possibile ricostruire automaticamente mesi passati interrogando i contatori attuali.

Recupero da terminale, con gli stessi parametri SNMP globali della pagina MFC:

```powershell
python manage.py leggi_contatori_mensili --settings=config.settings.prod
```

Il comando conserva i successi e restituisce errore se alcune macchine non rispondono. Il riepilogo del task di smistamento indica gli apparati **accodati**, non quanti hanno già risposto: verificare gli esiti dei job figli e il Monitor SNMP/schede MFC. Il polling generico non raccoglie automaticamente i quattro contatori Canon: questo è il compito del job mensile MFC.
