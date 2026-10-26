"""Chiusura del ciclo CVE: progresso per PC, chiusura con due prove, recidiva, metriche. Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityCveRecord,
    SecurityRemediationTicket,
    SoftwareCpeMapping,
    SoftwareInstallation,
    Status,
    WatchGuardPatch,
)
from security.services import auto_resolution, cve_chiusura, cve_impact, defender_vuln, soc_settings
from security.services.configuration import set_setting

CVE = "CVE-2099-0501"


class _Base(TestCase):
    def setUp(self):
        cache.delete_many([cve_impact.LOCK_KEY, cve_impact.QUEUED_KEY, cve_impact.RERUN_KEY])
        self.addCleanup(cache.delete_many, [cve_impact.LOCK_KEY, cve_impact.QUEUED_KEY, cve_impact.RERUN_KEY])
        self.admin = get_user_model().objects.create(username="cve_ch_admin", is_staff=True, is_superuser=True)
        SoftwareCpeMapping.objects.create(vendor="acme", product="viewer", cpe_vendor="acme", cpe_product="viewer", confirmed=True)
        self.record = SecurityCveRecord.objects.create(
            cve_id=CVE, description="Sintetica.", cvss=9.8, severity="critical", kev=True, nvd_fetched_at=timezone.now(),
            configurations=[{"vendor": "acme", "product": "viewer", "end_excluding": "2.0"}],
        )
        self.inst = {host: self._inst(host, "1.0") for host in ("pc-ch-01", "pc-ch-02")}
        cve_impact.recompute_all()
        self.alert = self._alert()
        self.assertIsNotNone(self.alert)

    def _inst(self, host, version, giorni_fa=0):
        now = timezone.now()
        # Stessa chiave di una versione già vista (es. versione vecchia reinstallata): la riga torna rilevata.
        obj, _ = SoftwareInstallation.objects.update_or_create(dedup_key=f"{host}|viewer|{version}", defaults=dict(
            source_kind="watchguard", host=host, host_display=host.upper(),
            vendor="acme", vendor_raw="Acme", product="viewer", product_raw="Acme Viewer", version_raw=version,
            fonti=["watchguard", "defender"], still_detected=True, seen_at=now, last_seen_at=now,
            last_inventory_date=timezone.localdate() - timedelta(days=giorni_fa),
        ))
        return obj

    def _alert(self):
        return SecurityAlert.objects.filter(event__event_type=cve_impact.IMPACT_EVENT_TYPE).order_by("pk").first()

    def _aggiorna(self, host, version="2.1", giorni_fa=0):
        """Il PC viene aggiornato: la versione vecchia non è più rilevata, arriva la nuova."""
        SoftwareInstallation.objects.filter(pk=self.inst[host].pk).update(still_detected=False)
        self.inst[host] = self._inst(host, version, giorni_fa)

    def _patch_installata(self, host):
        WatchGuardPatch.objects.create(device_id=f"d-{host}", patch_id="p1", host=host, nome="Acme Viewer 2.1",
                                       cve=f"|{CVE}|", presente=False, chiusa_il=timezone.now())

    def _defender(self, vede_su=()):
        soc_settings.save({"defender.vulnerabilita.attivo": True}, None)
        pc = [{"id": f"m-{h}", "computerDnsName": f"{h}.dominio.local"} for h in ("pc-ch-01", "pc-ch-02")]
        righe = [{"machineId": f"m-{h}", "cveId": CVE, "productName": "viewer", "productVersion": "1.0"} for h in vede_su]
        righe.append({"machineId": "m-pc-ch-01", "cveId": "CVE-2099-9999", "productName": "altro", "productVersion": "1"})
        defender_vuln.sincronizza(pc=pc, righe=righe)

    def _stati(self):
        return {r["host"]: r["stato"] for r in cve_chiusura.analisi(self.alert)["pc"]}


class ProgressoTests(_Base):
    def test_titolo_e_timeline_seguono_i_pc_che_escono(self):
        self.assertIn("2 PC con versione vulnerabile", self.alert.title)
        self._aggiorna("pc-ch-01")
        cve_impact.recompute(self.record)
        self.alert.refresh_from_db()
        self.assertIn("1 PC su 2 ancora con versione vulnerabile", self.alert.title)
        self.assertIn(self.alert.status, auto_resolution.ACTIVE_ALERT_STATUSES)
        log = SecurityAlertActionLog.objects.get(alert=self.alert, action=cve_chiusura.AZIONE_PC_RISOLTO)
        self.assertEqual((log.details["host"], log.details["versione_prima"], log.details["versione_dopo"]), ("pc-ch-01", "1.0", "2.1"))
        self.assertIn("aggiornato da 1.0 a 2.1", log.details["testo"])
        self.assertIn("inventario del", log.details["testo"])
        stati = self._stati()
        self.assertEqual(stati, {"pc-ch-01": cve_chiusura.IN_ATTESA, "pc-ch-02": cve_chiusura.VULNERABILE})
        self.assertEqual(auto_resolution.run_cve_impatto_risolto(), 0)

    def test_una_prova_sola_non_chiude(self):
        self._aggiorna("pc-ch-01")
        self._aggiorna("pc-ch-02")
        cve_impact.recompute_all()
        self.alert.refresh_from_db()
        self.assertIn(self.alert.status, auto_resolution.ACTIVE_ALERT_STATUSES)
        info = cve_chiusura.analisi(self.alert)
        self.assertFalse(info["chiudibile"])
        self.assertIn("prove insufficienti", info["motivo"])
        self.assertEqual(info["conteggi"][cve_chiusura.IN_ATTESA], 2)

    def test_inventario_vecchio_resta_da_verificare(self):
        self._aggiorna("pc-ch-01", giorni_fa=45)
        cve_impact.recompute(self.record)
        self.assertEqual(self._stati()["pc-ch-01"], cve_chiusura.DA_VERIFICARE)
        self.assertEqual(auto_resolution.run_cve_impatto_risolto(), 0)


class ChiusuraConProveTests(_Base):
    def test_due_prove_per_ogni_pc_chiudono_alert_e_ticket(self):
        ticket = SecurityRemediationTicket.objects.get(linked_alerts=self.alert)
        self._aggiorna("pc-ch-01")
        self._aggiorna("pc-ch-02")
        self._patch_installata("pc-ch-01")
        self._patch_installata("pc-ch-02")
        self.assertEqual(auto_resolution.simulate("cve_impatto_risolto")["would_close"], 0)  # non ancora ricalcolato
        cve_impact.recompute_all()
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Status.RESOLVED)
        self.assertIn("2 PC esposti sono aggiornati con 2 prove concordi", self.alert.status_reason)
        log = SecurityAlertActionLog.objects.get(alert=self.alert, action="auto_resolved")
        self.assertEqual(log.details["rule"], "cve_impatto_risolto")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.RESOLVED)
        self.assertEqual(SecurityAlertActionLog.objects.filter(alert=self.alert, action=cve_chiusura.AZIONE_PC_RISOLTO).count(), 2)

    def test_patch_ancora_mancante_o_defender_che_la_vede_bloccano(self):
        self._aggiorna("pc-ch-01")
        self._aggiorna("pc-ch-02")
        self._patch_installata("pc-ch-02")
        WatchGuardPatch.objects.create(device_id="d-pc-ch-01", patch_id="p1", host="pc-ch-01", nome="Acme Viewer 2.1",
                                       cve=f"|{CVE}|", presente=True, disponibilita=1)
        cve_impact.recompute_all()
        self.alert.refresh_from_db()
        self.assertIn(self.alert.status, auto_resolution.ACTIVE_ALERT_STATUSES)
        righe = {r["host"]: r for r in cve_chiusura.analisi(self.alert)["pc"]}
        self.assertEqual(righe["pc-ch-01"]["stato"], cve_chiusura.IN_ATTESA)
        self.assertIn("ancora mancante", righe["pc-ch-01"]["contro"][0])
        self.assertEqual(righe["pc-ch-02"]["stato"], cve_chiusura.CONFERMATO)
        # la patch risulta installata, ma Defender la vede ancora sul PC
        WatchGuardPatch.objects.filter(host="pc-ch-01").update(presente=False, chiusa_il=timezone.now())
        self._defender(vede_su=["pc-ch-01"])
        righe = {r["host"]: r for r in cve_chiusura.analisi(self.alert)["pc"]}
        self.assertEqual(righe["pc-ch-01"]["stato"], cve_chiusura.IN_ATTESA)
        self.assertIn("Defender la vede ancora", righe["pc-ch-01"]["contro"][0])
        self.assertEqual(auto_resolution.run_cve_impatto_risolto(), 0)
        # Defender non la vede più: tre prove, si chiude
        self._defender(vede_su=[])
        self.assertEqual(auto_resolution.run_cve_impatto_risolto(), 1)

    def test_pc_assente_non_verificabile_finche_una_persona_non_lo_esclude(self):
        self._aggiorna("pc-ch-02")
        self._patch_installata("pc-ch-02")
        SoftwareInstallation.objects.filter(host="pc-ch-01").update(still_detected=False)  # PC sparito dall'inventario
        cve_impact.recompute_all()
        self.alert.refresh_from_db()
        self.assertIn(self.alert.status, auto_resolution.ACTIVE_ALERT_STATUSES)
        info = cve_chiusura.analisi(self.alert)
        riga = next(r for r in info["pc"] if r["host"] == "pc-ch-01")
        self.assertEqual(riga["stato"], cve_chiusura.NON_VERIFICABILE)
        self.assertIn("non più nell'inventario", riga["nota"])
        self.assertIn("non verificabile", info["motivo"])
        with self.assertRaises(ValueError):
            cve_chiusura.escludi_pc(self.alert, "pc-ch-02", "no", actor="tester")  # confermato: non si esclude
        with self.assertRaises(ValueError):
            cve_chiusura.escludi_pc(self.alert, "pc-ch-01", "", actor="tester")  # senza motivo
        cve_chiusura.escludi_pc(self.alert, "pc-ch-01", "PC dismesso a settembre", actor="tester")
        log = SecurityAlertActionLog.objects.get(alert=self.alert, action=cve_chiusura.AZIONE_PC_ESCLUSO)
        self.assertEqual((log.actor, log.details["motivo"]), ("tester", "PC dismesso a settembre"))
        self.assertEqual(self._stati()["pc-ch-01"], cve_chiusura.ESCLUSO)
        self.assertEqual(auto_resolution.run_cve_impatto_risolto(), 1)
        self.alert.refresh_from_db()
        self.assertIn("1 PC escluso dalla verifica", self.alert.status_reason)

    def test_regola_spenta_lascia_aperto(self):
        set_setting("autoresolve.cve_impatto_risolto.attivo", False)
        self._aggiorna("pc-ch-01")
        self._aggiorna("pc-ch-02")
        self._patch_installata("pc-ch-01")
        self._patch_installata("pc-ch-02")
        cve_impact.recompute_all()
        self.alert.refresh_from_db()
        self.assertIn(self.alert.status, auto_resolution.ACTIVE_ALERT_STATUSES)
        self.assertTrue(cve_chiusura.analisi(self.alert)["chiudibile"])
        self.assertEqual(auto_resolution.simulate("cve_impatto_risolto")["would_close"], 1)


class RecidivaEMetricheTests(_Base):
    def _chiudi(self):
        self._aggiorna("pc-ch-01")
        self._aggiorna("pc-ch-02")
        self._patch_installata("pc-ch-01")
        self._patch_installata("pc-ch-02")
        cve_impact.recompute_all()
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Status.RESOLVED)

    def test_versione_vulnerabile_ricomparsa_riapre_lo_stesso_alert(self):
        self._chiudi()
        self._aggiorna("pc-ch-01", version="1.0")  # qualcuno ha reinstallato la versione vecchia
        cve_impact.recompute_all()
        self.assertEqual(SecurityAlert.objects.filter(event__event_type=cve_impact.IMPACT_EVENT_TYPE).count(), 1)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Status.OPEN)
        self.assertTrue(self.alert.title.startswith("Recidiva"))
        self.assertIn("1 PC su 2 ancora", self.alert.title)
        self.assertIn("Recidiva", self.alert.status_reason)
        log = SecurityAlertActionLog.objects.get(alert=self.alert, action=cve_chiusura.AZIONE_RECIDIVA)
        self.assertEqual(log.details["hosts"], ["pc-ch-01"])
        self.assertTrue(cve_chiusura.analisi(self.alert)["recidiva"])

    def test_chiusura_a_mano_non_e_recidiva(self):
        self._aggiorna("pc-ch-01")
        self._aggiorna("pc-ch-02")
        cve_impact.recompute_all()
        from security.services.alert_lifecycle import close_alert

        close_alert(self.alert, actor="tester", reason="verificato a mano")
        self._aggiorna("pc-ch-01", version="1.0")
        cve_impact.recompute_all()
        self.assertEqual(SecurityAlert.objects.filter(event__event_type=cve_impact.IMPACT_EVENT_TYPE).count(), 2)
        self.assertFalse(SecurityAlertActionLog.objects.filter(action=cve_chiusura.AZIONE_RECIDIVA).exists())

    def test_metriche(self):
        self._chiudi()
        m = cve_chiusura.metriche()
        self.assertEqual((m["correzioni"], m["correzioni_gravi"], m["chiusi"], m["auto"], m["manuali"], m["pct_auto"]), (2, 2, 1, 1, 0, 100))
        self.assertIsNotNone(m["giorni_medi"])
        self.assertEqual((m["recidive"], m["aperti"]), (0, 0))
        self.client.force_login(self.admin)
        page = self.client.get(reverse("security:vulnerabilities"))
        self.assertContains(page, "Dalla segnalazione alla correzione")
        self.assertContains(page, "100% da soli con le prove")


class PaginaAlertTests(_Base):
    def test_pannello_ed_esclusione_via_post(self):
        self._aggiorna("pc-ch-02")
        SoftwareInstallation.objects.filter(host="pc-ch-01").update(still_detected=False)
        cve_impact.recompute_all()
        self.client.force_login(self.admin)
        page = self.client.get(reverse("security:alert_detail", args=[self.alert.pk]))
        self.assertContains(page, "Chiusura con prove")
        self.assertContains(page, "Non verificabile")
        self.assertContains(page, "Aggiornamento rilevato, in attesa di conferma")
        self.assertContains(page, "Escludi dalla verifica")
        self.client.post(reverse("security:alert_cve_escludi_pc", args=[self.alert.pk]), {"host": "pc-ch-01", "motivo": "dismesso"})
        self.assertEqual(self._stati()["pc-ch-01"], cve_chiusura.ESCLUSO)
        page = self.client.get(reverse("security:alert_detail", args=[self.alert.pk]))
        self.assertContains(page, "Annulla esclusione")
        self.assertContains(page, "escluso dalla verifica da cve_ch_admin")
        self.client.post(reverse("security:alert_cve_escludi_pc", args=[self.alert.pk]), {"host": "pc-ch-01", "annulla": "1", "motivo": "x"})
        self.assertEqual(self._stati()["pc-ch-01"], cve_chiusura.NON_VERIFICABILE)

    def test_senza_permesso_di_configurazione_niente_esclusione(self):
        utente = get_user_model().objects.create(username="cve_ch_lettore")
        self.client.force_login(utente)
        self.client.post(reverse("security:alert_cve_escludi_pc", args=[self.alert.pk]), {"host": "pc-ch-01", "motivo": "x"})
        self.assertFalse(SecurityAlertActionLog.objects.filter(action=cve_chiusura.AZIONE_PC_ESCLUSO).exists())
