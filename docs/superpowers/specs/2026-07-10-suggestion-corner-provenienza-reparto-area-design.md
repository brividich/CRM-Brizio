# Suggestion Corner — Provenienza/Destinazione = Reparto **o** Area Aziendale

**Data:** 2026-07-10
**Modulo:** `django_app/suggestion_corner`
**Branch:** `feature/skill-matrix-mod187` (il branch che gira in prod)

## Problema

Le segnalazioni Suggestion Corner (SMS) tracciano provenienza e destinazione tramite
FK al solo `anagrafica.Reparto`, con `reparto_provenienza` **obbligatorio**.

Il registro storico da importare (`Registro SMS_Suggestion Corner.csv`, 47 record)
tagga la provenienza in modo **misto**: alcuni valori sono Reparti (`TORNI`, `CNC`,
`MARCATURA`, `AGGIUSTAGGIO`…), altri sono **Aree Aziendali** (`IT`, `CQ`, `CN5`,
`UFFICIO TECNICO`, `AMMINISTRAZIONE`, `DIREZIONE`…), più due jolly non mappabili
(`Altro`, `Generico`). Con il matching solo su `Reparto` **tutti i 47 record vengono
scartati** (`reparto provenienza non trovato`), quindi l'import produce 0 record.

Requisito (dall'utente): **in Suggestion Corner i "reparti" = Reparto + Area
Aziendale**, sia in dev sia in prod.

## Gerarchia esistente (non si tocca)

`AreaAziendale` è sotto-articolazione di un `Reparto` (FK `AreaAziendale.reparto`,
es. IT/IN1/DM sotto un reparto). Reparto = livello ampio; Area = livello fine.

## Decisioni di design (approvate)

1. **Modello: doppia FK nullable.** La provenienza/destinazione può essere un
   Reparto **oppure** un'Area (o nessuno dei due per i jolly storici).
2. **Integrità:** una **nuova** segnalazione richiede *almeno una* tra
   `reparto_provenienza` / `area_provenienza`. I record storici importati
   (`legacy_sharepoint_id` valorizzato) sono **esenti** (jolly → entrambe nulle).
3. **UI: cascata Reparto → Area.** Si sceglie il Reparto, poi opzionalmente un'Area
   figlia (filtrata). Scegliendo un'Area, il Reparto padre è impostato automaticamente.

## Progettazione

### 1. Modello (`models.py`)

- `reparto_provenienza`: `null=True, blank=True` (era obbligatorio).
- Nuovi campi:
  - `area_provenienza = FK("anagrafica.AreaAziendale", null=True, blank=True, on_delete=PROTECT, related_name="segnalazioni_provenienza")`
  - `area_destinazione = FK("anagrafica.AreaAziendale", null=True, blank=True, on_delete=PROTECT, related_name="segnalazioni_destinazione")`
  - (aggiornare i `related_name` dei FK Reparto esistenti se collidono → restano
    `segnalazioni_provenienza_reparto` / `segnalazioni_destinazione_reparto`).
- Coerenza padre: in `save()`, se `area_provenienza` è valorizzata e
  `reparto_provenienza` è nullo, impostare `reparto_provenienza = area_provenienza.reparto`
  (idem destinazione). Non sovrascrive un reparto già scelto esplicitamente.
- `clean()`: se **nuova** segnalazione (`legacy_sharepoint_id` vuoto) e nessuna delle
  due provenienze è valorizzata → `ValidationError`. Import esente.
- Property `provenienza_display` / `destinazione_display`: Area se presente, altrimenti
  Reparto, altrimenti `"—"`.

### 2. Migrazione

`0006_suggestioncorner_area_provenienza_destinazione` in coda a `0005` (cliente):
- `AddField` `area_provenienza`, `area_destinazione`;
- `AlterField` `reparto_provenienza` → `null=True`;
- eventuale `AlterField` sui `related_name` Reparto.
- Nessun backfill dati.

### 3. Form (pubblico `nuova` + gestione `modifica`)

- Selettore cascata: `reparto_provenienza` (select) + `area_provenienza` (select
  filtrata sul reparto, via HTMX o JS onchange che ricarica le opzioni area).
  Idem destinazione.
- `clean()` del form applica la regola "almeno uno" per le nuove segnalazioni.
- Il queryset Area è filtrato per `reparto` selezionato.

### 4. Import storico (`import_suggestion_corner_legacy` + `converti_sms_storico`)

- Nuovo helper `_unita(nome)` che risolve il nome (case-insensitive) contro:
  1. `Reparto` → `(reparto, None)`;
  2. altrimenti `AreaAziendale` → `(area.reparto, area)`;
  3. altrimenti `(None, None)` (jolly: nessuno scarto, nessun errore).
- `reparto_provenienza` non più obbligatorio in import → i jolly entrano con entrambe
  nulle invece di essere scartati.
- `--reparto-map` resta per rimappare abbreviazioni/rinomine prima del match
  (es. `CN5`, `LOG`→`LOGISTICA`), applicata sia a Reparto sia ad Area.
- Report: contatori distinti per `reparti_mancanti` vs `unita_non_risolte`.

### 5. Template lista/dettaglio

- `home.html`, `dettaglio.html`, `modifica.html`: usare `provenienza_display` /
  `destinazione_display` al posto di `reparto_provenienza.nome`.

### 6. Deploy prod (target reale)

Sequenza (eseguita sull'host prod, che gira `feature/skill-matrix-mod187`):
1. commit+push del modulo su `feature/skill-matrix-mod187`;
2. deploy + **migrate globale** su prod (attenzione al pitfall migrate selettivo del Setup Wizard);
3. `converti_sms_storico --file "Registro SMS_Suggestion Corner.csv" --out <fuori-repo>.json` (contro anagrafica prod, risolve i nomi persone);
4. `import_suggestion_corner_legacy --file <json>` (dry-run) → verifica `unita_non_risolte`;
5. costruire `--reparto-map` per gli scarti reali;
6. `import_suggestion_corner_legacy --file <json> --reparto-map <map>.json --apply`.

## Testing

- Modello: `save()` auto-compila reparto padre da area; `clean()` blocca nuova
  segnalazione senza provenienza ma consente record storico (legacy id) vuoto;
  `provenienza_display` nei tre casi.
- Form: regola "almeno uno"; queryset Area filtrato per reparto.
- Import: record con nome=Area → area+reparto padre; record jolly → entrambe nulle
  (creato, non scartato); record con nome=Reparto → invariato.

## Fuori scope (YAGNI)

- Nessun backfill/riclassificazione dei record esistenti in dev (dev è vuoto).
- Nessuna modifica alla gerarchia Reparto/AreaAziendale.
- Nessun cambiamento all'FSM PDCA né agli stati.
