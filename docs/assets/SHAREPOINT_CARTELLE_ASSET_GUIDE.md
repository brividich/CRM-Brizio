# Cartelle SharePoint Asset

Data: 2026-05-18

## Come funziona

Nei form asset e macchine la modalita consigliata e `Cartella SharePoint automatica`.

Quando e attiva, l'utente non deve compilare URL o percorso: al salvataggio il portale calcola il percorso logico della cartella con una struttura fissa:

```text
ASSET CN/<tag asset>
```

La cartella radice `ASSET CN` e fissa e non configurabile; vale sia per gli asset generici sia per le macchine operatrici. Il nome della cartella e il `tag` dell'asset (es. `ML-000123`).

Esempio:

```text
ASSET CN/ML-000123
```

Se Microsoft Graph e configurato, il portale crea la cartella su SharePoint se non esiste e salva automaticamente l'URL reale restituito da Graph. Al primo salvataggio vengono predisposte subito anche le tre sottocartelle distinte per categoria documento:

- `manuali`
- `specifiche`
- `interventi`

La cartella asset e le tre sottocartelle ricevono anche i metadati indicizzabili della libreria (`AssetTag`, categoria, produttore, modello, matricola, stato, reparto e `AssetTipoDocumento`). Le colonne mancanti vengono create automaticamente e la compilazione e best-effort: se Graph rifiuta il PATCH dei campi, la cartella resta comunque creata e il portale mostra solo un warning.

Gli upload dei documenti vengono poi sincronizzati nella sottocartella corrispondente alla categoria.

Quando dalla scheda asset si usa **Carica cartella**, il browser invia i file della cartella selezionata e delle eventuali sottocartelle. Il portale ricrea su SharePoint la stessa struttura relativa dentro la categoria attiva:

```text
ASSET CN/<tag asset>/<categoria>/<cartella selezionata>/<eventuali sottocartelle>/<file>
```

Esempio: caricando la cartella `Intervento maggio/Foto/foto-01.jpg` dalla tab `Interventi`, il file viene sincronizzato in:

```text
ASSET CN/ML-000123/interventi/Intervento maggio/Foto/<nome file remoto>
```

Il file resta anche registrato come `AssetDocument` nel portale per fallback, metadati e cancellazione controllata.

Se Graph non e configurato, il percorso puo restare salvato sul record asset ma i file rimangono nel portale e vengono serviti tramite download autenticato.

## Etichette QR

Il PDF `/assets/view/<id>/qr-label/` genera di default un QR verso la cartella SharePoint dell'asset quando `URL cartella SharePoint` e valorizzato.

Se l'URL SharePoint non e ancora disponibile, il QR rimanda alla scheda asset del portale. Per forzare sempre la scheda asset usare `?target=detail`.

## Configurazione minima

Da `/assets/impostazioni/`, sezione SharePoint:

- `Tenant ID`
- `Client ID`
- `Client Secret`
- `Site ID`

La cartella radice `ASSET CN` e mostrata in sola lettura: non e piu configurabile.

L'URL libreria documentale e opzionale: serve come riferimento amministrativo, mentre la sync usa Graph e `Site ID`.

## Quando usare i campi manuali

Disattivare `Cartella SharePoint automatica` solo quando un asset deve puntare a una cartella non standard, per esempio:

- archivio storico gia esistente;
- cartella condivisa tra piu asset;
- struttura SharePoint temporanea diversa dalla radice `ASSET CN`.

In quel caso compilare `Percorso cartella SharePoint`. L'URL completo puo essere lasciato vuoto: se Graph riesce a creare/trovare la cartella, verra aggiornato dal portale.

## Asset esistenti

Gli asset che hanno gia un `Percorso cartella SharePoint` valorizzato mantengono il percorso esistente: la struttura `ASSET CN/<tag>` si applica ai nuovi asset e a quelli senza percorso ancora impostato.
