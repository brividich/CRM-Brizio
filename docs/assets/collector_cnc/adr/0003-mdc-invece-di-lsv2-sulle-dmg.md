# ADR 0003 — Sulle DMG MORI con box MDC il portale usa OPC UA, non LSV2

Stato: accettata (27/10/2026)

## Contesto
DM6 è una DMG MORI con controllo Heidenhain TNC 640 (LSV2, .114) e box MDC (OPC UA, .115): la stessa
macchina è leggibile per due vie. Il portale ha un solo collegamento per asset.

## Decisione
- Al portale va la via **MDC (OPC UA)**, coerente con le altre DMG col box (DM7, DM9–DM13, DM15) e con
  i modelli dati già gestiti (BasicDataSet, umati). Niente login DNC sul controllo.
- LSV2 su DM6 si usa solo per confronto: `--once` o `machines.json` senza `asset_tag` (non arriva al
  portale).
- Il percorso LSV2 nel portale si collauda sulle Heidenhain senza box: AGV1 (.105), AGV2 (.106),
  DM3 (.107), AGV3 (.128), DM14 (.132).

## Conseguenze
Meno sessioni sul controllo delle DMG (il box MDC fa da intermediario). Se il box MDC si guasta, LSV2 è
la via di riserva, da attivare consapevolmente cambiando driver del collegamento.
