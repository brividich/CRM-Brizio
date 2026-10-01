# Discovery SNMP e catalogo community

La pagina `/contatori/discovery/` offre una scansione in background e la precedente
scansione rapida. Entrambe usano esclusivamente GET: non modificano gli apparati.

## Utilizzo

1. Aprire **Catalogo community salvate** e aggiungere un nome riconoscibile e il
   valore read-only. Il valore resta nascosto; in modifica un campo vuoto lo
   conserva. Versione e porta opzionali permettono di gestire apparati diversi.
   Disattivare una voce impedisce di usarla nelle nuove scansioni e nel polling.
2. Selezionare rete CIDR, fino a otto community e timeout per richiesta (1–10s).
   Selezionare **Globale** per includere la configurazione SNMP esistente. Le
   candidate seguono l'ordine del catalogo, con la globale per prima se inclusa.
3. Premere **Avvia scansione**. La pagina risponde subito e aggiorna avanzamento
   e risultati ogni quattro secondi. Si puo chiudere e riaprire la pagina:
   **Le tue ultime scansioni** conserva i collegamenti alle venti piu recenti.
4. **Interrompi** conserva i blocchi gia salvati. **Riprendi** riparte dal blocco
   rimasto, saltando gli host gia trovati. Una scansione completa non si riprende.
   Se non avanza per due minuti, controllare worker e coda prima di riprendere.
5. Nei risultati compare il nome della community che ha risposto. **Aggiungi al
   monitor** precompila il riferimento al catalogo; nelle schede MFC/dispositivo
   il campo **Community salvata** consente di riutilizzarla anche nel polling.
   La selezione non copia il segreto nel dispositivo e segue gli aggiornamenti
   successivi della voce. Le community globali/manuali preesistenti restano valide.

Nel polling la community salvata prevale sul valore manuale e globale. Per porta
e versione prevalgono gli override dell'apparato, poi la community salvata, poi
il profilo OID e la configurazione globale. La disattivazione di una community
gia assegnata produce un errore esplicito, senza ripiegare su credenziali diverse.

## Esecuzione e ripresa

- Massimo 512 host; la dimensione viene controllata prima di enumerare la rete.
- Un job legge al massimo 16 indirizzi con una candidata. La successiva viene
  provata solo sugli host ancora senza risposta. I job si concatenano sulla coda
  django-q2 gia esistente, senza aggiungere schedule o task Windows.
- Ogni GET ha un limite applicativo; un blocco ha budget di rete 35s e timeout
  worker 60s. I tempi SQL e di attesa nella coda non fanno parte del budget SNMP.
- Stato, cursore, risultati e revisione sono persistenti. Una acquisizione
  condizionale permette a un solo worker di eseguire la revisione corrente;
  job duplicati o precedenti a Interrompi/Riprendi vengono ignorati. La ripresa
  dopo un arresto improvviso puo rileggere il blocco non ancora salvato.
- Un errore di accodamento, una community non piu attiva/decifrabile o un blocco
  incompleto lasciano risultati e cursore recuperabili. Se il processo muore
  fra salvataggio e accodamento, la pagina propone la ripresa dopo due minuti.
- Le credenziali vengono risolte dal catalogo al momento del blocco: modificarle
  durante una scansione puo cambiare i tentativi successivi. Per una prova con
  configurazione uniforme, interrompere e avviare una nuova scansione.
- Nessuna cancellazione automatica dello storico o della coda. Le venti voci
  nella pagina sono un limite di visualizzazione, non una retention del DB.

La scansione rapida resta disponibile per diagnosi su pochi indirizzi, con
community transitorie e limite complessivo di 20s. Non e riprendibile. Un timeout
non distingue un apparato assente da community/versione errate o filtri di rete.

## Credenziali e accesso

Le nuove community sono cifrate con Fernet e chiave derivata da `SECRET_KEY`, con
separazione d'uso e supporto `SECRET_KEY_FALLBACKS` per lettura durante rotazione.
Non viene introdotta una nuova dipendenza: cryptography e gia installata.
Il backup deve conservare anche la configurazione delle chiavi. Prima di rimuovere
una vecchia chiave di fallback, risalvare i valori delle community con quella nuova.
La migrazione non ricifra i precedenti campi globali/manuali.

I job contengono solo ID scansione e revisione. Risultati e audit non contengono
valori community; i form password non li ripropongono neanche dopo errori. Restano
validi ACL e CSRF della route esistente; non si aggiungono route, grant o esenzioni.
Il catalogo e condiviso fra gli utenti autorizzati al discovery. Lo storico e le
azioni di controllo delle scansioni sono limitati al richiedente, anche conoscendo
l'UUID di una scansione altrui. Le risposte della pagina non sono memorizzabili in cache.

## Distribuzione

1. Integrare il commit nel ramo di rilascio e creare il pacchetto con il flusso
   ordinario, includendo le migrazioni Contatori **0014** e **0015**.
2. Eseguire il backup previsto dal deploy, applicare le migrazioni e riavviare
   applicazione e worker con il codice aggiornato. Nessuna nuova schedule.
3. Verificare che il worker smaltisca la coda; una coda ferma mantiene la scansione
   in attesa. Il discovery in background non sostituisce il ripristino di qcluster.
4. Provare dal portale prima un solo IP noto (`/32`, oppure `/128` IPv6), poi una
   piccola rete. Verificare una community alternativa, avanzamento, Interrompi/
   Riprendi e polling con community salvata. Le prove locali non certificano SQL
   Server, firewall o apparati di produzione.

## Riferimenti progettuali

- [LibreNMS: configurazione SNMP](https://docs.librenms.org/Support/Configuration/#snmp-settings):
  lista di community e distinzione fra timeout della risposta e limite esecuzione.
- [Zabbix: discovery di rete](https://www.zabbix.com/documentation/current/en/manual/discovery/network_discovery):
  elaborazione affidata a manager e worker.
- [Zabbix: regole discovery](https://www.zabbix.com/documentation/current/en/manual/discovery/network_discovery/rule):
  controlli asincroni e concorrenza configurabile. I limiti numerici HUB sono locali.
