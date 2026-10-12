"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='fornitori',
    nome='Fornitori',
    descrizione='Anagrafica fornitori: ordini, documenti, valutazioni, asset.',
    area='Acquisti',
    app='fornitori',
    moduli_acl=('fornitori',),
    codici_acl=(
        'anagrafica.fornitore_asset_add.view',
        'anagrafica.fornitore_asset_remove.view',
        'anagrafica.fornitore_create.view',
        'anagrafica.fornitore_detail.view',
        'anagrafica.fornitore_documento_add.view',
        'anagrafica.fornitore_documento_delete.view',
        'anagrafica.fornitore_edit.view',
        'anagrafica.fornitore_ordine_add.view',
        'anagrafica.fornitore_ordine_stato.view',
        'anagrafica.fornitore_toggle_active.view',
        'anagrafica.fornitore_valutazione_add.view',
        'anagrafica.fornitore_valutazione_delete.view',
        'anagrafica.fornitori_list.view',
        'legacy.anagrafica.anagrafica_fornitore_create',
        'legacy.anagrafica.anagrafica_fornitori',
        'legacy.anagrafica.view_anagrafica_fornitori',
    ),
))
