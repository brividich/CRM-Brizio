"""Test Gantt: saturazione (pura), pagina e drag-to-reschedule."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from assets.models import Asset

from .models import Macchina, Pianificazione
from .saturazione import calcola_saturazione, working_days


class SaturazioneTest(SimpleTestCase):
    def setUp(self):
        # 7 giorni consecutivi = sempre 5 lavorativi + 2 weekend
        self.giorni = [date(2026, 6, 22) + timedelta(days=i) for i in range(7)]
        self.wd = working_days(self.giorni)

    def test_capacita_e_percentuale(self):
        m = SimpleNamespace(id=1, categoria="5_axis", ha_turno_notte=False,
                            ore_giorno_disponibili=Decimal("8"))
        pians = [SimpleNamespace(macchina_id=1, ore=Decimal("20"))]
        res = calcola_saturazione([m], pians, self.giorni)
        self.assertEqual(res["per_macchina"][1]["capacita"], float(8 * self.wd))
        self.assertEqual(res["per_macchina"][1]["perc"], round(100 * 20 / (8 * self.wd), 1))
        self.assertEqual(res["per_reparto"]["5_axis"]["carico"], 20.0)

    def test_turno_notte_raddoppia_capacita(self):
        m = SimpleNamespace(id=1, categoria="5_axis", ha_turno_notte=True,
                            ore_giorno_disponibili=Decimal("8"))
        res = calcola_saturazione([m], [SimpleNamespace(macchina_id=1, ore=Decimal("10"))], self.giorni)
        self.assertEqual(res["per_macchina"][1]["capacita"], float(8 * self.wd * 2))


class GanttViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("op", "op@example.com", "x")
        self.asset = Asset.objects.create(
            asset_tag="CNC-DM3-1", name="DM3 - DMG Mori", asset_type=Asset.TYPE_WORK_MACHINE
        )
        self.m = Macchina.objects.create(asset=self.asset, categoria=Macchina.CAT_5AXIS)

    def test_gantt_page(self):
        self.client.force_login(self.user)
        Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno="giorno",
            ore=Decimal("16"), testo_originale="8 gimbal (16h)", fonte=Pianificazione.FONTE_IMPORT,
        )
        r = self.client.get(reverse("gestione_carichi_macchina:gantt"),
                            {"start": "2026-06-22", "giorni": 7})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "CNC-DM3-1")

    def test_reschedule_sposta_data(self):
        self.client.force_login(self.user)
        p = Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno="giorno",
            testo_originale="x", fonte=Pianificazione.FONTE_IMPORT,
        )
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                            {"pianificazione_id": p.id, "giorni_delta": "3"})
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.data, date(2026, 6, 26))
        self.assertEqual(p.fonte, Pianificazione.FONTE_MANUALE)

    def test_filtro_categoria_nasconde_altre_sezioni(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("gestione_carichi_macchina:gantt"),
                            {"start": "2026-06-22", "giorni": 7, "cat": "torni"})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "CNC-DM3-1")  # macchina 5_axis esclusa dal filtro

    def test_zoom_cw_param(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("gestione_carichi_macchina:gantt"),
                            {"start": "2026-06-22", "giorni": 7, "cw": "52"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "--cw:52px")

    def test_reschedule_cascata_sposta_i_successivi(self):
        self.client.force_login(self.user)
        d0 = date(2026, 6, 23)
        p0 = Pianificazione.objects.create(macchina=self.m, data=d0, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        p1 = Pianificazione.objects.create(macchina=self.m, data=d0 + timedelta(days=2), turno="giorno", testo_originale="b", fonte=Pianificazione.FONTE_IMPORT)
        p2 = Pianificazione.objects.create(macchina=self.m, data=d0 + timedelta(days=4), turno="giorno", testo_originale="c", fonte=Pianificazione.FONTE_IMPORT)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                            {"pianificazione_id": p0.id, "giorni_delta": "3", "cascata": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["spostati"], 3)
        p0.refresh_from_db(); p1.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual(p0.data, d0 + timedelta(days=3))
        self.assertEqual(p1.data, d0 + timedelta(days=5))
        self.assertEqual(p2.data, d0 + timedelta(days=7))

    def test_reschedule_senza_cascata_sposta_solo_uno(self):
        self.client.force_login(self.user)
        d0 = date(2026, 6, 23)
        p0 = Pianificazione.objects.create(macchina=self.m, data=d0, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        p1 = Pianificazione.objects.create(macchina=self.m, data=d0 + timedelta(days=2), turno="giorno", testo_originale="b", fonte=Pianificazione.FONTE_IMPORT)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                            {"pianificazione_id": p0.id, "giorni_delta": "3", "cascata": "0"})
        self.assertEqual(r.json()["spostati"], 1)
        p1.refresh_from_db()
        self.assertEqual(p1.data, d0 + timedelta(days=2))  # invariato

    def test_reschedule_undo_ripristina(self):
        self.client.force_login(self.user)
        d0 = date(2026, 6, 23)
        p = Pianificazione.objects.create(macchina=self.m, data=d0, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                        {"pianificazione_id": p.id, "giorni_delta": "3", "cascata": "0"})
        p.refresh_from_db()
        self.assertEqual(p.data, d0 + timedelta(days=3))
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule_undo"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        p.refresh_from_db()
        self.assertEqual(p.data, d0)  # ripristinato

    def _altra_macchina(self, tag, categoria):
        a = Asset.objects.create(asset_tag=tag, name=tag, asset_type=Asset.TYPE_WORK_MACHINE)
        return Macchina.objects.create(asset=a, categoria=categoria)

    def test_cambio_macchina_compatibile(self):
        self.client.force_login(self.user)
        m2 = self._altra_macchina("CNC-DM6-1", Macchina.CAT_5AXIS)  # stessa categoria
        p = Pianificazione.objects.create(macchina=self.m, data=date(2026, 6, 23), turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                            {"pianificazione_id": p.id, "giorni_delta": "0", "macchina_dest": m2.id})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertTrue(r.json()["macchina"])
        p.refresh_from_db()
        self.assertEqual(p.macchina_id, m2.id)

    def test_cambio_macchina_incompatibile_richiede_forza(self):
        self.client.force_login(self.user)
        mt = self._altra_macchina("MNO-TORNI-9", Macchina.CAT_TORNI)  # categoria diversa
        p = Pianificazione.objects.create(macchina=self.m, data=date(2026, 6, 23), turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                            {"pianificazione_id": p.id, "giorni_delta": "0", "macchina_dest": mt.id})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertEqual(r.json()["reason"], "incompatibile")
        p.refresh_from_db()
        self.assertEqual(p.macchina_id, self.m.id)  # non spostato
        r2 = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                             {"pianificazione_id": p.id, "giorni_delta": "0", "macchina_dest": mt.id, "forza": "1"})
        self.assertTrue(r2.json()["ok"])
        p.refresh_from_db()
        self.assertEqual(p.macchina_id, mt.id)

    def test_reschedule_delta_zero_400(self):
        self.client.force_login(self.user)
        p = Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno="giorno", testo_originale="x"
        )
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                            {"pianificazione_id": p.id, "giorni_delta": "0"})
        self.assertEqual(r.status_code, 400)
