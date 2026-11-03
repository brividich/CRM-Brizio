from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from automazioni.models import EmailInviata

from .models import AssenzaAvvisoCertificato, AssenzeImpostazioniHR

User = get_user_model()

MAIL = override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")


def _malattia(**extra):
    row = {
        "id": 501, "copia_nome": "Mario Test", "email_esterna": "mario.test@example.com",
        "tipo_assenza": "Malattia", "data_inizio": datetime(2026, 11, 2, 8, 0), "data_fine": datetime(2026, 11, 4, 17, 0),
        "motivazione_richiesta": "", "certificato_medico": "", "moderation_status": 2, "consenso": "In attesa",
    }
    row.update(extra)
    return row


@MAIL
class EsitoDipendenteTests(TestCase):
    def test_mail_al_dipendente_con_esito(self):
        from .mail_esito_service import send_esito_dipendente

        ok = send_esito_dipendente(_malattia(), consenso="Rifiutato", tipo_display="Malattia",
                                   note="Manca il giorno", deciso_da="Capo Test")
        self.assertTrue(ok)
        msg = mail.outbox[-1]
        self.assertEqual(msg.to, ["mario.test@example.com"])
        self.assertEqual(msg.subject, "Richiesta Malattia rifiutata")
        self.assertIn("Nota: Manca il giorno", msg.body)
        self.assertIn("Certificato arrivato: No", msg.body)
        self.assertEqual(EmailInviata.objects.get().origine, "assenze_esito")

    def test_senza_email_valida_non_parte(self):
        from .mail_esito_service import send_esito_dipendente

        self.assertFalse(send_esito_dipendente(_malattia(email_esterna="m.test"), consenso="Approvato", tipo_display="Malattia"))
        self.assertEqual(mail.outbox, [])

    @patch("assenze.views._helpers._sp_enqueue_upsert", return_value={"ok": True})
    @patch("assenze.views._helpers._update_assenza", return_value=True)
    @patch("assenze.views._helpers._legacy_identity", return_value=("Capo Test", "capo@example.com", 9))
    def test_decisione_dal_portale_avvisa_il_dipendente(self, *_):
        from .views._helpers import _applica_moderazione

        request = RequestFactory().post("/")
        request.user = User.objects.create_user(username="capo.test", password="x")
        _applica_moderazione(request, 501, _malattia(tipo_assenza="Ferie"), "Approvato", "")
        msg = mail.outbox[-1]
        self.assertEqual(msg.to, ["mario.test@example.com"])
        self.assertEqual(msg.subject, "Richiesta Ferie approvata")
        self.assertIn("Decisa da: Capo Test", msg.body)

    @patch("assenze.views._helpers._sp_enqueue_upsert", return_value={"ok": True})
    @patch("assenze.views._helpers._update_assenza", return_value=True)
    @patch("assenze.views._helpers._legacy_identity", return_value=("Capo Test", "capo@example.com", 9))
    def test_decisione_dal_portale_chiude_il_link_della_mail(self, *_):
        from automazioni.approval_links import create_link, decide_with_link
        from automazioni.models import AutomationApproval, AutomationRunLog

        from .views._helpers import _applica_moderazione

        def _approval(record_id):
            run_log = AutomationRunLog.objects.create(
                source_code="assenze", operation_type="INSERT", status="waiting_approval",
                payload_json={"id": record_id},
            )
            return AutomationApproval.objects.create(
                run_log=run_log, approver_emails=["capo@example.com"], subject="Approva",
                resume_payload={"id": record_id}, approved_actions=[{"action_type": "send_email", "config_json": {}}],
            )

        mia = _approval(501)
        altra = _approval(502)
        raw = create_link(mia, "capo@example.com")

        request = RequestFactory().post("/")
        request.user = User.objects.create_user(username="capo.test", password="x")
        _applica_moderazione(request, 501, _malattia(), "Approvato", "")

        mia.refresh_from_db()
        self.assertEqual(mia.status, "approved")
        self.assertEqual(mia.decided_by_email, "capo@example.com")
        self.assertEqual(mia.run_log.status, "success")
        self.assertEqual(AutomationApproval.objects.get(pk=altra.pk).status, "pending")

        inviate = len(mail.outbox)
        esito = decide_with_link(raw, "approved")
        self.assertEqual(esito["code"], "already_decided")
        self.assertEqual(len(mail.outbox), inviate)


