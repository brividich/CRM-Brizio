# Seed Skill Matrix MOD.187 — dizionario dati

Estratti da `MOD_187 - SKM Skill Matrix Rev.0.xlsx` (snapshot **30/04/2026** corrente +
**22/04/2024** storico). Input dell'importer `import_skill_matrix`.

## Chiave di join
- Macchine: **codice asset** (DM3, MK1, MZ5…) — stabile tra snapshot. ZEISS = nome
  completo (codice non univoco, 6 CMM). Processi/contatore = nome normalizzato.
- Operatori: **nome normalizzato** → da risolvere a `legacy_anagrafica_id` in import.

## File
- **skm_catalogo_competenze.csv** — `competenza_key, competenza_display, tipo
  (macchina|processo|contatore), codice_asset_match, alias_storici, note`.
  84 competenze: 42 macchine, 41 processi, 1 contatore ("corsi attivati", NON livello).
  `alias_storici` = intestazioni variate tra snapshot (7 macchine rinominate).
- **skm_operatori.csv** — `nome, reparto_area, turno_as_is, turno_to_be, is_car,
  is_academy, car_di_riferimento`. 102 operatori, 21 aree, 8 CAR, 7 academy.
  NB: alcune sotto-aree (ALC, PRESETTING, MONT, AGG, ecc.) non hanno una riga CAR
  propria nel foglio → `car_di_riferimento` vuoto: mappatura al CAR padre da definire
  in sessione di avvio.
- **skm_matrice_livelli.csv** — `operatore, competenza_key, livello (I/L/U/O o vuoto),
  valore_grezzo, snapshot`. Entrambi gli snapshot (baseline = 2026-04-30).
- **skm_storico_delta.csv** — `operatore, competenza_key, liv_2024_04_22,
  liv_2026_04_30, variazione (nuova|promozione|regressione)`.
  Evoluzione reale: **112 nuove, 43 promozioni, 5 regressioni**.

## Regole import
- CAR (`is_car=SI`) → `conteggiabile_nel_carico=False` (esclusi dal pool carico).
- Academy inclusi nel pool.
- Cella vuota = NON in lista (esclusione voluta), non livello 0.
- "corsi attivati" = contatore separato, non abilitazione.
- Baseline scritta diretta (dati già validati), storico seminato coi 2 snapshot.
