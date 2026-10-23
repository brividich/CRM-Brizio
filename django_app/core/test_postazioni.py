"""Postazioni condivise (core.postazioni): account del PC → scelta operatore → PIN.

Dati sintetici: nessun nome o account reale.
"""
from __future__ import annotations

import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from core import postazioni
from core.legacy_models import UtenteLegacy
from core.legacy_utils import sync_django_user_from_legacy
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    AuditLog,
    OperatorePostazione,
    PinPostazione,
    PostazioneCondivisa,
    UserOnboarding,
)

PIN = "4826"


class ErrorePinTests(TestCase):
    def test_regole(self):
        self.assertEqual(postazioni.errore_pin("4826"), "")
        self.assertEqual(postazioni.errore_pin("90817263"), "")
        self.assertIn("da 4 a 8", postazioni.errore_pin("123"))
        self.assertIn("da 4 a 8", postazioni.errore_pin("123456789"))
        self.assertIn("da 4 a 8", postazioni.errore_pin("12a4"))
        self.assertIn("ripetuta", postazioni.errore_pin("7777"))
        self.assertIn("sequenza", postazioni.errore_pin("1234"))
        self.assertIn("sequenza", postazioni.errore_pin("6543"))


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class PostazioneTests(TestCase):
    def setUp(self):
        def legacy(nome, email, ruolo="operatore", ruolo_id=2):
            return UtenteLegacy.objects.create(nome=nome, email=email, password="x", ruolo=ruolo,
                                               attivo=True, deve_cambiare_password=False, ruolo_id=ruolo_id)

        self.l_account = legacy("PC Sintetico", "pc.sintetico@example.local")
        self.l_op1 = legacy("Rossi Operatore", "op.uno@example.local")
        self.l_op2 = legacy("Verdi Operatrice", "op.due@example.local")
        self.l_admin = legacy("Admin Sintetico", "admin.sint@example.local", ruolo="admin", ruolo_id=1)
        self.l_esterno = legacy("Bianchi Esterno", "esterno@example.local")
        self.l_op3 = legacy("Gialli NonAbilitato", "op.tre@example.local")
        self.account = sync_django_user_from_legacy(self.l_account)
        self.op1 = sync_django_user_from_legacy(self.l_op1)
        self.op2 = sync_django_user_from_legacy(self.l_op2)
        self.esterno = sync_django_user_from_legacy(self.l_esterno)
        for u in (self.op1, self.op2, self.esterno):
            UserOnboarding.objects.create(user=u, completed=True)
        self.gruppo = AccessGroup.objects.create(code="operatori-controllo-test", label="Operatori controllo")
        for lu in (self.l_account, self.l_op1, self.l_op2, self.l_op3, self.l_admin):
            AccessGroupMembership.objects.create(group=self.gruppo, legacy_user_id=lu.id)
        # Il client di test arriva da 127.0.0.1: è il PC registrato.
        self.postazione = PostazioneCondivisa.objects.create(
            nome="Sala misure test", account_legacy_user_id=self.l_account.id, ip_pc="127.0.0.1",
            gruppo=self.gruppo, minuti_inattivita=10)
        # l_op3 è nel gruppo ma non è abilitato su questo PC.
        for lu in (self.l_account, self.l_op1, self.l_op2, self.l_admin):
            OperatorePostazione.objects.create(postazione=self.postazione, legacy_user_id=lu.id)
        postazioni.imposta_pin(self.l_op1.id, PIN)

    def _entra_account(self):
        # force_login non porta l'IP: il PC si riconosce alla prima richiesta.
        self.client.force_login(self.account)
        self.assertEqual(self.client.get(reverse("postazione_home")).status_code, 200)
        stato = self.client.session.get(postazioni.SESSIONE)
        self.assertEqual(stato["postazione"], self.postazione.pk)
        self.assertIsNone(stato["operatore"])

    def _utente_sessione(self):
        return int(self.client.session.get("_auth_user_id"))

    def _entra_operatore(self):
        self._entra_account()
        resp = self.client.post(reverse("postazione_entra"), {"operatore": self.l_op1.id, "pin": PIN})
        self.assertRedirects(resp, reverse("dashboard_home"), fetch_redirect_response=False)
        self.assertEqual(self._utente_sessione(), self.op1.pk)

    # ── account della postazione in attesa ──

    def test_account_vede_solo_la_scelta_operatore(self):
        self._entra_account()
        resp = self.client.get(reverse("dashboard_home"))
        self.assertRedirects(resp, reverse("postazione_home"), fetch_redirect_response=False)
        resp = self.client.get(reverse("postazione_home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Rossi Operatore")
        self.assertContains(resp, "Verdi Operatrice")
        self.assertNotContains(resp, "Admin Sintetico")  # gli amministratori non entrano con il PIN
        self.assertNotContains(resp, "PC Sintetico")
        self.assertNotContains(resp, "Gialli NonAbilitato")  # nel gruppo ma non abilitato su questo PC

    def test_account_in_attesa_api_json_403(self):
        self._entra_account()
        resp = self.client.get("/api/qualcosa/", HTTP_ACCEPT="application/json")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["reason"], "postazione_condivisa")

    def test_utente_normale_non_vede_la_postazione(self):
        self.client.force_login(self.op2)
        self.assertNotIn(postazioni.SESSIONE, self.client.session)
        resp = self.client.get(reverse("postazione_home"))
        self.assertRedirects(resp, reverse("dashboard_home"), fetch_redirect_response=False)

    # ── PIN ──

    def test_pin_giusto_sessione_dell_operatore_con_audit(self):
        self._entra_operatore()
        stato = self.client.session[postazioni.SESSIONE]
        self.assertEqual((stato["operatore"], stato["account"]), (self.op1.pk, self.account.pk))
        self.assertTrue(AuditLog.objects.filter(azione="postazione_operatore_entra").exists())

    def test_pin_errato_poi_blocco_con_mail(self):
        self._entra_account()
        url = reverse("postazione_entra")
        resp = self.client.post(url, {"operatore": self.l_op1.id, "pin": "9999"})
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "Restano 4 tentativi", status_code=403)
        for _ in range(postazioni.MAX_TENTATIVI - 1):
            resp = self.client.post(url, {"operatore": self.l_op1.id, "pin": "9999"})
        self.assertContains(resp, "PIN bloccato", status_code=403)
        self.assertIsNotNone(PinPostazione.objects.get(legacy_user_id=self.l_op1.id).bloccato_il)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("bloccato", mail.outbox[0].subject.lower() + mail.outbox[0].body.lower())
        # Bloccato: nemmeno il PIN giusto entra; nessun'altra mail.
        resp = self.client.post(url, {"operatore": self.l_op1.id, "pin": PIN})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._utente_sessione(), self.account.pk)
        self.assertEqual(len(mail.outbox), 1)
        # Al SOC: un evento e un alert «PIN bloccato».
        from security.models import SecurityAlert, SecurityEventRecord

        self.assertEqual(SecurityEventRecord.objects.filter(event_type="postazione_pin_bloccato").count(), 1)
        self.assertIn("PIN bloccato", SecurityAlert.objects.get().title)

    def test_operatore_fuori_dal_gruppo_o_admin_rifiutato(self):
        postazioni.imposta_pin(self.l_esterno.id, PIN)
        postazioni.imposta_pin(self.l_admin.id, PIN)
        self._entra_account()
        postazioni.imposta_pin(self.l_op3.id, PIN)
        for legacy_id in (self.l_esterno.id, self.l_admin.id, self.l_account.id, self.l_op3.id):
            resp = self.client.post(reverse("postazione_entra"), {"operatore": legacy_id, "pin": PIN})
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(self._utente_sessione(), self.account.pk)

    def test_pin_fuori_dalla_postazione_non_vale(self):
        self.client.force_login(self.esterno)
        resp = self.client.post(reverse("postazione_entra"), {"operatore": self.l_op1.id, "pin": PIN})
        self.assertRedirects(resp, reverse("dashboard_home"), fetch_redirect_response=False)
        self.assertEqual(self._utente_sessione(), self.esterno.pk)

    def test_hash_del_pin_mai_nell_audit(self):
        record = PinPostazione.objects.get(legacy_user_id=self.l_op1.id)
        for riga in AuditLog.objects.all():
            self.assertNotIn(record.pin_hash, str(riga.dettaglio))

    # ── PC ──

    def test_pc_non_registrato_solo_pagina_di_blocco(self):
        PostazioneCondivisa.objects.filter(pk=self.postazione.pk).update(ip_pc="10.0.0.50")
        self.client.force_login(self.account)
        resp = self.client.get(reverse("postazione_home"))
        self.assertContains(resp, "non è registrato", status_code=403)
        self.assertContains(resp, "127.0.0.1", status_code=403)
        self.assertRedirects(self.client.get(reverse("dashboard_home")), reverse("postazione_home"),
                             fetch_redirect_response=False, target_status_code=403)
        resp = self.client.get("/api/qualcosa/", HTTP_ACCEPT="application/json")
        self.assertEqual(resp.json()["reason"], "postazione_pc_non_registrato")
        self.client.post(reverse("postazione_entra"), {"operatore": self.l_op1.id, "pin": PIN})
        self.assertEqual(self._utente_sessione(), self.account.pk)
        # Registrato il PC, la stessa sessione passa a «Chi sei?».
        PostazioneCondivisa.objects.filter(pk=self.postazione.pk).update(ip_pc="127.0.0.1")
        self.assertContains(self.client.get(reverse("postazione_home")), "Rossi Operatore")

    def test_stesso_account_su_due_pc_operatori_diversi(self):
        pc2 = PostazioneCondivisa.objects.create(
            nome="Sala misure due", account_legacy_user_id=self.l_account.id, ip_pc="10.0.0.7", gruppo=self.gruppo)
        OperatorePostazione.objects.create(postazione=pc2, legacy_user_id=self.l_op2.id)
        self.client.force_login(self.account)
        resp = self.client.get(reverse("postazione_home"), REMOTE_ADDR="10.0.0.7")
        self.assertContains(resp, "Sala misure due")
        self.assertContains(resp, "Verdi Operatrice")
        self.assertNotContains(resp, "Rossi Operatore")
        resp = self.client.post(reverse("postazione_entra"), {"operatore": self.l_op1.id, "pin": PIN},
                                REMOTE_ADDR="10.0.0.7")
        self.assertEqual(resp.status_code, 400)

    def test_sessione_portata_su_un_altro_pc_si_chiude(self):
        self._entra_operatore()
        resp = self.client.get(reverse("dashboard_home"), REMOTE_ADDR="10.0.0.99")
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditLog.objects.filter(azione="postazione_altro_pc").exists())
        from security.models import SecurityEventRecord

        evento = SecurityEventRecord.objects.get(event_type="postazione_altro_pc")
        self.assertEqual(evento.payload["ip"], "10.0.0.99")

    def test_registro_uso(self):
        self._entra_operatore()
        self.client.post(reverse("postazione_cambio"))
        self.client.post(reverse("postazione_entra"), {"operatore": self.l_op1.id, "pin": "9999"})
        dati = postazioni.registro_uso(self.postazione.pk, 30)
        self.assertEqual(len(dati["sessioni"]), 1)
        sessione = dati["sessioni"][0]
        self.assertEqual(sessione["uscita_motivo"], "Cambio operatore")
        self.assertIsNotNone(sessione["uscita"])
        self.assertEqual([e["evento"] for e in dati["eventi"]], ["PIN sbagliato"])
        self.assertEqual(dati["eventi"][0]["chi"], "Rossi Operatore")  # la persona, non l'account del PC
        self.assertEqual(postazioni.registro_uso(999, 30), {"sessioni": [], "eventi": []})

    # ── uscita ──

    def test_cambio_operatore_torna_alla_postazione(self):
        self._entra_operatore()
        resp = self.client.post(reverse("postazione_cambio"))
        self.assertRedirects(resp, reverse("postazione_home"), fetch_redirect_response=False)
        self.assertEqual(self._utente_sessione(), self.account.pk)
        self.assertIsNone(self.client.session[postazioni.SESSIONE]["operatore"])
        self.assertTrue(AuditLog.objects.filter(azione="postazione_operatore_esce").exists())

    def test_esci_dell_operatore_torna_alla_postazione(self):
        self._entra_operatore()
        resp = self.client.post(reverse("logout"))
        self.assertRedirects(resp, reverse("postazione_home"), fetch_redirect_response=False)
        self.assertEqual(self._utente_sessione(), self.account.pk)
        # Dalla scelta operatore «Chiudi la postazione» chiude tutto.
        self.client.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inattivita_riporta_alla_postazione(self):
        self._entra_operatore()
        sessione = self.client.session
        stato = sessione[postazioni.SESSIONE]
        stato["attivita"] = int(time.time()) - 11 * 60
        sessione[postazioni.SESSIONE] = stato
        sessione.save()
        resp = self.client.get(reverse("dashboard_home"))
        self.assertRedirects(resp, reverse("postazione_home") + "?motivo=inattivita", fetch_redirect_response=False)
        self.assertEqual(self._utente_sessione(), self.account.pk)

    def test_aggiornamento_in_background_non_conta_come_attivita(self):
        self._entra_operatore()
        sessione = self.client.session
        stato = sessione[postazioni.SESSIONE]
        prima = int(time.time()) - 5 * 60
        stato["attivita"] = prima
        sessione[postazioni.SESSIONE] = stato
        sessione.save()
        self.client.get(reverse("dashboard_home"), HTTP_HX_REQUEST="true")
        self.assertEqual(self.client.session[postazioni.SESSIONE]["attivita"], prima)

    def test_postazione_disattivata_chiude_la_sessione(self):
        self._entra_account()
        PostazioneCondivisa.objects.filter(pk=self.postazione.pk).update(attiva=False)
        resp = self.client.get(reverse("postazione_home"))
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    # ── impostare il PIN con la password ──

    def test_imposta_pin_con_password_ed_entra(self):
        self._entra_account()
        url = reverse("postazione_imposta_pin", args=[self.l_op2.id])
        self.assertEqual(self.client.get(url).status_code, 200)
        with patch("core.postazioni_views.authenticate", return_value=self.op2) as auth:
            resp = self.client.post(url, {"username": "op.due@example.local", "password": "segreta",
                                          "pin": "5093", "pin_conferma": "5093"})
        auth.assert_called_once()
        self.assertRedirects(resp, reverse("dashboard_home"), fetch_redirect_response=False)
        self.assertEqual(self._utente_sessione(), self.op2.pk)
        self.assertEqual(postazioni.verifica_pin(self.l_op2.id, "5093")["esito"], "ok")

    def test_imposta_pin_rifiuta_password_di_un_altro_e_pin_deboli(self):
        self._entra_account()
        url = reverse("postazione_imposta_pin", args=[self.l_op2.id])
        with patch("core.postazioni_views.authenticate", return_value=self.op1):
            resp = self.client.post(url, {"username": "op.uno@example.local", "password": "x",
                                          "pin": "5093", "pin_conferma": "5093"})
        self.assertContains(resp, "password non corretti", status_code=400)
        with patch("core.postazioni_views.authenticate", return_value=self.op2):
            resp = self.client.post(url, {"username": "op.due@example.local", "password": "x",
                                          "pin": "1234", "pin_conferma": "1234"})
        self.assertContains(resp, "sequenza", status_code=400)
        self.assertFalse(PinPostazione.objects.filter(legacy_user_id=self.l_op2.id).exists())
        self.assertEqual(self._utente_sessione(), self.account.pk)

    def test_imposta_pin_sblocca(self):
        PinPostazione.objects.filter(legacy_user_id=self.l_op1.id).update(
            tentativi_falliti=postazioni.MAX_TENTATIVI, bloccato_il="2026-01-01T00:00:00Z")
        postazioni.imposta_pin(self.l_op1.id, "5093")
        self.assertEqual(postazioni.verifica_pin(self.l_op1.id, "5093")["esito"], "ok")


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class AdminPostazioniTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin.test", "admin.test@example.local", "x")
        self.client.force_login(self.admin)
        self.l_pc = UtenteLegacy.objects.create(nome="PC Due", email="pc.due@example.local", password="x",
                                                ruolo="operatore", attivo=True, ruolo_id=2)
        self.l_admin = UtenteLegacy.objects.create(nome="Admin Due", email="admin.due@example.local", password="x",
                                                   ruolo="admin", attivo=True, ruolo_id=1)
        self.gruppo = AccessGroup.objects.create(code="gruppo-pc-test", label="Gruppo PC")

    def _salva(self, account_id, minuti=10, ip="192.168.10.25"):
        return self.client.post(reverse("admin_portale:postazioni_condivise_azione"), {
            "azione": "salva", "nome": "PC prova", "account": account_id, "gruppo": self.gruppo.pk,
            "minuti_inattivita": minuti, "attiva": "1", "ip_pc": ip,
        })

    def test_pagina_e_creazione(self):
        self.assertEqual(self.client.get(reverse("admin_portale:postazioni_condivise")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin_portale:postazioni_condivise") + "?guida=1").status_code, 200)
        self._salva(self.l_pc.id)
        self.assertTrue(PostazioneCondivisa.objects.filter(account_legacy_user_id=self.l_pc.id).exists())

    def test_account_amministratore_minuti_e_ip_non_validi_rifiutati(self):
        self._salva(self.l_admin.id)
        self._salva(self.l_pc.id, minuti=0)
        self._salva(self.l_pc.id, minuti=61)
        self._salva(self.l_pc.id, ip="")
        self._salva(self.l_pc.id, ip="pc-zeiss")
        self.assertFalse(PostazioneCondivisa.objects.exists())

    def test_stesso_account_piu_pc_ma_ip_unico(self):
        self._salva(self.l_pc.id, ip="192.168.10.25")
        self._salva(self.l_pc.id, ip="192.168.10.26")
        self._salva(self.l_pc.id, ip="192.168.10.25")  # IP già registrato
        self.assertEqual(sorted(PostazioneCondivisa.objects.values_list("ip_pc", flat=True)),
                         ["192.168.10.25", "192.168.10.26"])

    def test_operatori_del_pc(self):
        self._salva(self.l_pc.id)
        pc = PostazioneCondivisa.objects.get()
        op = UtenteLegacy.objects.create(nome="Op Admin Test", email="op.at@example.local", password="x",
                                         ruolo="operatore", attivo=True, ruolo_id=2)
        AccessGroupMembership.objects.create(group=self.gruppo, legacy_user_id=op.id)
        url = reverse("admin_portale:postazioni_condivise_azione")
        self.assertContains(self.client.get(reverse("admin_portale:postazioni_condivise") + f"?operatori={pc.pk}"),
                            "Op Admin Test")
        # Un id fuori dal gruppo si ignora.
        self.client.post(url, {"azione": "operatori", "id": pc.pk, "abilitati": [op.id, 999999]})
        self.assertEqual(list(OperatorePostazione.objects.values_list("legacy_user_id", flat=True)), [op.id])
        self.client.post(url, {"azione": "operatori", "id": pc.pk})
        self.assertFalse(OperatorePostazione.objects.exists())

    def test_azzera_pin(self):
        self._salva(self.l_pc.id)
        postazioni.imposta_pin(4242, PIN)
        self.client.post(reverse("admin_portale:postazioni_condivise_azione"), {
            "azione": "azzera_pin", "id": PostazioneCondivisa.objects.get().pk, "legacy_user_id": 4242})
        self.assertFalse(PinPostazione.objects.filter(legacy_user_id=4242).exists())

    def test_registro_pagina_ed_excel(self):
        self.assertEqual(self.client.get(reverse("admin_portale:postazioni_registro") + "?giorni=7").status_code, 200)
        resp = self.client.get(reverse("admin_portale:postazioni_registro_excel") + "?giorni=90")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

    def test_non_amministratore_negato(self):
        utente = get_user_model().objects.create_user("normale.test", password="x")
        UserOnboarding.objects.create(user=utente, completed=True)
        self.client.force_login(utente)
        resp = self.client.get(reverse("admin_portale:postazioni_condivise"))
        self.assertIn(resp.status_code, (302, 403))
