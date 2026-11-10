"""Chiosco: riconoscimento da nome e cognome, ingresso di chi torna, cartellini in uso. Dati sintetici."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from django.test import override_settings

from . import chiosco, guestportal
from .test_chiosco import CHIAMATE, Base

SCHEDA_GP = [{"FirstName": "Bruno", "LastName": "Esempio", "Email": "bruno@example.local", "Phone": "000", "Company": "Ditta Prova"}]


def _mysql(sql, params):
    if "FROM SupplierContacts" in sql:
        return [{"ContactID": 9, "SupplierID": 5, "CompanyName": "Impianti Esempio Srl"}] if params[:2] == ["Bruno", "Esempio"] else []
    if "GROUP BY" in sql:
        if params[1:3] != ["Bruno", "Esempio"]:
            return []
        return [{"GuestID": 41, "Company": "Ditta Prova", "Ultima": datetime(2026, 10, 2, 9, 0)},
                {"GuestID": 42, "Company": "", "Ultima": datetime(2026, 9, 1, 9, 0)}]
    if "WHERE ContactID IN" in sql:
        return [{"ContactID": 9, "HostEmployee": "Prova Referente"}]
    if "WHERE GuestID IN" in sql:
        return [{"GuestID": 41, "HostEmployee": "Prova Referente", "Purpose": "Altro"}]
    if "FROM Guests" in sql:
        return SCHEDA_GP if params == [41] else []
    return []


class RiconosciTests(Base):
    def setUp(self):
        super().setUp()
        for p in (patch.object(guestportal, "_esegui", side_effect=_mysql),
                  patch.object(guestportal, "db_configurato", return_value=True)):
            p.start()
            self.addCleanup(p.stop)

    def riconosci(self, nome="Bruno", cognome="Esempio"):
        return self.api("riconosci", nome=nome, cognome=cognome)

    def test_omonimi_solo_con_la_loro_azienda(self):
        r = self.riconosci()
        trovati = r.json()["trovati"]
        self.assertEqual([(t["tipo"], t["azienda"]) for t in trovati],
                         [("fornitore", "Impianti Esempio Srl"), ("ospite", "Ditta Prova"), ("ospite", "")])
        testo = r.content.decode()
        self.assertNotIn("bruno@example.local", testo)
        self.assertNotIn('"41"', testo)

    def test_nome_parziale_o_diverso_niente(self):
        self.assertEqual(self.riconosci("Br", "Esempio").json()["trovati"], [])
        self.assertEqual(self.riconosci("Bruno", "Altro").json()["trovati"], [])

    def test_ingresso_di_chi_torna_rilegge_i_dati_dal_server(self):
        ospite = next(t for t in self.riconosci().json()["trovati"] if t["azienda"] == "Ditta Prova")
        r = self.api("ingresso-ospite", ospite=ospite["chiave"], referente_id=3, motivo="Altro", gdpr_consent=True,
                     first_name="Falso", email="falso@example.local")
        self.assertTrue(r.json()["success"])
        inviati = self.inviati("checkin_submit")
        self.assertEqual((inviati["first_name"], inviati["email"]), ("Bruno", "bruno@example.local"))
        self.assertNotIn("guest_id", inviati)

    def test_fornitore_riconosciuto_entra_con_la_chiave(self):
        fornitore = self.riconosci().json()["trovati"][0]
        r = self.api("ingresso-fornitore", fornitore=fornitore["chiave"], referente_id=3, gdpr_consent=True, azienda_id=77)
        self.assertTrue(r.json()["success"])
        self.assertEqual(self.inviati("supplier_checkin")["company_name"], "Impianti Esempio Srl")

    def test_chiave_falsa_scambiata_o_senza_informativa(self):
        self.assertFalse(self.api("ingresso-ospite", ospite="x:41", referente_id=3, motivo="Altro", gdpr_consent=True).json()["success"])
        chiave_fornitore = chiosco.chiave("gp", "fornitore", 9, 5)
        self.assertFalse(self.api("ingresso-ospite", ospite=chiave_fornitore, referente_id=3, motivo="Altro", gdpr_consent=True).json()["success"])
        chiave_hub = chiosco.chiave("hub", "ospite", 41)
        self.assertFalse(self.api("ingresso-ospite", ospite=chiave_hub, referente_id=3, motivo="Altro", gdpr_consent=True).json()["success"])
        chiave = chiosco.chiave("gp", "ospite", 41)
        self.assertFalse(self.api("ingresso-ospite", ospite=chiave, referente_id=3, motivo="Altro").json()["success"])
        self.assertNotIn("checkin_submit", [n for n, _ in CHIAMATE])

    def test_il_browser_non_aggancia_un_altro_ospite(self):
        self.api("ingresso", first_name="Luisa", last_name="Prova", referente_id=3, motivo="Altro", gdpr_consent=True, guest_id=41)
        self.assertNotIn("guest_id", self.inviati("checkin_submit"))

    def test_cartellini_in_uso(self):
        presenti = [guestportal.Accesso(1, "CHECKEDIN", "NORMAL", "x", "", "", "", b, None, None) for b in ("12", "03", "N/A")]
        with patch.object(guestportal, "presenti_ora", return_value=presenti):
            self.assertEqual(self.api("cartellini").json()["cartellini"], ["03", "12"])
        with patch.object(guestportal, "presenti_ora", side_effect=guestportal.GuestPortalNonRaggiungibile("giù")):
            self.assertFalse(self.api("cartellini").json()["success"])

    @override_settings(CHIOSCO_ALLOWED_IPS=[])
    def test_postazione_non_ammessa(self):
        self.assertEqual(self.riconosci().status_code, 403)

    def test_pagina_con_informativa_da_spuntare(self):
        pagina = self.client.get("/chiosco/").content.decode()
        self.assertIn('id="f-gdpr"', pagina)
        self.assertIn('id="b-entra" disabled', pagina)
        self.assertNotIn(' style="', pagina)
