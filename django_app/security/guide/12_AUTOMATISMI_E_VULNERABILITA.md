# Automatismi e vulnerabilità

Questo capitolo spiega tre funzioni che riducono il lavoro ripetitivo del SOC senza nascondere i problemi veri:

- la **soppressione appresa**: il sistema smette di aprire un alert che il team ha già scartato più volte;
- gli **automatismi di rientro**: l'alert si chiude da solo quando un dato successivo prova che il problema non c'è più;
- l'**impatto CVE sugli asset**: per ogni vulnerabilità si vede quali PC la hanno davvero, partendo dall'inventario software.

Le pagine si trovano nel menu del SOC: **Soppressioni** e **Vulnerabilità** per tutti; **Config › Automatismi di rientro**, **Config › Inventario software** e **Config › Software e CPE** per chi ha il permesso di configurazione.

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

Elenca le soppressioni manuali e quelle apprese. Per ognuna mostra ambito, motivo, quante volte ha fermato un evento (hit), ultima volta e scadenza. I filtri «Apprese / Manuali» e «Attive / In scadenza / Scadute o revocate» aiutano la revisione periodica: conviene guardare almeno una volta al mese le regole **in scadenza entro 14 giorni** e quelle con molti hit. In fondo alla pagina ci sono le ultime disattivazioni registrate.

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

### Simulare prima di accendere

Nella pagina **Config › Automatismi di rientro** ogni regola ha il pulsante **Simula 30 giorni**: mostra quali alert degli ultimi 30 giorni la regola avrebbe chiuso, con il motivo, **senza chiudere nulla**. Un alert che il team ha chiuso per altri motivi ma che la regola avrebbe chiuso è un buon segnale; un alert ancora in lavorazione che la regola avrebbe chiuso è un campanello d'allarme.

Una regola si può **accendere solo se è stata simulata negli ultimi 7 giorni**. Accensioni e spegnimenti finiscono nel registro audit. Per spegnere tutte le chiusure automatiche in un colpo solo si imposta `SECURITY_AUTO_RESOLVE_ENABLED` a `false` in Config › Impostazioni generali.

## Impatto CVE sugli asset

### Da dove arrivano i dati

- **Inventario software**: export dei software installati per PC, da WatchGuard EPDR (Panda) o da BusinessLog, caricato a mano in CSV o Excel.
- **NVD** (National Vulnerability Database): per ogni CVE, quali prodotti e quali versioni sono vulnerabili.
- **CISA KEV**: l'elenco delle CVE sfruttate attivamente.
- **EPSS** (FIRST.org): la probabilità che una CVE venga sfruttata nei prossimi 30 giorni.

NVD, KEV ed EPSS vengono letti da un job in background ogni ora, solo se in **Impostazioni › Impatto CVE sugli asset** è acceso «Arricchisci le CVE da NVD e CISA KEV». Nessuna pagina del portale chiama questi servizi mentre la si apre.

### Importare un inventario

1. Apri **Config › Inventario software**, scegli la provenienza (WatchGuard, BusinessLog, altro) e carica il file CSV o XLSX.
2. Associa le colonne del file ai campi: **PC**, **prodotto** e **versione** (obbligatori), **produttore** e **data di rilevamento** (facoltativi). Il sistema propone l'associazione leggendo le intestazioni; se compili **Salva come preset**, la volta dopo le colonne si associano da sole.
3. Premi **Aggiorna anteprima**: vedi le righe valide e quelle scartate, ognuna con il motivo (PC vuoto, versione vuota, riga duplicata…). In Excel formatta la colonna versione come **testo**: una versione salvata come numero («2.10» diventa 2.1) viene scartata.
4. Premi **Importa**. Le installazioni già note vengono aggiornate; quelle che non compaiono più nel nuovo export dello stesso tipo vengono segnate come **non più rilevate**.

