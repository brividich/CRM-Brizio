# Risoluzione problemi

Problemi comuni e come diagnosticarli. Il punto di partenza è quasi sempre la pagina `/soc/admin/diagnostics/` o i comandi `security_center_diagnostics` e `security_db_check`.

## Nessun parser corrisponde al report

- Controlla che il **pattern mittente/oggetto** della sorgente combaci con il report reale.
- Verifica che il **nome parser** sulla sorgente esista e sia **attivo** nella sezione Parser.
- Usa la Diagnostica per simulare mittente/oggetto e vedere se la sorgente li accetta.

## Nessun alert creato

- La **regola** è attiva? Il nome della **metrica** combacia con quello prodotto dal parser?
- La **soglia** e l'**operatore** sono corretti? Prova la regola col pulsante Test.
- Attenzione a **cooldown** e **deduplica**: un alert può non ricomparire perché è ancora attivo o in cooldown.
- Esiste una **soppressione** che sta silenziando l'evento?

## Nessun ticket creato

- La regola ha l'opzione **crea ticket** attiva?
- Un ticket **esistente** per lo stesso `(sorgente, dedup_hash)` viene aggiornato invece di crearne uno nuovo: cercalo tra i ticket aperti.

## Backup mancante non rilevato

- Il **nome job atteso** combacia con quello reale (device/NAS inclusi)?
- I **giorni attesi** e le **ore limite mancante** sono coerenti con la pianificazione?
- L'interruttore **allerta su mancante** è attivo?

## Notifiche non inviate

- Il canale è **attivo** e la **severità minima** non è troppo alta?
- Controlla il log invii: l'esito può essere **soppresso da cooldown**.
- Prova il canale con `python manage.py send_security_test_notification`.

## Sorgente "silente" / heartbeat

- Se una sorgente non manda report ma non scatta alcun alert, verifica che abbia una **cadenza attesa** impostata.
- L'heartbeat va schedulato accanto all'ingestione: `python manage.py check_security_source_heartbeat`.

## Permesso negato

- Serve il permesso ACL `security.config.view` e uno tra `security.manage_security_configuration` o `is_staff`.
- Ricorda: le API/AJAX protette rispondono con 401/403 JSON, non con redirect HTML.

## Documenti della guida non visibili in produzione

- La guida vive in `django_app/security/guide/` (non in `docs/`, che il packager esclude). Se un documento non si apre in prod, verifica che la cartella `guide/` sia stata inclusa nel pacchetto di deploy. Vedi la [Guida sviluppo](/soc/docs/10-developer-guide/).
