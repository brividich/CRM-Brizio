"""Registro dei moduli del portale per il sistema dei permessi.

Ogni modulo si dichiara qui, nel file ``<app>/registro_permessi.py``, con
:func:`registra_modulo`. Il registro dice:

- quali azioni il modulo conosce (le sette standard, piu' le sue);
- quali permessi di pagina (``PermissionDefinition.module``) gli appartengono,
  cosi' la matrice dei ruoli accende e spegne anche l'accesso alle rotte;
- come si trova il proprietario di un record, per la visibilita'
  «propri / team / tutti».

Un modulo che non si dichiara non esiste per la matrice: nessun ruolo puo'
riceverne i permessi e il test ``core.tests_permessi`` fallisce.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from core.permission_taxonomy import (
    CAPABILITY_AMMINISTRAZIONE,
    CAPABILITY_APPROVAZIONE,
    CAPABILITY_IGNOTO,
    CAPABILITY_LETTURA,
    CAPABILITY_MODIFICA,
)

AZIONE_VEDERE = "vedere"
AZIONE_CREARE = "creare"
AZIONE_MODIFICARE = "modificare"
AZIONE_APPROVARE = "approvare"
AZIONE_GESTIRE = "gestire"
AZIONE_ESPORTARE = "esportare"
AZIONE_CANCELLARE = "cancellare"

AZIONI_STANDARD: tuple[str, ...] = (
    AZIONE_VEDERE,
    AZIONE_CREARE,
    AZIONE_MODIFICARE,
    AZIONE_APPROVARE,
    AZIONE_GESTIRE,
    AZIONE_ESPORTARE,
    AZIONE_CANCELLARE,
)

AZIONI_LABEL: dict[str, str] = {
    AZIONE_VEDERE: "Vedere",
    AZIONE_CREARE: "Creare",
    AZIONE_MODIFICARE: "Modificare",
    AZIONE_APPROVARE: "Approvare",
    AZIONE_GESTIRE: "Chiudere / gestire",
    AZIONE_ESPORTARE: "Esportare",
    AZIONE_CANCELLARE: "Cancellare",
}

# Azioni di sola consultazione: sono quelle che il ruolo «vede tutto» concede.
AZIONI_LETTURA = frozenset({AZIONE_VEDERE, AZIONE_ESPORTARE})

# Che cosa accende ogni azione sui permessi di pagina del modulo. La
# classificazione dei permessi e' quella di ``core.permission_taxonomy``:
# un permesso di cui non si sa cosa faccia (``ignoto``) lo accende solo
# «gestire», mai la lettura.
AZIONE_CAPACITA: dict[str, frozenset[str]] = {
    AZIONE_VEDERE: frozenset({CAPABILITY_LETTURA}),
    AZIONE_ESPORTARE: frozenset({CAPABILITY_LETTURA}),
    AZIONE_CREARE: frozenset({CAPABILITY_MODIFICA}),
    AZIONE_MODIFICARE: frozenset({CAPABILITY_MODIFICA}),
    AZIONE_CANCELLARE: frozenset({CAPABILITY_MODIFICA}),
    AZIONE_APPROVARE: frozenset({CAPABILITY_APPROVAZIONE}),
    AZIONE_GESTIRE: frozenset({CAPABILITY_AMMINISTRAZIONE, CAPABILITY_IGNOTO}),
}

AMBITO_PROPRI = "propri"
AMBITO_TEAM = "team"
AMBITO_TUTTI = "tutti"
AMBITI: tuple[str, ...] = (AMBITO_PROPRI, AMBITO_TEAM, AMBITO_TUTTI)
AMBITI_LABEL = {
    AMBITO_PROPRI: "Propri",
    AMBITO_TEAM: "Propri e del team",
    AMBITO_TUTTI: "Tutti",
}
_AMBITO_RANK = {AMBITO_PROPRI: 1, AMBITO_TEAM: 2, AMBITO_TUTTI: 3}


def ambito_piu_ampio(*ambiti: str) -> str:
    validi = [a for a in ambiti if a in _AMBITO_RANK]
    if not validi:
        return ""
    return max(validi, key=lambda a: _AMBITO_RANK[a])


@dataclass(frozen=True)
class ModuloPermessi:
    """Dichiarazione di un modulo nel sistema dei permessi.

    ``proprietario(oggetto)`` restituisce l'id utente (``utenti.id``) del
    proprietario del record, o un insieme di id, o ``None`` se non e'
    determinabile: in quel caso il record e' visibile solo a chi ha ambito
    «tutti» (si nega, non si indovina).
    """

    chiave: str
    nome: str
    descrizione: str = ""
    area: str = ""
    app: str = ""
    moduli_acl: tuple[str, ...] = ()
    codici_acl: tuple[str, ...] = ()
    azioni_extra: tuple[tuple[str, str], ...] = ()
    # (azione propria, code di pagina) che la sola azione propria accende: quei
    # code escono dalle azioni standard (es. le Impostazioni del modulo, che
    # altrimenti «gestire» aprirebbe insieme al resto dell'amministrazione).
    pagine_azioni: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # (code, capacita') decise a mano quando la lettura automatica sbaglia:
    # es. un permesso di prefisso che copre la pagina principale del modulo.
    capacita_forzate: tuple[tuple[str, str], ...] = ()
    proprietario: Callable[[Any], Any] | None = None
    # Domini dei tool dell'Assistente AI che leggono dati di questo modulo.
    domini_ai: tuple[str, ...] = ()
    # Modulo tecnico o di amministrazione: compare in matrice ma i preset non
    # lo concedono a nessuno (resta all'Amministratore).
    solo_amministratore: bool = False
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def azioni(self) -> tuple[str, ...]:
        return AZIONI_STANDARD + tuple(chiave for chiave, _label in self.azioni_extra)

    def etichetta_azione(self, azione: str) -> str:
        if azione in AZIONI_LABEL:
            return AZIONI_LABEL[azione]
        return dict(self.azioni_extra).get(azione, azione)


_REGISTRO: dict[str, ModuloPermessi] = {}
_LOCK = threading.Lock()
_SCOPERTI = False


def registra_modulo(modulo: ModuloPermessi) -> ModuloPermessi:
    """Dichiara un modulo. Chiave duplicata = errore di programmazione."""
    chiave = str(modulo.chiave or "").strip().lower()
    if not chiave:
        raise ValueError("ModuloPermessi senza chiave.")
    for azione, _label in modulo.azioni_extra:
        if azione in AZIONI_STANDARD:
            raise ValueError(f"{chiave}: l'azione «{azione}» e' gia' standard.")
    proprie = {azione for azione, _label in modulo.azioni_extra}
    for azione, _codes in modulo.pagine_azioni:
        if azione not in proprie:
            raise ValueError(f"{chiave}: pagine per l'azione «{azione}», che non e' un'azione propria.")
    with _LOCK:
        esistente = _REGISTRO.get(chiave)
        if esistente is not None and esistente != modulo:
            raise ValueError(f"Modulo «{chiave}» registrato due volte.")
        _REGISTRO[chiave] = modulo
    return modulo


def registra_moduli(moduli: Iterable[ModuloPermessi]) -> None:
    for modulo in moduli:
        registra_modulo(modulo)


def _scopri() -> None:
    """Importa ``<app>/registro_permessi.py`` di ogni app installata (una volta sola)."""
    global _SCOPERTI
    if _SCOPERTI:
        return
    from django.utils.module_loading import autodiscover_modules

    with _LOCK:
        if _SCOPERTI:
            return
        _SCOPERTI = True
    autodiscover_modules("registro_permessi")


def moduli_registrati() -> dict[str, ModuloPermessi]:
    _scopri()
    return dict(sorted(_REGISTRO.items(), key=lambda item: (item[1].area, item[1].nome.lower())))


def modulo(chiave: str) -> ModuloPermessi | None:
    _scopri()
    return _REGISTRO.get(str(chiave or "").strip().lower())


def moduli_per_dominio_ai(dominio: str) -> list[ModuloPermessi]:
    dominio = str(dominio or "").strip().lower()
    return [m for m in moduli_registrati().values() if dominio in m.domini_ai]
