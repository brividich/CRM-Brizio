"""Affidabilità delle automazioni (10/11/2026): retry senza doppioni, coda a budget,
URL con segreti fuori dai log, esiti HTTP, decisioni senza attese nel thread web.

Dati sintetici: nessuna email, persona o URL reale; nessuna chiamata di rete.
"""
from __future__ import annotations

import smtplib
import socket
from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from automazioni import services
from automazioni.approval_links import build_link_urls, create_link
from automazioni.models import (
    AutomationAction,
    AutomationActionLog,
    AutomationActionLogStatus,
    AutomationActionType,
    AutomationApproval,
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
    AutomationRunLog,
    AutomationRunLogStatus,
)

APPROVER_A = "approvatore.a@example.com"
APPROVER_B = "approvatore.b@example.com"
SECRET_URL = (
    "https://prod-00.westeurope.logic.azure.com:443/workflows/abc123/triggers/manual/paths/invoke"
    "?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=FIRMA_SEGRETA_SINTETICA"
)


def _rule(code: str, *, source_code: str = "assenze") -> AutomationRule:
    return AutomationRule.objects.create(
        code=code,
        name=f"Regola {code}",
        source_code=source_code,
        operation_type=AutomationRuleOperationType.UPDATE,
        trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        is_active=True,
        is_draft=False,
    )


def _run_log(rule: AutomationRule, *, queue_event_id: int | None = None, status: str = "success") -> AutomationRunLog:
    return AutomationRunLog.objects.create(
        rule=rule,
        queue_event_id=queue_event_id,
        source_code=rule.source_code,
        operation_type=rule.operation_type,
        status=status,
    )


def _write_log_action(rule: AutomationRule, order: int) -> AutomationAction:
    return AutomationAction.objects.create(
        rule=rule,
        order=order,
        action_type=AutomationActionType.WRITE_LOG,
        config_json={"message_template": f"passo {order}"},
    )


