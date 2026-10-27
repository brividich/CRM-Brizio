"""Termini di correzione (ISO 27001 8.8), accettazione del rischio e traccia sigillata. Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from security.models import (
    SecurityAccettazioneRischio,
    SecurityAlert,
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityCveRisoluzione,
    SecurityEventRecord,
    SoftwareCpeMapping,
    SoftwareInstallation,
    Status,
)
from security.services import accettazione_rischio, auto_resolution, cve_impact, cve_sla, soc_settings, traccia
from security.services.alert_lifecycle import close_alert
from security.services.rule_engine import evaluate_security_rules

CVE = "CVE-2099-0801"


def _record(cve_id=CVE, **extra):
    base = dict(description="Sintetica.", cvss=9.8, severity="critical", kev=False, nvd_fetched_at=timezone.now(),
                configurations=[{"vendor": "acme", "product": "viewer", "end_excluding": "2.0"}])
    base.update(extra)
    return SecurityCveRecord.objects.create(cve_id=cve_id, **base)


class ClasseETermineTests(TestCase):
    def test_classe_per_kev_e_cvss(self):
        self.assertEqual(cve_sla.classe(SecurityCveRecord(cve_id="CVE-1", kev=True, cvss=3.0)), "kev")
        self.assertEqual(cve_sla.classe(SecurityCveRecord(cve_id="CVE-2", cvss=9.0)), "critica")
        self.assertEqual(cve_sla.classe(SecurityCveRecord(cve_id="CVE-3", cvss=7.5)), "alta")
        self.assertEqual(cve_sla.classe(SecurityCveRecord(cve_id="CVE-4", cvss=4.0)), "media")
        self.assertEqual(cve_sla.classe(SecurityCveRecord(cve_id="CVE-5", cvss=3.9)), "bassa")
        self.assertEqual(cve_sla.classe(SecurityCveRecord(cve_id="CVE-6", cvss=None, severity="HIGH")), "alta")
        self.assertEqual(cve_sla.classe(SecurityCveRecord(cve_id="CVE-7", cvss=None, severity="")), "bassa")

    def test_scadenza_default_e_data_cisa(self):
        oggi = timezone.localdate()
        aperta = timezone.now()
        self.assertEqual(cve_sla.scadenza(SecurityCveRecord(cve_id="C", cvss=9.5), aperta), oggi + timedelta(days=15))
        self.assertEqual(cve_sla.scadenza(SecurityCveRecord(cve_id="C", cvss=7.0), aperta), oggi + timedelta(days=30))
        self.assertEqual(cve_sla.scadenza(SecurityCveRecord(cve_id="C", cvss=5.0), aperta), oggi + timedelta(days=90))
        self.assertEqual(cve_sla.scadenza(SecurityCveRecord(cve_id="C", cvss=1.0), aperta), oggi + timedelta(days=180))
        self.assertEqual(cve_sla.scadenza(SecurityCveRecord(cve_id="C", kev=True), aperta), oggi + timedelta(days=14))
        due = oggi + timedelta(days=3)
        self.assertEqual(cve_sla.scadenza(SecurityCveRecord(cve_id="C", kev=True, kev_due=due), aperta), due)

    def test_giorni_configurabili(self):
        soc_settings.save({"cve.sla.critica_giorni": 7}, None)
        self.assertEqual(cve_sla.scadenza(SecurityCveRecord(cve_id="C", cvss=9.5), timezone.localdate()), timezone.localdate() + timedelta(days=7))


class _Base(TestCase):
    def setUp(self):
        cache.delete_many([cve_impact.LOCK_KEY, cve_impact.QUEUED_KEY, cve_impact.RERUN_KEY])
        self.addCleanup(cache.delete_many, [cve_impact.LOCK_KEY, cve_impact.QUEUED_KEY, cve_impact.RERUN_KEY])
        self.admin = get_user_model().objects.create(username="sla_admin", is_staff=True, is_superuser=True)
        SoftwareCpeMapping.objects.create(vendor="acme", product="viewer", cpe_vendor="acme", cpe_product="viewer", confirmed=True)
        self.record = _record()
        for host in ("pc-sla-01", "pc-sla-02"):
            self._inst(host, "1.0")
        cve_impact.recompute_all()
        self.assertEqual(self.record.impacts.filter(outcome=SecurityCveImpact.IMPACTS).count(), 2)

    def _inst(self, host, version):
        now = timezone.now()
        return SoftwareInstallation.objects.create(
            dedup_key=f"{host}|viewer|{version}", source_kind="watchguard", host=host, host_display=host.upper(),
            vendor="acme", vendor_raw="Acme", product="viewer", product_raw="Acme Viewer", version_raw=version,
            fonti=["watchguard"], still_detected=True, seen_at=now, last_seen_at=now, last_inventory_date=timezone.localdate(),
        )

    def _retrodata(self, giorni, host=None):
        qs = SecurityCveImpact.objects.filter(cve=self.record)
        if host:
            qs = qs.filter(host=host)
        qs.update(aperta_dal=timezone.now() - timedelta(days=giorni))

    def _sla_alerts(self):
        return SecurityAlert.objects.filter(event__event_type=cve_sla.EVENT_SLA).order_by("pk")


class ScaduteERiepilogoTests(_Base):
    def test_niente_scadute_entro_il_termine(self):
        self.assertEqual(cve_sla.scadute(), [])
        voci = cve_sla.esposizioni_aperte()
        self.assertEqual({v["host"] for v in voci}, {"pc-sla-01", "pc-sla-02"})
        self.assertEqual(voci[0]["scadenza"], timezone.localdate() + timedelta(days=15))

    def test_scadute_dopo_il_termine(self):
        self._retrodata(20, "pc-sla-01")
        scadute = cve_sla.scadute()
        self.assertEqual(len(scadute), 1)
        voce = scadute[0]
        self.assertEqual((voce["cve"], voce["host"], voce["classe"], voce["giorni_ritardo"], voce["accettata"]),
                         (CVE, "pc-sla-01", "critica", 5, False))
        self.assertEqual(voce["scadenza"], timezone.localdate() - timedelta(days=5))

    def test_riepilogo_conta_corrette_in_tempo_e_in_ritardo(self):
        self._retrodata(20, "pc-sla-02")
        ora = timezone.now()
        SecurityCveRisoluzione.objects.create(cve=self.record, host="pc-x", come=SecurityCveRisoluzione.AGGIORNATO,
                                              aperta_dal=ora - timedelta(days=10), risolta_il=ora - timedelta(days=1))
        SecurityCveRisoluzione.objects.create(cve=self.record, host="pc-y", come=SecurityCveRisoluzione.RIMOSSO,
                                              aperta_dal=ora - timedelta(days=40), risolta_il=ora - timedelta(days=1))
        SecurityCveRisoluzione.objects.create(cve=self.record, host="pc-z", come=SecurityCveRisoluzione.PC_ASSENTE,
                                              aperta_dal=ora - timedelta(days=40), risolta_il=ora - timedelta(days=1))
        oggi = timezone.localdate()
        dati = cve_sla.riepilogo(oggi - timedelta(days=90), oggi)
        self.assertEqual([c["classe"] for c in dati["classi"]], ["kev", "critica", "alta", "media", "bassa"])
        critica = dati["classi"][1]
        self.assertEqual((critica["corrette"], critica["in_tempo"], critica["in_ritardo"], critica["aperte"], critica["aperte_scadute"]),
                         (2, 1, 1, 2, 1))
        self.assertEqual(critica["giorni"], 15)
        self.assertEqual(dati["percentuale_in_tempo"], 50)
        self.assertEqual([v["host"] for v in dati["aperte_scadute"]], ["pc-sla-02"])
        self.assertIsNone(cve_sla.riepilogo(oggi - timedelta(days=400), oggi - timedelta(days=300))["percentuale_in_tempo"])


class AutomatismoTerminiTests(_Base):
    def test_evento_e_alert_per_esposizione_oltre_il_termine(self):
        self._retrodata(20, "pc-sla-01")
        creati, chiusi = cve_sla.segnala_scadute()
        self.assertEqual((creati, chiusi), (1, 0))
        evento = SecurityEventRecord.objects.get(event_type=cve_sla.EVENT_SLA)
        self.assertEqual(evento.severity, "high")
        self.assertEqual(evento.payload["host"], "pc-sla-01")
        evaluate_security_rules()
        alert = self._sla_alerts().get()
        self.assertIn("Oltre il termine di correzione", alert.title)
        self.assertIn("pc-sla-01", alert.title)
        self.assertEqual(alert.severity, "high")
        # Stesso termine: nessun doppione al giro dopo.
        self.assertEqual(cve_sla.segnala_scadute()[0], 0)
        self.assertEqual(AuditLog.objects.filter(modulo="security", azione=traccia.CVE_TERMINE_SCADUTO).count(), 1)

    def test_severita_media_per_classe_media(self):
        self.record.cvss, self.record.severity = 5.0, "medium"
        self.record.save()
        self._retrodata(100)
        cve_sla.segnala_scadute()
        self.assertEqual(SecurityEventRecord.objects.filter(event_type=cve_sla.EVENT_SLA, severity="medium").count(), 2)

    def test_spento_niente_eventi(self):
        soc_settings.save({"cve.sla.attivo": False}, None)
        self._retrodata(20)
        self.assertEqual(cve_sla.segnala_scadute(), (0, 0))

    def test_alert_si_chiude_quando_il_pc_rientra(self):
        self._retrodata(20, "pc-sla-01")
        cve_sla.segnala_scadute()
        evaluate_security_rules()
        alert = self._sla_alerts().get()
        SoftwareInstallation.objects.filter(host="pc-sla-01").update(still_detected=False)
        self._inst("pc-sla-01", "2.1")
        cve_impact.recompute(self.record)
        self.assertEqual(cve_sla.segnala_scadute(), (0, 1))
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.RESOLVED)
        self.assertIn("non risulta più esposto", alert.status_reason)
        self.assertTrue(AuditLog.objects.filter(modulo="security", azione=traccia.CVE_TERMINE_RIENTRATO, oggetto_id=str(alert.pk)).exists())
        self.assertTrue(AuditLog.objects.filter(modulo="security", azione=traccia.ALERT_AUTO_RISOLTO, oggetto_id=str(alert.pk)).exists())

    def test_ciclo_soc_include_il_passo(self):
        from security.tasks import run_security_cycle_task

        self._retrodata(20, "pc-sla-02")
        esito = run_security_cycle_task()
        self.assertEqual(esito["termini_cve"]["oltre_termine"], 1)
        self.assertEqual(self._sla_alerts().count(), 1)


class AccettazioneRischioTests(_Base):
    def _accetta(self, host="", giorni=60, motivo="Macchina isolata dalla rete di produzione, patch non disponibile."):
        return accettazione_rischio.crea(self.record, host=host, motivo=motivo, misure="Rete separata.",
                                         scadenza=timezone.localdate() + timedelta(days=giorni), user=self.admin)

    def test_controlli_su_motivo_scadenza_e_doppioni(self):
        with self.assertRaises(ValueError):
            self._accetta(motivo="troppo corto")
        with self.assertRaises(ValueError):
            self._accetta(giorni=0)
        with self.assertRaises(ValueError):
            self._accetta(giorni=400)
        with self.assertRaises(ValueError):
            self._accetta(host="pc-inesistente")
        self._accetta(host="pc-sla-01")
        with self.assertRaises(ValueError):
            self._accetta(host="PC-SLA-01")
        self.assertEqual(SecurityAccettazioneRischio.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(modulo="security", azione=traccia.RISCHIO_ACCETTATO).exists())

    def test_accettazione_evita_alert_e_chiude_quello_aperto(self):
        self._retrodata(20)
        cve_sla.segnala_scadute()
        evaluate_security_rules()
        self.assertEqual(self._sla_alerts().count(), 2)
        acc = self._accetta(host="pc-sla-01")
        chiuso = self._sla_alerts().filter(status=Status.RESOLVED).get()
        self.assertEqual(chiuso.event.payload["host"], "pc-sla-01")
        self.assertIn(f"#{acc.pk}", chiuso.status_reason)
        scadute = cve_sla.scadute()
        self.assertEqual([(v["host"], v["accettata"]) for v in scadute], [("pc-sla-01", True), ("pc-sla-02", False)])
        # Accettazione su tutti i PC: copre anche il secondo.
        self._accetta()
        self.assertTrue(all(v["accettata"] for v in cve_sla.scadute()))
        self.assertEqual(self._sla_alerts().filter(status=Status.RESOLVED).count(), 2)  # chiusi già da «crea»
        self.assertEqual(cve_sla.segnala_scadute(), (0, 0))

    def test_revoca_fa_tornare_a_contare(self):
        acc = self._accetta()
        self._retrodata(20)
        self.assertEqual(cve_sla.segnala_scadute()[0], 0)
        accettazione_rischio.revoca(acc, user=self.admin, motivo="Patch disponibile.")
        acc.refresh_from_db()
        self.assertEqual(acc.stato, "revocata")
        self.assertEqual(cve_sla.segnala_scadute()[0], 2)
        self.assertTrue(AuditLog.objects.filter(modulo="security", azione=traccia.RISCHIO_REVOCATO, oggetto_id=str(acc.pk)).exists())

    def test_promemoria_e_scadenza_una_volta_sola(self):
        presto = self._accetta(giorni=10)
        tardi = self._accetta(host="pc-sla-02", giorni=200)
        esito = accettazione_rischio.controlla_scadenze()
        self.assertEqual(esito, {"promemoria": 1, "scadute": 0})
        self.assertEqual(accettazione_rischio.controlla_scadenze(), {"promemoria": 0, "scadute": 0})
        evaluate_security_rules()
        alert = SecurityAlert.objects.get(event__event_type=accettazione_rischio.EVENT_ACCETTAZIONE)
        self.assertIn("in scadenza fra 10 giorni", alert.title)
        self.assertEqual(alert.event.payload["accettazione_id"], presto.pk)
        # Scaduta: evento di scadenza e l'esposizione torna a contare.
        SecurityAccettazioneRischio.objects.filter(pk=presto.pk).update(scadenza=timezone.localdate() - timedelta(days=1))
        self._retrodata(20)
        self.assertEqual(accettazione_rischio.controlla_scadenze(), {"promemoria": 0, "scadute": 1})
        evaluate_security_rules()
        self.assertTrue(SecurityAlert.objects.filter(event__event_type=accettazione_rischio.EVENT_ACCETTAZIONE,
                                                     title__startswith="Accettazione del rischio scaduta").exists())
        presto.refresh_from_db()
        self.assertEqual(presto.stato, "scaduta")
        self.assertEqual(tardi.stato, "attiva")
        creati, _ = cve_sla.segnala_scadute()
        self.assertEqual(creati, 1)  # pc-sla-01 conta di nuovo; pc-sla-02 resta coperto
        self.assertEqual(SecurityEventRecord.objects.get(event_type=cve_sla.EVENT_SLA).payload["host"], "pc-sla-01")
        self.assertTrue(AuditLog.objects.filter(modulo="security", azione=traccia.RISCHIO_SCADUTO).exists())
        self.assertTrue(AuditLog.objects.filter(modulo="security", azione=traccia.RISCHIO_IN_SCADENZA).exists())


class PagineTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.lettore = get_user_model().objects.create(username="sla_lettore", is_staff=True)

    def test_scheda_cve_mostra_termine_e_form(self):
        self._retrodata(20, "pc-sla-01")
        r = self.client.get(reverse("security:cve_detail", args=[CVE]))
        self.assertContains(r, "Oltre il termine di 5 giorni")
        self.assertContains(r, "Accetta il rischio")
        self.assertContains(r, "1 PC oltre il termine")

    def test_accetta_dalla_scheda_e_elenco(self):
        url = reverse("security:cve_accetta_rischio", args=[CVE])
        r = self.client.post(url, {"host": "pc-sla-01", "motivo": "Software del banco prova senza aggiornamento disponibile.",
                                   "misure": "Rete isolata", "scadenza": (timezone.localdate() + timedelta(days=90)).isoformat()})
        self.assertRedirects(r, reverse("security:cve_detail", args=[CVE]))
        acc = SecurityAccettazioneRischio.objects.get()
        self.assertEqual((acc.host, acc.approvata_da), ("pc-sla-01", self.admin))
        audit = AuditLog.objects.get(modulo="security", azione=traccia.RISCHIO_ACCETTATO)
        self.assertEqual(audit.oggetto_id, str(acc.pk))
        self.assertEqual(audit.dettaglio["cve"], CVE)
        r = self.client.get(reverse("security:accettazioni_rischio"))
        self.assertContains(r, CVE)
        self.assertContains(r, "Revoca")
        r = self.client.post(reverse("security:accettazione_rischio_revoca", args=[acc.pk]), {"motivo": "Patch installata"})
        self.assertRedirects(r, reverse("security:accettazioni_rischio"))
        acc.refresh_from_db()
        self.assertEqual(acc.stato, "revocata")

    def test_errori_del_form_tornano_come_messaggio(self):
        r = self.client.post(reverse("security:cve_accetta_rischio", args=[CVE]), {"motivo": "corto", "scadenza": ""}, follow=True)
        self.assertContains(r, "almeno 20 caratteri")
        self.assertEqual(SecurityAccettazioneRischio.objects.count(), 0)

    def test_senza_permesso_di_configurazione_niente_accettazione(self):
        from core.models import PermissionDefinition
        from security.permissions import SECURITY_VIEW_PERMISSION_CODE

        PermissionDefinition.objects.get_or_create(code=SECURITY_VIEW_PERMISSION_CODE, defaults={"label": "SOC", "module": "security", "is_active": True})
        self.client.force_login(self.lettore)
        r = self.client.post(reverse("security:cve_accetta_rischio", args=[CVE]),
                             {"motivo": "Motivo abbastanza lungo per passare il controllo.", "scadenza": (timezone.localdate() + timedelta(days=10)).isoformat()})
        self.assertEqual(SecurityAccettazioneRischio.objects.count(), 0)
        self.assertIn(r.status_code, (302, 403))

    def test_cruscotto_vulnerabilita_ha_il_riquadro(self):
        self._retrodata(20)
        r = self.client.get(reverse("security:vulnerabilities"))
        self.assertContains(r, "Tempi di correzione")
        self.assertContains(r, "2 oltre il termine")

    def test_pannello_cve_mostra_il_termine(self):
        self._retrodata(20, "pc-sla-02")
        r = self.client.get(reverse("security:cve_pannello_cve", args=[CVE]))
        self.assertContains(r, "Termine di correzione (ISO 27001 8.8)")
        self.assertContains(r, "Oltre il termine di 5 giorni")
        self.assertContains(r, "Da correggere entro il")


class TracciaSigillataTests(_Base):
    def test_decisioni_automatiche_e_manuali_in_audit(self):
        alert = SecurityAlert.objects.filter(event__event_type=cve_impact.IMPACT_EVENT_TYPE).get()
        close_alert(alert, actor="sla_admin", reason="Verificato a mano.", outcome="resolved", user=self.admin)
        riga = AuditLog.objects.get(modulo="security", azione=traccia.ALERT_STATO, oggetto_id=str(alert.pk))
        self.assertEqual(riga.dettaglio["actor"], "sla_admin")
        alert.refresh_from_db()
        self.assertEqual(riga.dettaglio["new_status"], alert.status)
        altro = SecurityAlert.objects.create(source=alert.source, event=alert.event, title="Sintetico", severity="high", dedup_hash="x" * 64)
        auto_resolution.resolve_alert(altro, "Rientrato.", rule_code="backup_job", evidence_ref="report #1")
        riga = AuditLog.objects.get(modulo="security", azione=traccia.ALERT_AUTO_RISOLTO, oggetto_id=str(altro.pk))
        self.assertEqual((riga.dettaglio["actor"], riga.dettaglio["rule"], riga.dettaglio["evidence"]), ("system", "backup_job", "report #1"))

    def test_esclusione_pc_e_caso(self):
        from security.services import cases, cve_chiusura

        alert = SecurityAlert.objects.filter(event__event_type=cve_impact.IMPACT_EVENT_TYPE).get()
        SoftwareInstallation.objects.filter(host="pc-sla-01").update(still_detected=False)
        cve_impact.recompute(self.record)
        cve_chiusura.escludi_pc(alert, "pc-sla-01", "PC dismesso.", actor="sla_admin")
        riga = AuditLog.objects.get(modulo="security", azione=traccia.CVE_PC_ESCLUSO)
        self.assertEqual((riga.dettaglio["host"], riga.dettaglio["actor"], riga.oggetto_id), ("pc-sla-01", "sla_admin", str(alert.pk)))
        caso = cases.open_manual_case(source=alert.source, title="Caso sintetico", user=self.admin)
        cases.set_case_status(caso, Status.CLOSED, user=self.admin, reason="Fatto.")
        self.assertTrue(AuditLog.objects.filter(modulo="security", azione=traccia.CASO_STATO, oggetto_id=str(caso.pk)).exists())
