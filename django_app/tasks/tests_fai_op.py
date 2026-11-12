"""Campo OP della scheda FAI collegato all'elenco unico degli OP (tabella ordini_produzione).

Tabelle legacy create in SQLite, dati sintetici.
"""
from __future__ import annotations

from django.db import connection
from django.urls import reverse

from core import ordini_produzione as op_db
from core.legacy_utils import legacy_table_columns

from .models import FaiArticolo, FaiFase, FaiGruppo, FaiOpzione, FaiRecord
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions


class OpBase(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        # Le colonne delle tabelle legacy restano in memoria: qui le tabelle nascono e muoiono a ogni test.
        legacy_table_columns.cache_clear()
        self.addCleanup(legacy_table_columns.cache_clear)
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE ordini_produzione (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, "
                "sharepoint_item_id TEXT, part_number TEXT, capocomessa TEXT, incaricato TEXT, stato TEXT)"
            )
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY AUTOINCREMENT, ex_op_nominativo TEXT, "
                "op_lookup_id INTEGER, chiudere INTEGER)"
            )
            cur.executemany(
                "INSERT INTO ordini_produzione (title, sharepoint_item_id, part_number, capocomessa, incaricato, stato) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    ("OP/2026/100", "41", "PN-ALFA-1", "Capo Uno", "Car Uno", "Aperto"),
                    ("OP/2026/101", "-3", "PN-BETA-2", "Capo Due", "Car Due", "Benestare"),
                    ("OP/2025/900", "7", "PN-ALFA-1", "", "", "Chiuso"),
                ],
            )
            cur.executemany(
                "INSERT INTO anomalie (ex_op_nominativo, op_lookup_id, chiudere) VALUES (%s, %s, %s)",
                [("OP/2026/100", 41, 0), ("OP/2026/100", 41, 1), ("op/2026/100", None, 0), ("OP/2026/101", -3, 1)],
            )
        self.admin = _create_user_with_legacy(username="op-adm", legacy_user_id=671, role_id=1, role_name="admin")
        self.client.force_login(self.admin)

    def tearDown(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")
            cur.execute("DROP TABLE ordini_produzione")
        super().tearDown()

    def _fai(self, op, pn="PN-ALFA-1"):
        return FaiRecord.objects.create(
            articolo=FaiArticolo.objects.create(client_name="Cliente Alfa", part_number=pn),
            stato=FaiOpzione.objects.filter(gruppo=FaiGruppo.STATO, fase=FaiFase.IN_CORSO).first(),
            tipo="COMPLETO", op=op,
        )


class ServizioOpTest(OpBase):
    def test_cerca_per_titolo_e_per_pn(self):
        self.assertEqual([r["op"] for r in op_db.cerca("2026/10")], ["OP/2026/100", "OP/2026/101"])
        self.assertEqual([r["op"] for r in op_db.cerca("alfa")], ["OP/2025/900", "OP/2026/100"])
        self.assertEqual(op_db.cerca("a"), [])

    def test_per_titolo_ignora_maiuscole_e_spazi(self):
        op = op_db.per_titolo("  op/2026/100 ")
        self.assertEqual((op["op"], op["capocommessa"], op["car"]), ("OP/2026/100", "Capo Uno", "Car Uno"))
        self.assertIsNone(op_db.per_titolo("OP/1999/1"))

    def test_anomalie_contate_come_in_gestione_anomalie(self):
        self.assertEqual(op_db.conta_anomalie(op_db.per_titolo("OP/2026/100")), {"totale": 3, "aperte": 2})
        self.assertEqual(op_db.conta_anomalie(op_db.per_titolo("OP/2026/101")), {"totale": 1, "aperte": 0})


class SchedaOpTest(OpBase):
    def test_scheda_mostra_l_op_collegato(self):
        pagina = self.client.get(reverse("tasks:fai_scheda", args=[self._fai("OP/2026/100").pk]))
        op = pagina.context["op_collegato"]
        self.assertTrue(op["trovato"])
        self.assertFalse(op["pn_diverso"])
        self.assertContains(pagina, "3 anomalie, 2 aperte in Gestione anomalie")
        self.assertContains(pagina, "/gestione-anomalie?op=OP%2F2026%2F100&amp;filter=tutti")

    def test_avvisa_se_il_pn_dell_op_e_diverso(self):
        pagina = self.client.get(reverse("tasks:fai_scheda", args=[self._fai("OP/2026/101").pk]))
        self.assertContains(pagina, "L'OP è del P/N PN-BETA-2")

    def test_op_fuori_elenco_si_salva_lo_stesso(self):
        pagina = self.client.get(reverse("tasks:fai_scheda", args=[self._fai("OP/2020/5").pk]))
        self.assertFalse(pagina.context["op_collegato"]["trovato"])
        self.assertContains(pagina, "non è nell'elenco OP di Gestione anomalie")

    def test_senza_op_nessun_riquadro(self):
        pagina = self.client.get(reverse("tasks:fai_scheda", args=[self._fai("").pk]))
        self.assertIsNone(pagina.context["op_collegato"])


class EndpointOpTest(OpBase):
    def test_ricerca_e_dettaglio(self):
        url = reverse("tasks:fai_op")
        dati = self.client.get(url, {"q": "beta"}).json()
        self.assertEqual([r["op"] for r in dati["risultati"]], ["OP/2026/101"])
        dettaglio = self.client.get(url, {"op": "OP/2026/100", "pn": "PN-ALTRO"}).json()["op"]
        self.assertEqual(dettaglio["anomalie"], {"totale": 3, "aperte": 2})
        self.assertTrue(dettaglio["pn_diverso"])
        self.assertIsNone(self.client.get(url, {"op": "OP/1999/1"}).json()["op"])

    def test_utente_kickoff_senza_superuser_entra(self):
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view"])
        self.client.force_login(_create_user_with_legacy(username="op-est", legacy_user_id=672, role_id=2, role_name="tasks"))
        self.assertEqual(self.client.get(reverse("tasks:fai_op"), {"q": "2026"}).status_code, 200)

    def test_anonimo_riceve_json_401(self):
        self.client.logout()
        risposta = self.client.get(reverse("tasks:fai_op"), {"q": "2026"}, HTTP_ACCEPT="application/json")
        self.assertEqual(risposta.status_code, 401)
        self.assertEqual(risposta["Content-Type"], "application/json")
