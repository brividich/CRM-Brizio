"""Test F6 — distribuzione tracciata, presa visione, regola copie con deroga."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from gestione_specifiche import constants as C
from gestione_specifiche.distribuzione import (
    DerogaCopieRichiesta, crea_distribuzione,
)
from gestione_specifiche.models import ConfigPresaVisione, Distribuzione, Specifica

User = get_user_model()


def _spec(codice, *, tipo=C.TIPO_SPECIFICA, revisione="0", revisione_precedente=None):
    return Specifica.objects.create(
        codice=codice, titolo="T", tipo=tipo, revisione=revisione,
        revisione_precedente=revisione_precedente,
    )


class RegolaCopieTests(TestCase):
    def test_match_copie_nessuna_deroga(self):
        prev = _spec("SP-D1", revisione="0")
        crea_distribuzione(prev, canale=C.CANALE_CARTACEO, cartacea=True, n_copie_distribuite=5)
        new = _spec("SP-D1", revisione="1", revisione_precedente=prev)
        d = crea_distribuzione(new, canale=C.CANALE_CARTACEO, cartacea=True,
                               n_copie_distribuite=5, n_copie_ritirate=5)
        self.assertIsNotNone(d.pk)
        self.assertEqual(d.deroga_giustificazione, "")

    def test_mismatch_senza_deroga_solleva(self):
        prev = _spec("SP-D2", revisione="0")
        crea_distribuzione(prev, canale=C.CANALE_CARTACEO, cartacea=True, n_copie_distribuite=5)
        new = _spec("SP-D2", revisione="1", revisione_precedente=prev)
        with self.assertRaises(DerogaCopieRichiesta) as ctx:
            crea_distribuzione(new, canale=C.CANALE_CARTACEO, cartacea=True,
                               n_copie_distribuite=5, n_copie_ritirate=3)
        self.assertEqual(ctx.exception.attese, 5)
        self.assertEqual(ctx.exception.ritirate, 3)

    def test_mismatch_con_deroga_procede(self):
        prev = _spec("SP-D3", revisione="0")
        crea_distribuzione(prev, canale=C.CANALE_CARTACEO, cartacea=True, n_copie_distribuite=5)
        new = _spec("SP-D3", revisione="1", revisione_precedente=prev)
        d = crea_distribuzione(new, canale=C.CANALE_CARTACEO, cartacea=True,
                               n_copie_distribuite=5, n_copie_ritirate=3,
                               deroga_giustificazione="2 copie smarrite in reparto")
        self.assertIsNotNone(d.pk)
        self.assertTrue(d.deroga_giustificazione)

    def test_non_cartacea_nessun_controllo_copie(self):
        spec = _spec("SP-D4")
        d = crea_distribuzione(spec, canale=C.CANALE_NOTIFICA, cartacea=False, n_copie_ritirate=99)
        self.assertIsNotNone(d.pk)


class PresaVisioneTests(TestCase):
    def setUp(self):
        from anagrafica.models import Reparto
        self.rep = Reparto.objects.create(nome="Produzione PV")

    def test_default_false_senza_config(self):
        spec = _spec("SP-PV1")
        d = crea_distribuzione(spec, canale=C.CANALE_NOTIFICA, reparti=[self.rep])
        self.assertFalse(d.presa_visione_richiesta)

    def test_config_reparto_specifico(self):
        ConfigPresaVisione.objects.create(
            tipo_documento=C.TIPO_SPECIFICA, reparto=self.rep, richiesta=True)
        spec = _spec("SP-PV2")
        d = crea_distribuzione(spec, canale=C.CANALE_NOTIFICA, reparti=[self.rep])
        self.assertTrue(d.presa_visione_richiesta)

    def test_config_default_reparto_nullo(self):
        ConfigPresaVisione.objects.create(
            tipo_documento=C.TIPO_COMUNICAZIONE, reparto=None, richiesta=True)
        spec = _spec("SP-PV3", tipo=C.TIPO_COMUNICAZIONE)
        d = crea_distribuzione(spec, canale=C.CANALE_NOTIFICA, reparti=[])
        self.assertTrue(d.presa_visione_richiesta)


class DistribuzioneAuditTests(TestCase):
    def test_evento_m2m_e_data(self):
        from anagrafica.models import Reparto
        rep = Reparto.objects.create(nome="Reparto X")
        user = User.objects.create_user("dist_u", password="x")
        spec = _spec("SP-D5")
        d = crea_distribuzione(spec, canale=C.CANALE_EMAIL, reparti=[rep], attore=user)
        self.assertEqual(d.destinatari.count(), 1)
        self.assertIsNotNone(d.data_distribuzione)
        self.assertTrue(spec.eventi.filter(trigger="distribuzione").exists())


class DistribuzioneViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su_dist", "s@x.it", "x")
        self.client.force_login(self.su)

    def test_get_form(self):
        spec = _spec("SP-VD")
        r = self.client.get(reverse("gestione_specifiche:distribuzione_nuova", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Distribuzione")

    def test_post_notifica(self):
        spec = _spec("SP-VD2")
        r = self.client.post(reverse("gestione_specifiche:distribuzione_nuova", args=[spec.pk]),
                            {"canale": C.CANALE_NOTIFICA})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Distribuzione.objects.filter(specifica=spec).exists())

    def test_post_cartacea_mismatch_poi_deroga(self):
        prev = _spec("SP-VD3", revisione="0")
        crea_distribuzione(prev, canale=C.CANALE_CARTACEO, cartacea=True, n_copie_distribuite=5)
        new = _spec("SP-VD3", revisione="1", revisione_precedente=prev)
        # mismatch senza deroga: re-render 200, nessuna nuova distribuzione
        r = self.client.post(reverse("gestione_specifiche:distribuzione_nuova", args=[new.pk]),
                            {"canale": C.CANALE_CARTACEO, "cartacea": "on",
                             "n_copie_distribuite": "5", "n_copie_ritirate": "3"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Distribuzione.objects.filter(specifica=new).exists())
        # con deroga: creata
        r2 = self.client.post(reverse("gestione_specifiche:distribuzione_nuova", args=[new.pk]),
                             {"canale": C.CANALE_CARTACEO, "cartacea": "on",
                              "n_copie_distribuite": "5", "n_copie_ritirate": "3",
                              "deroga_giustificazione": "smarrite"})
        self.assertEqual(r2.status_code, 302)
        self.assertTrue(Distribuzione.objects.filter(specifica=new).exists())
