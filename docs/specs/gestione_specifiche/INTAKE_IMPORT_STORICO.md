# Prospetto di intake — Import storico specifiche (solo "In validità")

> Documento operativo per chi prepara i dati. L'import carica **solo** le
> specifiche attualmente **In validità** (decisione di processo F0 #5). Le
> revisioni superate/annullate **non** vanno importate: lo storico nasce dal
> sistema in avanti.

## 0. Scorciatoia: conversione automatica dai listoni del gestionale

Se parti dagli **export del gestionale** (invece di compilare a mano il CSV), usa
l'adattatore `converti_export_gestionale`, che li trasforma nei CSV di questo template:

- **SPTE** (Specifiche Tecniche, es. `OK SPTE AL …-…-….xls`) → `specifiche_spte.csv`
  (`fonte=generica`) **+ `allegati_spte.csv`** (codice;revisione;percorso UNC del PDF).
- **Specifiche Cliente** (`MOD.097 … .xlsx`, foglio `Registro`) → `specifiche_cliente.csv`
  (`fonte=cliente`).

```powershell
python django_app\manage.py converti_export_gestionale ^
    --spte    "C:\PortaleNovicrom\import\OK SPTE AL 25-6-26.xls" ^
    --cliente "C:\PortaleNovicrom\import\MOD.097 - SPE - Specifiche Cliente.xlsx" ^
    --out     "C:\PortaleNovicrom\import\csv" --settings=config.settings.prod
```

Regole "In validità" applicate: scarta codici vuoti/`0`; **esclude** le SPTE con `fvali`
valorizzato (sospese/superate — override con `--includi-fvali`); per i clienti tiene solo
`SOSP.=NO` e non superate; dedup su (codice, revisione); date convertite. **Titolo cliente**:
il Registro non ha un titolo → si usa il N° Documento. I CSV prodotti si validano/applicano
coi passi §4. *(File ed export vanno tenuti FUORI dal repo — dati reali.)*

## 1. Cosa serve da te

Un file **CSV** (UTF-8) compilato secondo il template
[`template_import_storico.csv`](template_import_storico.csv) (è disponibile anche
la versione [`.xlsx`](template_import_storico.xlsx)). Una riga per specifica.

Per **rigenerare** il template in qualunque momento:

```powershell
python django_app\manage.py import_specifiche_storico --genera-template docs\specs\gestione_specifiche\template_import_storico.csv --settings=config.settings.dev
```

## 2. Campi attesi (mappati 1:1 sul modello `Specifica`)

| Colonna | Obbligatorio | Tipo / Formato | Valori ammessi / Regole |
|---|---|---|---|
| `codice` | **Sì** | testo | Codice identificativo della specifica (es. `SPEC-2023-001`). |
| `revisione` | No (default `0`) | testo | Revisione **corrente** in validità (es. `0`, `2`, `A`). |
| `titolo` | **Sì** | testo | Titolo/descrizione. |
| `tipo` | **Sì** | choice | `specifica` \| `comunicazione` \| `piano_qualita` |
| `fonte` | **Sì** | choice | `cliente` \| `generica` |
| `cliente` | No | testo | Nominativo cliente (per `fonte=cliente`). |
| `tag` | No | testo | TAG di processo (singolo, es. `trattamenti_termici`). |
| `data_inserimento` | No | data `YYYY-MM-DD` | Data storica di emissione/inserimento (preservata). |
| `data_verifica` | No | data `YYYY-MM-DD` | Prossima verifica periodica prevista. |
| `note` | No | testo | Note libere. |
| `stato` | No (default `in_validita`) | choice | **Deve essere** `in_validita` (le altre righe vengono scartate). |
| `master_codice` | No | testo | Codice della specifica "master" (solo se la riga è un duplicato di un'altra già importata). |

### Formato e encoding
- **Encoding**: UTF-8 (il template è salvato UTF-8 con BOM, compatibile Excel).
- **Delimitatore**: `;` (punto e virgola). Per usare la virgola passare `--delimiter ,`.
- **Date**: rigorosamente `YYYY-MM-DD` (es. `2023-03-14`). Celle vuote ammesse dove non obbligatorie.
- **Caratteri accentati**: pienamente supportati (colonna DB NVARCHAR): `città`, `però`, `°`, ecc.

## 3. Data cleansing (prima di consegnare il file)

- **Duplicati**: l'import è idempotente sulla coppia (`codice`, `revisione`) — righe già presenti o ripetute vengono contate come `duplicato` e **non** ricreate. Verifica comunque l'assenza di doppioni logici.
- **Codici/revisioni malformati**: niente spazi iniziali/finali; revisione coerente (numerica o alfanumerica, ma **una sola** rev corrente per specifica).
- **Solo In validità**: rimuovi le righe di specifiche superate/annullate/duplicate (verranno scartate).
- **Choices**: `tipo` e `fonte` devono usare **esattamente** i valori ammessi (minuscolo, snake_case).
- **Date**: niente `gg/mm/aaaa`; converti in `YYYY-MM-DD`.

## 4. Dove depositare il file e come lanciare l'import

1. Deposita il CSV compilato in una cartella accessibile dal server (NON nel repo; **niente dati reali committati**), es. `C:\PortaleNovicrom\import\specifiche_storico.csv`.
2. **Validazione (dry-run, default — non scrive nulla):**
   ```powershell
   python django_app\manage.py import_specifiche_storico "C:\PortaleNovicrom\import\specifiche_storico.csv" --settings=config.settings.prod
   ```
   Il comando elenca righe **valide / duplicate / scartate** con il motivo dello scarto.
3. **Import reale** (dopo aver verificato il dry-run):
   ```powershell
   python django_app\manage.py import_specifiche_storico "C:\PortaleNovicrom\import\specifiche_storico.csv" --apply --settings=config.settings.prod
   ```

Ogni specifica importata nasce in stato **`in_validita`**, con `data_inserimento`
storica preservata e un evento di audit `EventoSpecifica(trigger="import_storico")`.

## 5. Allegati: PDF dalla share UNC

`import_specifiche_storico` carica **solo i metadati**. I PDF si agganciano dopo, in una di
due modalità (entrambe dry-run → `--apply`, idempotenti, da lanciare su una macchina che
vede la share e **dopo** l'import):

### 5a. COLLEGAMENTO (default consigliato — la share è il master unico)

La `Specifica` memorizza il **percorso UNC** (`percorso_esterno`) e la view protetta serve il
PDF **on-demand dalla share**: nessuna copia, sempre allineato al master (PDF protetti da
Adobe, cartella aggiornata da tutti) — coerente con ISO 9001/EN 9100.

```powershell
python django_app\manage.py collega_pdf_da_share "C:\PortaleNovicrom\import\csv\allegati_spte.csv" --settings=config.settings.prod           # dry-run
python django_app\manage.py collega_pdf_da_share "C:\PortaleNovicrom\import\csv\allegati_spte.csv" --apply --settings=config.settings.prod   # scrive
```

**Sicurezza**: si servono SOLO percorsi dentro le radici allowlist
`GESTIONE_SPECIFICHE_SHARE_ROOTS` (default `\\novisrv\Area Produzione\SPECIFICHE`), assoluti e
senza traversal, ri-validati ad ogni download. **Prerequisito**: all'app-pool IIS serve la
**sola lettura** su quella share (least privilege) perché il download funzioni in prod.

### 5b. COPIA cifrata (alternativa)

`allega_pdf_da_share` copia invece il PDF in `Specifica.allegato` (storage privato **cifrato**
at-rest). Usala solo se vuoi una copia locale indipendente dalla share.

```powershell
python django_app\manage.py allega_pdf_da_share "…\allegati_spte.csv" --apply --settings=config.settings.prod
```

> Lo script guidato `tools/import_specifiche_prod.ps1 -Apply` esegue tutta la catena
> (conversione → import → allegati) usando il **collegamento** di default (`-Copia` per la copia).

## 6. Cosa NON fa l'import

- Non importa revisioni non in validità (vengono scartate con motivo).
- Non genera MOD.133/OFI/distribuzioni storiche (lo storico processuale nasce in avanti).
- Non modifica righe già presenti (idempotente).
