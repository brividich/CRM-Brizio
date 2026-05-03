# Contract test integrazioni esterne

Lo scopo di questa suite è bloccare in CI le **regressioni di contratto**
con i sistemi esterni (Microsoft Graph, LDAP/AD, DB legacy SQL Server)
prima che diventino incidenti in produzione.

## Due livelli

### Livello A — registrato, sempre in CI

I test in questa cartella mockano il *boundary* (MSAL, ldap3, ORM legacy)
con risposte registrate (`cassettes/*.json`) che riproducono lo shape
reale che l'integrazione restituisce. Verificano che il nostro codice:

- gestisca correttamente i casi di successo
- ritorni `None`/sollevi l'eccezione attesa nei casi di errore
- non si rompa se cambiano campi opzionali

Le cassette sono **manualmente sanitizzate** e committate in repo.
Eseguibili in qualsiasi ambiente, anche offline.

```powershell
python django_app\manage.py test core.contract_tests --settings=config.settings.test
```

### Livello B — live, opt-in

I test marcati `@tag("live_integration")` colpiscono i sistemi reali con
credenziali da `config\.env.test`. Sono pensati per:

- aggiornare le cassette (`--record`) quando l'integrazione cambia
- verificare prima di ogni rilascio che le credenziali e il tenant non
  siano stati invalidati

Esecuzione:

```powershell
$env:RUN_LIVE_INTEGRATION_TESTS = "1"
python django_app\manage.py test core.contract_tests --tag live_integration `
    --settings=config.settings.test
```

## Sanitizzazione cassette

`test_sanitize.py` esegue automaticamente check su tutte le cassette in
`cassettes/`. Il test fallisce se trova:

- token Bearer (`Bearer ey...`)
- email reali (qualsiasi cosa che non finisca per `.invalid`, `.example`,
  `example.local`, `novicrom.local`, ecc.)
- domini interni reali nei DN LDAP
- chiavi `client_secret`, `password`, `refresh_token`, `id_token` non
  vuote o con valori non-placeholder

Quando registri una nuova cassetta:

1. cattura la risposta vera in dev/test
2. sostituisci ogni valore sensibile con la versione `<placeholder>`
   o `synthetic-...`
3. esegui `python django_app\manage.py test core.contract_tests.test_sanitize`
4. committa
