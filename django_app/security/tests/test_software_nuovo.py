"""Programma mai visto prima: evento, alert, badge del catalogo, chiusura alla decisione. Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import SoftwareCatalogEntry
from security.models import SecurityAlert, SecurityEventRecord, SoftwareInstallation
from security.services import software_nuovo, software_policy


def _sw(host, vendor, product, version="1.0", giorni_fa=0, still=True):
    quando = timezone.now() - timedelta(days=giorni_fa)
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{vendor}|{product}|{version}", source_kind="watchguard", fonti=["watchguard"], host=host, host_display=host.upper(),
        vendor=vendor, vendor_raw=vendor.title(), product=product, product_raw=product.title(), version_raw=version, still_detected=still,
        seen_at=quando, last_seen_at=timezone.now(),
    )


class ProgrammiNuoviTests(TestCase):
    def test_nuovo_solo_se_prima_comparsa_recente_e_senza_decisione(self):
        _sw("pc-01", "acme", "fresh tool", giorni_fa=2)
        _sw("pc-02", "acme", "fresh tool", giorni_fa=1)
        _sw("pc-01", "acme", "old tool", giorni_fa=40)
        _sw("pc-01", "acme", "decided tool", giorni_fa=3)
        SoftwareCatalogEntry.objects.create(inventory_key="acme|decided tool", classification=SoftwareCatalogEntry.CLASS_ALLOWED)
        nuovi = software_nuovo.programmi_nuovi()
        self.assertEqual([(r["key"], r["hosts"]) for r in nuovi], [("acme|fresh tool", 2)])
        self.assertEqual(nuovi[0]["dal"].date(), (timezone.now() - timedelta(days=2)).date())

    def test_versione_nuova_di_programma_vecchio_non_e_nuova(self):
        _sw("pc-01", "igor", "7-zip 25.01", version="25.01", giorni_fa=200, still=False)
        _sw("pc-01", "igor", "7-zip 26.05", version="26.05", giorni_fa=1)
        self.assertEqual(software_nuovo.programmi_nuovi(), [])

    def test_evento_una_volta_sola_e_alert_che_si_chiude_alla_decisione(self):
        _sw("pc-01", "acme", "fresh tool", giorni_fa=1)
        self.assertEqual(software_policy.run(), 1)
        self.assertEqual(SecurityEventRecord.objects.filter(event_type="software_nuovo").count(), 1)
        alert = SecurityAlert.objects.get(event__event_type="software_nuovo")
        self.assertEqual(alert.title, "Programma nuovo: Fresh Tool su 1 PC")
        self.assertEqual(software_policy.run(), 0)
        self.assertEqual(SecurityEventRecord.objects.filter(event_type="software_nuovo").count(), 1)
        SoftwareCatalogEntry.objects.create(inventory_key="acme|fresh tool", classification=SoftwareCatalogEntry.CLASS_ALLOWED)
        software_policy.run()
        alert.refresh_from_db()
        self.assertEqual(alert.status, "resolved")
        self.assertIn("decisione", alert.status_reason)

    def test_spento_niente_eventi(self):
        from security.services import soc_settings

        soc_settings.save({"software.nuovo.alert": False}, None)
        _sw("pc-01", "acme", "fresh tool", giorni_fa=1)
        self.assertEqual(software_nuovo.record_events(), [])


class CatalogoTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("nuovo-demo", "nuovo@example.test", "x")
        self.client.force_login(self.user)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})

    def test_badge_e_filtro_nuovi(self):
        _sw("pc-01", "acme", "fresh tool", giorni_fa=1)
        _sw("pc-01", "acme", "old tool", giorni_fa=60)
        risposta = self.client.get(reverse("assets:software_catalog") + "?f=nuovi")
        self.assertContains(risposta, "nuovo dal")
        self.assertContains(risposta, "Seleziona Fresh Tool")
        self.assertNotContains(risposta, "Seleziona Old Tool")  # fuori dal filtro (resta solo nella scelta della dotazione)
