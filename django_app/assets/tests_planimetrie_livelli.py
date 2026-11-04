"""Planimetrie: legenda nella lettura, asset e reparti dalla pianta, pianta base + livelli, scala reale."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset, AssetCategory, PlantLayout, PlantLayoutArea, PlantLayoutMarker
from assets.services import planimetria_livelli as livelli
from assets.services import planimetria_lettura as lettura
from assets.services import planimetria_pagina as pagina
from assets.tests import _complete_onboarding
from assets.tests_plant_layout_image import _MediaMixin, _png


def _pdf_servizio(*, rotazione=0) -> bytes:
    """Pianta di servizio sintetica: simboli colorati con sigla e una legenda in basso a destra."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    azzurro, rosso = (0, 1, 1), (1, 0, 0)
    # sulla pianta: due chiller e un bruciatore, più un differenziale senza asset
    for x, y, testo, colore in ((100, 100, "C1", azzurro), (200, 100, "C12", azzurro), (100, 200, "B3", rosso),
                                (300, 250, "D5", rosso)):
        page.draw_rect(fitz.Rect(x - 6, y - 6, x + 6, y + 6), color=colore, fill=colore)
        page.insert_text((x + 9, y + 3), testo, fontsize=8)
    page.insert_text((150, 300), "10", fontsize=8)  # numero di stanza: non è la macchina Int.10
    # legenda
    page.draw_rect(fitz.Rect(380, 270, 590, 390), color=(0, 0, 0))
    page.insert_text((390, 285), "LEGENDA", fontsize=9)
    page.insert_text((390, 300), "TIPOLOGIA", fontsize=7)
    page.insert_text((480, 300), "COSTRUTTORE", fontsize=7)
    page.draw_rect(fitz.Rect(390, 310, 400, 320), color=azzurro, fill=azzurro)
    page.insert_text((405, 318), "CHILLER", fontsize=7)
    page.insert_text((480, 318), "AERMEC", fontsize=7)
    page.insert_text((530, 318), "C1, C2, C12", fontsize=7)
    page.draw_rect(fitz.Rect(390, 340, 400, 350), color=rosso, fill=rosso)
    page.insert_text((405, 348), "BRUCIATORI", fontsize=7)
    page.insert_text((480, 348), "RIELLO", fontsize=7)
    page.insert_text((530, 348), "B3", fontsize=7)
    if rotazione:
        page.set_rotation(rotazione)
    data = doc.tobytes()
    doc.close()
    return data


