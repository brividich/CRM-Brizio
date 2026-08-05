# Asset Inventory (Django app `assets`)

## ACL legacy: pulsanti creati
Esegui:

```bash
python manage.py seed_assets_acl
```

Il command crea/aggiorna questi pulsanti (`modulo="assets"`):

- `asset_list` -> `django:assets:asset_list`
- `asset_view` -> `django:assets:asset_view`
- `asset_create` -> `django:assets:asset_create`
- `asset_edit` -> `django:assets:asset_edit`
- `asset_assign` -> `django:assets:asset_assign`
- `wo_list` -> `django:assets:wo_list`
- `wo_view` -> `django:assets:wo_view`
- `wo_create` -> `django:assets:wo_create`
- `wo_close` -> `django:assets:wo_close`
- `reports` -> `django:assets:reports`
- `periodic_verifications` -> `django:assets:periodic_verifications`
- `software_license_list` -> `django:assets:software_license_list`

Dopo il seed, assegna i permessi per ruolo nella tabella legacy `permessi` (o da pannello admin ACL).

## Topbar (navigation registry)
Opzione command:

```bash
python manage.py seed_assets_nav
```

Viene creata la voce `NavigationItem(code="assets", label="Asset", route_name="assets:asset_list", section="topbar")`.

Alternativa: inserimento manuale da `/admin-portale/navigation-builder/`.

## Campi personalizzati (admin)
- Nella pagina `/assets/` gli admin (superuser o admin legacy) possono:
  - creare nuovi campi compilabili (testo, numero, data, si/no),
  - rinominare i campi,
  - riordinarli,
  - disattivarli o eliminarli.
- I campi attivi compaiono direttamente nel form `Nuovo asset` / `Modifica asset`.
- I valori vengono salvati in `Asset.extra_columns` usando il `code` del campo (stabile), cosi la rinomina non perde i dati.

## Liste precompilate (admin)
- Dalla pagina `/assets/`, sezione "Liste precompilate", puoi gestire i valori suggeriti per:
  - `Reparto`
  - `Manufacturer`
  - `Model`
  - `Assignment to`
  - `Assignment reparto`
  - `Assignment location`
- I campi restano sempre modificabili manualmente: la lista e solo un aiuto di compilazione.

## Pulsanti pagina dettaglio (admin)
- Dalla pagina `/assets/`, sezione "Pulsanti pagina dettaglio", puoi creare/ordinare/disattivare pulsanti per:
  - `Header`
  - `Quick Actions`
- Tipi azione supportati:
  - `Link` (target configurabile)
  - `Print`
  - `Refresh`
- Placeholder supportati nel target:
  - `{asset_id}`, `{asset_tag}`, `{asset_name}`, `{asset_type}`, `{assigned_user_id}`

## Manutenzione periodica
- La pagina canonica `/assets/manutenzione/verifiche/` consente di configurare i piani di manutenzione periodica collegati agli asset. Il vecchio percorso `/assets/verifiche-periodiche/` resta disponibile come redirect compatibile.
- Per ogni piano puoi gestire:
  - nome piano
  - fornitore responsabile (`anagrafica.Fornitore`)
  - frequenza in mesi
  - ultima manutenzione e prossima manutenzione
  - stato attivo/disattivo
  - note interne
  - uno o piu asset coinvolti
- Ogni asset puo appartenere a piu piani di manutenzione periodica contemporaneamente.
- La selezione della manutenzione periodica e disponibile anche nei form `Nuovo/Modifica asset` e `Nuova/Modifica macchina di lavoro`, oltre che nella scheda dettaglio asset.
- La schermata di gestione include layout selezionabile lato utente (`Compatta`, `Bilanciata`, `Ampia`) memorizzato nel browser.
- La selezione asset supporta ricerca live per tag/nome e azioni rapide `Seleziona visibili` / `Pulisci`.

