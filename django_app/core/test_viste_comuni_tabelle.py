"""Viste comuni delle tabelle fm-table (menu «Viste ▾»): uguali per tutti, gestite dagli admin."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import SharedTableView, UserOnboarding, UserTablePreference

TID = "anagrafica.dipendenti.list"
URL = f"/api/table-prefs/{TID}/comuni/"
STATO = {"visible": ["nome", "reparto"], "order": ["nome", "reparto", "email"], "sort": [["nome", "asc"]], "filters": {}, "q": "", "group": ""}


class VisteComuniTabelleTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.utente = user_model.objects.create_user("vc-utente", password="x-Vc-2026!")
        self.admin = user_model.objects.create_superuser("vc-admin", "vc-admin@example.invalid", "x-Vc-2026!")
        UserOnboarding.objects.create(user=self.utente, completed=True)

    def _post(self, data):
        return self.client.post(URL, data=json.dumps(data), content_type="application/json")

    def test_percorso_aperto_a_ogni_utente_collegato(self):
        from core.middleware import is_acl_shared_path

        self.assertTrue(is_acl_shared_path(URL))

    def test_anonimo_riceve_json_401(self):
        r = self.client.get(URL)
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(r["Content-Type"].split(";")[0], "application/json")

    def test_utente_vede_ma_non_salva(self):
        SharedTableView.objects.create(table_id=TID, nome="Produzione", state_json=STATO)
        self.client.force_login(self.utente)
        with patch("core.views.can_manage_shared_table_views", return_value=False):
            data = self.client.get(URL).json()
            self.assertFalse(data["can_manage"])
            self.assertEqual([v["nome"] for v in data["viste"]], ["Produzione"])
            self.assertEqual(self._post({"nome": "Mia", "stato": STATO}).status_code, 403)
            self.assertEqual(self.client.delete(URL + "?id=1").status_code, 403)
        self.assertEqual(SharedTableView.objects.count(), 1)

    def test_admin_salva_sostituisce_e_una_sola_predefinita(self):
        self.client.force_login(self.admin)
        self.assertEqual(self._post({"nome": "Uno", "stato": STATO, "predefinita": True}).status_code, 200)
        self.assertEqual(self._post({"nome": "Due", "stato": STATO, "predefinita": True}).status_code, 200)
        self.assertEqual(self._post({"nome": "uno", "stato": {**STATO, "q": "x"}}).status_code, 200)
        self.assertEqual(SharedTableView.objects.filter(table_id=TID).count(), 2)
        self.assertEqual(list(SharedTableView.objects.filter(predefinita=True).values_list("nome", flat=True)), ["Due"])
        uno = SharedTableView.objects.get(nome__iexact="uno")
        self.assertEqual(uno.state_json["q"], "x")
        # Stella: cambia solo la predefinita.
        self.assertEqual(self._post({"id": uno.pk, "predefinita": True}).status_code, 200)
        self.assertEqual(list(SharedTableView.objects.filter(predefinita=True).values_list("nome", flat=True)), [uno.nome])
        self.assertEqual(self.client.delete(f"{URL}?id={uno.pk}").status_code, 200)
        self.assertFalse(SharedTableView.objects.filter(pk=uno.pk).exists())

    def test_preferenze_portano_la_predefinita_comune(self):
        SharedTableView.objects.create(table_id=TID, nome="Base", state_json=STATO, predefinita=True)
        self.client.force_login(self.utente)
        data = self.client.get(f"/api/table-prefs/{TID}/").json()
        self.assertEqual(data["state"], {})
        self.assertEqual(data["default"]["nome"], "Base")
        self.assertEqual(data["default"]["stato"]["visible"], ["nome", "reparto"])
        # Le preferenze proprie restano separate: la vista comune non le tocca.
        UserTablePreference.objects.create(user=self.utente, table_id=TID, state_json={"visible": ["email"]})
        data = self.client.get(f"/api/table-prefs/{TID}/").json()
        self.assertEqual(data["state"]["visible"], ["email"])
        self.assertEqual(data["default"]["nome"], "Base")
