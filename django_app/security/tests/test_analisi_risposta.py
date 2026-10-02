"""Analisi (fatti collegati, precedenti, storico) e risposta (procedure, passi e esito proposti dall'AI simulata)."""
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord, SecurityAlert, SecurityAlertSuppressionRule, SecurityCaseTask, SecurityEventRecord, SecurityRemediationTicket,
    SecuritySource, SecurityVpnAccess, Severity, Status,
)
from security.services.ai_explain import alert_context, case_context
from security.services.history_review import build_review, review_as_text
from security.services.investigation import PLAYBOOKS, alert_kind, precedents, related_facts

CHAT = "ai_assistant.services.chat_with_ollama"
DENIED = "watchguard_vpn_repeated_denied"


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="soc_analyst", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Firebox", source_type="email", vendor="watchguard")
        self._n = 0

    def _alert(self, title="Repeated denied SSL VPN logins from 198.51.100.7", status=Status.NEW, reason="", days_ago=0, **payload):
        self._n += 1
        payload = {"type": DENIED, "source_ip": "198.51.100.7", "count": 30, **payload}
        event = SecurityEventRecord.objects.create(source=self.source, event_type="watchguard_alert_candidate", severity=Severity.WARNING,
                                                   fingerprint=f"f{self._n}", dedup_hash=f"h{self._n}", payload=payload,
                                                   decision_trace={"decision": "alert", "rule": "demo"})
        alert = SecurityAlert.objects.create(source=self.source, event=event, title=title, severity=Severity.WARNING, dedup_hash=f"h{self._n}",
                                             status=status, status_reason=reason)
        if days_ago:
            SecurityAlert.objects.filter(pk=alert.pk).update(created_at=timezone.now() - timezone.timedelta(days=days_ago))
            alert.refresh_from_db()
        return alert

    def _vpn(self, action, ip="198.51.100.7", user="admin", n=1):
        for i in range(n):
            self._n += 1
            SecurityVpnAccess.objects.create(source=self.source, action=action, username=user, source_ip=ip, kind="vpn",
                                             login_at=timezone.now() - timezone.timedelta(hours=i + 1), dedup_hash=f"v{self._n}")


