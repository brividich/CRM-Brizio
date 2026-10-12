"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='assistente_ai',
    nome='Assistente AI',
    descrizione='Chatbot interno: risponde sempre nei limiti dei permessi di chi lo interroga.',
    area='Piattaforma',
    app='ai_assistant',
    moduli_acl=('ai_assistant',),
))
