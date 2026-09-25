# Verifiche periodiche (Manutenzione)

Sezione di **Manutenzione** (app `assets`) per le verifiche periodiche **sugli impianti**
dello stabilimento: illuminazione di emergenza, antintrusione, quadri elettrici,
cabine MT/BT, impianto di terra, differenziali, UPS, antincendio, primo soccorso…
Sostituisce lo scadenziario Excel (`Verifiche riassuntive ditta Bruschi.xlsx`) e le
cartelle `\\novisrv\privman\...` come fonte di verita'.

## Confini (decisioni utente, 25/09/2026)

- **Non e' un modulo a se'**: e' una voce del menu Manutenzione, accanto a «Scadenze
  amministrative». Stesso pacchetto: manutenzione · scadenze amministrative · verifiche periodiche.
- **Impianto, non asset**: una verifica riguarda un impianto intero con molti punti.
  Le verifiche di legge **sul singolo asset** (gru/carroponti, serbatoi a pressione,
  piattaforma aerea, olio trasformatori, camini emissioni, bruciatori) restano in
  **Scadenze amministrative** (`AssetAdministrativeDeadline`).
- **Separata dalla pagina legacy** `periodic_verifications` («Manutenzioni periodiche»,
  modello `PeriodicVerification`, in dismissione): nomi, modelli e URL diversi.
  I nuovi modelli usano il prefisso `PeriodicCheck*` proprio per non confondersi.
- Esito non conforme -> **OdL** (`WorkOrder`). `WorkOrder.asset` e' obbligatorio: ogni
  impianto ha un *asset di riferimento* proposto come default, modificabile.
- Chi registra puo' anche confermare (nessuna separazione dei ruoli).

## Modello

| Modello | Cosa | Note |
|---|---|---|
| `PeriodicCheckSystem` | Impianto (elettrico, antincendio, primo soccorso…) | `asset` di riferimento per gli OdL (opzionale) |
| `PeriodicCheckType` | Tipo di verifica («Verifica quadri elettrici», semestrale) | metodo, frequenza in mesi, preavviso, fornitore, riferimento normativo, codice (es. «005» Bruschi), `next_due_date` |
| `PeriodicCheckItem` | Voce di checklist del tipo | solo metodo checklist |
| `PeriodicCheckSession` | Una verifica eseguita | data, tecnico, fornitore, esito, stato (bozza/confermata), origine (manuale/import/parser), `import_key` univoca |
| `PeriodicCheckResult` | Esito per voce / prescrizione | OK/KO/NA, nota, `work_order` generato |
| `PeriodicCheckAttachment` | Rapportino/verbale | storage privato cifrato (`ASSETS_PRIVATE_ROOT`), download con audit |

Alla conferma di una sessione la prossima scadenza del tipo diventa
`data verifica + frequenza` (o quella indicata a mano, es. la data del verbale DPR 462).

## Metodi di acquisizione

| Metodo | Esempi | Stato |
|---|---|---|
| **C · Checklist** | quadri elettrici, cabine MT/BT, cassetta primo soccorso | Fase 1 |
| **D · Verbale esterno** (esito + prescrizioni + prossima data) | impianto di terra (HT, DPR 462), impianto generale, antincendio | Fase 1 |
| **A · Planimetria a punti** | illuminazione emergenza, differenziali tasto prova (D1…D76), antintrusione a zone | Fase 2: parser `parser pdf/planimetria_parser.py` + modello visione sul cartiglio; all'operatore **solo le differenze** fra «letto dal cartiglio» ed «evidenziato» |
| **B · Misure per punto** | pacchi batteria UPS, differenziali con strumento (PDF testo Bruschi) | Fase 3 |

Il metodo A/B aggiungera' `PeriodicCheckPoint` (punti numerati con coordinate sulla
planimetria versionata) e risultati per punto; il nucleo e' gia' pronto (stato bozza,
origine parser, esiti per riga).

## Storico

`manage.py import_periodic_checks <cartella>` (dry-run di default, `--apply` per
scrivere) importa i documenti gia' archiviati come sessioni confermate con origine
`IMPORT`: data dal nome file (`MM-YYYY`, `DD-MM-YY`, `YYYY`…), allegato, esito
«storico (da documento)». Idempotente via `import_key` (percorso relativo).
La mappa cartella -> tipo e' in `assets/services/periodic_checks_catalog.py`.

## Deploy

- `migrate assets` (modelli + voce di menu).
- `bootstrap_acl_v2` per i binding canonici delle nuove route `/assets/manutenzione/verifiche-impianti/`.
- `seed_periodic_checks --apply` (catalogo impianti/tipi da Excel Bruschi e cartelle).
- `import_periodic_checks "\\novisrv\privman\_Impianto Elettrico\Verifiche impianto elettrico" --apply`
  (e le altre cartelle del catalogo).
