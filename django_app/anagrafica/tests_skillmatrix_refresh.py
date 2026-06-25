"""F6 — test refresh semestrale: campagna, rivalutazione, aggiunta, view, menu."""
from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset

from .models import (
    AbilitazioneMacchina, AbilitazioneMacchinaStorico, CampagnaRefresh,
    CompetenzaSkm, LivelloSkm, SubnavLinkAnagrafica,
)
from .services import skillmatrix_refresh as R

User = get_user_model()
OGGI = date(2026, 6, 25)


class RefreshServiceTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="CNC-RF-1", name="Macchina RF",
                                          asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="RF1", display="RF1", tipo="macchina", asset=self.asset)
        self.ab = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=10, asset=self.asset, livello=LivelloSkm.INTERMEDIO)

    def test_apri_campagna_idempotente(self):
        c1 = R.apri_campagna("Officina")
        c2 = R.apri_campagna("Officina")
        self.assertEqual(c1.id, c2.id)
        self.assertEqual(CampagnaRefresh.objects.filter(reparto="Officina").count(), 1)

    def test_abilitazioni_reparto(self):
        self.assertEqual(list(R.abilitazioni_reparto("Officina")), [self.ab])
        self.assertEqual(list(R.abilitazioni_reparto("Altro")), [])

    def test_conferma_invariato_scrive_storico_e_revisione(self):
        stats = R.applica_refresh(reparto="Officina",
                                  decisioni={self.ab.id: {"azione": "conferma", "livello": "L"}},
                                  oggi=OGGI)
        self.assertEqual(stats["confermate"], 1)
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "L")
        self.assertIsNotNone(self.ab.prossima_revisione)
        s = AbilitazioneMacchinaStorico.objects.get()
        self.assertEqual(s.fonte, AbilitazioneMacchinaStorico.FONTE_REFRESH)

    def test_modifica_livello(self):
        stats = R.applica_refresh(reparto="Officina",
                                  decisioni={self.ab.id: {"azione": "conferma", "livello": "U"}},
                                  oggi=OGGI)
        self.assertEqual(stats["modificate"], 1)
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "U")

    def test_rimuovi_dalla_lista(self):
        stats = R.applica_refresh(reparto="Officina",
                                  decisioni={self.ab.id: {"azione": "rimuovi"}}, oggi=OGGI)
        self.assertEqual(stats["rimosse"], 1)
        self.ab.refresh_from_db()
        self.assertFalse(self.ab.in_lista)

    def test_aggiunta_manuale(self):
        ab = R.aggiungi_abilitazione(legacy_anagrafica_id=20, asset_id=self.asset.id,
                                     livello="U", oggi=OGGI)
        self.assertTrue(ab.in_lista)
        self.assertEqual(ab.livello, "U")
        self.assertTrue(AbilitazioneMacchinaStorico.objects.filter(
            legacy_anagrafica_id=20, fonte=AbilitazioneMacchinaStorico.FONTE_REFRESH).exists())

    def test_aggiunta_livello_invalido(self):
        with self.assertRaises(ValueError):
            R.aggiungi_abilitazione(legacy_anagrafica_id=21, asset_id=self.asset.id, livello="X")

    def test_dry_run_non_scrive(self):
        stats = R.applica_refresh(reparto="Officina",
                                  decisioni={self.ab.id: {"azione": "conferma", "livello": "U"}},
                                  oggi=OGGI, apply=False)
        self.assertEqual(stats["modificate"], 1)
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "L")  # invariato
        self.assertEqual(AbilitazioneMacchinaStorico.objects.count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class RefreshViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("rfadmin", "rf@example.com", "pass12345")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:skm_refresh")
        self.asset = Asset.objects.create(asset_tag="CNC-RF-2", name="Macchina RF2",
                                          asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="RF2", display="RF2", tipo="macchina", asset=self.asset)
        self.ab = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=10, asset=self.asset, livello=LivelloSkm.AUTONOMO)

    def test_get_render_reparto(self):
        resp = self.client.get(self.url, {"reparto": "Officina"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Refresh semestrale")
        self.assertContains(resp, "Macchina RF2")

    def test_post_salva_modifica(self):
        resp = self.client.post(self.url, {
            "reparto": "Officina",
            f"azione_{self.ab.id}": "conferma",
            f"livello_{self.ab.id}": "O",
        })
        self.assertEqual(resp.status_code, 302)
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "O")

    def test_accesso_negato(self):
        self.client.logout()
        nobody = User.objects.create_user("nob3", "nob3@example.com", "pass12345")
        self.client.force_login(nobody)
        resp = self.client.get(self.url, {"reparto": "Officina"})
        self.assertEqual(resp.status_code, 302)


class RefreshNavTests(TestCase):
    def test_voce_menu_refresh(self):
        link = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:skm_refresh").first()
        self.assertIsNotNone(link)
        self.assertEqual(link.gruppo, "Skill Matrix")
