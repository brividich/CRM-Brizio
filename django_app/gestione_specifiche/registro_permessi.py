"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='specifiche',
    # Pagina principale: il namespace «gestione_...» delle sue rotte (tutte di lettura)
    # la faceva sembrare amministrazione, e chi ha «vedere» non apriva il modulo ne' lo
    # trovava nel menu. Le scritture hanno binding propri (verificati il 28/10/2026).
    capacita_forzate=(
        ('gestione_specifiche.specifica.view', 'lettura'),
    ),
    nome='Gestione specifiche e OFI',
    descrizione='Flusso specifiche, MOD.133, distribuzione, registro OFI.',
    area='Qualità',
    app='gestione_specifiche',
    moduli_acl=('gestione_specifiche',),
))
