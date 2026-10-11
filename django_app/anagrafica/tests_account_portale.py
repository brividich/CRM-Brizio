"""Creazione dipendente con verifica dell'utente portale (prompt 03, obiettivo B).

LDAP sempre mockato (nessuna rete): trovato, non trovato, ambiguo, disabilitato, fuori allowlist,
timeout. Dati sintetici su domini ``example.invalid``.
"""
from __future__ import annotations

import socket
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import AuditLog, Profile

from .services import account_portale as svc
from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()

LDAP_OK = dict(LDAP_ENABLED=True, LDAP_SERVER="ldap://ad.example.invalid", LDAP_BASE_DN="DC=example,DC=invalid",
               LDAP_USER_FILTER="(objectClass=user)", LDAP_SERVICE_USER="svc@example.invalid", LDAP_SERVICE_PASSWORD="x",
               LDAP_GROUP_ALLOWLIST=["Portale"])
PWD_OK = "Cavallo-Batteria-Graffetta-42"


def _entry(upn, *, uac=512, gruppi=("Portale",), nome="Mario Rossi"):
    return {"type": "searchResEntry", "attributes": {
        "userPrincipalName": upn, "mail": upn, "sAMAccountName": upn.split("@")[0], "displayName": nome,
        "userAccountControl": uac, "memberOf": [f"CN={g},OU=Gruppi,DC=example,DC=invalid" for g in gruppi]}}


class _FakeConn:
    def __init__(self, entries=None, errore=None):
        self.entries_ad = entries or []
        self.errore = errore
        self.response = []
        self.filtri = []

    def search(self, search_base, search_filter, attributes, size_limit):
        self.filtri.append(search_filter)
        if self.errore:
            raise self.errore
        self.response = list(self.entries_ad)
        return True

    def unbind(self):
        pass

    # Il servizio non deve mai scrivere in AD.
    def add(self, *a, **k):
        raise AssertionError("scrittura in AD")

    modify = delete = modify_dn = add


def _ad(entries=None, errore=None):
    conn = _FakeConn(entries, errore)
    return patch.object(svc, "_connetti", return_value=conn), conn


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, **LDAP_OK)
class AccountPortaleBase(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute("DELETE FROM utenti")
        self.admin = User.objects.create_superuser("acc_admin", "acc_admin@example.invalid", "x")
        self.client.force_login(self.admin)

    def _post(self, **extra):
        dati = {"nome": "Mario", "cognome": "Rossi", "aliasusername": "m.rossi", "attivo": "on",
                "email_notifica": "m.rossi@example.invalid", "account_scelta": "nessuno"}
        dati.update(extra)
        return self.client.post(reverse("anagrafica:dipendente_create"), dati)

    def _dipendente(self):
        return AnagraficaDipendente.objects.filter(aliasusername="m.rossi").first()


class RicercaADTests(AccountPortaleBase):
    def test_trovato_con_gruppi_e_stato(self):
        p, conn = _ad([_entry("m.rossi@example.invalid")])
        with p:
            esito = svc.cerca_ad(email="m.rossi@example.invalid", nome="Mario", cognome="Rossi")
        self.assertEqual(esito.stato, "ok")
        self.assertEqual(len(esito.risultati), 1)
        a = esito.risultati[0]
        self.assertEqual((a.upn, a.abilitato, a.in_allowlist, a.gruppi), ("m.rossi@example.invalid", True, True, ["Portale"]))
        self.assertIn("(givenName=Mario)", conn.filtri[0])

    def test_input_con_caratteri_ldap_viene_escapato(self):
        p, conn = _ad([])
        with p:
            svc.cerca_ad(email="x*)(uid=*@example.invalid")
        self.assertNotIn("x*)(uid=*", conn.filtri[0])
        self.assertIn(r"\2a", conn.filtri[0])

    def test_timeout_spiegato(self):
        p, _conn = _ad(errore=socket.timeout("timed out"))
        with p:
            esito = svc.cerca_ad(email="m.rossi@example.invalid")
        self.assertEqual(esito.stato, "irraggiungibile")
        self.assertIn("comunque", esito.messaggio)

    @override_settings(LDAP_ENABLED=False)
    def test_non_configurato(self):
        self.assertEqual(svc.cerca_ad(email="m.rossi@example.invalid").stato, "non_configurato")

    def test_verifica_rifiuta_disabilitato_ambiguo_fuori_allowlist_non_trovato(self):
        casi = [
            ([_entry("m.rossi@example.invalid", uac=514)], "disabilitato"),
            ([_entry("m.rossi@example.invalid"), _entry("m.rossi@example.invalid", nome="Omonimo")], "ambiguo"),
            ([_entry("m.rossi@example.invalid", gruppi=("Esterni",))], "LDAP_GROUP_ALLOWLIST"),
            ([], "Nessun account AD"),
            ([_entry("m.rossi.bis@example.invalid")], "Nessun account AD"),  # niente prefissi o somiglianze
        ]
        for entries, atteso in casi:
            p, _conn = _ad(entries)
            with p, self.subTest(atteso=atteso):
                account, errore, _irr = svc.verifica_account_ad("m.rossi@example.invalid")
                self.assertIsNone(account)
                self.assertIn(atteso, errore)

    def test_endpoint_risponde_json_401_403_e_html_all_admin(self):
        url = reverse("anagrafica:account_portale_cerca")
        p, _conn = _ad([_entry("m.rossi@example.invalid")])
        with p:
            ok = self.client.get(url, {"email": "m.rossi@example.invalid"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(ok, "m.rossi@example.invalid")
        self.assertContains(ok, "abilitato")
        self.client.logout()
        anon = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertIn(anon.status_code, (401, 403))
        self.assertEqual(anon["Content-Type"].split(";")[0], "application/json")
        semplice = User.objects.create_user("acc_semplice", "acc_semplice@example.invalid", "x")
        self.client.force_login(semplice)
        negato = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(negato.status_code, 403)
        self.assertEqual(negato["Content-Type"].split(";")[0], "application/json")


class CreazioneConAccountTests(AccountPortaleBase):
    def test_collega_ad_crea_utente_ad_managed_e_scrive_audit(self):
        p, _conn = _ad([_entry("m.rossi@example.invalid")])
        with p:
            r = self._post(account_scelta="ad", account_ad_upn="m.rossi@example.invalid")
        self.assertEqual(r.status_code, 302)
        dip = self._dipendente()
        utente = UtenteLegacy.objects.get(email="m.rossi@example.invalid")
        self.assertEqual(dip.utente_id, utente.id)
        self.assertEqual(utente.password, svc.AD_MANAGED)
        self.assertTrue(AuditLog.objects.filter(azione="ACCOUNT_PORTALE_COLLEGATO", oggetto_id=str(dip.id)).exists())

    def test_ad_fuori_allowlist_blocca_e_non_crea(self):
        p, _conn = _ad([_entry("m.rossi@example.invalid", gruppi=("Esterni",))])
        with p:
            r = self._post(account_scelta="ad", account_ad_upn="m.rossi@example.invalid")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self._dipendente())
        self.assertContains(r, "gruppo autorizzato")

    def test_ad_timeout_crea_dipendente_senza_account(self):
        p, _conn = _ad(errore=socket.timeout("timed out"))
        with p:
            r = self._post(account_scelta="ad", account_ad_upn="m.rossi@example.invalid")
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self._dipendente().utente_id)
        self.assertFalse(UtenteLegacy.objects.exists())

    def test_nessun_collegamento_automatico_per_alias(self):
        UtenteLegacy.objects.create(nome="ALTRO", email="m.rossi@altro.example.invalid", password="h", attivo=True)
        r = self._post()
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self._dipendente().utente_id)
        self.assertEqual(UtenteLegacy.objects.count(), 1)

    def test_utente_locale_con_password_scelta_e_cambio_obbligato(self):
        debole = self._post(account_scelta="locale", account_login="m.rossi", account_password="1990")
        self.assertEqual(debole.status_code, 200)
        self.assertIsNone(self._dipendente())
        r = self._post(account_scelta="locale", account_login="m.rossi", account_password=PWD_OK)
        self.assertEqual(r.status_code, 302)
        utente = UtenteLegacy.objects.get(email="m.rossi")
        self.assertTrue(utente.deve_cambiare_password)
        self.assertNotIn(PWD_OK, utente.password)
        self.assertEqual(self._dipendente().utente_id, utente.id)
        self.assertTrue(AuditLog.objects.filter(azione="ACCOUNT_PORTALE_CREATO").exists())

    def test_collega_solo_utente_con_stessa_email(self):
        estraneo = UtenteLegacy.objects.create(nome="ESTRANEO", email="estraneo@example.invalid", password="h", attivo=True)
        r = self._post(account_scelta="collega", account_collega_id=str(estraneo.id))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self._dipendente())

    def test_doppio_submit_crea_un_solo_dipendente(self):
        token = "a" * 32
        primo = self._post(creazione_token=token)
        secondo = self._post(creazione_token=token)
        self.assertEqual(AnagraficaDipendente.objects.filter(aliasusername="m.rossi").count(), 1)
        self.assertEqual(primo["Location"], secondo["Location"])


