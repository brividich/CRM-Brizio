"""Test modello Skill Matrix MOD.187 (F1).

Copre: creazione, vincoli unique, scala/ordinale, ``is_operational`` (soglia,
CAR, in_lista, stato), singleton config, derivazione stato continuità.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from assets.models import Asset

from .models import (
    AbilitazioneMacchina,
    CompetenzaSkm,
    ContinuitaOperativa,
    LivelloSkm,
    ProcessoCriticoContinuita,
    SkillMatrixConfig,
    SkmCorsiAttivati,
    ordinale_livello,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class SkillMatrixModelTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="CNC-DM3-001", name="DM3 - DMG DMC 85")
        self.asset2 = Asset.objects.create(asset_tag="CNC-MZ5-002", name="MZ5 - MAZAK FH6800")

    # ── Scala ──────────────────────────────────────────────────────────────
    def test_ordinale_scala(self):
        self.assertLess(ordinale_livello("I"), ordinale_livello("L"))
        self.assertLess(ordinale_livello("L"), ordinale_livello("U"))
        self.assertLess(ordinale_livello("U"), ordinale_livello("O"))
        self.assertEqual(ordinale_livello(""), 0)
        self.assertEqual(ordinale_livello(None), 0)

    # ── Config singleton ─────────────────────────────────────────────────────
    def test_config_singleton(self):
        c1 = SkillMatrixConfig.get_instance()
        c2 = SkillMatrixConfig.get_instance()
        self.assertEqual(c1.pk, c2.pk)
        self.assertEqual(c1.pk, 1)
        self.assertEqual(c1.soglia_operativa, LivelloSkm.AUTONOMO)
        self.assertEqual(c1.etichetta(LivelloSkm.AUTONOMO), "Autonomo")

    # ── Abilitazione + vincolo unique ───────────────────────────────────────
    def test_abilitazione_unique_persona_asset(self):
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=10, asset=self.asset, livello=LivelloSkm.AUTONOMO,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AbilitazioneMacchina.objects.create(
                    legacy_anagrafica_id=10, asset=self.asset, livello=LivelloSkm.INTERMEDIO,
                )
        # Stessa persona, asset diverso → ammesso.
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=10, asset=self.asset2, livello=LivelloSkm.INTERMEDIO,
        )
        self.assertEqual(AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=10).count(), 2)

    # ── is_operational ───────────────────────────────────────────────────────
    def test_is_operational_soglia(self):
        ab_u = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO,
        )
        ab_l = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=2, asset=self.asset, livello=LivelloSkm.INTERMEDIO,
        )
        self.assertTrue(ab_u.is_operational)   # U >= soglia U
        self.assertFalse(ab_l.is_operational)  # L < soglia U

    def test_is_operational_car_escluso(self):
        ab = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=3, asset=self.asset, livello=LivelloSkm.ESPERTO,
            conteggiabile_nel_carico=False,  # CAR
        )
        self.assertFalse(ab.is_operational)

    def test_is_operational_non_in_lista_o_sospesa(self):
        ab_fuori = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=4, asset=self.asset, livello=LivelloSkm.AUTONOMO,
            in_lista=False,
        )
        ab_sosp = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=5, asset=self.asset2, livello=LivelloSkm.AUTONOMO,
            stato=AbilitazioneMacchina.STATO_SOSPESA,
        )
        self.assertFalse(ab_fuori.is_operational)
        self.assertFalse(ab_sosp.is_operational)

    def test_is_operational_soglia_configurabile(self):
        ab_l = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=6, asset=self.asset, livello=LivelloSkm.INTERMEDIO,
        )
        self.assertFalse(ab_l.is_operational)
        cfg = SkillMatrixConfig.get_instance()
        cfg.soglia_operativa = LivelloSkm.INTERMEDIO
        cfg.save()
        self.assertTrue(ab_l.is_operational)  # ora L >= soglia L

    def test_sotto_livello_richiesto(self):
        ab = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=7, asset=self.asset, livello=LivelloSkm.INTERMEDIO,
            livello_richiesto=LivelloSkm.AUTONOMO,
        )
        self.assertTrue(ab.sotto_livello_richiesto)
        ab.livello = LivelloSkm.ESPERTO
        self.assertFalse(ab.sotto_livello_richiesto)

    # ── Continuità ───────────────────────────────────────────────────────────
    def test_continuita_stati(self):
        # NB: "CND-PT" è seminato dalla migration 0073 → uso un nome dedicato al test.
        proc = ProcessoCriticoContinuita.objects.create(
            nome="CND-PT-TEST", finestra_mesi=12, preavviso_mesi=9,
        )
        cont = ContinuitaOperativa.objects.create(legacy_anagrafica_id=1, processo=proc)
        oggi = date(2026, 6, 25)
        # na: nessuna esecuzione
        self.assertEqual(cont.stato(oggi=oggi), ContinuitaOperativa.STATO_NA)
        # mantenuta: eseguito di recente
        cont.ultima_esecuzione = oggi - timedelta(days=30)
        self.assertEqual(cont.stato(oggi=oggi), ContinuitaOperativa.STATO_MANTENUTA)
        # in_scadenza: oltre preavviso (9 mesi) ma entro finestra (12 mesi)
        cont.ultima_esecuzione = oggi - timedelta(days=int(10 * 30.44))
        self.assertEqual(cont.stato(oggi=oggi), ContinuitaOperativa.STATO_IN_SCADENZA)
        # persa: oltre finestra (12 mesi)
        cont.ultima_esecuzione = oggi - timedelta(days=int(13 * 30.44))
        self.assertEqual(cont.stato(oggi=oggi), ContinuitaOperativa.STATO_PERSA)

    def test_continuita_override_finestra(self):
        proc = ProcessoCriticoContinuita.objects.create(nome="Test override", finestra_mesi=6)
        cont = ContinuitaOperativa.objects.create(
            legacy_anagrafica_id=2, processo=proc,
            ultima_esecuzione=date(2026, 6, 25) - timedelta(days=int(7 * 30.44)),
        )
        # 7 mesi > finestra 6 → persa (anche se config default è 12)
        self.assertEqual(cont.stato(oggi=date(2026, 6, 25)), ContinuitaOperativa.STATO_PERSA)

    # ── Catalogo + contatore ─────────────────────────────────────────────────
    def test_competenza_key_unique(self):
        CompetenzaSkm.objects.create(competenza_key="DM3", tipo=CompetenzaSkm.TIPO_MACCHINA)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CompetenzaSkm.objects.create(competenza_key="DM3", tipo=CompetenzaSkm.TIPO_MACCHINA)

    def test_corsi_attivati_unique(self):
        SkmCorsiAttivati.objects.create(legacy_anagrafica_id=1, numero=3)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SkmCorsiAttivati.objects.create(legacy_anagrafica_id=1, numero=5)
