"""Inserimento del controllore: dati strutturati (misure, difetto, documenti, riferimento),
«Dove sono i pezzi?» per blocco, «Riprendi» dei controlli di altri e chiusura dei
controlli vuoti. Dati sintetici."""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie import controllo_service as cs
from anomalie import dettaglio_controllo as dc
from anomalie.quality_models import AnomaliaControllo, AnomaliaSchedaQualita, AnomaliaTipoDifetto
from anomalie.tests_controllo import OP, LegacyTableMixin, _salva_finta

User = get_user_model()


class FrasiEsitiTests(SimpleTestCase):
    def test_minmax_sotto_il_minimo(self):
        m = {"car": "diametro", "modo": "minmax", "a": "131.345", "b": "131.360", "ril": "131.330", "dove": "Sez. H-H"}
        self.assertEqual(dc.esito_misura(m), {"fuori": True, "scarto": -0.015})
        self.assertEqual(dc.frase_misura(m), "Ø 131.345/131.360 rilevato 131.330 (−0.015) · Sez. H-H")

    def test_pm_e_max(self):
        pm = {"car": "quota", "modo": "pm", "nom": "41.202", "a": "0.01", "ril": "41.230"}
        self.assertEqual(dc.esito_misura(pm)["fuori"], True)
        self.assertEqual(dc.frase_misura(pm), "Quota 41.202 ±0.01 rilevato 41.230 (+0.018)")
        geo = {"car": "concentricita", "modo": "max", "a": "0.05", "ril": "0.26"}
        self.assertEqual(dc.frase_misura(geo), "◎ Concentricità max 0.05 rilevato 0.26 (+0.21)")
        dentro = {"car": "quota", "modo": "minmax", "a": "1", "b": "2", "ril": "1,5"}
        self.assertEqual(dc.esito_misura(dentro), {"fuori": False, "scarto": 0.0})

    def test_normalizza_scarta_campi_ignoti_e_righe_vuote(self):
        d = dc.normalizza({"tipo": "misura", "misure": [{"car": "x", "ril": "1"}, {"car": "quota"}], "hack": 1,
                           "rif": {"sezione": " H-H "}})
        self.assertEqual(d["misure"], [{"car": "altro", "nome": "", "modo": "minmax", "nom": "", "a": "", "b": "",
                                        "ril": "1", "dove": ""}])
        self.assertEqual(d["rif"], {"disegno": "", "sezione": "H-H", "fase": ""})
        self.assertNotIn("hack", d)
        self.assertEqual(dc.normalizza("x"), {})

    def test_frasi_difetto_e_documenti(self):
        dif = {"tipo": "difetto", "difetto": {"genere": "fusione", "dove": "diametro AY", "prof": "0.41"},
               "rif": {"disegno": "DIS-1", "fase": "Fase 80"}}
        self.assertEqual(dc.frasi(dc.normalizza(dif)), [
            "Testimone di fusione / porosità · diametro AY · profondità 0.41", "Rif.: DIS-1 · Fase 80"])
        doc = {"tipo": "documenti", "documenti": {"trovato": "AW340", "atteso": "AW341", "docs": ["OP", "DDT", "Boh"]}}
        self.assertEqual(dc.frasi(dc.normalizza(doc)),
                         ["Marcatura/documenti non coincidenti · sul pezzo AW340 · atteso AW341 · documenti: OP, DDT"])

    def test_tipo_difetto_suggerito(self):
        self.assertEqual(dc.tipo_difetto_suggerito({"tipo": "misura", "misure": [{"car": "simmetria"}]}), "geometria")
        self.assertEqual(dc.tipo_difetto_suggerito({"tipo": "difetto", "difetto": {"genere": "bava"}}), "bave-spigoli")
        self.assertEqual(dc.tipo_difetto_suggerito({"tipo": "documenti"}), "marcatura-documenti")
        self.assertEqual(dc.tipo_difetto_suggerito({}, "Trovata bava su smusso"), "bave-spigoli")
        self.assertEqual(dc.tipo_difetto_suggerito({}, "Ø 131.345/131.360 risulta Ø 131.330"), "fuori-tolleranza")
        self.assertEqual(dc.tipo_difetto_suggerito({}, "niente di riconoscibile"), "")


