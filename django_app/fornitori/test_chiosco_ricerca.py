"""Chiosco: ricerca live dal campo unico, ingresso di chi torna, cartellini in uso. Dati sintetici."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from django.test import override_settings

from . import chiosco, guestportal
from .test_chiosco import CHIAMATE, Base

OSPITI_GP = [{"GuestID": 41, "FirstName": "Bruno", "LastName": "Esempio", "Company": "Ditta Prova",
              "Ultima": datetime(2026, 10, 2, 9, 0)}]
ULTIME_GP = [{"GuestID": 41, "HostEmployee": "Prova Referente", "Purpose": "Altro"}]
SCHEDA_GP = [{"FirstName": "Bruno", "LastName": "Esempio", "Email": "bruno@example.local", "Phone": "000", "Company": "Ditta Prova"}]


def _mysql(sql, params):
    if "GROUP BY" in sql:
        return OSPITI_GP
    if "HostEmployee" in sql:
        return ULTIME_GP
    if "FROM Guests" in sql:
        return SCHEDA_GP if params == [41] else []
    return []


class RicercaTests(Base):
    def setUp(self):
        super().setUp()
        p1 = patch.object(guestportal, "_esegui", side_effect=_mysql)
        p2 = patch.object(guestportal, "db_configurato", return_value=True)
        for p in (p1, p2):
            p.start()
            self.addCleanup(p.stop)

    def test_sotto_tre_lettere_niente(self):
        r = self.api("cerca", q="Br").json()
        self.assertEqual((r["ospiti"], r["ditte"], r["invito"]), ([], [], None))

    def test_bru_propone_il_nome_ridotto_senza_email(self):
        r = self.api("cerca", q="Bru")
        dati = r.json()
        self.assertEqual(dati["ospiti"][0]["nome"], "Bruno E.")
        self.assertEqual(dati["ospiti"][0]["referente"], "Prova Referente")
        testo = r.content.decode()
        self.assertNotIn("Esempio", testo)
        self.assertNotIn("bruno@example.local", testo)
        self.assertNotIn('"41"', testo)

    def test_ditte_accreditate(self):
        self.assertEqual(self.api("cerca", q="impi").json()["ditte"][0]["nome"], "Impianti Esempio Srl")

    def test_codice_invito(self):
        r = self.api("cerca", q="abcd2345").json()
        self.assertEqual(r["invito"]["code"], "ABCD2345")
        self.assertNotIn("host_email", r["invito"])

    def test_ingresso_di_chi_torna_rilegge_i_dati_dal_server(self):
        chiave = self.api("cerca", q="Bru").json()["ospiti"][0]["chiave"]
        r = self.api("ingresso-ospite", ospite=chiave, referente_id=3, motivo="Altro", gdpr_consent=True,
                     first_name="Falso", email="falso@example.local")
        self.assertTrue(r.json()["success"])
        inviati = self.inviati("checkin_submit")
        self.assertEqual((inviati["first_name"], inviati["email"]), ("Bruno", "bruno@example.local"))
        self.assertNotIn("guest_id", inviati)

    def test_chiave_falsa_o_senza_informativa(self):
        self.assertFalse(self.api("ingresso-ospite", ospite="x:41", referente_id=3, motivo="Altro", gdpr_consent=True).json()["success"])
        chiave = chiosco.chiave_ospite("gp", 41)
        self.assertFalse(self.api("ingresso-ospite", ospite=chiave, referente_id=3, motivo="Altro").json()["success"])
        self.assertNotIn("checkin_submit", [n for n, _ in CHIAMATE])

    def test_il_browser_non_aggancia_un_altro_ospite(self):
        self.api("ingresso", first_name="Luisa", last_name="Prova", referente_id=3, motivo="Altro", gdpr_consent=True,
                 guest_id=41, _ospite_hub=41)
        self.assertNotIn("guest_id", self.inviati("checkin_submit"))

    def test_cartellini_in_uso(self):
        presenti = [guestportal.Accesso(1, "CHECKEDIN", "NORMAL", "x", "", "", "", b, None, None) for b in ("12", "03", "N/A")]
        with patch.object(guestportal, "presenti_ora", return_value=presenti):
            self.assertEqual(self.api("cartellini").json()["cartellini"], ["03", "12"])
        with patch.object(guestportal, "presenti_ora", side_effect=guestportal.GuestPortalNonRaggiungibile("giù")):
            self.assertFalse(self.api("cartellini").json()["success"])

    @override_settings(CHIOSCO_ALLOWED_IPS=[])
    def test_postazione_non_ammessa(self):
        self.assertEqual(self.api("cerca", q="Bru").status_code, 403)

    def test_pagina_nuova(self):
        pagina = self.client.get("/chiosco/").content.decode()
        self.assertIn('id="f-q"', pagina)
        self.assertNotIn(' style="', pagina)
