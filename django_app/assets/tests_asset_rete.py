"""Interfacce di rete modificabili dalla scheda e mappa porte dello switch. Dati sintetici."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import Asset, AssetEndpoint, AssetFieldHistory
from .services import rete_switch

User = get_user_model()


def _user(username, *, superuser=False):
    user = User.objects.create_user(username=username, password="x", is_superuser=superuser, is_staff=superuser)
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()})
    return user


def _gestione(n_righe, **righe):
    data = {
        "rete-TOTAL_FORMS": str(n_righe), "rete-INITIAL_FORMS": "0",
        "rete-MIN_NUM_FORMS": "0", "rete-MAX_NUM_FORMS": "1000",
    }
    data.update(righe)
    return data


class PortaTests(TestCase):
    def test_scomponi_porta(self):
        self.assertEqual(rete_switch.scomponi_porta("A0.1.37"), ("A0", "1", 37))
        self.assertEqual(rete_switch.scomponi_porta("a1.19"), ("A1", "", 19))
        self.assertEqual(rete_switch.scomponi_porta("Gi1/0/3"), ("GI1", "0", 3))
        self.assertIsNone(rete_switch.scomponi_porta("A3."))
        self.assertIsNone(rete_switch.scomponi_porta(""))


class ModificaReteTests(TestCase):
    def setUp(self):
        self.admin = _user("rete.admin", superuser=True)
        self.client.force_login(self.admin)
        self.pc = Asset.objects.create(asset_tag="SYN-PC-1", name="PC sintetico", asset_type=Asset.TYPE_PC,
                                       status=Asset.STATUS_IN_USE)
        self.switch = Asset.objects.create(asset_tag="SYN-SW-1", name="Switch sintetico CED",
                                           asset_type=Asset.TYPE_HW, status=Asset.STATUS_IN_USE)
        self.url = reverse("assets:asset_rete_edit", args=[self.pc.id])

    def test_form_si_apre_e_riga_vuota_non_crea_nulla(self):
        resp = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertContains(resp, "Salva rete")
        self.assertContains(resp, "SYN-SW-1")  # tendina switch
        resp = self.client.post(self.url, _gestione(1), HTTP_HX_REQUEST="true")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.pc.endpoints.exists())

    def test_aggiunge_interfaccia_con_storico(self):
        resp = self.client.post(self.url, _gestione(
            1, **{"rete-0-ip": "192.0.2.10", "rete-0-mac": "AA-BB-CC-DD-EE-01", "rete-0-vlan": "23",
                  "rete-0-switch_name": "SYN-SW-1", "rete-0-switch_port": "A0.1.5", "rete-0-punto": "Q0.1"},
        ), HTTP_HX_REQUEST="true")
        self.assertEqual(resp.status_code, 200)
        ep = self.pc.endpoints.get()
        self.assertEqual((ep.endpoint_name, ep.ip, ep.mac, ep.vlan), ("Collegamento principale", "192.0.2.10", "aa:bb:cc:dd:ee:01", 23))
        self.assertContains(resp, reverse("assets:asset_view", args=[self.switch.id]))
        self.assertTrue(AssetFieldHistory.objects.filter(asset=self.pc, campo="endpoint.ip").exists())

    def test_mac_non_valido_rifiutato(self):
        resp = self.client.post(self.url, _gestione(1, **{"rete-0-mac": "non-un-mac"}), HTTP_HX_REQUEST="true")
        self.assertContains(resp, "MAC non valido")
        self.assertFalse(self.pc.endpoints.exists())

    def test_modifica_ed_elimina(self):
        ep = AssetEndpoint.objects.create(asset=self.pc, endpoint_name="Collegamento principale", ip="192.0.2.1")
        data = _gestione(2, **{
            "rete-INITIAL_FORMS": "1",
            "rete-0-id": str(ep.id), "rete-0-endpoint_name": "Collegamento principale", "rete-0-ip": "192.0.2.2",
        })
        self.client.post(self.url, data, HTTP_HX_REQUEST="true")
        ep.refresh_from_db()
        self.assertEqual(ep.ip, "192.0.2.2")
        data["rete-0-DELETE"] = "on"
        self.client.post(self.url, data, HTTP_HX_REQUEST="true")
        self.assertFalse(AssetEndpoint.objects.filter(pk=ep.pk).exists())

    def test_senza_permesso_403(self):
        self.client.force_login(_user("rete.base"))
        resp = self.client.post(self.url, _gestione(1, **{"rete-0-ip": "192.0.2.9"}))
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(self.pc.endpoints.exists())


class MappaSwitchTests(TestCase):
    def setUp(self):
        self.admin = _user("mappa.admin", superuser=True)
        self.client.force_login(self.admin)
        self.switch = Asset.objects.create(asset_tag="SYN-SW-2", name="Switch sintetico", asset_type=Asset.TYPE_HW,
                                           status=Asset.STATUS_IN_USE)
        pcs = [Asset.objects.create(asset_tag=f"SYN-PC-{i}", name=f"PC {i}", asset_type=Asset.TYPE_PC) for i in range(3)]
        AssetEndpoint.objects.create(asset=pcs[0], switch_name="syn-sw-2", switch_port="A0.1.3", vlan=23)
        AssetEndpoint.objects.create(asset=pcs[1], switch_port="A0.2.7")
        AssetEndpoint.objects.create(asset=pcs[2], switch_port="B1.4")

    def test_mappa_porte(self):
        mappa = rete_switch.mappa_switch(self.switch)
        self.assertEqual(mappa["totale"], 1)
        pannello = mappa["pannelli"][0]
        self.assertEqual((pannello["titolo"], pannello["totale"]), ("A0.1", 24))
        porta3 = next(s for s in pannello["sopra"] if s["numero"] == 3)
        self.assertEqual(porta3["occupanti"][0].asset.asset_tag, "SYN-PC-0")
        self.assertEqual({p["prefisso"]: p["porte"] for p in mappa["prefissi_liberi"]}, {"A0": 1, "B1": 1})

    def _prefisso(self, valore, switch=None):
        return self.client.post(reverse("assets:asset_rete_prefisso", args=[(switch or self.switch).id]), {"prefisso": valore})

    def test_prefisso_collega_senza_scrivere_sui_punti_rete(self):
        resp = self._prefisso("a0")
        self.assertEqual(resp.status_code, 302)
        self.switch.refresh_from_db()
        self.assertEqual(self.switch.switch_prefisso_porte, "A0")
        self.assertEqual(AssetEndpoint.objects.filter(switch_name="").count(), 2)  # nessuna scrittura sugli endpoint
        self.assertTrue(AssetFieldHistory.objects.filter(asset=self.switch, campo="switch_prefisso_porte").exists())
        mappa = rete_switch.mappa_switch(self.switch)
        self.assertEqual(mappa["totale"], 2)
        self.assertEqual([p["titolo"] for p in mappa["pannelli"]], ["A0.1", "A0.2"])
        self.assertEqual({p["prefisso"] for p in mappa["prefissi_liberi"]}, {"B1"})
        # Una porta censita dopo segue lo switch da sola.
        nuovo = Asset.objects.create(asset_tag="SYN-PC-9", name="PC 9", asset_type=Asset.TYPE_PC)
        ep = AssetEndpoint.objects.create(asset=nuovo, switch_port="A0.2.9")
        self.assertEqual(rete_switch.mappa_switch(self.switch)["totale"], 3)
        self.assertEqual(rete_switch.switch_per_endpoint([ep])[ep.id], (self.switch, True))
        resp = self.client.get(reverse("assets:asset_view", args=[self.switch.id]))
        self.assertContains(resp, "Mappa porte dello switch")
        self.assertContains(resp, "A0.2")
        resp = self.client.get(reverse("assets:asset_view", args=[nuovo.id]))
        self.assertContains(resp, "da prefisso")

    def test_switch_name_esplicito_vince_sul_prefisso(self):
        altro = Asset.objects.create(asset_tag="SYN-SW-3", name="Altro switch", asset_type=Asset.TYPE_HW)
        self._prefisso("A0", altro)
        altro.refresh_from_db()
        # A0.1.3 indica SYN-SW-2 esplicitamente: resta suo; A0.2.7 (senza switch) va ad altro.
        self.assertEqual(rete_switch.mappa_switch(self.switch)["totale"], 1)
        self.assertEqual(rete_switch.mappa_switch(altro)["totale"], 1)

    def test_prefisso_duplicato_rifiutato_e_rimovibile(self):
        self._prefisso("A0")
        altro = Asset.objects.create(asset_tag="SYN-SW-4", name="Switch doppione", asset_type=Asset.TYPE_HW)
        self._prefisso("A0", altro)
        altro.refresh_from_db()
        self.assertEqual(altro.switch_prefisso_porte, "")
        self._prefisso("")
        self.switch.refresh_from_db()
        self.assertEqual(self.switch.switch_prefisso_porte, "")

    def test_prefisso_non_valido(self):
        self._prefisso("A0;--")
        self.switch.refresh_from_db()
        self.assertEqual(self.switch.switch_prefisso_porte, "")