def _send_approval_action(rule: AutomationRule, to_template: str) -> AutomationAction:
    return AutomationAction.objects.create(
        rule=rule,
        order=1,
        action_type=AutomationActionType.SEND_APPROVAL,
        config_json={
            "to_template": to_template,
            "subject_template": "Approva richiesta {id}",
            "message_template": "Richiesta sintetica",
            "expiry_days": 3,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Retry dello stesso evento: niente azioni ripetute
# ─────────────────────────────────────────────────────────────────────────────
class RetrySenzaDoppioniTests(TestCase):
    def setUp(self):
        self.rule = _rule("retry-no-dup")
        self.first = _write_log_action(self.rule, 1)
        self.second = _write_log_action(self.rule, 2)

    def _previous_attempt(self, queue_event_id: int) -> None:
        old_run = _run_log(self.rule, queue_event_id=queue_event_id, status="error")
        AutomationActionLog.objects.create(
            run_log=old_run, action=self.first, status=AutomationActionLogStatus.SUCCESS, result_message="ok"
        )
        AutomationActionLog.objects.create(
            run_log=old_run, action=self.second, status=AutomationActionLogStatus.ERROR, result_message="ko"
        )

    def test_azione_riuscita_nel_tentativo_precedente_non_si_ripete(self):
        self._previous_attempt(700)
        with patch("automazioni.services.execute_action", return_value={"status": "success", "result_message": ""}) as ex:
            run_log = services.run_rule(self.rule, {"id": 1}, queue_event_id=700)

        self.assertEqual([call.args[0].pk for call in ex.call_args_list], [self.second.pk])
        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        skipped = run_log.action_logs.get(action=self.first)
        self.assertEqual(skipped.status, AutomationActionLogStatus.SUCCESS)
        self.assertIn("non ripetuta", skipped.result_message)

    def test_altro_evento_o_test_rieseguono_tutto(self):
        self._previous_attempt(701)
        with patch("automazioni.services.execute_action", return_value={"status": "success", "result_message": ""}) as ex:
            services.run_rule(self.rule, {"id": 1}, queue_event_id=702)
            services.run_rule(self.rule, {"id": 1}, queue_event_id=701, is_test=True)
        self.assertEqual(ex.call_count, 4)


@override_settings(SITE_URL="https://portale.example.local", DEFAULT_FROM_EMAIL="noreply@example.com")
class SendApprovalRecapitoParzialeTests(TestCase):
    def setUp(self):
        self.rule = _rule("approval-partial")
        self.action = _send_approval_action(self.rule, f"{APPROVER_A}, {APPROVER_B}")

    def test_recapito_parziale_non_cancella_la_richiesta_e_il_retry_invia_solo_ai_mancanti(self):
        real_send = services._send_approval_email

        def _fail_for_b(**kwargs):
            if kwargs["approver_emails"] == [APPROVER_B]:
                raise smtplib.SMTPRecipientsRefused({APPROVER_B: (550, b"rifiutato")})
            return real_send(**kwargs)

        with patch("automazioni.services._send_approval_email", side_effect=_fail_for_b):
            first_run = services.run_rule(self.rule, {"id": 5}, queue_event_id=800)

        self.assertEqual(first_run.status, AutomationRunLogStatus.ERROR)
        approval = AutomationApproval.objects.get()
        # Il link del primo approvatore resta valido: la richiesta non è cancellata.
        self.assertEqual(list(approval.links.values_list("recipient_email", flat=True)), [APPROVER_A])
        action_log = first_run.action_logs.get()
        self.assertIn("Recapito parziale", action_log.result_message)
        self.assertEqual([m.to for m in mail.outbox], [[APPROVER_A]])

        second_run = services.run_rule(self.rule, {"id": 5}, queue_event_id=800)

        self.assertEqual(second_run.status, AutomationRunLogStatus.WAITING_APPROVAL)
        self.assertEqual(AutomationApproval.objects.count(), 1)
        approval.refresh_from_db()
        self.assertEqual(approval.run_log_id, second_run.pk)
        self.assertEqual(
            sorted(approval.links.values_list("recipient_email", flat=True)), [APPROVER_A, APPROVER_B]
        )
        # Al retry parte solo la mail mancante.
        self.assertEqual([m.to for m in mail.outbox], [[APPROVER_A], [APPROVER_B]])

    def test_nessun_recapito_cancella_la_richiesta(self):
        with patch("automazioni.services._send_approval_email", side_effect=smtplib.SMTPException("giù")):
            run_log = services.run_rule(self.rule, {"id": 6}, queue_event_id=801)
        self.assertEqual(run_log.status, AutomationRunLogStatus.ERROR)
        self.assertEqual(AutomationApproval.objects.count(), 0)
        self.assertIn("Nessun recapito approvazione riuscito", run_log.action_logs.get().result_message)

    def test_richiesta_gia_decisa_prima_del_retry_non_si_rimanda(self):
        old_run = _run_log(self.rule, queue_event_id=802, status="error")
        AutomationApproval.objects.create(
            run_log=old_run,
            action=self.action,
            subject="x",
            approver_emails=[APPROVER_A, APPROVER_B],
            status=AutomationApproval.Status.APPROVED,
        )
        run_log = services.run_rule(self.rule, {"id": 7}, queue_event_id=802)
        self.assertEqual(AutomationApproval.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("già chiusa", run_log.action_logs.get().result_message)

    def test_una_sola_connessione_smtp_per_richiesta(self):
        connection = MagicMock()
        with patch("django.core.mail.get_connection", return_value=connection), patch(
            "automazioni.services.EmailMultiAlternatives"
        ) as email_class:
            email_class.return_value.send.return_value = 1
            run_log = _run_log(self.rule)
            result = services.execute_action(self.action, {"id": 8}, run_log=run_log)

        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        self.assertEqual(email_class.call_count, 2)
        for call in email_class.call_args_list:
            self.assertIs(call.kwargs["connection"], connection)
        connection.open.assert_called_once()
        connection.close.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Coda: un evento alla volta, budget di tempo, rilascio dei non lavorati
# ─────────────────────────────────────────────────────────────────────────────
class CodaBudgetTests(SimpleTestCase):
    @patch("automazioni.services.recover_stale_processing_events", return_value=0)
    @patch("automazioni.services.process_queue_event")
    @patch("automazioni.services.fetch_pending_queue_events")
    def test_preleva_un_evento_alla_volta(self, mock_fetch, mock_process, _recover):
        mock_fetch.side_effect = [[{"id": 1}], [{"id": 2}], []]
        mock_process.side_effect = [
            {"queue_id": 1, "status": "done", "rule_runs": 1},
            {"queue_id": 2, "status": "done", "rule_runs": 0},
        ]
        summary = services.process_pending_queue_events(limit=10)
        self.assertEqual(summary["fetched"], 2)
        self.assertEqual(summary["done"], 2)
        for call in mock_fetch.call_args_list:
            self.assertEqual(call.args[0], 1)

    @patch("automazioni.services.recover_stale_processing_events", return_value=0)
    @patch("automazioni.services.process_queue_event")
    @patch("automazioni.services.fetch_pending_queue_events")
    def test_budget_esaurito_si_ferma(self, mock_fetch, mock_process, _recover):
        with patch.object(services, "QUEUE_BATCH_TIME_BUDGET_SECONDS", 0):
            summary = services.process_pending_queue_events(limit=10)
        mock_fetch.assert_not_called()
        mock_process.assert_not_called()
        self.assertTrue(summary["budget_exhausted"])

    @patch("automazioni.services.release_queue_events")
    @patch("automazioni.services.recover_stale_processing_events", return_value=0)
    @patch("automazioni.services.process_queue_event")
    @patch("automazioni.services.fetch_pending_queue_events")
    def test_eventi_presi_e_non_lavorati_tornano_in_coda(self, mock_fetch, mock_process, _recover, mock_release):
        mock_fetch.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
        mock_process.return_value = {"queue_id": 1, "status": "done", "rule_runs": 0}
        summary = services.process_pending_queue_events(limit=1)
        self.assertEqual(summary["fetched"], 1)
        mock_release.assert_called_once_with([2, 3])


# ─────────────────────────────────────────────────────────────────────────────
# 3-6. HTTP: segreti, allowlist sul flow Teams, 3xx, proxy, DNS
# ─────────────────────────────────────────────────────────────────────────────
class RedazioneUrlTests(SimpleTestCase):
    def test_redact_url_tiene_solo_schema_e_host(self):
        self.assertEqual(services._redact_url(SECRET_URL), "https://prod-00.westeurope.logic.azure.com:443")
        self.assertEqual(services._redact_url("non un url"), "<url>")

    def test_redact_secrets_su_messaggio_requests(self):
        text = (
            "HTTPSConnectionPool(host='prod-00.westeurope.logic.azure.com', port=443): Max retries exceeded "
            "with url: /workflows/abc/triggers/manual/paths/invoke?sig=FIRMA_SEGRETA_SINTETICA (Caused by x) "
            f"e anche {SECRET_URL}"
        )
        cleaned = services._redact_secrets(text)
        self.assertNotIn("FIRMA_SEGRETA_SINTETICA", cleaned)
        self.assertNotIn("/workflows/", cleaned)
        self.assertIn("prod-00.westeurope.logic.azure.com", cleaned)

    def test_errore_di_rete_diventa_tipo_piu_host(self):
        exc = requests.ConnectionError(f"Max retries exceeded with url: {SECRET_URL}")
        with patch("automazioni.services.validate_http_action_target", return_value=False), patch.object(
            services.requests, "request", side_effect=exc
        ):
            with self.assertRaises(services.AutomationHttpError) as ctx:
                services._perform_http_request(method="POST", url=SECRET_URL, headers={}, body=None, timeout_seconds=5)
        message = str(ctx.exception)
        self.assertNotIn("FIRMA_SEGRETA_SINTETICA", message)
        self.assertIn("ConnectionError verso prod-00.westeurope.logic.azure.com", message)
        self.assertTrue(ctx.exception.__suppress_context__)


class HttpActionEsitiTests(TestCase):
    def setUp(self):
        self.rule = _rule("http-esiti", source_code="tasks")
        self.run_log = _run_log(self.rule)

    def _http_action(self, url: str, **extra) -> AutomationAction:
        return AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.HTTP_REQUEST,
            config_json={"method": "POST", "url_template": url, **extra},
        )

    def test_errore_di_rete_non_scrive_la_firma_in_run_log_e_traceback(self):
        action = self._http_action(SECRET_URL)
        with patch("automazioni.services.validate_http_action_target", return_value=False), patch.object(
            services.requests, "request", side_effect=requests.ConnectionError(f"url: {SECRET_URL}")
        ):
            result = services.execute_action(action, {"id": 1}, run_log=self.run_log)
        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        log = AutomationActionLog.objects.get(run_log=self.run_log)
        self.assertNotIn("FIRMA_SEGRETA_SINTETICA", log.result_message)
        self.assertNotIn("FIRMA_SEGRETA_SINTETICA", log.error_trace or "")

    def test_successo_registra_solo_schema_e_host(self):
        action = self._http_action(SECRET_URL)
        response = MagicMock(status_code=202)
        with patch("automazioni.services.validate_http_action_target", return_value=False), patch.object(
            services.requests, "request", return_value=response
        ):
            result = services.execute_action(action, {"id": 1}, run_log=self.run_log)
        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        self.assertNotIn("sig=", result["result_message"])
        self.assertIn("https://prod-00.westeurope.logic.azure.com:443", result["result_message"])

    def test_redirect_non_seguito_non_e_successo(self):
        action = self._http_action("https://hook.example.com/a")
        response = MagicMock(status_code=302, headers={"Location": "https://login.example.org/x"})
        with patch("automazioni.services.validate_http_action_target", return_value=False), patch.object(
            services.requests, "request", return_value=response
        ):
            result = services.execute_action(action, {"id": 1}, run_log=self.run_log)
        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("redirect verso login.example.org non seguito", result["result_message"])

    def test_teams_webhook_3xx_e_errore(self):
        action = AutomationAction.objects.create(
            rule=self.rule,
            order=2,
            action_type=AutomationActionType.TEAMS_WEBHOOK,
            config_json={"webhook_url": "https://example.webhook.office.com/webhookb2/SEGRETO", "title_template": "t"},
        )
        response = MagicMock(status_code=301, headers={})
        with patch("automazioni.services.validate_http_action_target", return_value=False), patch.object(
            services.requests, "request", return_value=response
        ):
            result = services.execute_action(action, {"id": 1}, run_log=self.run_log)
        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("redirect verso example.webhook.office.com non seguito", result["result_message"])
        self.assertNotIn("SEGRETO", result["result_message"])

    def test_expected_statuses_resta_valido(self):
        action = self._http_action("https://hook.example.com/a", expected_statuses=[304])
        with patch("automazioni.services.validate_http_action_target", return_value=False), patch.object(
            services.requests, "request", return_value=MagicMock(status_code=304)
        ):
            result = services.execute_action(action, {"id": 1}, run_log=self.run_log)
        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)


@override_settings(SITE_URL="https://portale.example.local", DEFAULT_FROM_EMAIL="noreply@example.com")
class TeamsChatFlowGuardTests(TestCase):
    @override_settings(AUTOMATION_HTTP_EXTERNAL_HOSTS=[])
    def test_flow_verso_host_non_ammesso_bloccato_senza_chiamata(self):
        from automazioni.models import AutomationDeliveryEndpoint, AutomationDeliveryEndpointType

        endpoint = AutomationDeliveryEndpoint.objects.create(
            code="flow-non-ammesso",
            name="Flow non ammesso",
            endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
            endpoint_url="https://flow.example.com/x",
        )
        rule = _rule("flow-guard")
        action = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.SEND_APPROVAL,
            config_json={
                "delivery_mode": "teams_chat_flow",
                "teams_flow_endpoint_id": str(endpoint.pk),
                "teams_recipient_email_template": APPROVER_A,
                "subject_template": "x",
            },
        )
        with patch.object(services.requests, "request") as fake_request, patch.object(
            services.requests, "post"
        ) as fake_post:
            result = services.execute_action(action, {"id": 1}, run_log=_run_log(rule))
        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        fake_request.assert_not_called()
        fake_post.assert_not_called()
        self.assertEqual(AutomationApproval.objects.count(), 0)


