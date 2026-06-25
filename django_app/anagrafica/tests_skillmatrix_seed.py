"""Test F2a-UI — sync catalogo (CompetenzaSkm) + specchietto di validazione."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset

from .models import CompetenzaSkm
from .services.skillmatrix_seed import sincronizza_catalogo

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class SeedCatalogoTests(TestCase):
    def setUp(self):
        # DM3: il tag contiene il token DM3 → match esatto su asset_tag.
        Asset.objects.create(asset_tag="CNC-DM3-12280000463", name="DMG Mori DMC 85")

    def test_sincronizza_popola_catalogo(self):
        stats = sincronizza_catalogo()
        self.assertEqual(CompetenzaSkm.objects.count(), 84)
        self.assertEqual(stats["macchine"], 42)
        self.assertEqual(CompetenzaSkm.objects.filter(tipo="processo").count(), 41)
        self.assertEqual(CompetenzaSkm.objects.filter(tipo="contatore").count(), 1)
        dm3 = CompetenzaSkm.objects.get(competenza_key="DM3")
        self.assertEqual(dm3.match_confidenza, CompetenzaSkm.CONF_ESATTO)
        self.assertTrue(dm3.match_confermato)  # esatto = pre-approvato
        self.assertIsNotNone(dm3.asset_id)

    def test_idempotente_preserva_conferma_manuale(self):
        sincronizza_catalogo()
        mz5 = CompetenzaSkm.objects.get(competenza_key="MZ5")  # assente all'inizio
        self.assertFalse(mz5.match_confermato)
        asset = Asset.objects.create(asset_tag="MANUAL-MZ5", name="Mazak FH6800")
        mz5.asset = asset
        mz5.match_confermato = True
        mz5.save()
        # re-run: non deve sovrascrivere la decisione manuale né duplicare righe
        sincronizza_catalogo()
        self.assertEqual(CompetenzaSkm.objects.count(), 84)
        mz5.refresh_from_db()
        self.assertTrue(mz5.match_confermato)
        self.assertEqual(mz5.asset_id, asset.id)


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class ValidazioneViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("skm", "skm@example.com", "pass12345")
        self.client.force_login(self.user)
        Asset.objects.create(asset_tag="CNC-DM3-001", name="DM3 DMG")
        self.url = reverse("anagrafica:skm_match_validazione")

    def test_get_render_catalogo_vuoto(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Validazione abbinamento macchine")
        self.assertContains(resp, "Catalogo non ancora inizializzato")

    def test_sincronizza_poi_conferma(self):
        self.client.post(self.url, {"azione": "sincronizza"})
        self.assertEqual(CompetenzaSkm.objects.filter(tipo="macchina").count(), 42)
        cnv = CompetenzaSkm.objects.get(competenza_key="CNV")
        Asset.objects.create(asset_tag="MAN-CNV-1", name="CNS CNC KMV16")
        self.client.post(self.url, {
            "azione": "salva",
            f"asset_{cnv.id}": "MAN-CNV-1",
            f"decisione_{cnv.id}": "conferma",
        })
        cnv.refresh_from_db()
        self.assertTrue(cnv.match_confermato)
        self.assertEqual(cnv.asset.asset_tag, "MAN-CNV-1")

    def test_escludi_competenza(self):
        self.client.post(self.url, {"azione": "sincronizza"})
        hh = CompetenzaSkm.objects.get(competenza_key="HH")
        self.client.post(self.url, {
            "azione": "salva",
            f"decisione_{hh.id}": "escludi",
        })
        hh.refresh_from_db()
        self.assertTrue(hh.match_confermato)
        self.assertIsNone(hh.asset_id)

    def test_accesso_negato_senza_permesso(self):
        self.client.logout()
        other = User.objects.create_user("nobody", "n@example.com", "pass12345")
        self.client.force_login(other)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)  # redirect a index