class LegendaTests(_MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.chiller = AssetCategory.objects.create(code="chiller", label="Chiller")
        self.bruciatori = AssetCategory.objects.create(code="bruciatori", label="Bruciatori")
        self.macchine = AssetCategory.objects.create(code="macchine", label="Macchine utensili")
        self.layout = PlantLayout.objects.create(category="Clima", name="Condizionatori", image=_png(600, 400), is_active=True)
        self.c1 = Asset.objects.create(asset_tag="CH-1", name="Chiller 1", internal_number="Int.C1",
                                       asset_category=self.chiller, manufacturer="Aermec")
        self.c12 = Asset.objects.create(asset_tag="CH-12", name="Chiller 12", internal_number="Int.C12",
                                        asset_category=self.chiller, manufacturer="Mitsubishi")
        self.b3 = Asset.objects.create(asset_tag="BR-3", name="Bruciatore 3", internal_number="Int.B3",
                                       asset_category=self.bruciatori)
        self.tornio = Asset.objects.create(asset_tag="ML-10", name="Tornio", internal_number="Int.10",
                                           asset_category=self.macchine, asset_type=Asset.TYPE_WORK_MACHINE)

    def test_legenda_letta_e_tenuta_fuori_dalle_posizioni(self):
        pag = lettura.leggi_pagina_pdf(_pdf_servizio(), ocr_se_vuoto=False)
        self.assertEqual([t.upper() for _c, t in pag.legenda.tipi], ["CHILLER", "BRUCIATORI"])
        self.assertEqual(pag.legenda.costruttori.get("C12"), "AERMEC")
        self.assertEqual(pag.legenda.costruttori.get("B3"), "RIELLO")
        testi = {p.testo for p in pag.parole}
        self.assertNotIn("LEGENDA", testi)
        self.assertNotIn("C2,", testi)  # la sigla della legenda non è una posizione

    def test_sigle_brevi_categorie_dalla_legenda_e_avvisi(self):
        pag = lettura.leggi_pagina_pdf(_pdf_servizio(), ocr_se_vuoto=False)
        risultato = lettura.abbina(self.layout, pagina=pag)
        per_id = {p.asset_id: p for p in risultato.proposte}
        self.assertEqual(set(per_id), {self.c1.pk, self.c12.pk, self.b3.pk})  # niente Int.10: è un'altra categoria
        self.assertEqual(per_id[self.c1.pk].tipo.upper(), "CHILLER")
        self.assertTrue(per_id[self.c1.pk].preselezionata)
        # costruttore diverso fra legenda e scheda: proposta con avviso, non preselezionata
        self.assertTrue(any("AERMEC" in a for a in per_id[self.c12.pk].avvisi))
        self.assertFalse(per_id[self.c12.pk].preselezionata)
        self.assertEqual(risultato.categorie_note, "dalla legenda della pianta")
        self.assertAlmostEqual(per_id[self.c1.pk].x, 100 / 600 * 100 + 2.5, delta=3)

    def test_sigla_senza_asset_diventa_da_creare(self):
        pag = lettura.leggi_pagina_pdf(_pdf_servizio(), ocr_se_vuoto=False)
        risultato = lettura.abbina(self.layout, pagina=pag)
        (nuovo,) = [d for d in risultato.da_creare if d.sigla == "D5"]
        self.assertEqual(nuovo.tipo.upper(), "BRUCIATORI")  # simbolo rosso
        self.assertEqual(nuovo.categoria_id, self.bruciatori.id)
        self.assertTrue(nuovo.nome.startswith("Bruciatore D5"))

    def test_pagina_ruotata_raddrizzata(self):
        pag = lettura.leggi_pagina_pdf(_pdf_servizio(rotazione=90), ocr_se_vuoto=False)
        c1 = next(p for p in pag.parole if p.testo == "C1")
        # ruotata di 90° in senso orario: la x originale diventa la y
        self.assertAlmostEqual(c1.y, (100 + 9) / 600 * 100, delta=3)
        self.assertGreater(c1.x, 50)

    def test_elenco_sigla_descrizione_e_correzioni_ocr(self):
        righe = [pagina.Riga(f"T{i} PIAZZALE {n}", 80, 10 + i * 2) for i, n in enumerate(["UFFICI", "NORD", "SUD", "EST", "OVEST"], 1)]
        leg = pagina.interpreta_legenda(righe, [])
        self.assertEqual(leg.descrizioni["T1"], "PIAZZALE UFFICI")
        self.assertIsNotNone(pagina._riquadro_elenco(righe))
        self.assertEqual(pagina.correggi_sigla_ocr("T1Z"), "T12")
        self.assertEqual(pagina.correggi_sigla_ocr("D95/A"), "D95/A")
        self.assertEqual(pagina.correggi_sigla_ocr("CHILLER"), "CHILLER")

    def test_categoria_per_testo_non_confonde_le_parole(self):
        AssetCategory.objects.create(code="noce", label="Macchine NO CE")
        self.assertEqual([c.label for c in lettura.categorie_per_testo("CHILLER")], ["Chiller"])
        self.assertEqual(lettura.categorie_per_testo("DIFFERENZIALI MACCHINE"), [])
        self.assertEqual(lettura.singolare("DIFFERENZIALI DI SERVIZIO"), "Differenziale di servizio")


class AllineamentoTests(_MediaMixin, TestCase):
    def test_matrice_con_rotazione_e_scala(self):
        # livello 200x100, base 100x200: il livello è la base ruotata di 90° in senso orario e scalata x2
        punti = [[0, 0, 100, 0], [100, 0, 100, 100]]
        m = livelli.calcola_matrice(punti, (200, 100), (100, 200))
        lay = PlantLayout(allineamento={"matrice": m}, base_id=1)
        self.assertEqual(lay.su_base(0, 0), (100.0, 0.0))
        self.assertEqual(lay.su_base(100, 0), (100.0, 100.0))
        self.assertEqual(lay.su_base(0, 100), (0.0, 0.0))
        self.assertEqual(livelli.descrivi_matrice(m, (200, 100), (100, 200))["rotazione"], 90.0)

    def test_punti_troppo_vicini(self):
        with self.assertRaises(livelli.ErroreAllineamento):
            livelli.calcola_matrice([[10, 10, 10, 10], [10.05, 10, 50, 50]], (1000, 1000), (1000, 1000))

    def test_scala_reale(self):
        lay = PlantLayout(scala={"punti": [[10, 10], [60, 10]], "metri": 50, "rapporto": 0.5})
        self.assertAlmostEqual(lay.metri_tra(10, 10, 10, 30), 10.0)  # 20% dell'altezza = 10% della larghezza
        self.assertAlmostEqual(lay.metri_quadri(10 * 20), 10 * 10 * 1.0)  # 10% x 20% = 10 m x 10 m


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class LivelliVisteTests(_MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="plv-admin", email="plv@test.local", password="x")
        _complete_onboarding(self.admin)
        self.client.force_login(self.admin)
        self.base = PlantLayout.objects.create(category="Officina", name="Generale", image=_png(400, 200), is_active=True)
        PlantLayoutArea.objects.create(layout=self.base, name="CN5", reparto_code="CN5", x_percent=40, y_percent=40,
                                       width_percent=20, height_percent=20)
        self.livello = PlantLayout.objects.create(category="Clima", name="Condizionatori", image=_png(400, 200), is_active=True)
        self.cat = AssetCategory.objects.create(code="chiller", label="Chiller")
        self.chiller = Asset.objects.create(asset_tag="CH-1", name="Chiller 1", internal_number="Int.C1", asset_category=self.cat)
        PlantLayoutMarker.objects.create(layout=self.livello, asset=self.chiller, x_percent=30, y_percent=40)
        self.url = reverse("assets:plant_layout_editor")

    def _admin(self):
        return (patch("admin_portale.decorators.get_legacy_user", return_value=SimpleNamespace(id=1, ruolo_id=1)),
                patch("admin_portale.decorators.is_legacy_admin", return_value=True))

    def _allinea(self):
        a, b = self._admin()
        with a, b:
            self.client.post(self.url + f"?livello={self.livello.id}", {
                "action": "salva_impostazioni", "layout_id": self.livello.id, "base": self.base.id,
                "colore": "#ff0000", "categorie": [self.cat.id]})
            # stesso disegno spostato: il centro del livello è a (25, 25) sulla base, metà scala
            self.client.post(self.url + f"?livello={self.livello.id}", {
                "action": "salva_allineamento", "layout_id": self.livello.id,
                "p1x": 0, "p1y": 0, "p1bx": 0, "p1by": 0, "p2x": 100, "p2y": 100, "p2bx": 50, "p2by": 50})
        self.livello.refresh_from_db()

    def test_impostazioni_allineamento_e_mappa(self):
        a, b = self._admin()
        with a, b:
            pagina_liv = self.client.get(self.url + f"?livello={self.livello.id}")
        self.assertContains(pagina_liv, "Livello, allineamento e scala")
        self._allinea()
        self.assertEqual(self.livello.base, self.base)
        self.assertEqual(self.livello.colore, "#FF0000")
        self.assertEqual(list(self.livello.asset_categories.all()), [self.cat])
        self.assertEqual(self.livello.su_base(30, 40), (15.0, 20.0))
        resp = self.client.get(reverse("assets:plant_layout_map") + "?category=Officina&format=json")
        (liv,) = resp.json()["payload"]["livelli"]
        self.assertEqual(liv["nome"], "Clima")
        self.assertEqual((liv["markers"][0]["x_percent"], liv["markers"][0]["y_percent"]), (15.0, 20.0))
        # stampa con il livello acceso
        stampa = self.client.get(reverse("assets:plant_layout_map") + f"?category=Officina&stampa=1&livelli={self.livello.id}&solo=1")
        self.assertContains(stampa, "Chiller 1")
        self.assertContains(stampa, "Legenda")
        # «Dov'è?» apre la base con il livello acceso
        url = livelli.url_mappa_asset(self.chiller)
        self.assertIn("category=Officina", url)
        self.assertIn(f"livelli={self.livello.id}", url)

    def test_copertura_e_scala(self):
        self._allinea()
        Asset.objects.create(asset_tag="CH-2", name="Chiller 2", internal_number="Int.C2", asset_category=self.cat)
        cop = livelli.copertura(self.livello)
        self.assertEqual((cop["collocati"], cop["totale"]), (1, 2))
        a, b = self._admin()
        with a, b:
            self.client.post(self.url + f"?livello={self.base.id}", {
                "action": "salva_scala", "layout_id": self.base.id, "s1x": 10, "s1y": 10, "s2x": 60, "s2y": 10, "metri": "50"})
        self.base.refresh_from_db()
        self.assertTrue(self.base.ha_scala)
        self.assertEqual(self.base.scala["rapporto"], 0.5)
        resp = self.client.get(reverse("assets:plant_layout_map") + "?category=Officina&format=json")
        area = resp.json()["payload"]["areas"][0]
        self.assertAlmostEqual(area["m2"], 20 * 20 * 0.5 * 1.0, delta=0.5)

    def test_nuova_versione_della_base_sposta_i_livelli(self):
        self._allinea()
        nuova = PlantLayout.objects.create(category="Officina", name="Generale v2", image=_png(400, 200), is_active=False)
        nuova.is_active = True
        nuova.save()
        self.livello.refresh_from_db()
        self.assertEqual(self.livello.base, nuova)
        self.assertTrue(self.livello.allineamento["da_verificare"])

    def test_ruota_la_base_riallinea_i_livelli(self):
        from assets.services.plant_layout_image import rotate_layout

        self._allinea()
        rotate_layout(self.base, clockwise=True)
        self.livello.refresh_from_db()
        # il punto (50,50) del livello stava a (25,25) sulla base; ruotata a destra: (100-25, 25)
        x, y = self.livello.su_base(50, 50)
        self.assertAlmostEqual(x, 75, delta=0.6)
        self.assertAlmostEqual(y, 25, delta=0.6)

    def test_applica_crea_asset_e_reparti(self):
        a, b = self._admin()
        with a, b:
            resp = self.client.post(self.url + "?leggi=1", {
                "action": "applica_proposte", "layout_id": self.livello.id,
                "crea": ["1", "2"],
                "crea_sigla_1": "C9", "crea_nome_1": "Chiller C9", "crea_categoria_1": self.cat.id,
                "crea_x_1": "12.5", "crea_y_1": "20", "crea_costruttore_1": "AERMEC", "crea_descrizione_1": "Tetto",
                "crea_sigla_2": "C1", "crea_nome_2": "Doppione", "crea_categoria_2": self.cat.id,
                "crea_x_2": "1", "crea_y_2": "1",
                "reparto": ["1"], "rep_nome_1": "ALC", "rep_x_1": "5", "rep_y_1": "5", "rep_w_1": "10", "rep_h_1": "8",
            })
        self.assertEqual(resp.status_code, 302)
        nuovo = Asset.objects.get(internal_number="Int.C9")
        self.assertEqual((nuovo.asset_category, nuovo.manufacturer), (self.cat, "AERMEC"))
        self.assertEqual(PlantLayoutMarker.objects.get(layout=self.livello, asset=nuovo).x_percent, Decimal("12.50"))
        self.assertFalse(Asset.objects.filter(name="Doppione").exists())  # Int.C1 c'è già
        self.assertTrue(PlantLayoutArea.objects.filter(layout=self.livello, name="ALC").exists())

    def test_pagina_lettura_mostra_legenda_e_da_creare(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        a, b = self._admin()
        with a, b:
            pdf = SimpleUploadedFile("clima.pdf", _pdf_servizio(), content_type="application/pdf")
            resp = self.client.post(self.url + "?leggi=1", {"action": "leggi_planimetria", "layout_id": self.livello.id, "pdf": pdf})
        self.assertContains(resp, "Legenda letta")
        self.assertContains(resp, "Sulla pianta ma non in anagrafica")
        self.assertContains(resp, 'name="crea_sigla_')