Il file caricato resta in un'area privata e cifrata solo fino all'import e non è mai scaricabile dal browser. Se abbandoni un'importazione a metà, **Annulla e elimina il file**; in ogni caso le anteprime non confermate vengono cancellate dopo 2 giorni.

### Collegare i software alle CVE (CPE)

NVD descrive i prodotti con un codice chiamato **CPE** (produttore e prodotto, per esempio `7-zip:7-zip`). Per sapere se una CVE riguarda un software dell'inventario, ogni coppia produttore/prodotto va collegata al suo CPE una volta sola, in **Config › Software e CPE**:

- **Cerca in NVD** propone i CPE più simili; **Conferma** quello giusto.
- **N/A** per i software senza CVE da seguire (driver, componenti interni): non verranno più proposti.
- **Alias** unisce nomi diversi dello stesso produttore o prodotto (per esempio «Microsoft Corporation» e «Microsoft»).
- **Ricalcola impatti** riapplica tutte le regole dopo una serie di modifiche.

Finché un software non ha il CPE confermato, le CVE che potrebbero riguardarlo risultano **da verificare**, mai «non impatta». Conviene partire dai software installati sul maggior numero di PC: la dashboard Vulnerabilità li elenca in «Software senza mappatura CPE».

La **API key NVD** è facoltativa: senza key NVD accetta 5 richieste ogni 30 secondi, con la key molte di più. Si inserisce nella stessa pagina, viene salvata cifrata e si rimuove solo con **Rimuovi la key**.

### Come si legge l'esito

Per ogni CVE e ogni PC il sistema dà uno di tre esiti, sempre con la spiegazione in chiaro (prodotto, versione installata, range vulnerabile, fonte e data dell'inventario).

| Esito | Quando | Esempio |
| --- | --- | --- |
| **Impatta** | CPE confermato e versione installata dentro il range vulnerabile | 7-Zip 23.01 con CVE vulnerabile sotto la 24.07 |
| **Non impatta** | CPE confermato e versione fuori range, oppure inventario recente in cui il prodotto non c'è | 7-Zip 24.08 con la stessa CVE |
| **Da verificare** | CPE non confermato, versione non confrontabile (es. `21H2`, `1.1.1b`), inventario più vecchio di 30 giorni, CVE valida solo su un sistema operativo specifico | Un prodotto simile ma non ancora collegato |

Il sistema non tira mai a indovinare: quando non può dimostrare l'esito, scrive «da verificare».

### Dove si vede

- **Vulnerabilità**: CVE che impattano o da verificare, ordinate per KEV, CVSS, EPSS e numero di PC impattati; i PC più esposti; i software ancora da collegare.
- **Scheda CVE**: l'esito PC per PC con la spiegazione.
- **Scheda alert e ticket** di una CVE: il riquadro «Impatto sugli asset» e, se non ci sono PC impattati, la proposta di chiusura. La proposta **non compare mai** per CVE sfruttate (KEV) o critiche.
- **Scheda asset** del modulo Asset: la sezione «Vulnerabilità» con le CVE che riguardano quel PC.

## Domande frequenti

**Ho disattivato tre volte lo stesso alert ma la regola non è nata.** Controlla nella scheda dell'alert il conteggio e il motivo: probabilmente l'alert è critico, riguarda una CVE sfruttata o una minaccia, il tipo è escluso, oppure nessuna delle tre disattivazioni è stata fatta da chi ha il permesso di configurazione.

**Una soppressione appresa nasconde un problema vero.** Riapri l'alert o promuovi l'evento soppresso: la regola si spegne subito e il conteggio riparte. Per spegnere del tutto la funzione: Impostazioni › Soppressione appresa.

**Un PC risulta «da verificare» per tutte le CVE.** L'inventario di quel PC è più vecchio di 30 giorni (la soglia si cambia in Impostazioni): carica un export aggiornato.

**La dashboard Vulnerabilità è vuota.** Verifica che l'arricchimento sia acceso in Impostazioni, che sia stato importato almeno un inventario e che i software principali abbiano il CPE confermato. Il job gira ogni ora.
