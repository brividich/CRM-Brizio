from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .mail_inviate import registra
from .models import (
    AutomationAction,
    AutomationActionLogStatus,
    AutomationActionType,
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
    AutomationRunLog,
    AutomationRunLogStatus,
    EmailInviata,
)
from .services import execute_action

User = get_user_model()


class RegistraTests(TestCase):
    def test_scrive_riga_con_destinatari_puliti(self):
        registra(origine="assenze_modifica", destinatari=["A@Example.com", "a@example.com", ""],
                 copia="capo@example.com", oggetto="Oggetto", sorgente="assenze", record_id=12)
        riga = EmailInviata.objects.get()
        self.assertEqual(riga.destinatari, "a@example.com")
        self.assertEqual(riga.copia, "capo@example.com")
        self.assertEqual(riga.record_id, "12")
        self.assertEqual(riga.esito, EmailInviata.ESITO_INVIATA)

    def test_errore_segnato(self):
        registra(origine="automazione", destinatari="x@example.com", errore="SMTPException: down")
        self.assertEqual(EmailInviata.objects.get().esito, EmailInviata.ESITO_ERRORE)

    def test_non_solleva_mai(self):
        with patch("automazioni.models.EmailInviata.objects.create", side_effect=RuntimeError("db")):
            registra(origine="automazione", destinatari="x@example.com")


@override_settings(DEFAULT_FROM_EMAIL="noreply@test.local")
class RegistroDaAzioniTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="mail-registro", name="Mail registro", source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        self.payload = {"id": 55, "tipo_assenza": "Ferie"}
        self.run_log = AutomationRunLog.objects.create(
            rule=self.rule, source_code="assenze", operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.SUCCESS, payload_json=self.payload,
        )
        self.action = AutomationAction.objects.create(
            rule=self.rule, order=1, action_type=AutomationActionType.SEND_EMAIL,
            config_json={"to": "dip@test.local", "cc": "capo@test.local",
                         "subject_template": "Richiesta {id} approvata", "body_text_template": "ok"},
        )

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_email_registra_invio(self, mock_email_class):
        mock_email_class.return_value = MagicMock(**{"send.return_value": 1})
        result = execute_action(self.action, self.payload, run_log=self.run_log)
        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        riga = EmailInviata.objects.get()
        self.assertEqual((riga.origine, riga.destinatari, riga.copia), ("automazione", "dip@test.local", "capo@test.local"))
        self.assertEqual((riga.oggetto, riga.sorgente, riga.record_id), ("Richiesta 55 approvata", "assenze", "55"))
        self.assertEqual((riga.regola_id, riga.run_log_id), (self.rule.id, self.run_log.id))

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_email_fallito_registra_errore(self, mock_email_class):
        mock_email_class.return_value = MagicMock(**{"send.side_effect": OSError("smtp giu")})
        result = execute_action(self.action, self.payload, run_log=self.run_log)
        self.assertNotEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        riga = EmailInviata.objects.get()
        self.assertEqual(riga.esito, EmailInviata.ESITO_ERRORE)
        self.assertIn("smtp giu", riga.errore)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistroMailAssenzeTests(TestCase):
    def test_mail_modifica_registrata(self):
        from assenze.mail_modifica_service import send_assenza_modificata_notification

        send_assenza_modificata_notification(
            {"id": 9, "copia_nome": "Mario Test", "tipo_assenza": "Ferie"},
            modifiche=[{"campo": "Inizio", "prima": "a", "dopo": "b"}], tipo_display="Ferie",
        )
        riga = EmailInviata.objects.get()
        self.assertEqual((riga.origine, riga.sorgente, riga.record_id), ("assenze_modifica", "assenze", "9"))

    def test_mail_eliminazione_registrata(self):
        from assenze.mail_delete_service import send_assenza_deleted_notification

        send_assenza_deleted_notification(
            {"id": 10, "copia_nome": "Mario Test", "email_esterna": "dip@example.com", "tipo_assenza": "Ferie"},
            tipo_display="Ferie",
        )
        riga = EmailInviata.objects.get()
        self.assertEqual((riga.origine, riga.record_id), ("assenze_eliminazione", "10"))
        self.assertIn("dip@example.com", riga.destinatari)


class MailInviatePageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="mail.admin", email="mail.admin@example.com", password="x")
        UserOnboarding.objects.update_or_create(
            user=self.admin, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()},
        )
        registra(origine="automazione", destinatari="dip.uno@example.com", oggetto="Ferie approvate",
                 sorgente="assenze", record_id=101)
        registra(origine="assenze_modifica", destinatari="altro@example.com", oggetto="Richiesta modificata",
                 sorgente="assenze", record_id=202, errore="SMTPException: down")
        self.url = reverse("admin_portale:automazioni_mail_inviate")

    def test_anonimo_rimandato_al_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_elenco_e_filtri(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertContains(response, "dip.uno@example.com")
        self.assertContains(response, "altro@example.com")
        self.assertContains(response, "Mail inviate")

        response = self.client.get(self.url, {"q": "dip.uno"})
        self.assertContains(response, "dip.uno@example.com")
        self.assertNotContains(response, "altro@example.com")

        response = self.client.get(self.url, {"richiesta": "202"})
        self.assertContains(response, "altro@example.com")
        self.assertNotContains(response, "dip.uno@example.com")

        response = self.client.get(self.url, {"esito": "errore", "dal": "data-sbagliata"})
        self.assertContains(response, "SMTPException: down")
        self.assertNotContains(response, "dip.uno@example.com")


class RetentionMailInviateTests(TestCase):
    def test_cleanup_cancella_righe_vecchie(self):
        registra(origine="automazione", destinatari="vecchia@example.com")
        registra(origine="automazione", destinatari="nuova@example.com")
        EmailInviata.objects.filter(destinatari="vecchia@example.com").update(
            inviata_il=timezone.now() - timedelta(days=200)
        )
        call_command("cleanup_run_logs", apply=True, days=90, stdout=StringIO())
        self.assertEqual(list(EmailInviata.objects.values_list("destinatari", flat=True)), ["nuova@example.com"])
