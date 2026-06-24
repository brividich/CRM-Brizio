"""Test delle viste (matrice Excel + edit cella HTMX + API Gantt)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset

from .models import Macchina, Pianificazione


class ViewsTest(TestCase):
    def setUp(self):
        # superuser: bypassa onboarding/ACL e isola il test alla logica della view
        # (il binding ACL canonico per i ruoli reali e' al PASSO 6).
        self.user = get_user_model().objects.create_superuser(
            username="op", password="x", email="op@example.com"
        )
        self.asset = Asset.objects.create(
            asset_tag="CNC-DM3-1", name="DM3 - DMG Mori", asset_type=Asset.TYPE_WORK_MACHINE
        )
        self.m = Macchina.objects.create(asset=self.asset, categoria=Macchina.CAT_5AXIS)
        self.url_excel = reverse("gestione_carichi_macchina:excel")
        self.url_cella = reverse("gestione_carichi_macchina:cella_edit")

    def test_login_required(self):
        self.assertEqual(self.client.get(self.url_excel).status_code, 302)

    def test_excel_page_mostra_macchina(self):
        self.client.force_login(self.user)
        r = self.client.get(self.url_excel)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "CNC-DM3-1")

    def test_cella_form_get(self):
        self.client.force_login(self.user)
        r = self.client.get(self.url_cella, {"macchina": self.m.id, "turno": "giorno", "data": "2026-06-23"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="testo"')

    def test_cella_salva_crea_manuale(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url_cella, {
            "macchina": self.m.id, "turno": "giorno", "data": "2026-06-23",
            "testo": "8 gimbal (33h)", "stato": "pianificata", "fase": "",
        })
        self.assertEqual(r.status_code, 200)
        p = Pianificazione.objects.get(macchina=self.m, data=date(2026, 6, 23))
        self.assertEqual(p.fonte, Pianificazione.FONTE_MANUALE)
        self.assertEqual(p.qta, 8)
        self.assertEqual(p.ore, 33)

    def test_cella_elimina(self):
        self.client.force_login(self.user)
        p = Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno="giorno",
            testo_originale="x", fonte=Pianificazione.FONTE_MANUALE,
        )
        r = self.client.post(self.url_cella, {
            "macchina": self.m.id, "turno": "giorno", "data": "2026-06-23",
            "pianificazione_id": p.id, "elimina": "1",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Pianificazione.objects.filter(pk=p.id).exists())

    def test_api_suggerimento_macchina(self):
        from .models import FamigliaPezzo, MacchinaFamigliaAffinita

        self.client.force_login(self.user)
        fam = FamigliaPezzo.objects.create(nome="gimbal")
        MacchinaFamigliaAffinita.objects.create(macchina=self.m, famiglia=fam, occorrenze=7)
        r = self.client.get(
            reverse("gestione_carichi_macchina:api_suggerimento_macchina"),
            {"famiglia": "gimbal"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["suggerimenti"][0]["macchina_id"], self.m.id)

    def test_cella_suggerimento_box(self):
        from .models import FamigliaPezzo, MacchinaFamigliaAffinita

        self.client.force_login(self.user)
        fam = FamigliaPezzo.objects.create(nome="gimbal")
        MacchinaFamigliaAffinita.objects.create(macchina=self.m, famiglia=fam, occorrenze=7)
        # Famiglia riconosciuta dal testo della cella -> box con macchina consigliata.
        r = self.client.get(
            reverse("gestione_carichi_macchina:cella_suggerimento"),
            {"testo": "8 gimbal (33h)", "macchina": self.m.id},
        )
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("gcm-sugg", body)
        self.assertIn(self.m.codice, body)  # codice macchina mostrato
        self.assertIn("●", body)            # evidenziata come macchina della cella
        # Testo senza famiglia riconoscibile -> frammento vuoto (nessun box).
        r2 = self.client.get(
            reverse("gestione_carichi_macchina:cella_suggerimento"),
            {"testo": "zzz ignoto", "macchina": self.m.id},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.content.decode().strip(), "")

    def test_excel_turni_flag_mostra_righe_turno(self):
        self.client.force_login(self.user)
        self.m.ha_secondo_turno = True
        self.m.ha_turno_notte = True
        self.m.save()
        # Default (collassato): nessuna sotto-riga per turno.
        r0 = self.client.get(self.url_excel).content.decode()
        self.assertNotIn("↳ 2° turno", r0)
        self.assertNotIn("↳ notturno", r0)
        # Con ?turni=1: sotto-righe 2° turno e notturno.
        r1 = self.client.get(self.url_excel, {"turni": "1"}).content.decode()
        self.assertIn("↳ 2° turno", r1)
        self.assertIn("↳ notturno", r1)

    @override_settings(OLLAMA_CHAT_ENABLED=False)
    def test_api_spiega_macchina_failsafe(self):
        from .models import FamigliaPezzo, MacchinaFamigliaAffinita

        self.client.force_login(self.user)
        fam = FamigliaPezzo.objects.create(nome="koala")
        MacchinaFamigliaAffinita.objects.create(macchina=self.m, famiglia=fam, occorrenze=3)
        r = self.client.get(
            reverse("gestione_carichi_macchina:api_spiega_macchina"), {"famiglia": "koala"}
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["suggerimenti"][0]["macchina_id"], self.m.id)
        self.assertIsNone(data["spiegazione"])  # AI off nei test -> fail-safe

    def test_carico_settimanale(self):
        from datetime import date as _d

        from .models import Pianificazione
        from .previsioni import carico_settimanale

        lun = _d(2026, 6, 22)
        # 40h su macchina 8h/gg, 5 gg lavorativi -> capacita' 40 -> 100%
        Pianificazione.objects.create(
            macchina=self.m, data=lun, turno="giorno", ore=40,
            testo_originale="x", fonte=Pianificazione.FONTE_IMPORT,
        )
        weeks = carico_settimanale(lun, 2)
        self.assertEqual(len(weeks), 2)
        self.assertGreater(weeks[0]["totale"]["perc"], 0)

    def test_api_pianificazioni(self):
        self.client.force_login(self.user)
        Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno="giorno",
            testo_originale="8 gimbal", fonte=Pianificazione.FONTE_IMPORT,
        )
        r = self.client.get(reverse("gestione_carichi_macchina:api_pianificazioni"),
                            {"start": "2026-06-22", "giorni": 7})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["items"]), 1)
