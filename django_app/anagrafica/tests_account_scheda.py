"""Riquadro «Account portale» della scheda dipendente: collega / scollega su una scheda esistente.

Stesse regole del wizard di creazione (``services.account_portale``). LDAP sempre mockato (nessuna
rete), dati sintetici su domini ``example.invalid``.
"""
from __future__ import annotations

import socket
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import AuditLog, Profile

from .services import account_portale as svc
from .tests_account_portale import PWD_OK, AccountPortaleBase, _ad, _entry

User = get_user_model()
EMAIL = "m.rossi@example.invalid"
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class AccountSchedaBase(AccountPortaleBase):
    def setUp(self):
        super().setUp()
        self.dip = AnagraficaDipendente.objects.create(nome="Mario", cognome="Rossi", aliasusername="m.rossi",
                                                       email_notifica=EMAIL)

    def _collega(self, **dati):
        return self.client.post(reverse("anagrafica:dipendente_account_portale", args=[self.dip.id]), dati)

    def _scollega(self, **extra):
        return self.client.post(reverse("anagrafica:dipendente_account_scollega", args=[self.dip.id]), {"conferma": "1"}, **extra)

    def _utente_id(self):
        return AnagraficaDipendente.objects.get(pk=self.dip.id).utente_id


class CollegaDaSchedaTests(AccountSchedaBase):
    def test_collega_ad_crea_utente_ad_managed_e_audit(self):
        p, _conn = _ad([_entry(EMAIL)])
        with p:
            r = self._collega(account_scelta="ad", account_ad_upn=EMAIL)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("#account-portale"))
        utente = UtenteLegacy.objects.get(email=EMAIL)
        self.assertEqual(utente.password, svc.AD_MANAGED)
        self.assertEqual(self._utente_id(), utente.id)
        log = AuditLog.objects.get(azione="ACCOUNT_PORTALE_COLLEGATO", oggetto_id=str(self.dip.id))
        self.assertEqual((log.dettaglio["modo"], log.dettaglio["origine"]), ("ad", "scheda"))

    def test_ad_irraggiungibile_non_collega(self):
        p, _conn = _ad(errore=socket.timeout("timed out"))
        with p:
            r = self._collega(account_scelta="ad", account_ad_upn=EMAIL)
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self._utente_id())
        self.assertFalse(UtenteLegacy.objects.exists())

    def test_collega_utente_esistente_con_stessa_email(self):
        legacy = UtenteLegacy.objects.create(nome="ROSSI MARIO", email=EMAIL, password=svc.AD_MANAGED, attivo=True)
        r = self._collega(account_scelta="collega", account_collega_id=str(legacy.id))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._utente_id(), legacy.id)
        self.assertTrue(AuditLog.objects.filter(azione="ACCOUNT_PORTALE_COLLEGATO", oggetto_id=str(self.dip.id)).exists())

    def test_email_dal_db_non_dal_post(self):
        estraneo = UtenteLegacy.objects.create(nome="ESTRANEO", email="estraneo@example.invalid", password="h", attivo=True)
        r = self._collega(account_scelta="collega", account_collega_id=str(estraneo.id), email="estraneo@example.invalid")
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self._utente_id())

    def test_crea_utente_locale(self):
        r = self._collega(account_scelta="locale", account_login="m.rossi", account_password=PWD_OK)
        self.assertEqual(r.status_code, 302)
        utente = UtenteLegacy.objects.get(email="m.rossi")
        self.assertTrue(utente.deve_cambiare_password)
        self.assertEqual(self._utente_id(), utente.id)
        self.assertTrue(AuditLog.objects.filter(azione="ACCOUNT_PORTALE_CREATO", oggetto_id=str(self.dip.id)).exists())

    def test_scheda_gia_collegata_rifiuta(self):
        primo = UtenteLegacy.objects.create(nome="PRIMO", email=EMAIL, password=svc.AD_MANAGED, attivo=True)
        AnagraficaDipendente.objects.filter(pk=self.dip.id).update(utente_id=primo.id)
        r = self._collega(account_scelta="locale", account_login="m.rossi2", account_password=PWD_OK)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._utente_id(), primo.id)
        self.assertFalse(UtenteLegacy.objects.filter(email="m.rossi2").exists())

    def test_utente_gia_su_altra_scheda_rifiuta(self):
        legacy = UtenteLegacy.objects.create(nome="ROSSI MARIO", email=EMAIL, password=svc.AD_MANAGED, attivo=True)
        AnagraficaDipendente.objects.create(nome="Altro", cognome="Rossi", utente_id=legacy.id)
        r = self._collega(account_scelta="collega", account_collega_id=str(legacy.id))
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self._utente_id())

    def test_dipendente_inattivo_rifiuta(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE anagrafica_dipendenti SET attivo = 0 WHERE id = %s", [self.dip.id])
        r = self._collega(account_scelta="locale", account_login="m.rossi", account_password=PWD_OK)
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self._utente_id())
        self.assertFalse(UtenteLegacy.objects.exists())

    def test_ajax_rifiuto_in_json(self):
        r = self.client.post(reverse("anagrafica:dipendente_account_portale", args=[self.dip.id]),
                             {"account_scelta": "nessuno"}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])

    def test_scheda_mostra_il_riquadro_all_admin(self):
        r = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.dip.id]))
        self.assertContains(r, 'id="account-portale"')
        self.assertContains(r, reverse("anagrafica:dipendente_account_portale", args=[self.dip.id]))


