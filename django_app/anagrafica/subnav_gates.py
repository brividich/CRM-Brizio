"""Cancelli di sezione delle voci della subnav Anagrafica.

Il middleware ACL decide se una route è raggiungibile; alcune pagine però hanno
un secondo cancello in-view (singleton di sezione, permesso HR, amministratore
anagrafica) che rimbalza l'utente anche con l'ACL concessa. La subnav deve
nascondere anche quelle voci: qui, per nome di route, lo STESSO helper che la
view usa come blocco di pagina — mai una regola riscritta.

Sono elencate solo le route che compaiono in subnav e il cui helper è un
blocco dell'intera pagina (redirect/negazione), non un filtro parziale dei
contenuti. Le route governate dal solo permesso canonico (Skill Matrix, MPQ)
non servono: coincidono con la decisione del middleware.
"""

from __future__ import annotations

import logging
from typing import Callable

from django.urls import Resolver404, resolve

logger = logging.getLogger(__name__)


def _formazione(request) -> bool:
    from .views import _can_view_formazione

    return _can_view_formazione(request)


def _visite(request) -> bool:
    from .views import _can_view_visite_mediche

    return _can_view_visite_mediche(request)


def _hr(request) -> bool:
    from .views import _check_hr_permission

    return _check_hr_permission(request)


def _admin(request) -> bool:
    from .views import _is_anagrafica_admin

    return _is_anagrafica_admin(request)


def _recruiting(request) -> bool:
    from .views_recruiting import _can_view_recruiting

    return _can_view_recruiting(request)


SECTION_GATES: dict[str, Callable] = {
    "anagrafica:recruiting_list": _recruiting,
    "anagrafica:onboarding_list": _hr,
    "anagrafica:matrice_competenze": _hr,
    "anagrafica:conformita_report": _hr,
    "anagrafica:retribuzioni_globale": _hr,
    "anagrafica:ratei_list": _hr,
    "anagrafica:formazione_dashboard": _formazione,
    "anagrafica:formazione_piani_list": _formazione,
    "anagrafica:formazione_corsi_list": _formazione,
    "anagrafica:formazione_sessioni_list": _formazione,
    "anagrafica:formazione_istruttori_list": _formazione,
    "anagrafica:formazione_elearning_hub": _formazione,
    "anagrafica:formazione_copertura": _formazione,
    "anagrafica:sicurezza_hub": _formazione,
    "anagrafica:visite_mediche_dashboard": _visite,
    "anagrafica:referti_coda": _visite,
    "anagrafica:dipendente_create": _admin,
    "anagrafica:dipendenti_report": _admin,
    "anagrafica:retribuzioni_import": _admin,
    "anagrafica:contratti_import": _admin,
    "anagrafica:cedolini_import": _admin,
}


def section_gate_allows(request, path: str) -> bool:
    """True se il cancello in-view della pagina ``path`` lascia passare l'utente.

    Route senza cancello registrato → True (decide solo l'ACL). Fail-closed se
    l'helper esplode: meglio una voce in meno che un link che rimbalza.
    """
    try:
        view_name = resolve(path).view_name
    except Resolver404:
        return True
    gate = SECTION_GATES.get(view_name)
    if gate is None:
        return True
    try:
        return bool(gate(request))
    except Exception:
        logger.exception("Subnav anagrafica: cancello di sezione fallito per %s", view_name)
        return False