def _fake_resolve(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


class ProxyEDnsTests(SimpleTestCase):
    @override_settings(AUTOMATION_HTTP_ALLOWED_HOSTS=["intranet.example.local"])
    def test_host_lan_senza_proxy_di_sistema(self):
        session = MagicMock()
        session.__enter__.return_value = session
        with patch("socket.getaddrinfo", return_value=_fake_resolve("10.0.0.5")), patch.object(
            services.requests, "Session", return_value=session
        ), patch.object(services.requests, "request") as public_request:
            services._perform_http_request(
                method="GET", url="http://intranet.example.local/api", headers={}, body=None, timeout_seconds=5
            )
        self.assertIs(session.trust_env, False)
        session.request.assert_called_once()
        self.assertIs(session.request.call_args.kwargs["allow_redirects"], False)
        public_request.assert_not_called()

    @override_settings(AUTOMATION_HTTP_EXTERNAL_HOSTS=["hook.example.com"])
    def test_host_pubblico_usa_requests_con_proxy(self):
        with patch("socket.getaddrinfo", return_value=_fake_resolve("93.184.216.34")), patch.object(
            services.requests, "Session"
        ) as fake_session, patch.object(services.requests, "request") as public_request:
            services._perform_http_request(
                method="GET", url="https://hook.example.com/a", headers={}, body=None, timeout_seconds=5
            )
        public_request.assert_called_once()
        fake_session.assert_not_called()

    @override_settings(AUTOMATION_HTTP_EXTERNAL_HOSTS=["hook.example.com"])
    def test_dns_non_risolvibile_non_e_un_blocco_di_policy(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("nome sconosciuto")):
            with self.assertRaises(services.AutomationHostUnresolvedError) as ctx:
                services.validate_http_action_target("https://hook.example.com/a")
        self.assertNotIsInstance(ctx.exception, services.AutomationSafetyError)
        self.assertIn("non è un blocco", str(ctx.exception))


class SmtpMessaggiTests(TestCase):
    def test_server_disconnected_non_accusa_solo_smtp_auth(self):
        rule = _rule("smtp-msg", source_code="tasks")
        action = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.SEND_EMAIL,
            config_json={
                "from_email": "mittente@example.com",
                "to": "dest@example.com",
                "subject_template": "s",
                "body_text_template": "b",
            },
        )
        with patch("automazioni.services.EmailMultiAlternatives") as email_class:
            email_class.return_value.send.side_effect = smtplib.SMTPServerDisconnected("chiusa")
            result = services.execute_action(action, {"id": 1}, run_log=_run_log(rule))
        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("Cause possibili", result["result_message"])
        self.assertIn("momentaneamente non disponibile", result["result_message"])


