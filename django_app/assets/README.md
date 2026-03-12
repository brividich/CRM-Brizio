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

## Verifiche periodiche
- La pagina `/assets/verifiche-periodiche/` consente di configurare verifiche ricorrenti collegate agli asset.
- Per ogni verifica puoi gestire:
  - nome verifica
  - fornitore responsabile (`anagrafica.Fornitore`)
  - frequenza in mesi
  - ultima verifica e prossima verifica
  - stato attivo/disattivo
  - note interne
  - uno o piu asset coinvolti
- Ogni asset puo appartenere a piu verifiche periodiche contemporaneamente.
- La selezione delle verifiche e disponibile anche nei form `Nuovo/Modifica asset` e `Nuova/Modifica macchina di lavoro`, oltre che nella scheda dettaglio asset.
- La schermata di gestione include layout selezionabile lato utente (`Compatta`, `Bilanciata`, `Ampia`) memorizzato nel browser.
- La selezione asset supporta ricerca live per tag/nome e azioni rapide `Seleziona visibili` / `Pulisci`.

## Assegnazione asset <-> dipendente
- Da pagina asset (`/assets/assign/<id>/`) puoi assegnare il singolo asset a un dipendente attivo.
- Da scheda dipendente admin (`/admin-portale/utenti/<id>/`, tab Anagrafica) puoi assegnare in blocco uno o piu asset.
- Il salvataggio bulk e "replace": gli asset selezionati vengono assegnati al dipendente, quelli prima assegnati ma non piu selezionati vengono sganciati.

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
