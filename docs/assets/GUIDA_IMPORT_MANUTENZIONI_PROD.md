# Guida rapida — Import storico manutenzioni (collaudo) su PROD

> Importa lo storico collaudo/manutenzioni come Ordini di Lavoro storici + accende lo scadenzario.
> Tutti i comandi sono **dry-run di default**, scrivono solo con `--commit`, e sono **idempotenti** (ri-eseguirli non duplica).

## File necessari (già pronti in `C:\import_manutenzioni\`)

| File | Cos'è |
|---|---|
| `Causali manutenzione.xlsx` | catalogo causali collaudo (54 valide) |
| `storico collaudo.xlsx` | storico interventi (747 righe) |
| `riconciliazione_collaudo_macchine_PROD.xlsx` | mapping macchina→asset, colonna `CONFERMA` (22 macchine confermate) |

I primi due sono esclusi dai deploy (gitignored): vanno **copiati a mano** sul server.

## Prerequisiti

- Copia `C:\import_manutenzioni\` sul **server prod** (stesso percorso).
- Apri PowerShell sul server, attiva il venv di prod, posizionati nella root `django_app` del checkout `current`.
- Gli asset `CNC-*` devono già esistere a portale (l'import li **abbina**, non li crea).

## Ordine dei 3 comandi (obbligatorio)

1. `import_maintenance_causali` → crea i template causali *(atteso: ~54 create, 4 escluse A10-A13)*
2. `import_collaudo_history` → crea gli OdL storici chiusi *(atteso: ~186 OdL, 0 asset/template mancanti)*
3. `derive_collaudo_rules` → accende lo scadenzario *(atteso: ~17 regole + ~186 stati)*

Il passo 2 richiede i template del passo 1. Il passo 3 usa lo stesso storico+mapping.

## Passo 1 — DRY-RUN (verifica, non scrive)

```powershell
python manage.py import_maintenance_causali --file "C:\import_manutenzioni\Causali manutenzione.xlsx" --dry-run --settings=config.settings.prod
python manage.py import_collaudo_history --storico "C:\import_manutenzioni\storico collaudo.xlsx" --mapping "C:\import_manutenzioni\riconciliazione_collaudo_macchine_PROD.xlsx" --dry-run --settings=config.settings.prod
python manage.py derive_collaudo_rules --storico "C:\import_manutenzioni\storico collaudo.xlsx" --mapping "C:\import_manutenzioni\riconciliazione_collaudo_macchine_PROD.xlsx" --dry-run --settings=config.settings.prod
```

🚩 **STOP se** nel passo 2 vedi `asset mancante > 0` o `template mancante > 0`. Non fare il commit: verifica gli asset a portale / che il passo 1 sia stato committato.

## Passo 2 — COMMIT (scrive su DB, stesso ordine)

```powershell
python manage.py import_maintenance_causali --file "C:\import_manutenzioni\Causali manutenzione.xlsx" --commit --settings=config.settings.prod
python manage.py import_collaudo_history --storico "C:\import_manutenzioni\storico collaudo.xlsx" --mapping "C:\import_manutenzioni\riconciliazione_collaudo_macchine_PROD.xlsx" --commit --settings=config.settings.prod
python manage.py derive_collaudo_rules --storico "C:\import_manutenzioni\storico collaudo.xlsx" --mapping "C:\import_manutenzioni\riconciliazione_collaudo_macchine_PROD.xlsx" --commit --settings=config.settings.prod
```

## Verifica finale

Apri **Asset → Manutenzione → Prossime manutenzioni** (`/assets/manutenzione/prossime/`):
scadenzario popolato + OdL storici chiusi sulle 22 macchine confermate.

## In breve

- Ordine fisso: causali → storico → regole.
- Prima sempre `--dry-run`, poi `--commit`.
- Idempotente: un re-run non duplica.
- Salta da solo: centri non-macchina, macchine non confermate, causali corsi/sanitario (A10-A13).
