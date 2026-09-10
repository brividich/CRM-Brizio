"""I gate delle pagine amministrative dei moduli leggono l'ACL.

``legacy_admin_required`` ammette solo superuser e ruoli legacy admin: una pagina
protetta cosi' resta chiusa anche dopo che il pannello Accessi ha concesso il
permesso, perche' il permesso non viene mai letto. Fuori da ``admin_portale``
(che resta deliberatamente riservato) i moduli usano il gate che l'ACL la legge.

Il test guarda il codice, non le singole rotte: e' l'unico modo perche' una view
aggiunta domani non reintroduca il cancello cieco senza che nessuno se ne accorga.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

DJANGO_APP = Path(__file__).resolve().parent.parent

# Moduli i cui pannelli devono essere governabili dal pannello Accessi.
MODULES_UNDER_ACL = (
    "automazioni/views.py",
    "automazioni/htmx_views.py",
    "monitoring/views.py",
    "tasks/views.py",
    "planimetria/views.py",
    "notizie/views.py",
    "assenze/views.py",
    "hub_tools/views.py",
)

BLIND_GATE_RE = re.compile(r"^\s*@(?:legacy_admin_required|_staff_required)\s*$", re.MULTILINE)


class AclGateCoverageTest(SimpleTestCase):
    def test_i_moduli_non_usano_piu_il_gate_cieco(self):
        offenders = {}
        for rel in MODULES_UNDER_ACL:
            path = DJANGO_APP / rel
            if not path.exists():  # il modulo puo' essere stato rinominato
                continue
            hits = BLIND_GATE_RE.findall(path.read_text(encoding="utf-8-sig"))
            if hits:
                offenders[rel] = len(hits)
        self.assertEqual(
            offenders,
            {},
            "Gate che ignorano l'ACL: usa legacy_admin_or_acl_required(modulo, azione). "
            f"Trovati in {offenders}",
        )

    def test_admin_portale_resta_riservato_per_scelta(self):
        """Non e' una svista: il pannello admin non si delega ai gruppi."""
        path = DJANGO_APP / "admin_portale" / "views.py"
        self.assertTrue(BLIND_GATE_RE.search(path.read_text(encoding="utf-8-sig")))
