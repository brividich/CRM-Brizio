"""Alert simili dal pannello laterale e selezione multipla in Segnalazioni (dati sintetici)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserOnboarding
from security.models import SecurityAlert, SecurityAlertActionLog, SecurityEventRecord, SecuritySource, Severity, SourceType, Status
from security.services import alert_simili
from security.services.alert_lifecycle import close_alert
from security.services.cve_sla import EVENT_SLA


class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="simili_user", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Impatti CVE sintetici", vendor="Demo", source_type=SourceType.EMAIL)
        self.n = 0

    def cve_alert(self, cve="CVE-2099-0001", host="PC-DEMO-01", software="Browser Demo", status=Status.NEW, tipo=EVENT_SLA):
        self.n += 1
        payload = {"cve": cve, "host": host, "affected_product": software, "etichetta": "Critica", "classe": "critica",
                   "giorni_termine": 7, "giorni_ritardo": 3, "scadenza": "2099-01-01", "cvss": 9.8, "kev": True}
        event = SecurityEventRecord.objects.create(source=self.source, event_type=tipo, severity=Severity.HIGH,
                                                   fingerprint=f"f{self.n}", dedup_hash=f"d{self.n}", payload=payload)
        return SecurityAlert.objects.create(source=self.source, event=event, severity=Severity.HIGH, status=status, dedup_hash=f"d{self.n}",
                                            title=f"Oltre il termine di correzione: {cve} su {host} ({software}), classe critica, 3 giorni di ritardo")


class SimiliServizioTests(_Base):
    def test_criteri_cve_software_pc_con_aperti_e_chiusi(self):
        a = self.cve_alert()
        self.cve_alert(host="PC-DEMO-02")                        # stessa CVE, altro PC: aperto
        chiuso = self.cve_alert(host="PC-DEMO-03")               # stessa CVE, chiuso con motivo
        close_alert(chiuso, actor="tecnico_demo", reason="Browser aggiornato alla 130", outcome="resolved")
        self.cve_alert(cve="CVE-2099-0002")                      # stesso software e stesso PC, altra CVE
        self.cve_alert(cve="CVE-2099-0003", software="Altro programma", host="PC-DEMO-09")  # non c'entra
        dati = alert_simili.simili(a)
        per = {c["codice"]: c for c in dati["criteri"]}
        self.assertEqual(set(per), {"cve", "software", "pc"})
        self.assertEqual((per["cve"]["n_aperti"], per["cve"]["n_chiusi"]), (1, 1))
        self.assertEqual(per["software"]["n_aperti"], 2)
        self.assertEqual(per["pc"]["n_aperti"], 1)
        ultima = per["cve"]["ultime"][0]
        self.assertEqual((ultima["esito"], ultima["chi"], ultima["motivo"], ultima["host"]), ("Risolto", "tecnico_demo", "Browser aggiornato alla 130", "PC-DEMO-03"))
        self.assertEqual(per["cve"]["per_esito"], [("Risolto", 1)])
        self.assertEqual(dati["contesto"]["software"], "Browser Demo")

    def test_altra_sorgente_o_altro_tipo_di_evento_non_sono_simili(self):
        a = self.cve_alert()
        self.cve_alert(tipo="vulnerability_finding")
        altra = SecuritySource.objects.create(name="Firewall sintetico", vendor="Demo", source_type=SourceType.EMAIL)
        SecurityAlert.objects.create(source=altra, title="Oltre il termine di correzione: CVE-2099-0001 su PC-DEMO-01", severity=Severity.HIGH, status=Status.NEW, dedup_hash="x1")
        self.assertEqual(alert_simili.simili(a)["criteri"], [])

    def test_alert_generico_usa_il_gruppo(self):
        def generico(title, status=Status.NEW):
            self.n += 1
            return SecurityAlert.objects.create(source=self.source, title=title, severity=Severity.HIGH, status=status, dedup_hash=f"g{self.n}")
        a = generico("Endpoint Security: 3 devices blocked su PC-DEMO-01")
        generico("Endpoint Security: 9 devices blocked su PC-DEMO-01")
        generico("Endpoint Security: 1 devices blocked su PC-DEMO-02")
        per = {c["codice"]: c for c in alert_simili.simili(a)["criteri"]}
        self.assertEqual(per["gruppo"]["n_aperti"], 1)
        self.assertEqual(set(per), {"gruppo"})  # il gruppo è già «stesso PC»

    def test_chiudi_simili_rispetta_criterio_e_max_pk(self):
        a = self.cve_alert()
        b = self.cve_alert(host="PC-DEMO-02")
        altra_cve = self.cve_alert(cve="CVE-2099-0002")
        dopo = self.cve_alert(host="PC-DEMO-05")  # arrivato dopo che la persona aveva il pannello davanti
        fatti = alert_simili.chiudi_simili(a, criterio="cve", esito="resolved", motivo="Aggiornato ovunque", user=self.user, max_pk=b.pk)
        self.assertEqual(fatti, 2)
        for alert, atteso in ((a, Status.CLOSED), (b, Status.CLOSED), (altra_cve, Status.NEW), (dopo, Status.NEW)):
            alert.refresh_from_db()
            self.assertEqual(alert.status, atteso, alert.title)
        self.assertEqual(a.status_reason, "Aggiornato ovunque")
        batch = {log.details.get("batch") for log in SecurityAlertActionLog.objects.filter(alert__in=[a, b], action="close")}
        self.assertEqual(len(batch), 1)  # un'azione sola per la soppressione appresa
        with self.assertRaises(ValueError):
            alert_simili.chiudi_simili(a, criterio="boh", esito="resolved", motivo="x", user=self.user)


class SimiliPannelloTests(_Base):
    def test_anteprima_mostra_dettagli_cve_simili_e_come_sono_stati_chiusi(self):
        a = self.cve_alert()
        self.cve_alert(host="PC-DEMO-02")
        chiuso = self.cve_alert(host="PC-DEMO-03")
        close_alert(chiuso, actor="tecnico_demo", reason="Browser aggiornato alla 130", outcome="accepted_risk")
        r = self.client.get(reverse("security:preview", args=["alert", a.pk]))
        self.assertContains(r, "Alert simili")
        self.assertContains(r, "Stessa CVE (CVE-2099-0001)")
        self.assertContains(r, "Browser aggiornato alla 130")
        self.assertContains(r, "Rischio accettato")
        self.assertContains(r, "tecnico_demo")
        self.assertContains(r, "Chiudi insieme")
        self.assertContains(r, "CVSS 9.8")
        self.assertContains(r, "Sfruttata (KEV)")
        self.assertContains(r, "PC-DEMO-01")  # il dispositivo viene dal payload anche senza asset collegato
        self.assertContains(r, reverse("security:cve_detail", args=["CVE-2099-0001"]))

    def test_chiusura_dal_pannello_richiede_motivo_e_rifa_il_pannello(self):
        a = self.cve_alert()
        b = self.cve_alert(host="PC-DEMO-02")
        url = reverse("security:alert_simili_chiudi", args=[a.pk])
        r = self.client.post(url, {"criterio": "cve", "esito": "resolved", "motivo": "", "max_pk": b.pk}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(r, "Scrivi il motivo")
        a.refresh_from_db()
        self.assertEqual(a.status, Status.NEW)
        r = self.client.post(url, {"criterio": "cve", "esito": "resolved", "motivo": "Aggiornato", "max_pk": b.pk}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(r, "2 alert chiusi come «Risolto»")
        self.assertNotContains(r, "Chiudi insieme")  # non più attivo
        for alert in (a, b):
            alert.refresh_from_db()
            self.assertEqual(alert.status, Status.CLOSED)

    def test_chiusura_senza_ajax_torna_a_segnalazioni(self):
        a = self.cve_alert()
        r = self.client.post(reverse("security:alert_simili_chiudi", args=[a.pk]), {"criterio": "cve", "esito": "false_positive", "motivo": "Non è installato", "max_pk": a.pk})
        self.assertRedirects(r, reverse("security:segnalazioni"), fetch_redirect_response=False)
        a.refresh_from_db()
        self.assertEqual(a.status, Status.FALSE_POSITIVE)

    def test_senza_permesso_403(self):
        a = self.cve_alert()
        self.client.logout()
        altro = get_user_model().objects.create(username="nessun_permesso")
        UserOnboarding.objects.create(user=altro, completed=True)
        self.client.force_login(altro)
        r = self.client.post(reverse("security:alert_simili_chiudi", args=[a.pk]), {"criterio": "cve", "esito": "resolved", "motivo": "x"})
        self.assertIn(r.status_code, (302, 403))
        a.refresh_from_db()
        self.assertEqual(a.status, Status.NEW)


class SegnalazioniSelezioneTests(_Base):
    def test_la_lista_ha_le_caselle_per_tipo_e_la_barra(self):
        a = self.cve_alert()
        r = self.client.get(reverse("security:segnalazioni"))
        self.assertContains(r, "data-bulk-kinds")
        self.assertContains(r, f'name="alert_ids" value="{a.pk}"')
        self.assertContains(r, 'data-action-ticket="' + reverse("security:tickets_bulk"))
        self.assertContains(r, 'data-action-incident="' + reverse("security:incidents_bulk"))
        self.assertContains(r, "soc-selbar")
        self.assertContains(r, "Chiudi")

    def test_azione_massiva_dalla_lista_torna_alla_lista(self):
        a, b = self.cve_alert(), self.cve_alert(host="PC-DEMO-02")
        back = reverse("security:segnalazioni") + "?gravita=high"
        r = self.client.post(reverse("security:alerts_bulk"), {"alert_ids": [a.pk, b.pk], "action": "acknowledge", "reason": "", "next": back})
        self.assertRedirects(r, back, fetch_redirect_response=False)
        for alert in (a, b):
            alert.refresh_from_db()
            self.assertEqual(alert.status, Status.ACKNOWLEDGED)
