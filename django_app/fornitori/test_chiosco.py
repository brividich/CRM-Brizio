"""Chiosco nell'HUB: senza login, solo dalle postazioni ammesse, con i dati riletti dal server."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import chiosco

REFERENTI = {"success": True, "data": [
    {"EmployeeID": 3, "FullName": "Prova Referente", "Email": "referente@example.local", "Department": "IT"},
]}


def _finto(nome, dati=None, ip=""):
    """Il GuestPortal finto: registra le chiamate in ``CHIAMATE``."""
    CHIAMATE.append((nome, dati))
    if nome == "employees":
        return 200, REFERENTI
    if nome == "supplier_lookup" and dati["action"] == "suppliers":
        return 200, {"success": True, "suppliers": [{"SupplierID": 5, "CompanyName": "Impianti Esempio Srl"}]}
    if nome == "supplier_lookup":
        return 200, {"success": True, "contacts": [{"ContactID": 9, "FirstName": "Mario", "LastName": "Esempio"}]}
    if nome in ("checkin_submit", "supplier_checkin", "prereg_checkin"):
        return 200, {"success": True, "visit_id": 1, "badge_number": "07", "guest_name": "Mario Esempio", "host_employee": "Prova Referente"}
    if nome == "checkout_lookup":
        return 200, {"success": True, "visits": [{"visit_id": 1, "badge_number": "07", "guest_name": "Mario Esempio", "checkin_time": "2026-03-01 08:00:00", "altro": "x"}]}
    if nome == "checkout_submit":
        return 200, {"success": True, "duration": "4h"}
    if nome == "guest_lookup":
        return 200, {"found": True, "guest": {"FirstName": "Mario", "LastName": "Esempio", "Email": "m@example.local", "Phone": "", "Company": "Impianti"}}
    if nome == "prereg_lookup":
        return 200, {"success": True, "prereg": {"guest_name": "Mario Esempio", "guest_email": "m@example.local", "guest_company": "Impianti", "host_employee": "Prova Referente", "host_email": "referente@example.local", "purpose": "Riunione / Meeting"}}
    return 200, {"success": False}


CHIAMATE: list = []


@override_settings(CHIOSCO_ALLOWED_IPS=["127.0.0.1"], GUESTPORTAL_CHIOSCO_API_URL="http://gp.example.local/public/api/",
                   SECURE_SSL_REDIRECT=False)
class Base(TestCase):
    def setUp(self):
        cache.clear()
        CHIAMATE.clear()
        for bersaglio, finto in (("chiama", _finto), ("categorie", lambda: chiosco.CATEGORIE_PREDEFINITE)):
            patcher = patch.object(chiosco, bersaglio, side_effect=finto)
            patcher.start()
            self.addCleanup(patcher.stop)

    def api(self, azione, **dati):
        return self.client.post(reverse("chiosco:api", args=[azione]), json.dumps(dati), content_type="application/json")

    def inviati(self, nome):
        return next(d for n, d in CHIAMATE if n == nome)


class AccessoTests(Base):
    def test_si_apre_senza_login(self):
        risposta = self.client.get(reverse("chiosco:pagina"))
        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "Prova Referente")

    def test_email_dei_referenti_non_arriva_al_browser(self):
        self.assertNotContains(self.client.get(reverse("chiosco:pagina")), "referente@example.local")

    def test_referrer_policy_per_il_csrf(self):
        self.assertEqual(self.client.get(reverse("chiosco:pagina"))["Referrer-Policy"], "same-origin")

    @override_settings(CHIOSCO_ALLOWED_IPS=[])
    def test_senza_elenco_e_chiuso(self):
        self.assertEqual(self.client.get(reverse("chiosco:pagina")).status_code, 403)
        risposta = self.api("aziende")
        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(risposta["Content-Type"], "application/json")
        self.assertEqual(CHIAMATE, [])

    @override_settings(CHIOSCO_ALLOWED_IPS=["10.0.5.0/24"])
    def test_ip_fuori_dalla_rete_non_entra(self):
        self.assertEqual(self.client.get(reverse("chiosco:pagina")).status_code, 403)
        self.assertEqual(self.client.get(reverse("chiosco:pagina"), REMOTE_ADDR="10.0.5.7").status_code, 200)

    def test_il_forwarded_for_non_apre_il_chiosco(self):
        with override_settings(CHIOSCO_ALLOWED_IPS=["10.0.5.7"]):
            risposta = self.client.get(reverse("chiosco:pagina"), HTTP_X_FORWARDED_FOR="10.0.5.7")
        self.assertEqual(risposta.status_code, 403)

    def test_csrf_obbligatorio(self):
        client = Client(enforce_csrf_checks=True)
        risposta = client.post(reverse("chiosco:api", args=["aziende"]), "{}", content_type="application/json")
        self.assertEqual(risposta.status_code, 403)

    def test_azione_sconosciuta(self):
        self.assertEqual(self.api("create_supplier").status_code, 404)

    def test_get_sulle_api_non_ammesso(self):
        self.assertEqual(self.client.get(reverse("chiosco:api", args=["aziende"])).status_code, 405)

    def test_guestportal_giu(self):
        with patch.object(chiosco, "chiama", side_effect=chiosco.ChioscoNonDisponibile):
            self.assertEqual(self.api("aziende").status_code, 503)
            cache.clear()
            self.assertContains(self.client.get(reverse("chiosco:pagina")), "Registrazione non disponibile")


class IngressoTests(Base):
    DATI = {"first_name": "Mario", "last_name": "Esempio", "referente_id": 3, "motivo": "Altro", "gdpr_consent": True}

    def test_ingresso_rilegge_il_referente_dal_server(self):
        risposta = self.api("ingresso", **self.DATI, host_email="altro@example.local")
        self.assertEqual(risposta.json()["badge_number"], "07")
        inviati = self.inviati("checkin_submit")
        self.assertEqual(inviati["host_email"], "referente@example.local")
        self.assertEqual(inviati["host_employee"], "Prova Referente")

    def test_senza_consenso_non_parte(self):
        risposta = self.api("ingresso", **{**self.DATI, "gdpr_consent": False})
        self.assertFalse(risposta.json()["success"])
        self.assertNotIn("checkin_submit", [n for n, _ in CHIAMATE])

    def test_motivo_e_referente_devono_esistere(self):
        self.assertFalse(self.api("ingresso", **{**self.DATI, "motivo": "Inventato"}).json()["success"])
        self.assertFalse(self.api("ingresso", **{**self.DATI, "referente_id": 99}).json()["success"])

    def test_nome_di_chi_usa_gia_l_email_non_si_vede(self):
        with patch.object(chiosco, "chiama", side_effect=lambda n, d=None, **k: _finto(n, d) if n == "employees" else (
                422, {"success": False, "email_conflict": True, "error": "L'email è già associata a Persona Riservata."})):
            risposta = self.api("ingresso", **self.DATI, email="m@example.local")
        self.assertNotIn("Riservata", risposta.content.decode())

    def test_errore_tecnico_non_arriva_allo_schermo(self):
        with patch.object(chiosco, "chiama", side_effect=lambda n, d=None, **k: _finto(n, d) if n == "employees" else (
                500, {"success": False, "error": "SQLSTATE dettaglio interno"})):
            risposta = self.api("ingresso", **self.DATI)
        self.assertNotIn("SQLSTATE", risposta.content.decode())

    def test_gia_dentro_e_cartellini_finiti(self):
        for risposta_gp, chiave in (((409, {"success": False, "already_in": True}), "already_in"),
                                    ((503, {"success": False, "no_badges": True}), "no_badges")):
            with patch.object(chiosco, "chiama", side_effect=lambda n, d=None, r=risposta_gp, **k: _finto(n, d) if n == "employees" else r):
                self.assertTrue(self.api("ingresso", **self.DATI).json()[chiave])

    def test_ospite_gia_noto(self):
        self.assertEqual(self.api("ospite", email="m@example.local").json()["guest"]["first_name"], "Mario")
        self.assertFalse(self.api("ospite", email="non-valida").json()["found"])

    def test_fornitore_rilegge_azienda_e_nominativo(self):
        risposta = self.api("ingresso-fornitore", azienda_id=5, nominativo_id=9, referente_id=3, gdpr_consent=True,
                            company_name="Falsa", first_name="Falso")
        self.assertTrue(risposta.json()["success"])
        inviati = self.inviati("supplier_checkin")
        self.assertEqual(inviati["company_name"], "Impianti Esempio Srl")
        self.assertEqual(inviati["first_name"], "Mario")

    def test_fornitore_inesistente(self):
        self.assertFalse(self.api("ingresso-fornitore", azienda_id=77, nominativo_id=9, referente_id=3, gdpr_consent=True).json()["success"])
        self.assertFalse(self.api("ingresso-fornitore", azienda_id=5, nominativo_id=77, referente_id=3, gdpr_consent=True).json()["success"])

    def test_fornitore_senza_informativa_non_entra(self):
        risposta = self.api("ingresso-fornitore", azienda_id=5, nominativo_id=9, referente_id=3)
        self.assertFalse(risposta.json()["success"])
        self.assertNotIn("supplier_checkin", [n for n, _ in CHIAMATE])

    def test_informativa_completa_e_senza_promesse_false(self):
        pagina = self.client.get(reverse("chiosco:pagina")).content.decode()
        self.assertIn("56025 Pontedera (PI)", pagina)
        self.assertIn("come prova dell", pagina)
        self.assertNotIn("automaticamente", pagina)


class UscitaPreregTests(Base):
    def test_cerca_uscita_mette_gli_zeri_e_filtra_i_campi(self):
        visita = self.api("cerca-uscita", badge="7").json()["visits"][0]
        self.assertEqual(self.inviati("checkout_lookup"), {"badge": "07"})
        self.assertNotIn("altro", visita)

    def test_uscita(self):
        self.assertEqual(self.api("uscita", visit_id=1, badge="07").json()["duration"], "4h")
        self.assertFalse(self.api("uscita", badge="07").json()["success"])

    def test_prereg_non_manda_le_email_al_browser(self):
        contenuto = self.api("prereg-cerca", code="abcd2345").content.decode()
        self.assertEqual(self.inviati("prereg_lookup"), {"code": "ABCD2345"})
        self.assertNotIn("example.local", contenuto)

    def test_prereg_vuole_il_consenso(self):
        self.assertFalse(self.api("prereg-entra", code="ABCD2345").json()["success"])
        self.assertEqual(self.api("prereg-entra", code="ABCD2345", gdpr_consent=True).json()["badge_number"], "07")


class ClientTests(TestCase):
    @override_settings(GUESTPORTAL_CHIOSCO_API_URL="")
    def test_non_configurato(self):
        self.assertFalse(chiosco.configurato())
        with self.assertRaises(chiosco.ChioscoNonDisponibile):
            chiosco.chiama("employees")

    @override_settings(GUESTPORTAL_CHIOSCO_API_URL="http://gp.example.local/public/api/")
    def test_categorie_lette_dalla_pagina_o_predefinite(self):
        cache.clear()
        pagina = ('<div class="category-card"\n data-id="1"\n data-name="Riunione &amp; altro"\n onclick="x">'
                  '<div class="cat-icon">🤝</div>').encode()
        with patch.object(chiosco, "_richiesta", return_value=(200, pagina)):
            self.assertEqual(chiosco.categorie()[0]["nome"], "Riunione & altro")
        cache.clear()
        with patch.object(chiosco, "_richiesta", side_effect=chiosco.ChioscoNonDisponibile):
            self.assertEqual(chiosco.categorie(), chiosco.CATEGORIE_PREDEFINITE)
        cache.clear()

    @override_settings(GUESTPORTAL_CHIOSCO_API_URL="http://gp.example.local/public/api/")
    def test_risposta_non_json(self):
        with patch.object(chiosco, "_richiesta", return_value=(500, b"<html>errore</html>")), \
                self.assertRaises(chiosco.ChioscoNonDisponibile):
            chiosco.chiama("employees")
