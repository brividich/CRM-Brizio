"""Audit C1-C2: passaggi di stato degli alert controllati sotto blocco, scala unica di gravità. Dati sintetici."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from security.models import SecurityAlert, SecurityEventRecord, SecuritySource, Severity, Status
from security.services import alert_gruppi
from security.services.alert_lifecycle import (
    TransizioneNonAmmessa,
    acknowledge_alert,
    close_alert,
    reopen_alert,
)
from security.services.gravita import rango
from security.services.notifications import SEVERITY_ORDER
from security.services.posture import ALERT_PENALTY


class PassaggiDiStatoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.source = SecuritySource.objects.create(name="Demo", vendor="Demo", source_type="email")
        evento = SecurityEventRecord.objects.create(
            source=self.source, event_type="demo", severity=Severity.HIGH, occurred_at=timezone.now(),
            fingerprint="f1", dedup_hash="d1", payload={},
        )
        self.alert = SecurityAlert.objects.create(
            source=self.source, event=evento, title="Demo", severity=Severity.HIGH, status=Status.NEW, dedup_hash="d1",
        )

    def test_chiuso_non_torna_in_lavorazione_senza_riapri(self):
        close_alert(self.alert, actor="op1", reason="ok")
        with self.assertRaises(TransizioneNonAmmessa):
            acknowledge_alert(self.alert, actor="op2")
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Status.CLOSED)
        reopen_alert(self.alert, actor="op2", reason="si ripete")
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Status.OPEN)

    def test_secondo_operatore_con_pagina_vecchia_viene_fermato(self):
        # op2 ha in mano l'oggetto letto prima della chiusura di op1.
        copia_vecchia = SecurityAlert.objects.get(pk=self.alert.pk)
        close_alert(self.alert, actor="op1", reason="ok")
        with self.assertRaises(TransizioneNonAmmessa):
            close_alert(copia_vecchia, actor="op2", reason="anche io")
        self.assertEqual(self.alert.action_logs.filter(action="close").count(), 1)

    def test_riapri_su_alert_aperto_rifiutato(self):
        with self.assertRaises(TransizioneNonAmmessa):
            reopen_alert(self.alert, actor="op1")

    def test_pagina_dettaglio_mostra_il_motivo(self):
        user = get_user_model().objects.create_superuser("soc_c1", "c1@example.local", "x")
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)
        close_alert(self.alert, actor="op1", reason="ok")
        r = self.client.post(reverse("security:alert_action", args=[self.alert.pk, "acknowledge"]), follow=True)
        self.assertContains(r, "Riapri")
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Status.CLOSED)


class ScalaGravitaTests(TestCase):
    def test_attenzione_sopra_media_ovunque(self):
        self.assertGreater(rango(Severity.WARNING), rango(Severity.MEDIUM))
        self.assertGreater(alert_gruppi.RANGO[Severity.WARNING], alert_gruppi.RANGO[Severity.MEDIUM])
        self.assertGreater(SEVERITY_ORDER[Severity.WARNING], SEVERITY_ORDER[Severity.MEDIUM])
        self.assertGreater(ALERT_PENALTY[Severity.WARNING], ALERT_PENALTY[Severity.MEDIUM])

    def test_ordine_completo(self):
        ordine = sorted([Severity.LOW, Severity.CRITICAL, Severity.MEDIUM, Severity.INFO, Severity.HIGH, Severity.WARNING], key=rango)
        self.assertEqual(ordine, [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.WARNING, Severity.HIGH, Severity.CRITICAL])
