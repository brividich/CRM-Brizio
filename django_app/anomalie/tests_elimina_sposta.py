"""Eliminare (solo chi l'ha inserita) e «Taglia» (spostare su altro S/N/OP) una singola
anomalia finché non ha avanzamenti. Tabella legacy in SQLite, dati sintetici."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from anomalie import views as av
from core.legacy_utils import legacy_table_columns
from anomalie.mail_action_models import AnomaliaActionLog, AnomaliaPendingNotification
from anomalie.quality_models import (
    AnomaliaBlocco,
    AnomaliaControllo,
    AnomaliaEsito,
    AnomaliaSchedaQualita,
    AnomaliaSegnalazioneMeta,
)

User = get_user_model()
OP = "OP/2026/0771"
OP2 = "OP/2026/0772"
ME = 7


class _Base(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY AUTOINCREMENT, ex_op_nominativo TEXT, seriale TEXT, "
                "descrizione TEXT, note_capocommessa TEXT, aprire_rdc INTEGER, numero_rdc TEXT, "
                "segnalare_cliente INTEGER, chiudere INTEGER, avanzamento TEXT, pezzo_recuperato INTEGER, "
                "created_by_user_id INTEGER, op_lookup_id INTEGER, created_datetime TEXT)"
            )
        # Colonne della tabella legacy in cache: le ricalcola su questa tabella e dopo il test.
        legacy_table_columns.cache_clear()
        self.addCleanup(legacy_table_columns.cache_clear)
        self.controllo = AnomaliaControllo.objects.create(op_id=OP, fase="Collaudo finale")
        self.b1 = AnomaliaBlocco.objects.create(controllo=self.controllo, ordine=1, fase="Collaudo finale",
                                                seriali=["LCN00001"], seriale_label="LCN00001",
                                                stato_superficie=["Finito macchinato"])
        self.b2 = AnomaliaBlocco.objects.create(controllo=self.controllo, ordine=2, fase="Collaudo finale",
                                                seriali=["LCN00002-LCN00004"], seriale_label="LCN00002-LCN00004 (3 pezzi)")
        self.a1 = self.crea("LCN00001", "Graffio sul diametro", self.b1)
        self.a2 = self.crea("LCN00001", "Foro fuori quota", self.b1)
        self.a3 = self.crea("LCN00002-LCN00004 (3 pezzi)", "Bava", self.b2)
        self.controllo.da_notificare = [self.a1, self.a2, self.a3]
        self.controllo.save()

    def tearDown(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")

    def crea(self, sn, testo, blocco, *, autore=ME, op=OP, avanzamento="In attesa"):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anomalie (ex_op_nominativo, seriale, descrizione, note_capocommessa, aprire_rdc,"
                " segnalare_cliente, chiudere, avanzamento, created_by_user_id) VALUES (%s, %s, %s, '', 0, 0, 0, %s, %s)",
                [op, sn, testo, avanzamento, autore],
            )
            cur.execute("SELECT MAX(id) FROM anomalie")
            local_id = int(cur.fetchone()[0])
        AnomaliaSegnalazioneMeta.objects.create(anomalia_id=local_id, controllo=self.controllo, blocco=blocco,
                                                fase="Collaudo finale")
        AnomaliaSchedaQualita.objects.create(anomalia_id=local_id, op_titolo=op)
        return local_id

    def riga(self, local_id):
        with connection.cursor() as cur:
            cur.execute("SELECT ex_op_nominativo, seriale, avanzamento FROM anomalie WHERE id = %s", [local_id])
            r = cur.fetchone()
        return dict(zip(["op", "seriale", "avanzamento"], r)) if r else None

    def set_riga(self, local_id, **campi):
        sets = ", ".join(f"{k} = %s" for k in campi)
        with connection.cursor() as cur:
            cur.execute(f"UPDATE anomalie SET {sets} WHERE id = %s", [*campi.values(), local_id])


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class _Api(_Base):
    creatore = True
    edit_op = False

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser(username="ctl-elim", password="pass12345", email="ctl@example.local")
        self.client.force_login(self.user)
        self._patches = [
            patch.object(av, "_is_creatore_anomalia", side_effect=lambda req, lid: self.creatore),
            patch.object(av, "_can_edit_anomalie_for_op", side_effect=lambda req, op: self.edit_op),
            patch.object(av, "_can_create_anomalie_for_op", return_value=True),
            patch("anomalie.controllo_views._op_esiste", return_value=True),
            patch("anomalie.qualita_service.sync_da_anomalia", return_value=None),
            patch("anomalie.mail_action_service._fetch_pn_for_ops", return_value={}),
            patch("anomalie.elimina_sposta._allegati_in_cestino", return_value=""),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        super().tearDown()

    def post(self, name, body):
        return self.client.post(reverse(name), data=json.dumps(body), content_type="application/json")


class EliminaTests(_Api):
    def test_elimina_riga_dati_e_code(self):
        AnomaliaPendingNotification.objects.create(op_id=OP, last_modified_at="2026-11-05T10:00:00Z",
                                                   updates_snapshot=[{"id": self.a2}, {"id": self.a1}])
        AnomaliaActionLog.objects.create(anomalia_id=self.a2, op_id=OP, action="crea")
        r = self.post("api_anomalie_elimina", {"local_id": self.a2})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNone(self.riga(self.a2))
        self.assertFalse(AnomaliaSegnalazioneMeta.objects.filter(anomalia_id=self.a2).exists())
        self.assertFalse(AnomaliaSchedaQualita.objects.filter(anomalia_id=self.a2).exists())
        # Il registro attività resta, con l'evento «elimina» e S/N e testo dell'anomalia.
        self.assertTrue(AnomaliaActionLog.objects.filter(anomalia_id=self.a2, action="crea").exists())
        ev = AnomaliaActionLog.objects.get(anomalia_id=self.a2, action="elimina")
        self.assertIn("seriale", ev.payload)
        self.controllo.refresh_from_db()
        self.assertEqual(self.controllo.da_notificare, [self.a1, self.a3])
        p = AnomaliaPendingNotification.objects.get(op_id=OP)
        self.assertEqual(p.updates_snapshot, [{"id": self.a1}])
        self.assertFalse(p.notified)
        # Il blocco ha ancora un'anomalia: resta.
        self.assertTrue(AnomaliaBlocco.objects.filter(pk=self.b1.pk).exists())

    def test_ultima_anomalia_del_blocco_porta_via_il_blocco(self):
        AnomaliaPendingNotification.objects.create(op_id=OP, last_modified_at="2026-11-05T10:00:00Z",
                                                   updates_snapshot=[{"id": self.a3}])
        r = self.post("api_anomalie_elimina", {"local_id": self.a3})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(AnomaliaBlocco.objects.filter(pk=self.b2.pk).exists())
        # Riepilogo rimasto vuoto: niente mail.
        self.assertTrue(AnomaliaPendingNotification.objects.get(op_id=OP).notified)

    def test_solo_chi_l_ha_inserita(self):
        self.creatore = False
        self.edit_op = True
        r = self.post("api_anomalie_elimina", {"local_id": self.a1})
        self.assertEqual(r.status_code, 403)
        self.assertIsNotNone(self.riga(self.a1))

    def test_con_decisione_non_si_elimina(self):
        self.set_riga(self.a1, avanzamento="Accetto lo stato")
        r = self.post("api_anomalie_elimina", {"local_id": self.a1})
        self.assertEqual(r.status_code, 409)
        self.assertIn("decisione", r.json()["error"])
        self.assertIsNotNone(self.riga(self.a1))

    def test_con_esito_non_si_elimina(self):
        AnomaliaEsito.objects.create(anomalia_id=self.a1, tipo=AnomaliaEsito.Tipo.AZIONE, azione="Ripresa")
        self.assertEqual(self.post("api_anomalie_elimina", {"local_id": self.a1}).status_code, 409)

    def test_presa_in_carico_non_si_elimina(self):
        AnomaliaActionLog.objects.create(anomalia_id=self.a1, op_id=OP, action="prendi_in_carico")
        self.assertEqual(self.post("api_anomalie_elimina", {"local_id": self.a1}).status_code, 409)

    def test_segnala_terzista_non_si_elimina(self):
        AnomaliaSchedaQualita.objects.filter(anomalia_id=self.a1).update(segnala_terzista=True)
        self.assertEqual(self.post("api_anomalie_elimina", {"local_id": self.a1}).status_code, 409)

    def test_anomalia_inesistente(self):
        self.assertEqual(self.post("api_anomalie_elimina", {"local_id": 99999}).status_code, 404)


class TagliaTests(_Api):
    def test_stesso_op_in_blocco_esistente(self):
        r = self.post("api_anomalie_sposta", {"local_id": self.a2, "op_id": OP, "seriali": ["LCN00003"]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.riga(self.a2)["seriale"], "LCN00003")
        meta = AnomaliaSegnalazioneMeta.objects.get(anomalia_id=self.a2)
        self.assertEqual(meta.blocco_id, self.b2.pk)
        self.assertEqual(meta.controllo_id, self.controllo.pk)
        self.assertIn("da S/N LCN00001 a S/N LCN00003", r.json()["nota"])
        self.assertTrue(AnomaliaActionLog.objects.filter(anomalia_id=self.a2, action="spostata").exists())

    def test_blocco_intero_prende_l_etichetta_del_blocco(self):
        r = self.post("api_anomalie_sposta", {"local_id": self.a1, "op_id": OP, "seriali": ["LCN00002-LCN00004"]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.riga(self.a1)["seriale"], "LCN00002-LCN00004 (3 pezzi)")

    def test_stesso_op_s_n_nuovo_crea_blocco_e_toglie_quello_vuoto(self):
        r = self.post("api_anomalie_sposta", {"local_id": self.a3, "op_id": OP, "seriali": "LCN00009"})
        self.assertEqual(r.status_code, 200, r.content)
        meta = AnomaliaSegnalazioneMeta.objects.get(anomalia_id=self.a3)
        nuovo = AnomaliaBlocco.objects.get(pk=meta.blocco_id)
        self.assertEqual((nuovo.seriali, nuovo.ordine), (["LCN00009"], 3))
        self.assertFalse(AnomaliaBlocco.objects.filter(pk=self.b2.pk).exists())
        self.controllo.refresh_from_db()
        self.assertIn(self.a3, self.controllo.da_notificare)

    def test_altro_op_esce_dal_controllo_e_va_nel_riepilogo(self):
        AnomaliaPendingNotification.objects.create(op_id=OP, last_modified_at="2026-11-05T10:00:00Z",
                                                   updates_snapshot=[{"id": self.a1}, {"id": self.a2}])
        r = self.post("api_anomalie_sposta", {"local_id": self.a1, "op_id": OP2, "seriali": ["XKC00010"]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.riga(self.a1), {"op": OP2, "seriale": "XKC00010", "avanzamento": "In attesa"})
        meta = AnomaliaSegnalazioneMeta.objects.get(anomalia_id=self.a1)
        self.assertIsNone(meta.controllo_id)
        self.assertIsNone(meta.blocco_id)
        self.controllo.refresh_from_db()
        self.assertNotIn(self.a1, self.controllo.da_notificare)
        self.assertEqual(AnomaliaPendingNotification.objects.get(op_id=OP).updates_snapshot, [{"id": self.a2}])
        dest = AnomaliaPendingNotification.objects.get(op_id=OP2)
        self.assertEqual([u["id"] for u in dest.updates_snapshot], [self.a1])
        self.assertIn(f"all'OP {OP2}", dest.updates_snapshot[0]["note"])
        self.assertEqual(AnomaliaSchedaQualita.objects.get(anomalia_id=self.a1).op_titolo, OP2)

    def test_stesso_s_n_rifiutato(self):
        r = self.post("api_anomalie_sposta", {"local_id": self.a1, "op_id": OP, "seriali": ["lcn00001"]})
        self.assertEqual(r.status_code, 400)

    def test_senza_s_n(self):
        self.assertEqual(self.post("api_anomalie_sposta", {"local_id": self.a1, "op_id": OP2, "seriali": []}).status_code, 400)

    def test_op_inesistente(self):
        with patch("anomalie.controllo_views._op_esiste", return_value=False):
            r = self.post("api_anomalie_sposta", {"local_id": self.a1, "op_id": "OP/0000/X", "seriali": ["A1"]})
        self.assertEqual(r.status_code, 404)

    def test_chi_gestisce_l_op_puo_tagliare(self):
        self.creatore = False
        self.edit_op = True
        r = self.post("api_anomalie_sposta", {"local_id": self.a1, "op_id": OP, "seriali": ["LCN00002"]})
        self.assertEqual(r.status_code, 200, r.content)

    def test_estraneo_non_taglia(self):
        self.creatore = False
        r = self.post("api_anomalie_sposta", {"local_id": self.a1, "op_id": OP, "seriali": ["LCN00002"]})
        self.assertEqual(r.status_code, 403)

    def test_con_decisione_non_si_taglia(self):
        self.set_riga(self.a1, note_capocommessa="Rilavorare")
        r = self.post("api_anomalie_sposta", {"local_id": self.a1, "op_id": OP, "seriali": ["LCN00002"]})
        self.assertEqual(r.status_code, 409)


class FlagElencoTests(_Base):
    def _flags(self, *, me=ME, edit=False):
        req = RequestFactory().get("/api/anomalie/anomalie")
        req.user = SimpleNamespace(is_authenticated=True)
        rows = [{"local_id": self.a1}, {"local_id": self.a2}, {"local_id": self.a3}]
        raw = {self.a1: {"avanzamento": "In attesa"}, self.a2: {"avanzamento": "Accetto lo stato"}, self.a3: {}}
        autori = {self.a1: ME, self.a2: ME, self.a3: 99}
        with patch.object(av, "_request_legacy_user_id", return_value=me), \
                patch.object(av, "_can_edit_anomalie_for_op", return_value=edit):
            av._segna_eliminabili(req, rows, raw, autori, OP)
        return {r["local_id"]: (r["can_elimina"], r["can_sposta"]) for r in rows}

    def test_autore(self):
        f = self._flags()
        self.assertEqual(f[self.a1], (True, True))
        self.assertEqual(f[self.a2], (False, False))  # già decisa
        self.assertEqual(f[self.a3], (False, False))  # di un altro

    def test_chi_gestisce_l_op_taglia_ma_non_elimina(self):
        f = self._flags(me=None, edit=True)
        self.assertEqual(f[self.a1], (False, True))
        self.assertEqual(f[self.a3], (False, True))

    def test_serializza_controllo_espone_autore_e_modificabile(self):
        from anomalie import controllo_service as cs

        self.set_riga(self.a2, avanzamento="Accetto lo stato")
        with patch.object(cs, "_allegati", return_value=[]):
            data = cs.serializza_controllo(self.controllo)
        anomalie = {a["local_id"]: a for b in data["blocchi"] for a in b["anomalie"]}
        self.assertEqual(anomalie[self.a1]["autore_id"], ME)
        self.assertTrue(anomalie[self.a1]["modificabile"])
        self.assertFalse(anomalie[self.a2]["modificabile"])


class CambiaOpControlloTests(_Api):
    def post_cambia(self, body):
        url = reverse("api_anomalie_controllo_cambia_op", args=[self.controllo.pk])
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def test_sposta_controllo_e_anomalie(self):
        self.controllo.da_notificare = [self.a1, self.a2]  # a3 già comunicata
        self.controllo.save()
        AnomaliaPendingNotification.objects.create(op_id=OP, last_modified_at="2026-11-05T10:00:00Z",
                                                   updates_snapshot=[{"id": self.a3}])
        r = self.post_cambia({"op_id": OP2, "op_item_id": "-9"})
        self.assertEqual(r.status_code, 200, r.content)
        self.controllo.refresh_from_db()
        self.assertEqual((self.controllo.op_id, self.controllo.op_item_id), (OP2, "-9"))
        for i in (self.a1, self.a2, self.a3):
            self.assertEqual(self.riga(i)["op"], OP2)
            self.assertEqual(AnomaliaSchedaQualita.objects.get(anomalia_id=i).op_titolo, OP2)
            self.assertTrue(AnomaliaActionLog.objects.filter(anomalia_id=i, action="spostata").exists())
        # Blocchi e collegamento al controllo restano.
        self.assertEqual(AnomaliaSegnalazioneMeta.objects.filter(controllo=self.controllo).count(), 3)
        self.assertTrue(AnomaliaPendingNotification.objects.get(op_id=OP).notified)
        dest = AnomaliaPendingNotification.objects.get(op_id=OP2)
        self.assertEqual([u["id"] for u in dest.updates_snapshot], [self.a3])

    def test_con_avanzamenti_non_si_sposta_niente(self):
        self.set_riga(self.a2, avanzamento="Accetto lo stato")
        r = self.post_cambia({"op_id": OP2})
        self.assertEqual(r.status_code, 409)
        self.assertIn(f"#{self.a2}", r.json()["error"])
        self.controllo.refresh_from_db()
        self.assertEqual(self.controllo.op_id, OP)
        self.assertEqual(self.riga(self.a1)["op"], OP)

    def test_stesso_op_e_terminato(self):
        self.assertEqual(self.post_cambia({"op_id": OP}).status_code, 400)
        self.controllo.terminato_at = "2026-11-05T11:00:00Z"
        self.controllo.save()
        self.assertEqual(self.post_cambia({"op_id": OP2}).status_code, 409)

    def test_controllo_vuoto(self):
        AnomaliaSegnalazioneMeta.objects.all().delete()
        r = self.post_cambia({"op_id": OP2})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["spostate"], 0)
