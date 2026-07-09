# Guida — Import storico Suggestion Corner (SMS) su PROD

Import una tantum dei record storici del «Registro SMS_Suggestion Corner» (ex Microsoft
Forms) nel modulo `suggestion_corner`. **47 record** già convertiti in JSON.

> ⚠️ **Dati personali**: il file `sms_storico.json` contiene nomi reali (autori,
> incaricati, controllori). Tienilo **fuori dal repo git**, non committarlo, non
> incollarlo in chat/log. Cancellalo dopo l'import.

---

## 0. File coinvolti

| File | Cos'è | Dove sta ora |
|---|---|---|
| `sms_storico.json` | i 47 record convertiti (nomi reali) | scratchpad dev / cartella `_import` |
| `reparto_map.json` | mappa nomi reparto CSV→catalogo prod | `docs/` (template) → copia in `_import` |
| `import_sms_prod.ps1` | runbook PowerShell a fasi | scratchpad dev / cartella `_import` |
| `GUIDA_IMPORT_SMS_PROD.md` | questa guida | `docs/` |

Su prod crea una cartella di lavoro **fuori dal checkout**, es. `C:\PortaleNovicrom\prod\_import\`,
e copiaci i file operativi (`sms_storico.json`, `reparto_map.json`, `import_sms_prod.ps1`).

### Come si rigenera `sms_storico.json` (da dev)

Il JSON si ottiene dal CSV di export con il comando `converti_sms_storico` (sola lettura,
risolve i nomi sull'anagrafica; scrive **fuori dal repo**):

```powershell
.\.venv\Scripts\python.exe django_app\manage.py converti_sms_storico `
  --file "Registro SMS_Suggestion Corner.csv" `
  --out "<cartella_fuori_repo>\sms_storico.json" `
  --settings=config.settings.dev
```

---

## 1. Prerequisito: il modulo dev'essere deployato su prod

Le tabelle `suggestion_corner_*` esistono solo se il modulo è stato **deployato e migrato**.
Include il commit `90e7e69` (opzione `--reparto-map`), quindi il branch va prima
**pushato e deployato** su prod.

Verifica (dev'essere tutto `[X]`):

```powershell
& C:\PortaleNovicrom\prod\venv\Scripts\python.exe `
  C:\PortaleNovicrom\prod\current\django_app\manage.py `
  showmigrations suggestion_corner --settings=config.settings.prod
```

Se compaiono `[ ]` o errore «no such table» → **fai prima deploy + migrate**. Lo script
si ferma da solo se il modulo non è deployato.

---

## 2. Come funziona l'import (cosa aspettarsi)

- **Dry-run di default**: senza `-Apply` non scrive nulla, mostra solo il report.
- **Idempotente**: rilanciandolo non duplica (chiave `legacy_sharepoint_id`).
- **Reparto provenienza = obbligatorio**: se il nome CSV non è nel catalogo prod, quel
  record viene **scartato** (finisce in «Reparti non trovati»).
- **Reparto destinazione e persone**: se non trovati diventano vuoti, il record entra
  comunque.
- **Stato PDCA** già derivato dai flag P/D/C/A del registro; **stato SMS** (`SMS_SI`/`SMS_NO`)
  tal quale — `SMS_SI` = da gestire come segnalazione SMS con comunicazione al cliente.

Distribuzione dei 47 record: 34 CHECK_COMPLETATO · 10 DO_COMPLETATO · 1 CHIUSA ·
1 PLAN_DEFINITO · 1 DA_CLASSIFICARE. SMS: 42 NO · 4 SI · 1 DA_GESTIRE.

---

## 3. Il mapping reparti (il punto delicato)

Il CSV usa 17 nomi di reparto di provenienza, alcuni non allineati al catalogo prod:

```
UFFICIO TECNICO, CN5, CQ, Altro, AGGIUSTAGGIO, AMMINISTRAZIONE, MARCATURA,
CNC, Generico, QUALITA', LOG, IT, LOGISTICA, TORNI, MAGAZZINO, SALA TAGLIO, DIREZIONE
```

`reparto_map.json` parte così (i due chiaramente non-reparto vengono ignorati):

```json
{
  "Altro": "",
  "Generico": ""
}
```

**Non indovinare gli altri a memoria**: il dry-run (Fase 0 dello script) stampa il
**catalogo Reparto reale di prod**. Regola:

1. lancia il dry-run;
2. per ogni voce in «Reparti non trovati», aggiungi una riga alla mappa:
   - `"NOME_CSV": "NOME_CATALOGO_ESATTO"` per rimappare (attenzione a maiuscole/apostrofi,
     es. `QUALITA'`);
   - `"NOME_CSV": ""` per ignorare il reparto (record entra senza reparto — **solo se** il
     nome non è un reparto reale; ricorda che la provenienza è obbligatoria, quindi `""`
     sulla provenienza fa **scartare** il record);
3. rilancia il dry-run finché «Reparti non trovati» è **vuoto** e i numeri tornano.

> Nota: se `LOG` e `LOGISTICA` esistono **entrambi** nel catalogo prod, lasciali com'è
> (nessuna riga nella mappa) — combaciano già.

---

## 4. Esecuzione

### 4a. Dry-run (ripeti finché pulito)

```powershell
cd C:\PortaleNovicrom\prod\_import
.\import_sms_prod.ps1 -JsonFile .\sms_storico.json -RepartoMap .\reparto_map.json
```

Leggi in fondo il report:
- `Creati:` = quanti verrebbero importati
- `Reparti non trovati:` = **deve diventare vuoto** (aggiorna la mappa)
- `Persone non trovate:` = accettabile (entrano senza persona), ma controlla che siano poche

### 4b. Apply (scrittura reale)

Quando il dry-run è pulito:

```powershell
.\import_sms_prod.ps1 -JsonFile .\sms_storico.json -RepartoMap .\reparto_map.json -Apply
```

Se serve un `ProdRoot` diverso dal default `C:\PortaleNovicrom\prod`, aggiungi
`-ProdRoot <percorso>`.

---

## 5. Verifica post-import

```powershell
& C:\PortaleNovicrom\prod\venv\Scripts\python.exe `
  C:\PortaleNovicrom\prod\current\django_app\manage.py shell --settings=config.settings.prod `
  -c "from suggestion_corner.models import SuggestionCorner as S; print('totale importati:', S.objects.filter(da_portale=False).count())"
```

Poi in UI: **`/suggestion-corner/`** (con utente del team SMS) e in Django admin
**`/admin/suggestion_corner/suggestioncorner/`**.

---

## 6. Rollback

L'import non ha un «undo» automatico. Se qualcosa va storto **dopo l'apply**, i record
importati sono riconoscibili da `da_portale=False` + `legacy_sharepoint_id` valorizzato.
Rimozione mirata (solo se necessario, con backup DB fatto prima):

```powershell
& ...\python.exe ...\manage.py shell --settings=config.settings.prod `
  -c "from suggestion_corner.models import SuggestionCorner as S; S.objects.filter(da_portale=False, legacy_sharepoint_id__isnull=False).delete()"
```

> Fai **sempre un backup del DB** prima dell'apply su prod.

---

## 7. Pulizia finale

- cancella `sms_storico.json` da prod (contiene nomi reali);
- conserva `reparto_map.json` completato (utile come traccia del mapping usato).
