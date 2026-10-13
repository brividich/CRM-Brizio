"""MAC dichiarato del punto rete (AssetEndpoint.mac)."""
from django.test import TestCase, override_settings

from assets.forms import AssetForm
from assets.models import Asset, AssetEndpoint
from assets.services import storico_asset


class EndpointMacTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="CCTV-QA-1", name="Telecamera QA", asset_type=Asset.TYPE_CCTV)

    def test_salvataggio_normalizza(self):
        endpoint = AssetEndpoint.objects.create(asset=self.asset, ip="192.0.2.91", mac="00-18-9A-0B-0C-0D")
        endpoint.refresh_from_db()
        self.assertEqual(endpoint.mac, "00:18:9a:0b:0c:0d")

    def test_form_valida_e_mostra_rete_per_telecamere(self):
        form = AssetForm(instance=self.asset)
        self.assertTrue(form.show_it_network_fields)
        self.assertIn("network_mac", form.fields)
        form.cleaned_data = {"network_mac": "0018.9a0b.0c0d"}
        self.assertEqual(form.clean_network_mac(), "00:18:9a:0b:0c:0d")
        form.cleaned_data = {"network_mac": "non-un-mac"}
        with self.assertRaises(Exception):
            form.clean_network_mac()

    def test_mac_tracciato_nello_storico(self):
        self.assertIn("mac", storico_asset.CAMPI_ENDPOINT)
        self.assertIn("endpoint.mac", storico_asset.GRUPPI["rete"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, SITE_URL="")
class QrPubblicoSenzaDatiTvccTests(TestCase):
    def test_landing_pubblica_non_mostra_snmp_ne_mac(self):
        from django.urls import reverse

        from assets.services import asset_qr
        from contatori.models import DispositivoSNMP

        asset = Asset.objects.create(asset_tag="CCTV-QA-2", name="Telecamera ingresso", asset_type=Asset.TYPE_CCTV)
        AssetEndpoint.objects.create(asset=asset, ip="192.0.2.92", mac="00:18:9a:0b:0c:0e")
        DispositivoSNMP.objects.create(nome="Cam SNMP QA", host="192.0.2.93", asset=asset,
                                       categoria=DispositivoSNMP.Categoria.TVCC_TELECAMERA,
                                       sys_description="Linux synthetic-ipc")
        asset_qr.abilita_link_pubblico(asset)
        risposta = self.client.get(reverse("assets:asset_qr_public_landing",
                                           kwargs={"public_qr_token": asset.public_qr_token}))
        self.assertEqual(risposta.status_code, 200)
        for dato in ("192.0.2.93", "00:18:9a:0b:0c:0e", "Cam SNMP QA", "synthetic-ipc", "Monitoraggio"):
            self.assertNotContains(risposta, dato)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, SITE_URL="")
class SchedaMonitoraggioTvccTests(TestCase):
    def setUp(self):
        from contatori.models import DispositivoSNMP, RilevazioneSNMP, SondaSNMP, StatoSNMP, ValoreSNMP

        from .tests_asset_qr import _user

        self.admin = _user("tvcc.admin", superuser=True)
        self.asset = Asset.objects.create(asset_tag="CCTV-QA-3", name="Telecamera magazzino",
                                          asset_type=Asset.TYPE_CCTV)
        self.endpoint = AssetEndpoint.objects.create(asset=self.asset, ip="192.0.2.94", mac="00:18:9a:0b:0c:0f")
        dispositivo = DispositivoSNMP.objects.create(
            nome="Cam magazzino", host="192.0.2.94", asset=self.asset,
            categoria=DispositivoSNMP.Categoria.TVCC_TELECAMERA, snmp_stato=StatoSNMP.OK,
            sys_uptime_seconds=3 * 86400,
        )
        sonda = SondaSNMP.objects.create(dispositivo=dispositivo, nome="MAC", oid="1.3.6.1.2.1.2.2.1.6",
                                         tipo_valore="MAC", modalita="WALK", aggregazione="VALIDO")
        self.rilevazione = RilevazioneSNMP.objects.create(dispositivo=dispositivo, stato=StatoSNMP.OK)
        self.valore = ValoreSNMP.objects.create(rilevazione=self.rilevazione, sonda=sonda,
                                                valore_testo="00:18:9a:0b:0c:0f", stato=StatoSNMP.OK)

    def _pagina(self):
        from django.urls import reverse

        self.client.force_login(self.admin)
        return self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id}))

    def test_valori_e_mac_uguale(self):
        risposta = self._pagina()
        self.assertContains(risposta, "TVCC - Telecamera IP · Cam magazzino")
        self.assertContains(risposta, "acceso da circa 3 giorni")
        self.assertContains(risposta, "= dichiarato")

    def test_mac_diverso(self):
        self.valore.valore_testo = "00:18:9a:0b:0c:10"
        self.valore.save()
        self.assertContains(self._pagina(), "diverso dal dichiarato")

    def test_mac_non_dichiarato(self):
        self.endpoint.mac = ""
        self.endpoint.save()
        self.assertContains(self._pagina(), "non dichiarato")
