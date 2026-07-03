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


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class ScadenzarioViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("scadm", "sc@example.com", "pass12345")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:skm_scadenzario")
        self.asset = Asset.objects.create(asset_tag="CNC-E-1", name="Epsilon", asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="E1", display="E1", tipo="macchina", asset=self.asset)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO,
            prossima_revisione=OGGI - timedelta(days=3))
        Reparto.objects.create(nome="Officina", caporeparto_legacy_id=99)

    def test_get_render(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Officina")

    def test_export_csv(self):
        resp = self.client.get(self.url, {"format": "csv"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("Officina".encode("utf-8"), resp.content)

    def test_post_avvia_apre_campagna(self):
        resp = self.client.post(self.url, {"azione": "avvia", "reparto": "Officina"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CampagnaRefresh.objects.filter(
            reparto="Officina", stato=CampagnaRefresh.STATO_APERTA).exists())

    def test_accesso_negato(self):
        self.client.logout()
        nobody = User.objects.create_user("nob10", "nob10@example.com", "pass12345")
        self.client.force_login(nobody)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)


class AclBindingTests(TestCase):
    def test_binding_scadenzario_manage(self):
        from .acl_bootstrap import _bootstrap_skillmatrix_canonical, PERM_SKM_MANAGE
        from core.models import RoutePermissionBinding
        _bootstrap_skillmatrix_canonical()
        b = RoutePermissionBinding.objects.filter(route_name="anagrafica:skm_scadenzario").first()
        self.assertIsNotNone(b)
        self.assertEqual(b.permission_id, PERM_SKM_MANAGE)


class ScadenzarioNavTests(TestCase):
    def test_voce_menu_scadenzario(self):
        link = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:skm_scadenzario").first()
        self.assertIsNotNone(link)
        self.assertEqual(link.gruppo, "Skill Matrix")


class CoseDaGestireHelperTests(TestCase):
    def setUp(self):
        from .services import skillmatrix_refresh as R
        self.asset = Asset.objects.create(asset_tag="CNC-F-1", name="Zeta", asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="F1", display="F1", tipo="macchina", asset=self.asset)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO)
        Reparto.objects.create(nome="Officina", caporeparto_legacy_id=77)
        R.avvia_refresh(reparto="Officina", avviatore_ruolo="HR")

    def test_helper_mappa_item(self):
        from dashboard.views_mie_attivita import _my_skm_refresh
        items = _my_skm_refresh(77)
        self.assertEqual(len(items), 1)
        self.assertIn("Officina", items[0]["title"])
        self.assertIn("url", items[0])
        self.assertEqual(_my_skm_refresh(0), [])
