from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserOnboarding

from .forms import AssetForm, WorkMachineAssetForm
from .models import Asset
from .services import acronimi
from .services.ricerca_flessibile import testo_q


class AssetAcronimoTests(TestCase):
    def test_vuoto_di_default(self):
        asset = Asset.objects.create(asset_tag="ACR-1", name="Tornio")
        self.assertEqual(asset.acronimo, "")

    def test_non_univoco(self):
        Asset.objects.create(asset_tag="ACR-2", name="Centro A", acronimo="DM11")
        Asset.objects.create(asset_tag="ACR-3", name="Centro B", acronimo="DM11")
        self.assertEqual(Asset.objects.filter(acronimo="DM11").count(), 2)

    def test_campo_nei_form(self):
        self.assertIn("acronimo", AssetForm.Meta.fields)
        self.assertEqual(AssetForm.Meta.labels["acronimo"], "Acronimo")
        self.assertIn("acronimo", WorkMachineAssetForm.Meta.fields)
        self.assertIn("acronimo", WorkMachineAssetForm.asset_field_names)

    def test_ricerca_trova_per_acronimo(self):
        asset = Asset.objects.create(asset_tag="ACR-4", name="Carrello automatico", acronimo="AGV1")
        Asset.objects.create(asset_tag="ACR-5", name="Altro")
        trovati = Asset.objects.filter(testo_q("agv 1", ("name", "acronimo"), compatti=("name", "acronimo")))
        self.assertEqual(list(trovati), [asset])


class ProponiAcronimiTests(TestCase):
    def test_candidati_da_nome_e_tag(self):
        self.assertEqual(acronimi.candidati(Asset(name="DM7 - DMG Mori", asset_tag="X-1")), ["DM7"])
        self.assertEqual(acronimi.candidati(Asset(name="Centro di lavoro", asset_tag="CNC-DM11-0006")), ["DM11"])
        self.assertEqual(acronimi.candidati(Asset(name="C1 Tornio", asset_tag="X-2")), ["C1"])
        # misure, modelli lunghi e tag senza sigla non sono acronimi
        self.assertEqual(acronimi.candidati(Asset(name="Pressa 1400mm 5assi", asset_tag="WM-000123")), [])
        self.assertEqual(acronimi.candidati(Asset(name="Stampante LaserJetM404dn", asset_tag="IT-000001")), [])

    def test_righe_spunta_solo_le_proposte_sicure(self):
        sicura = Asset.objects.create(asset_tag="P-1", name="AGV1 Carrello", asset_type=Asset.TYPE_WORK_MACHINE)
        doppia_a = Asset.objects.create(asset_tag="P-2", name="MK2 Fresa A", asset_type=Asset.TYPE_CNC)
        doppia_b = Asset.objects.create(asset_tag="P-3", name="MK2 Fresa B", asset_type=Asset.TYPE_CNC)
        usata = Asset.objects.create(asset_tag="P-4", name="DM11 Centro", asset_type=Asset.TYPE_CNC)
        Asset.objects.create(asset_tag="P-5", name="Altro centro", acronimo="dm11")
        it = Asset.objects.create(asset_tag="P-6", name="SW24 Switch", asset_type=Asset.TYPE_PC)
        muta = Asset.objects.create(asset_tag="P-7", name="Tornio parallelo")
        Asset.objects.create(asset_tag="P-8", name="ZZ9 Dismessa", status=Asset.STATUS_RETIRED)
        con, senza = acronimi.righe(Asset.objects.all())
        per_id = {r.asset.pk: r for r in con}
        self.assertTrue(per_id[sicura.pk].spuntata)
        self.assertEqual(per_id[sicura.pk].proposta, "AGV1")
        for asset, avviso in ((doppia_a, "Stessa sigla su 2 asset"), (doppia_b, "Stessa sigla su 2 asset"),
                              (usata, "Già usato da un altro asset"), (it, "Dispositivo IT: controlla")):
            self.assertFalse(per_id[asset.pk].spuntata)
            self.assertEqual(per_id[asset.pk].avviso, avviso)
        self.assertEqual([r.asset.pk for r in senza], [muta.pk])
        self.assertEqual(len(con), 5)

    def test_applica_non_sovrascrive(self):
        vuoto = Asset.objects.create(asset_tag="A-1", name="Uno")
        pieno = Asset.objects.create(asset_tag="A-2", name="Due", acronimo="OLD1")
        salvati = acronimi.applica(Asset.objects.all(), {vuoto.pk: "  dm 5 ", pieno.pk: "NEW1", 999999: "X1"})
        self.assertEqual(salvati, 1)
        vuoto.refresh_from_db()
        pieno.refresh_from_db()
        self.assertEqual(vuoto.acronimo, "dm 5")
        self.assertEqual(pieno.acronimo, "OLD1")

    def test_pagina_salva_solo_le_righe_spuntate(self):
        utente = get_user_model().objects.create_superuser("acr_admin", "acr@example.com", "x")
        UserOnboarding.objects.update_or_create(user=utente, defaults={"completed": True})
        self.client.force_login(utente)
        a = Asset.objects.create(asset_tag="W-1", name="AGV1 Carrello", asset_type=Asset.TYPE_WORK_MACHINE)
        b = Asset.objects.create(asset_tag="W-2", name="MK2 Fresa", asset_type=Asset.TYPE_CNC)
        url = reverse("assets:acronimi_proponi")
        pagina = self.client.get(url)
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, f'name="acr_{a.pk}" value="AGV1"')
        self.assertContains(pagina, "? Guida")
        risposta = self.client.post(url, {"sel": [str(a.pk)], f"acr_{a.pk}": "AGV1", f"acr_{b.pk}": "MK2"})
        self.assertEqual(risposta.status_code, 302)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.acronimo, b.acronimo), ("AGV1", ""))
        elenco = self.client.get(reverse("assets:asset_list"))
        self.assertContains(elenco, "Senza acronimo (1)")

    def test_pagina_richiede_login(self):
        risposta = self.client.get(reverse("assets:acronimi_proponi"))
        self.assertEqual(risposta.status_code, 302)
        self.assertIn("login", risposta["Location"])