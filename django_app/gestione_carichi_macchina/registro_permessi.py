"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='carichi_macchina',
    # Pagina principale: il namespace «gestione_...» delle sue rotte (tutte di lettura)
    # la faceva sembrare amministrazione, e chi ha «vedere» non apriva il modulo ne' lo
    # trovava nel menu. Le scritture hanno binding propri (verificati il 28/10/2026).
    capacita_forzate=(
        ('gestione_carichi_macchina.piano.view', 'lettura'),
    ),
    nome='Carichi macchina',
    descrizione='Pianificazione dei carichi macchine x giorni e Gantt.',
    area='Produzione',
    app='gestione_carichi_macchina',
    moduli_acl=('gestione_carichi_macchina',),
    domini_ai=('carichi',),
))
