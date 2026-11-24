"""Nominativi in COGNOME NOME e confronti indipendenti dall'ordine (24/11/2026). Dati sintetici."""

from django.test import SimpleTestCase, TestCase

from core import naming

from .nominativi import converti_config, converti_elenco_testo, mappa_da_righe


class ChiavePersonaTests(SimpleTestCase):
    def test_stessa_persona_in_ogni_ordine(self):
        self.assertEqual(naming.chiave_persona("Mario Rossi"), naming.chiave_persona("ROSSI  MARIO"))
        self.assertEqual(naming.chiave_persona("Mario De Luca"), naming.chiave_persona("DE LUCA MARIO"))
        self.assertEqual(naming.chiave_persona("Niccolò Verdi"), naming.chiave_persona("VERDI NICCOLO"))
        self.assertNotEqual(naming.chiave_persona("Mario Rossi"), naming.chiave_persona("Maria Rossi"))


class ConversioneTests(SimpleTestCase):
    mappa = mappa_da_righe([("Mario", "Rossi"), ("Anna", "Bianchi"), ("Luca", "Neri"), ("Luca", "Neri")])

    def test_omonimi_esatti_restano_convertibili_ma_ambigui_no(self):
        mappa = mappa_da_righe([("Mario", "Rossi"), ("Rossi", "Mario")])
        # Due persone diverse con le stesse parole: nessuna conversione.
        self.assertNotIn(naming.chiave_persona("Mario Rossi"), mappa)
        self.assertEqual(self.mappa[naming.chiave_persona("Luca Neri")], "NERI LUCA")

    def test_converte_gli_elenchi_di_persone_del_json(self):
        cfg = {
            "referenti_rdc": ["Mario Rossi", "ROSSI MARIO", "Esterno Senza Anagrafica"],
            "derived_sources": {"capi_reparto": {"ruoli": [3], "extra": ["Anna Bianchi"], "esclusi": []}},
            "gruppi_controllori": [{"codice": "cmm", "nome": "Controllo CMM", "persone": ["Luca Neri"]}],
            "stati": ["Mario Rossi"],  # non è un elenco di persone: resta com'è
        }
        out = converti_config(cfg, self.mappa)
        self.assertEqual(out["referenti_rdc"], ["ROSSI MARIO", "Esterno Senza Anagrafica"])
        self.assertEqual(out["derived_sources"]["capi_reparto"]["extra"], ["BIANCHI ANNA"])
        self.assertEqual(out["derived_sources"]["capi_reparto"]["ruoli"], [3])
        self.assertEqual(out["gruppi_controllori"][0]["persone"], ["NERI LUCA"])
        self.assertEqual(out["gruppi_controllori"][0]["nome"], "Controllo CMM")
        self.assertEqual(out["stati"], ["Mario Rossi"])

    def test_car_segnalati(self):
        self.assertEqual(converti_elenco_testo("Mario Rossi; Anna Bianchi; ROSSI MARIO", self.mappa),
                         "ROSSI MARIO; BIANCHI ANNA")


class ConfrontiTests(SimpleTestCase):
    def test_separa_car_scelti_senza_doppioni_in_ordine_diverso(self):
        from .automazioni_service import separa_car_scelti

        self.assertEqual(separa_car_scelti("Mario Rossi; ROSSI MARIO; Anna Bianchi"), ["Mario Rossi", "Anna Bianchi"])

    def test_lista_derivata_esclusi_e_aggiunti_in_ogni_ordine(self):
        from unittest.mock import patch

        from . import views

        with patch.object(views, "_capireparto_from_anagrafica", return_value=["ROSSI MARIO", "BIANCHI ANNA"]):
            valori = views._resolve_derived_list(
                "capi_reparto",
                {"capi_reparto": {"ruoli": [], "extra": ["Anna Bianchi", "Luca Neri"], "esclusi": ["Mario Rossi"]}},
            )
        # «Mario Rossi» escluso vale per ROSSI MARIO; «Anna Bianchi» non si raddoppia.
        self.assertEqual(valori, ["BIANCHI ANNA", "Luca Neri"])

    def test_etichetta_da_anagrafica_cognome_nome(self):
        from .views import _label_from_anagrafica_row

        self.assertEqual(_label_from_anagrafica_row({"nome": "Mario", "cognome": "De Luca"}), "DE LUCA MARIO")


class UtenteDaNominativoTests(TestCase):
    def setUp(self):
        from anagrafica.tests import _ensure_utenti_table
        from core.legacy_models import UtenteLegacy

        _ensure_utenti_table()
        self.u = UtenteLegacy.objects.create(nome="Mario De Luca", password="x", attivo=True)
        UtenteLegacy.objects.create(nome="Anna Bianchi", password="x", attivo=True)

    def test_cognome_composto_in_ordine_inverso(self):
        from .mail_action_service import find_legacy_user_by_name

        self.assertEqual(find_legacy_user_by_name("DE LUCA MARIO"), self.u)
        self.assertEqual(find_legacy_user_by_name("mario de luca"), self.u)
        self.assertIsNone(find_legacy_user_by_name("Luca Mario"))
