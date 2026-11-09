# Verbale di collaudo su TEST (A.8.29) - RFC ____ - versione ____

Il collaudo si fa sull'ambiente TEST con lo **stesso pacchetto** che andrà in PROD (`BUILD_INFO.json` identico). I dati di TEST sono sintetici o anonimizzati con autorizzazione scritta (AUTORIZZAZIONE_COPIA_PROD_TEST_TEMPLATE.md). Il verbale viene firmato dai responsabili dei moduli toccati e dall'IT Officer prima dell'autorizzazione al go-live.

| Pacchetto | Commit | Deploy su TEST (data/ora) | Esecutore |
|---|---|---|---|
| | | | |

## 1. Controlli tecnici

| Controllo | Esito | Note |
|---|---|---|
| Deploy completato senza errori (migrate, collectstatic, attivazione) | | |
| Smoke test (`smoke-test.ps1 -Environment test`) | | |
| Login con i quattro backend previsti (Axes, legacy SQL, LDAP, Model) con utenze di test | | |
| Pagine protette: 302 al login se anonimi; API: JSON 401/403 | | |
| Superfici pubbliche a token: solo `/automazioni/approvazione/*` e `/approval-actions/*` | | |
| Task django-q in esecuzione, nessun errore in Centrale | | |
| Versione in footer e in `BUILD_INFO.json` coincidono | | |

## 2. Collaudo funzionale per modulo

Una tabella per modulo toccato dal rilascio (dal CHANGELOG della versione). Ogni caso ha un risultato atteso scritto prima della prova.

### Modulo: ____ (responsabile: ruolo ____)

| Caso di prova | Passi | Risultato atteso | Esito | Note |
|---|---|---|---|---|
| | | | | |

## 3. Dati personali e sicurezza

| Verifica | Esito |
|---|---|
| Nessun dato reale non autorizzato visibile in TEST | |
| Nuovi permessi presenti nella matrice ACL e assegnati ai ruoli previsti | |
| Nuove pagine raggiungibili solo con il permesso previsto (prova con utente senza permesso) | |
| Guide in-app e Centro guide aggiornati per le funzioni nuove | |

## 4. Anomalie rilevate

| # | Descrizione | Gravità (bloccante / alta / bassa) | Decisione (correggere prima del go-live / rilasciare e correggere dopo / accettare) |
|---|---|---|---|
| | | | |

## 5. Esito

- [ ] Collaudo superato: il pacchetto può andare in PROD.
- [ ] Collaudo superato con riserve (anomalie non bloccanti elencate sopra).
- [ ] Collaudo non superato: si riparte dallo sviluppo.

| Ruolo | Data | Firma |
|---|---|---|
| Responsabile di modulo | | |
| IT Officer | | |
