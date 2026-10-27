"""Mappa di calore: posizione da punto, macchina, area, reparto; punto indicato nel modulo."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, PlantLayout, PlantLayoutMarker
from core.models import UserOnboarding
from rilevazione_incidenti import views
from rilevazione_incidenti.models import RilevazioneIncidente, TipoEventoSicurezza


class HeatmapFontiTests(TestCase):
    def setUp(self):
        self.layout = PlantLayout.objects.create(category="Officina", name="Officina", image="plant_layouts/t.png", is_active=True)
        self.other = PlantLayout.objects.create(category="Carroponti", name="Carroponti", image="plant_layouts/c.png", is_active=True)
        self.tornio = Asset.objects.create(asset_tag="HM-1", name="Tornio", reparto="Torni")
        self.tornio2 = Asset.objects.create(asset_tag="HM-2", name="Tornio 2", reparto="Torni")
        PlantLayoutMarker.objects.create(layout=self.layout, asset=self.tornio, x_percent=20, y_percent=40)
        PlantLayoutMarker.objects.create(layout=self.layout, asset=self.tornio2, x_percent=40, y_percent=40)

    def _ril(self, **kw):
        kw.setdefault("tipologia_scheda", "Accident")
        kw.setdefault("tipo_evento", TipoEventoSicurezza.INCIDENTE)
        return RilevazioneIncidente.objects.create(nominativo="Persona Sintetica", **kw)

    def test_sources_in_order_of_precision(self):
        self._ril(planimetria_layout=self.layout, planimetria_x=80, planimetria_y=10, reparto="Torni")
        self._ril(asset=self.tornio, reparto="Torni")
        self._ril(reparto="torni")  # baricentro delle macchine del reparto
        self._ril(planimetria_layout=self.other, planimetria_x=5, planimetria_y=5)  # altra pianta
        self._ril(reparto="Magazzino")  # nessun indizio
        points, fonti = views.heatmap_points(self.layout, RilevazioneIncidente.objects.all())
        self.assertEqual(dict(fonti), {"punto": 1, "macchina": 1, "reparto": 1, "fuori": 2})
        coords = sorted((p["x"], p["y"]) for p in points)
        self.assertEqual(coords, [(20.0, 40.0), (30.0, 40.0), (80.0, 10.0)])

    def test_parse_point(self):
        self.assertEqual(views.parse_planimetria_punto("7;12.5;80"), (7, 12.5, 80.0))
        for bad in ("", "7;120;5", "x;1;2", "7;1", "0;1;1"):
            self.assertIsNone(views.parse_planimetria_punto(bad))

    def test_point_saved_from_form_fields(self):
        kwargs = views._sp_fields_to_kwargs({"PlanimetriaPunto": f"{self.layout.id};33.3;44.4"})
        self.assertEqual((kwargs["planimetria_layout_id"], kwargs["planimetria_x"], kwargs["planimetria_y"]), (self.layout.id, 33.3, 44.4))
        self.assertIsNone(views._sp_fields_to_kwargs({"PlanimetriaPunto": "99999;1;1"})["planimetria_layout_id"])
        ril = self._ril(planimetria_layout=self.layout, planimetria_x=33.3, planimetria_y=44.4)
        self.assertEqual(ril.as_sp_fields()["PlanimetriaPunto"], f"{self.layout.id};33.30;44.40")

    def test_pages_render(self):
        user = get_user_model().objects.create_superuser(username="hm-admin", email="hm@example.com", password="x")
        UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())
        self.client.force_login(user)
        self._ril(asset=self.tornio, reparto="Torni")
        response = self.client.get(reverse("rilevazione_incidenti:heatmap") + f"?layout={self.layout.id}")
        self.assertContains(response, "macchina coinvolta")
        # coordinate sempre col punto: con la virgola il punto finirebbe fuori posto
        self.assertContains(response, "left:20.0%;top:40.0%")
        response = self.client.get(reverse("rilevazione_incidenti:nuovo") + "?tipo=Accident")
        self.assertContains(response, 'name="planimetria_punto"')
        self.assertContains(response, "Dove è successo")
