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
    """Nomi simili ma NON equivalenti per l'abbinatore: restano due righe finché non c'è un alias."""

    def setUp(self):
        importa(WG, [("pc-01", "Contoso", "Contoso Reporting Studio", "5.1")])
        importa(DEF, [("pc-01", "Contoso", "Contoso Reporting Studios", "5.1")])

    def test_restano_due_righe_senza_alias(self):
        self.assertEqual(SoftwareInstallation.objects.count(), 2)

    def test_il_comando_propone_lalias_ed_e_ascii(self):
        out = StringIO()
        call_command("software_fonti_confronto", stdout=out)
        testo = out.getvalue()
        self.assertIn("PC visti da entrambe le fonti", testo)
        self.assertIn("contoso reporting studio", testo)
        self.assertIn("~", testo)
        testo.encode("cp1252")  # la console Windows di produzione non regge altro

    def test_alias_fonde_le_righe_e_sposta_gli_impatti(self):
        da_tenere = SoftwareInstallation.objects.get(source_kind=WG)
        da_fondere = SoftwareInstallation.objects.get(source_kind=DEF)
        SoftwareAlias.objects.create(kind=SoftwareAlias.KIND_PRODUCT, raw="contoso reporting studios", canonical="contoso reporting studio")
        SoftwareInstallation.objects.filter(pk=da_fondere.pk).update(product="contoso reporting studio")

        esito = inv.unifica_installazioni()
        self.assertEqual(esito["fuse"], 1)
        self.assertEqual(SoftwareInstallation.objects.count(), 1)
        self.assertEqual(sorted(SoftwareInstallation.objects.get().fonti), [DEF, WG])
        self.assertEqual(SoftwareInstallation.objects.filter(pk__in=[da_tenere.pk, da_fondere.pk]).count(), 1)
        self.assertEqual(inv.unifica_installazioni(), {"fuse": 0, "richiavate": 0})  # idempotente

    def test_dopo_lalias_il_reimport_non_crea_doppioni(self):
        SoftwareAlias.objects.create(kind=SoftwareAlias.KIND_PRODUCT, raw="contoso reporting studios", canonical="contoso reporting studio")
        SoftwareInstallation.objects.filter(source_kind=DEF).update(product="contoso reporting studio")
        inv.unifica_installazioni()
        importa(WG, [("pc-01", "Contoso", "Contoso Reporting Studio", "5.1")])
        importa(DEF, [("pc-01", "Contoso", "Contoso Reporting Studios", "5.1")])
        self.assertEqual(SoftwareInstallation.objects.count(), 1)


