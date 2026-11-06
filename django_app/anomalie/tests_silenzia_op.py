"""«Non voglio più aggiornamenti su questo OP»: pagina, pulsante e filtro delle mail."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie import controllo_service as cs
from anomalie import silenzia_op
from anomalie import views as anomalie_views
from anomalie.mail_action_models import AnomaliaOpSilenziata
from anomalie.mail_action_service import (
    _destinatari_resoconto,
    build_anomalie_action_email,
    send_anomalie_update_confirmation,
)
from anomalie.quality_models import AnomaliaBlocco, AnomaliaControllo, AnomaliaSegnalazioneMeta
from anomalie.tests_controllo import OP, LegacyTableMixin, _salva_finta
from core.middleware import is_acl_shared_path
from core.models import UserOnboarding

User = get_user_model()
SITE = "https://hub.example.local"
RECS = [
    {"email": "cc@example.local", "display": "Capo", "role": "CC"},
    {"email": "car@example.local", "display": "Incaricato", "role": "CAR"},
]


def _silenzia(email, op=OP):
    return AnomaliaOpSilenziata.objects.create(op_id=op, op_key=op.lower(), email=email)


@override_settings(
    LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    LDAP_ENABLED=False, SITE_URL=SITE,
)
class PaginaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sil-user", "persona@example.local", "x")
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.url = reverse("anomalie_op_silenzia")

    def test_senza_login_non_si_apre(self):
        r = self.client.get(self.url, {"op": OP})
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r["Location"])

    def test_pagina_aperta_a_chi_non_ha_permessi_sul_modulo(self):
        self.assertTrue(is_acl_shared_path(self.url))

    def test_aprire_il_link_non_silenzia(self):
        # I controlli antivirus della posta aprono i link: solo il POST cambia lo stato.
        self.client.force_login(self.user)
        r = self.client.get(self.url, {"op": OP})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Non voglio più aggiornamenti su questo OP")
        self.assertFalse(AnomaliaOpSilenziata.objects.exists())

    def test_silenzia_e_riattiva_solo_per_chi_e_collegato(self):
        _silenzia("altro@example.local")
        self.client.force_login(self.user)
        self.client.post(self.url, {"op": OP.upper(), "azione": "silenzia"})
        self.assertEqual(silenzia_op.email_silenziate(OP), {"altro@example.local", "persona@example.local"})
        r = self.client.get(self.url, {"op": OP})
        self.assertContains(r, "Non ricevi più gli aggiornamenti")
        self.client.post(self.url, {"op": OP, "azione": "riattiva"})
        self.assertEqual(silenzia_op.email_silenziate(OP), {"altro@example.local"})

    def test_due_volte_non_duplica(self):
        self.client.force_login(self.user)
        for _ in range(2):
            self.client.post(self.url, {"op": OP, "azione": "silenzia"})
        self.assertEqual(AnomaliaOpSilenziata.objects.count(), 1)

    def test_utente_senza_indirizzo_non_puo_silenziare(self):
        # L'email dell'utente può contenere il login legacy, che non è un indirizzo.
        user = User.objects.create_user("sil-login", "m.rossi", "x")
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)
        r = self.client.post(self.url, {"op": OP, "azione": "silenzia"}, follow=True)
        self.assertFalse(AnomaliaOpSilenziata.objects.exists())
        self.assertContains(r, "non è collegato un indirizzo")

    def test_api_pannello_solo_a_chi_gestisce_la_configurazione(self):
        riga = _silenzia("altro@example.local")
        url = reverse("api_anomalie_op_silenziato_riattiva", args=[riga.pk])
        self.client.force_login(self.user)
        with patch.object(anomalie_views, "_can_manage_anomalie_config", return_value=False):
            self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(AnomaliaOpSilenziata.objects.filter(pk=riga.pk).exists())
        with patch.object(anomalie_views, "_can_manage_anomalie_config", return_value=True):
            self.assertEqual(self.client.post(url).status_code, 200)
        self.assertFalse(AnomaliaOpSilenziata.objects.filter(pk=riga.pk).exists())


@override_settings(SITE_URL=SITE, LDAP_ENABLED=False, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MailTests(TestCase):
    def _rows(self):
        return [{"id": 1, "descrizione": "Graffio", "seriale": "SN-1", "avanzamento": "In attesa"}]

    def test_pulsante_nella_mail_di_decisione(self):
        _s, text, html = build_anomalie_action_email(
            recipient_email="cc@example.local", recipient_display="Capo", op_id="OP 1/A", op_nominativo="",
            anomalie_rows=self._rows(), action="aggiorna_avanzamento", token_str="tok",
            expires_at=timezone.now() + timedelta(hours=48), site_url=SITE,
        )
        link = f"{SITE}/anomalie-op-silenzia?op=OP%201%2FA"
        self.assertIn("Non voglio più aggiornamenti su questo OP", html)
        self.assertIn(link, html)
        self.assertIn(link, text)

    def _riepilogo(self, **kwargs):
        with patch("automazioni.services._resolve_op_recipients", return_value=RECS), \
                patch("anomalie.mail_action_service._resolve_segnalante_email", return_value=("", "")), \
                patch("anomalie.mail_action_service._fetch_pn_for_ops", return_value={}), \
                patch("anomalie.mail_action_service._resolve_lista_fissa_conferma", return_value=["cqi@example.local"]), \
                patch("anomalie.mail_action_service._resolve_lista_rdc_segnalazione", return_value=["rdc@example.local"]):
            return send_anomalie_update_confirmation(
                op_id=OP, op_nominativo="", anomalie_rows=self._rows(),
                updates_summary=[{"id": 1, "avanzamento": "In attesa", **kwargs}],
            )

    def test_riepilogo_senza_chi_ha_silenziato_e_con_il_pulsante(self):
        _silenzia("CQI@example.local".lower())
        _silenzia("car@example.local")
        self.assertTrue(self._riepilogo())
        self.assertEqual(mail.outbox[0].to, ["cc@example.local"])
        self.assertIn("Non voglio più aggiornamenti su questo OP", mail.outbox[0].alternatives[0][0])

    def test_riepilogo_rdc_arriva_comunque_alla_lista_dedicata(self):
        _silenzia("rdc@example.local")
        _silenzia("cqi@example.local")
        self.assertTrue(self._riepilogo(aprire_rdc=True))
        self.assertIn("rdc@example.local", mail.outbox[0].to)
        self.assertNotIn("cqi@example.local", mail.outbox[0].to)

    def test_silenziato_su_un_altro_op_riceve(self):
        _silenzia("car@example.local", op="ALTRO-OP")
        self.assertTrue(self._riepilogo())
        self.assertIn("car@example.local", mail.outbox[0].to)

    def test_resoconto_tiene_chi_deve_decidere(self):
        _silenzia("cc@example.local")
        _silenzia("car@example.local")
        with patch.object(cs, "_destinatari", return_value=(RECS[0], None)):
            self.assertEqual(_destinatari_resoconto(OP, RECS), ["cc@example.local"])

    def test_errore_di_lettura_non_perde_le_mail(self):
        with patch("anomalie.mail_action_models.AnomaliaOpSilenziata.objects") as manager:
            manager.filter.side_effect = RuntimeError("db")
            self.assertEqual(silenzia_op.togli_silenziati(OP, ["a@example.local"]), ["a@example.local"])


@override_settings(
    LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL=SITE,
)
class MailControlloTests(LegacyTableMixin, TestCase):
    def setUp(self):
        self.crea_tabella()
        user = User.objects.create_user(username="sil-ctl", password="pass12345")
        self.controllo = AnomaliaControllo.objects.create(
            op_id=OP, fase="Lavorazione", operatore=user, operatore_display="Operatore Test",
            destinatari_extra=[
                {"email": "extra@example.local", "nome": "Persona Extra"},
                {"email": "resta@example.local", "nome": "Persona Resta"},
            ],
        )
        blocco = AnomaliaBlocco.objects.create(
            controllo=self.controllo, ordine=1, fase="Lavorazione", seriali=["LCN00001"], seriale_label="LCN00001",
        )
        r = _salva_finta(None, {"op_id": OP, "sn": "LCN00001", "desc": "Graffio", "avanzamento": "In attesa"})
        AnomaliaSegnalazioneMeta.objects.create(
            anomalia_id=r["local_id"], fase="Lavorazione", controllo=self.controllo, blocco=blocco,
        )
        cs.accoda_notifica(self.controllo, [r["local_id"]])

    def tearDown(self):
        self.elimina_tabella()

    def _invia(self):
        with patch("automazioni.services._resolve_op_recipients", return_value=RECS), \
                patch("anomalie.views._op_is_benestare", return_value=False), \
                patch("anomalie.mail_action_service.send_anomalie_update_confirmation", return_value=True):
            return cs.invia_mail_controllo(self.controllo)

    def test_copia_e_persona_aggiunta_silenziate_escono(self):
        _silenzia("car@example.local")
        _silenzia("extra@example.local")
        esito = self._invia()
        self.assertTrue(esito["sent"])
        self.assertEqual(esito["extra"], ["Persona Resta"])
        self.assertEqual(mail.outbox[0].to, ["cc@example.local"])
        self.assertEqual(mail.outbox[0].cc, ["resta@example.local"])

    def test_chi_deve_decidere_riceve_anche_se_ha_silenziato(self):
        _silenzia("cc@example.local")
        self.assertTrue(self._invia()["sent"])
        self.assertEqual(mail.outbox[0].to, ["cc@example.local"])
