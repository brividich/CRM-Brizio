"""Piano di aggiornamento Windows: caso con un'attività per PC, che segue l'inventario. Dati sintetici."""
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import SecurityCaseTask, SecurityRemediationTicket, SoftwareInstallation, Status
from security.services import windows_lavoro

OGGI = date(2026, 11, 6)


def _win(host, version, product="Windows 11 Pro"):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{product}|{version}", source_kind="watchguard", fonti=["watchguard"], host=host, host_display=host.upper(),
        vendor="microsoft", vendor_raw="Microsoft", product=product.lower(), product_raw=product, version_raw=version, still_detected=True,
        seen_at=now, last_seen_at=now,
    )


class _Base(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("win-demo", "win@example.test", "x")
        self.client.force_login(self.user)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        self.fuori = _win("pc-old", "10.0.26100.1234")      # 24H2 Pro: fine 13/10/2026
        self.scade = _win("pc-soon", "10.0.26100.1234")
        self.ok = _win("pc-new", "10.0.26200.1234")         # 25H2


class PianoTests(_Base):
    def test_caso_con_attivita_per_pc_fuori_o_in_scadenza(self):
        caso = windows_lavoro.apri_lavoro(self.user, OGGI)
        self.assertEqual(caso.affected_product, windows_lavoro.MARCATORE)
        self.assertEqual(caso.title, "Aggiornare Windows su 2 PC (2 fuori supporto)")
        titoli = sorted(caso.tasks.values_list("title", flat=True))
        self.assertEqual(titoli, ["pc-old: Windows 11 24H2 fuori supporto, fine supporto 13/10/2026",
                                  "pc-soon: Windows 11 24H2 fuori supporto, fine supporto 13/10/2026"])
        self.assertEqual(windows_lavoro.apri_lavoro(self.user, OGGI).pk, caso.pk)

    def test_in_scadenza_prima_della_data(self):
        caso = windows_lavoro.apri_lavoro(self.user, date(2026, 9, 1))
        self.assertEqual(caso.title, "Aggiornare Windows su 2 PC (2 in scadenza)")
        self.assertEqual(caso.severity, "medium")

    def test_senza_pc_non_apre(self):
        SoftwareInstallation.objects.filter(host__in=["pc-old", "pc-soon"]).delete()
        with self.assertRaises(ValueError):
            windows_lavoro.apri_lavoro(self.user, OGGI)

    def test_pc_aggiornato_si_spunta_e_ultimo_chiude(self):
        caso = windows_lavoro.apri_lavoro(self.user, OGGI)
        self.fuori.version_raw = "10.0.26200.1"
        self.fuori.save()
        self.assertFalse(windows_lavoro.aggiorna(OGGI))
        self.assertTrue(SecurityCaseTask.objects.get(ticket=caso, cve_host="pc-old").done)
        self.assertEqual(SecurityRemediationTicket.objects.get(pk=caso.pk).title, "Aggiornare Windows su 1 PC (1 fuori supporto)")
        self.scade.still_detected = False
        self.scade.save()
        self.assertTrue(windows_lavoro.aggiorna(OGGI))
        caso.refresh_from_db()
        self.assertEqual(caso.status, Status.RESOLVED)
        self.assertIn("nessun PC", caso.resolution)

    def test_pc_nuovo_aggiunge_attivita(self):
        caso = windows_lavoro.apri_lavoro(self.user, OGGI)
        _win("pc-extra", "10.0.22631.1")
        windows_lavoro.aggiorna(OGGI)
        self.assertEqual(caso.tasks.count(), 3)


class PaginaTests(_Base):
    def test_pulsante_e_apertura_dalla_pagina(self):
        with patch("security.services.rischio_asset.timezone.localdate", return_value=OGGI):
            risposta = self.client.get(reverse("security:pc_copertura"))
            self.assertContains(risposta, "Apri il piano di aggiornamento Windows (2 PC)")
            risposta = self.client.post(reverse("security:pc_copertura"), {"action": "windows_lavoro"})
            caso = SecurityRemediationTicket.objects.get(affected_product=windows_lavoro.MARCATORE)
            self.assertRedirects(risposta, reverse("security:case_detail", kwargs={"pk": caso.pk}), fetch_redirect_response=False)
            risposta = self.client.get(reverse("security:pc_copertura"))
            self.assertContains(risposta, "0 PC su 2 aggiornati")
            self.assertNotContains(risposta, "Apri il piano di aggiornamento")
