"""Soglie «in scadenza» uniche per formazione e qualifiche (analisi 26/11/2026: erano 30/90, 30/60 e 60).

- ``GIORNI_URGENTE``: entro questi giorni la scadenza è urgente (rosso/arancio);
- ``GIORNI_PREAVVISO``: entro questi giorni è «in scadenza» (giallo).
Le visite mediche hanno regole proprie e non usano queste soglie: il loro
preavviso è ``GIORNI_PREAVVISO_VISITE`` (60 giorni), qui solo per averlo in un posto.
"""
GIORNI_URGENTE = 30
GIORNI_PREAVVISO = 90
GIORNI_PREAVVISO_VISITE = 60
