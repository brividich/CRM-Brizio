"""Dalla CVE al caso con un'attività per PC, che segue l'inventario. Dati sintetici."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import SecurityCaseTask, SecurityCveImpact, SecurityCveRecord, SecurityRemediationTicket, SoftwareInstallation, Status
from security.services import cve_lavoro


class _Base(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("lav-demo", "lav@example.test", "x")
        self.client.force_login(self.user)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        self.cve = SecurityCveRecord.objects.create(cve_id="CVE-2099-0001", description="Falla demo", cvss=8.1, severity="high",
                                                    configurations=[{"vendor": "demo", "product": "tool", "end_excluding": "2.0"}])
        self.esponi("pc-01")
        self.esponi("pc-02")

    def esponi(self, host):
        now = timezone.now()
        inst, _ = SoftwareInstallation.objects.get_or_create(dedup_key=f"{host}|tool", defaults=dict(
            source_kind="watchguard", host=host, host_display=host.upper(), vendor="demo", vendor_raw="Demo", product="tool", product_raw="Demo Tool",
            version_raw="1.0", still_detected=True, seen_at=now, last_seen_at=now))
        SecurityCveImpact.objects.create(cve=self.cve, host=host, installation=inst, outcome=SecurityCveImpact.IMPACTS, computed_at=now)

    def guarisci(self, host):
        SecurityCveImpact.objects.filter(cve=self.cve, host=host).delete()

    def apri(self):
        return cve_lavoro.apri_lavoro(self.cve, self.user)


class AperturaTests(_Base):
    def test_un_attivita_per_pc_con_versione_corretta(self):
        caso = self.apri()
        self.assertEqual(caso.status, Status.IN_PROGRESS)
        self.assertEqual(caso.cve, "CVE-2099-0001")
        self.assertEqual(caso.title, "Correggere CVE-2099-0001 su 2 PC")
        self.assertIn("2.0", caso.description)
        self.assertEqual(caso.assignee, self.user)
        self.assertEqual(sorted(t.title for t in caso.tasks.all()), ["PC-01: aggiornare Demo Tool 1.0", "PC-02: aggiornare Demo Tool 1.0"])

    def test_due_volte_lo_stesso_caso(self):
        self.assertEqual(self.apri().pk, self.apri().pk)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 1)

    def test_senza_pc_colpiti_non_apre(self):
        self.guarisci("pc-01")
        self.guarisci("pc-02")
        with self.assertRaises(ValueError):
            self.apri()


class InventarioTests(_Base):
    def test_pc_corretto_si_spunta_e_ultimo_chiude(self):
        caso = self.apri()
        self.guarisci("pc-01")
        self.assertFalse(cve_lavoro.aggiorna(self.cve))
        self.assertTrue(caso.tasks.get(cve_host="pc-01").done)
        self.assertFalse(caso.tasks.get(cve_host="pc-02").done)
        self.guarisci("pc-02")
        self.assertTrue(cve_lavoro.aggiorna(self.cve))
        caso.refresh_from_db()
        self.assertEqual(caso.status, Status.RESOLVED)
        self.assertIsNone(cve_lavoro.lavoro_aperto(self.cve))

    def test_recidiva_e_pc_nuovo(self):
        caso = self.apri()
        self.guarisci("pc-01")
        cve_lavoro.aggiorna(self.cve)
        self.esponi("pc-01")
        self.esponi("pc-03")
        cve_lavoro.aggiorna(self.cve)
        self.assertFalse(caso.tasks.get(cve_host="pc-01").done)
        self.assertTrue(caso.tasks.filter(cve_host="pc-03", done=False).exists())

    def test_attivita_a_mano_tiene_aperto_il_caso(self):
        caso = self.apri()
        SecurityCaseTask.objects.create(ticket=caso, title="Avvisare il fornitore")
        self.guarisci("pc-01")
        self.guarisci("pc-02")
        self.assertFalse(cve_lavoro.aggiorna(self.cve))
        caso.refresh_from_db()
        self.assertEqual(caso.status, Status.IN_PROGRESS)
        self.assertFalse(caso.tasks.get(title="Avvisare il fornitore").done)

    def test_il_ricalcolo_lo_aggiorna(self):
        self.apri()
        with patch("security.services.cve_impact.evaluate", return_value=({}, [])):
            from security.services import cve_impact

            cve_impact.recompute(self.cve)
        caso = SecurityRemediationTicket.objects.get()
        self.assertEqual(caso.status, Status.RESOLVED)


class PaginaTests(_Base):
    def url(self):
        return reverse("security:cve_detail", args=[self.cve.cve_id])

    def test_pulsante_e_apertura(self):
        pagina = self.client.get(self.url())
        self.assertContains(pagina, "Apri il lavoro di correzione")
        r = self.client.post(reverse("security:cve_lavoro_apri", args=[self.cve.cve_id]))
        caso = SecurityRemediationTicket.objects.get()
        self.assertRedirects(r, reverse("security:case_detail", args=[caso.pk]), fetch_redirect_response=False)
        pagina = self.client.get(self.url())
        self.assertContains(pagina, "0 PC su 2")
        self.assertNotContains(pagina, "Apri il lavoro di correzione")

    def test_nessun_pc_nessun_pulsante(self):
        self.guarisci("pc-01")
        self.guarisci("pc-02")
        self.assertNotContains(self.client.get(self.url()), "Apri il lavoro di correzione")

    def test_negato_senza_soc(self):
        with patch("security.views_vuln.can_view_security_center", return_value=False):
            self.client.post(reverse("security:cve_lavoro_apri", args=[self.cve.cve_id]))
        self.assertFalse(SecurityRemediationTicket.objects.exists())

    def test_solo_post(self):
        self.assertEqual(self.client.get(reverse("security:cve_lavoro_apri", args=[self.cve.cve_id])).status_code, 405)