# ─────────────────────────────────────────────────────────────────────────────
# 9. Decisione dal web: ramo in background
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(SITE_URL="https://portale.example.local", DEFAULT_FROM_EMAIL="noreply@example.com")
class DecisioneRamoInBackgroundTests(TestCase):
    def setUp(self):
        self.rule = _rule("ramo-bg")
        run = _run_log(self.rule, status="waiting_approval")
        self.approval = AutomationApproval.objects.create(
            run_log=run,
            subject="Richiesta sintetica",
            approver_emails=[APPROVER_A],
            expires_at=timezone.now() + timedelta(days=1),
            approved_actions=[{"action_type": "write_log", "message_template": "ramo"}],
        )

    def test_defer_branch_accoda_e_risponde_subito(self):
        with patch("django_q.tasks.async_task") as fake_async, patch(
            "automazioni.services.run_approval_branch"
        ) as fake_branch:
            result = services.process_approval_decision(
                str(self.approval.token), "approved", decided_by_email=APPROVER_A, defer_branch=True
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["branch_deferred"])
        self.assertIsNone(result["actions_run"])
        self.assertIn("Decisione registrata", result["message"])
        fake_branch.assert_not_called()
        self.assertEqual(fake_async.call_args.args, ("automazioni.tasks.run_approval_branch_task", self.approval.pk))
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "approved")
        self.assertEqual(self.approval.branch_status, AutomationApproval.BranchStatus.RUNNING)

    def test_accodamento_fallito_esegue_subito(self):
        with patch("django_q.tasks.async_task", side_effect=RuntimeError("cluster fermo")):
            result = services.process_approval_decision(
                str(self.approval.token), "approved", decided_by_email=APPROVER_A, defer_branch=True
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["actions_run"], 1)
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.branch_status, AutomationApproval.BranchStatus.DONE)

    def test_task_esegue_il_ramo_una_volta_sola(self):
        from automazioni.tasks import run_approval_branch_task

        with patch("django_q.tasks.async_task"):
            services.process_approval_decision(
                str(self.approval.token), "approved", decided_by_email=APPROVER_A, defer_branch=True
            )
        first = run_approval_branch_task(self.approval.pk)
        self.assertEqual(first["actions_run"], 1)
        second = run_approval_branch_task(self.approval.pk)
        self.assertTrue(second["skipped"])
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.branch_status, AutomationApproval.BranchStatus.DONE)

    def test_pagina_link_personale_non_esegue_il_ramo_nel_thread_web(self):
        raw = create_link(self.approval, APPROVER_A)
        approve_url, _ = build_link_urls(raw)
        path = approve_url.replace("https://portale.example.local", "")
        with patch("django_q.tasks.async_task") as fake_async, patch(
            "automazioni.services.run_approval_branch"
        ) as fake_branch:
            response = self.client.post(path)
        self.assertEqual(response.status_code, 302)
        fake_branch.assert_not_called()
        fake_async.assert_called_once()
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "approved")


