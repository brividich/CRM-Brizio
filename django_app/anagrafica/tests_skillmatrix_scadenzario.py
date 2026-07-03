"""F10 — scadenzario abilitazioni macchina + avvio refresh HR->CAR."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset

from .models import (
    AbilitazioneMacchina, CampagnaRefresh, CompetenzaSkm, LivelloSkm,
    Reparto, SkillMatrixConfig, SubnavLinkAnagrafica,
)

User = get_user_model()
OGGI = date(2026, 7, 3)


class ConfigPreavvisoTests(TestCase):
    def test_default_preavviso_refresh_giorni(self):
        cfg = SkillMatrixConfig.get_instance()
        self.assertEqual(cfg.preavviso_refresh_giorni, 60)

    def test_form_salva_preavviso(self):
        from .forms import SkillMatrixConfigForm
        cfg = SkillMatrixConfig.get_instance()
        data = {
            "soglia_operativa": "U", "regola_multivoce": "MIN", "soglia_uomo_solo": 2,
            "finestra_continuita_mesi": 12, "preavviso_continuita_mesi": 9,
            "periodicita_refresh_mesi": 6, "preavviso_refresh_giorni": 45,
            "etichetta_i": "I", "etichetta_l": "L", "etichetta_u": "U", "etichetta_o": "O",
        }
        form = SkillMatrixConfigForm(data, instance=cfg)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        cfg.refresh_from_db()
        self.assertEqual(cfg.preavviso_refresh_giorni, 45)


class ScadenzarioRepartiTests(TestCase):
    def setUp(self):
        from .services import skillmatrix_refresh as R
        self.R = R
        self.a1 = Asset.objects.create(asset_tag="CNC-A-1", name="Alfa", asset_type="CNC", reparto="Officina")
        self.a2 = Asset.objects.create(asset_tag="CNC-B-1", name="Beta", asset_type="CNC", reparto="Montaggio")
        CompetenzaSkm.objects.create(competenza_key="A1", display="A1", tipo="macchina", asset=self.a1)
        CompetenzaSkm.objects.create(competenza_key="B1", display="B1", tipo="macchina", asset=self.a2)

    def test_reparto_scaduto_in_arrivo_ok(self):
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.a1, livello=LivelloSkm.AUTONOMO,
            prossima_revisione=OGGI - timedelta(days=5))
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=2, asset=self.a2, livello=LivelloSkm.AUTONOMO,
            prossima_revisione=OGGI + timedelta(days=10))
        rows = self.R.scadenzario_reparti(oggi=OGGI)
        by = {r["reparto"]: r for r in rows}
        self.assertEqual(by["Officina"]["stato"], "scaduto")
        self.assertEqual(by["Officina"]["n_scadute"], 1)
        self.assertEqual(by["Montaggio"]["stato"], "in_arrivo")
        self.assertEqual(by["Montaggio"]["n_in_arrivo"], 1)
        self.assertEqual(rows[0]["reparto"], "Officina")

    def test_reparto_ok_e_non_in_lista_escluso(self):
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=3, asset=self.a1, livello=LivelloSkm.AUTONOMO,
            prossima_revisione=OGGI + timedelta(days=200))
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=4, asset=self.a2, livello=LivelloSkm.AUTONOMO,
            in_lista=False, prossima_revisione=OGGI - timedelta(days=5))
        by = {r["reparto"]: r for r in self.R.scadenzario_reparti(oggi=OGGI)}
        self.assertEqual(by["Officina"]["stato"], "ok")
        self.assertNotIn("Montaggio", by)


class AvviaRefreshTests(TestCase):
    def setUp(self):
        from .services import skillmatrix_refresh as R
        self.R = R
        self.asset = Asset.objects.create(asset_tag="CNC-C-1", name="Gamma", asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="C1", display="C1", tipo="macchina", asset=self.asset)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO)
        Reparto.objects.create(nome="Officina", caporeparto_legacy_id=99)

    def _notifiche_car(self):
        from core.models import Notifica
        return Notifica.objects.filter(legacy_user_id=99, tipo="skm_refresh")

    def test_avvia_apre_campagna_e_notifica_una_volta(self):
        camp, created = self.R.avvia_refresh(reparto="Officina", avviatore_ruolo="HR")
        self.assertTrue(created)
        self.assertEqual(camp.stato, CampagnaRefresh.STATO_APERTA)
        self.assertEqual(self._notifiche_car().count(), 1)
        camp2, created2 = self.R.avvia_refresh(reparto="Officina", avviatore_ruolo="HR")
        self.assertFalse(created2)
        self.assertEqual(camp2.id, camp.id)
        self.assertEqual(self._notifiche_car().count(), 1)

    def test_apri_campagna_retrocompatibile(self):
        c = self.R.apri_campagna("Officina")
        self.assertEqual(c.reparto, "Officina")

    def test_risolvi_car(self):
        car_id, email = self.R._risolvi_car("Officina")
        self.assertEqual(car_id, 99)


class CampagneDaGestireTests(TestCase):
    def setUp(self):
        from .services import skillmatrix_refresh as R
        self.R = R
        self.asset = Asset.objects.create(asset_tag="CNC-D-1", name="Delta", asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="D1", display="D1", tipo="macchina", asset=self.asset)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO)
        Reparto.objects.create(nome="Officina", caporeparto_legacy_id=99)

    def test_solo_campagne_aperte_del_car(self):
        self.assertEqual(self.R.campagne_da_gestire(99), [])
        self.R.avvia_refresh(reparto="Officina", avviatore_ruolo="HR")
        items = self.R.campagne_da_gestire(99)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["reparto"], "Officina")
        self.assertEqual(items[0]["n_da_rivalutare"], 1)
        self.assertEqual(self.R.campagne_da_gestire(100), [])
