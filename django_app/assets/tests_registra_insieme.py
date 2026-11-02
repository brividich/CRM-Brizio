"""«Registra insieme»: rinnovo contratti con «Rinnova anche» e nuova scadenza «Crea anche su…».

Checklist: docs/ai/CHECKLIST_REGISTRA_INSIEME.md (voci 3 e 4; 1 e 2 nei test di manutenzione e licenze).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore
from assets.models import Asset, AssetAdministrativeDeadline, AssetCategory, AssistanceContract

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class RinnovoContrattiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="ins-contr-admin", password="x", email="c@i.n")
        cls.ditta = Fornitore.objects.create(ragione_sociale="Ditta Assistenza Sintetica")
        cls.altra_ditta = Fornitore.objects.create(ragione_sociale="Altra Ditta Sintetica")

    def setUp(self):
        self.client.force_login(self.admin)
        self.main = AssistanceContract.objects.create(
            supplier=self.ditta, title="Full service presse", start_date=date(2025, 1, 1), end_date=date(2026, 12, 31),
            notes="Contratto quadro",
        )
        self.gemello = AssistanceContract.objects.create(
            supplier=self.ditta, title="Assistenza compressori", start_date=date(2025, 1, 1), end_date=date(2027, 2, 28),
        )
        self.altra = AssistanceContract.objects.create(
            supplier=self.altra_ditta, title="Altro fornitore", start_date=date(2025, 1, 1), end_date=date(2026, 12, 31),
        )
        self.url = reverse("assets:assistance_contract_list")

    def test_pagina_propone_rinnovo_e_contratti_dello_stesso_fornitore(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'value="renew_assistance_contract"')
        self.assertContains(page, 'name="renew_end_date" value="2027-12-31"')
        self.assertContains(page, f'name="also_renew" value="{self.gemello.id}"')
        self.assertContains(page, '<li data-insieme-days="59">')
        self.assertNotContains(page, f'name="also_renew" value="{self.altra.id}"')
        self.assertNotContains(page, "{#")

    def test_rinnova_insieme_e_scrive_note(self):
        response = self.client.post(self.url, {
            "action": "renew_assistance_contract", "contract_id": self.main.id,
            "renew_end_date": "2027-12-31", "renew_note": "offerta 12/26",
            "also_renew": [self.gemello.id, self.altra.id],
        })
        self.assertEqual(response.status_code, 302)
        for contract in (self.main, self.gemello, self.altra):
            contract.refresh_from_db()
        self.assertEqual(self.main.end_date, date(2027, 12, 31))
        self.assertIn("Contratto quadro", self.main.notes)
        self.assertIn("fine da 31/12/2026 a 31/12/2027 — offerta 12/26.", self.main.notes)
        self.assertEqual(self.gemello.end_date, date(2027, 12, 31))
        self.assertIn("fine da 28/02/2027", self.gemello.notes)
        self.assertEqual(self.altra.end_date, date(2026, 12, 31))  # altro fornitore: mai

    def test_data_non_successiva_non_rinnova(self):
        self.client.post(self.url, {
            "action": "renew_assistance_contract", "contract_id": self.main.id, "renew_end_date": "2026-06-30",
            "also_renew": [self.gemello.id],
        })
        self.main.refresh_from_db()
        self.gemello.refresh_from_db()
        self.assertEqual(self.main.end_date, date(2026, 12, 31))
        self.assertEqual(self.gemello.end_date, date(2027, 2, 28))

    def test_senza_permesso_non_rinnova(self):
        user = User.objects.create_user(username="ins-contr-base", password="x")
        self.client.force_login(user)
        self.client.post(self.url, {
            "action": "renew_assistance_contract", "contract_id": self.main.id, "renew_end_date": "2027-12-31",
        })
        self.main.refresh_from_db()
        self.assertEqual(self.main.end_date, date(2026, 12, 31))


@override_settings(LEGACY_AUTH_ENABLED=False)
class NuovaScadenzaCreaAncheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="ins-scad-admin", password="x", email="s@i.n")
        cls.today = timezone.localdate()
        cls.carrelli = AssetCategory.objects.create(code="ins-carrelli", label="Carrelli insieme")
        cls.altra_cat = AssetCategory.objects.create(code="ins-altro", label="Altro insieme")
        cls.c1 = Asset.objects.create(asset_tag="INS-C1", name="Carrello 1", asset_category=cls.carrelli, status=Asset.STATUS_IN_USE)
        cls.c2 = Asset.objects.create(asset_tag="INS-C2", name="Carrello 2", asset_category=cls.carrelli, status=Asset.STATUS_IN_USE)
        cls.c3 = Asset.objects.create(asset_tag="INS-C3", name="Carrello 3", asset_category=cls.carrelli, status=Asset.STATUS_IN_USE)
        cls.dismesso = Asset.objects.create(asset_tag="INS-C4", name="Carrello dismesso", asset_category=cls.carrelli, status=Asset.STATUS_RETIRED)
        cls.fuori = Asset.objects.create(asset_tag="INS-X1", name="Altra categoria", asset_category=cls.altra_cat, status=Asset.STATUS_IN_USE)
        # c3 ha gia' la scadenza: non va duplicata.
        AssetAdministrativeDeadline.objects.create(
            asset=cls.c3, deadline_type=AssetAdministrativeDeadline.TYPE_TECHNICAL, title="Controllo batterie",
            due_date=cls.today + timedelta(days=40),
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = f"{reverse('assets:asset_administrative_deadline_create')}?asset={self.c1.id}"

    def test_pagina_propone_gli_asset_della_stessa_categoria(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Crea anche su")
        for asset in (self.c2, self.c3):
            self.assertContains(page, f'name="extra_asset_ids" value="{asset.id}"')
        for asset in (self.c1, self.dismesso, self.fuori):
            self.assertNotContains(page, f'name="extra_asset_ids" value="{asset.id}"')
        self.assertNotContains(page, "{#")

    def test_crea_anche_e_salta_chi_ce_l_ha_gia(self):
        due = self.today + timedelta(days=30)
        response = self.client.post(self.url, {
            "asset": self.c1.id,
            "deadline_type": AssetAdministrativeDeadline.TYPE_TECHNICAL,
            "title": "Controllo batterie",
            "due_date": due.isoformat(),
            "warning_days": 30,
            "recurrence_months": 3,
            "is_active": "on",
            "extra_asset_ids": [self.c2.id, self.c3.id, self.fuori.id],
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", {}) and response.context["form"].errors)
        qs = AssetAdministrativeDeadline.objects.filter(title__iexact="Controllo batterie")
        self.assertTrue(qs.filter(asset=self.c1).exists())
        copia = qs.get(asset=self.c2)
        self.assertEqual((copia.due_date, copia.recurrence_months, copia.warning_days), (due, 3, 30))
        self.assertEqual(qs.filter(asset=self.c3).count(), 1)  # gia' presente: nessun doppione
        self.assertFalse(qs.filter(asset=self.fuori).exists())  # altra categoria: mai
