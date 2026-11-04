"""«Importa planimetrie»: allineamento automatico sui muri, piante dai PDF, validazione degli asset."""

from __future__ import annotations

import io

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from assets.models import Asset, AssetCategory, PlantLayout, PlantLayoutArea, PlantLayoutMarker
from assets.services import planimetria_allinea as allinea
from assets.services import planimetria_import as importa
from assets.services import planimetria_lettura as lettura
from assets.tests import _complete_onboarding
from assets.tests_plant_layout_image import _MediaMixin

# muri di uno stabilimento sintetico (coordinate del disegno, 0..100 x 0..70)
_MURI = [
    ((5, 5), (95, 5)), ((95, 5), (95, 65)), ((95, 65), (5, 65)), ((5, 65), (5, 5)),
    ((40, 5), (40, 40)), ((40, 40), (70, 40)), ((70, 40), (70, 65)), ((20, 30), (20, 65)),
    ((55, 5), (55, 25)), ((80, 20), (95, 20)), ((5, 50), (20, 50)),
]


def _pdf(*, ruota=False, scala=1.0, sigle=(), legenda=False, titolo="") -> bytes:
    """Pianta sintetica: muri grigi, simboli colorati con sigla, legenda; ruotata di 90° se richiesto."""
    import fitz

    doc = fitz.open()
    w, h = (420, 600) if ruota else (600, 420)
    page = doc.new_page(width=w, height=h)

    def p(x, y):
        x, y = 20 + x * 5 * scala, 20 + y * 5 * scala
        return fitz.Point(w - y, x) if ruota else fitz.Point(x, y)  # 90° in senso orario

    for a, b in _MURI:
        page.draw_line(p(*a), p(*b), color=(0.3, 0.3, 0.3), width=1.2)
    for x, y, testo in sigle:
        c = p(x, y)
        if not testo.startswith("-"):  # «-233-»: numero di macchina del disegno di fondo, senza simbolo
            page.draw_rect(fitz.Rect(c.x - 5, c.y - 5, c.x + 5, c.y + 5), color=(1, 0.5, 0), fill=(1, 0.5, 0))
        page.insert_text((c.x + 7, c.y + 3), testo, fontsize=8)
    if legenda:
        r = fitz.Rect(w - 170, h - 100, w - 10, h - 10)
        page.draw_rect(r, color=(0, 0, 0))
        page.insert_text((r.x0 + 8, r.y0 + 16), "LEGENDA", fontsize=9)
        if titolo:
            page.insert_text((r.x0 + 8, r.y0 + 32), titolo, fontsize=8)
        page.draw_rect(fitz.Rect(r.x0 + 8, r.y0 + 44, r.x0 + 18, r.y0 + 54), color=(1, 0.5, 0), fill=(1, 0.5, 0))
        page.insert_text((r.x0 + 24, r.y0 + 52), "CARROPONTI", fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


def _png_da_pdf(data: bytes) -> bytes:
    return lettura.pagina_pdf_png(data, 0, lato_max=1400)


class AllineamentoAutomaticoTests(SimpleTestCase):
    def test_ritrova_rotazione_scala_e_spostamento(self):
        from PIL import Image

        base = Image.open(io.BytesIO(_png_da_pdf(_pdf())))
        liv_pdf = _pdf(ruota=True, scala=0.8, legenda=True)
        liv = Image.open(io.BytesIO(_png_da_pdf(liv_pdf)))
        pag = lettura.leggi_pagina_pdf(liv_pdf, ocr_se_vuoto=False)
        esito = allinea.allinea(liv, base, pag.riquadri)
        self.assertIsNotNone(esito)
        self.assertTrue(esito.buono, esito)
        self.assertAlmostEqual(esito.rotazione % 360, 270, delta=1.5)  # il livello torna indietro di 90°
        # l'angolo del muro (95, 5) del livello cade su quello della base
        wl, hl = liv.size
        wb, hb = base.size
        (x1, y1, bx1, by1), (x2, y2, bx2, by2) = esito.punti
        l1, l2 = complex(x1 * wl / 100, y1 * hl / 100), complex(x2 * wl / 100, y2 * hl / 100)
        b1, b2 = complex(bx1 * wb / 100, by1 * hb / 100), complex(bx2 * wb / 100, by2 * hb / 100)
        s = (b2 - b1) / (l2 - l1)
        t = b1 - s * l1
        zoom_l, zoom_b = wl / 420, wb / 600
        angolo_liv = complex((420 - (20 + 5 * 5 * 0.8)) * zoom_l, (20 + 95 * 5 * 0.8) * zoom_l)
        atteso = complex((20 + 95 * 5) * zoom_b, (20 + 5 * 5) * zoom_b)
        self.assertLess(abs(s * angolo_liv + t - atteso), 0.012 * wb)

    def test_immagine_senza_tratti(self):
        from PIL import Image

        bianca = Image.new("RGB", (300, 200), "white")
        self.assertIsNone(allinea.allinea(bianca, bianca))

    def test_nome_del_servizio(self):
        self.assertEqual(importa.nome_servizio("PLANIMETRIA CONDIZIONATORI E CALDAIE 02_2026.pdf"), "Condizionatori e caldaie")
        self.assertEqual(importa.nome_servizio("PLANIMETRIA TELECAMERE 04_11_2024.pdf"), "Telecamere")
        self.assertEqual(importa.nome_servizio("Planimetria P145_07-2026.pdf"), "P145")
        self.assertEqual(importa.nome_servizio("PLANIMETRIA IMPIANTO GAS - 01_2025.pdf"), "Impianto gas")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ImportaVisteTests(_MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="pim-admin", email="pim@test.local", password="x")
        _complete_onboarding(self.admin)
        self.client.force_login(self.admin)
        self.base = PlantLayout(category="Azienda", name="Planimetria generale", is_active=True)
        self.base.image.save("base.png", ContentFile(_png_da_pdf(_pdf())), save=False)
        self.base.save()
        PlantLayoutArea.objects.create(layout=self.base, name="CN5", reparto_code="CN5", x_percent=10, y_percent=10,
                                       width_percent=10, height_percent=10)
        self.apparecchi = AssetCategory.objects.create(code="aps", label="Apparecchi di sollevamento")
        self.carroponti = AssetCategory.objects.create(code="crp", label="Carroponti", parent=self.apparecchi)
        self.c219 = Asset.objects.create(asset_tag="CRP-1", name="Carroponte prova", internal_number="Int.219",
                                         asset_category=self.carroponti, reparto="CN5")
        self.url = reverse("assets:plant_layout_editor") + "?importa=1"
        self.pdf = _pdf(ruota=True, scala=0.8, legenda=True, titolo="PLANIMETRIA CARROPONTI",
                        sigle=((30, 15, "219"), (60, 50, "CN5"), (75, 30, "-233-")))

    def tearDown(self):
        lettura._CACHE_CATEGORIE.clear()  # la cache delle categorie non passa al test successivo
        super().tearDown()

    def _importa(self, nome="PLANIMETRIA CARROPONTI 07_2025.pdf"):
        return self.client.post(self.url, {
            "action": "importa_uno", "base_id": self.base.id,
            "pdf": SimpleUploadedFile(nome, self.pdf, content_type="application/pdf"),
        })

    def test_pagina(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Importa planimetrie")
        self.assertContains(r, "Planimetria generale")

    def test_importa_crea_livello_allineato_e_non_duplica(self):
        r = self._importa()
        self.assertEqual(r.status_code, 200, r.content)
        dati = r.json()
        self.assertTrue(dati["ok"])
        lay = PlantLayout.objects.get(pk=dati["id"])
        self.assertEqual(lay.base_id, self.base.id)
        self.assertTrue(lay.matrice, lay.allineamento)
        self.assertTrue(lay.allineamento.get("automatico"))
        self.assertEqual(lay.category, "Carroponti")
        self.assertTrue(lay.sorgente_pdf)
        self.assertEqual(lay.importazione["file"], "PLANIMETRIA CARROPONTI 07_2025.pdf")
        self.assertFalse(lay.importazione["validata"])
        self.assertIn(self.apparecchi.id, set(lay.asset_categories.values_list("id", flat=True)) | {
            c.parent_id for c in lay.asset_categories.all()})
        # stesso file di nuovo: aggiorna la stessa pianta
        self._importa()
        self.assertEqual(PlantLayout.objects.exclude(importazione={}).count(), 1)

    def test_valida_dal_pdf_salvato(self):
        lay = PlantLayout.objects.get(pk=self._importa().json()["id"])
        url = reverse("assets:plant_layout_editor") + f"?leggi=1&layout={lay.id}&sorgente=1"
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Valida e colloca")
        risultato = r.context["risultato"]
        self.assertEqual([p.asset_id for p in risultato.proposte], [self.c219.id])
        # né il reparto CN5 né il numero di macchina -233- sono asset da creare; niente reparti su un livello
        self.assertEqual([d.sigla for d in risultato.da_creare], [])
        self.assertEqual(risultato.reparti, [])
        p = risultato.proposte[0]
        r = self.client.post(reverse("assets:plant_layout_editor") + "?leggi=1", {
            "action": "applica_proposte", "layout_id": lay.id, "sel": f"{p.asset_id}:{p.x}:{p.y}",
        })
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        lay.refresh_from_db()
        self.assertTrue(lay.importazione["validata"])
        self.assertTrue(PlantLayoutMarker.objects.filter(layout=lay, asset=self.c219).exists())

    def test_scarta(self):
        lay_id = self._importa().json()["id"]
        self.client.post(self.url, {"action": "scarta", "layout_id": lay_id})
        self.assertFalse(PlantLayout.objects.filter(pk=lay_id).exists())
        # la pianta base non si scarta
        self.client.post(self.url, {"action": "scarta", "layout_id": self.base.id})
        self.assertTrue(PlantLayout.objects.filter(pk=self.base.id).exists())

    def test_non_pdf(self):
        r = self.client.post(self.url, {
            "action": "importa_uno", "base_id": self.base.id,
            "pdf": SimpleUploadedFile("pianta.png", b"x", content_type="image/png"),
        })
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])