def _sync_crea_scheda(local_id):
    AnomaliaSchedaQualita.objects.get_or_create(anomalia_id=local_id, defaults={"op_titolo": OP})


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class BloccoConDettaglioTests(LegacyTableMixin, TestCase):
    def setUp(self):
        self.crea_tabella()
        self.user = User.objects.create_superuser(username="ctl-dett", password="pass12345", email="d@example.local")
        self.client.force_login(self.user)
        self._patches = [
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
            patch("anomalie.views._salva_riga_anomalia", side_effect=_salva_finta),
            patch("anomalie.controllo_views._sync_scheda", side_effect=_sync_crea_scheda),
            patch("anomalie.controllo_service._allegati", return_value=[]),
            patch("anomalie.controllo_service.stati_superficie_configurati", return_value=False),
        ]
        for p in self._patches:
            p.start()
        AnomaliaTipoDifetto.objects.get_or_create(codice="fuori-tolleranza", defaults={"nome": "Fuori tolleranza dimensionale"})
        self.geo, _ = AnomaliaTipoDifetto.objects.get_or_create(codice="geometria", defaults={"nome": "Geometria"})

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.elimina_tabella()

    def post(self, name, body, pk=None):
        url = reverse(name, args=[pk]) if pk else reverse(name)
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def test_dettaglio_tipo_difetto_e_dove_pezzi(self):
        cid = self.post("api_anomalie_controllo_apri", {"op_id": OP, "fase": "Collaudo"}).json()["controllo"]["id"]
        misura = {"tipo": "misura", "misure": [{"car": "diametro", "modo": "minmax", "a": "1", "b": "2", "ril": "2.1"}]}
        r = self.post("api_anomalie_controllo_blocco", {
            "seriali": ["LCN00001"], "dove_pezzi": "Area NC",
            "anomalie": [{"testo": "Diametro grande", "dettaglio": misura},
                         {"testo": "Altra", "dettaglio": {}, "tipo_difetto_id": self.geo.pk}],
        }, cid)
        self.assertEqual(r.status_code, 200, r.content)
        ids = [x["local_id"] for x in r.json()["risultati"]]
        s1, s2 = (AnomaliaSchedaQualita.objects.get(anomalia_id=i) for i in ids)
        self.assertEqual(s1.dettaglio_controllo["misure"][0]["ril"], "2.1")
        self.assertEqual(s1.tipo_difetto.codice, "fuori-tolleranza")  # proposto dalle misure
        self.assertEqual(s2.tipo_difetto_id, self.geo.pk)  # scelto dal controllore
        self.assertEqual((s1.dove_pezzi, s2.dove_pezzi), ("Area NC", "Area NC"))
        blocco = r.json()["controllo"]["blocchi"][0]
        self.assertEqual(blocco["dove_pezzi"], "Area NC")
        self.assertEqual(blocco["anomalie"][0]["dettaglio"]["tipo"], "misura")
        # Gruppi delle mail: dove sono i pezzi e frasi delle misure.
        gruppi = cs.gruppi_per_blocco([{"id": i, "seriale": "LCN00001", "descrizione": "x"} for i in ids])
        self.assertEqual(gruppi[0]["dove_pezzi"], "Area NC")
        self.assertEqual(gruppi[0]["righe"][0]["dettaglio_righe"], ["Ø 1/2 rilevato 2.1 (+0.1)"])

    def test_risalvataggio_invariato_aggiorna_dettaglio(self):
        cid = self.post("api_anomalie_controllo_apri", {"op_id": OP, "fase": "Collaudo"}).json()["controllo"]["id"]
        r = self.post("api_anomalie_controllo_blocco", {"seriali": ["LCN00001"], "anomalie": [{"testo": "A"}]}, cid)
        data = r.json()
        aid = data["risultati"][0]["local_id"]
        self.post("api_anomalie_controllo_blocco", {
            "blocco_id": data["blocco_id"], "seriali": ["LCN00001"], "dove_pezzi": "Reparto 2",
            "anomalie": [{"local_id": aid, "testo": "A", "dettaglio": {"tipo": "documenti", "documenti": {"trovato": "X"}}}],
        }, cid)
        scheda = AnomaliaSchedaQualita.objects.get(anomalia_id=aid)
        self.assertEqual(scheda.dettaglio_controllo["tipo"], "documenti")
        self.assertEqual(scheda.dove_pezzi, "Reparto 2")


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class RiprendiEChiusuraTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="ctl-rip", password="pass12345", email="r@example.local")
        self.altro = User.objects.create_user(username="ctl-altro", password="pass12345")
        self.client.force_login(self.user)

    def test_controllo_di_altri_proposto(self):
        c = AnomaliaControllo.objects.create(op_id=OP, fase="Collaudo", operatore=self.altro, operatore_display="Collega")
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=True):
            r = self.client.get(reverse("api_anomalie_controlli"), {"op_id": OP})
        righe = r.json()["controlli"]
        self.assertEqual([(x["id"], x["mio"], x["operatore"]) for x in righe], [(c.pk, False, "Collega")])

    def test_chiusura_controlli_vuoti(self):
        vecchio = timezone.now() - timedelta(hours=30)
        vuoto = AnomaliaControllo.objects.create(op_id=OP, fase="A", operatore=self.user)
        con_bozza = AnomaliaControllo.objects.create(op_id=OP, fase="B", operatore=self.user,
                                                     bozza={"voci": ["LCN1"]}, bozza_at=vecchio)
        recente = AnomaliaControllo.objects.create(op_id=OP, fase="C", operatore=self.user)
        AnomaliaControllo.objects.filter(pk__in=[vuoto.pk, con_bozza.pk]).update(created_at=vecchio)
        self.assertEqual(cs.chiudi_controlli_vuoti(), 1)
        vuoto.refresh_from_db(); con_bozza.refresh_from_db(); recente.refresh_from_db()
        self.assertIsNotNone(vuoto.terminato_at)
        self.assertIsNone(con_bozza.terminato_at)
        self.assertIsNone(recente.terminato_at)
