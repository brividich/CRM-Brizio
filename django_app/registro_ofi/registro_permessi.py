"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
L'inserimento resta il permesso ``gestione_specifiche.registroofi.add``, dichiarato
dal modulo Specifiche (il modello delle voci vive li').
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='registro_ofi',
    nome='Registro OFI / NC',
    descrizione='Dashboard, registro MOD.174, le mie voci: OFI e NC da audit, enti, MOD.133 e processi.',
    area='Qualità',
    app='registro_ofi',
    moduli_acl=('registro_ofi',),
))