# ─────────────────────────────────────────────────────────────────────────────
# 10. Payload arricchito una volta, condizioni/azioni in prefetch
# ─────────────────────────────────────────────────────────────────────────────
class ArricchimentoUnaVoltaTests(TestCase):
    def test_process_queue_event_arricchisce_una_volta_sola(self):
        rule = _rule("enrich-once")
        _write_log_action(rule, 1)
        event = {
            "id": 900,
            "source_code": "assenze",
            "operation_type": "update",
            "payload_json": '{"id": 1, "x": 2}',
            "old_payload_json": '{"id": 1, "x": 1}',
        }
        with patch("automazioni.services._enrich_payload_for_source", side_effect=lambda s, p: p) as enrich, patch(
            "automazioni.services.mark_queue_done"
        ), patch("automazioni.services.mark_queue_error"):
            result = services.process_queue_event(event)
        self.assertEqual(result["rule_runs"], 1)
        self.assertEqual(enrich.call_count, 2)  # payload + old_payload, non 4

    def test_find_matching_rules_porta_condizioni_e_azioni_in_prefetch(self):
        rule = _rule("prefetch")
        _write_log_action(rule, 1)
        AutomationAction.objects.create(
            rule=rule, order=2, action_type=AutomationActionType.WRITE_LOG, is_enabled=False, config_json={}
        )
        rules = services.find_matching_rules({"source_code": "assenze", "operation_type": "update"})
        self.assertEqual(len(rules), 1)
        with self.assertNumQueries(0):
            self.assertEqual(len(rules[0].prefetched_enabled_actions), 1)
            self.assertEqual(len(rules[0].prefetched_enabled_conditions), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Mailbox Graph: errori definitivi, tetto tentativi, URL codificati
# ─────────────────────────────────────────────────────────────────────────────
MAILBOX_SETTINGS = dict(
    GRAPH_TENANT_ID="t",
    GRAPH_CLIENT_ID="c",
    GRAPH_CLIENT_SECRET="s",
    APPROVAL_MAILBOX_ADDRESS="mb@example.com",
    APPROVAL_MAILBOX_FOLDER="Inbox",
    APPROVAL_GRAPH_ONLY_UNREAD="1",
    APPROVAL_GRAPH_PAGE_SIZE="10",
    APPROVAL_GRAPH_MARK_READ="1",
    APPROVAL_MAILBOX_BACKEND="graph",
)
TOKEN_SINTETICO = "550e8400-e29b-41d4-a716-446655440099"


def _raw_message() -> dict:
    return {
        "id": "GMSG/ab+c=",
        "internetMessageId": "<errore-sintetico@example.com>",
        "subject": f"CMD APPROVO RID {TOKEN_SINTETICO}",
        "from": {"emailAddress": {"address": APPROVER_A}},
        "receivedDateTime": "2026-04-15T10:00:00Z",
        "bodyPreview": "",
        "body": {"contentType": "text", "content": ""},
        "isRead": False,
    }


@override_settings(**MAILBOX_SETTINGS)
@patch("automazioni.mailbox_graph._get_token", return_value="tok")
@patch("automazioni.mailbox_graph._validate_sender", return_value=None)
@patch("automazioni.mailbox_graph.mark_message_as_read")
@patch("automazioni.mailbox_graph.fetch_messages")
class MailboxErroriTests(TestCase):
    def _poll(self):
        from automazioni.mailbox_graph import poll_graph_mailbox

        return poll_graph_mailbox(limit=10, dry_run=False, mark_read=True)

    def test_richiesta_non_trovata_diventa_ignorata_e_letta(self, mock_fetch, mock_mark, _v, _t):
        mock_fetch.return_value = [_raw_message()]
        with patch(
            "automazioni.services.process_approval_decision",
            return_value={"ok": False, "message": "Richiesta di approvazione non trovata."},
        ):
            result = self._poll()
        self.assertEqual(result.ignored, 1)
        self.assertEqual(result.error, 0)
        mock_mark.assert_called_once()

    def test_errore_generico_abbandonato_dopo_tre_giri(self, mock_fetch, mock_mark, _v, _t):
        from automazioni.models import ApprovalMailboxMessage

        mock_fetch.return_value = [_raw_message()]
        with patch(
            "automazioni.services.process_approval_decision", return_value={"ok": False, "message": "boom"}
        ):
            first = self._poll()
            second = self._poll()
            third = self._poll()
        self.assertEqual((first.error, second.error, third.error), (1, 1, 0))
        self.assertEqual(third.ignored, 1)
        mock_mark.assert_called_once()
        record = ApprovalMailboxMessage.objects.get()
        self.assertEqual(record.processing_status, "ignored")
        self.assertIn("Abbandonato dopo 3 tentativi", record.processing_error)


class MailboxUrlTests(SimpleTestCase):
    @override_settings(**MAILBOX_SETTINGS)
    def test_id_messaggio_e_casella_codificati_e_token_riusato(self):
        from automazioni import mailbox_graph

        with patch.object(mailbox_graph, "_graph_request", return_value={}) as fake_request, patch.object(
            mailbox_graph, "_get_token"
        ) as fake_token:
            ok = mailbox_graph.mark_message_as_read(mailbox="mb@example.com", graph_message_id="AA/b+c=", token="tok")
        self.assertTrue(ok)
        fake_token.assert_not_called()
        url = fake_request.call_args.args[1]
        self.assertTrue(url.endswith("/users/mb@example.com/messages/AA%2Fb%2Bc%3D"))


# ─────────────────────────────────────────────────────────────────────────────
# 13. Schedule del warmup Ollama
# ─────────────────────────────────────────────────────────────────────────────
class ScheduleWarmupTests(SimpleTestCase):
    def test_warmup_ollama_ha_timeout_oltre_i_300_secondi(self):
        from automazioni.schedules import SCHEDULES

        spec = next(item for item in SCHEDULES if item["name"] == "ai_warmup_ollama")
        self.assertEqual(spec["kwargs"]["q_options"]["timeout"], 330)
