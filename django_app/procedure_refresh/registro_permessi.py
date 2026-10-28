"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='procedure',
    # Permesso della pagina principale legato a un prefisso: «ereditava» le rotte di
    # scrittura/gestione sotto e la matrice lo dava solo a «modificare»/«gestire», cosi'
    # chi ha «vedere» non apriva il modulo ne' lo trovava nel menu. Le scritture hanno
    # controlli propri nelle view (verificati il 28/10/2026).
    capacita_forzate=(
        ('legacy.procedure_refresh.pr_assignment_detail', 'lettura'),
    ),
    nome='Procedure (presa visione)',
    descrizione='Campagne di presa visione delle procedure, scadenze e solleciti.',
    area='Sicurezza',
    app='procedure_refresh',
    moduli_acl=('procedure_refresh',),
    domini_ai=('procedure',),
))
