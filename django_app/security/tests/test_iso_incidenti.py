"""ISO 27001 5.24-5.28 e 8.13: tempi di presa in carico, lezioni apprese, integrità delle evidenze,
ruoli e contatti, prove di ripristino, riepilogo per il cruscotto."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupRestoreTest,
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityCorrectiveAction,
    SecurityEventRecord,
    SecurityEvidenceContainer,
    SecurityEvidenceCustody,
    SecurityIncident,
    SecurityIncidentLog,
    SecurityNotificationChannel,
    SecurityNotificationLog,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.services import evidenze, iso_incidenti, proactive_alerts, riesame, ripristini, triage_tempi
from security.services import incidents as inc_svc
from security.services.alert_lifecycle import acknowledge_alert, close_alert
from security.services.configuration import set_setting
from security.services.evidence_builder import build_evidence_container


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="soc@example.test")
class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_iso_user", is_staff=True, is_superuser=True, email="iso@example.test")
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Fonte sintetica ISO", vendor="Demo", source_type=SourceType.EMAIL)
        self.channel = SecurityNotificationChannel.objects.create(name="SOC mail ISO", channel_type="email", recipients="soc@example.test")
        self.n = 0

    def alert(self, severity=Severity.HIGH, hours_ago=0, **fields):
        self.n += 1
        alert = SecurityAlert.objects.create(source=self.source, title=f"Alert sintetico {self.n}", severity=severity, dedup_hash=f"h{self.n}", **fields)
        if hours_ago:
            SecurityAlert.objects.filter(pk=alert.pk).update(created_at=timezone.now() - timedelta(hours=hours_ago))
            alert.refresh_from_db()
        SecurityAlertActionLog.objects.create(alert=alert, action="alert_created", actor="system")
        return alert

    def incident(self, **fields):
        fields.setdefault("title", "Phishing sintetico con credenziali rubate")
        return inc_svc.create_incident(self.user, **fields)

    def event(self):
        self.n += 1
        return SecurityEventRecord.objects.create(source=self.source, event_type="demo", severity=Severity.HIGH,
                                                  fingerprint=f"f{self.n}", dedup_hash=f"f{self.n}", payload={"n": self.n})


class TriageTests(_Base):
    def test_defaults_per_gravita(self):
        self.assertEqual(triage_tempi.target_ore(), {"critical": 1, "high": 4, "medium": 24, "low": 72})
        self.assertEqual(triage_tempi.target_per_alert(self.alert(Severity.WARNING)), 24)
        self.assertEqual(triage_tempi.target_per_alert(self.alert(Severity.INFO)), 72)

    def test_presa_in_carico_in_tempo_e_in_ritardo(self):
        presto = self.alert(Severity.HIGH, hours_ago=6)
        SecurityAlertActionLog.objects.filter(alert=presto).update(created_at=presto.created_at)
        acknowledge_alert(presto, actor="mario")
        SecurityAlertActionLog.objects.filter(alert=presto, action="acknowledge").update(created_at=presto.created_at + timedelta(hours=2))
        s = triage_tempi.stato(presto)
        self.assertFalse(s["in_ritardo"])
        self.assertEqual(s["ore_presa_in_carico"], 2.0)

        tardi = self.alert(Severity.CRITICAL, hours_ago=6)
        close_alert(tardi, actor="mario", reason="rientrato")
        s = triage_tempi.stato(tardi)
        self.assertTrue(s["in_ritardo"])
        self.assertEqual(s["target_ore"], 1)
        self.assertIsNotNone(s["ore_risoluzione"])

    def test_azioni_del_motore_non_contano(self):
        alert = self.alert(Severity.CRITICAL, hours_ago=3)
        SecurityAlertActionLog.objects.create(alert=alert, action="auto_resolve_check", actor="system")
        s = triage_tempi.stato(alert)
        self.assertTrue(s["non_presa"])
        self.assertTrue(s["in_ritardo"])
        self.assertEqual([a.pk for a in triage_tempi.alert_oltre_tempo()], [alert.pk])
        self.alert(Severity.LOW, hours_ago=3)  # bassa: 72 h, non è in ritardo
        self.assertEqual(len(triage_tempi.alert_oltre_tempo()), 1)

    def test_riepilogo_e_mediana(self):
        a = self.alert(Severity.HIGH, hours_ago=10)
        acknowledge_alert(a, actor="mario")
        SecurityAlertActionLog.objects.filter(alert=a, action="acknowledge").update(created_at=a.created_at + timedelta(hours=1))
        b = self.alert(Severity.HIGH, hours_ago=10)
        acknowledge_alert(b, actor="mario")
        SecurityAlertActionLog.objects.filter(alert=b, action="acknowledge").update(created_at=b.created_at + timedelta(hours=5))
        self.alert(Severity.LOW, hours_ago=1)
        oggi = timezone.localdate()
        r = triage_tempi.riepilogo(oggi - timedelta(days=1), oggi)
        self.assertEqual((r["presi_in_tempo"], r["presi_in_ritardo"], r["non_presi"]), (1, 1, 1))
        self.assertEqual(r["mediana_ore"], 3.0)

    def test_elenco_e_scheda_mostrano_il_ritardo(self):
        alert = self.alert(Severity.CRITICAL, hours_ago=3)
        self.assertContains(self.client.get(reverse("security:alerts_list")), "oltre il tempo di presa in carico")
        self.assertContains(self.client.get(reverse("security:alert_detail", args=[alert.pk])), "oltre il tempo di presa in carico")

    def test_escalation_una_volta_sola(self):
        set_setting("iso.triage.attivo", True)
        set_setting("iso.triage.canali", [self.channel.pk])
        self.alert(Severity.CRITICAL, hours_ago=3)
        self.assertEqual(proactive_alerts.check_triage(), 1)
        self.assertEqual(proactive_alerts.check_triage(), 0)
        self.assertEqual(SecurityNotificationLog.objects.filter(event_kind=proactive_alerts.EVENT_TRIAGE).count(), 1)


class RiesameTests(_Base):
    def test_concluso_senza_riesame_non_bloccato_ma_segnalato(self):
        incident = self.incident(status=SecurityIncident.STATUS_CLOSED)
        self.assertTrue(riesame.riesame_mancante(incident))
        self.assertContains(self.client.get(reverse("security:incident_detail", args=[incident.pk])), "Riesame mancante")
        self.assertContains(self.client.get(reverse("security:incidents") + "?status=closed"), "Riesame mancante")
        # Il modulo di modifica chiude comunque: solo un avviso.
        response = self.client.post(reverse("security:incident_edit", args=[incident.pk]), {
            "title": incident.title, "category": "phishing", "severity": "high", "status": "closed",
            "detected_at": timezone.localtime(incident.detected_at).strftime("%Y-%m-%dT%H:%M"),
        }, follow=True)
        self.assertContains(response, "senza «Lezioni apprese»")
        incident.refresh_from_db()
        self.assertEqual(incident.status, SecurityIncident.STATUS_CLOSED)

    def test_salva_riesame_e_azioni(self):
        incident = self.incident(status=SecurityIncident.STATUS_RESOLVED)
        self.client.post(reverse("security:incident_riesame", args=[incident.pk]),
                         {"causa": "Password riusata", "cosa_ha_funzionato": "Blocco rapido", "cosa_migliorare": "MFA"})
        incident.refresh_from_db()
        self.assertFalse(riesame.riesame_mancante(incident))
        self.assertIn("Causa: Password riusata", incident.lessons_learned)
        self.assertTrue(SecurityIncidentLog.objects.filter(incident=incident, action="riesame").exists())
        with self.assertRaises(ValueError):
            riesame.salva_riesame(incident, self.user, causa="  ")

        ieri = timezone.localdate() - timedelta(days=1)
        self.client.post(reverse("security:incident_azione", args=[incident.pk]),
                         {"titolo": "MFA su VPN", "responsabile": "IT", "scadenza": ieri.isoformat()})
        azione = SecurityCorrectiveAction.objects.get(incident=incident)
        self.assertTrue(azione.scaduta)
        self.assertEqual(len(riesame.azioni_scadute()), 1)
        self.assertContains(self.client.get(reverse("security:incident_detail", args=[incident.pk])), "In ritardo")
        self.client.post(reverse("security:incident_azione_fatta", args=[incident.pk, azione.pk]))
        azione.refresh_from_db()
        self.assertIsNotNone(azione.fatta_il)
        self.assertEqual(riesame.azioni_scadute(), [])

    def test_promemoria_dopo_n_giorni(self):
        set_setting("iso.triage.attivo", True)
        set_setting("iso.triage.canali", [self.channel.pk])
        incident = self.incident(status=SecurityIncident.STATUS_CLOSED, resolved_at=timezone.now() - timedelta(days=10))
        self.incident(status=SecurityIncident.STATUS_CLOSED, resolved_at=timezone.now() - timedelta(days=2))
        self.assertEqual([i.pk for i in riesame.incidenti_senza_riesame(solo_da_avvisare=True)], [incident.pk])
        self.assertEqual(proactive_alerts.check_riesami(), 1)
        self.assertEqual(proactive_alerts.check_riesami(), 0)
        riesame.aggiungi_azione(incident, self.user, titolo="Formazione", scadenza=timezone.localdate() - timedelta(days=1))
        self.assertEqual(proactive_alerts.check_riesami(), 1)

    def test_pdf_con_riesame_e_ruoli(self):
        incident = self.incident(status=SecurityIncident.STATUS_CLOSED)
        riesame.salva_riesame(incident, self.user, causa="Patch mancante")
        pdf = self.client.get(reverse("security:incident_pdf", args=[incident.pk]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))


class EvidenzeTests(_Base):
    def test_sigillo_alla_nascita_e_verifica(self):
        container = build_evidence_container(self.source, "Prova", event=self.event())
        container.refresh_from_db()
        self.assertEqual(len(container.sha256), 64)
        self.assertEqual(list(container.custodia.order_by("id").values_list("azione", flat=True)), ["created", "sealed"])
        self.assertEqual(evidenze.verifica(container, "mario")["esito"], evidenze.VERIFIED)
        item = container.items.first()
        item.content = {"manomesso": True}
        item.save(update_fields=["content"])
        self.assertEqual(evidenze.verifica(container, "mario")["esito"], evidenze.ALTERED)
        container.refresh_from_db()
        self.assertEqual(container.integrita, evidenze.ALTERED)
        self.assertEqual(evidenze.riepilogo(), {"totali": 1, "verificate": 0, "alterate": 1})

    def test_sigilla_mancanti_dal_ciclo(self):
        container = SecurityEvidenceContainer.objects.create(source=self.source, title="Vecchia")
        self.assertEqual(iso_incidenti.ciclo(), {"evidenze_sigillate": 1})
        container.refresh_from_db()
        self.assertTrue(container.sha256)
        self.assertEqual(evidenze.sigilla_mancanti(), 0)

    def test_custodia_visione_verifica_esportazione(self):
        alert = self.alert()
        container = build_evidence_container(self.source, "Prova", alert=alert, event=self.event())
        url = reverse("security:alert_detail", args=[alert.pk])
        self.client.get(url)
        self.client.get(url)
        self.assertEqual(SecurityEvidenceCustody.objects.filter(container=container, azione="viewed").count(), 1)
        response = self.client.post(reverse("security:evidence_verify", args=[container.pk]), follow=True)
        self.assertContains(response, "integra")
        export = self.client.get(reverse("security:evidence_export", args=[container.pk]))
        self.assertEqual(export.status_code, 200)
        self.assertIn("sha256", export.json())
        self.assertEqual(SecurityEvidenceCustody.objects.filter(container=container, azione="exported").count(), 1)
        from core.models import AuditLog

        self.assertTrue(AuditLog.objects.filter(azione__in=["evidenza_verifica", "evidenza_esporta"]).count() >= 2)


class RuoliTests(_Base):
    def test_mancanti_e_completi(self):
        r = iso_incidenti.ruoli()
        self.assertFalse(r["completi"])
        self.assertEqual(len(r["mancanti"]), 4)
        incident = self.incident()
        self.assertContains(self.client.get(reverse("security:incident_detail", args=[incident.pk])), "Da completare")
        for key, _label in iso_incidenti.RUOLI:
            set_setting(key, "Mario Rossi 0123 456789")
        self.assertTrue(iso_incidenti.ruoli()["completi"])
        self.assertContains(self.client.get(reverse("security:soc_settings")), "Gestione degli incidenti (ISO 27001 5.24-5.28)")


class RipristiniTests(_Base):
    def test_stato_e_promemoria(self):
        self.assertTrue(ripristini.stato()["in_ritardo"])
        set_setting("iso.ripristini.attivo", True)
        set_setting("iso.ripristini.canali", [self.channel.pk])
        self.assertEqual(proactive_alerts.check_ripristini(), 1)
        self.assertEqual(proactive_alerts.check_ripristini(), 0)
        ripristini.registra(self.user, data=timezone.localdate() - timedelta(days=10), sistema="SRV-FILE", cosa_ripristinato="cartella Uffici")
        s = ripristini.stato()
        self.assertFalse(s["in_ritardo"])
        self.assertEqual(s["prossima_entro"], timezone.localdate() + timedelta(days=80))
        ripristini.registra(self.user, data=timezone.localdate() - timedelta(days=100), sistema="SRV-OLD", cosa_ripristinato="x")
        self.assertFalse(ripristini.stato()["in_ritardo"])  # conta l'ultima riuscita, non la più vecchia

    def test_prova_fallita_apre_alert(self):
        prova = ripristini.registra(self.user, data=timezone.localdate(), sistema="SRV-SQL", job="Job SQL", cosa_ripristinato="database", esito="ko")
        self.assertIsNotNone(prova.alert)
        self.assertEqual(prova.alert.severity, Severity.HIGH)
        self.assertIn("SRV-SQL", prova.alert.title)
        self.assertEqual(prova.alert.status, Status.NEW)

    def test_pagina_registro(self):
        url = reverse("security:backup_ripristini")
        self.assertContains(self.client.get(url), "Prove di ripristino")
        response = self.client.post(url, {
            "data": timezone.localdate().isoformat(), "sistema": "NAS-01", "cosa_ripristinato": "share Progetti", "esito": "ok",
            "durata_minuti": "15", "eseguito_da": "Mario", "note": "", "allegato": SimpleUploadedFile("verbale.txt", b"ok"),
        }, follow=True)
        self.assertContains(response, "Prova di ripristino registrata.")
        prova = BackupRestoreTest.objects.get(sistema="NAS-01")
        self.assertTrue(prova.allegato)
        self.assertEqual(self.client.get(reverse("security:backup_ripristino_allegato", args=[prova.pk])).status_code, 200)
        self.assertContains(self.client.get(reverse("security:backup")), "Prove di ripristino")


class RiepilogoTests(_Base):
    def test_chiavi_e_valori(self):
        oggi = timezone.localdate()
        chiuso = self.incident(status=SecurityIncident.STATUS_CLOSED, resolved_at=timezone.now())
        con = self.incident(title="Altro", status=SecurityIncident.STATUS_CLOSED, resolved_at=timezone.now())
        riesame.salva_riesame(con, self.user, causa="x")
        self.incident(title="Aperto")
        build_evidence_container(self.source, "Prova", event=self.event())
        ripristini.registra(self.user, data=oggi, sistema="SRV", cosa_ripristinato="y", esito="ko")
        r = iso_incidenti.riepilogo(oggi - timedelta(days=30), oggi)
        self.assertEqual(set(r), {"triage", "incidenti", "evidenze", "ruoli", "ripristini"})
        self.assertEqual(set(r["triage"]), {"target", "presi_in_tempo", "presi_in_ritardo", "non_presi", "mediana_ore"})
        self.assertEqual(r["incidenti"]["aperti"], 1)
        self.assertEqual(r["incidenti"]["chiusi"], 2)
        self.assertEqual(r["incidenti"]["chiusi_con_riesame"], 1)
        self.assertEqual([x["id"] for x in r["incidenti"]["senza_riesame"]], [chiuso.pk])
        self.assertEqual(set(r["incidenti"]["senza_riesame"][0]), {"id", "titolo", "chiuso_il"})
        self.assertEqual(r["evidenze"]["totali"], 2)  # contenitore della prova + quello dell'alert di ripristino fallito
        self.assertFalse(r["ruoli"]["completi"])
        self.assertEqual(r["ripristini"], {"ultimo_test": oggi, "esito_ultimo": "ko", "in_ritardo": True, "test_periodo": 1, "falliti_periodo": 1})
        self.assertIsInstance(r["ripristini"]["ultimo_test"], date)
