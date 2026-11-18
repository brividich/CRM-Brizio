"""Tessere del glossario cliccabili: elenco filtrato per stato con lo stesso numero."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Termine

User = get_user_model()


class GlossarioKpiLinkTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username="gl_kpi", password="x", is_superuser=True, is_staff=True))
        self.base = {s: Termine.objects.filter(stato=s).count() for s in (Termine.VALIDATO, Termine.BOZZA)}
        for i, stato in enumerate([Termine.VALIDATO, Termine.VALIDATO, Termine.BOZZA, Termine.DEPRECATO]):
            Termine.objects.create(termine=f"termine sintetico {i}", categoria="lavorazione",
                                   definizione="Definizione sintetica.", stato=stato)

    def test_tessere_href_e_conteggi(self):
        url = reverse("glossario_tecnico:index")
        r = self.client.get(url)
        conteggi = r.context["conteggi"]
        self.assertContains(r, f'href="{url}?stato=validato"')
        self.assertContains(r, f'href="{url}?stato=bozza"')
        self.assertContains(r, f'href="{reverse("glossario_tecnico:revisione")}#gl-proposte"')
        for stato in ("validato", "bozza"):
            dest = self.client.get(url, {"stato": stato})
            self.assertEqual(dest.context["pagina"].paginator.count, conteggi[stato], stato)
        self.assertEqual(conteggi.get("validato", 0) - self.base["validato"], 2)
        self.assertEqual(conteggi.get("bozza", 0) - self.base["bozza"], 1)

    def test_revisione_mostra_il_totale_delle_proposte(self):
        r = self.client.get(reverse("glossario_tecnico:revisione"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("proposte_totale", r.context)
        self.assertContains(r, 'id="gl-proposte"')
