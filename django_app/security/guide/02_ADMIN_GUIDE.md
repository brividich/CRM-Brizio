# Guida admin

Questa guida descrive le 9 sezioni della **Configuration Studio** (`/soc/admin/config/`). Per la configurazione servono il permesso ACL `security.config.view` e uno tra `security.manage_security_configuration` o `is_staff`. Ogni modifica finisce nel registro audit.

## Autoconfigurazione

`/soc/admin/autoconfig/` (link in testa alla Configuration Studio) è il punto di partenza: mostra il piano di configurazione — cosa manca, cosa è difforme dai default, cosa è già allineato — e permette di seminare la base senza shell. Applica anche, come pulsanti, le correzioni che la diagnostica sa risolvere da sola. Dettagli in [Guida alla configurazione](/soc/docs/08-configuration-guide/).

## Generali

Chiavi di configurazione globali (soglie, finestre temporali, comportamenti di default). Le chiavi marcate come **segrete** non mostrano il valore in chiaro: lasciando il campo vuoto si conserva il valore esistente. Dopo un'autoconfigurazione (o un `seed_security_center_config`) è qui che si rivedono i default.

## Sorgenti

Definiscono da dove arrivano i report: tipo (email/PDF/CSV/API/manuale), vendor, pattern del mittente e dell'oggetto, il parser associato e la **cadenza attesa**. Impostare la cadenza attesa attiva l'heartbeat: se un report non arriva in tempo, scatta un alert. La pagina Diagnostica permette di provare se un dato mittente/oggetto verrebbe accettato.

## Parser

Elenco dei parser che trasformano i report in metriche e finding. Ogni parser ha uno stato (attivo/disattivo) e una **priorità** (valore più basso = valutato prima). Un parser disattivato non produce nulla, anche se il report arriva regolarmente.

## Regole alert

Condizioni su una metrica che generano un alert. Ogni regola ha: metrica, operatore (maggiore, minore, uguale, contiene, regex, deviazione dalla baseline), soglia, **severità**, **cooldown** (minuti di silenzio dopo uno scatto) e **finestra di deduplica**. Può creare automaticamente un ticket e/o un contenitore evidenze. Il pulsante **Test** simula la regola su metriche fittizie senza creare alert.

## Soppressioni

Regole che silenziano eventi noti o rumorosi **prima** che diventino alert, per tipo evento, severità o condizioni sul payload. Hanno una validità temporale (inizio/scadenza). Utili per ridurre il rumore, ma vanno riviste: una soppressione può nascondere un segnale reale. Meglio impostare sempre una scadenza.

## Backup

Job di backup **attesi** e regole per rilevare anomalie: backup mancante (non visto oltre le ore limite), fallito, di durata anomala o di dimensione anomala. Un job può essere marcato come **critico** perché la sua assenza allerti subito. Le soglie di durata/dimensione sono opzionali.

## Notifiche

Canali in uscita: **email**, **webhook Teams**, **dashboard**. Ogni canale ha una severità minima, i destinatari, un cooldown e i tipi di evento su cui notificare (nuovo alert, ticket creato, violazione SLA). Ogni tentativo di invio è tracciato (inviato/fallito/soppresso da cooldown). Prova un canale con `send_security_test_notification` prima di affidartici.

## Ticketing

Come gli alert diventano ticket di remediation: strategia di **aggregazione** (es. per prodotto, che raggruppa le CVE dello stesso prodotto), assegnatario e gruppo di default, riapertura in caso di ricorrenza, e **SLA per severità** che guidano gli avvisi di scadenza.

## Audit

Traccia in sola lettura di ogni modifica di configurazione: chi, cosa, quale campo, valore vecchio e nuovo, quando. È la fonte di verità per capire cosa è cambiato e per gli audit di conformità.

## Approfondimenti

- Valori e default consigliati: [Guida alla configurazione](/soc/docs/08-configuration-guide/).
- Stati e transizioni degli alert: [Ciclo di vita degli alert](/soc/docs/07-alert-lifecycle/).
