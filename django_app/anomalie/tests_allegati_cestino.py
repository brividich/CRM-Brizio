"""Allegati tolti: finiscono nel cestino dell'anomalia e si possono ripristinare."""
from __future__ import annotations

import json
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from anomalie import views as anomalie_views

LOCAL_ID = 4243
FILE_ID = "0123456789abcdef0123456789abcdef__foto.png"


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AllegatiCestinoTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-cestino", password="pass12345")
        self.factory = RequestFactory()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root / str(LOCAL_ID)
        self.folder.mkdir()
        (self.folder / FILE_ID).write_bytes(b"\x89PNG-uno")

    def _chiama(self, vista, nome_url, file_id, *, puo=True):
        req = self.factory.post(reverse(nome_url), data=json.dumps({"local_id": LOCAL_ID, "file_id": file_id}),
                                content_type="application/json")
        req.user = self.user
        req.legacy_user = None
        with ExitStack() as stack:
            stack.enter_context(patch("anomalie.views._anomalie_attachments_root", return_value=self.root))
            stack.enter_context(patch("anomalie.views._anomaly_local_row",
                                      return_value={"id": LOCAL_ID, "ex_op_nominativo": "OP/A"}))
            stack.enter_context(patch("anomalie.views._can_attach_anomalia", return_value=puo))
            stack.enter_context(patch("anomalie.views.log_action"))
            self.registro = stack.enter_context(patch("anomalie.views._registro_allegati"))
            resp = vista.__wrapped__(req)
        return resp, json.loads(resp.content)

    def _togli(self, file_id=FILE_ID, **kw):
        return self._chiama(anomalie_views.api_anomalie_allegati_delete, "api_anomalie_allegati_delete", file_id, **kw)

    def _ripristina(self, file_id=FILE_ID, **kw):
        return self._chiama(anomalie_views.api_anomalie_allegati_ripristina, "api_anomalie_allegati_ripristina",
                            file_id, **kw)

    def test_togliere_non_cancella_il_file(self):
        resp, body = self._togli()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["attachments"], [])
        self.assertEqual([f["name"] for f in body["removed"]], ["foto.png"])
        self.assertFalse((self.folder / FILE_ID).exists())
        self.assertEqual((self.folder / "_cestino" / FILE_ID).read_bytes(), b"\x89PNG-uno")
        self.assertEqual(self.registro.call_args.args[3], "allegato_tolto")

    def test_ripristina_rimette_l_allegato(self):
        self._togli()
        resp, body = self._ripristina()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([f["file_id"] for f in body["attachments"]], [FILE_ID])
        self.assertEqual(body["removed"], [])
        self.assertEqual((self.folder / FILE_ID).read_bytes(), b"\x89PNG-uno")
        self.assertEqual(self.registro.call_args.args[3], "allegato_ripristinato")

    def test_il_cestino_non_compare_tra_gli_allegati(self):
        self._togli()
        with patch("anomalie.views._anomalie_attachments_root", return_value=self.root):
            self.assertEqual(anomalie_views._list_attachments_for_local(LOCAL_ID), [])
            self.assertIsNone(anomalie_views._resolve_anomalia_attachment_path(LOCAL_ID, "_cestino"))

    def test_stesso_nome_tolto_due_volte_non_si_sovrascrive(self):
        self._togli()
        (self.folder / FILE_ID).write_bytes(b"\x89PNG-due")
        _resp, body = self._togli()
        self.assertEqual(len(body["removed"]), 2)
        contenuti = sorted(p.read_bytes() for p in (self.folder / "_cestino").iterdir())
        self.assertEqual(contenuti, [b"\x89PNG-due", b"\x89PNG-uno"])

    def test_ripristina_senza_permesso_o_fuori_dal_cestino(self):
        self._togli()
        resp, _ = self._ripristina(puo=False)
        self.assertEqual(resp.status_code, 403)
        for cattivo in ("..", "../" + FILE_ID, "__sync_meta__.json", "non-esiste__x.png"):
            resp, _ = self._ripristina(cattivo)
            self.assertEqual(resp.status_code, 404, cattivo)
        self.assertTrue((self.folder / "_cestino" / FILE_ID).exists())
