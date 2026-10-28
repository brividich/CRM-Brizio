"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='suggestion_corner',
    # Permesso della pagina principale legato a un prefisso: «ereditava» le rotte di
    # scrittura/gestione sotto e la matrice lo dava solo a «modificare»/«gestire», cosi'
    # chi ha «vedere» non apriva il modulo ne' lo trovava nel menu. Le scritture hanno
    # controlli propri nelle view (verificati il 28/10/2026).
    capacita_forzate=(
        ('suggestion_corner.segnalazione.view', 'lettura'),
    ),
    nome='Suggestion Corner',
    descrizione='Segnalazioni e miglioramenti con ciclo PDCA. Il form anonimo pubblico resta aperto.',
    area='Qualità',
    app='suggestion_corner',
    moduli_acl=('suggestion_corner',),
    domini_ai=('suggestioni',),
))
