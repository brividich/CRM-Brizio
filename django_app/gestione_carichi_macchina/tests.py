"""Smoke test del modello dati (PASSO 1).

Verifica che lo schema migri e funzioni su sqlite e che l'aggancio all'asset e i
vincoli di unicita' chiave siano corretti. I test sull'importer arrivano al PASSO 2.
"""
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from assets.models import Asset

from .models import (
    FamigliaAlias,
    FamigliaPezzo,
    Macchina,
    MacchinaAlias,
    Pianificazione,
)


def _make_asset(tag="CNC-DM3-12280000463", name="DM3 - DMG Mori DMC 85"):
    return Asset.objects.create(asset_tag=tag, name=name, asset_type=Asset.TYPE_WORK_MACHINE)


class ModelloDatiTest(TestCase):
    def test_macchina_legge_identita_da_asset(self):
        asset = _make_asset()
        macchina = Macchina.objects.create(asset=asset, categoria=Macchina.CAT_5AXIS)
        self.assertEqual(macchina.codice, "CNC-DM3-12280000463")
        self.assertEqual(macchina.descrizione, "DM3 - DMG Mori DMC 85")
        self.assertEqual(macchina.stato_pianificazione, Macchina.STATO_ATTIVA)
        self.assertEqual(macchina.ore_giorno_disponibili, Decimal("8.0"))

    def test_un_solo_profilo_per_asset(self):
        asset = _make_asset()
        Macchina.objects.create(asset=asset, categoria=Macchina.CAT_5AXIS)
        with self.assertRaises(IntegrityError):
            Macchina.objects.create(asset=asset, categoria=Macchina.CAT_TORNI)

    def test_codice_foglio_alias_univoco(self):
        m1 = Macchina.objects.create(asset=_make_asset(), categoria=Macchina.CAT_5AXIS)
        m2 = Macchina.objects.create(
            asset=_make_asset(tag="CNC-DM11-12280009603", name="DM11 - DMG Mori DMC 85"),
            categoria=Macchina.CAT_5AXIS,
        )
        MacchinaAlias.objects.create(macchina=m1, codice_foglio="DM3")
        with self.assertRaises(IntegrityError):
            MacchinaAlias.objects.create(macchina=m2, codice_foglio="DM3")

    def test_famiglia_alias_univoco(self):
        f1 = FamigliaPezzo.objects.create(nome="gimbal")
        f2 = FamigliaPezzo.objects.create(nome="sombrero")
        FamigliaAlias.objects.create(famiglia=f1, alias="gimbals")
        with self.assertRaises(IntegrityError):
            FamigliaAlias.objects.create(famiglia=f2, alias="gimbals")

    def test_pianificazione_collegata(self):
        macchina = Macchina.objects.create(asset=_make_asset(), categoria=Macchina.CAT_5AXIS)
        famiglia = FamigliaPezzo.objects.create(nome="gimbal")
        p = Pianificazione.objects.create(
            macchina=macchina,
            data="2026-06-23",
            famiglia=famiglia,
            qta=8,
            ore=Decimal("33.0"),
            fase=Pianificazione.FASE_FIN,
            testo_originale="8 gimbal 6F (33h) fin",
        )
        self.assertEqual(p.stato, Pianificazione.STATO_PIANIFICATA)
        self.assertEqual(p.turno, Pianificazione.TURNO_GIORNO)
        self.assertEqual(macchina.pianificazioni.count(), 1)
