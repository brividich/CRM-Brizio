"""Testata asset comune ad Asset, Contatori e SOC: stessa identità, stessi riquadri, collegamenti incrociati. Dati sintetici."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from contatori.models import AvvisoStampante, Macchina
from core.models import UserOnboarding


class AssetTestataTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(username="testata_admin", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)
        self.asset = Asset.objects.create(asset_tag="IT-MFC-SYN1", name="MFC sintetica", serial_number="SYN1",
                                          asset_type=Asset.TYPE_OTHER)
        self.mfc = Macchina.objects.create(reparto="Ufficio sintetico", matricola="SYN1", host="192.0.2.91", asset=self.asset,
                                           dati_stampante={"contatori": [], "consumabili": [], "stato": {"stato": "pronta"}})
        AvvisoStampante.objects.create(macchina=self.mfc, chiave="k1", testo="Carta inceppata", critico=True,
                                       aperto_il=timezone.now(), ultimo_visto_il=timezone.now())

    def test_scheda_mfc_mostra_la_testata_con_link_alla_scheda_asset(self):
        page = self.client.get(reverse("contatori:macchina", args=[self.mfc.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'class="at-card"')
        self.assertContains(page, "IT-MFC-SYN1")
        self.assertContains(page, reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertNotContains(page, ">Stampante MFC <span")  # il modulo che la mostra non si linka da solo

    def test_scheda_asset_porta_alla_stampante_e_mostra_gli_avvisi(self):
        page = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Lo stesso apparato in")
        self.assertContains(page, reverse("contatori:macchina", args=[self.mfc.pk]))

    def test_riquadro_stato_stampante(self):
        from assets.services.asset_kpis import _printer_tiles

        tiles = {t["label"]: t for t in _printer_tiles(self.asset, timezone.now())}
        self.assertEqual(tiles["Stato stampante"]["value"], "1 avviso")
        self.assertEqual(tiles["Stato stampante"]["level"], "bad")