## Interventi / Work order
- Le pagine operative di manutenzione, scadenzario, interventi, report e template report condividono una sotto-navigazione con breadcrumb e tab `Da fare`, `Scadenzario`, `Interventi`, `Report`, `Template report`, `Impostazioni`, piu azioni rapide per `Nuovo intervento`, export OdL e impostazioni, cosi l'utente resta orientato tra consultazione e azioni operative.
- L'hub manutenzione usa una sola fascia di priorita (interventi aperti, scaduti, attivita in avvicinamento, completati), seguita dal lavoro operativo filtrabile e da una sola agenda laterale a 7 giorni. Le azioni globali restano nella toolbar e nella sotto-navigazione, evitando duplicazioni. I KPI della dashboard report continuano a portare a scadenzario, registro OdL o liste filtrate; il budget per categoria rimanda al registro OdL gia filtrato.
- `/assets/manutenzione/` evidenzia nel tab **Da fare** anche le regole manutenzione effettive con stato critico (`overdue`, `warning`, `missing`), calcolate dallo stesso motore di `/assets/manutenzione/prossime/`. Ogni riga porta all'asset, alla creazione OdL o alla baseline della prima esecuzione.
- `/assets/workorders/` e' la coda operativa degli interventi: apre sugli OdL aperti e offre le viste rapide `Aperti`, `Assegnati a me`, `Non assegnati` e `Chiusi`. Ricerca e presa in carico sono immediate; tipo, origine, copertura, reparto, categoria, responsabile e anzianita restano disponibili in `Altri filtri`, con chip rimovibili. La tabella principale mostra solo intervento, asset, gestione, tempistiche e azioni; costi e contratto restano nel dettaglio e negli export XLSX/PDF.
- Il form `Nuovo intervento` e' un flusso guidato utilizzabile sia per guasti sia per manutenzioni pianificate: asset in evidenza, tipo/titolo/descrizione prima dei dettagli tecnici, risoluzione subito disponibile ma opzionale, impatto e allegati separati. Regola, manutenzione periodica, fornitore e contratto restano accessibili in `Pianificazione e copertura`, aperto automaticamente quando il contesto lo richiede.
- Il form consente sia `Crea intervento` (rimane aperto) sia `Crea e vai alla chiusura`, utile per consuntivare subito un'attivita gia svolta.
- La chiusura OdL (`/assets/workorders/close/<id>/`) e' un atto formale: esito completato/annullato, data e ora editabili (default ora corrente), risoluzione obbligatoria se completato, zero/una/piu giornate di esecuzione e tempo indicativo totale in ore/minuti. Registra inoltre fermo, costi manodopera/materiali/totale, assegnato/eseguito da e allegati finali (`close_attachments`) validati come gli altri documenti asset.

## Assegnazione asset <-> dipendente
- Da pagina asset (`/assets/assign/<id>/`) puoi assegnare il singolo asset a un dipendente attivo.
- Da scheda dipendente admin (`/admin-portale/utenti/<id>/`, tab Anagrafica) puoi assegnare in blocco uno o piu asset.
- Il salvataggio bulk e "replace": gli asset selezionati vengono assegnati al dipendente, quelli prima assegnati ma non piu selezionati vengono sganciati.

## Rinomina massiva solo nome asset
Command sicuro per aggiornare esclusivamente `Asset.name`, lasciando invariati `asset_tag`, categorie, stato, reparto, SharePoint e relazioni:

```bash
python manage.py rename_asset_names --export-template asset_names.csv
python manage.py rename_asset_names asset_names.csv --dry-run
python manage.py rename_asset_names asset_names.csv --commit
```

Il template contiene `asset_tag;current_name;new_name`: modifica solo `new_name`, poi controlla il dry-run prima del commit. Se parti dall'export della lista asset, usa `Tag` come colonna identificativa e passa la colonna del nuovo nome con `--name-column`, ad esempio:

```bash
python manage.py rename_asset_names asset_export.csv --tag-column Tag --name-column "Nuovo Nome" --dry-run
```

## Import Excel massivo
Command:

```bash
python manage.py import_assets_excel --file "CN - Asset Inventory (1).xlsx"
```

Esempi utili:

```bash
python manage.py import_assets_excel --dry-run
python manage.py import_assets_excel --include-optional
python manage.py import_assets_excel --all-sheets
python manage.py import_assets_excel --sheets "LAN A 203.0.113.x,LAN C 192.0.2.x"
python manage.py import_assets_excel --no-update
```

Supporto fogli:

- default: `LAN A 203.0.113.x`, `LAN B 198.51.100.x`, `LAN C 192.0.2.x`
- opzionali (con `--include-optional`): `CCTV 198.51.100.X`, `GUEST-LAN 203.0.113.X`, `MASS-STORAGE`, `Telefonia`, `SIM Telefonica`
- matching nomi foglio flessibile (case-insensitive/fuzzy), con fallback su tutti i fogli se quelli richiesti non esistono.

