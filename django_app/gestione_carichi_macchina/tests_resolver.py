"""Test della cascata di mappatura codice-officina -> asset (funzioni pure)."""
from dataclasses import dataclass

from django.test import SimpleTestCase

from .asset_resolver import (
    CONF_ALTA,
    CONF_AMBIGUA,
    CONF_ASSENTE,
    CONF_MEDIA,
    IndiceAsset,
    normalizza_codice,
    normalizza_codice_attacco,
    risolvi,
)


@dataclass
class StubAsset:
    asset_tag: str
    name: str


# Dati che imitano i pattern reali osservati negli asset di produzione.
ASSETS = [
    StubAsset("CNC-DM3-12280000463", "DM3 - DMG Mori DMC 85"),     # tag+name concordano
    StubAsset("CNC-DM12-12670000953", "DM12-DMGMoriDMC160U"),      # tag+name concordano (no spazi)
    StubAsset("CNC-MZ2117322", "MZ2 - MAZAK H-800"),               # codice solo nel name
    StubAsset("CNC-MZ5153592", "MAZAK FH-6800"),                   # codice solo nel tag (no trattino) -> non risolvibile
    StubAsset("CNC-DM100500002381", "DM1-DMGCTXGamma2000TC"),      # tag malformato, salvato dal name
    StubAsset("MNO-TORNI-001", "Tornio AKEBONO"),                  # nessun mnemonico
]


class ResolverTest(SimpleTestCase):
    def setUp(self):
        self.indice = IndiceAsset.costruisci(ASSETS)

    def test_normalizza(self):
        self.assertEqual(normalizza_codice("dm 11"), "DM11")
        self.assertEqual(normalizza_codice(" mz5 "), "MZ5")

    def test_separa_attacco(self):
        self.assertEqual(normalizza_codice_attacco("DM3 ISO40"), ("DM3", "ISO40"))
        self.assertEqual(normalizza_codice_attacco("MK1 HSK"), ("MK1", "HSK"))
        self.assertEqual(normalizza_codice_attacco("HH ISO40"), ("HH", "ISO40"))
        self.assertEqual(normalizza_codice_attacco("DM10"), ("DM10", ""))

    def test_tag_e_name_concordano_alta(self):
        r = risolvi("DM3", self.indice)
        self.assertEqual(r.confidenza, CONF_ALTA)
        self.assertEqual(r.asset.asset_tag, "CNC-DM3-12280000463")

        r2 = risolvi("dm12", self.indice)  # normalizzazione + no spazi nel name
        self.assertEqual(r2.confidenza, CONF_ALTA)

    def test_solo_name_media(self):
        r = risolvi("MZ2", self.indice)
        self.assertEqual(r.confidenza, CONF_MEDIA)
        self.assertEqual(r.fonte, "name")
        self.assertEqual(r.asset.asset_tag, "CNC-MZ2117322")

    def test_tag_senza_trattino_non_risolvibile(self):
        r = risolvi("MZ5", self.indice)
        self.assertEqual(r.confidenza, CONF_ASSENTE)
        self.assertIsNone(r.asset)

    def test_tag_malformato_salvato_dal_name(self):
        r = risolvi("DM1", self.indice)
        self.assertEqual(r.confidenza, CONF_MEDIA)
        self.assertEqual(r.fonte, "name")

    def test_nessun_mnemonico(self):
        r = risolvi("AKEBONO", self.indice)
        self.assertEqual(r.confidenza, CONF_ASSENTE)

    def test_ambiguo(self):
        indice = IndiceAsset.costruisci([
            StubAsset("CNC-DM9-1", "DM9 - alfa"),
            StubAsset("CNC-DM9-2", "DM9 - beta"),
        ])
        r = risolvi("DM9", indice)
        self.assertEqual(r.confidenza, CONF_AMBIGUA)
        self.assertIsNone(r.asset)
