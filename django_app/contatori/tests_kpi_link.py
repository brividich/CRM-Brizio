"""Tessere della riconciliazione cliccabili: ogni numero apre la vista del confronto con lo stesso insieme."""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from . import services
from .models import Fattura, LetturaContatori, Macchina, RigaFattura
from .tests import _AuthedClientMixin


class RiconciliazioneKpiLinkTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        a = Macchina.objects.create(reparto="Uff A", matricola="SYN-KA", contratto="C-OK")
        b = Macchina.objects.create(reparto="Uff B", matricola="SYN-KB", contratto="C-KO")
        Macchina.objects.create(reparto="Uff C", matricola="SYN-KC", contratto="C-MANCA")
        f = Fattura.objects.create(numero="F-K", data=date(2026, 7, 1), trimestre="2026-Q2",
                                   periodo_al=date(2026, 6, 30))
        RigaFattura.objects.create(fattura=f, contratto="C-OK", a4_bn=10)
        RigaFattura.objects.create(fattura=f, contratto="C-KO", a4_bn=500)
        RigaFattura.objects.create(fattura=f, contratto="C-MANCA", a4_bn=10)
        LetturaContatori.objects.create(macchina=a, trimestre="2026-Q2", data=date(2026, 7, 3), a4_bn=20)
        LetturaContatori.objects.create(macchina=b, trimestre="2026-Q2", data=date(2026, 7, 3), a4_bn=100)
        self.url = reverse("contatori:riconciliazione_trim", args=["2026-Q2"])

    def test_tessere_portano_alle_viste_con_lo_stesso_numero(self):
        _righe, riepilogo = services.riconcilia("2026-Q2")
        html = self.client.get(self.url).content.decode()
        attese = {
            "": riepilogo["contratti"],
            "allineati": riepilogo["contratti_ok"],
            "da-controllare": riepilogo["contratti_danger"],
            "letture-mancanti": None,
        }
        for vista, numero in attese.items():
            href = f"{self.url}{'?vista=' + vista if vista else ''}#confronto"
            self.assertIn(f'href="{href}"', html, vista)
            r = self.client.get(self.url, {"vista": vista} if vista else {})
            if numero is not None:
                self.assertEqual(len(r.context["gruppi"]), numero, vista)
        # Letture mancanti: la vista mostra i contratti con MFC senza lettura, cioè quelle contate.
        r = self.client.get(self.url, {"vista": "letture-mancanti"})
        mfc = {m.pk for gr in r.context["gruppi"] for m in gr["mancanti"]}
        self.assertEqual(len(mfc), riepilogo["letture_mancanti"])
        self.assertEqual(riepilogo["contratti_ok"], 1)
        self.assertEqual(riepilogo["contratti_danger"], 1)
        self.assertEqual(riepilogo["letture_mancanti"], 1)

    def test_vista_sconosciuta_mostra_tutto(self):
        r = self.client.get(self.url, {"vista": "boh"})
        self.assertEqual(r.context["vista"], "")
        self.assertEqual(len(r.context["gruppi"]), 3)


class LicenzeApparatiKpiLinkTests(_AuthedClientMixin, TestCase):
    """«Licenze degli apparati»: la tessera apre l'elenco licenze con ``?apparati=1``,
    cioè le sole licenze degli asset collegati ad apparati attivi (lo stesso numero)."""

    def setUp(self):
        super().setUp()
        from datetime import timedelta

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from assets.models import Asset, SoftwareLicense
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(
            user=get_user_model().objects.get(username="contatori_test_admin"),
            defaults={"completed": True, "skipped": False, "completed_at": timezone.now()},
        )
        oggi = timezone.localdate()
        attivo = Asset.objects.create(asset_tag="K7-MFC1", name="MFC attiva")
        spento = Asset.objects.create(asset_tag="K7-MFC2", name="MFC dismessa")
        altro = Asset.objects.create(asset_tag="K7-PC", name="PC senza apparato")
        Macchina.objects.create(reparto="Uff L1", matricola="SYN-L1", asset=attivo)
        Macchina.objects.create(reparto="Uff L2", matricola="SYN-L2", asset=spento, attiva=False)
        for nome, asset, giorni in (("Scaduta apparato", attivo, -3), ("In scadenza apparato", attivo, 10),
                                    ("Lontana apparato", attivo, 300), ("Scaduta dismessa", spento, -3),
                                    ("Scaduta altrove", altro, -3), ("In scadenza altrove", altro, 5)):
            SoftwareLicense.objects.create(product_name=nome, asset=asset, expiry_date=oggi + timedelta(days=giorni))

    def _licenze(self, query):
        r = self.client.get(reverse("assets:software_license_list") + query)
        self.assertEqual(r.status_code, 200)
        return r

    def test_tessera_e_elenco_licenze_contano_uguale(self):
        kpi = services.licenze_asset_apparati()
        self.assertEqual(kpi, {"scadute": 1, "in_scadenza": 1})
        self.assertEqual(self._licenze("?status=expired&apparati=1").context["license_total"], kpi["scadute"])
        self.assertEqual(self._licenze("?status=expiring&apparati=1").context["license_total"], kpi["in_scadenza"])
        # Senza il filtro l'elenco conta anche le licenze degli altri asset: era lo scarto di prima.
        self.assertEqual(self._licenze("?status=expired").context["license_total"], 3)
        r = self._licenze("?status=expired&apparati=1")
        self.assertEqual(r.context["expiring_count"], kpi["in_scadenza"])
        self.assertIn("apparati=1", r.context["license_kpi_links"]["expiring"])
        self.assertContains(r, "data-filtro-apparati")

    def test_tessera_del_cruscotto_porta_al_filtro(self):
        r = self.client.get(reverse("contatori:dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("assets:software_license_list") + "?status=expired&amp;apparati=1")
