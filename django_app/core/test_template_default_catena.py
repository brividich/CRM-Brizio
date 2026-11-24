"""Nei template, `|default:a.b.c` va in errore 500 quando `b` è vuoto.

Django risolve gli argomenti dei filtri senza tollerare gli anelli mancanti: se `b` è una chiave
esterna vuota (per esempio un utente eliminato), la pagina cade. Successo nell'elenco dei prospetti
il 24/11/2026. Al suo posto: `{% firstof a a.b.c %}`, che tollera gli anelli mancanti.

La prova cerca le catene il cui anello intermedio è il nome di una relazione che può essere vuota
in qualche modello. I casi già protetti (da un `{% if %}` o perché l'oggetto non è mai vuoto)
stanno in ``PROTETTI``.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import models
from django.test import SimpleTestCase

MODELLO = re.compile(r"\|default:([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){2,})")
# (file relativo a django_app, catena): protetti da un {% if %} o mai vuoti.
PROTETTI = {
    ("ai_assistant/templates/ai_assistant/chat.html", "request.user.username"),
    ("assets/templates/assets/pages/gestione_admin.html", "tpl.asset.asset_type"),
    ("tasks/templates/tasks/list.html", "task.assigned_to.username"),
}


def _relazioni_che_possono_mancare() -> set[str]:
    nomi = set()
    for m in apps.get_models():
        for f in m._meta.get_fields():
            if isinstance(f, (models.ForeignKey, models.OneToOneField)) and f.null:
                nomi.add(f.name)
            elif isinstance(f, models.OneToOneRel):
                nomi.add(f.get_accessor_name())
    return nomi


class DefaultCatenaTests(SimpleTestCase):
    def test_nessun_default_su_relazione_che_puo_mancare(self):
        radice = Path(settings.BASE_DIR)
        nullabili = _relazioni_che_possono_mancare()
        trovati = []
        for f in radice.rglob("*.html"):
            if "node_modules" in f.parts or "staticfiles" in f.parts:
                continue
            rel = f.relative_to(radice).as_posix()
            for n, riga in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for m in MODELLO.finditer(riga):
                    catena = m.group(1)
                    if (rel, catena) in PROTETTI:
                        continue
                    if any(anello in nullabili for anello in catena.split(".")[1:-1]):
                        trovati.append(f"{rel}:{n}: default:{catena}")
        self.assertEqual(trovati, [], "Usa {% firstof … %}: con l'anello vuoto la pagina va in errore 500.")
