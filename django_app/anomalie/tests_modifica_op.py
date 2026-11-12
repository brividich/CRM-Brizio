"""«Modifica OP» da Gestione anomalie: solo il controllore che ha creato l'OP dal portale,
con motivazione, AuditLog e cronologia dell'OP. Tabella legacy in SQLite, dati sintetici.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from anomalie import modifica_op as mo
from anomalie.mail_action_models import AnomaliaActionLog
from core.legacy_utils import legacy_table_columns
from core.models import AuditLog

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ModificaOpTests(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE ordini_produzione (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, "
                "sharepoint_item_id TEXT, part_number TEXT, capocomessa TEXT, incaricato TEXT, stato TEXT, "
                "in1text TEXT, created_by TEXT, modified_by TEXT, modified_datetime TEXT)"
            )
            righe = [
                ("OP/2026/0901", "-1", "PN-1", "Mario Rossi", "Anna Neri", "Aperto", "Fase 20 | nota", "Dario Verdi"),
                ("OP/2026/0902", "-2", "PN-2", "Mario Rossi", "Anna Neri", "Aperto", "", "Luca Bianchi"),
                ("OP/2026/0903", "77", "PN-3", "Mario Rossi", "Anna Neri", "Aperto", "", "Dario Verdi"),
            ]
            for r in righe:
                cur.execute(
                    "INSERT INTO ordini_produzione (title, sharepoint_item_id, part_number, capocomessa, incaricato, "
                    "stato, in1text, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", list(r)
                )
        legacy_table_columns.cache_clear()
        self.addCleanup(legacy_table_columns.cache_clear)
        self.user = User.objects.create_superuser(username="ctl-modop", password="pass12345",
                                                  email="ctl@example.local", first_name="Dario", last_name="Verdi")
        self.client.force_login(self.user)

    def tearDown(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE ordini_produzione")

    def url(self):
        return reverse("api_anomalie_op_modifica")

    def post(self, body):
        return self.client.post(self.url(), data=json.dumps(body), content_type="application/json")

    def riga(self, item_id):
        return mo.riga_op(item_id)

    def test_solo_op_locali_creati_da_me(self):
        req = RequestFactory().get("/")
        req.user = self.user
        self.assertEqual(mo.op_modificabili_da(req), {"-1"})

    def test_get_restituisce_i_campi_scomposti(self):
        r = self.client.get(self.url(), {"item_id": "-1"})
        self.assertEqual(r.status_code, 200)
        op = r.json()["op"]
        self.assertEqual((op["pn"], op["fase"], op["note"], op["benestare"]), ("PN-1", "20", "nota", False))

    def test_altro_autore_o_op_del_gestionale_negati(self):
        self.assertEqual(self.client.get(self.url(), {"item_id": "-2"}).status_code, 403)
        self.assertEqual(self.client.get(self.url(), {"item_id": "77"}).status_code, 403)
        r = self.post({"item_id": "-2", "pn": "X", "motivazione": "prova di modifica"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.riga("-2")["part_number"], "PN-2")

    def test_motivazione_obbligatoria(self):
        r = self.post({"item_id": "-1", "pn": "PN-1-B", "motivazione": ""})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.riga("-1")["part_number"], "PN-1")

    def test_nessun_cambio_e_campo_obbligatorio_vuoto(self):
        self.assertEqual(self.post({"item_id": "-1", "pn": "PN-1", "motivazione": "nessun cambio"}).status_code, 400)
        self.assertEqual(self.post({"item_id": "-1", "capocommessa": " ", "motivazione": "svuoto"}).status_code, 400)

    def test_modifica_scrive_dati_audit_e_cronologia(self):
        r = self.post({"item_id": "-1", "pn": "PN-1-B", "car": "Bruno Gialli", "fase": "20", "note": "nota",
                       "benestare": True, "motivazione": "P/N scritto male"})
        self.assertEqual(r.status_code, 200, r.content)
        row = self.riga("-1")
        self.assertEqual(row["part_number"], "PN-1-B")
        self.assertEqual(row["incaricato"], "Bruno Gialli")
        self.assertEqual(row["stato"], "Benestare")
        self.assertEqual(row["in1text"], "Fase 20 | Collaudo benestare: SI | nota")
        with connection.cursor() as cur:
            cur.execute("SELECT modified_by FROM ordini_produzione WHERE sharepoint_item_id = '-1'")
            self.assertEqual(cur.fetchone()[0].casefold(), "dario verdi")
        self.assertEqual(row["title"], "OP/2026/0901")
        campi = {m["campo"] for m in r.json()["modifiche"]}
        self.assertEqual(campi, {"pn", "car", "benestare"})

        audit = AuditLog.objects.filter(azione="op_modificato").latest("id")
        self.assertEqual(audit.dettaglio["motivazione"], "P/N scritto male")
        self.assertEqual(audit.dettaglio["prima"]["pn"], "PN-1")
        log = AnomaliaActionLog.objects.get(action="op_modificato")
        self.assertEqual((log.anomalia_id, log.op_id), (0, "OP/2026/0901"))
        self.assertIn("P/N: PN-1 → PN-1-B", log.note)
        self.assertIn("Motivo: P/N scritto male", log.note)

        tl = self.client.get(reverse("api_anomalie_timeline"), {"op_id": "OP/2026/0901"}).json()["items"]
        self.assertEqual(tl[0]["action_label"], "Dati dell'OP modificati")

    def test_flag_nell_elenco_ordini(self):
        # La query aggregata è T-SQL (TRY_CAST): qui si finge il suo risultato.
        righe = [{"item_id": i, "op_title": t, "part_number": "PN", "incaricato": "", "capocomessa": "Mario Rossi",
                  "stato": "Aperto"} for i, t in (("-1", "OP/2026/0901"), ("-2", "OP/2026/0902"), ("77", "OP/2026/0903"))]
        with patch("anomalie.views._fetch_all_dict", return_value=righe), \
                patch("anomalie.views._has_table", return_value=True):
            r = self.client.get(reverse("api_anomalie_ordini"))
        self.assertEqual(r.status_code, 200)
        flag = {o["id"]: o.get("can_modifica_op") for o in r.json()}
        self.assertEqual(flag, {"OP/2026/0901": True, "OP/2026/0902": False, "OP/2026/0903": False})
