"""Bozza del controllo anche su un OP nuovo non ancora creato, e promemoria per le bozze ferme.

Il controllo nasce subito con i dati del nuovo OP (``op_nuovo``): la bozza si salva sul
server come per gli OP esistenti e l'OP vero si crea al primo «Salva blocco». Una bozza
ferma senza anomalie da inviare manda al controllore notifica e mail con quello che ha
scritto. Tabelle legacy in SQLite, dati sintetici.
"""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie import controllo_service as cs
from anomalie import controllo_views as cv
from anomalie.quality_models import AnomaliaControllo
from anomalie.tests_controllo import LegacyTableMixin, _salva_finta

User = get_user_model()
NUOVO = {"causale_doc": "OP", "anno": "2026", "numero": "1500", "pn": "PN-7781-A",
         "capocommessa": "Mario Rossi", "car": "Anna Neri"}
TITOLO = "OP/2026/1500"


class OrdiniMixin:
    def crea_ordini(self):
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE ordini_produzione (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, "
                        "sharepoint_item_id TEXT, part_number TEXT, capocomessa TEXT, incaricato TEXT, stato TEXT)")

    def elimina_ordini(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE ordini_produzione")

    def conta_ordini(self):
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ordini_produzione")
            return cur.fetchone()[0]


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ControlloOpNuovoTests(OrdiniMixin, LegacyTableMixin, TestCase):
    def setUp(self):
        self.crea_tabella()
        self.crea_ordini()
        self.user = User.objects.create_superuser(username="bozza-op", password="pass12345", email="b@example.local")
        self.client.force_login(self.user)

        def crea_finto(request, dati):
            with connection.cursor() as cur:
                cur.execute("INSERT INTO ordini_produzione (title, sharepoint_item_id, part_number, capocomessa, "
                            "incaricato, stato) VALUES (%s, '-9', %s, %s, %s, 'Aperto')",
                            [TITOLO, dati["pn"], dati["capocommessa"], dati["car"]])
            return {"success": True, "op": {"item_id": "-9", "id": TITOLO, "pn": dati["pn"], "capo": dati["capocommessa"],
                                            "car": dati["car"], "stato": "Aperto"}, "error": "", "status": 200}

        self._patches = [
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views._salva_riga_anomalia", side_effect=_salva_finta),
            patch("anomalie.views.crea_op_da_dati", side_effect=crea_finto),
            patch("anomalie.controllo_views._sync_scheda"),
            patch("anomalie.controllo_service._allegati", return_value=[]),
            patch("anomalie.controllo_service.stati_superficie_configurati", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.elimina_tabella()
        self.elimina_ordini()

    def post(self, name, body, pk=None):
        url = reverse(name, args=[pk]) if pk else reverse(name)
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def apri(self):
        r = self.post("api_anomalie_controllo_apri", {"op_id": TITOLO, "op_nuovo": NUOVO, "fase": "Collaudo finale",
                                                       "mail_mode": "fine"})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["controllo"]

    def test_apertura_non_crea_l_op(self):
        c = self.apri()
        self.assertEqual(c["op_id"], TITOLO)
        self.assertEqual(c["op_nuovo"]["pn"], "PN-7781-A")
        self.assertEqual(self.conta_ordini(), 0)
        # La bozza si salva come per un OP esistente.
        r = self.post("api_anomalie_controllo_bozza", {"bozza": {"voci": ["LCN00001"], "anomalie": [{"testo": "Graffio"}]}},
                      c["id"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(AnomaliaControllo.objects.get(pk=c["id"]).bozza["voci"], ["LCN00001"])

    def test_op_gia_esistente(self):
        with connection.cursor() as cur:
            cur.execute("INSERT INTO ordini_produzione (title, sharepoint_item_id) VALUES (%s, '-1')", [TITOLO])
        r = self.post("api_anomalie_controllo_apri", {"op_id": TITOLO, "op_nuovo": NUOVO, "fase": "Collaudo"})
        self.assertEqual(r.status_code, 409)

    def test_dati_mancanti(self):
        r = self.post("api_anomalie_controllo_apri", {"op_id": TITOLO, "op_nuovo": {**NUOVO, "car": ""}, "fase": "Collaudo"})
        self.assertEqual(r.status_code, 400)

    def test_primo_blocco_crea_l_op(self):
        c = self.apri()
        r = self.post("api_anomalie_controllo_blocco", {
            "seriali": ["LCN00001"], "stato_superficie": [], "anomalie": [{"testo": "Graffio sulla flangia"}],
        }, c["id"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["op_creato"]["id"], TITOLO)
        self.assertEqual(self.conta_ordini(), 1)
        controllo = AnomaliaControllo.objects.get(pk=c["id"])
        self.assertEqual((controllo.op_nuovo, controllo.op_item_id), ({}, "-9"))
        # Secondo blocco: l'OP c'è già, non si ricrea.
        r = self.post("api_anomalie_controllo_blocco", {
            "seriali": ["LCN00002"], "stato_superficie": [], "anomalie": [{"testo": "Bava"}],
        }, c["id"])
        self.assertIsNone(r.json()["op_creato"])
        self.assertEqual(self.conta_ordini(), 1)

    def test_op_creato_nel_frattempo_si_aggancia(self):
        c = self.apri()
        with connection.cursor() as cur:
            cur.execute("INSERT INTO ordini_produzione (title, sharepoint_item_id, stato) VALUES (%s, '-4', 'Aperto')",
                        [TITOLO])
        op, errore = cv.crea_op_del_controllo(None, AnomaliaControllo.objects.get(pk=c["id"]))
        self.assertEqual((errore, op["item_id"]), ("", "-4"))
        self.assertEqual(self.conta_ordini(), 1)

    def test_riprendi_elenca_la_bozza_dell_op_nuovo(self):
        c = self.apri()
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=False):
            r = self.client.get(reverse("api_anomalie_controlli"), {"op_id": TITOLO})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["id"] for x in r.json()["controlli"]], [c["id"]])


class PromemoriaBozzaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ctl-bozza", password="x", email="ctl@example.local")
        self.controllo = AnomaliaControllo.objects.create(
            op_id=TITOLO, fase="Collaudo", operatore=self.user, op_nuovo=NUOVO,
            bozza={"voci": ["LCN00001-LCN00004"], "anomalie": [{"testo": "Bassopiani fuori quota", "allegati": 2}],
                   "coda": [{"seriali": ["LCN00010"], "anomalie": [{"testo": "Graffio"}]}]},
            bozza_at=timezone.now() - timedelta(minutes=30),
        )
        self.mail = []
        self._patches = [
            patch("anomalie.controllo_service._contatti_operatore", return_value=(None, "ctl@example.local")),
            patch("anomalie.mail_action_service.send_and_log_email",
                  side_effect=lambda **kw: (self.mail.append(kw) or (True, None))),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_mail_con_la_bozza(self):
        self.assertEqual(cs.promemoria_bozze(timezone.now(), 15), 1)
        body = self.mail[0]["body_text"]
        self.assertIn("non ancora creato", body)
        self.assertIn("Bassopiani fuori quota (+2 allegati da ricaricare)", body)
        self.assertIn("Da copiare ancora: 1 blocco con 1 anomalia", body)
        self.assertIn(f"controllo={self.controllo.pk}", body)
        # Uno per pausa: senza modifiche alla bozza non si ripete.
        self.assertEqual(cs.promemoria_bozze(timezone.now(), 15), 0)
        # La bozza cambia dopo il promemoria e poi resta ferma: nuovo promemoria.
        AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(
            promemoria_bozza_at=timezone.now() - timedelta(minutes=40), bozza_at=timezone.now() - timedelta(minutes=20))
        self.assertEqual(cs.promemoria_bozze(timezone.now(), 15), 1)

    def test_bozza_recente_o_con_anomalie_da_inviare(self):
        AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(bozza_at=timezone.now())
        self.assertEqual(cs.promemoria_bozze(timezone.now(), 15), 0)
        AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(
            bozza_at=timezone.now() - timedelta(minutes=30), da_notificare=[5])
        self.assertEqual(cs.promemoria_bozze(timezone.now(), 15), 0)  # ci pensa il promemoria del controllo

    def test_url_riapre_il_controllo(self):
        self.assertTrue(cs.url_controllo(self.controllo).endswith(f"&controllo={self.controllo.pk}"))