@MAIL
@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
@patch("assenze.mail_modifica_service._hr_mailbox", return_value="")
@patch("assenze.views._helpers._load_capi_options", return_value=[])
@patch("assenze.views._helpers._sp_enqueue_upsert", return_value={"ok": True})
@patch("assenze.views._helpers._sharepoint_managed_error", return_value=None)
@patch("assenze.views._helpers._legacy_identity", return_value=("Mario Test", "mario.test@example.com", 77))
@patch("assenze.views._helpers._assenze_permissions", return_value={"can_insert": True})
class CertificatoSuMalattiaApprovataTests(TestCase):
    def setUp(self):
        # Superuser per passare l'ACLMiddleware; permessi e identità sono mock.
        self.user = User.objects.create_superuser(username="mario.test", email="mario.test@example.com", password="x")
        self.client.force_login(self.user)
        self.url = reverse("assenze_api_mia_update", args=[501])

    def _post(self, body):
        return self.client.post(self.url, content_type="application/json", data=body)

    @patch("assenze.views._helpers._update_assenza", return_value=True)
    @patch("assenze.views._helpers._get_assenza", return_value=_malattia(moderation_status=0, consenso="Approvato"))
    def test_spunta_vale_come_modifica(self, _get, mock_update, *_):
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True, "completed_at": timezone.now()})
        response = self._post('{"certificato_medico":"Arrivato","tipo":"Ferie"}')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(mock_update.call_args.args[1]), {"certificato_medico", "modified_datetime"})
        msg = mail.outbox[-1]
        self.assertIn("Richiesta modificata", msg.subject)
        self.assertIn("Motivo della modifica: Certificato medico arrivato", msg.body)
        self.assertIn("Certificato arrivato: Sì", msg.body)

    @patch("assenze.views._helpers._update_assenza", return_value=True)
    @patch("assenze.views._helpers._get_assenza", return_value=_malattia(moderation_status=0, consenso="Approvato"))
    def test_altri_cambi_rifiutati(self, _get, mock_update, *_):
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True, "completed_at": timezone.now()})
        response = self._post('{"certificato_medico":""}')
        self.assertEqual(response.status_code, 400)
        mock_update.assert_not_called()


@MAIL
@patch("assenze.mail_modifica_service._hr_mailbox", return_value="")
@patch("assenze.views._helpers._has_assenze_column", return_value=True)
@patch("assenze.views._helpers._table_exists", return_value=True)
class AvvisoCertificatoTests(TestCase):
    def _righe(self):
        return [
            _malattia(id=601),
            _malattia(id=602, certificato_medico="Arrivato"),
            _malattia(id=603, tipo_assenza="Ferie"),
        ]

    def test_una_mail_ad_assenza_una_volta_sola(self, *_):
        from .certificato_avviso import invia_avvisi

        now = timezone.make_aware(datetime(2026, 11, 5, 8, 30))
        with patch("assenze.views._helpers._fetch_all_dict", return_value=self._righe()) as mock_fetch:
            esito = invia_avvisi(now)
            self.assertEqual(esito, {"email_sent": 1, "malattie": 1})
            dal, al = mock_fetch.call_args.args[1]
            self.assertEqual(al, datetime(2026, 11, 4))  # iniziate fino al 03/11 compreso
            self.assertEqual(invia_avvisi(now), {"email_sent": 0, "malattie": 0})
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["assenza@costruzioninovicrom.it"])
        self.assertIn("MARIO TEST", msg.body)
        self.assertIn("#601", msg.body)
        self.assertNotIn("#602", msg.body)
        self.assertEqual(list(AssenzaAvvisoCertificato.objects.values_list("assenza_id", flat=True)), [601])
        self.assertEqual(EmailInviata.objects.get().origine, "assenze_certificato")

    def test_spento_nelle_impostazioni(self, *_):
        from .certificato_avviso import invia_avvisi

        imp = AssenzeImpostazioniHR.get_solo()
        imp.certificato_avviso_attivo = False
        imp.save()
        self.assertIn("skipped", invia_avvisi())
        self.assertEqual(mail.outbox, [])
