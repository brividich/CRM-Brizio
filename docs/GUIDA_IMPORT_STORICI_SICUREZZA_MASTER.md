# Guida MASTER — Import storici Sicurezza su PROD (SMS · Diario Preposto · Rilevazioni)

Runbook d'insieme per importare i tre storici in produzione, **nell'ordine giusto** e con
i controlli di sicurezza. Ogni modulo ha una guida di dettaglio; questa è la sequenza da
seguire dall'inizio alla fine.

| # | Modulo | Comando | Guida di dettaglio |
|---|---|---|---|
| 1 | Suggestion Corner (SMS) | `import_suggestion_corner_legacy` | `GUIDA_IMPORT_SMS_PROD.md` |
| 2 | Diario Preposto | `import_preposto_csv` | `GUIDA_IMPORT_DIARIO_PREPOSTO_PROD.md` |
| 3 | Segnalazioni Sicurezza (rilevazioni) | `importa_rilevazioni_csv` | `GUIDA_IMPORT_RILEVAZIONI_SICUREZZA_PROD.md` |

> ⚠️ **GDPR / dati personali**: tutti e tre i CSV/JSON contengono nomi reali. Tienili
> **fuori dal repo git**, in una cartella di lavoro dedicata su prod (es.
> `C:\PortaleNovicrom\prod\_import\`), e **cancellali a fine import**.

Convenzioni percorsi prod (modifica se il tuo ambiente differisce):
- Python: `C:\PortaleNovicrom\prod\venv\Scripts\python.exe`
- manage.py: `C:\PortaleNovicrom\prod\current\django_app\manage.py`
- settings: `config.settings.prod`

---

## FASE A — Preparazione (una volta sola)

### A1. Deploy del branch su prod
Il codice appena pushato (branch `feature/skill-matrix-mod187`) deve essere deployato su
prod: porta i moduli e l'opzione `--reparto-map` dell'SMS. Usa il tuo flusso di deploy
abituale (Setup Wizard / `deploy-release.ps1`). **Il deploy esegue anche il migrate.**

### A2. Verifica che i tre moduli siano migrati
Tutte le righe devono essere `[X]`:

```powershell
$py = "C:\PortaleNovicrom\prod\venv\Scripts\python.exe"
$mg = "C:\PortaleNovicrom\prod\current\django_app\manage.py"
& $py $mg showmigrations suggestion_corner    --settings=config.settings.prod
& $py $mg showmigrations diario_preposto       --settings=config.settings.prod
& $py $mg showmigrations rilevazione_incidenti --settings=config.settings.prod
```

Se qualcuna è `[ ]`:
```powershell
& $py $mg migrate --settings=config.settings.prod
```

### A3. Backup del database
**Obbligatorio prima di qualsiasi import** (soprattutto per il #3, che non ha dry-run).
Fai un backup SQL Server completo del DB di prod e verifica che sia leggibile.

### A4. Cartella di lavoro + file dati
Crea `C:\PortaleNovicrom\prod\_import\` e copiaci:
- `sms_storico.json` + `reparto_map.json` (per il #1)
- `diario_preposto.csv` (per il #2)
- `rilevazioni.csv` (per il #3)

---

## FASE B — Import #1: Suggestion Corner (SMS)

Il più elaborato: richiede la mappatura dei reparti. **Dry-run di default**, `--apply` per
scrivere. Dettagli in `GUIDA_IMPORT_SMS_PROD.md`.

### B1. Dry-run + catalogo reparti
```powershell
cd C:\PortaleNovicrom\prod\_import
& $py $mg import_suggestion_corner_legacy --file .\sms_storico.json `
  --reparto-map .\reparto_map.json --settings=config.settings.prod
```
Osserva **«Reparti non trovati»** nel report.

### B2. Completa `reparto_map.json`
Per ogni reparto non trovato aggiungi `"NOME_CSV": "NOME_CATALOGO"` (o `""` per ignorare).
Il catalogo reale di prod lo stampi con:
```powershell
& $py $mg shell --settings=config.settings.prod -c "from anagrafica.models import Reparto; [print(repr(r.nome)) for r in Reparto.objects.order_by('nome')]"
```
Ripeti B1 finché «Reparti non trovati» è **vuoto**.

### B3. Apply
```powershell
& $py $mg import_suggestion_corner_legacy --file .\sms_storico.json `
  --reparto-map .\reparto_map.json --apply --settings=config.settings.prod
```

### B4. Verifica
```powershell
& $py $mg shell --settings=config.settings.prod -c "from suggestion_corner.models import SuggestionCorner as S; print('SMS importati:', S.objects.filter(da_portale=False).count())"
```
UI: `/suggestion-corner/` — Admin: `/admin/suggestion_corner/suggestioncorner/`.

---

## FASE C — Import #2: Diario Preposto

**Attenzione**: il default **SCRIVE**; la simulazione è `--dry-run` esplicito. Idempotente
(upsert su data+titolo+chi segnala). Dettagli in `GUIDA_IMPORT_DIARIO_PREPOSTO_PROD.md`.

### C1. Dry-run
```powershell
& $py $mg import_preposto_csv .\diario_preposto.csv `
  --dry-run --created-by <username_admin> --settings=config.settings.prod
```
Controlla `rows / inserted / updated / unchanged / skipped`. Gli `skipped` devono essere
righe attese (vuote/duplicate).

### C2. Import reale (togli `--dry-run`)
```powershell
& $py $mg import_preposto_csv .\diario_preposto.csv `
  --created-by <username_admin> --settings=config.settings.prod
```

### C3. Verifica
```powershell
& $py $mg shell --settings=config.settings.prod -c "from diario_preposto.models import SegnalazionePreposto as S; print('Diario:', S.objects.count())"
```
UI: `/diario-preposto/`.

---

## FASE D — Import #3: Segnalazioni Sicurezza (rilevazioni)

🔴 **Il più delicato**: **NESSUN dry-run** (scrive subito) e **senza `--skip-existing`
duplica**. Dettagli in `GUIDA_IMPORT_RILEVAZIONI_SICUREZZA_PROD.md`.

### D1. Prova su dev/copia (non c'è dry-run su prod)
Testa prima su dev o su una copia del DB:
```powershell
.\.venv\Scripts\python.exe django_app\manage.py importa_rilevazioni_csv `
  "<percorso>\rilevazioni.csv" --skip-existing --settings=config.settings.dev
```
Verifica `creati / saltati / errori` e ispeziona qualche record.

### D2. Import su prod (con `--skip-existing`)
```powershell
& $py $mg importa_rilevazioni_csv .\rilevazioni.csv `
  --skip-existing --settings=config.settings.prod
```
> `--clear` (cancella tutto lo storico) **solo** per un reimport pulito e consapevole.

### D3. Verifica
```powershell
& $py $mg shell --settings=config.settings.prod -c "import collections; from rilevazione_incidenti.models import RilevazioneIncidente as R; print('Rilevazioni:', R.objects.count()); print(collections.Counter(R.objects.values_list('tipo_evento', flat=True)))"
```
`tipo_evento` (KPI) è derivato automaticamente — il `Counter` deve mostrare
`near_miss/unsafe_condition/incidente` coerenti. UI: `/rilevazione-incidenti/`.

---

## FASE E — Chiusura

- [ ] Conteggi verificati per tutti e tre i moduli (attesi vs importati)
- [ ] Cancella i file dati da `_import\` (contengono nomi reali)
- [ ] Conserva i `reparto_map.json` completati come traccia del mapping
- [ ] Se qualcosa è andato storto: **ripristina il backup DB** (Fase A3)

---

## Ordine e perché

1. **SMS per primo**: è idempotente e ha dry-run, quindi è il più sicuro per «scaldarsi»
   e prendere confidenza col catalogo reparti di prod.
2. **Diario Preposto**: idempotente, veloce; unico rischio è dimenticare `--dry-run`.
3. **Rilevazioni per ultimo**: è quello senza rete di sicurezza (no dry-run, `--clear`
   distruttivo) — meglio affrontarlo quando gli altri due sono già a posto e il backup è
   fresco.
