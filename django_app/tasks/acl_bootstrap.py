from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "tasks_acl_bootstrap_v3"

_PULSANTI_DEFINITIONS = [
    {"modulo": "tasks", "codice": "tasks_view", "label": "KICK-OFF - Lista", "url": "/tasks/", "visible_topbar": True, "ui_order": 45},
    {"modulo": "tasks", "codice": "tasks_create", "label": "KICK-OFF - Crea", "url": "/tasks/new/", "visible_topbar": False, "ui_order": None},
    {"modulo": "tasks", "codice": "tasks_edit", "label": "KICK-OFF - Modifica", "url": "/tasks/edit/", "visible_topbar": False, "ui_order": None},
    {"modulo": "tasks", "codice": "tasks_comment", "label": "KICK-OFF - Commenta", "url": "/tasks/comment/", "visible_topbar": False, "ui_order": None},
    {"modulo": "tasks", "codice": "tasks_admin", "label": "KICK-OFF - Scope globale", "url": "/tasks/admin/", "visible_topbar": False, "ui_order": None},
    {"modulo": "tasks", "codice": "tasks_projects", "label": "KICK-OFF - Lista kickoff", "url": "/tasks/projects/", "visible_topbar": False, "ui_order": None},
]


def bootstrap_tasks_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "tasks",
        icona="check-square",
        section="tasks",
        force=force,
    )
