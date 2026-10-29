"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».

«Copiare» e «scaricare» le immagini di timbri, firme e sigle sono azioni
proprie, separate da «esportare» (elenco Excel/PDF): ognuna ha il suo ambito
(solo i propri timbri, anche quelli del team, tutti). Proprietario = l'account
collegato alla scheda anagrafica del titolare del timbro.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

AZIONE_COPIARE = "copiare"
AZIONE_SCARICARE = "scaricare"


def proprietario_timbro(oggetto):
    """``utenti.id`` del titolare: da immagine, record, operatore o id anagrafica."""
    from core.permessi.identita import utente_da_anagrafica

    if isinstance(oggetto, int):
        return utente_da_anagrafica(oggetto)
    registro = getattr(oggetto, "registro", None)
    if registro is not None:
        oggetto = registro
    operatore = getattr(oggetto, "operatore", None)
    if operatore is not None:
        oggetto = operatore
    return utente_da_anagrafica(getattr(oggetto, "legacy_anagrafica_id", None))


registra_modulo(ModuloPermessi(
    chiave='timbri',
    nome='Registro timbri MOD.130',
    descrizione='Timbri, firme e sigle del personale.',
    area='Qualità',
    app='timbri',
    moduli_acl=('timbri',),
    azioni_extra=(
        (AZIONE_COPIARE, "Copiare le immagini (appunti)"),
        (AZIONE_SCARICARE, "Scaricare le immagini (file PNG)"),
    ),
    proprietario=proprietario_timbro,
))
