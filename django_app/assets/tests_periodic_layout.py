"""Verifiche periodiche, metodo planimetria: foglio con QR, lettura della scansione, conferma.

La planimetria e' sintetica (disegnata qui con PyMuPDF come quelle Novicrom: riquadro
rosso con la X e numero rosso), la «scansione» e' il foglio rasterizzato, segnato,
ruotato e compresso in JPEG.
"""

from __future__ import annotations

import tempfile
from datetime import date
from io import BytesIO

import fitz
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter

from assets.models import (
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
)
from assets.services import periodic_checks as checks
from assets.services import periodic_layout
from core.qr import disponibile as qr_disponibile
from core.qr import leggi_codici

User = get_user_model()

POINTS = {str(n): (120 + (n - 1) % 4 * 190, 160 + (n - 1) // 4 * 260) for n in range(1, 13)}
TITLE_BLOCK = [600.0, 1000.0, 800.0, 1150.0]


def synthetic_plan() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=842, height=1190)
    # muri: danno appigli all'allineamento
    for x0, y0, x1, y1 in ((60, 80, 780, 80), (60, 80, 60, 950), (780, 80, 780, 950), (60, 950, 780, 950),
                           (300, 80, 300, 600), (60, 600, 520, 600), (520, 400, 780, 400)):
        page.draw_line((x0, y0), (x1, y1), color=(0, 0, 0), width=1.2)
    for code, (x, y) in POINTS.items():
        box = page.new_shape()
        box.draw_rect(fitz.Rect(x - 4.85, y - 4.85, x + 4.85, y + 4.85))
        box.finish(color=(1, 0, 0), width=0.6)
        box.commit()
        cross = page.new_shape()
        for (ax, ay), (bx, by) in (((-4, -2.6), (4, 2.6)), ((-4, 2.6), (4, -2.6))):
            for step in range(4):
                t0, t1 = step / 4, (step + 1) / 4
                cross.draw_line((x + ax + (bx - ax) * t0, y + ay + (by - ay) * t0),
                                (x + ax + (bx - ax) * t1, y + ay + (by - ay) * t1))
        cross.finish(color=(1, 0, 0), width=0.6)
        cross.commit()
        page.insert_text((x - 20, y + 3), code, fontsize=8, color=(1, 0, 0))
    page.draw_rect(fitz.Rect(*TITLE_BLOCK), color=(0, 0, 0), width=0.8)
    page.insert_text((620, 1040), "NON FUNZIONANTI", fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


def fake_scan(sheet_pdf: bytes, geo, *, highlight=(), circle=(), rotate=90) -> bytes:
    """Foglio stampato e scansionato: rasterizzato, segnato, storto, ruotato, JPEG."""
    dpi = 200
    pix = fitz.open(stream=sheet_pdf, filetype="pdf")[0].get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    k = dpi / 72
    draw = ImageDraw.Draw(img, "RGBA")
    for code in highlight:
        x, y = geo.to_sheet(*POINTS[code])
        draw.rounded_rectangle([x * k - 16, y * k - 12, x * k + 16, y * k + 12], 6, fill=(255, 60, 200, 120))
    for code in circle:
        x, y = geo.to_sheet(*POINTS[code])
        draw.ellipse([x * k - 24, y * k - 24, x * k + 24, y * k + 24], outline=(60, 60, 60, 255), width=3)
    img = img.rotate(0.8, resample=Image.BICUBIC, expand=True, fillcolor=(246, 244, 239))
    img = img.filter(ImageFilter.GaussianBlur(0.6)).rotate(rotate, expand=True)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=75)
    out = fitz.open()
    page = out.new_page(width=img.width * 72 / dpi, height=img.height * 72 / dpi)
    page.insert_image(page.rect, stream=buf.getvalue())
    data = out.tobytes()
    out.close()
    return data


class EstrazionePuntiTests(SimpleTestCase):
    def test_trova_tutti_i_punti_della_planimetria(self):
        points = periodic_layout.extract_points(synthetic_plan())
        self.assertEqual([p["code"] for p in points], [str(n) for n in range(1, 13)])
        by = {p["code"]: p for p in points}
        self.assertAlmostEqual(by["6"]["x"], POINTS["6"][0], delta=0.5)
        self.assertAlmostEqual(by["6"]["y"], POINTS["6"][1], delta=0.5)

    def test_token_dal_qr(self):
        self.assertEqual(periodic_layout.token_from_qr("NVC-VP:ABCD234XYZ"), "ABCD234XYZ")
        self.assertEqual(periodic_layout.token_from_qr("nvc-vp:abcd234xyz"), "ABCD234XYZ")
        self.assertEqual(periodic_layout.token_from_qr("https://esempio"), "")


@override_settings(LEGACY_AUTH_ENABLED=False)
class FoglioEScansioneTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="pl-admin", password="x", email="pl@y.z")
        system = PeriodicCheckSystem.objects.create(name="Impianto elettrico")
        cls.check_type = PeriodicCheckType.objects.create(
            system=system, name="Verifica illuminazione di emergenza", frequency_months=4,
            method=PeriodicCheckType.METHOD_LAYOUT,
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self._tmp = tempfile.TemporaryDirectory()
        override = override_settings(ASSETS_PRIVATE_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._tmp.cleanup)
        self.layout = checks.create_layout(self.check_type, synthetic_plan(), name="plan.pdf", exclude_areas=[TITLE_BLOCK])

    def _issue(self) -> PeriodicCheckSession:
        response = self.client.post(reverse("assets:periodic_check_sheet_issue", args=[self.check_type.id]))
        session = PeriodicCheckSession.objects.filter(status=PeriodicCheckSession.STATUS_ISSUED).latest("id")
        self.assertRedirects(response, reverse("assets:periodic_check_session_detail", args=[session.id]) + "?stampa=1",
                             fetch_redirect_response=False)
        return session

    def _sheet(self, session):
        response = self.client.get(reverse("assets:periodic_check_sheet_pdf", args=[session.id]))
        self.assertEqual(response["Content-Type"], "application/pdf")
        _pdf, geo = checks.build_sheet_for(session.layout)
        return response.content, geo

    def test_planimetria_caricata_con_punti_e_versione(self):
        self.assertEqual((self.layout.version, self.layout.points.count()), (1, 12))
        second = checks.create_layout(self.check_type, synthetic_plan(), name="plan-v2.pdf")
        self.layout.refresh_from_db()
        self.assertEqual((second.version, second.is_active, self.layout.is_active), (2, True, False))
        self.assertEqual(self.check_type.active_layout, second)

    def test_foglio_con_qr_leggibile(self):
        session = self._issue()
        self.assertEqual(len(session.sheet_token), 10)
        pdf, _geo = self._sheet(session)
        if qr_disponibile():
            self.assertIn(f"NVC-VP:{session.sheet_token}", leggi_codici(pdf, "foglio.pdf"))
        self.assertEqual(self.client.get(reverse("assets:periodic_check_sheet_preview", args=[self.check_type.id])).status_code, 200)

    def test_scansione_letta_proposta_e_confermata(self):
        session = self._issue()
        pdf, geo = self._sheet(session)
        scan = fake_scan(pdf, geo, highlight=("5",), circle=("9",))
        url = reverse("assets:periodic_check_session_detail", args=[session.id])
        self.client.post(url, {"action": "scan", "scan": SimpleUploadedFile("scan.pdf", scan, content_type="application/pdf")})
        session.refresh_from_db()
        self.assertEqual(session.status, PeriodicCheckSession.STATUS_DRAFT)
        self.assertTrue(session.reading["ok"], session.reading)
        proposed = {r.point.code: r.category for r in session.results.filter(kind=PeriodicCheckResult.KIND_POINT)}
        self.assertEqual(proposed, {"5": "Non funzionante", "9": "Bassa autonomia"})
        names = set(session.attachments.values_list("original_name", flat=True))
        self.assertEqual(names, {"scan.pdf", "lettura-automatica.png"})
        page = self.client.get(url)
        self.assertContains(page, "Conferma verifica")
        self.assertNotContains(page, "{#")

        # La scadenza non si muove finche' non si conferma.
        self.check_type.refresh_from_db()
        self.assertIsNone(self.check_type.next_due_date)
        r9 = session.results.get(point__code="9")
        r5 = session.results.get(point__code="5")
        self.client.post(url, {
            "action": "confirm_points", "performed_on": "2026-09-20", "technician": "Tecnico prova",
            f"point_{r5.id}": "Non funzionante", f"point_{r9.id}": "", "add_1": "11",
        })
        session.refresh_from_db()
        self.assertEqual(session.status, PeriodicCheckSession.STATUS_CONFIRMED)
        self.assertEqual(session.outcome, PeriodicCheckSession.OUTCOME_REMARKS)
        final = {r.point.code: r.category for r in session.results.filter(kind=PeriodicCheckResult.KIND_POINT)}
        self.assertEqual(final, {"5": "Non funzionante", "11": "Bassa autonomia"})
        self.check_type.refresh_from_db()
        self.assertEqual(self.check_type.next_due_date, date(2027, 1, 20))

    def test_scansione_pulita_nessun_punto(self):
        session = self._issue()
        pdf, geo = self._sheet(session)
        url = reverse("assets:periodic_check_session_detail", args=[session.id])
        self.client.post(url, {"action": "scan", "scan": SimpleUploadedFile("pulita.pdf", fake_scan(pdf, geo, rotate=0))})
        session.refresh_from_db()
        self.assertTrue(session.reading["ok"])
        self.assertEqual(session.reading["proposti"], {})

    def test_scansione_di_un_altro_foglio_rifiutata(self):
        if not qr_disponibile():
            self.skipTest("zxing-cpp non installato")
        first, second = self._issue(), self._issue()
        pdf, geo = self._sheet(second)
        url = reverse("assets:periodic_check_session_detail", args=[first.id])
        self.client.post(url, {"action": "scan", "scan": SimpleUploadedFile("altro.pdf", fake_scan(pdf, geo, highlight=("3",)))})
        first.refresh_from_db()
        self.assertEqual(first.status, PeriodicCheckSession.STATUS_ISSUED)
        self.assertFalse(first.attachments.exists())

    def test_registrazione_a_mano_con_i_numeri(self):
        url = reverse("assets:periodic_check_register", args=[self.check_type.id])
        base = {"performed_on": timezone.localdate().isoformat(), "outcome": "OK"}
        response = self.client.post(url, {**base, "codes_0": "3, 99"})
        self.assertContains(response, "99")
        self.assertFalse(PeriodicCheckSession.objects.exists())
        self.client.post(url, {**base, "codes_0": "3 7", "codes_1": "12"})
        session = PeriodicCheckSession.objects.get()
        self.assertEqual(session.outcome, PeriodicCheckSession.OUTCOME_REMARKS)
        got = {r.point.code: r.category for r in session.results.all()}
        self.assertEqual(got, {"3": "Non funzionante", "7": "Non funzionante", "12": "Bassa autonomia"})
