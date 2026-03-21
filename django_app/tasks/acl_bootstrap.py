from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "tasks_acl_bootstrap_v3"

_PULSANTI_DEFINITIONS = [
    {"modulo": "tasks", "codice": "tasks_view", "label": "Task - Lista", "url": "/tasks/", "visible_topbar": True, "ui_order": 45},
    {"modulo": "tasks", "codice": "tasks_create", "label": "Task - Crea", "url": "/tasks/new/", "visible_topbar": False, "ui_order": None},
    {"modulo": "tasks", "codice": "tasks_edit", "label": "Task - Modifica", "url": "/tasks/edit/", "visible_topbar": False, "ui_order": None},
    {"modulo": "tasks", "codice": "tasks_comment", "label": "Task - Commenta", "url": "/tasks/comment/", "visible_topbar": False, "ui_order": None},
    {"modulo": "tasks", "codice": "tasks_admin", "label": "Task - Scope globale", "url": "/tasks/admin/", "visible_topbar": False, "ui_order": None},
    {"modulo": "tasks", "codice": "tasks_projects", "label": "Task - Lista progetti", "url": "/tasks/projects/", "visible_topbar": False, "ui_order": None},
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
