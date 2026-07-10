# Guida — Import storico Segnalazioni Sicurezza (rilevazioni incidenti) su PROD

Import dei record storici delle rilevazioni di sicurezza (near miss / unsafe / incidenti)
esportati da SharePoint/Power Apps nel modulo `rilevazione_incidenti`
(modello `RilevazioneIncidente`), comando `importa_rilevazioni_csv`.

> ⚠️ **Dati personali (GDPR)**: il CSV contiene nominativi, persone coinvolte,
> partecipanti e descrizioni di eventi. Tienilo **fuori dal repo git**, non committarlo,
> non incollarlo in chat/log, cancellalo dopo l'import. Modulo di sicurezza: preserva
> audit trail e privacy.

---

## 0. Comando e opzioni

```
manage.py importa_rilevazioni_csv <csv_file> [--clear] [--skip-existing]
```

| Opzione | Cosa fa |
|---|---|
| `csv_file` | percorso del CSV (posizionale, obbligatorio) |
| `--skip-existing` | salta le righe il cui **ID** originale è già a DB (idempotenza) |
| `--clear` | **ELIMINA TUTTI** i record esistenti prima di importare (distruttivo) |

> 🔴 **DUE AVVERTENZE CRITICHE**, diverse dagli altri import:
> 1. **NON esiste `--dry-run`**: il comando **scrive subito**. Non c'è simulazione.
> 2. **Senza `--skip-existing` rilanciare DUPLICA** (l'idempotenza non è automatica).
>
> Regola operativa su prod: **backup DB → prima prova su una copia/dev → poi prod con
> `--skip-existing`**. Usa `--clear` solo per un reimport pulito e consapevole.

---

## 1. Prerequisito: modulo deployato su prod

```powershell
& C:\PortaleNovicrom\prod\venv\Scripts\python.exe `
  C:\PortaleNovicrom\prod\current\django_app\manage.py `
  showmigrations rilevazione_incidenti --settings=config.settings.prod
```

Tutto `[X]`. Se `[ ]` → deploy + migrate prima.

---

## 2. Formato CSV atteso (esatto, con typo originali)

Encoding **`utf-8-sig`**, separatore **`,`** (fissi, non configurabili). Il comando legge
le colonne **per nome esatto** dall'export originale: alcune intestazioni contengono
**typo e spazi finali intenzionali** — vanno lasciate **così come sono**, altrimenti la
colonna viene letta come vuota (il comando **non fallisce**, importa il campo vuoto).

Intestazioni riconosciute:

```
Nominativo | Tipologia scheda | Reparto | Reparto_txt | Data segnalazione |
Descrizione attività che venivano svolte durante l'accaduto |
Descrizione avvenimento  (← spazio finale) |
Incidenti causato da uso macchina | Nome macchina/attrezzatura e utilizoz (← typo) |
Buono stato macchina/attrezzatura | Utilizo DPI previsti (← typo) |
Prima volta quasi incidente | Persone coinvolte  (← spazio finale) |
Causa che ha determinato l'evento | Altre cause |
Misure tecniche, organizzative o procedurali per evitare che possa riaccedere questo genere di evento |
Quali misure adottare | Approvazione RLS | Note preposto | Note RSPP / ASPP |
Data approvazione RLS | Chiusura RSPP | Data chiusura RSPP |
ID | Contatore | Partecipanti | 1 WHY | 2 WHY | 3 WHY | 4 WHY | 5 WHY
```

Note sul parsing:
- **ID** = identificativo originale SharePoint → usato da `--skip-existing`. Se manca, il
  record viene comunque creato ma **non sarà de-duplicabile** in run successivi.
- **Reparto**: usa `Reparto_txt` se valorizzato, altrimenti `Reparto` (testo libero, nessun
  catalogo da mappare — a differenza dell'SMS).
- **Date** (`Data segnalazione`, approvazione, chiusura): accetta `gg/mm/aaaa hh:mm`,
  `gg/mm/aaaa`, ISO `aaaa-mm-ggThh:mm:ss`, `aaaa-mm-gg`. Non parsabile → vuoto.
- **Booleani** (`uso macchina`, `buono stato`, `DPI`, `prima volta`, `misure tecniche`,
  `chiusura RSPP`): veri se `Vero/True/1/Si/Sì/Yes`.

---

## 3. Esecuzione

### 3a. Prova preliminare (obbligatoria, non c'è dry-run)

Non esistendo il dry-run, testa **su dev** o su una **copia del DB** prima di prod:

```powershell
.\.venv\Scripts\python.exe django_app\manage.py `
  importa_rilevazioni_csv "<percorso>\rilevazioni.csv" `
  --skip-existing --settings=config.settings.dev
```

Verifica il conteggio finale (`creati / saltati / errori`) e ispeziona qualche record.

### 3b. Import su prod

```powershell
& C:\PortaleNovicrom\prod\venv\Scripts\python.exe `
  C:\PortaleNovicrom\prod\current\django_app\manage.py `
  importa_rilevazioni_csv "C:\PortaleNovicrom\prod\_import\rilevazioni.csv" `
  --skip-existing --settings=config.settings.prod
```

Output: `Importazione completata: N creati, M saltati, K errori.` Gli errori riga-per-riga
finiscono su stderr con numero di riga.

> **Reimport pulito** (solo se davvero necessario, cancella tutto lo storico prima):
> aggiungi `--clear`. Irreversibile senza backup.

---

## 4. Verifica post-import

```powershell
& C:\PortaleNovicrom\prod\venv\Scripts\python.exe `
  C:\PortaleNovicrom\prod\current\django_app\manage.py shell --settings=config.settings.prod `
  -c "import collections; from rilevazione_incidenti.models import RilevazioneIncidente as R; print('totale:', R.objects.count()); print(collections.Counter(R.objects.values_list('tipologia_scheda', flat=True)))"
```

Sul modello ci sono **due** campi tipologia, entrambi popolati correttamente all'import:
- `tipologia_scheda` — etichetta legacy testuale (es. `Near Miss`, `Unsafe Act`), presa
  dal CSV e normalizzata;
- `tipo_evento` — **categoria KPI** con scelte fisse (`near_miss` / `unsafe_condition` /
  `incidente`), **dedotta automaticamente** dal `save()` del modello tramite
  `normalize_tipo_evento(tipologia_scheda)`. È il campo usato per statistiche/heatmap.

Il conteggio qui sopra (`Counter` su `tipologia_scheda`) mostra le etichette legacy; per i
KPI conta `tipo_evento`. La derivazione è coperta da test
(`rilevazione_incidenti.tests.ImportaRilevazioniCsvTests`), quindi non serve alcun
allineamento manuale post-import.

Poi in UI: **`/rilevazione-incidenti/`**. Admin:
**`/admin/rilevazione_incidenti/rilevazioneincidente/`**.

---

## 5. Rollback

Nessun undo automatico e **nessun flag** che marchi i record importati. L'unica via sicura
è il **ripristino del backup DB**. Se hai importato con `ID` valorizzati, puoi in teoria
rimuovere per `id_originale`, ma solo con backup disponibile e massima cautela.

> Fai **sempre un backup del DB** prima di qualsiasi import (con o senza `--clear`).

---

## 6. Pulizia finale

- cancella il CSV da prod (contiene nominativi/persone coinvolte reali);
- annota da qualche parte quanti record erano attesi vs `creati` per il controllo incrociato.
