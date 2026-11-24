"""Memoria dei permessi per i controlli in blocco (menu, richieste GET): stessi esiti, meno query."""
from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from core.acl_resolver import memo_attiva, memo_permessi, resolve_permission_decision
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Ruolo, UtenteLegacy
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    GroupPermissionGrant,
    PermissionDefinition,
    UserPermissionGrant,
)
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

RUOLO_ID = 78
CODICI = [f"assets.pagina_{i}.view" for i in range(8)]


@override_settings(LEGACY_AUTH_ENABLED=True)
class MemoPermessiTests(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        Ruolo.objects.create(id=RUOLO_ID, nome="manutenzione")
        self.utente = UtenteLegacy.objects.create(
            nome="Mario Memo", email="memo@example.local", password="x", ruolo="manutenzione",
            attivo=True, deve_cambiare_password=False, ruolo_id=RUOLO_ID,
        )
        self.permessi = {c: PermissionDefinition.objects.create(code=c, label=c, module="assets") for c in CODICI}
        gruppo = AccessGroup.objects.create(code="memo", label="Memo", priority=100)
        AccessGroupMembership.objects.create(group=gruppo, legacy_user_id=self.utente.id)
        for c in CODICI[:3]:
            GroupPermissionGrant.objects.create(group=gruppo, permission=self.permessi[c], enabled=True)
        GroupPermissionGrant.objects.create(group=gruppo, permission=self.permessi[CODICI[3]], enabled=False)
        UserPermissionGrant.objects.create(legacy_user_id=self.utente.id, permission=self.permessi[CODICI[4]], enabled=True)
        UserPermissionGrant.objects.create(legacy_user_id=self.utente.id, permission=self.permessi[CODICI[0]], enabled=False)
        bump_legacy_cache_version()

    def _esiti(self):
        return [
            (resolve_permission_decision(permission_code=c, legacy_user=self.utente).allowed,
             resolve_permission_decision(permission_code=c, legacy_user=self.utente).level)
            for c in CODICI
        ]

    def test_stessi_esiti_con_e_senza_memoria(self):
        senza = self._esiti()
        with memo_permessi():
            con = self._esiti()
        self.assertEqual(senza, con)
        # Override personale che nega vince sul gruppo che concede.
        self.assertFalse(con[0][0])
        self.assertTrue(con[4][0])

    def test_meno_query_con_la_memoria(self):
        with CaptureQueriesContext(connection) as senza:
            self._esiti()
        with memo_permessi(), CaptureQueriesContext(connection) as con:
            self._esiti()
        self.assertLess(len(con.captured_queries), len(senza.captured_queries) / 2)

    def test_memoria_solo_dentro_il_blocco(self):
        self.assertIsNone(memo_attiva())
        with memo_permessi():
            self.assertIsNotNone(memo_attiva())
            with memo_permessi():  # annidato: stessa memoria
                self.assertIsNotNone(memo_attiva())
        self.assertIsNone(memo_attiva())
