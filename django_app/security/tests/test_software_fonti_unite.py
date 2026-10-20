"""Inventario software: lo stesso software da più fonti è una riga sola; le release si raggruppano per prodotto."""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from security.models import (
    SecurityCveImpact,
    SoftwareAlias,
    SoftwareInstallation,
    SoftwareInventoryImport,
    SoftwareSourceKind,
)
from security.services import software_inventory as inv
from security.services.software_catalog import catalog, software_for_hub_asset, versions_by_key

WG = SoftwareSourceKind.WATCHGUARD
DEF = SoftwareSourceKind.DEFENDER


def importa(fonte, righe):
    """``righe``: [(host, vendor, prodotto, versione)] come le produrrebbe un export."""
    item = SoftwareInventoryImport.objects.create(source_kind=fonte, original_name=f"{fonte}.csv", file_sha256="x" * 64)
    preview = inv.RowPreview(total=len(righe))
    preview.valid = [
        {"host": h, "vendor": v, "product": p, "version": ver, "detected_at": None} for h, v, p, ver in righe
    ]
    return inv.run_import(item, preview)


class DueFontiTests(TestCase):
    def test_stesso_software_da_due_fonti_e_una_riga(self):
        importa(WG, [("PC-01.local", "Microsoft Corporation", "Visual Studio Code", "1.90.0")])
        imp = importa(DEF, [("pc-01", "microsoft_corporation".replace("_", " "), "visual studio code", "1.90.0")])
        self.assertEqual(SoftwareInstallation.objects.count(), 1)
        self.assertEqual(imp.rows_new, 0)
        riga = SoftwareInstallation.objects.get()
        self.assertEqual(sorted(riga.fonti), [DEF, WG])
        self.assertEqual(riga.fonti_etichette, ["Microsoft Defender for Endpoint", "WatchGuard EPDR / Panda"])

    def test_reimport_stessa_fonte_idempotente(self):
        righe = [("pc-01", "Acme", "Tool", "1.0")]
        importa(WG, righe)
        importa(WG, righe)
        self.assertEqual(SoftwareInstallation.objects.count(), 1)
        self.assertEqual(SoftwareInstallation.objects.get().fonti, [WG])

    def test_sparito_da_una_fonte_resta_se_laltra_lo_vede(self):
        importa(WG, [("pc-01", "Acme", "Tool", "1.0")])
        importa(DEF, [("pc-01", "Acme", "Tool", "1.0")])
        importa(DEF, [("pc-01", "Acme", "Altro", "2.0")])  # Defender non vede più Tool
        tool = SoftwareInstallation.objects.get(product="tool")
        self.assertTrue(tool.still_detected)
        self.assertEqual(tool.fonti, [WG])
        importa(WG, [])  # nessun host nel file: non cambia nulla
        self.assertTrue(SoftwareInstallation.objects.get(product="tool").still_detected)
        importa(WG, [("pc-01", "Acme", "Qualcosa", "9")])  # ora anche WatchGuard non lo vede
        tool = SoftwareInstallation.objects.get(product="tool")
        self.assertFalse(tool.still_detected)
        self.assertEqual(tool.fonti, [])

    def test_una_fonte_non_tocca_i_pc_che_non_ha_letto(self):
        importa(WG, [("pc-01", "Acme", "Tool", "1.0"), ("pc-02", "Acme", "Tool", "1.0")])
        importa(DEF, [("pc-01", "Acme", "Tool", "1.0")])  # Defender legge solo pc-01
        self.assertEqual(SoftwareInstallation.objects.filter(still_detected=True).count(), 2)

    def test_release_diverse_si_raggruppano_per_prodotto(self):
        importa(WG, [(f"pc-{i:02d}", "Microsoft", "Microsoft 365 Apps", f"16.0.{17000 + i}.20000") for i in range(10)])
        importa(DEF, [(f"pc-{i:02d}", "Microsoft", "microsoft 365 apps", f"16.0.{17000 + i}.20000") for i in range(10)])
        self.assertEqual(SoftwareInstallation.objects.count(), 10)  # una per PC, non venti
        voci = [c for c in catalog() if c["label"]]
        self.assertEqual(len(voci), 1)  # un solo prodotto nel catalogo
        self.assertEqual(voci[0]["hosts"], 10)
        versioni = versions_by_key()
        self.assertEqual(sum(sum(c.values()) for c in versioni.values()), 10)
        self.assertEqual(len(next(iter(versioni.values()))), 10)  # le 10 release restano distinguibili

    def test_scheda_asset_non_ripete_la_versione(self):
        from assets.models import Asset

        asset = Asset.objects.create(name="PC-01", asset_tag="PC-01", asset_type="PC")
        importa(WG, [("pc-01", "Acme", "Tool", "1.0")])
        importa(DEF, [("pc-01", "Acme", "Tool", "1.0")])
        dati = software_for_hub_asset(asset)
        self.assertEqual(len(dati["rows"]), 1)
        self.assertEqual(dati["rows"][0]["versions"], ["1.0"])


