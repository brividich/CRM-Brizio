"""Tessere del magazzino DPI cliccabili: stesso insieme e stesso numero nella pagina di destinazione."""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import magazzino
from .models import CategoriaDPI, ModelloDPI, MovimentoMagazzinoDPI, TipoDPI

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MagazzinoKpiLinkTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser(username="dpi-kpi", password="x", email="k@y.z"))
        cat = CategoriaDPI.objects.create(nome="Mani", icona_emoji="gloves", vita_utile_giorni=180)
        tipo = TipoDPI.objects.create(categoria=cat, nome="Guanti")
        self.a = ModelloDPI.objects.create(tipo=tipo, codice="GK-1", nome="Guanto A", scorta_minima=10)
        self.b = ModelloDPI.objects.create(tipo=tipo, codice="GK-2", nome="Guanto B", scorta_minima=0)
        self.c = ModelloDPI.objects.create(tipo=tipo, codice="GK-3", nome="Guanto C", scorta_minima=2)
        oggi = date.today()
        magazzino.carica_ddt(self.a, 8, data=oggi - timedelta(days=5))     # sotto scorta
        magazzino.carica_ddt(self.c, 50, data=oggi - timedelta(days=400))  # carico fuori dal periodo
        MovimentoMagazzinoDPI.objects.create(modello=self.c, tipo="SCARICO", quantita=-3, data=oggi - timedelta(days=10))
        MovimentoMagazzinoDPI.objects.create(modello=self.c, tipo="SCARICO", quantita=-4, data=oggi - timedelta(days=200))

    def test_report_tessere_href_e_conteggi(self):
        dati = magazzino.report(90)
        html = self.client.get(reverse("dpi:magazzino_report")).content.decode()
        base = reverse("dpi:magazzino")
        da = dati["da"].isoformat()
        self.assertIn(f'href="{base}?tipo=SCARICO&amp;da={da}#movimenti"', html)
        self.assertIn(f'href="{base}?tipo=CARICO&amp;da={da}#movimenti"', html)
        self.assertIn(f'href="{base}?stato=sotto#giacenze"', html)
        self.assertIn(f'href="{base}?stato=esaurito#giacenze"', html)

        r = self.client.get(base, {"tipo": "SCARICO", "da": da})
        self.assertEqual(r.context["movimenti_pezzi"], dati["consumati"])
        self.assertEqual(dati["consumati"], 3)
        r = self.client.get(base, {"tipo": "CARICO", "da": da})
        self.assertEqual(r.context["movimenti_pezzi"], dati["caricati"])
        self.assertEqual(dati["caricati"], 8)
        r = self.client.get(base, {"stato": "sotto"})
        self.assertEqual(len(r.context["righe"]), dati["sotto"])
        r = self.client.get(base, {"stato": "esaurito"})
        self.assertEqual(len(r.context["righe"]), dati["esauriti"])
        self.assertEqual(sum(x["giacenza"] for x in self.client.get(base).context["righe"]), dati["pezzi_totali"])

    def test_da_riordinare_della_home_coincide_con_il_filtro(self):
        r = self.client.get(reverse("dpi:magazzino"), {"stato": "da_riordinare"})
        self.assertEqual(len(r.context["righe"]), magazzino.da_riordinare())
        self.assertEqual(magazzino.da_riordinare(), 2)  # A sotto scorta, B esaurito

    def test_magazzino_tessera_pezzi_e_link(self):
        html = self.client.get(reverse("dpi:magazzino")).content.decode()
        self.assertIn(f'href="{reverse("dpi:magazzino")}#giacenze"', html)
        self.assertIn('id="giacenze"', html)
