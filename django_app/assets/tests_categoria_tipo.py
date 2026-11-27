from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserOnboarding

from .models import Asset, AssetCategory
from .services import categoria_tipo


class CategoriaFamigliaTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("cat_tipo_admin", "cat@example.com", "x")
        UserOnboarding.objects.update_or_create(user=self.admin, defaults={"completed": True})
        self.client.force_login(self.admin)
        self.madre = AssetCategory.objects.create(code="t-officina", label="Officina test")
        self.torni = AssetCategory.objects.create(code="t-torni", label="Torni test", parent=self.madre)
        self.figlia = AssetCategory.objects.create(code="t-torni-figlia", label="Torni figlia", parent=self.torni)
        self.tornio = Asset.objects.create(asset_tag="CT-1", name="Tornio uno", asset_category=self.torni)
        self.altro = Asset.objects.create(asset_tag="CT-2", name="Tornio due", asset_category=self.torni)
        self.sotto = Asset.objects.create(asset_tag="CT-3", name="Nella figlia", asset_category=self.figlia)
        self.fuori = Asset.objects.create(asset_tag="CT-4", name="Altra categoria", asset_category=self.madre)

    def _cambia_famiglia(self, categoria, famiglia):
        return self.client.post(reverse("assets:gestione_admin"), {
            "action": "update_asset_category",
            "category_id": categoria.pk,
            "label": categoria.label,
            "parent_id": categoria.parent_id or "",
            "base_asset_type": famiglia,
            "sort_order": categoria.sort_order,
            "is_active": "1",
        }, follow=True)

    def _tipi(self):
        return {a.asset_tag: a.asset_type for a in Asset.objects.filter(asset_tag__startswith="CT-")}

    def test_cambio_famiglia_riallinea_solo_gli_asset_della_categoria(self):
        risposta = self._cambia_famiglia(self.torni, Asset.TYPE_WORK_MACHINE)
        self.assertContains(risposta, "2 asset passati a «Macchina di lavoro»")
        self.assertEqual(self._tipi(), {
            "CT-1": Asset.TYPE_WORK_MACHINE, "CT-2": Asset.TYPE_WORK_MACHINE,
            "CT-3": Asset.TYPE_OTHER, "CT-4": Asset.TYPE_OTHER,
        })

    def test_salvare_senza_cambiare_famiglia_non_tocca_gli_asset(self):
        Asset.objects.filter(pk=self.tornio.pk).update(asset_type=Asset.TYPE_HW)
        self._cambia_famiglia(self.torni, Asset.TYPE_OTHER)
        self.assertEqual(self._tipi()["CT-1"], Asset.TYPE_HW)

    def test_prodotti_chimici_mai_in_blocco(self):
        Asset.objects.filter(pk=self.tornio.pk).update(asset_type=Asset.TYPE_CHEMICAL)
        self.torni.base_asset_type = Asset.TYPE_WORK_MACHINE
        self.assertEqual(categoria_tipo.allinea_asset(self.torni, Asset.TYPE_OTHER), 1)
        self.assertEqual(self._tipi()["CT-1"], Asset.TYPE_CHEMICAL)
        self.torni.base_asset_type = Asset.TYPE_CHEMICAL
        self.assertEqual(categoria_tipo.allinea_asset(self.torni, Asset.TYPE_WORK_MACHINE), 0)

    def test_macchina_senza_scheda_macchina_si_apre_e_si_modifica(self):
        """Un asset diventato macchina di lavoro non ha la riga WorkMachine: le pagine devono reggere."""
        self._cambia_famiglia(self.torni, Asset.TYPE_WORK_MACHINE)
        for nome, argomenti in (("assets:asset_view", [self.tornio.pk]), ("assets:work_machine_edit", [self.tornio.pk]),
                                ("assets:work_machine_list", []), ("assets:asset_list", [])):
            risposta = self.client.get(reverse(nome, args=argomenti), follow=True)
            self.assertEqual(risposta.status_code, 200, nome)
        elenco = self.client.get(reverse("assets:asset_list"), {"group": "production"})
        self.assertContains(elenco, "Tornio uno")