class AnalysisTests(_Base):
    def test_kind_from_parser_type_or_title(self):
        self.assertEqual(alert_kind(self._alert()), "vpn_denied")
        backup = SecurityAlert.objects.create(source=self.source, title="Backup fallito: NAS", severity=Severity.WARNING, dedup_hash="b")
        self.assertEqual(alert_kind(backup), "backup")

    def test_unknown_ip_with_only_denied_logins_is_flagged(self):
        self._vpn("denied", n=12)
        facts = related_facts(self._alert())
        ip = next(fact for fact in facts if fact["label"] == "Indirizzo 198.51.100.7")
        self.assertEqual(ip["tone"], "warn")
        self.assertIn("0 accessi VPN riusciti, 12 negati", " ".join(ip["lines"]))
        self.assertIn("non è un utente noto", " ".join(ip["lines"]))
        self.assertIn("ip=198.51.100.7", ip["url"])
        self.assertEqual(ip["lines"][0], "Indirizzo esterno (Internet)")  # 198.51.100.0/24 non è una LAN aziendale

    def test_backup_job_fact_says_when_the_last_good_backup_ran(self):
        BackupJobRecord.objects.create(source=self.source, job_name="NAS-01", status="completed", dedup_hash="ok",
                                       started_at=timezone.now() - timezone.timedelta(days=4))
        BackupJobRecord.objects.create(source=self.source, job_name="NAS-01", status="failed", dedup_hash="ko", started_at=timezone.now())
        alert = self._alert(title="Backup fallito: NAS-01", type="", job_name="NAS-01", source_ip="")
        job = next(fact for fact in related_facts(alert) if fact["label"] == "Job NAS-01")
        self.assertIn("(4 giorni fa)", " ".join(job["lines"]))
        self.assertEqual(job["tone"], "warn")

    def test_precedents_include_closures_reasons_and_discarded_events(self):
        for _ in range(3):
            self._alert(status=Status.FALSE_POSITIVE, reason="IP del consulente esterno, attività nota", days_ago=10)
        rule = SecurityAlertSuppressionRule.objects.create(name="Consulente", reason="noto", is_active=True)
        SecurityEventRecord.objects.create(source=self.source, event_type="watchguard_alert_candidate", severity=Severity.WARNING, fingerprint="s",
                                           dedup_hash="s", payload={"type": DENIED}, suppressed=True,
                                           decision_trace={"decision": "suppressed_kpi_only", "rule": rule.name})
        history = precedents(self._alert())
        self.assertEqual(history["total"], 3)
        self.assertIn("3 falsi positivi", history["text"])
        self.assertEqual(history["reasons"][0]["text"], "IP del consulente esterno, attività nota")
        self.assertIn("1 eventi simili scartati da una regola di soppressione", history["discarded"])
        self.assertIn("soppressione", history["hint"])

    def test_ai_context_carries_history_but_never_the_mail_body(self):
        self._alert(status=Status.FALSE_POSITIVE, reason="Test del fornitore", days_ago=3)
        context = alert_context(self._alert(body="TESTO SEGRETO DELLA MAIL"))
        self.assertIn("Precedenti: Successo altre 1 volte", context)
        self.assertIn("Test del fornitore", context)
        self.assertIn("Procedura standard «Tentativi di accesso VPN negati»", context)
        self.assertNotIn("SEGRETO", context)

    def test_alert_page_shows_analysis_and_opens_a_ticket_with_the_playbook(self):
        alert = self._alert()
        page = self.client.get(reverse("security:alert_detail", args=[alert.pk]))
        self.assertContains(page, "Cosa sappiamo")
        self.assertContains(page, "Come rispondere")
        self.assertContains(page, "È la prima volta negli ultimi 6 mesi.")
        response = self.client.post(reverse("security:case_create"), {"alert_ids": alert.pk, "title": alert.title, "assign_to_me": "1", "with_playbook": "1"})
        case = SecurityRemediationTicket.objects.get(origin=SecurityRemediationTicket.ORIGIN_MANUAL)
        self.assertRedirects(response, reverse("security:case_detail", args=[case.pk]))
        self.assertEqual(list(case.tasks.values_list("title", flat=True)), PLAYBOOKS["vpn_denied"][1])


