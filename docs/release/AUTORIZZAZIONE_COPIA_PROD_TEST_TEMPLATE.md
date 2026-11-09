# Autorizzazione alla copia di dati di produzione in TEST o DEV (A.8.33, MT CN 275 par. 8.3)

I dati di produzione dell'HUB contengono dati personali di dipendenti, visitatori e fornitori, referti e informazioni di sicurezza. Una copia fuori da PROD è ammessa solo con questa autorizzazione firmata **prima** della copia, con anonimizzazione e con data di cancellazione. Senza autorizzazione, TEST e DEV usano solo dati sintetici (seed e fixture del repository).

| Richiesta n. | Data | Richiedente (ruolo) | Ambiente di destinazione | Server / postazione |
|---|---|---|---|---|
| | | | | |

## 1. Motivo e perimetro

| Voce | Valore |
|---|---|
| Scopo (collaudo RFC ____, prova migrazioni, analisi di un difetto, altro) | |
| Fonte (backup `.bak` del ____ oppure DB live) | |
| Tabelle o moduli necessari (tutto il DB solo se motivato) | |
| Dati che devono restare leggibili (es. codici asset, OP) | |
| Dati da anonimizzare (anagrafiche, contatti, referti, timbrature, visitatori, allegati) | |
| Media e allegati inclusi? (di norma no) | |

## 2. Misure

| Misura | Come | Esito |
|---|---|---|
| Anonimizzazione | `deployment\scripts\ripristina-copia-anonima.ps1` + comando `anonimizza_copia`; esito salvato nella cartella della richiesta | |
| Accesso | Solo il richiedente e l'IT Officer; account SQL dedicato; nessuna condivisione di rete aperta | |
| Separazione | Istanza o database distinto da PROD; `.env` dell'ambiente senza credenziali di PROD | |
| Nessuna uscita | Vietato copiare la copia su portatili, cloud personali, prompt di assistenti IA, ticket | |
| Cancellazione | Entro il ____ (massimo 30 giorni): drop del DB, cancellazione dei file, conferma scritta sotto | |

## 3. Autorizzazione

| Ruolo | Data | Firma |
|---|---|---|
| Titolare del progetto | | |
| CISO | | |
| Responsabile del trattamento (se diverso) | | |

## 4. Chiusura

| Cancellazione eseguita il | Da (ruolo) | Verificata da (ruolo) | Note |
|---|---|---|---|
| | | | |
