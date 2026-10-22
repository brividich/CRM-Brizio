"""Storico delle CVE risolte: il ricalcolo registra perché un PC non è più esposto. Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from security.models import (
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityCveRisoluzione,
    SoftwareCpeMapping,
    SoftwareInstallation,
)
from security.services import cve_impact, cve_pannello


class CveRisoluzioniTests(TestCase):
    def setUp(self):
        self.pc = Asset.objects.create(asset_tag="RIS-1", name="PC-RIS-01")
        SoftwareCpeMapping.objects.create(vendor="acme", product="viewer", cpe_vendor="acme", cpe_product="viewer", confirmed=True)
        self.record = SecurityCveRecord.objects.create(
            cve_id="CVE-2099-0101", description="Sintetica.", cvss=8.0,
            configurations=[{"vendor": "acme", "product": "viewer", "end_excluding": "2.0"}],
        )
        self.vecchia = self._inst("pc-ris-01", "1.0", hub=self.pc)
        self.altro_pc = self._inst("pc-ris-02", "1.5")
        cve_impact.recompute(self.record)

    def _inst(self, host, version, hub=None, product="viewer"):
        now = timezone.now()
        return SoftwareInstallation.objects.create(
            dedup_key=f"{host}|{product}|{version}", source_kind="watchguard", host=host, host_display=host.upper(),
            hub_asset=hub, vendor="acme", vendor_raw="Acme", product=product, product_raw="Acme Viewer", version_raw=version,
            fonti=["watchguard"], still_detected=True, seen_at=now, last_seen_at=now, last_inventory_date=timezone.localdate(),
        )

    def _impattati(self):
        return set(self.record.impacts.filter(outcome=SecurityCveImpact.IMPACTS).values_list("host", flat=True))

    def test_aggiornamento_rilevato_chiude_e_registra_le_versioni(self):
        self.assertEqual(self._impattati(), {"pc-ris-01", "pc-ris-02"})
        aperta_dal = self.record.impacts.get(host="pc-ris-01").aperta_dal
        self.assertIsNotNone(aperta_dal)
        # il PC viene aggiornato: il nuovo inventario segna la vecchia versione come non più rilevata
        SoftwareInstallation.objects.filter(pk=self.vecchia.pk).update(still_detected=False)
        self._inst("pc-ris-01", "2.1", hub=self.pc)
        cve_impact.recompute(self.record)
        self.assertEqual(self._impattati(), {"pc-ris-02"})
        r = SecurityCveRisoluzione.objects.get(host="pc-ris-01")
        self.assertEqual((r.come, r.versione_prima, r.versione_dopo), (SecurityCveRisoluzione.AGGIORNATO, "1.0", "2.1"))
        self.assertEqual(r.hub_asset, self.pc)
        self.assertEqual(r.aperta_dal, aperta_dal)
        self.assertTrue(r.correzione)

    def test_aperta_dal_resta_tra_un_ricalcolo_e_l_altro(self):
        prima = self.record.impacts.get(host="pc-ris-02").aperta_dal
        SecurityCveImpact.objects.filter(host="pc-ris-02").update(aperta_dal=prima - timedelta(days=10))
        cve_impact.recompute(self.record)
        self.assertEqual(self.record.impacts.get(host="pc-ris-02").aperta_dal, prima - timedelta(days=10))
        self.assertFalse(SecurityCveRisoluzione.objects.exists())

    def test_disinstallato_e_pc_uscito(self):
        self._inst("pc-ris-02", "9.9", product="altro")  # il PC resta nell'inventario con altri programmi
        SoftwareInstallation.objects.filter(pk__in=[self.vecchia.pk, self.altro_pc.pk]).update(still_detected=False)
        cve_impact.recompute(self.record)
        come = dict(SecurityCveRisoluzione.objects.values_list("host", "come"))
        self.assertEqual(come, {"pc-ris-01": SecurityCveRisoluzione.PC_ASSENTE, "pc-ris-02": SecurityCveRisoluzione.RIMOSSO})

    def test_rivalutata_se_la_versione_non_cambia(self):
        self.record.configurations = [{"vendor": "acme", "product": "viewer", "end_excluding": "0.5"}]
        self.record.save()
        cve_impact.recompute(self.record)
        r = SecurityCveRisoluzione.objects.get(host="pc-ris-01")
        self.assertEqual(r.come, SecurityCveRisoluzione.RIVALUTATA)
        self.assertFalse(r.correzione)

    def test_pannelli_mostrano_le_risolte(self):
        SoftwareInstallation.objects.filter(pk=self.vecchia.pk).update(still_detected=False)
        self._inst("pc-ris-01", "2.1", hub=self.pc)
        cve_impact.recompute(self.record)
        self.assertEqual(cve_pannello.per_asset(self.pc)["corrette"], 1)
        self.assertEqual(cve_pannello.dettaglio(self.record.cve_id)["corrette"], 1)
        self.assertEqual(cve_pannello.per_programma("acme|viewer")["corrette"], 1)
        admin = get_user_model().objects.create(username="ris_admin", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        page = self.client.get(reverse("security:cve_pannello_cve", args=[self.record.cve_id]))
        self.assertContains(page, "Risolte negli ultimi 90 giorni")
        self.assertContains(page, "Programma aggiornato")
        self.assertContains(page, "1.0 &#8594; 2.1", html=False)