class ResponseTests(_Base):
    def _case(self):
        from security.services.cases import open_case_from_alerts

        return open_case_from_alerts([self._alert()], user=self.user, assignee=self.user)

    def test_case_shows_missing_playbook_steps_and_adds_them_once(self):
        case = self._case()
        steps = PLAYBOOKS["vpn_denied"][1]
        SecurityCaseTask.objects.create(ticket=case, title=steps[0])
        page = self.client.get(reverse("security:case_detail", args=[case.pk]))
        self.assertContains(page, f"Aggiungi {len(steps) - 1} passi della procedura")
        url = reverse("security:case_tasks_add_many", args=[case.pk])
        self.client.post(url, {"titles": steps})
        self.client.post(url, {"titles": steps})
        self.assertEqual(case.tasks.count(), len(steps))

    def test_ai_steps_are_proposals_until_confirmed(self):
        case = self._case()
        SecurityCaseTask.objects.create(ticket=case, title="Bloccare l'IP sul Firebox")
        answer = "Ecco i passi:\n- Bloccare l'IP sul Firebox\n- Cambiare la password di admin\n2. Cambiare la password di admin\n* Verificare l'MFA"
        with mock.patch(CHAT, return_value=SimpleNamespace(content=answer)) as chat:
            response = self.client.post(reverse("security:case_ai_steps", args=[case.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(response, 'value="Cambiare la password di admin" checked')
        self.assertContains(response, 'value="Verificare l&#x27;MFA" checked')
        self.assertNotContains(response, 'value="Bloccare l&#x27;IP sul Firebox"')
        self.assertNotContains(response, "Ecco i passi")
        self.assertEqual(case.tasks.count(), 1)  # niente diventa attività senza conferma
        context = chat.call_args.kwargs["runtime_context"]
        self.assertIn("Attività da fare: Bloccare l'IP sul Firebox", context)

    def test_ai_resolution_is_a_draft_in_the_textarea(self):
        case = self._case()
        with mock.patch(CHAT, return_value=SimpleNamespace(content="Bloccato l'IP 198.51.100.7, nessun accesso riuscito.")):
            response = self.client.post(reverse("security:case_ai_resolution", args=[case.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(response, '<textarea name="reason" rows="5"')
        self.assertContains(response, "Bloccato l&#x27;IP 198.51.100.7")
        case.refresh_from_db()
        self.assertEqual(case.status, Status.IN_PROGRESS)

    def test_ai_down_on_resolution_keeps_an_empty_textarea(self):
        case = self._case()
        with mock.patch(CHAT, side_effect=RuntimeError("Ollama non raggiungibile")):
            response = self.client.post(reverse("security:case_ai_resolution", args=[case.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(response, 'name="reason"')
        self.assertContains(response, "Scrivi l'esito a mano")

    def test_case_context_has_notes_and_tasks(self):
        from security.services.cases import add_note

        case = self._case()
        add_note(case, "Sentito il consulente: non era lui.", user=self.user)
        context = case_context(case)
        self.assertIn("Nota del", context)
        self.assertIn("non era lui", context)


class HistoryTests(_Base):
    def test_review_finds_recurring_false_positives_discarded_and_stale(self):
        for _ in range(3):
            self._alert(status=Status.FALSE_POSITIVE, reason="Scansione del fornitore", days_ago=5)
        self._alert(days_ago=10)
        SecurityEventRecord.objects.create(source=self.source, event_type="watchguard_alert_candidate", severity=Severity.WARNING, fingerprint="s",
                                           dedup_hash="s", payload={}, suppressed=True, decision_trace={"decision": "suppressed_kpi_only", "rule": "Scanner"})
        SecurityAlertSuppressionRule.objects.create(name="Vecchia regola", reason="x", is_active=True)
        SecurityAlertSuppressionRule.objects.create(name="Scanner", reason="ha scartato eventi", is_active=True)
        review = build_review(30)
        self.assertEqual(review["recurring"][0]["total"], 4)
        self.assertEqual(review["recurring"][0]["status_text"], "3 falsi positivi, 1 nuovo")
        self.assertEqual(review["false_positives"][0]["false_positive"], 3)
        self.assertEqual(review["discarded_by_rule"], [("Scanner", 1)])
        self.assertEqual(review["stale_alerts_total"], 1)
        self.assertEqual([rule.name for rule in review["unused_rules"]], ["Vecchia regola"])
        text = review_as_text(review)
        self.assertIn("Falso positivo ripetuto", text)
        self.assertIn("Scansione del fornitore", text)

    def test_history_page_and_ai_proposals(self):
        self._alert(status=Status.FALSE_POSITIVE, reason="Noto", days_ago=2)
        self._alert(status=Status.FALSE_POSITIVE, reason="Noto", days_ago=1)
        page = self.client.get(reverse("security:history"))
        self.assertContains(page, "Alert che si ripetono")
        self.assertContains(page, "Falsi positivi ricorrenti")
        with mock.patch(CHAT, return_value=SimpleNamespace(content="1. **Creare una regola di soppressione**")) as chat:
            response = self.client.post(reverse("security:history_proposals"), {"giorni": "30"}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "<strong>Creare una regola di soppressione</strong>")
        self.assertIn("Falso positivo ripetuto", chat.call_args.kwargs["runtime_context"])
        self.assertEqual(SecurityAlertSuppressionRule.objects.count(), 0)  # l'AI propone, non crea
