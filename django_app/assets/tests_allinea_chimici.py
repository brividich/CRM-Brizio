"""Allineamento asset «Prodotto chimico» ↔ Schede di sicurezza."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from assets.models import Asset
from assets.services import allinea_chimici
from schede_sicurezza.models import ProdottoChimico


class AllineaChimiciTests(TestCase):
    def setUp(self):
        self.senza_asset = ProdottoChimico.objects.create(nome="Sgrassante A")
        self.rinominato = ProdottoChimico.objects.create(nome="Olio B nuovo")
        self.asset_rin = Asset.objects.create(name="Olio B", asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=self.rinominato)
        self.disattivato = ProdottoChimico.objects.create(nome="Solvente C", attivo=False)
        self.asset_dis = Asset.objects.create(name="Solvente C", asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=self.disattivato)
        self.inattivo_senza = ProdottoChimico.objects.create(nome="Vecchio D", attivo=False)

    def test_differenze_e_allinea(self):
        diff = allinea_chimici.differenze()
        self.assertEqual([p.pk for p in diff.da_creare], [self.senza_asset.pk])
        self.assertEqual(diff.totale, 3)

        allinea_chimici.allinea()

        nuovo = Asset.objects.get(prodotto_chimico=self.senza_asset)
        self.assertEqual(nuovo.asset_type, Asset.TYPE_CHEMICAL)
        self.assertEqual(nuovo.name, "Sgrassante A")
        self.assertEqual(Asset.objects.get(pk=self.asset_rin.pk).name, "Olio B nuovo")
        self.assertEqual(Asset.objects.get(pk=self.asset_dis.pk).status, Asset.STATUS_RETIRED)
        self.assertFalse(Asset.objects.filter(prodotto_chimico=self.inattivo_senza).exists())
        self.assertEqual(allinea_chimici.differenze().totale, 0)

    def test_riattivazione(self):
        Asset.objects.filter(pk=self.asset_dis.pk).update(status=Asset.STATUS_RETIRED)
        ProdottoChimico.objects.filter(pk=self.disattivato.pk).update(attivo=True)
        allinea_chimici.allinea([ProdottoChimico.objects.get(pk=self.disattivato.pk)])
        self.assertEqual(Asset.objects.get(pk=self.asset_dis.pk).status, Asset.STATUS_IN_USE)

    def test_pulsante(self):
        user = get_user_model().objects.create_superuser(username="sds_admin", email="sds@example.com", password="x")
        self.client.force_login(user)
        with patch("schede_sicurezza.views._can_gestire", return_value=True):
            response = self.client.post(reverse("schede_sicurezza:allinea_inventario"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Asset.objects.filter(prodotto_chimico=self.senza_asset).exists())

    def test_pulsante_negato_senza_gestione(self):
        user = get_user_model().objects.create_user(username="sds_user", email="u@example.com", password="x")
        self.client.force_login(user)
        with patch("schede_sicurezza.views._can_gestire", return_value=False):
            self.client.post(reverse("schede_sicurezza:allinea_inventario"))
        self.assertFalse(Asset.objects.filter(prodotto_chimico=self.senza_asset).exists())
