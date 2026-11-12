"""Clona OP: anomalie scelte in Gestione copiate sul nuovo OP, a blocchi, con gli allegati.

Tabella legacy ``anomalie`` in SQLite (come in ``tests_controllo``). Dati sintetici.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from anomalie.tests_controllo import LegacyTableMixin, _salva_finta

User = get_user_model()
OP = "OP/2026/0042"


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ClonaOpTests(LegacyTableMixin, TestCase):
    def setUp(self):
        self.crea_tabella()
        self.user = User.objects.create_superuser(username="clona-op", password="pass12345", email="cl@example.local")
        self.client.force_login(self.user)
        self._patches = [
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
            patch("anomalie.views._salva_riga_anomalia", side_effect=_salva_finta),
            patch("anomalie.controllo_views._sync_scheda"),
            patch("anomalie.controllo_service._allegati", return_value=[]),
            patch("anomalie.controllo_service.stati_superficie_configurati", return_value=False),
            # ``SELECT TOP 1`` è SQL Server: qui la stessa lettura in SQLite.
            patch("anomalie.views._anomaly_local_row", side_effect=self._riga_op),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.elimina_tabella()

    def post(self, name, body, pk=None):
        url = reverse(name, args=[pk]) if pk else reverse(name)
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def _blocco(self):
        cid = self.post("api_anomalie_controllo_apri", {"op_id": OP, "fase": "Collaudo finale"}).json()["controllo"]["id"]
        r = self.post("api_anomalie_controllo_blocco", {
            "seriali": ["LCN00001-LCN00004"],
            "stato_superficie": ["Finito trattato"],
            "anomalie": [
                {"testo": "Graffio su tutto il lotto"},
                {"testo": "Foro fuori quota", "tutti": False, "seriali": ["LCN00002", "LCN00003"]},
            ],
        }, cid)
        self.assertEqual(r.status_code, 200, r.content)
        return [x["local_id"] for x in r.json()["risultati"]]

    @staticmethod
    def _riga_op(local_id):
        with connection.cursor() as cur:
            cur.execute("SELECT id, ex_op_nominativo FROM anomalie WHERE id = %s", [int(local_id)])
            r = cur.fetchone()
        return {"id": r[0], "ex_op_nominativo": r[1]} if r else None

    def _riga_libera(self, seriale, testo, op=OP):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anomalie (ex_op_nominativo, seriale, descrizione, chiudere, avanzamento) VALUES (%s, %s, %s, 1, 'Accetto lo stato')",
                [op, seriale, testo],
            )
            cur.execute("SELECT MAX(id) FROM anomalie")
            return int(cur.fetchone()[0])

    def _dati(self, ids, op=OP):
        return self.client.get(reverse("api_anomalie_clona"), {"op_id": op, "anomalie": ",".join(map(str, ids))})

    def test_blocchi_con_seriali_stato_e_copertura(self):
        ids = self._blocco()
        libera = self._riga_libera("ABC00007, ABC00008", "Bava sul bordo")
        altro_op = self._riga_libera("ZZZ00001", "Non va copiata", op="OP/2026/0099")
        r = self._dati([*ids, libera, altro_op])
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(data["fase"], "Collaudo finale")
        self.assertEqual(len(data["blocchi"]), 2)
        primo, secondo = data["blocchi"]
        self.assertEqual(primo["seriali"], ["LCN00001-LCN00004"])
        self.assertEqual(primo["stato_superficie"], ["Finito trattato"])
        self.assertEqual([a["testo"] for a in primo["anomalie"]], ["Graffio su tutto il lotto", "Foro fuori quota"])
        self.assertEqual([a["tutti"] for a in primo["anomalie"]], [True, False])
        self.assertEqual(primo["anomalie"][1]["seriali"], ["LCN00002-LCN00003"])
        self.assertEqual([a["origine_id"] for a in primo["anomalie"]], ids)
        # Anomalia nata fuori da un controllo: un blocco da sola, con i suoi S/N.
        self.assertEqual(secondo["seriali"], ["ABC00007-ABC00008"])
        self.assertEqual(secondo["anomalie"][0]["testo"], "Bava sul bordo")

    def test_solo_chi_vede_l_op(self):
        ids = self._blocco()
        with patch("anomalie.views._can_view_anomalie_for_op", return_value=False):
            self.assertEqual(self._dati(ids).status_code, 403)

    def test_richiede_anomalie(self):
        self.assertEqual(self._dati([]).status_code, 400)

    def test_copia_allegati(self):
        da = self._riga_libera("LCN00001", "Graffio")
        a = self._riga_libera("LCN00009", "Graffio", op="OP/2026/0100")
        with tempfile.TemporaryDirectory() as tmp, patch("anomalie.views._anomalie_attachments_root", return_value=Path(tmp)):
            (Path(tmp) / str(da)).mkdir()
            (Path(tmp) / str(da) / "abc123__foto.jpg").write_bytes(b"jpeg")
            r = self.post("api_anomalie_allegati_copia", {"da": da, "a": a})
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json()["copiati"], 1)
            copiati = list((Path(tmp) / str(a)).iterdir())
            self.assertEqual(len(copiati), 1)
            self.assertTrue(copiati[0].name.endswith("__foto.jpg"))
            self.assertEqual(copiati[0].read_bytes(), b"jpeg")

    def test_copia_allegati_negata_senza_permesso_sulla_destinazione(self):
        da = self._riga_libera("LCN00001", "Graffio")
        a = self._riga_libera("LCN00009", "Graffio", op="OP/2026/0100")
        with patch("anomalie.views._can_attach_anomalia", return_value=False):
            self.assertEqual(self.post("api_anomalie_allegati_copia", {"da": da, "a": a}).status_code, 403)

    def test_copia_anche_le_misure(self):
        from anomalie.quality_models import AnomaliaSchedaQualita

        ids = self._blocco()
        dettaglio = {"tipo": "misura", "misure": [{"car": "diametro", "modo": "minmax", "a": "1", "b": "2", "ril": "2.1"}]}
        AnomaliaSchedaQualita.objects.update_or_create(anomalia_id=ids[0], defaults={
            "op_titolo": OP, "dettaglio_controllo": dettaglio, "dove_pezzi": "Area NC"})
        primo = self._dati(ids).json()["blocchi"][0]
        self.assertEqual(primo["anomalie"][0]["dettaglio"], dettaglio)
        self.assertEqual(primo["anomalie"][1]["dettaglio"], {})
        self.assertNotIn("dove_pezzi", primo)  # i pezzi del nuovo OP sono altri