class AccountPrivilegiatoTests(AccountPortaleBase):
    def setUp(self):
        super().setUp()
        self.legacy = UtenteLegacy.objects.create(nome="ROSSI MARIO", email="m.rossi@example.invalid", password="h", attivo=True)
        self.root = User.objects.create_superuser("root_omonimo", "root@example.invalid", "x")
        Profile.objects.create(user=self.root, legacy_user_id=self.legacy.id)

    def _request(self, user):
        request = RequestFactory().post("/")
        request.user = user
        return request

    def test_rifiuta_collegamento_a_superuser_senza_conferma(self):
        operatore = User.objects.create_user("hr_operatore", "hr@example.invalid", "x")
        scelta = svc.SceltaAccount(tipo="collega", collega_id=self.legacy.id, conferma_privilegiato=True)
        errori = svc.valida_scelta(self._request(operatore), scelta, email="m.rossi@example.invalid", codice_fiscale="", attivo=True)
        self.assertTrue(errori and "superuser" in errori[0])
        scelta.conferma_privilegiato = False
        errori = svc.valida_scelta(self._request(self.admin), scelta, email="m.rossi@example.invalid", codice_fiscale="", attivo=True)
        self.assertTrue(errori)

    def test_superuser_con_conferma_collega_e_traccia(self):
        r = self._post(account_scelta="collega", account_collega_id=str(self.legacy.id), account_conferma_privilegiato="1")
        self.assertEqual(r.status_code, 302)
        dip = self._dipendente()
        self.assertEqual(dip.utente_id, self.legacy.id)
        log = AuditLog.objects.get(azione="ACCOUNT_PORTALE_COLLEGATO", oggetto_id=str(dip.id))
        self.assertTrue(log.dettaglio["conferma_privilegiato"])

    def test_ad_su_utente_privilegiato_esistente_richiede_conferma(self):
        p, _conn = _ad([_entry("m.rossi@example.invalid")])
        with p:
            r = self._post(account_scelta="ad", account_ad_upn="m.rossi@example.invalid")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self._dipendente())
