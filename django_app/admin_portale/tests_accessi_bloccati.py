from __future__ import annotations

from datetime import timedelta

from axes.models import AccessAttempt
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog


class AccessiBloccatiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="admin", password="x", email="a@a.it")
        self.user = User.objects.create_user(username="mario", password="x")

    def _tentativo(self, username="utente.prova@esempio.local", errori=5, minuti_fa=1):
        t = AccessAttempt.objects.create(
            username=username, ip_address="10.0.0.50", user_agent="test", http_accept="*/*",
            path_info="/login/", get_data="", post_data="", failures_since_start=errori,
        )
        # attempt_time è auto_now_add: l'ora del tentativo si sposta dopo.
        AccessAttempt.objects.filter(pk=t.pk).update(attempt_time=timezone.now() - timedelta(minutes=minuti_fa))
        return t

    def test_elenco_mostra_bloccati_e_non_bloccati(self):
        self._tentativo()
        self._tentativo(username="altro@esempio.local", errori=2)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("admin_portale:accessi_bloccati"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "utente.prova@esempio.local")
        self.assertContains(r, "Bloccati ora: 1")
        self.assertContains(r, "Azzera errori")
        self.assertContains(r, "Nome utente sconosciuto")

    def test_blocco_scaduto_non_conta(self):
        self._tentativo(minuti_fa=90)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("admin_portale:accessi_bloccati"))
        self.assertContains(r, "Bloccati ora: 0")

    def test_sblocca_cancella_il_tentativo_e_scrive_audit(self):
        t = self._tentativo()
        self.client.force_login(self.admin)
        r = self.client.post(reverse("admin_portale:accessi_bloccati_sblocca"), {"tentativo": t.pk})
        self.assertRedirects(r, reverse("admin_portale:accessi_bloccati"), fetch_redirect_response=False)
        self.assertFalse(AccessAttempt.objects.filter(pk=t.pk).exists())
        self.assertTrue(AuditLog.objects.filter(azione="accesso_sbloccato").exists())

    def test_non_admin_non_sblocca(self):
        t = self._tentativo()
        self.client.force_login(self.user)
        self.client.post(reverse("admin_portale:accessi_bloccati_sblocca"), {"tentativo": t.pk})
        self.assertTrue(AccessAttempt.objects.filter(pk=t.pk).exists())

    def test_sblocca_get_non_ammesso(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("admin_portale:accessi_bloccati_sblocca"))
        self.assertEqual(r.status_code, 405)
