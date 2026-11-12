"""Alert aperti per gruppo: una decisione per lo stesso problema, l'AI una volta per gruppo. Dati sintetici; AI simulata."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import SecurityAlert, SecurityAlertProposta, SecurityEventRecord, SecuritySource, Severity, Status
from security.services import ai_proposte, alert_gruppi, soc_settings

CHIEDI = "security.services.cpe_ai._chiedi"
DISPONIBILE = "security.services.cpe_ai.disponibile"
RISOLTO = {"ok": True, "data": {"esito": "risolto", "confidenza": 92, "motivo": "Non si ripete.", "prove": ["P1"]}, "error": "", "model": "demo", "ms": 5}


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="soc_demo", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        self.source = SecuritySource.objects.create(name="Demo", vendor="Demo", source_type="email")
        soc_settings.save({"ai.proposte.soglia": 1, "ai.proposte.attesa_ore": 1, "ai.proposte.confidenza_auto": 50}, None)
        self.n = 0

    def alert(self, payload=None, tipo="watchguard_alert_candidate", severity=Severity.HIGH, title="Endpoint Security: 3 devices blocked su PC-DEMO", ore_fa=5):
        self.n += 1
        adesso = timezone.now() - timedelta(hours=ore_fa)
        evento = SecurityEventRecord.objects.create(source=self.source, event_type=tipo, severity=severity, occurred_at=adesso,
                                                    fingerprint=f"f{self.n}", dedup_hash=f"d{self.n}", payload=payload or {})
        alert = SecurityAlert.objects.create(source=self.source, event=evento, title=title, severity=severity, status=Status.NEW, dedup_hash=f"d{self.n}")
        SecurityAlert.objects.filter(pk=alert.pk).update(created_at=adesso)
        alert.refresh_from_db()
        return alert


class GruppiTests(_Base):
    def test_stesso_pc_un_gruppo_altro_pc_un_altro(self):
        self.alert({"computer": "PC-DEMO-01"})
        self.alert({"computer": "PC-DEMO-01"})
        self.alert({"computer": "PC-DEMO-02"})
        gruppi = alert_gruppi.gruppi_aperti()
        self.assertEqual(sorted(g["n"] for g in gruppi), [1, 2])

    def test_pc_preso_dal_titolo(self):
        self.alert(title="Endpoint Security: 3 devices blocked su PC-DEMO-01")
        self.alert(title="Endpoint Security: 9 devices blocked su PC-DEMO-01")
        self.alert(title="Endpoint Security: 1 devices blocked su PC-DEMO-02")
        self.assertEqual(sorted(g["n"] for g in alert_gruppi.gruppi_aperti()), [1, 2])

    def test_le_cve_stanno_nel_gruppo_del_tipo(self):
        self.alert(tipo="vulnerability_finding", title="Critical exposed vulnerability CVE-2099-0001", severity=Severity.CRITICAL)
        self.alert(tipo="vulnerability_finding", title="Critical exposed vulnerability CVE-2099-0002", severity=Severity.CRITICAL)
        gruppi = alert_gruppi.gruppi_aperti()
        self.assertEqual([(g["n"], g["soggetto"]) for g in gruppi], [(2, "")])

    def test_chiusi_non_contano(self):
        chiuso = self.alert({"computer": "PC-DEMO-01"})
        SecurityAlert.objects.filter(pk=chiuso.pk).update(status=Status.CLOSED)
        self.assertEqual(alert_gruppi.gruppi_aperti(), [])


class ChiusuraTests(_Base):
    def test_chiude_il_gruppo_non_gli_altri_e_non_i_piu_nuovi(self):
        a, b = self.alert({"computer": "PC-DEMO-01"}), self.alert({"computer": "PC-DEMO-01"})
        altro = self.alert({"computer": "PC-DEMO-02"})
        gruppo = next(g for g in alert_gruppi.gruppi_aperti() if g["n"] == 2)
        nuovo = self.alert({"computer": "PC-DEMO-01"})
        r = self.client.post(reverse("security:alert_gruppo_chiudi"), {
            "chiave": gruppo["chiave"], "max_pk": gruppo["max_pk"], "esito": "not_relevant", "motivo": "Blocchi attesi"})
        self.assertEqual(r.status_code, 302)
        for alert, stato in ((a, Status.CLOSED), (b, Status.CLOSED), (altro, Status.NEW), (nuovo, Status.NEW)):
            alert.refresh_from_db()
            self.assertEqual(alert.status, stato)
        self.assertEqual(a.status_reason, "Blocchi attesi")

    def test_chiude_tutto_il_tipo(self):
        self.alert({"computer": "PC-DEMO-01"})
        self.alert({"computer": "PC-DEMO-02"})
        fuori = self.alert({"computer": "PC-DEMO-01"}, tipo="backup_job")
        tipo = alert_gruppi.tipo_di(SecurityAlert.objects.exclude(pk=fuori.pk).first())[0]
        self.client.post(reverse("security:alert_gruppo_chiudi"), {"tipo": tipo, "max_pk": fuori.pk, "esito": "resolved", "motivo": "Rientrato"})
        self.assertEqual(SecurityAlert.objects.filter(status=Status.NEW).count(), 1)
        fuori.refresh_from_db()
        self.assertEqual(fuori.status, Status.NEW)

    def test_senza_motivo_non_chiude(self):
        self.alert({"computer": "PC-DEMO-01"})
        gruppo = alert_gruppi.gruppi_aperti()[0]
        self.client.post(reverse("security:alert_gruppo_chiudi"), {"chiave": gruppo["chiave"], "max_pk": gruppo["max_pk"], "esito": "resolved", "motivo": " "})
        self.assertEqual(SecurityAlert.objects.filter(status=Status.NEW).count(), 1)

    def test_falso_positivo(self):
        a = self.alert({"computer": "PC-DEMO-01"})
        gruppo = alert_gruppi.gruppi_aperti()[0]
        self.client.post(reverse("security:alert_gruppo_chiudi"), {"chiave": gruppo["chiave"], "max_pk": gruppo["max_pk"], "esito": "false_positive", "motivo": "Test"})
        a.refresh_from_db()
        self.assertEqual(a.status, Status.FALSE_POSITIVE)

    def test_negato_senza_accesso_soc(self):
        self.alert({"computer": "PC-DEMO-01"})
        gruppo = alert_gruppi.gruppi_aperti()[0]
        with mock.patch("security.views.can_view_security_center", return_value=False):
            self.client.post(reverse("security:alert_gruppo_chiudi"), {"chiave": gruppo["chiave"], "max_pk": gruppo["max_pk"], "esito": "resolved", "motivo": "x"})
        self.assertEqual(SecurityAlert.objects.filter(status=Status.NEW).count(), 1)

    def test_pagina(self):
        self.alert({"computer": "PC-DEMO-01"})
        self.alert({"computer": "PC-DEMO-01"})
        r = self.client.get(reverse("security:alert_proposte"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "PC-DEMO-01")
        self.assertContains(r, "Chiudi i 2 alert")
        self.assertNotContains(r, "{#")


class AiPerGruppoTests(_Base):
    def test_una_domanda_per_gruppo_sul_piu_recente(self):
        soc_settings.save({"ai.proposte.chiusura_auto": False}, None)
        self.alert({"computer": "PC-DEMO-01"}, ore_fa=9)
        recente = self.alert({"computer": "PC-DEMO-01"}, ore_fa=3)
        self.alert({"computer": "PC-DEMO-02"}, ore_fa=3)
        with mock.patch(DISPONIBILE, return_value=(True, "")), mock.patch(CHIEDI, return_value=RISOLTO) as chiedi:
            esito = ai_proposte.giro(limit=10)
        self.assertEqual(esito["esaminati"], 2)
        self.assertEqual(chiedi.call_count, 2)
        self.assertTrue(SecurityAlertProposta.objects.filter(alert=recente, stato=SecurityAlertProposta.APERTA).exists())
        self.assertIn("Alert uguali ancora aperti", chiedi.call_args_list[0].args[0][-1]["content"])

    def test_proposta_piu_vecchia_del_gruppo_superata(self):
        soc_settings.save({"ai.proposte.chiusura_auto": False}, None)
        vecchio = self.alert({"computer": "PC-DEMO-01"}, ore_fa=9)
        with mock.patch(DISPONIBILE, return_value=(True, "")), mock.patch(CHIEDI, return_value=RISOLTO):
            ai_proposte.giro(limit=10)
            self.assertTrue(SecurityAlertProposta.objects.filter(alert=vecchio, stato=SecurityAlertProposta.APERTA).exists())
            self.alert({"computer": "PC-DEMO-01"}, ore_fa=3)
            ai_proposte.giro(limit=10)
        self.assertEqual(SecurityAlertProposta.objects.filter(stato=SecurityAlertProposta.APERTA).count(), 1)
        self.assertEqual(SecurityAlertProposta.objects.get(alert=vecchio).stato, SecurityAlertProposta.SUPERATA)

    def test_una_conferma_di_gruppo_conta_una_volta(self):
        soc_settings.save({"ai.proposte.chiusura_auto": False}, None)
        self.alert({"computer": "PC-DEMO-01"})
        self.alert({"computer": "PC-DEMO-01"})
        with mock.patch(DISPONIBILE, return_value=(True, "")), mock.patch(CHIEDI, return_value=RISOLTO):
            ai_proposte.giro(limit=10)
        proposta = SecurityAlertProposta.objects.get(stato=SecurityAlertProposta.APERTA)
        gruppo = alert_gruppi.gruppi_aperti()[0]
        alert_gruppi.chiudi(esito="resolved", motivo="Ok", max_pk=gruppo["max_pk"], user=self.user, chiave=gruppo["chiave"])
        self.assertEqual(SecurityAlert.objects.filter(status=Status.CLOSED).count(), 2)
        self.assertEqual(ai_proposte.fiducia(proposta.schema, "resolved")["conferme"], 1)

    def test_chiusura_da_sola_salta_i_critici_del_gruppo(self):
        # Fiducia già guadagnata su questo tipo.
        soc_settings.save({"ai.proposte.soglia": 3}, None)
        for i in range(3):
            vecchio = self.alert({"computer": f"PC-DEMO-9{i}"})
            schema = alert_gruppi.tipo_di(vecchio)[0]
            SecurityAlertProposta.objects.create(alert=vecchio, schema=schema, schema_label="demo", esito="resolved", motivo="x", prove=["P1: x"],
                                                 confidenza=90, stato=SecurityAlertProposta.CONFERMATA, decisa_il=timezone.now())
            SecurityAlert.objects.filter(pk=vecchio.pk).update(status=Status.CLOSED)
        critico = self.alert({"computer": "PC-DEMO-01"}, severity=Severity.CRITICAL, ore_fa=9)
        normale = self.alert({"computer": "PC-DEMO-01"}, ore_fa=8)
        recente = self.alert({"computer": "PC-DEMO-01"}, ore_fa=3)
        with mock.patch(DISPONIBILE, return_value=(True, "")), mock.patch(CHIEDI, return_value=RISOLTO), \
                mock.patch("security.services.learned_suppression.guardrail_reason", return_value=""):
            esito = ai_proposte.giro(limit=10)
        self.assertEqual(esito["chiusi_da_soli"], 1)
        for alert, stato in ((recente, Status.CLOSED), (normale, Status.CLOSED), (critico, Status.NEW)):
            alert.refresh_from_db()
            self.assertEqual(alert.status, stato)
