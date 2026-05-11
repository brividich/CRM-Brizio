# Cartelle SharePoint Asset

Data: 2026-05-08

## Come funziona

Nei form asset e macchine la modalita consigliata e `Cartella SharePoint automatica`.

Quando e attiva, l'utente non deve compilare URL o percorso: al salvataggio il portale calcola il percorso logico della cartella usando:

```text
<cartella base>/<reparto>/<ID asset>
```

Default:

- Asset generici: `Asset/Inventario/<reparto>/<ID asset>`
- Macchine: `Macchine/<reparto>/<ID asset>`

Esempio:

```text
Macchine/CN5/123
```

Se Microsoft Graph e configurato, il portale crea la cartella su SharePoint se non esiste e salva automaticamente l'URL reale restituito da Graph. Gli upload dei documenti vengono poi sincronizzati nelle sottocartelle per categoria:

- `specifiche`
- `manuali`
- `interventi`

Se Graph non e configurato, il percorso puo restare salvato sul record asset ma i file rimangono nel portale e vengono serviti tramite download autenticato.

## Configurazione minima

Da `/assets/impostazioni/`, sezione SharePoint:

- `Tenant ID`
- `Client ID`
- `Client Secret`
- `Site ID`
- Cartella base asset, default `Asset/Inventario`
- Cartella base macchine, default `Macchine`

L'URL libreria documentale e opzionale: serve come riferimento amministrativo, mentre la sync usa Graph e `Site ID`.

## Quando usare i campi manuali

Disattivare `Cartella SharePoint automatica` solo quando un asset deve puntare a una cartella non standard, per esempio:

- archivio storico gia esistente;
- cartella condivisa tra piu asset;
- struttura SharePoint temporanea diversa dalle root configurate.

In quel caso compilare `Percorso cartella SharePoint`. L'URL completo puo essere lasciato vuoto: se Graph riesce a creare/trovare la cartella, verra aggiornato dal portale.
