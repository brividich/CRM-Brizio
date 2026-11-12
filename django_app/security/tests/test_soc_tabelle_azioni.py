"""Selezione multipla e pannelli anche su Dispositivi, Patch e protezione, Soppressioni, Rischi accettati, Accessi VPN."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAlertSuppressionRule,
    SecurityEventRecord,
    SecurityRemediationTicket,
    SecuritySource,
    SecurityVpnAccess,
    SourceType,
)


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="soc_tab_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Fonte tabelle", vendor="Demo", source_type=SourceType.EMAIL)


class PcBulkTests(_Base):
    def test_ticket_for_selected_pcs(self):
        SecurityEventRecord.objects.create(source=self.source, event_type="demo", fingerprint="f1", dedup_hash="e1")
        response = self.client.post(reverse("security:pc_bulk"), {"devices": ["PC-A", "PC-B", "PC-A"], "pagina": "Dispositivi"})
        case = SecurityRemediationTicket.objects.get()
        self.assertRedirects(response, reverse("security:case_detail", args=[case.pk]), fetch_redirect_response=False)
        self.assertEqual(case.tasks.count(), 2)
        self.assertEqual(case.assignee, self.user)
        self.assertIn("Dispositivi", case.description)

    def test_no_selection(self):
        self.client.post(reverse("security:pc_bulk"), {"devices": []})
        self.assertFalse(SecurityRemediationTicket.objects.exists())

    def test_device_page_has_external_bulk_form(self):
        page = self.client.get(reverse("security:pc_copertura"))
        self.assertContains(page, 'id="pc-bulk"')
        self.assertContains(page, 'data-bulk-all form="pc-bulk"')


class SuppressionsBulkTests(_Base):
    def _rule(self, name):
        return SecurityAlertSuppressionRule.objects.create(name=name, source=self.source, reason="test", is_active=True)

    def test_revoke_needs_reason_then_revokes_selected(self):
        r1, r2, r3 = self._rule("R1"), self._rule("R2"), self._rule("R3")
        url = reverse("security:suppressions_bulk")
        self.client.post(url, {"rule_ids": [r1.pk, r2.pk]})
        self.assertEqual(SecurityAlertSuppressionRule.objects.filter(is_active=True).count(), 3)
        self.client.post(url, {"rule_ids": [r1.pk, r2.pk], "reason": "Falsi positivi finiti"})
        live = set(SecurityAlertSuppressionRule.objects.filter(is_active=True, revoked_at__isnull=True).values_list("pk", flat=True))
        self.assertEqual(live, {r3.pk})


class VpnUserPreviewTests(_Base):
    def test_user_panel(self):
        now = timezone.now()
        for i, (action, ip) in enumerate((("allowed", "203.0.113.1"), ("denied", "203.0.113.2"), ("allowed", "203.0.113.1"))):
            SecurityVpnAccess.objects.create(source=self.source, action=action, username="utente.demo", source_ip=ip, kind="vpn",
                                             login_at=now - timedelta(hours=i + 1), duration_seconds=600, dedup_hash=f"v{i}")
        response = self.client.get(reverse("security:preview_vpn_user"), {"utente": "utente.demo"})
        self.assertContains(response, "utente.demo")
        self.assertContains(response, "<dt>IP diversi</dt><dd>2</dd>", html=False)
        self.assertContains(response, "<dt>Accessi</dt><dd>3</dd>", html=False)
        page = self.client.get(reverse("security:vpn_history"))
        self.assertContains(page, reverse("security:preview_vpn_user") + "?utente=utente.demo")

    def test_unknown_user_404(self):
        self.assertEqual(self.client.get(reverse("security:preview_vpn_user"), {"utente": "nessuno"}).status_code, 404)
