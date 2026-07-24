"""Skill Matrix — verifica copertura minima AS/EN 9100 (1.13).

Soglie **configurabili** (min. N abilitati ≥ livello X) su asset/processo/ruolo
critico, attribuibili a una certificazione. La vista confronta soglia vs
abilitati operativi (riuso resolver skill matrix) ed evidenzia i gap. Gli
standard aeronautici (AS/EN 9100, Nadcap, EN 4179) NON dettano una percentuale
fissa: le soglie sono definite dall'organizzazione o dal flow-down cliente.
Nessun dato reale.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset

from .models import (
    AbilitazioneMacchina,
    AbilitazioneProcesso,
    ClienteQualificante,
    CompetenzaSkm,
    LivelloSkm,
    ProcessoQualificato,
    SkillMatrixConfig,
    SogliaCopertura,
)
from .services import skillmatrix_copertura as C


class SogliaModelTests(TestCase):
    def test_richiede_almeno_un_target(self):
        s = SogliaCopertura(nome="Vuota", minimo_abilitati=2)
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_valida_con_asset(self):
        a = Asset.objects.create(asset_tag="CNC-CV", name="M", asset_type="CNC")
        s = SogliaCopertura(nome="Con asset", asset=a, minimo_abilitati=2,
                            livello_minimo=LivelloSkm.AUTONOMO)
        s.full_clean()  # non solleva


class CoperturaAssetTests(TestCase):
    def setUp(self):
        SkillMatrixConfig.get_instance()
        self.a = Asset.objects.create(asset_tag="CNC-CA", name="Macchina CA", asset_type="CNC")
        CompetenzaSkm.objects.create(competenza_key="CA", tipo="macchina", asset=self.a)
        for lid in (10, 11):
            AbilitazioneMacchina.objects.create(
                legacy_anagrafica_id=lid, asset=self.a, livello=LivelloSkm.AUTONOMO)
        # uno sotto soglia (INTERMEDIO) non conta come operativo a livello U
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=12, asset=self.a, livello=LivelloSkm.INTERMEDIO)

    def test_coperta_quando_sufficiente(self):
        s = SogliaCopertura.objects.create(
            nome="Copertura CNC", asset=self.a, minimo_abilitati=2,
            livello_minimo=LivelloSkm.AUTONOMO, certificazione="AS/EN 9100")
        r = C.valuta_soglia(s)
        self.assertEqual(r["disponibili"], 2)
        self.assertEqual(r["gap"], 0)
        self.assertTrue(r["coperta"])

    def test_gap_quando_insufficiente(self):
        s = SogliaCopertura.objects.create(
            nome="Copertura alta", asset=self.a, minimo_abilitati=3,
            livello_minimo=LivelloSkm.AUTONOMO)
        r = C.valuta_soglia(s)
        self.assertEqual(r["disponibili"], 2)
        self.assertEqual(r["gap"], 1)
        self.assertFalse(r["coperta"])

    def test_livello_minimo_intermedio_conta_di_piu(self):
        s = SogliaCopertura.objects.create(
            nome="Copertura L", asset=self.a, minimo_abilitati=3,
            livello_minimo=LivelloSkm.INTERMEDIO)
        r = C.valuta_soglia(s)
        # 2 AUTONOMO + 1 INTERMEDIO = 3 ≥ L
        self.assertEqual(r["disponibili"], 3)
        self.assertTrue(r["coperta"])


class CoperturaProcessoTests(TestCase):
    def test_conta_abilitazioni_processo_attive(self):
        cli = ClienteQualificante.objects.create(nome="Cli CP")
        p = ProcessoQualificato.objects.create(nome="Proc CP", cliente=cli)
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=1, processo=p, stato=AbilitazioneProcesso.STATO_ATTIVA)
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=2, processo=p, stato=AbilitazioneProcesso.STATO_ATTIVA)
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=3, processo=p, stato=AbilitazioneProcesso.STATO_REVOCATA)
        s = SogliaCopertura.objects.create(
            nome="Copertura processo", processo=p, minimo_abilitati=2)
        r = C.valuta_soglia(s)
        self.assertEqual(r["disponibili"], 2)  # solo le attive
        self.assertTrue(r["coperta"])


class CoperturaBatchTests(TestCase):
    def test_valuta_copertura_solo_attive(self):
        a = Asset.objects.create(asset_tag="CNC-BB", name="BB", asset_type="CNC")
        CompetenzaSkm.objects.create(competenza_key="BB", tipo="macchina", asset=a)
        SogliaCopertura.objects.create(nome="Attiva", asset=a, minimo_abilitati=1)
        SogliaCopertura.objects.create(nome="Disattiva", asset=a, minimo_abilitati=1, attiva=False)
        out = C.valuta_copertura()
        nomi = {r["soglia"].nome for r in out}
        self.assertIn("Attiva", nomi)
        self.assertNotIn("Disattiva", nomi)


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class CoperturaViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("covadmin", "cov@example.com", "pass12345")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:skm_copertura")

    def test_render_vuoto(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "copertura minima")

    def test_render_con_gap(self):
        a = Asset.objects.create(asset_tag="CNC-VG", name="VG", asset_type="CNC")
        CompetenzaSkm.objects.create(competenza_key="VG", tipo="macchina", asset=a)
        SogliaCopertura.objects.create(
            nome="Copertura VG", asset=a, minimo_abilitati=2,
            livello_minimo=LivelloSkm.AUTONOMO, certificazione="AS/EN 9100")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Copertura VG")
        self.assertContains(resp, "Scoperta")  # 0 disponibili < 2 richiesti
