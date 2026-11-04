"""Azioni rapide della home: liste per tutti / ruolo / persona e scelte personali."""
from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import SiteConfig, UserUiPreference
from dashboard import azioni_rapide as ar
from dashboard import views_home_portale as hp


def _voce(key, label=None, gruppo="Azioni"):
    return {"key": key, "label": label or key, "href": f"/{key}/", "gruppo": gruppo}


class CatalogoTests(TestCase):
    def test_catalogo_ha_azioni_e_moduli_con_chiavi_uniche(self):
        keys = [v["key"] for v in ar.catalogo()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("a:mie_attivita", keys)
        self.assertTrue(any(k.startswith("m:") for k in keys))

    def test_pulisci_scarta_sconosciute_doppioni_e_oltre_il_massimo(self):
        validi = [v["key"] for v in ar.catalogo()]
        raw = ["a:mie_attivita", "a:mie_attivita", "x:boh", None, *validi]
        out = ar.pulisci(raw)
        self.assertEqual(out[0], "a:mie_attivita")
        self.assertNotIn("x:boh", out)
        self.assertEqual(len(out), min(ar.AZIONI_MAX, len(validi)))


class PrecedenzaTests(TestCase):
    def test_standard_senza_configurazione(self):
        keys, fonte, limite = ar.lista_effettiva({}, None)
        self.assertEqual(fonte, "standard")
        self.assertEqual(limite, hp.HOME_AZIONI_MAX)
        self.assertEqual(keys, ar.standard())

    def test_predefinite_poi_ruolo_poi_persona(self):
        ar.salva_predefinite(["a:scadenzario"])
        self.assertEqual(ar.lista_effettiva({}, 7)[:2], (["a:scadenzario"], "predefinite"))
        ar.salva_ruolo(7, ["a:ticket", "a:mie_attivita"])
        self.assertEqual(ar.lista_effettiva({}, 7)[:2], (["a:ticket", "a:mie_attivita"], "ruolo"))
        self.assertEqual(ar.lista_effettiva({}, 8)[1], "predefinite")
        prefs = {"azioni": ["a:dpi"], "azioni_fonte": "admin"}
        self.assertEqual(ar.lista_effettiva(prefs, 7)[:2], (["a:dpi"], "admin"))
        self.assertEqual(ar.lista_effettiva({"azioni": []}, 7)[:2], ([], "utente"))
        self.assertEqual(ar.ruoli_personalizzati(), {7})
        ar.salva_ruolo(7, None)
        ar.salva_predefinite(None)
        self.assertEqual(ar.lista_effettiva({}, 7)[1], "standard")

    def test_valore_corrotto_ignorato(self):
        SiteConfig.set(ar.CHIAVE_PREDEFINITE, "{non json")
        self.assertIsNone(ar.leggi_predefinite())

    def test_home_mostra_solo_le_voci_consentite_nell_ordine_scelto(self):
        consentite = [_voce("a:mie_attivita"), _voce("m:ticket", gruppo="Moduli")]
        dati = ar.azioni_home({"azioni": ["m:ticket", "a:anomalia", "a:mie_attivita"]}, None, consentite)
        self.assertEqual([a["label"] for a in dati["azioni"]], ["m:ticket", "a:mie_attivita"])
        self.assertEqual(dati["azioni"][0]["variant"], "primary")
        self.assertEqual(dati["fonte"], "utente")

    def test_standard_limitato_alle_prime_consentite(self):
        consentite = [_voce(k) for k in ar.standard()]
        dati = ar.azioni_home({}, None, consentite)
        self.assertEqual(len(dati["azioni"]), hp.HOME_AZIONI_MAX)


class HomeAzioniViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="adm", email="a@a.it", password="x")
        self.client.force_login(self.user)
        self.url = reverse("home_portale:index")

    def _prefs(self):
        return UserUiPreference.objects.get(user=self.user).home_prefs

    def test_personalizza_salva_le_azioni_solo_se_modificate(self):
        self.client.post(self.url, {"azione": "personalizza", "stanza": "", "mostra": ["azioni"]})
        self.assertNotIn("azioni", self._prefs())
        r = self.client.post(self.url, {
            "azione": "personalizza", "stanza": "", "mostra": ["azioni"],
            "azioni_modificate": "1", "voce": ["a:scadenzario", "a:mie_attivita", "x:boh"],
        })
        self.assertEqual(r.status_code, 200)
        p = self._prefs()
        self.assertEqual(p["azioni"], ["a:scadenzario", "a:mie_attivita"])
        self.assertEqual(p["azioni_fonte"], "utente")
        resp = self.client.get(self.url)
        self.assertEqual([a["label"] for a in resp.context["header_actions"]], ["Scadenzario", "Le mie attività"])
        self.assertContains(resp, "Scelte da te")

    def test_ripristina_torna_alle_predefinite(self):
        UserUiPreference.objects.create(user=self.user, home_prefs={"azioni": ["a:scadenzario"]})
        ar.salva_predefinite(["a:mie_attivita"])
        self.client.post(self.url, {"azione": "azioni_ripristina"})
        self.assertNotIn("azioni", self._prefs())
        resp = self.client.get(self.url)
        self.assertEqual([a["label"] for a in resp.context["header_actions"]], ["Le mie attività"])

    def test_scelta_non_consentita_scartata_dal_server(self):
        with mock.patch.object(ar, "voci_consentite", return_value=[_voce("a:mie_attivita")]):
            self.client.post(self.url, {
                "azione": "personalizza", "stanza": "", "azioni_modificate": "1",
                "voce": ["a:anomalia", "a:mie_attivita"],
            })
        self.assertEqual(self._prefs()["azioni"], ["a:mie_attivita"])


class AdminAzioniRapideTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="adm", email="a@a.it", password="x")
        self.p1 = User.objects.create_user(username="p1", password="x", first_name="Primo", last_name="Sintetico")
        self.p2 = User.objects.create_user(username="p2", password="x", first_name="Secondo", last_name="Sintetico")
        self.url = reverse("admin_portale:home_azioni_rapide")
        self.client.force_login(self.admin)

    def test_pagina_si_apre(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Predefinite per tutti")
        self.assertContains(resp, "PRIMO SINTETICO")

    def test_predefinite_e_standard(self):
        self.client.post(self.url, {"azione": "predefinite_salva", "voce": ["a:ticket", "m:anomalie"]})
        self.assertEqual(ar.leggi_predefinite(), ["a:ticket", "m:anomalie"])
        self.client.post(self.url, {"azione": "predefinite_standard"})
        self.assertIsNone(ar.leggi_predefinite())

    def test_ruolo(self):
        self.client.post(self.url, {"azione": "ruolo_salva", "ruolo": "3", "voce": ["a:dpi"]})
        self.assertEqual(ar.leggi_ruolo(3), ["a:dpi"])
        self.client.post(self.url, {"azione": "ruolo_togli", "ruolo": "3"})
        self.assertIsNone(ar.leggi_ruolo(3))

    def test_persone_in_blocco_e_ripristino(self):
        UserUiPreference.objects.create(user=self.p2, home_prefs={"preferiti": ["ticket"]})
        self.client.post(self.url, {
            "azione": "persone_applica", "utenti": [self.p1.pk, self.p2.pk], "voce": ["a:scadenzario"],
        })
        for u in (self.p1, self.p2):
            home = UserUiPreference.objects.get(user=u).home_prefs
            self.assertEqual(home["azioni"], ["a:scadenzario"])
            self.assertEqual(home["azioni_fonte"], "admin")
        # Le altre preferenze della persona restano.
        self.assertEqual(UserUiPreference.objects.get(user=self.p2).home_prefs["preferiti"], ["ticket"])
        resp = self.client.get(self.url, {"utente": self.p1.pk})
        self.assertContains(resp, "Partendo dalla lista di PRIMO SINTETICO")
        self.client.post(self.url, {"azione": "persone_ripristina", "utenti": [self.p1.pk]})
        self.assertNotIn("azioni", UserUiPreference.objects.get(user=self.p1).home_prefs)
        self.assertIn("azioni", UserUiPreference.objects.get(user=self.p2).home_prefs)

    def test_lista_admin_resta_modificabile_dalla_persona(self):
        prefs = hp._pulisci_home_prefs({"azioni": ["a:scadenzario"], "azioni_fonte": "admin"})
        self.assertEqual(prefs["azioni_fonte"], "admin")
        self.assertEqual(ar.azioni_home(prefs, None, [_voce("a:scadenzario")])["fonte_label"],
                         "Impostate dall'amministratore")

    def test_nessuna_persona_selezionata(self):
        self.client.post(self.url, {"azione": "persone_applica", "voce": ["a:scadenzario"]})
        self.assertFalse(UserUiPreference.objects.exists())

    def test_non_admin_non_entra(self):
        self.client.force_login(self.p1)
        resp = self.client.get(self.url)
        self.assertIn(resp.status_code, (302, 403))
        self.client.post(self.url, {"azione": "predefinite_salva", "voce": ["a:ticket"]})
        self.assertIsNone(ar.leggi_predefinite())

    def test_dati_salvati_come_json(self):
        self.client.post(self.url, {"azione": "predefinite_salva", "voce": ["a:ticket"]})
        self.assertEqual(json.loads(SiteConfig.get(ar.CHIAVE_PREDEFINITE)), ["a:ticket"])
