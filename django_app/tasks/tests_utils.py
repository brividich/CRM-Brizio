"""Helper condivisi dai test del modulo tasks."""
from __future__ import annotations

from .models import Project

# I ruoli del team sono M2M: i test continuano a scrivere il caso comune
# "una persona per ruolo" con la vecchia forma a keyword singola.
_TEAM_KWARGS = {
    "project_manager": "project_managers",
    "capo_commessa": "capi_commessa",
    "programmer": "programmers",
    "caporeparto": "caporeparti",
}


def make_project(**kwargs) -> Project:
    """Crea un Project accettando anche i referenti singoli del team."""
    team: dict[str, object] = {}
    for kwarg, field in _TEAM_KWARGS.items():
        if kwarg in kwargs:
            team[field] = kwargs.pop(kwarg)
    project = Project.objects.create(**kwargs)
    for field, user in team.items():
        if user is not None:
            getattr(project, field).add(user)
    return project