Colonne dinamiche:

- se nel file ci sono colonne extra (es. campi esclusivi per macchinario), vengono create automaticamente come `AssetCustomField` e salvate in `Asset.extra_columns`.
- tipizzazione automatica base: testo/numero/data/si-no.

## Macchine di lavoro
- I macchinari di officina possono essere gestiti come `Asset` con `asset_type="WORK_MACHINE"` e dettagli dedicati nella tabella `WorkMachine`.
- La relazione e `1:1`: `Asset` resta il master record (tag, nome, stato, reparto), `WorkMachine` contiene le colonne specifiche di officina.

## Link pubblici QR SharePoint
- Il QR pubblico usa `/assets/public/<public_qr_token>/`, che reindirizza solo a `sharepoint_public_url` quando il link pubblico read-only e attivo.
- Se `SITE_URL` e configurato, i PDF etichetta usano quella base canonica per le route QR (es. `https://hub.cnovicrom.local/assets/public/<token>/`) invece dello scheme visto dalla request interna IIS/Waitress.
- La creazione automatica e controllata da `SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED` (default `false`) e non cambia permessi tenant/sito.
- Le impostazioni `SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED`, `SHAREPOINT_ASSET_ALLOWED_ROOT_NAME`, `SHAREPOINT_ASSET_ALLOWED_ROOT_DRIVE_ID`, `SHAREPOINT_ASSET_ALLOWED_ROOT_ITEM_ID`, `SHAREPOINT_ASSET_SITE_ID` e `SHAREPOINT_ASSET_DRIVE_ID` sono gestibili sia dal pannello centrale `/admin-portale/hub/setup-wizard/#sec-graph` sia dalla tab configurazione di `/assets/impostazioni/`; entrambe le pagine salvano le stesse chiavi `.env`.
- Sono eleggibili solo cartelle asset verificabili sotto `SHAREPOINT_ASSET_ALLOWED_ROOT_NAME` (default `ASSET CN`), con `sharepoint_drive_id` e `sharepoint_item_id`.
- Riconversione asset esistenti:

```bash
python manage.py assets_ensure_public_share_links --dry-run
python manage.py assets_ensure_public_share_links --apply --only-missing
python manage.py assets_ensure_public_share_links --apply --asset-tag "APLCP142-MATR.PI-I-2286"
```

Import dedicato:

```bash
python manage.py import_work_machines_excel --file "Macchine di lavoro.xlsx"
python manage.py import_work_machines_excel --file "Macchine di lavoro.xlsx" --dry-run
python manage.py import_work_machines_excel --file "Macchine di lavoro.xlsx" --sheet "Foglio1"
```

Campi importati:
- `REPARTO`, `Name`
- `X/Y/Z (mm)`, `Ø (mm)`, `Spindle (mm)`
- `Year`, `TMC`, `TCR`, `Pressure (bar)`, `CNC`, `5 AXES`, `Accuracy from`

Note:
- i duplicati con stesso nome ma anno diverso vengono gestiti come asset distinti;
- il matching di update usa una chiave stabile basata su foglio + reparto + nome + anno (o dimensioni se anno assente).

Note sicurezza:

- Campi sensibili (`PSW BIOS`, PIN/PUK, password) non vengono salvati in chiaro.
- `PSW BIOS` viene importato solo come flag booleano `bios_pwd_set`.
- Altri campi sensibili vengono salvati solo come flag di presenza (`... (presente)`), mai come valore originale.
- Eventuali riferimenti sicuri possono essere tracciati in `vault_ref` (testuale).

## Import catalogo asset CSV/XLSX
Command dedicato per liste normalizzate con `famiglia` e `sottocategoria`:

```bash
python manage.py import_assets_catalog "lista_asset_normalizzata_import_portale.csv" --dry-run
python manage.py import_assets_catalog "lista_asset_normalizzata_import_portale.xlsx" --commit
```

Il comando crea categorie padre da `famiglia`, sottocategorie figlie da `sottocategoria` e asset collegati alla sottocategoria. Supporta CSV UTF-8 con fallback `cp1252`, separatori `;`/`,` e XLSX via `openpyxl`.

Dettagli operativi: [docs/assets/IMPORT_ASSETS.md](../../docs/assets/IMPORT_ASSETS.md).
