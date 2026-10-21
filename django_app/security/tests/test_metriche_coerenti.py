"""Catalogo delle metriche: ogni numero mostrato e' uguale alle righe dell'elenco a cui porta (dati sintetici)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from security.models import BackupJobRecord, SecurityAlert, SecurityRemediationTicket, SecuritySource, Severity, SourceType, Status
from security.services import incidents as inc_svc
from security.services import metriche


class MetricheCoerentiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="met_user", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)
        src = SecuritySource.objects.create(name="Fonte sintetica", vendor="Demo", source_type=SourceType.EMAIL)
        for i, (sev, st) in enumerate([(Severity.CRITICAL, Status.OPEN), (Severity.HIGH, Status.NEW), (Severity.LOW, Status.OPEN), (Severity.CRITICAL, Status.CLOSED)]):
            SecurityAlert.objects.create(source=src, title=f"Alert {i}", severity=sev, status=st, dedup_hash=f"m{i}")
        SecurityRemediationTicket.objects.create(source=src, title="Ticket alto", severity=Severity.HIGH, status=Status.OPEN, dedup_hash="mt1")
        SecurityRemediationTicket.objects.create(source=src, title="Ticket medio", severity=Severity.MEDIUM, status=Status.OPEN, dedup_hash="mt2")
        # incidente significativo con la pre-notifica (24 h) gia' scaduta: urgente anche se di gravita' media
        inc_svc.create_incident(self.user, title="Incidente sintetico", detected_at=timezone.now() - timedelta(hours=30), is_significant=True)
        now = timezone.now()
        for n, (device, status, days) in enumerate([("PC-OK", "completed", 0), ("PC-FALLITO", "failed", 0), ("PC-VECCHIO", "completed", 6)]):
            BackupJobRecord.objects.create(source=src, job_name="Job sintetico", status=status, completed_at=now - timedelta(days=days),
                                           payload={"device_name": device}, dedup_hash=f"mb{n}")

    def test_urgenti_uguale_alle_righe_di_segnalazioni(self):
        m = metriche.segnalazioni_urgenti()
        self.assertEqual(m.value, 4)  # 2 alert critici/alti + 1 ticket alto + 1 incidente con scadenza
        page = self.client.get(m.url)
        self.assertEqual(page.context["righe_totali"], m.value)
        self.assertEqual(page.context["n_urgenti"], m.value)
        # i chip per tipo, con il filtro acceso, contano le stesse righe
        chips = {c["value"]: c["count"] for c in page.context["chips_tipo"]}
        self.assertEqual(chips[""], m.value)
        for tipo in ("alert", "ticket", "incident"):
            self.assertEqual(chips[tipo], self.client.get(m.url + "&tipo=" + tipo).context["righe_totali"], tipo)

    def test_alert_urgenti_uguale_alla_coda_alert(self):
        m = metriche.alert_urgenti()
        self.assertEqual(m.value, 2)
        self.assertEqual(self.client.get(m.url).context["total"], m.value)

    def test_scadenze_legali_uguale_agli_incidenti_filtrati(self):
        m = metriche.scadenze_legali()
        self.assertEqual(m.value, 1)
        self.assertEqual(self.client.get(m.url).context["righe_totali"], m.value)

    def test_pc_backup_ko_uguale_alla_pagina_backup(self):
        m = metriche.pc_backup_ko()
        self.assertEqual(m.value, 2)  # un fallito, uno senza riuscito oltre la soglia
        page = self.client.get(m.url)
        self.assertEqual(len(page.context["devices"]), m.value)
        self.assertEqual({d["name"] for d in page.context["devices"]}, {"PC-FALLITO", "PC-VECCHIO"})

    def test_barra_menu_e_panoramica_dicono_lo_stesso_numero(self):
        urgenti = metriche.segnalazioni_urgenti().value
        html = self.client.get(reverse("security:dashboard")).content.decode()
        live = html.split('class="soc-live"', 1)[1]
        self.assertIn(f"<strong>{urgenti}</strong><span>segnalazioni urgenti</span>", live)
        menu = html.split('<nav class="soc-tabs"', 1)[1].split("</nav>", 1)[0]
        self.assertIn(f'tone-critical" title="{urgenti} segnalazioni urgenti">{urgenti}</span>', menu)
        hero = html.split('id="ov-hero"', 1)[1].split("</section>", 1)[0]
        self.assertIn(f"<strong>{urgenti}</strong> segnalazioni urgenti", hero)
        self.assertIn(f"<strong>{metriche.segnalazioni_aperte().value}</strong> segnalazioni aperte", hero)

    def test_panoramica_backup_per_pc_e_link_esatti(self):
        html = self.client.get(reverse("security:dashboard")).content.decode()
        self.assertIn("Backup ko: PC-FALLITO", html)
        self.assertIn("Backup ko: PC-VECCHIO", html)
        self.assertNotIn("Backup ko: PC-OK", html)

    def test_copertura_cpe_senza_inventario(self):
        m = metriche.copertura_cpe()
        self.assertEqual((m.value, m.extra["totale"]), (0, 0))
