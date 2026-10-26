"""Interfacce di rete modificabili dalla scheda e mappa porte dello switch. Dati sintetici."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import Asset, AssetEndpoint, AssetFieldHistory, RackRete
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
        self.assertContains(resp, "riconosciuto dalla porta")

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


class RackTests(TestCase):
    """Rack con prefisso A0 e stack di switch: ogni membro serve le sue porte A0.<membro>.x."""

    def setUp(self):
        self.admin = _user("rack.admin", superuser=True)
        self.client.force_login(self.admin)
        self.rack = RackRete.objects.create(codice="R0", nome="Armadio sintetico", prefisso_porte="A0", prefisso_patch="Q0")
        self.sw1 = Asset.objects.create(asset_tag="SYN-SW-M1", name="Switch stack 1", asset_type=Asset.TYPE_HW)
        self.sw2 = Asset.objects.create(asset_tag="SYN-SW-M2", name="Switch stack 2", asset_type=Asset.TYPE_HW)
        self.pc = [Asset.objects.create(asset_tag=f"SYN-PCR-{i}", name=f"PC {i}", asset_type=Asset.TYPE_PC) for i in range(5)]
        self.ep1 = AssetEndpoint.objects.create(asset=self.pc[0], switch_port="A0.1.3", vlan=10)
        self.ep2 = AssetEndpoint.objects.create(asset=self.pc[1], switch_port="A0.2.7")
        # Inventario che scrive il nome dello stack (switch membro 1) anche per le porte del membro 2.
        self.ep3 = AssetEndpoint.objects.create(asset=self.pc[2], switch_name="SYN-SW-M1", switch_port="A0.2.9")
        self.ep4 = AssetEndpoint.objects.create(asset=self.pc[3], switch_port="A0.3.1")
        self.ep5 = AssetEndpoint.objects.create(asset=self.pc[4], punto="Q0.12")

    def _colloca(self, switch, **dati):
        return self.client.post(reverse("assets:asset_rete_prefisso", args=[switch.id]), dati)

    def test_membri_dividono_le_porte_del_rack(self):
        self._colloca(self.sw1, rack=str(self.rack.id), membro="1", prefisso="")
        self._colloca(self.sw2, rack=str(self.rack.id), membro="2", prefisso="")
        self.sw1.refresh_from_db()
        self.sw2.refresh_from_db()
        self.assertEqual((self.sw1.rack_id, self.sw1.switch_membro), (self.rack.id, "1"))
        self.assertTrue(AssetFieldHistory.objects.filter(asset=self.sw1, campo="rack__codice", valore_dopo="R0").exists())
        risolti = rete_switch.collegamenti([self.ep1, self.ep2, self.ep3, self.ep4, self.ep5])
        self.assertEqual(risolti[self.ep1.id].switch, self.sw1)
        self.assertEqual(risolti[self.ep2.id].switch, self.sw2)
        self.assertEqual(risolti[self.ep3.id].switch, self.sw2)  # nome dello stack, porta del membro 2
        self.assertIsNone(risolti[self.ep4.id].switch)  # membro 3 non censito
        for ep in (self.ep1, self.ep2, self.ep4, self.ep5):
            self.assertEqual(risolti[ep.id].rack, self.rack)
        self.assertEqual(rete_switch.mappa_switch(self.sw1)["totale"], 1)
        self.assertEqual(rete_switch.mappa_switch(self.sw2)["totale"], 2)
        self.assertEqual(rete_switch.porte_senza_switch(), [{"prefisso": "A0.3", "membro": "3", "porte": 1, "rack": self.rack}])
        self.assertIn("membro 3", rete_switch.motivo_senza_switch(self.ep4, self.rack))
        panoramica = rete_switch.panoramica_rack()
        self.assertEqual(panoramica["riepilogo"]["porte_libere"], 1)
        self.assertEqual([p["prefisso"] for p in panoramica["racks"][0]["porte_libere"]], ["A0.3"])
        dettaglio = rete_switch.dettaglio_rack(self.rack)
        self.assertEqual([b["titolo"] for b in dettaglio["switch"]], ["A0.1", "A0.2"])
        self.assertEqual({ep.id for ep in dettaglio["orfani"]}, {self.ep4.id, self.ep5.id})
        resp = self.client.get(reverse("assets:asset_view", args=[self.pc[1].id]))
        self.assertContains(resp, reverse("assets:rete_rack_detail", args=[self.rack.id]))
        self.assertContains(resp, "SYN-SW-M2")

    def test_switch_senza_membro_prende_le_porte_libere(self):
        self._colloca(self.sw2, rack=str(self.rack.id), membro="2")
        self._colloca(self.sw1, rack=str(self.rack.id), membro="")
        risolti = rete_switch.collegamenti([self.ep1, self.ep2, self.ep4])
        self.assertEqual(risolti[self.ep1.id].switch, self.sw1)
        self.assertEqual(risolti[self.ep2.id].switch, self.sw2)
        self.assertEqual(risolti[self.ep4.id].switch, self.sw1)

    def test_collocazione_doppia_o_senza_prefisso_rifiutata(self):
        self._colloca(self.sw1, rack=str(self.rack.id), membro="1")
        self._colloca(self.sw2, rack=str(self.rack.id), membro="1")
        self.sw2.refresh_from_db()
        self.assertIsNone(self.sw2.rack_id)
        self._colloca(self.sw2, rack="", membro="2", prefisso="")
        self.sw2.refresh_from_db()
        self.assertEqual(self.sw2.switch_membro, "")
        self._colloca(self.sw2, rack=str(self.rack.id), membro="x")
        self.sw2.refresh_from_db()
        self.assertIsNone(self.sw2.rack_id)

    def test_pagine_crea_modifica_elimina(self):
        self._colloca(self.sw1, rack=str(self.rack.id), membro="1")
        resp = self.client.get(reverse("assets:rete_rack"))
        self.assertContains(resp, "Armadio sintetico")
        self.assertContains(resp, "A0.1")
        self.assertContains(resp, "A0.2 · 1")  # porte senza switch
        resp = self.client.get(reverse("assets:rete_rack_detail", args=[self.rack.id]))
        self.assertContains(resp, "SYN-SW-M1")
        self.assertContains(resp, "SYN-PCR-3")  # orfano del membro 3
        url = reverse("assets:rete_rack")
        resp = self.client.post(url, {"azione": "salva", "codice": "r1", "nome": "Armadio due", "prefisso_porte": "a1"})
        self.assertEqual(resp.status_code, 302)
        nuovo = RackRete.objects.get(codice="R1")
        self.assertEqual(nuovo.prefisso_porte, "A1")
        resp = self.client.post(url, {"azione": "salva", "codice": "R2", "nome": "Doppione", "prefisso_porte": "A0"})
        self.assertContains(resp, "Già usato dal rack R0")
        resp = self.client.post(url, {"azione": "salva", "rack": str(nuovo.id), "codice": "R1", "nome": "Rinominato", "prefisso_porte": "", "torna": str(nuovo.id)})
        self.assertRedirects(resp, reverse("assets:rete_rack_detail", args=[nuovo.id]), fetch_redirect_response=False)
        nuovo.refresh_from_db()
        self.assertEqual((nuovo.nome, nuovo.prefisso_porte), ("Rinominato", ""))
        self.client.post(url, {"azione": "elimina", "rack": str(self.rack.id)})
        self.sw1.refresh_from_db()
        self.assertIsNone(self.sw1.rack_id)
        self.assertFalse(RackRete.objects.filter(pk=self.rack.id).exists())

    def test_senza_permesso_non_crea(self):
        self.client.force_login(_user("rack.base"))
        self.client.post(reverse("assets:rete_rack"), {"azione": "salva", "codice": "RX", "nome": "No"})
        self.assertFalse(RackRete.objects.filter(codice="RX").exists())
