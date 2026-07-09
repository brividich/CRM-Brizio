# Guida — Import storico Diario Preposto su PROD

Import dei record storici delle segnalazioni preposto (CSV export) nel modulo
`diario_preposto` (modello `SegnalazionePreposto`), comando `import_preposto_csv`.

> ⚠️ **Dati personali (GDPR)**: il CSV contiene nominativi (chi segnala, nominativo
> segnalato) e descrizioni di comportamenti. Tienilo **fuori dal repo git**, non
> committarlo, non incollarlo in chat/log, e cancellalo dopo l'import. Modulo di
> sicurezza: preserva audit trail e privacy.

---

## 0. Comando e opzioni

```
manage.py import_preposto_csv <csv_path>
        [--dry-run] [--delimiter ,] [--encoding utf-8-sig]
        [--limit N] [--created-by <username_django>]
```

| Opzione | Cosa fa | Default |
|---|---|---|
| `csv_path` | percorso del CSV (posizionale, obbligatorio) | — |
| `--dry-run` | simula e **fa rollback** (nessuna scrittura) | assente = **scrive** |
| `--delimiter` | separatore colonne | `,` |
| `--encoding` | encoding del file | `utf-8-sig` |
| `--limit N` | processa al massimo N righe (0 = tutte) | `0` |
| `--created-by` | username Django associato a `creato_da` sui nuovi record | vuoto |

> ⚠️ **Attenzione**: a differenza dell'import SMS, qui **il default SCRIVE**.
> Per la simulazione devi passare **`--dry-run`** esplicito.

---

## 1. Prerequisito: modulo deployato su prod

Le tabelle `diario_preposto_*` devono esistere (modulo deployato + migrato):

```powershell
& C:\PortaleNovicrom\prod\venv\Scripts\python.exe `
  C:\PortaleNovicrom\prod\current\django_app\manage.py `
  showmigrations diario_preposto --settings=config.settings.prod
```

Tutto `[X]`. Se `[ ]` → deploy + migrate prima.

---

## 2. Formato CSV atteso

Il file **deve** contenere queste 4 colonne di intestazione (nomi esatti):

```
Chi segnala,Data segnalazione,Nominativo Segnalato,Descrizione della segnalazione
```

- **Data segnalazione**: formato `gg/mm/aaaa hh:mm` (es. `15/03/2024 09:30`). Vuota o
  formato diverso → riga **saltata**.
- **Chi segnala** → mappato su `preposto` **e** `chi_segnala`.
- **Nominativo Segnalato** → mappato su `titolo`.
- **Descrizione della segnalazione** → `descrizione` (multiriga ammessa).
- Righe con uno dei tre campi obbligatori (chi segnala / nominativo / descrizione) vuoto
  → **saltate** con warning.

Esempio (dati sintetici):

```csv
Chi segnala,Data segnalazione,Nominativo Segnalato,Descrizione della segnalazione
Mario Rossi,15/03/2024 09:30,Luigi Bianchi,Mancato uso dei DPI in area taglio
```

---

## 3. Idempotenza (rilanciabile senza duplicare)

L'import fa **upsert** su una **chiave naturale**: `data_segnalazione` + `titolo` +
`chi_segnala`.

- 0 match → **crea** (`inserted`).
- 1 match → **aggiorna** `descrizione`/`preposto` se cambiati (`updated`), altrimenti
  `unchanged`; valorizza `creato_da` se era vuoto e passi `--created-by`.
- >1 match (duplicati già presenti) → riga **saltata** (`skipped`) con warning: vanno
  risolti a mano.

Quindi **rilanciare non duplica**.

---

## 4. Esecuzione

### 4a. Dry-run (consigliato prima)

```powershell
& C:\PortaleNovicrom\prod\venv\Scripts\python.exe `
  C:\PortaleNovicrom\prod\current\django_app\manage.py `
  import_preposto_csv "C:\PortaleNovicrom\prod\_import\diario_preposto.csv" `
  --dry-run --created-by <username_admin> --settings=config.settings.prod
```

Leggi il riepilogo finale: `rows / inserted / updated / unchanged / skipped`.
Controlla che gli `skipped` siano attesi (righe vuote/duplicate) e i numeri tornino.

### 4b. Import reale (togli `--dry-run`)

```powershell
& C:\PortaleNovicrom\prod\venv\Scripts\python.exe `
  C:\PortaleNovicrom\prod\current\django_app\manage.py `
  import_preposto_csv "C:\PortaleNovicrom\prod\_import\diario_preposto.csv" `
  --created-by <username_admin> --settings=config.settings.prod
```

> `--created-by` deve essere un **username Django esistente** (altrimenti il comando
> esce con errore). Serve solo per attribuire l'autore dei record importati.

---

## 5. Verifica post-import

```powershell
& C:\PortaleNovicrom\prod\venv\Scripts\python.exe `
  C:\PortaleNovicrom\prod\current\django_app\manage.py shell --settings=config.settings.prod `
  -c "from diario_preposto.models import SegnalazionePreposto as S; print('totale:', S.objects.count())"
```

Poi in UI: **`/diario-preposto/`**. Admin: **`/admin/diario_preposto/segnalazionepreposto/`**.

---

## 6. Rollback

Nessun undo automatico. Se serve annullare **subito dopo** un import andato male, la via
sicura è il **ripristino del backup DB** fatto prima. Rimozione mirata solo con estrema
cautela e backup disponibile (non c'è un flag `da_portale` come nell'SMS: i record
importati non sono distinguibili da quelli inseriti a mano se non per data/contenuto).

> Fai **sempre un backup del DB** prima dell'import reale su prod.

---

## 7. Pulizia finale

- cancella il CSV da prod (contiene nominativi reali);
- l'import è ripetibile: in caso di dubbio rilancia in `--dry-run` per confrontare i conteggi.
