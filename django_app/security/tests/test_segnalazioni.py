"""Segnalazioni: alert, ticket e incidenti in un elenco solo, dal piu' urgente (dati sintetici)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from security.models import SecurityAlert, SecurityRemediationTicket, SecuritySource, Severity, SourceType, Status
from security.services import incidents as inc_svc
from security.services import segnalazioni as svc


class SegnalazioniTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="seg_user", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Fonte sintetica", vendor="Demo", source_type=SourceType.EMAIL)
        now = timezone.now()
        self.alert_basso = SecurityAlert.objects.create(source=self.source, title="Alert basso", severity=Severity.LOW, status=Status.OPEN, dedup_hash="a1")
        self.alert_critico = SecurityAlert.objects.create(source=self.source, title="Alert critico", severity=Severity.CRITICAL, status=Status.OPEN, dedup_hash="a2")
        self.alert_chiuso = SecurityAlert.objects.create(source=self.source, title="Alert chiuso", severity=Severity.CRITICAL, status=Status.CLOSED, dedup_hash="a3")
        self.ticket = SecurityRemediationTicket.objects.create(source=self.source, title="Ticket alto", severity=Severity.HIGH, status=Status.OPEN,
                                                               dedup_hash="t1", affected_product="Prodotto sintetico")
        self.incidente = inc_svc.create_incident(self.user, title="Incidente sintetico", detected_at=now - timedelta(hours=30), is_significant=True)

    def test_unico_elenco_con_i_tre_tipi_dal_piu_urgente(self):
        titoli = [r["title"] for r in svc.elenco()]
        self.assertEqual(len(titoli), 4)  # il chiuso non c'e'
        self.assertNotIn("Alert chiuso", titoli)
        # la notifica in scadenza/scaduta passa davanti a tutto, poi la gravita'
        self.assertIn("Incidente sintetico", titoli[0])
        self.assertEqual(titoli[1], "Alert critico")
        self.assertEqual(titoli[-1], "Alert basso")

    def test_filtri_tipo_stato_gravita_e_testo(self):
        self.assertEqual({r["kind"] for r in svc.elenco(tipo="alert")}, {"alert"})
        self.assertEqual([r["title"] for r in svc.elenco(tipo="alert", stato="chiuse")], ["Alert chiuso"])
        self.assertEqual(len(svc.elenco(stato="tutte", tipo="alert")), 3)
        self.assertEqual([r["title"] for r in svc.elenco(severity="critical")], ["Alert critico"])
        self.assertEqual(len(svc.elenco(q="sintetico", tipo="ticket")), 1)
        # valori non validi tornano ai predefiniti invece di rompere
        self.assertEqual(len(svc.elenco(tipo="xx", stato="yy", severity="zz")), 4)

    def test_conteggi_delle_aperte(self):
        self.assertEqual(svc.conteggi(), {"alert": 2, "ticket": 1, "incident": 1})

    def test_la_pagina_mostra_elenco_chip_e_anteprima(self):
        page = self.client.get(reverse("security:segnalazioni"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Alert critico")
        self.assertContains(page, "Ticket alto")
        self.assertContains(page, "Incidente sintetico")
        self.assertNotContains(page, "Alert chiuso")
        self.assertContains(page, reverse("security:preview", args=["alert", self.alert_critico.pk]))
        self.assertContains(page, '<nav class="soc-subnav"')

    def test_filtri_via_url_e_pagina_vuota(self):
        self.assertContains(self.client.get(reverse("security:segnalazioni") + "?tipo=ticket"), "Ticket alto")
        self.assertNotContains(self.client.get(reverse("security:segnalazioni") + "?tipo=ticket"), "Alert critico")
        self.assertContains(self.client.get(reverse("security:segnalazioni") + "?q=nonesiste"), "Nessuna segnalazione corrisponde ai filtri")

    def test_senza_permesso_non_si_entra(self):
        self.client.logout()
        outsider = get_user_model().objects.create(username="seg_out")
        UserOnboarding.objects.create(user=outsider, completed=True)
        self.client.force_login(outsider)
        self.assertNotEqual(self.client.get(reverse("security:segnalazioni")).status_code, 200)

    def test_menu_ha_la_scheda_tutte(self):
        page = self.client.get(reverse("security:alerts_list")).content.decode()
        sub = page.split('<nav class="soc-subnav"', 1)[1].split("</nav>", 1)[0]
        self.assertIn(">Tutte</a>", sub)
        self.assertIn(reverse("security:segnalazioni"), sub)
