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

Il metodo B aggiungera' le misure per punto; il metodo A e' fatto (sotto). In origine era previsto `PeriodicCheckPoint` (punti numerati con coordinate sulla
planimetria versionata) e risultati per punto; il nucleo e' gia' pronto (stato bozza,
origine parser, esiti per riga).

## Metodo A: foglio «layout Novicrom» con QR (fase 2, fatta)

Decisioni utente (25/09/2026): **solo planimetria**, nessuna lista scritta da leggere;
la cartella di pescaggio arriva dopo con una pagina di configurazione.

- `PeriodicCheckLayout` (planimetria PDF vettoriale con **versioni**, zone da coprire
  `exclude_areas`) e `PeriodicCheckPoint` (codice + coordinate). I punti si estraggono da
  soli: riquadro rosso con la X + numero rosso (`services/periodic_layout.extract_points`).
  Caricamento dalla pagina della verifica o con `import_periodic_layout`.
- «Stampa foglio per il tecnico» crea la verifica in stato **ISSUED** con un token
  (`sheet_token`, alfabeto senza caratteri ambigui) e il PDF A4: intestazione con data /
  tecnico / firma, QR `NVC-VP:<token>`, legenda, planimetria vettoriale, vecchio cartiglio
  coperto, 4 marcatori d'angolo (stesso schema del foglio firme della formazione,
  `anagrafica/services/foglio_firme.py`).
- **Legenda**: evidenziatore = prima categoria del tipo, cerchio a penna = seconda
  (`PeriodicCheckType.point_categories`, default «Non funzionante / Bassa autonomia»).
- Lettura (`services/periodic_layout_reader.py`, numpy + PyMuPDF + Pillow, niente AI):
  allineamento al foglio rigenerato senza QR (rotazione a 90 gradi, scala, affinamento sui
  simboli), segni = inchiostro nuovo nella zona planimetria; controllo dedicato dei cerchi
  a penna (copertura della corona attorno al punto, contando solo i settori dove la carta
  era libera). Soglie in punti della planimetria originale, scalate con `unit`.
- La scansione si carica dalla pagina della verifica: il QR viene controllato (una
  scansione di un altro foglio e' rifiutata), scansione e immagine della lettura
  (`lettura-automatica.png`) vanno negli allegati, i punti diventano esiti `POINT` proposti
  e la verifica passa **DRAFT**. La conferma (data scritta sul foglio, categoria per punto,
  scarta, aggiungi i mancanti) la rende CONFIRMED e ricalcola la scadenza.
- Senza foglio: «Registra a mano» accetta i numeri dei punti per categoria.
- Prossimo passo: **cartella di pescaggio** (job django-q che legge il QR e aggancia la
  scansione alla verifica; stessa logica di `anagrafica/services/intake_scansioni.py`,
  cartelle `elaborati` / `errori`) con pagina di configurazione del percorso.

## Scheda della verifica (contenitore a schede)

La pagina di un tipo di verifica (`/assets/manutenzione/verifiche-impianti/tipo/<id>/`) e' la
**scheda** della verifica, con schede `?tab=`: **Panoramica** (statistiche), **Storico verifiche**,
**Ordini di lavoro** (OdL nati dai rilievi), **Documenti** (tutti gli allegati, senza le immagini
di lettura), **Impostazioni** (dati del tipo, planimetria, voci di checklist).

Panoramica (`services/periodic_stats.py`, sola lettura):
- indicatori: prossima e ultima verifica, **punti in ordine** (%), **nei tempi** (verifiche fatte
  entro la scadenza fissata dalla precedente, ultimi 24 mesi), verifiche negli ultimi 12 mesi
  rispetto alle attese, rilievi dell'ultima verifica senza OdL e OdL aperti;
- metodo planimetria: **mappa dello stato attuale** (planimetria come immagine
  `periodic_check_layout_image`, in cache 30 giorni, con i punti in percentuale: difettoso per
  categoria, riparato = OdL chiuso, in ordine), elenco dei difettosi con «da quando» e verifiche
  di fila, **punti ricorrenti** (almeno 2 volte nelle ultime 6 verifiche con esiti);
- metodo checklist: **voci piu' spesso non OK**;
- **andamento dei rilievi**: barre impilate per categoria delle ultime 12 verifiche con esiti (SVG).
- Le verifiche importate dallo storico hanno solo il documento: contano per date e puntualita',
  non per punti e voci; la pagina lo dice.
- Trappola: i valori numerici in `style`/SVG vanno dentro `{% localize off %}` (virgola italiana).
- Colori dei punti e delle serie **provvisori** (`--pc-cat0/1` in `periodic_check_styles.html`,
  validati solo in tema chiaro): l'utente li decide in seguito.

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
- `pip install -r requirements.txt` (nuova dipendenza **numpy**), `migrate assets` 0114.
- `import_periodic_layout "Verifica illuminazione di emergenza" "\\novisrv\privman\_Impianto Elettrico\Verifiche impianto elettrico\Verifica illuminazione di emergenza (quadrimestrale)\PLANIMETRIA PLAFONIERE DI EMERGENZA.pdf" --exclude "465.6,975.5,813.7,1136.3" --apply`.
- `import_periodic_checks "\\novisrv\privman\_Impianto Elettrico\Verifiche impianto elettrico" --apply`
  (e le altre cartelle del catalogo).
