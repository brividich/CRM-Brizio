"""Soppressioni in scadenza: promemoria una volta per scadenza, alert, soglia unica con la pagina. Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, UserOnboarding
from security.models import SecurityAlert, SecurityAlertSuppressionRule, SecurityEventRecord, SecuritySource, SourceType
from security.services import soc_settings, soppressioni_scadenza, traccia
from security.services.rule_engine import evaluate_security_rules


class SoppressioniScadenzaTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Fonte soppressioni", vendor="Demo", source_type=SourceType.EMAIL)
        now = timezone.now()
        self.presto = self._regola("Regola in scadenza", now + timedelta(days=5))
        self.tardi = self._regola("Regola lontana", now + timedelta(days=60))
        self.senza = self._regola("Regola senza scadenza", None)

    def _regola(self, nome, scade):
        return SecurityAlertSuppressionRule.objects.create(
            name=nome, source=self.source, event_type="tipo_sintetico", reason="Motivo sintetico", expires_at=scade,
        )

    def test_promemoria_una_volta_e_alert(self):
        self.assertEqual(soppressioni_scadenza.controlla_scadenze(), 1)
        self.assertEqual(soppressioni_scadenza.controlla_scadenze(), 0)  # niente doppioni
        self.presto.refresh_from_db()
        self.assertIsNotNone(self.presto.promemoria_il)
        evaluate_security_rules()
        alert = SecurityAlert.objects.get(event__event_type=soppressioni_scadenza.EVENT_IN_SCADENZA)
        self.assertIn("Soppressione manuale in scadenza fra 5 giorni: Regola in scadenza", alert.title)
        self.assertTrue(AuditLog.objects.filter(modulo="security", azione=traccia.SOPPRESSIONE_IN_SCADENZA).exists())

    def test_scadenza_prolungata_riparte(self):
        soppressioni_scadenza.controlla_scadenze()
        # Prolungata di 3 mesi e poi di nuovo vicina alla scadenza: promemoria nuovo.
        SecurityAlertSuppressionRule.objects.filter(pk=self.presto.pk).update(
            promemoria_il=timezone.now() - timedelta(days=90), expires_at=timezone.now() + timedelta(days=3))
        self.assertEqual(soppressioni_scadenza.controlla_scadenze(), 1)
        self.assertEqual(SecurityEventRecord.objects.filter(event_type=soppressioni_scadenza.EVENT_IN_SCADENZA).count(), 2)

    def test_soglia_e_interruttore(self):
        soc_settings.save({"soppressione.scadenza.promemoria_giorni": 90, "soppressione.scadenza.alert": False}, None)
        self.assertEqual(soppressioni_scadenza.controlla_scadenze(), 2)
        evaluate_security_rules()
        self.assertFalse(SecurityAlert.objects.filter(event__event_type=soppressioni_scadenza.EVENT_IN_SCADENZA).exists())
        self.assertEqual(SecurityEventRecord.objects.filter(event_type=soppressioni_scadenza.EVENT_IN_SCADENZA,
                                                            decision_trace__decision="kpi_only").count(), 2)

    def test_revocata_o_scaduta_niente_promemoria(self):
        SecurityAlertSuppressionRule.objects.filter(pk=self.presto.pk).update(is_active=False)
        self.assertEqual(soppressioni_scadenza.controlla_scadenze(), 0)

    def test_ciclo_del_soc(self):
        from security.tasks import _termini_correzione_cve

        self.assertEqual(_termini_correzione_cve()["soppressioni_in_scadenza"], 1)

    def test_pagina_usa_la_stessa_soglia(self):
        admin = get_user_model().objects.create(username="sopp_admin", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=admin, completed=True)
        self.client.force_login(admin)
        url = reverse("security:suppressions")
        pagina = self.client.get(url, {"stato": "in-scadenza", "tipo": "tutte"})
        self.assertContains(pagina, "Regola in scadenza")
        self.assertNotContains(pagina, "Regola lontana")
        self.assertContains(pagina, "in scadenza entro 14 giorni")
        soc_settings.save({"soppressione.scadenza.promemoria_giorni": 90}, None)
        pagina = self.client.get(url, {"stato": "in-scadenza", "tipo": "tutte"})
        self.assertContains(pagina, "Regola lontana")
        self.assertContains(pagina, "in scadenza entro 90 giorni")
