"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='schede_sicurezza',
    nome='Schede di sicurezza (SDS)',
    descrizione='Schede dei prodotti chimici, versioni, mansioni di rischio, presa visione.',
    area='Sicurezza',
    app='schede_sicurezza',
    moduli_acl=('schede_sicurezza',),
    # Elenco, scheda, download, QR e presa visione: consultazione delle SDS per chi le
    # deve leggere. La presa visione lo faceva sembrare «modifica».
    capacita_forzate=(('schede_sicurezza.prodotto.view', 'lettura'),),
    domini_ai=('schede_sicurezza',),
))
