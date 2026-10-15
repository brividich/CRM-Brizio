"""Centro guide: contenuti coerenti, collegamenti validi, parti per amministratori riservate."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from core import guide_moduli
from core.models import UserOnboarding
from core.views_guide import _url_sicuro

_BLOCCHI = {"p", "passi", "ul", "nota", "def"}


class GuideContenutiTests(TestCase):
    def test_ogni_guida_ha_struttura_e_collegamenti_validi(self):
        slugs = set()
        for guida in guide_moduli.tutte():
            with self.subTest(guida=guida["slug"]):
                self.assertNotIn(guida["slug"], slugs)
                slugs.add(guida["slug"])
                self.assertIn(guida["area"], guide_moduli.AREE)
                self.assertTrue(guida["sintesi"])
                self.assertTrue(guida["uso"], "manca la parte «Come si usa»")
                self.assertTrue(_url_sicuro(guida["url"]), f"rotta inesistente: {guida['url']}")
                for etichetta, nome, *query in guida["dettaglio"]:
                    self.assertTrue(_url_sicuro(nome, query[0] if query else ""), f"guida di dettaglio inesistente: {nome}")
                for vista, _etichetta in guide_moduli.VISTE:
                    for capitolo in guide_moduli.capitoli(guida, vista):
                        self.assertTrue(capitolo["id"] and capitolo["titolo"])
                        for tipo, _contenuto in capitolo["blocchi"]:
                            self.assertIn(tipo, _BLOCCHI)
        self.assertIn("emergenza", slugs)

    def test_ogni_guida_non_admin_ha_le_tre_parti(self):
        for guida in guide_moduli.tutte():
            if guida["solo_admin"]:
                continue
            with self.subTest(guida=guida["slug"]):
                self.assertTrue(guida["admin"], "manca la parte «Amministratore e configurazione»")

    def test_pulsante_guida_trova_il_modulo_dal_percorso(self):
        self.assertEqual(guide_moduli.per_path("/assenze/calendario")["slug"], "assenze")
        self.assertEqual(guide_moduli.per_path("/dpi/nuova/")["slug"], "dpi")
        self.assertEqual(guide_moduli.per_path("/admin-portale/accessi/")["slug"], "amministrazione")
        self.assertIsNone(guide_moduli.per_path("/nessun-modulo/"))


class GuideViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser(username="adm", email="a@example.com", password="x")
        self.utente = user_model.objects.create_user(username="utente", email="u@example.com", password="x")
        UserOnboarding.objects.create(user=self.utente, completed=True)

    def test_indice_e_tutte_le_viste_per_amministratore(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("guide_indice"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Manuale di emergenza")
        for guida in guide_moduli.tutte():
            for vista, _etichetta in guide_moduli.VISTE:
                if vista != "uso" and (guida["solo_admin"] or not guida[vista]):
                    continue
                with self.subTest(guida=guida["slug"], vista=vista):
                    resp = self.client.get(reverse("guida_modulo", args=[guida["slug"]]), {"vista": vista})
                    self.assertEqual(resp.status_code, 200)
                    for capitolo in guide_moduli.capitoli(guida, vista):
                        self.assertContains(resp, escape(capitolo["titolo"]))

    def test_pdf(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("guida_modulo", args=["assenze"]), {"vista": "admin", "pdf": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_utente_vede_solo_come_si_usa(self):
        self.client.force_login(self.utente)
        resp = self.client.get(reverse("guida_modulo", args=["assenze"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Chiedere ferie o un permesso")
        self.assertNotContains(resp, "?vista=admin")
        self.assertEqual(self.client.get(reverse("guida_modulo", args=["assenze"]), {"vista": "admin"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("guida_modulo", args=["emergenza"])).status_code, 403)
        indice = self.client.get(reverse("guide_indice"))
        self.assertEqual(indice.status_code, 200)
        self.assertNotContains(indice, "Manuale di emergenza")

    def test_guida_inesistente_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("guida_modulo", args=["non-esiste"])).status_code, 404)

    def test_barra_in_alto_porta_alla_guida_del_modulo(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("guide_indice"))
        self.assertContains(resp, "nav-icon-guida")

    def test_assistente_ai_parte_uso_per_tutti_parte_admin_solo_amministratori(self):
        from django.test import RequestFactory

        from ai_assistant import guide_portale

        centro = {g.slug: g for g in guide_portale.guide() if g.slug.startswith("centro-")}
        self.assertNotIn("centro-timbri", centro)  # ha già la sua guida di dettaglio nel registro
        uso = centro["centro-assenze"].testo()
        self.assertIn("Chiedere ferie o un permesso", uso)
        self.assertNotIn("Convivenza con SharePoint", uso)
        admin = centro["centro-assenze-admin"]
        self.assertTrue(admin.solo_admin)
        self.assertIn("Convivenza con SharePoint", admin.testo())
        self.assertIn("La richiesta va al capo sbagliato", admin.testo())
        self.assertIn("centro-timbri-admin", centro)
        self.assertTrue(centro["centro-emergenza"].solo_admin)

        factory = RequestFactory()
        richiesta = factory.get("/assistente-ai/")
        richiesta.user = self.utente
        per_utente = guide_portale.guide_consentite(richiesta)
        self.assertIn("centro-assenze", per_utente)
        self.assertNotIn("centro-assenze-admin", per_utente)
        self.assertNotIn("centro-emergenza", per_utente)
        richiesta.user = self.admin
        per_admin = guide_portale.guide_consentite(richiesta)
        self.assertIn("centro-assenze-admin", per_admin)
        self.assertIn("centro-emergenza", per_admin)
