"""Accessi esterni dal GuestPortal e apertura del pannello con accesso automatico."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from anagrafica.models import Fornitore
from fornitori import guestportal as gp

SEGRETO = "s" * 48
GP_SSO = {
    "GUESTPORTAL_SSO_URL": "https://gp.example.local/guestportal/public/admin/sso.php",
    "GUESTPORTAL_SSO_SECRET": SEGRETO,
    "GUESTPORTAL_ADMIN_URL": "https://gp.example.local/guestportal/public/admin/index.php",
}


def _decodifica(token: str) -> dict:
    corpo, firma = token.split(".")
    attesa = base64.urlsafe_b64encode(
        hmac.new(SEGRETO.encode(), corpo.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    assert hmac.compare_digest(firma, attesa), "firma non valida"
    return json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))


class TokenSsoTests(SimpleTestCase):
    @override_settings(**GP_SSO)
    def test_token_firmato_con_scadenza_60s_e_nonce(self):
        payload = _decodifica(gp.firma_token("Mario.Rossi", adesso=1_000, nonce="abc"))
        self.assertEqual(payload, {"u": "mario.rossi", "iat": 1_000, "exp": 1_060, "n": "abc", "iss": "novicrom-hub"})

    @override_settings(**GP_SSO)
    def test_nonce_diverso_a_ogni_token(self):
        self.assertNotEqual(_decodifica(gp.firma_token("a"))["n"], _decodifica(gp.firma_token("a"))["n"])

    def test_username_ridotto_al_nome_di_dominio(self):
        self.assertEqual(gp.username_dominio("CNOVICROM\\M.Rossi"), "m.rossi")
        self.assertEqual(gp.username_dominio("m.rossi@example.local"), "m.rossi")
        self.assertEqual(gp.username_dominio("  M.Rossi "), "m.rossi")

    @override_settings(GUESTPORTAL_SSO_SECRET="corto", GUESTPORTAL_SSO_URL="https://x")
    def test_segreto_corto_non_attiva_sso(self):
        self.assertFalse(gp.sso_configurato())
        with self.assertRaises(gp.GuestPortalNonConfigurato):
            gp.firma_token("m.rossi")


class LetturaVisiteTests(SimpleTestCase):
    def _riga(self, **extra):
        riga = {
            "VisitID": 7, "Status": "CHECKEDIN", "VisitType": "SUPPLIER", "BadgeNumber": "03",
            "HostEmployee": "Referente Test", "Purpose": "Manutenzione", "CheckInTime": datetime(2026, 11, 4, 9, 0),
            "CheckOutTime": None, "FirstName": "Ospite", "LastName": "Esempio", "Company": "Ditta X",
            "IsAnonymized": 0, "SupplierName": "Fornitore Esempio Srl",
        }
        riga.update(extra)
        return riga

    def test_riga_fornitore_usa_ragione_sociale_del_fornitore(self):
        a = gp._riga_in_accesso(self._riga())
        self.assertEqual((a.nome, a.azienda, a.tipo_label, a.stato_label), ("Ospite Esempio", "Fornitore Esempio Srl", "Fornitore / consulente", "Presente"))
        self.assertTrue(a.presente)

    def test_ospite_anonimizzato_non_mostra_dati(self):
        a = gp._riga_in_accesso(self._riga(IsAnonymized=1))
        self.assertEqual((a.nome, a.azienda), ("Ospite anonimizzato", ""))

    def test_durata(self):
        a = gp._riga_in_accesso(self._riga(CheckOutTime=datetime(2026, 11, 4, 10, 35)))
        self.assertEqual(a.durata_label, "1 h 35 min")

    @override_settings(GUESTPORTAL_DB_HOST="db", GUESTPORTAL_DB_NAME="GuestManagement", GUESTPORTAL_DB_USER="hub_ro")
    def test_storico_segnala_troncamento_e_usa_solo_select(self):
        cursore = MagicMock()
        cursore.fetchall.return_value = [self._riga(VisitID=i) for i in range(4)]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursore
        with patch.object(gp, "_connessione", return_value=conn):
            righe, troncato = gp.storico(dal=date(2026, 11, 1), al=date(2026, 11, 4), testo="ditta", limite=3)
        self.assertEqual((len(righe), troncato), (3, True))
        sql, params = cursore.execute.call_args[0]
        self.assertTrue(sql.lstrip().upper().startswith("SELECT"))
        self.assertEqual(params[-1], 4)
        self.assertIn("%ditta%", params)
        conn.close.assert_called_once()

    def test_senza_configurazione_errore_esplicito(self):
        with self.assertRaises(gp.GuestPortalNonConfigurato):
            gp.presenti_ora()


class VisteGuestPortalTests(TestCase):
    def setUp(self):
        self.utente = get_user_model().objects.create_superuser("m.rossi", "m.rossi@example.com", "pwd12345")
        self.client.force_login(self.utente)

    @override_settings(**GP_SSO)
    def test_apri_con_sso_reindirizza_a_sso_php_con_token(self):
        with patch("fornitori.views.log_action"):
            resp = self.client.get(reverse("fornitori:guestportal_apri"))
        self.assertEqual(resp.status_code, 302)
        url = urlparse(resp["Location"])
        self.assertEqual(url.path, "/guestportal/public/admin/sso.php")
        self.assertEqual(_decodifica(parse_qs(url.query)["t"][0])["u"], "m.rossi")
        self.assertEqual(resp["Cache-Control"], "no-store")
        self.assertEqual(resp["Referrer-Policy"], "no-referrer")

    @override_settings(GUESTPORTAL_SSO_SECRET="", GUESTPORTAL_ADMIN_URL=GP_SSO["GUESTPORTAL_ADMIN_URL"])
    def test_apri_senza_sso_porta_al_login_del_pannello(self):
        resp = self.client.get(reverse("fornitori:guestportal_apri"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], GP_SSO["GUESTPORTAL_ADMIN_URL"])

    def test_apri_richiede_login(self):
        self.client.logout()
        resp = self.client.get(reverse("fornitori:guestportal_apri"))
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("sso.php", resp["Location"])

    @override_settings(GUESTPORTAL_DB_HOST="")
    def test_pagina_senza_configurazione_mostra_avviso(self):
        resp = self.client.get(reverse("fornitori:accessi_esterni"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "non configurato")

    @override_settings(GUESTPORTAL_DB_HOST="db", GUESTPORTAL_DB_NAME="GuestManagement", GUESTPORTAL_DB_USER="hub_ro")
    def test_pagina_collega_azienda_alla_scheda_fornitore(self):
        fornitore = Fornitore.objects.create(ragione_sociale="Fornitore Esempio Srl")
        accesso = gp._riga_in_accesso(LetturaVisiteTests()._riga())
        with patch.object(gp, "presenti_ora", return_value=[accesso]), \
             patch.object(gp, "storico", return_value=([], False)):
            resp = self.client.get(reverse("fornitori:accessi_esterni"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ospite Esempio")
        self.assertContains(resp, reverse("fornitori:fornitore_detail", args=[fornitore.pk]))
        self.assertContains(resp, "Presenti ora")
        self.assertContains(resp, reverse("fornitori:guestportal_apri"))
        self.assertContains(resp, "Accessi esterni</a>")  # voce nella subnav del modulo
        html = resp.content.decode()
        self.assertNotIn("{#", html)
        self.assertNotIn("{%", html)

    def test_centro_guide_spiega_accessi_esterni(self):
        url = reverse("guida_modulo", args=["fornitori"])
        self.assertContains(self.client.get(url), "Accessi esterni (GuestPortal)")
        self.assertContains(self.client.get(url + "?vista=admin"), "Collegare il GuestPortal")
        self.assertContains(self.client.get(url + "?vista=problemi"), "guestportal.log")

    @override_settings(GUESTPORTAL_DB_HOST="db", GUESTPORTAL_DB_NAME="GuestManagement", GUESTPORTAL_DB_USER="hub_ro")
    def test_db_non_raggiungibile_messaggio_chiaro(self):
        with patch.object(gp, "presenti_ora", side_effect=gp.GuestPortalNonRaggiungibile("down")):
            resp = self.client.get(reverse("fornitori:accessi_esterni"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "non risponde")


class RottaCondivisaTests(SimpleTestCase):
    def test_apri_guestportal_tra_le_rotte_condivise(self):
        from core import middleware

        self.assertIn("fornitori:guestportal_apri", middleware._ACL_SHARED_ROUTE_NAMES)
        self.assertNotIn("fornitori:accessi_esterni", middleware._ACL_SHARED_ROUTE_NAMES)
