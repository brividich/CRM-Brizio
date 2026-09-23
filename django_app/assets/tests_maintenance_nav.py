"""Menu unico della Manutenzione e filtri dello Scadenzario.

La barra di sezione si costruisce da ``assets.maintenance_nav``; la sidebar vive a
database ed e' allineata dalla migration 0106 con una copia congelata della stessa
definizione. Questi test impediscono che le due tornino a divergere.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from assets.maintenance_nav import MAINTENANCE_NAV, find_active
from assets.models import (
    Asset,
    AssetCategory,
    AssetSidebarButton,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
)
from assets.views import _is_sidebar_button_active, _resolve_sidebar_url

User = get_user_model()


class MenuUnicoTests(TestCase):
    def test_sidebar_coincide_con_la_definizione(self):
        for group in MAINTENANCE_NAV:
            parent = AssetSidebarButton.objects.get(code=group.sidebar_code)
            self.assertTrue(parent.is_visible, group.sidebar_code)
            children = list(
                AssetSidebarButton.objects.filter(parent=parent, is_visible=True).order_by("sort_order", "id")
            )
            self.assertEqual(
                [(b.code, b.label) for b in children],
                [(item.sidebar_code, item.label) for item in group.items],
                f"Ramo {group.label}: sidebar e barra di sezione divergono",
            )
            for button, item in zip(children, group.items):
                resolved = _resolve_sidebar_url(button.target_url)
                self.assertEqual(urlsplit(resolved).path, reverse(f"assets:{item.route}"), button.code)

    def test_ogni_voce_ha_un_codice_sidebar_e_rotte_valide(self):
        seen: set[str] = set()
        for group in MAINTENANCE_NAV:
            for item in group.items:
                self.assertTrue(item.sidebar_code, item.key)
                reverse(f"assets:{item.route}")
                for route in item.all_routes:
                    self.assertNotIn(route, seen, f"La rotta {route} accende due voci")
                    seen.add(route)

    def test_licenze_calendario_e_contratti_stanno_nel_ramo(self):
        self.assertEqual(find_active("calendario_asset")[0].label, "Manutenzione")
        self.assertEqual(find_active("software_license_list")[0].label, "Configurazione")
        self.assertEqual(find_active("assistance_contract_list")[0].label, "Configurazione")
        self.assertIsNone(find_active("asset_list"))

    def test_evidenziazione_sidebar_per_nome_rotta(self):
        """Piani e Da fare condividono il prefisso /assets/manutenzione/: con il
        confronto per URL si accendevano insieme; per rotta si accende solo la voce giusta."""
        factory = RequestFactory()
        path = reverse("assets:maintenance_plan_detail", args=[1])
        request = factory.get(path)
        request.resolver_match = resolve(path)
        piani = AssetSidebarButton.objects.get(code="maintenance_piani")
        da_fare = AssetSidebarButton.objects.get(code="maintenance_da_fare")
        config = AssetSidebarButton.objects.get(code="maintenance_configurazione")
        self.assertTrue(_is_sidebar_button_active(request, piani, ""))
        self.assertTrue(_is_sidebar_button_active(request, config, ""))
        self.assertFalse(_is_sidebar_button_active(request, da_fare, ""))


@override_settings(LEGACY_AUTH_ENABLED=False)
class ScadenzarioFiltriTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="admin-scad", password="x", email="s@b.c")
        cls.famiglia = AssetCategory.objects.create(code="sollevamento-t", label="Sollevamento T")
        cls.sotto = AssetCategory.objects.create(code="carroponte-t", label="Carroponte T", parent=cls.famiglia)
        cls.altra = AssetCategory.objects.create(code="cnc-t", label="CNC T")
        plan = MaintenanceInterventionTemplate.objects.create(code="verifica-t", label="Verifica T")
        due = timezone.localdate() + timedelta(days=5)
        cls.asset_sotto = Asset.objects.create(asset_tag="CRP-T1", name="Carroponte", asset_category=cls.sotto)
        cls.asset_altra = Asset.objects.create(asset_tag="CNC-T1", name="Tornio CNC", asset_category=cls.altra)
        for asset in (cls.asset_sotto, cls.asset_altra):
            MaintenanceOccurrence.objects.create(plan=plan, asset=asset, due_date=due, warning_days=30)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_famiglia_include_le_sottocategorie(self):
        response = self.client.get(reverse("assets:maintenance_scadenze"), {"category": self.famiglia.id})
        self.assertEqual(response.status_code, 200)
        # Sulle righe, non sull'HTML: il menu "Asset" dei filtri avanzati elenca tutti gli asset.
        tags = {row["occurrence"].asset.asset_tag for row in response.context["rows"]}
        self.assertEqual(tags, {"CRP-T1"})

    def test_schede_conservano_gli_altri_filtri(self):
        response = self.client.get(
            reverse("assets:maintenance_scadenze"), {"window": "30", "q": "carro", "category": self.famiglia.id}
        )
        for tab in response.context["window_tabs"] + response.context["type_tabs"]:
            query = parse_qs(urlsplit(tab["url"]).query)
            self.assertEqual(query.get("q"), ["carro"], tab["label"])
            self.assertEqual(query.get("category"), [str(self.famiglia.id)], tab["label"])
        amministrative = next(t for t in response.context["type_tabs"] if t["label"] == "Amministrative")
        # Cambiare tipologia non azzera piu' la finestra temporale.
        self.assertEqual(parse_qs(urlsplit(amministrative["url"]).query).get("window"), ["30"])

    def test_finestra_e_tipologia_non_compaiono_due_volte(self):
        response = self.client.get(reverse("assets:maintenance_scadenze"))
        form = response.context["filter_form"]
        visibili = {f.name for f in form.simple_fields} | {f.name for f in form.advanced_fields}
        self.assertNotIn("window", visibili)
        self.assertNotIn("plan_type", visibili)
        self.assertEqual([f.name for f in form.simple_fields], ["q", "category", "reparto", "assignee"])
        self.assertContains(response, 'name="window"', html=False)
