"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='anomalie',
    nome='Anomalie',
    descrizione="Controllo dell'OP a blocchi di seriali, decisioni del capocommessa.",
    area='Produzione',
    app='anomalie',
    moduli_acl=('anomalie', 'gestione-anomalie'),
    codici_acl=(
        'legacy.dashboard.dashboard_anomalie_menu',
        'legacy.dashboard.gestione_anomalie',
        'api.anomalie_config.export',
        'api.anomalie_config.manage',
        'api.anomalie_config.run',
        'api.anomalie_db.manage',
        'api.anomalie_filtrato.export',
        'api.route.view',
    ),
    domini_ai=('anomalie',),
))
