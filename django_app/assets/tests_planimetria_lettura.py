"""«Leggi planimetria»: sigle lette dal PDF/OCR → proposte di posizione degli asset."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset, AssetTimelineEntry, PlantLayout, PlantLayoutMarker
from assets.services import planimetria_lettura as lettura
from assets.tests import _complete_onboarding
from assets.tests_plant_layout_image import _MediaMixin, _png


def _pdf(scritte, w=400, h=200) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    for x, y, testo in scritte:
        page.insert_text((x, y), testo, fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


class LetturaServizioTests(_MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.layout = PlantLayout.objects.create(category="Officina", name="Pianta", image=_png(400, 200), is_active=True)
        self.dm7 = Asset.objects.create(asset_tag="WM-DM7", name="Centro DM7", internal_number="233",
                                        asset_type=Asset.TYPE_WORK_MACHINE)
        self.mz3 = Asset.objects.create(asset_tag="WM-MZ3", name="Fresa MZ3", internal_number="33",
                                        serial_number="SN-99812", asset_type=Asset.TYPE_WORK_MACHINE)
        self.pc = Asset.objects.create(asset_tag="PC-777", name="PC", internal_number="777", asset_type="PC")
        self.dup_a = Asset.objects.create(asset_tag="A-1", name="Uno", internal_number="550", asset_type=Asset.TYPE_OTHER)
        self.dup_b = Asset.objects.create(asset_tag="B-1", name="Due", serial_number="550", asset_type=Asset.TYPE_OTHER)

    def test_normalizza_prefissi_e_trattini(self):
        self.assertEqual(lettura.normalizza("-233-"), "233")
        self.assertEqual(lettura.normalizza("N. INT 045"), "45")
        self.assertEqual(lettura.normalizza("Int.033"), "33")
        self.assertEqual(lettura.normalizza("sn-99812"), "SN99812")
        self.assertEqual(lettura.normalizza("DMI2"), "DM12")
        self.assertEqual(lettura.normalizza("ALC"), "ALC")  # senza cifre niente sostituzioni

    def test_pdf_proposte_da_numero_interno_e_matricola(self):
        parole, _ = lettura.parole_da_pdf(_pdf([(100, 50, "DM7 -233-"), (300, 150, "SN 99812"),
                                                (200, 100, "777"), (50, 180, "550"), (20, 20, "CN5G")]))
        risultato = lettura.abbina(self.layout, parole, fonte_testo="test")
        per_id = {p.asset_id: p for p in risultato.proposte}
        self.assertEqual(set(per_id), {self.dm7.pk, self.mz3.pk})  # niente IT, niente sigle ambigue
        self.assertEqual(per_id[self.dm7.pk].fonte, lettura.FONTE_NUMERO_INTERNO)
        self.assertEqual(per_id[self.mz3.pk].fonte, lettura.FONTE_MATRICOLA)
        self.assertAlmostEqual(per_id[self.mz3.pk].x, 78, delta=4)
        self.assertTrue(per_id[self.dm7.pk].preselezionata)
        self.assertIn("550", risultato.non_riconosciute)

    def test_dati_come_in_produzione_int_sigla_nel_nome_e_ocr(self):
        from anagrafica.models import Reparto

        Reparto.objects.create(nome="CN5")
        dm12 = Asset.objects.create(asset_tag="CNC-DM12-1267", name="DM12-DMGMoriDMC160U", internal_number="Int.250",
                                    asset_type=Asset.TYPE_WORK_MACHINE)
        mz5 = Asset.objects.create(asset_tag="CNC-MZ5", name="MZ5 - MAZAK", internal_number="Int.069",
                                   asset_type=Asset.TYPE_WORK_MACHINE)
        ap = Asset.objects.create(asset_tag="AP-CN5", name="ACCESS POINT CN5", asset_type=Asset.TYPE_OTHER)
        parole, _ = lettura.parole_da_pdf(_pdf([(50, 40, "DMI2"), (300, 40, "-69."), (200, 150, "CN5")]))
        per_id = {p.asset_id: p for p in lettura.abbina(self.layout, parole).proposte}
        self.assertEqual(per_id[dm12.pk].fonte, lettura.FONTE_SIGLA)  # OCR: I letta al posto di 1
        self.assertEqual(per_id[mz5.pk].fonte, lettura.FONTE_NUMERO_INTERNO)  # «Int.069» = «-69.»
        self.assertNotIn(ap.pk, per_id)  # «CN5» è il reparto

    def test_spostamento_grande_non_preselezionato(self):
        PlantLayoutMarker.objects.create(layout=self.layout, asset=self.dm7, x_percent=90, y_percent=90)
        parole, _ = lettura.parole_da_pdf(_pdf([(100, 50, "233")]))
        (proposta,) = lettura.abbina(self.layout, parole).proposte
        self.assertTrue(proposta.spostamento_grande)
        self.assertFalse(proposta.preselezionata)

    def test_stato_rispetto_al_marker_attuale(self):
        PlantLayoutMarker.objects.create(layout=self.layout, asset=self.dm7, x_percent=5, y_percent=5)
        parole, _ = lettura.parole_da_pdf(_pdf([(100, 50, "233")]))
        (proposta,) = lettura.abbina(self.layout, parole).proposte
        self.assertEqual(proposta.stato, "sposta")
        self.assertEqual(proposta.x_attuale, 5.0)

    def test_ai_solo_sigle_lette_e_asset_validi(self):
        parole, _ = lettura.parole_da_pdf(_pdf([(100, 50, "MZ-3/A"), (200, 50, "ZZ9")]))
        risposta = SimpleNamespace(content='{"abbinamenti": [{"sigla": "MZ-3/A", "asset_id": %d},'
                                           ' {"sigla": "INVENTATA", "asset_id": %d},'
                                           ' {"sigla": "ZZ9", "asset_id": %d}]}' % (self.mz3.pk, self.dm7.pk, self.pc.pk))
        with patch("ai_assistant.services.chat_with_ollama", return_value=risposta):
            risultato = lettura.abbina(self.layout, parole, usa_ai=True)
        (proposta,) = risultato.proposte
        self.assertEqual((proposta.asset_id, proposta.fonte), (self.mz3.pk, lettura.FONTE_AI))
        self.assertFalse(proposta.preselezionata)

    def test_pdf_senza_testo_o_non_valido(self):
        parole, _ = lettura.parole_da_pdf(_pdf([]))
        self.assertEqual(parole, [])
        with self.assertRaises(lettura.ErroreLettura):
            lettura.parole_da_pdf(b"non un pdf")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class LetturaVisteTests(_MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="pll-admin", email="pll@test.local", password="x")
        _complete_onboarding(self.admin)
        self.client.force_login(self.admin)
        self.layout = PlantLayout.objects.create(category="Officina", name="Pianta", image=_png(400, 200), is_active=True)
        self.dm7 = Asset.objects.create(asset_tag="WM-DM7", name="Centro DM7", internal_number="233",
                                        asset_type=Asset.TYPE_WORK_MACHINE)
        self.url = reverse("assets:plant_layout_editor") + "?leggi=1"

    def _admin(self):
        return (patch("admin_portale.decorators.get_legacy_user", return_value=SimpleNamespace(id=1, ruolo_id=1)),
                patch("admin_portale.decorators.is_legacy_admin", return_value=True))

    def test_pagina_e_proposte_da_pdf(self):
        a, b = self._admin()
        with a, b:
            pagina = self.client.get(self.url + f"&layout={self.layout.id}")
            self.assertContains(pagina, "Leggi e proponi")
            pdf = SimpleUploadedFile("pianta.pdf", _pdf([(100, 50, "DM7 -233-")]), content_type="application/pdf")
            resp = self.client.post(self.url, {"action": "leggi_planimetria", "layout_id": self.layout.id, "pdf": pdf})
        self.assertContains(resp, "Centro DM7")
        self.assertContains(resp, f'value="{self.dm7.pk}:')
        self.assertFalse(PlantLayoutMarker.objects.exists())  # solo proposta

    def test_applica_crea_marker_e_timeline(self):
        a, b = self._admin()
        with a, b:
            resp = self.client.post(self.url, {"action": "applica_proposte", "layout_id": self.layout.id,
                                               "sel": [f"{self.dm7.pk}:25.5:24", "999999:1:1", f"{self.dm7.pk}:abc:1"]})
        self.assertEqual(resp.status_code, 302)
        marker = PlantLayoutMarker.objects.get(layout=self.layout, asset=self.dm7)
        self.assertEqual((marker.x_percent, marker.y_percent), (Decimal("25.50"), Decimal("24.00")))
        self.assertTrue(AssetTimelineEntry.objects.filter(asset=self.dm7, tag="PLANIMETRIA").exists())

    def test_pdf_come_immagine_crea_nuova_versione_non_attiva(self):
        PlantLayoutMarker.objects.create(layout=self.layout, asset=self.dm7, x_percent=5, y_percent=5)
        a, b = self._admin()
        with a, b:
            pdf = SimpleUploadedFile("pianta.pdf", _pdf([(100, 50, "233")]), content_type="application/pdf")
            resp = self.client.post(self.url, {"action": "leggi_planimetria", "layout_id": self.layout.id, "pdf": pdf,
                                               "usa_pdf_immagine": "1"})
            token = resp.context["token_immagine"]
            self.assertRegex(token, r"^[0-9a-f]{32}$")
            self.client.post(self.url, {"action": "applica_proposte", "layout_id": self.layout.id,
                                        "token_immagine": token, "sel": [f"{self.dm7.pk}:25:24"]})
        nuova = PlantLayout.objects.exclude(pk=self.layout.pk).get()
        self.assertFalse(nuova.is_active)
        self.assertEqual(PlantLayoutMarker.objects.get(layout=nuova, asset=self.dm7).x_percent, Decimal("25.00"))
        # la pianta attuale resta com'era
        self.assertEqual(PlantLayoutMarker.objects.get(layout=self.layout, asset=self.dm7).x_percent, Decimal("5.00"))