class PrivilegiatoDaSchedaTests(AccountSchedaBase):
    def setUp(self):
        super().setUp()
        self.legacy = UtenteLegacy.objects.create(nome="ROSSI MARIO", email=EMAIL, password="h", attivo=True)
        self.root = User.objects.create_superuser("root_omonimo", "root@example.invalid", "x")
        Profile.objects.create(user=self.root, legacy_user_id=self.legacy.id)

    def test_superuser_senza_conferma_rifiutato(self):
        r = self._collega(account_scelta="collega", account_collega_id=str(self.legacy.id))
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self._utente_id())

    def test_admin_non_superuser_non_puo_confermare(self):
        operatore = User.objects.create_user("hr_operatore", "hr@example.invalid", "x")
        self.client.force_login(operatore)
        with patch("anagrafica.views._helpers._is_anagrafica_admin", return_value=True):
            self._collega(account_scelta="collega", account_collega_id=str(self.legacy.id), account_conferma_privilegiato="1")
        self.assertIsNone(self._utente_id())

    def test_superuser_con_conferma_collega_e_traccia(self):
        r = self._collega(account_scelta="collega", account_collega_id=str(self.legacy.id), account_conferma_privilegiato="1")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._utente_id(), self.legacy.id)
        log = AuditLog.objects.get(azione="ACCOUNT_PORTALE_COLLEGATO", oggetto_id=str(self.dip.id))
        self.assertTrue(log.dettaglio["conferma_privilegiato"])


class ScollegaTests(AccountSchedaBase):
    def setUp(self):
        super().setUp()
        self.legacy = UtenteLegacy.objects.create(nome="ROSSI MARIO", email=EMAIL, password=svc.AD_MANAGED, attivo=True)
        AnagraficaDipendente.objects.filter(pk=self.dip.id).update(utente_id=self.legacy.id)

    def test_scollega_con_audit_senza_cancellare_utente(self):
        r = self._scollega()
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self._utente_id())
        self.assertTrue(UtenteLegacy.objects.filter(pk=self.legacy.id).exists())
        log = AuditLog.objects.get(azione="ACCOUNT_PORTALE_SCOLLEGATO", oggetto_id=str(self.dip.id))
        self.assertEqual(log.dettaglio["utente_legacy_id"], self.legacy.id)

    def test_scollega_richiede_conferma(self):
        self.client.post(reverse("anagrafica:dipendente_account_scollega", args=[self.dip.id]))
        self.assertEqual(self._utente_id(), self.legacy.id)

    def test_scheda_collegata_mostra_utente_e_scollega(self):
        r = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.dip.id]))
        self.assertContains(r, reverse("anagrafica:dipendente_account_scollega", args=[self.dip.id]))
        self.assertContains(r, "Active Directory")


class NegatoNonAdminTests(AccountSchedaBase):
    def setUp(self):
        super().setUp()
        self.legacy = UtenteLegacy.objects.create(nome="ROSSI MARIO", email=EMAIL, password=svc.AD_MANAGED, attivo=True)
        self.client.force_login(User.objects.create_user("acc_semplice", "acc_semplice@example.invalid", "x"))

    def test_collega_negato(self):
        r = self._collega(account_scelta="collega", account_collega_id=str(self.legacy.id))
        self.assertIn(r.status_code, (302, 403))
        self.assertIsNone(self._utente_id())
        ajax = self.client.post(reverse("anagrafica:dipendente_account_portale", args=[self.dip.id]),
                                {"account_scelta": "collega", "account_collega_id": str(self.legacy.id)}, **AJAX)
        self.assertEqual(ajax.status_code, 403)
        self.assertEqual(ajax["Content-Type"].split(";")[0], "application/json")
        self.assertIsNone(self._utente_id())

    def test_scollega_negato(self):
        AnagraficaDipendente.objects.filter(pk=self.dip.id).update(utente_id=self.legacy.id)
        r = self._scollega(**AJAX)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r["Content-Type"].split(";")[0], "application/json")
        self.assertEqual(self._utente_id(), self.legacy.id)
        self.assertFalse(AuditLog.objects.filter(azione="ACCOUNT_PORTALE_SCOLLEGATO").exists())

    def test_anonimo_ajax_json(self):
        self.client.logout()
        r = self._scollega(**AJAX)
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(r["Content-Type"].split(";")[0], "application/json")

    def test_riquadro_non_mostrato(self):
        from django.test import RequestFactory

        from .views_account import contesto_scheda

        request = RequestFactory().get("/")
        request.user = User.objects.get(username="acc_semplice")
        self.assertIsNone(contesto_scheda(request, self.dip.id))
