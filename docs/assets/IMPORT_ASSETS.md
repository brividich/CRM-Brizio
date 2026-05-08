# Import catalogo asset

`import_assets_catalog` importa un catalogo CSV/XLSX creando in modo idempotente:

- categorie padre asset da `famiglia`;
- sottocategorie figlie da `sottocategoria`;
- asset collegati alla sottocategoria.

## Comandi

```powershell
python django_app\manage.py import_assets_catalog "C:\path\lista_asset.csv" --dry-run --settings=config.settings.test
python django_app\manage.py import_assets_catalog "C:\path\lista_asset.xlsx" --commit --settings=config.settings.test
```

`--dry-run` non scrive a database e mostra conteggi + errori riga per riga.
`--commit` esegue l'import in `transaction.atomic()` e si ferma senza scrivere se trova errori bloccanti.

## Colonne supportate

Minime:

- `famiglia` obbligatoria;
- `sottocategoria` obbligatoria;
- `asset_id` opzionale.

Opzionali:

- `descrizione`;
- `nome`;
- `ubicazione`;
- `matricola`;
- `stato`.

Gli header sono normalizzati con trim, spazi multipli collassati e matching case-insensitive. I CSV sono letti in UTF-8 con fallback `cp1252` e separatore `;` o `,`.

## Codici asset

Se `asset_id` e' presente viene validato e usato come `Asset.asset_tag` univoco, per esempio:

```text
APLCP142-MATR.PI-I-2286
CN-ANT
CN-Z
CN-BLSD
```

Se `asset_id` manca, il servizio `AssetCodeGenerator` genera un codice stabile a partire dai dati riga.

I codici `CN-*` sono importati come asset reali, non come categorie. Per questi record vengono valorizzati `notes = "Asset generico CN"` ed `extra_columns["is_generic_asset"] = true`.

## Idempotenza

Il matching usa `asset_id` quando presente e una `source_key` stabile quando assente. Rilanciare lo stesso file aggiorna i campi consentiti senza creare duplicati.

Campi aggiornati sugli asset esistenti: nome, tipo, categoria, ubicazione/reparto, matricola, stato, source key e note CN generiche.
