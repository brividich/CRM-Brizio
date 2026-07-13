"""Test Gantt: saturazione (pura), pagina e drag-to-reschedule."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_piano_slittamento_spinge_solo_conflitto_minimo(self):
        from datetime import date
        from .views import _piano_slittamento
        d = date(2026, 6, 22)  # lunedì
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
        c = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=4), turno="giorno", testo_originale="C", fonte=Pianificazione.FONTE_IMPORT)
        piano = _piano_slittamento(self.m, p0, d + timedelta(days=1), coda=False)
        ids = [r["id"] for r in piano]
        self.assertEqual(ids[0], p0.id)
        self.assertIn(b.id, ids)
        self.assertNotIn(c.id, ids)
        riga_b = next(r for r in piano if r["id"] == b.id)
        self.assertEqual(riga_b["a"], d + timedelta(days=2))

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

    def test_piano_slittamento_conflitti_multipli_impilati_senza_overlap(self):
        """Due lavori già sullo STESSO slot: trascinandone sopra un terzo, i conflitti
        vengono impilati in giorni distinti, non ammucchiati sulla stessa data."""
        from datetime import date

        from .views import _piano_slittamento, _sovrapposizioni
        d = date(2026, 6, 22)  # lunedì
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        # B e C già entrambi sul giorno 23 (slot condiviso pre-esistente)
        b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
        c = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="C", fonte=Pianificazione.FONTE_IMPORT)
        piano = _piano_slittamento(self.m, p0, d + timedelta(days=1), coda=False)
        a_di = {r["id"]: r["a"] for r in piano}
        self.assertIn(b.id, a_di)
        self.assertIn(c.id, a_di)
        # B e C finiscono su giorni DISTINTI (impilati), non sulla stessa data
        self.assertNotEqual(a_di[b.id], a_di[c.id])

    def test_reschedule_coda_sposta_i_successivi(self):
        self.client.force_login(self.user)
        d0 = date(2026, 6, 22)  # lunedì
        p0 = Pianificazione.objects.create(macchina=self.m, data=d0, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        p1 = Pianificazione.objects.create(macchina=self.m, data=d0 + timedelta(days=2), turno="giorno", testo_originale="b", fonte=Pianificazione.FONTE_IMPORT)  # mercoledì
        p2 = Pianificazione.objects.create(macchina=self.m, data=d0 + timedelta(days=4), turno="giorno", testo_originale="c", fonte=Pianificazione.FONTE_IMPORT)  # venerdì
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                             {"pianificazione_id": p0.id, "giorni_delta": "3", "coda": "1", "conferma_slittamento": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["spostati"], 3)
        p0.refresh_from_db(); p1.refresh_from_db(); p2.refresh_from_db()
        # +3 giorni LAVORATIVI (non calendario): p0 lun->gio non attraversa il weekend,
        # ma p1 (mer) e p2 (ven) sì, quindi il loro spostamento non è un timedelta secco.
        self.assertEqual(p0.data, d0 + timedelta(days=3))  # giovedì
        self.assertEqual(p1.data, date(2026, 6, 29))  # lunedì (non sabato 27)
        self.assertEqual(p2.data, date(2026, 7, 1))  # mercoledì
        self.assertLess(p1.data.weekday(), 5)
        self.assertLess(p2.data.weekday(), 5)

    def test_reschedule_senza_coda_non_tocca_i_non_conflitti(self):
        self.client.force_login(self.user)
        d0 = date(2026, 6, 22)
        p0 = Pianificazione.objects.create(macchina=self.m, data=d0, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        p1 = Pianificazione.objects.create(macchina=self.m, data=d0 + timedelta(days=2), turno="giorno", testo_originale="b", fonte=Pianificazione.FONTE_IMPORT)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                             {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0"})
        self.assertEqual(r.json()["spostati"], 1)
        p1.refresh_from_db()
        self.assertEqual(p1.data, d0 + timedelta(days=2))  # invariato

    def test_reschedule_undo_ripristina(self):
        self.client.force_login(self.user)
        d0 = date(2026, 6, 23)
        p = Pianificazione.objects.create(macchina=self.m, data=d0, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                        {"pianificazione_id": p.id, "giorni_delta": "3", "coda": "0"})
        p.refresh_from_db()
        self.assertEqual(p.data, d0 + timedelta(days=3))
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule_undo"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        p.refresh_from_db()
        self.assertEqual(p.data, d0)  # ripristinato

    def test_reschedule_undo_salta_job_modificato_nel_frattempo(self):
        """L'undo non deve sovrascrivere alla cieca: se un job coinvolto nello snapshot
        viene modificato di nuovo DOPO il nostro spostamento (altra tab/utente) e PRIMA
        del click su Annulla, quel job va saltato, non riportato allo stato pre-mossa."""
        self.client.force_login(self.user)
        d0 = date(2026, 6, 23)
        p = Pianificazione.objects.create(macchina=self.m, data=d0, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                        {"pianificazione_id": p.id, "giorni_delta": "3", "coda": "0"})
        p.refresh_from_db()
        self.assertEqual(p.data, d0 + timedelta(days=3))
        p.data = d0 + timedelta(days=9)
        p.save(update_fields=["data", "updated_at"])  # modifica concorrente successiva
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule_undo"))
        j = r.json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["annullati"], 0)
        self.assertEqual(j["saltati"], 1)
        p.refresh_from_db()
        self.assertEqual(p.data, d0 + timedelta(days=9))  # non sovrascritto alla cieca

    def test_undo_ripristina_tutti_gli_slittati(self):
        self.client.force_login(self.user)
        d = date(2026, 6, 22)
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
        self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                         {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0", "conferma_slittamento": "1"})
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule_undo"))
        self.assertTrue(r.json()["ok"])
        p0.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(p0.data, d)
        self.assertEqual(b.data, d + timedelta(days=1))

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

    def test_cambio_macchina_turno_incompatibile_richiede_forza(self):
        self.client.force_login(self.user)
        # m2 stessa categoria ma SENZA turno notte: destinazione fisicamente incompatibile
        # con un lavoro notturno.
        m2 = self._altra_macchina("CNC-DM7-1", Macchina.CAT_5AXIS)
        p = Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno=Pianificazione.TURNO_NOTTE,
            testo_originale="a", fonte=Pianificazione.FONTE_IMPORT,
        )
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                            {"pianificazione_id": p.id, "giorni_delta": "0", "macchina_dest": m2.id})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertEqual(r.json()["reason"], "turno_incompatibile")
        p.refresh_from_db()
        self.assertEqual(p.macchina_id, self.m.id)  # non spostato
        r2 = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                             {"pianificazione_id": p.id, "giorni_delta": "0", "macchina_dest": m2.id, "forza": "1"})
        self.assertTrue(r2.json()["ok"])
        p.refresh_from_db()
        self.assertEqual(p.macchina_id, m2.id)

    def test_forza_macchina_non_salta_la_preview_slittamento(self):
        """`forza=1` deve bypassare SOLO l'incompatibilità di categoria macchina: se la
        destinazione forzata genera anche un conflitto reale, l'operatore deve comunque
        vedere la preview di slittamento e confermarla separatamente (conferma_slittamento)."""
        self.client.force_login(self.user)
        mt = self._altra_macchina("MNO-TORNI-8", Macchina.CAT_TORNI)  # categoria diversa
        d = date(2026, 6, 23)
        Pianificazione.objects.create(macchina=mt, data=d, turno="giorno", testo_originale="X", fonte=Pianificazione.FONTE_IMPORT)
        p = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="a", fonte=Pianificazione.FONTE_IMPORT)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                            {"pianificazione_id": p.id, "giorni_delta": "0", "macchina_dest": mt.id, "forza": "1"})
        j = r.json()
        self.assertFalse(j["ok"])
        self.assertEqual(j["reason"], "slittamento")  # non "incompatibile": la categoria è già forzata
        p.refresh_from_db()
        self.assertEqual(p.macchina_id, self.m.id)  # non ancora applicato
        r2 = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                             {"pianificazione_id": p.id, "giorni_delta": "0", "macchina_dest": mt.id,
                              "forza": "1", "conferma_slittamento": "1"})
        self.assertTrue(r2.json()["ok"])
        p.refresh_from_db()
        self.assertEqual(p.macchina_id, mt.id)

    def test_reschedule_versione_scaduta_rifiutata(self):
        """TOCTOU: se tra la preview e la conferma un'altra richiesta modifica lo stato
        del piano (es. un altro utente sposta uno dei job coinvolti), la conferma con
        la versione ORMAI STALE va rifiutata, non applicata alla cieca."""
        self.client.force_login(self.user)
        d = date(2026, 6, 22)
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        # due lavori STESSO giorno (d+1): entrambi confliggono col drag di p0, così anche
        # dopo la modifica concorrente su b1 resta un conflitto reale (b2) da mostrare.
        b1 = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B1", fonte=Pianificazione.FONTE_IMPORT)
        b2 = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B2", fonte=Pianificazione.FONTE_IMPORT)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                             {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0"})
        j = r.json()
        self.assertEqual(j["reason"], "slittamento")
        versione_stale = j["versione"]
        self.assertTrue(versione_stale)

        b1.data = d + timedelta(days=10)
        b1.save(update_fields=["data", "updated_at"])  # modifica concorrente (altro utente/tab)

        r2 = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                              {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0",
                               "conferma_slittamento": "1", "versione": versione_stale})
        j2 = r2.json()
        self.assertFalse(j2["ok"])
        self.assertEqual(j2["reason"], "stato_cambiato")
        p0.refresh_from_db(); b2.refresh_from_db()
        self.assertEqual(p0.data, d)  # non applicato
        self.assertEqual(b2.data, d + timedelta(days=1))

        # Una NUOVA preview riflette lo stato corrente (b2 conflitta ancora) e con la
        # sua versione aggiornata si conferma regolarmente.
        r3 = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                              {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0"})
        j3 = r3.json()
        self.assertEqual(j3["reason"], "slittamento")
        self.assertNotEqual(j3["versione"], versione_stale)
        r4 = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                              {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0",
                               "conferma_slittamento": "1", "versione": j3["versione"]})
        self.assertTrue(r4.json()["ok"])

    def test_reschedule_delta_zero_400(self):
        self.client.force_login(self.user)
        p = Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno="giorno", testo_originale="x"
        )
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                            {"pianificazione_id": p.id, "giorni_delta": "0"})
        self.assertEqual(r.status_code, 400)

    def test_piano_slittamento_niente_catena(self):
        """Si spostano SOLO i lavori in conflitto col lavoro trascinato. Se lo slittato
        va a sovrapporsi a un terzo lavoro, quel terzo NON viene trascinato a sua volta:
        il Gantt lo segnalerà come conflitto (⚠), ma la pianificazione non viene
        bulldozzata a catena."""
        from datetime import date
        from .views import _piano_slittamento
        d = date(2026, 6, 22)  # lunedì
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
        c = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=2), turno="giorno", testo_originale="C", fonte=Pianificazione.FONTE_IMPORT)
        far = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=10), turno="giorno", testo_originale="Z", fonte=Pianificazione.FONTE_IMPORT)
        piano = _piano_slittamento(self.m, p0, d + timedelta(days=1), coda=False)
        ids = [r["id"] for r in piano]
        self.assertEqual(ids, [p0.id, b.id])  # B slitta (conflitto diretto); C e Z restano
        self.assertNotIn(c.id, ids)
        self.assertNotIn(far.id, ids)

    def test_piano_slittamento_ignora_conflitto_preesistente(self):
        """Caso reale (CNC-DM5): un lavoro da 129h occupa 17 giorni lavorativi; il lavoro
        trascinato ci era GIÀ dentro prima del drag. Spostarlo in avanti non crea né
        peggiora quel conflitto → il lavoro lungo NON va toccato e non c'è nulla da
        confermare."""
        from datetime import date
        from decimal import Decimal
        from .views import _piano_slittamento
        d = date(2026, 6, 22)  # lunedì
        lungo = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", ore=Decimal("129"), testo_originale="18 gimbal 4G 129h", fonte=Pianificazione.FONTE_IMPORT)
        drag = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", ore=Decimal("84"), testo_originale="SGR gimbal 84h", fonte=Pianificazione.FONTE_IMPORT)
        piano = _piano_slittamento(self.m, drag, d + timedelta(days=8), coda=False)
        self.assertEqual([r["id"] for r in piano], [drag.id])
        self.assertNotIn(lungo.id, [r["id"] for r in piano])

    def test_piano_slittamento_salta_weekend(self):
        from datetime import date
        from .views import _piano_slittamento
        gio = date(2026, 6, 25)
        ven = date(2026, 6, 26)
        p0 = Pianificazione.objects.create(macchina=self.m, data=gio, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        b = Pianificazione.objects.create(macchina=self.m, data=ven, turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
        piano = _piano_slittamento(self.m, p0, ven, coda=False)
        riga_b = next(r for r in piano if r["id"] == b.id)
        self.assertEqual(riga_b["a"], date(2026, 6, 29))  # lunedì, non sabato 27
        self.assertLess(riga_b["a"].weekday(), 5)

    def test_piano_slittamento_coda_sposta_tutta_la_coda(self):
        from datetime import date
        from .views import _piano_slittamento
        d = date(2026, 6, 22)  # lunedì
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)  # martedì
        c = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=2), turno="giorno", testo_originale="C", fonte=Pianificazione.FONTE_IMPORT)  # mercoledì
        piano = _piano_slittamento(self.m, p0, d + timedelta(days=3), coda=True)  # +3 giorni lavorativi (lun->gio, nessun weekend attraversato)
        ids = [r["id"] for r in piano]
        self.assertEqual(set(ids), {p0.id, b.id, c.id})
        riga_b = next(r for r in piano if r["id"] == b.id)
        riga_c = next(r for r in piano if r["id"] == c.id)
        self.assertEqual(riga_b["a"], b.data + timedelta(days=3))  # martedì->venerdì, nessun weekend: coincide col calendario
        self.assertEqual(riga_c["a"], date(2026, 6, 29))  # mercoledì +3gg lav = lunedì (non sabato 27)

    def test_piano_slittamento_coda_non_atterra_nel_weekend(self):
        """Il delta della coda va applicato in giorni LAVORATIVI: se il raw calendar-delta
        (venerdì->lunedì = 3 giorni di calendario, ma 1 solo giorno lavorativo) venisse
        sommato secco a un successivo, potrebbe farlo atterrare di sabato."""
        from .views import _piano_slittamento
        p0 = Pianificazione.objects.create(macchina=self.m, data=date(2026, 6, 26), turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)  # venerdì
        b = Pianificazione.objects.create(macchina=self.m, data=date(2026, 7, 1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)  # mercoledì
        piano = _piano_slittamento(self.m, p0, date(2026, 6, 29), coda=True)  # lunedì: +1 giorno lavorativo
        riga_b = next(r for r in piano if r["id"] == b.id)
        self.assertEqual(riga_b["a"], date(2026, 7, 2))  # giovedì (+1 giorno lavorativo), non sabato
        self.assertLess(riga_b["a"].weekday(), 5)

    def test_piano_slittamento_coda_include_fasce_intersecanti(self):
        """La coda deve includere anche i successivi con turno DIVERSO ma fascia oraria
        intersecante (es. 'entrambi' G+T tocca sia 'giorno' G che 't2' T), non solo il
        match esatto del turno del lavoro trascinato."""
        from .views import _piano_slittamento
        d = date(2026, 6, 22)  # lunedì
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno=Pianificazione.TURNO_ENTRAMBI, testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        o = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno=Pianificazione.TURNO_T2, testo_originale="O", fonte=Pianificazione.FONTE_IMPORT)
        piano = _piano_slittamento(self.m, p0, d + timedelta(days=2), coda=True)
        ids = [r["id"] for r in piano]
        self.assertIn(o.id, ids)

    def test_piano_slittamento_riga_normale_non_e_irrisolta(self):
        from .views import _piano_slittamento
        d = date(2026, 6, 22)  # lunedì
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
        piano = _piano_slittamento(self.m, p0, d + timedelta(days=1), coda=False)
        riga_b = next(r for r in piano if r["id"] == b.id)
        self.assertFalse(riga_b["irrisolto"])
        self.assertFalse(piano[0]["irrisolto"])

    def test_reschedule_preview_segnala_conflitto_irrisolto(self):
        """La view deve propagare il flag `irrisolto` calcolato da `_piano_slittamento`
        nella preview JSON e, in fase di apply, non scrivere righe irrisolte (nessun
        movimento reale) pur riportandone il conteggio."""
        self.client.force_login(self.user)
        d = date(2026, 6, 22)  # lunedì
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
        finto_piano = [
            {"id": p0.id, "etichetta": "A", "macchina": self.m.codice, "da": d, "a": d + timedelta(days=1), "irrisolto": False},
            {"id": b.id, "etichetta": "B", "macchina": self.m.codice, "da": b.data, "a": b.data, "irrisolto": True},
        ]
        with patch("gestione_carichi_macchina.views._piano_slittamento", return_value=finto_piano):
            r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                                 {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0"})
            j = r.json()
            self.assertFalse(j["ok"])
            self.assertEqual(j["reason"], "slittamento")
            riga_b = next(row for row in j["piano"] if row["etichetta"] == "B")
            self.assertTrue(riga_b["irrisolto"])

            r2 = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                                  {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0",
                                   "conferma_slittamento": "1"})
        j2 = r2.json()
        self.assertTrue(j2["ok"])
        self.assertEqual(j2["irrisolti"], 1)
        b.refresh_from_db()
        self.assertEqual(b.data, d + timedelta(days=1))  # non toccato: era irrisolto (a == da)

    def test_reschedule_conflitto_richiede_conferma_poi_applica(self):
        self.client.force_login(self.user)
        d = date(2026, 6, 22)  # lunedì
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        b = Pianificazione.objects.create(macchina=self.m, data=d + timedelta(days=1), turno="giorno", testo_originale="B", fonte=Pianificazione.FONTE_IMPORT)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                             {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0"})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertFalse(j["ok"])
        self.assertEqual(j["reason"], "slittamento")
        self.assertGreaterEqual(len(j["piano"]), 2)
        p0.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(p0.data, d)
        self.assertEqual(b.data, d + timedelta(days=1))
        r2 = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                              {"pianificazione_id": p0.id, "giorni_delta": "1", "coda": "0", "conferma_slittamento": "1"})
        self.assertTrue(r2.json()["ok"])
        p0.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(p0.data, d + timedelta(days=1))
        self.assertEqual(b.data, d + timedelta(days=2))

    def test_reschedule_senza_conflitto_applica_diretto(self):
        self.client.force_login(self.user)
        d = date(2026, 6, 22)
        p0 = Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", testo_originale="A", fonte=Pianificazione.FONTE_IMPORT)
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"),
                             {"pianificazione_id": p0.id, "giorni_delta": "3", "coda": "0"})
        self.assertTrue(r.json()["ok"])
        p0.refresh_from_db()
        self.assertEqual(p0.data, d + timedelta(days=3))
