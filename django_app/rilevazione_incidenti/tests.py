from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import PlantLayout, PlantLayoutArea
from core.models import UserOnboarding

from .models import (
    RilevazioneIncidente,
    SicurezzaImpostazioni,
    TipoEventoSicurezza,
    normalize_tipo_evento,
)
from .services import get_safety_kpis


def _aware_datetime(year: int, month: int, day: int, hour: int = 9):
    return timezone.make_aware(
        datetime(year, month, day, hour, 0),
        timezone.get_current_timezone(),
    )


class TipoEventoSicurezzaTests(TestCase):
    def test_normalize_tipo_evento_maps_legacy_labels(self):
        self.assertEqual(normalize_tipo_evento("Accident"), TipoEventoSicurezza.INCIDENTE)
        self.assertEqual(normalize_tipo_evento("Near Miss"), TipoEventoSicurezza.NEAR_MISS)
        self.assertEqual(normalize_tipo_evento("Unsafe Act"), TipoEventoSicurezza.UNSAFE_CONDITION)

    def test_model_save_infers_tipo_evento_from_tipologia(self):
        evento = RilevazioneIncidente.objects.create(
            nominativo="Mario Rossi",
            tipologia_scheda="Near Miss",
            reparto="CNC",
            data_segnalazione=_aware_datetime(2026, 5, 1),
        )

        self.assertEqual(evento.tipo_evento, TipoEventoSicurezza.NEAR_MISS)


class ImportaRilevazioniCsvTests(TestCase):
    """Il comando di import deve derivare `tipo_evento` (KPI) dalla tipologia legacy.

    Protegge da regressioni: il comando usa `inst.save()`, che eredita l'inferenza
    del modello. Se un domani passasse a bulk_create/insert, `tipo_evento` resterebbe
    al default e questo test fallirebbe.
    """

    def _run(self, righe, extra_args=()):
        import csv
        import tempfile
        from pathlib import Path

        from django.core.management import call_command

        headers = ["Nominativo", "Tipologia scheda", "Data segnalazione", "ID"]
        fd, path = tempfile.mkstemp(suffix=".csv")
        with __import__("os").fdopen(fd, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers)
            writer.writeheader()
            for r in righe:
                writer.writerow(r)
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        call_command("importa_rilevazioni_csv", path, *extra_args)

    def test_import_deriva_tipo_evento_da_tipologia(self):
        self._run([
            {"Nominativo": "Mario Rossi", "Tipologia scheda": "Near Miss",
             "Data segnalazione": "01/05/2026 09:00", "ID": "101"},
            {"Nominativo": "Luigi Bianchi", "Tipologia scheda": "Accident",
             "Data segnalazione": "02/05/2026 10:00", "ID": "102"},
            {"Nominativo": "Anna Verdi", "Tipologia scheda": "Unsafe Act",
             "Data segnalazione": "03/05/2026 11:00", "ID": "103"},
        ])
        by_id = {r.id_originale: r for r in RilevazioneIncidente.objects.all()}
        self.assertEqual(by_id[101].tipo_evento, TipoEventoSicurezza.NEAR_MISS)
        self.assertEqual(by_id[102].tipo_evento, TipoEventoSicurezza.INCIDENTE)
        self.assertEqual(by_id[103].tipo_evento, TipoEventoSicurezza.UNSAFE_CONDITION)

    def test_skip_existing_evita_duplicati(self):
        riga = [{"Nominativo": "Mario Rossi", "Tipologia scheda": "Near Miss",
                 "Data segnalazione": "01/05/2026 09:00", "ID": "101"}]
        self._run(riga)
        self._run(riga, extra_args=("--skip-existing",))
        self.assertEqual(RilevazioneIncidente.objects.filter(id_originale=101).count(), 1)


class SafetyKpiTests(TestCase):
    @patch("rilevazione_incidenti.services.active_headcount", return_value=50)
    def test_get_safety_kpis_counts_events_and_trir(self, _mock_headcount):
        RilevazioneIncidente.objects.create(
            nominativo="Mario Rossi",
            tipologia_scheda="Accident",
            tipo_evento=TipoEventoSicurezza.INCIDENTE,
            reparto="CNC",
            data_segnalazione=_aware_datetime(2026, 5, 1),
        )
        RilevazioneIncidente.objects.create(
            nominativo="Lucia Bianchi",
            tipologia_scheda="Near Miss",
            tipo_evento=TipoEventoSicurezza.NEAR_MISS,
            reparto="CNC",
            data_segnalazione=_aware_datetime(2026, 5, 2),
        )

        kpis = get_safety_kpis(today=date(2026, 5, 8))

        self.assertEqual(kpis["incidenti"], 1)
        self.assertEqual(kpis["near_miss"], 1)
        self.assertEqual(kpis["headcount"], 50)
        self.assertEqual(kpis["trir"], 2.0)
        self.assertEqual(kpis["giorni_senza_infortuni"], 7)
        self.assertEqual(len(kpis["trend"]), 12)


class HeatmapIncidentiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="sicurezza",
            email="sicurezza@example.com",
            password="pwd12345",
        )
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())
        self.client.force_login(self.user)

    def test_heatmap_renders_incident_count_on_layout_area(self):
        layout = PlantLayout.objects.create(
            category="Officina",
            name="Layout test",
            image="plant_layouts/test.png",
            is_active=True,
        )
        area = PlantLayoutArea.objects.create(
            layout=layout,
            name="CNC 1",
            x_percent=10,
            y_percent=20,
            width_percent=30,
            height_percent=20,
        )
        RilevazioneIncidente.objects.create(
            nominativo="Mario Rossi",
            tipologia_scheda="Accident",
            tipo_evento=TipoEventoSicurezza.INCIDENTE,
            reparto="CNC",
            planimetria_area=area,
            data_segnalazione=_aware_datetime(2026, 5, 1),
        )

        response = self.client.get(reverse("rilevazione_incidenti:heatmap"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Heatmap incidenti")
        self.assertContains(response, "Layout test")
        self.assertContains(response, ">1</text>")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ExportPdfAuthorizationTests(TestCase):
    """SEC-PREPROD-02 (H1): export_pdf riservato ai gestori sicurezza."""

    def setUp(self):
        cfg = SicurezzaImpostazioni.get_singleton()
        cfg.acl_preposti = ["preposto@example.com"]
        cfg.acl_rspp = ["rspp@example.com"]
        cfg.save()
        user_model = get_user_model()
        self.basic = user_model.objects.create_user(
            username="ri-basic", email="basic@example.com", password="pwd12345",
        )
        self.rspp = user_model.objects.create_user(
            username="ri-rspp", email="rspp@example.com", password="pwd12345",
        )
        self.admin = user_model.objects.create_superuser(
            username="ri-admin", email="ri-admin@example.com", password="pwd12345",
        )
        for user in (self.basic, self.rspp):
            UserOnboarding.objects.create(
                user=user, completed=True, completed_at=timezone.now(),
            )
        self.evento = RilevazioneIncidente.objects.create(
            nominativo="Mario Rossi",
            tipologia_scheda="Accident",
            reparto="CNC",
            data_segnalazione=_aware_datetime(2026, 5, 1),
        )

    def _url(self, pk):
        return reverse("rilevazione_incidenti:export_pdf", args=[pk])

    def test_basic_module_user_is_forbidden(self):
        self.client.force_login(self.basic)
        response = self.client.get(self._url(self.evento.pk))
        self.assertEqual(response.status_code, 403)

    def test_rspp_user_is_allowed(self):
        self.client.force_login(self.rspp)
        response = self.client.get(self._url(self.evento.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_superuser_is_allowed(self):
        self.client.force_login(self.admin)
        response = self.client.get(self._url(self.evento.pk))
        self.assertEqual(response.status_code, 200)

    def test_missing_incident_returns_404_for_authorized_user(self):
        self.client.force_login(self.admin)
        response = self.client.get(self._url(999999))
        self.assertEqual(response.status_code, 404)

    def test_denied_is_real_403_and_missing_is_real_404(self):
        # Regressione: in passato la risorsa mancante restituiva il template
        # "forbidden" con status 404 (incoerente). Ora 403 = negato, 404 = assente.
        self.client.force_login(self.basic)
        self.assertEqual(self.client.get(self._url(self.evento.pk)).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self._url(999999)).status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class ReadViewsAuthGuardTests(TestCase):
    """SEC-PREPROD-02 (M1): le viste di lettura non sono accessibili in anonimo."""

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("rilevazione_incidenti:lista"))
        self.assertIn(response.status_code, (301, 302))
        self.assertIn("/login", response.headers.get("Location", ""))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ReadViewsAuthenticatedAccessTests(TestCase):
    """SEC-PREPROD-02 (M1): l'accesso autenticato resta funzionante."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="ri-read-admin", email="ri-read-admin@example.com", password="pwd12345",
        )

    def test_authenticated_manager_can_open_lista(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("rilevazione_incidenti:lista"))
        self.assertEqual(response.status_code, 200)
