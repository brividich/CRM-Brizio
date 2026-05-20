# Cartelle SharePoint Asset

Data: 2026-05-18

## Come funziona

Nei form asset e macchine la modalita consigliata e `Cartella SharePoint automatica`.

Quando e attiva, l'utente non deve compilare URL o percorso: al salvataggio il portale calcola il percorso logico della cartella con una struttura fissa:

```text
ASSET CN/<tag asset>
```

La cartella radice predefinita e `ASSET CN`; vale sia per gli asset generici sia per le macchine operatrici. Il nome della cartella e il `tag` dell'asset (es. `ML-000123`). La root resta amministrabile dalla configurazione SharePoint del modulo assets, ma va cambiata solo se cambia davvero la root operativa consentita.

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
ASSET CN/ML-000123/interventi/Intervento maggio/Foto/foto-01.jpg
```

I file caricati da cartella conservano il **nome originale** su SharePoint: la cartella replicata resta integra e riconoscibile. Le sottocartelle evitano le collisioni e un nuovo upload dello stesso file ne aggiorna il contenuto. I file singoli caricati con il drag&drop mantengono invece un nome remoto univoco (`<timestamp>_<id>_<nome>`) per non sovrascrivere file omonimi nella stessa categoria.

Il file resta anche registrato come `AssetDocument` nel portale per fallback, metadati e cancellazione controllata. Nella card **Documenti** della scheda asset i file caricati da cartella vengono mostrati raggruppati sotto l'intestazione della cartella di origine, non come elenco piatto; i file singoli restano elencati per primi.

Se Graph non e configurato, il percorso puo restare salvato sul record asset ma i file rimangono nel portale e vengono serviti tramite download autenticato.

## Cartelle documento aggiuntive per categoria

Oltre alle tre cartelle di base (`specifiche`, `interventi`, `manuali`) si possono aggiungere cartelle documento extra **a livello di categoria asset** (`AssetCategory`): una cartella aggiunta vale per tutti gli asset di quella categoria.

Dalla card **Documenti** della scheda asset, gli utenti con permessi di gestione asset (admin o `admin_assets`) vedono:

- un campo **"+ Aggiungi cartella"**: crea una nuova cartella documento per la categoria dell'asset; viene predisposta anche la relativa sottocartella su SharePoint (`ASSET CN/<tag>/<slug>`);
- un pulsante **"Disattiva questa cartella"** sulle sole cartelle extra: consentito **solo se la cartella non contiene documenti** in nessun asset della categoria. La disattivazione e un soft-delete (`is_active=False`): la cartella sparisce dai nuovi upload, ma record e cartelle SharePoint esistenti restano.

Le cartelle **non sono rinominabili**: lo slug e stabile e viene usato sia come chiave interna sia come nome della cartella SharePoint. L'asset deve avere una categoria assegnata per poter aggiungere cartelle. Le tre cartelle di base non sono disattivabili.

## Etichette QR

Il PDF `/assets/view/<id>/qr-label/` genera di default un QR verso la route pubblica del portale:

```text
/assets/public/<public_qr_token>/
```

Se `SITE_URL` e configurato, il PDF usa quella base canonica per costruire il QR completo, per esempio:

```text
https://hub.cnovicrom.local/assets/public/<public_qr_token>/
```

Questo evita link `http` quando IIS/HttpPlatform inoltra internamente la request a Waitress senza header proxy HTTPS affidabile.

La route non richiede login e reindirizza con `302` al link pubblico SharePoint salvato su `sharepoint_public_url`. Se il link pubblico non e disponibile, il QR non usa piu l'URL SharePoint interno (`sharepoint_folder_url`) e torna alla scheda asset del portale.

Per forzare sempre la scheda asset usare `?target=detail`.

## Link pubblici SharePoint per QR

La creazione automatica dei link pubblici e spenta di default e non modifica tenant, sito o permessi globali. Quando abilitata, il portale chiama Microsoft Graph sul singolo `driveItem` della cartella asset:

```text
POST /drives/{drive_id}/items/{item_id}/createLink
```

Il body e sempre `type=view`, `scope=anonymous`, `retainInheritedPermissions=true`. Non vengono creati link di modifica, link organization o link specificPeople.

Il servizio genera link solo se la cartella e verificabile sotto la root consentita (`ASSET CN` di default). Se `SHAREPOINT_ASSET_ALLOWED_ROOT_ITEM_ID` e configurato, la validazione risale la catena `parentReference`; altrimenti controlla il path Graph normalizzato usando `SHAREPOINT_ASSET_ALLOWED_ROOT_NAME` come segmento reale.

Comandi operativi:

```bash
python manage.py assets_ensure_public_share_links --dry-run
python manage.py assets_ensure_public_share_links --apply --only-missing
python manage.py assets_ensure_public_share_links --apply --asset-tag "APLCP142-MATR.PI-I-2286"
```

## Configurazione minima

Dal pannello centrale `/admin-portale/hub/setup-wizard/#sec-graph`, sezione Microsoft Graph / SharePoint, oppure da `/assets/impostazioni/`, sezione SharePoint:

- `Tenant ID`
- `Client ID`
- `Client Secret`
- `Site ID`

La cartella radice consentita (default `ASSET CN`) e modificabile dalla stessa card SharePoint, insieme al feature flag dei link pubblici QR e agli ID root/drive opzionali. Il pannello centrale e il pannello assets scrivono le stesse chiavi `.env`.

L'URL libreria documentale e opzionale: serve come riferimento amministrativo, mentre la sync usa Graph e `Site ID`.

Per i QR pubblici configurare dalla card SharePoint, solo dopo verifica Microsoft 365:

- `SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED=true`
- `SHAREPOINT_ASSET_ALLOWED_ROOT_NAME=ASSET CN`
- `SHAREPOINT_ASSET_ALLOWED_ROOT_DRIVE_ID` opzionale ma consigliato
- `SHAREPOINT_ASSET_ALLOWED_ROOT_ITEM_ID` opzionale ma consigliato
- `SHAREPOINT_ASSET_SITE_ID` o `GRAPH_SITE_ID`
- `SHAREPOINT_ASSET_DRIVE_ID` opzionale se si vuole forzare il drive

## Quando usare i campi manuali

Disattivare `Cartella SharePoint automatica` solo quando un asset deve puntare a una cartella non standard, per esempio:

- archivio storico gia esistente;
- cartella condivisa tra piu asset;
- struttura SharePoint temporanea diversa dalla radice `ASSET CN`.

In quel caso compilare `Percorso cartella SharePoint`. L'URL completo puo essere lasciato vuoto: se Graph riesce a creare/trovare la cartella, verra aggiornato dal portale.

## Asset esistenti

Gli asset che hanno gia un `Percorso cartella SharePoint` valorizzato mantengono il percorso esistente: la struttura `ASSET CN/<tag>` si applica ai nuovi asset e a quelli senza percorso ancora impostato.
