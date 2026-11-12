"""Menu del SOC: Dispositivi su una riga, pagine accorpate in Patch e Vulnerabilità con la terza riga."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserOnboarding


class MenuGruppiTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(username="menu_gruppi", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)

    def _sottomenu(self, route):
        html = self.client.get(reverse(f"security:{route}")).content.decode()
        sub = html.split('class="soc-subnav"', 1)[1].split("</nav>", 1)[0]
        terza = html.split('class="soc-subsub"', 1)[1].split("</nav>", 1)[0] if 'class="soc-subsub"' in html else ""
        return sub, terza

    def test_dispositivi_sette_voci(self):
        sub, terza = self._sottomenu("pc_copertura")
        self.assertEqual(sub.count("<a "), 7)
        for voce in ("Elenco", "Backup", "Patch", "Software", "Rete (IP)", "Vulnerabilità", "Accessi VPN"):
            self.assertIn(f">{voce}</a>", sub)
        self.assertEqual(terza, "")  # niente terza riga fuori dai gruppi

    def test_patch_accorpate(self):
        for route, attiva in (("watchguard_pc", "Da installare e protezione"), ("watchguard_patch_installate", "Installate"),
                              ("watchguard_task", "Installazioni da console"), ("watchguard_patch_tempi", "Tempi")):
            sub, terza = self._sottomenu(route)
            self.assertIn('class="active" aria-current="page">Patch</a>', sub, route)
            self.assertIn(f'class="active" aria-current="page">{attiva}</a>', terza, route)
            self.assertEqual(terza.count("<a "), 4)

    def test_vulnerabilita_accorpate(self):
        for route, attiva in (("vulnerabilities", "CVE sui PC"), ("cve_correzioni", "Correzioni"),
                              ("accettazioni_rischio", "Rischi accettati"), ("dipendenze_portale", "Librerie del portale")):
            sub, terza = self._sottomenu(route)
            self.assertIn('class="active" aria-current="page">Vulnerabilità</a>', sub, route)
            self.assertIn(f'class="active" aria-current="page">{attiva}</a>', terza, route)
