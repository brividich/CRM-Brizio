from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import PlantLayout, PlantLayoutArea
from core.models import UserOnboarding

from .models import RilevazioneIncidente, TipoEventoSicurezza, normalize_tipo_evento
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
