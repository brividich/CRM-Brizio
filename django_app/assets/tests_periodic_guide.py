"""Verifiche periodiche: «Come funziona questa verifica», azioni chiare nell'elenco,
riconoscimento dei punti nello stile «quadratino colorato + etichetta» (differenziali)."""

from __future__ import annotations

import tempfile

import fitz
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from assets.models import PeriodicCheckItem, PeriodicCheckSystem, PeriodicCheckType
from assets.services import periodic_checks as checks
from assets.services import periodic_layout
from assets.tests_periodic_layout import TITLE_BLOCK, synthetic_plan

User = get_user_model()


def marker_plan() -> bytes:
    """Planimetria stile differenziali: quadratino pieno colorato + etichetta nera accanto."""
    doc = fitz.open()
    page = doc.new_page(width=842, height=1190)
    page.draw_rect(fitz.Rect(60, 80, 780, 950), color=(0, 0, 0), width=1)
    codes = ["D1", "D2", "D3", "D3/A", "D12", "7"]
    for index, code in enumerate(codes):
        x, y = 150 + index * 100, 300 + (index % 2) * 120
        page.draw_rect(fitz.Rect(x - 3, y - 3, x + 3, y + 3), color=None, fill=(0.85, 0, 0) if code != "7" else (1, 0.9, 0))
        page.insert_text((x + 6, y + 3), code, fontsize=7, color=(0, 0, 0))
    # due codici attaccati nella stessa scritta, ognuno col suo quadratino
    page.draw_rect(fitz.Rect(597, 697, 603, 703), color=None, fill=(0.85, 0, 0))
    page.draw_rect(fitz.Rect(627, 697, 633, 703), color=None, fill=(0.85, 0, 0))
    page.insert_text((605, 712), "D52D53", fontsize=7, color=(0, 0, 0))
    data = doc.tobytes()
    doc.close()
    return data


class RiconoscimentoPuntiTests(SimpleTestCase):
    def test_stile_luci(self):
        points = periodic_layout.extract_points(synthetic_plan())
        self.assertEqual(len(points), 12)
        self.assertEqual(points[0]["style"], periodic_layout.STYLE_RED_X)

    def test_stile_differenziali(self):
        points = periodic_layout.extract_points(marker_plan())
        self.assertEqual(points[0]["style"], periodic_layout.STYLE_MARKER)
        self.assertEqual([p["code"] for p in points], ["7", "D1", "D2", "D3", "D3/A", "D12", "D52", "D53"])

    def test_ordinamento_codici(self):
        codes = ["D12", "D3/A", "7", "D3", "D1"]
        self.assertEqual(sorted(codes, key=periodic_layout.point_sort_key), ["7", "D1", "D3", "D3/A", "D12"])


@override_settings(LEGACY_AUTH_ENABLED=False)
class GuidaTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        override = override_settings(ASSETS_PRIVATE_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._tmp.cleanup)
        self.client.force_login(User.objects.create_superuser(username="pg-admin", password="x", email="pg@y.z"))
        self.system = PeriodicCheckSystem.objects.create(name="Impianto elettrico")

    def _type(self, name, method):
        return PeriodicCheckType.objects.create(system=self.system, name=name, frequency_months=12, method=method)

    def _page(self, check_type):
        return self.client.get(reverse("assets:periodic_check_type_detail", args=[check_type.id]))

    def test_planimetria_mancante_poi_stampa_foglio(self):
        luci = self._type("Luci", PeriodicCheckType.METHOD_LAYOUT)
        page = self._page(luci)
        self.assertContains(page, "Come funziona questa verifica")
        self.assertEqual(page.context["guide"]["steps"][0]["title"], "Carica la planimetria")
        self.assertTrue(page.context["guide"]["steps"][0]["is_next"])
        self.assertContains(page, "Prima completa il passo precedente")

        checks.create_layout(luci, synthetic_plan(), exclude_areas=[TITLE_BLOCK])
        page = self._page(luci)
        steps = page.context["guide"]["steps"]
        self.assertEqual((steps[0]["state"], steps[1]["title"]), ("done", "Stampa il foglio per il tecnico"))
        self.assertTrue(steps[1]["is_next"])
        self.assertContains(page, reverse("assets:periodic_check_sheet_issue", args=[luci.id]))

        checks.issue_sheet(luci)
        steps = self._page(luci).context["guide"]["steps"]
        self.assertEqual(steps[2]["state"], "todo")
        self.assertIn("in attesa", steps[2]["detail"])

    def test_checklist_senza_voci_poi_registra(self):
        quadri = self._type("Quadri", PeriodicCheckType.METHOD_CHECKLIST)
        steps = self._page(quadri).context["guide"]["steps"]
        self.assertEqual((steps[0]["title"], steps[1]["state"]), ("Definisci le voci", "blocked"))
        PeriodicCheckItem.objects.create(check_type=quadri, label="Esame a vista")
        steps = self._page(quadri).context["guide"]["steps"]
        self.assertEqual((steps[0]["state"], steps[1]["title"], steps[1]["state"]), ("done", "Registra la verifica", "ready"))

    def test_misure_dice_cosa_manca(self):
        ups = self._type("UPS", PeriodicCheckType.METHOD_MEASURES)
        self.assertContains(self._page(ups), "lettura automatica delle misure")

    def test_elenco_con_azioni_per_metodo(self):
        luci = self._type("Luci", PeriodicCheckType.METHOD_LAYOUT)
        self._type("Terra", PeriodicCheckType.METHOD_REPORT)
        page = self.client.get(reverse("assets:periodic_check_list"))
        self.assertContains(page, "Carica planimetria")
        self.assertContains(page, "Apri scheda")
        checks.create_layout(luci, synthetic_plan())
        page = self.client.get(reverse("assets:periodic_check_list"))
        self.assertContains(page, "Stampa foglio")
        self.assertContains(page, reverse("assets:periodic_check_register", args=[PeriodicCheckType.objects.get(name="Terra").id]))

    def test_impostazioni_mostra_i_punti_riconosciuti(self):
        luci = self._type("Luci", PeriodicCheckType.METHOD_LAYOUT)
        checks.create_layout(luci, synthetic_plan())
        page = self.client.get(reverse("assets:periodic_check_type_detail", args=[luci.id]), {"tab": "impostazioni"})
        self.assertContains(page, "Punti riconosciuti (12)")
        self.assertContains(page, "12 punti riconosciuti")