class AbbinamentoAutomaticoTests(TestCase):
    """Defender usa nomi brevi («chrome»), WatchGuard quelli completi («Google Chrome»): si fondono da soli."""

    def test_nome_breve_senza_il_produttore(self):
        importa(WG, [("PC-01.local", "Google LLC", "Google Chrome", "130.0.6723.92")])
        imp = importa(DEF, [("pc-01", "google", "chrome", "130.0.6723.92")])
        self.assertEqual(SoftwareInstallation.objects.count(), 1)
        self.assertEqual(imp.rows_new, 0)
        riga = SoftwareInstallation.objects.get()
        self.assertEqual(sorted(riga.fonti), [DEF, WG])
        self.assertEqual(riga.product, "google chrome")  # il nome della prima fonte non cambia

    def test_funziona_anche_al_contrario(self):
        importa(DEF, [("pc-01", "google", "chrome", "130.0.1")])
        importa(WG, [("pc-01", "Google LLC", "Google Chrome", "130.0.1")])
        self.assertEqual(SoftwareInstallation.objects.count(), 1)

    def test_versione_diversa_resta_riga_distinta(self):
        importa(WG, [("pc-01", "Google LLC", "Google Chrome", "130.0.1")])
        importa(DEF, [("pc-01", "google", "chrome", "131.0.1")])
        self.assertEqual(SoftwareInstallation.objects.count(), 2)

    def test_prodotti_diversi_non_si_fondono(self):
        importa(WG, [("pc-01", "Microsoft", "Microsoft Edge", "1.0")])
        importa(DEF, [("pc-01", "microsoft", "microsoft edge webview2 runtime", "1.0")])
        importa(DEF, [("pc-01", "microsoft", "office 2019", "1.0")])
        importa(WG, [("pc-01", "Microsoft", "Microsoft Office", "1.0")])
        # edge ≠ edge webview2 runtime (numero), office ≠ office 2019 (numero)
        self.assertEqual(SoftwareInstallation.objects.filter(host="pc-01").count(), 4)

    def test_produttori_diversi_non_si_fondono(self):
        importa(WG, [("pc-01", "Acme", "Acme Tool", "1.0")])
        importa(DEF, [("pc-01", "Globex", "tool", "1.0")])
        self.assertEqual(SoftwareInstallation.objects.count(), 2)

    def test_due_candidati_alla_pari_non_si_indovina(self):
        importa(WG, [("pc-01", "Acme", "Acme Tool Pro", "1.0"), ("pc-01", "Acme", "Acme Tool Max", "1.0")])
        importa(DEF, [("pc-01", "acme", "tool", "1.0")])
        self.assertEqual(SoftwareInstallation.objects.count(), 3)  # ambiguo: resta una riga nuova

    def test_reimport_non_crea_ne_toglie_nulla(self):
        importa(WG, [("pc-01", "Google LLC", "Google Chrome", "130.0.1")])
        importa(DEF, [("pc-01", "google", "chrome", "130.0.1")])
        for _ in range(2):
            importa(DEF, [("pc-01", "google", "chrome", "130.0.1")])
        riga = SoftwareInstallation.objects.get()
        self.assertEqual(SoftwareInstallation.objects.count(), 1)
        self.assertTrue(riga.still_detected)
        self.assertEqual(sorted(riga.fonti), [DEF, WG])
        importa(DEF, [("pc-01", "altro", "altro", "1.0")])  # Defender non lo vede più: resta per WatchGuard
        riga = SoftwareInstallation.objects.get(product="google chrome")
        self.assertTrue(riga.still_detected)
        self.assertEqual(riga.fonti, [WG])

    def test_un_solo_candidato_non_serve_a_due_righe_dello_stesso_file(self):
        importa(WG, [("pc-01", "Google LLC", "Google Chrome", "130.0.1")])
        importa(DEF, [("pc-01", "google", "chrome", "130.0.1"), ("pc-01", "google", "chrome browser", "130.0.1")])
        # la prima prende la riga WatchGuard, la seconda non può riusarla: due righe in tutto
        self.assertEqual(SoftwareInstallation.objects.count(), 2)


class UnisciPerEquivalenzaTests(TestCase):
    """Per i doppioni già in archivio (importati prima dell'abbinamento automatico)."""

    def _riga(self, fonte, vendor, product, version="1.0", host="pc-01"):
        return SoftwareInstallation.objects.create(
            dedup_key=inv.identity_key(host, vendor, product, version), source_kind=fonte, host=host,
            vendor=vendor, product=product, product_raw=product, version_raw=version, fonti=[fonte],
        )

    def test_anteprima_non_scrive_poi_applica(self):
        from security.models import SecurityCveRecord

        wg = self._riga(WG, "google", "google chrome")
        df = self._riga(DEF, "google", "chrome")
        altro = self._riga(DEF, "acme", "qualcosa")
        cve = SecurityCveRecord.objects.create(cve_id="CVE-2026-0002")
        SecurityCveImpact.objects.create(cve=cve, host="pc-01", installation=df, outcome=SecurityCveImpact.IMPACTS, explanation="prova")

        out = StringIO()
        call_command("software_fonti_unisci", stdout=out)
        self.assertIn("Coppie da fondere: 1", out.getvalue())
        self.assertEqual(SoftwareInstallation.objects.count(), 3)  # anteprima: nessuna modifica
        out.getvalue().encode("cp1252")

        out = StringIO()
        call_command("software_fonti_unisci", "--applica", stdout=out)
        self.assertEqual(SoftwareInstallation.objects.count(), 2)
        tenuta = SoftwareInstallation.objects.get(pk=wg.pk)  # si tiene la più vecchia
        self.assertEqual(sorted(tenuta.fonti), [DEF, WG])
        self.assertEqual(SecurityCveImpact.objects.get().installation_id, tenuta.pk)
        self.assertTrue(SoftwareInstallation.objects.filter(pk=altro.pk).exists())
        self.assertFalse(SoftwareInstallation.objects.filter(pk=df.pk).exists())
        self.assertEqual(inv.unisci_per_equivalenza()["coppie"], [])  # idempotente

    def test_ambigui_e_stessa_fonte_si_saltano(self):
        self._riga(WG, "acme", "acme tool pro")
        self._riga(WG, "acme", "acme tool max")
        self._riga(DEF, "acme", "tool")
        esito = inv.unisci_per_equivalenza(applica=True)
        self.assertEqual(esito["fuse"], 0)
        self.assertGreaterEqual(esito["ambigue"], 1)
        self.assertEqual(SoftwareInstallation.objects.count(), 3)


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