class NomiDiversiAliasTests(TestCase):
    def setUp(self):
        importa(WG, [("pc-01", "Microsoft", "Microsoft 365 Apps for enterprise", "16.0.1")])
        importa(DEF, [("pc-01", "Microsoft", "microsoft 365 apps", "16.0.1")])

    def test_nomi_diversi_restano_due_righe_finche_non_c_e_alias(self):
        self.assertEqual(SoftwareInstallation.objects.count(), 2)

    def test_il_comando_propone_lalias(self):
        out = StringIO()
        call_command("software_fonti_confronto", stdout=out)
        testo = out.getvalue()
        self.assertIn("PC visti da entrambe le fonti", testo)
        self.assertIn("microsoft 365 apps for enterprise", testo)
        self.assertIn("≈", testo)

    def test_alias_fonde_le_righe_e_sposta_gli_impatti(self):
        da_tenere = SoftwareInstallation.objects.get(source_kind=WG)
        da_fondere = SoftwareInstallation.objects.get(source_kind=DEF)
        SoftwareAlias.objects.create(kind=SoftwareAlias.KIND_PRODUCT, raw="microsoft 365 apps for enterprise", canonical="microsoft 365 apps")
        SoftwareInstallation.objects.filter(pk=da_tenere.pk).update(product="microsoft 365 apps")
        from security.models import SecurityAsset  # noqa: F401  (assicura l'app caricata)

        esito = inv.unifica_installazioni()
        self.assertEqual(esito["fuse"], 1)
        self.assertEqual(SoftwareInstallation.objects.count(), 1)
        self.assertEqual(sorted(SoftwareInstallation.objects.get().fonti), [DEF, WG])
        self.assertFalse(SoftwareInstallation.objects.filter(pk__in=[da_tenere.pk, da_fondere.pk]).count() == 2)
        # idempotente
        self.assertEqual(inv.unifica_installazioni(), {"fuse": 0, "richiavate": 0})

    def test_dopo_lalias_il_reimport_non_crea_doppioni(self):
        SoftwareAlias.objects.create(kind=SoftwareAlias.KIND_PRODUCT, raw="microsoft 365 apps for enterprise", canonical="microsoft 365 apps")
        SoftwareInstallation.objects.filter(source_kind=WG).update(product="microsoft 365 apps")
        inv.unifica_installazioni()
        importa(WG, [("pc-01", "Microsoft", "Microsoft 365 Apps for enterprise", "16.0.1")])
        importa(DEF, [("pc-01", "Microsoft", "microsoft 365 apps", "16.0.1")])
        self.assertEqual(SoftwareInstallation.objects.count(), 1)


class FirmwareNonSiFondeTests(TestCase):
    def test_firmware_snmp_restano_per_fonte(self):
        for fonte in (SoftwareSourceKind.SNMP_FIRMWARE, SoftwareSourceKind.WATCHGUARD):
            SoftwareInstallation.objects.create(
                dedup_key=inv.installation_key(fonte, "dev-1", "acme", "fw", "1.0"), source_kind=fonte, host="dev-1",
                vendor="acme", product="fw", product_raw="fw", version_raw="1.0", fonti=[fonte],
            )
        inv.unifica_installazioni()
        self.assertEqual(SoftwareInstallation.objects.count(), 2)


class MigrazioneFusioneTests(TestCase):
    """La migrazione 0025 fonde le righe doppie già in archivio senza perdere gli impatti CVE."""

    def _vecchia(self, fonte, host="pc-01", prodotto="tool", versione="1.0", rilevata=True):
        import hashlib

        chiave = hashlib.sha256("|".join([fonte, host, "acme", prodotto, versione]).encode()).hexdigest()
        return SoftwareInstallation.objects.create(
            dedup_key=chiave, source_kind=fonte, host=host, vendor="acme", product=prodotto, product_raw=prodotto,
            version_raw=versione, still_detected=rilevata, fonti=[],
        )

    def test_righe_doppie_fuse_e_impatti_spostati(self):
        import importlib

        from django.apps import apps

        from security.models import SecurityCveRecord as SecurityCve

        wg = self._vecchia(WG)
        df = self._vecchia(DEF)
        altra = self._vecchia(WG, host="pc-02")
        cve = SecurityCve.objects.create(cve_id="CVE-2026-0001")
        SecurityCveImpact.objects.create(cve=cve, host="pc-01", installation=df, outcome=SecurityCveImpact.IMPACTS, explanation="prova")
        fw = self._vecchia(SoftwareSourceKind.SNMP_FIRMWARE, host="sw-1", prodotto="fw")

        mig = importlib.import_module("security.migrations.0025_software_fonti_unite")
        mig.fondi(apps, None)

        self.assertEqual(SoftwareInstallation.objects.filter(host="pc-01").count(), 1)
        tenuta = SoftwareInstallation.objects.get(host="pc-01")
        self.assertEqual(sorted(tenuta.fonti), [DEF, WG])
        self.assertEqual(tenuta.dedup_key, inv.identity_key("pc-01", "acme", "tool", "1.0"))
        self.assertEqual(SecurityCveImpact.objects.get().installation_id, tenuta.pk)
        self.assertEqual(SoftwareInstallation.objects.get(pk=altra.pk).fonti, [WG])
        self.assertEqual(SoftwareInstallation.objects.get(pk=fw.pk).fonti, [SoftwareSourceKind.SNMP_FIRMWARE])
        self.assertTrue(SoftwareInstallation.objects.filter(pk__in=[wg.pk, df.pk]).count() == 1)

        # un import dopo la migrazione trova la riga fusa e non ne crea altre
        importa(DEF, [("pc-01", "acme", "tool", "1.0")])
        self.assertEqual(SoftwareInstallation.objects.filter(host="pc-01").count(), 1)

