"""Indirizzi IP da DHCP e DNS di Windows Server (assets.services.rete_windows). PowerShell sempre simulato, dati sintetici."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import AmbitoDhcp, Asset, AssetEndpoint, DispositivoIntune, IndirizzoRete
from assets.services import rete_windows as svc
from assets.services.fonti_dispositivo import per_asset
from assets.services.identity_match import REASON_MAC, match_hub_asset
from core.models import RoutePermissionBinding, UserOnboarding

ORA = datetime(2026, 10, 23, 9, 0, tzinfo=dt_timezone.utc)


def _scope(scope_id="192.168.10.0", name="Uffici", in_use=230, free=20, pct=92.0):
    return {"scope_id": scope_id, "name": name, "mask": "255.255.255.0", "start": "192.168.10.10", "end": "192.168.10.250",
            "state": "Active", "lease_hours": 192.0, "in_use": in_use, "free": free, "pct": pct}


def _lease(ip="192.168.10.21", mac="AA-BB-CC-00-00-01", host="pc-sint-01.dominio.local", state="Active"):
    return {"ip": ip, "mac": mac, "host": host, "state": state, "scope_id": "192.168.10.0", "expiry": "2026-10-31T09:00:00Z"}


def _dhcp(leases=None, scopes=None):
    return {"scopes": scopes if scopes is not None else [_scope()], "leases": leases if leases is not None else [_lease()]}


class SalvataggioTests(TestCase):
    def test_dhcp_crea_ambiti_e_indirizzi(self):
        esito = svc.salva_dhcp("dhcp-sint", _dhcp([_lease(), _lease("192.168.10.5", "aa:bb:cc:00:00:05", "stampante", "ActiveReservation")]), ORA)
        self.assertEqual((esito["ambiti"], esito["indirizzi"]), (1, 2))
        ambito = AmbitoDhcp.objects.get()
        self.assertEqual(ambito.percentuale_uso, 92.0)
        riga = IndirizzoRete.objects.get(ip="192.168.10.21")
        self.assertEqual(riga.mac, "aa:bb:cc:00:00:01")
        self.assertEqual(riga.tipo, IndirizzoRete.TIPO_LEASE)
        self.assertEqual(riga.ambito, ambito)
        self.assertTrue(riga.nel_dhcp)
        self.assertEqual(IndirizzoRete.objects.get(ip="192.168.10.5").tipo, IndirizzoRete.TIPO_PRENOTAZIONE)

    def test_indirizzo_sparito_resta_ma_non_presente(self):
        svc.salva_dhcp("dhcp-sint", _dhcp([_lease(), _lease("192.168.10.22", "aa:bb:cc:00:00:02", "pc-02")]), ORA)
        esito = svc.salva_dhcp("dhcp-sint", _dhcp([_lease()], scopes=[]), ORA + timedelta(hours=1))
        self.assertEqual(esito["spariti"], 1)
        riga = IndirizzoRete.objects.get(ip="192.168.10.22")
        self.assertFalse(riga.presente)
        self.assertFalse(AmbitoDhcp.objects.get().presente)

    def test_dns_nomi_statici_vecchi_e_diversi(self):
        svc.salva_dhcp("dhcp-sint", _dhcp([_lease(host="pc-sint-01.dominio.local")]), ORA)
        svc.salva_dns([
            {"name": "pc-vecchio", "zone": "dominio.local", "ip": "192.168.10.21", "stamp": "2026-10-20T08:00:00Z"},
            {"name": "srv-sint", "zone": "dominio.local", "ip": "192.168.10.2", "stamp": None},
            {"name": "pc-dimenticato", "zone": "dominio.local", "ip": "192.168.10.99", "stamp": "2026-08-01T08:00:00Z"},
            {"name": "DomainDnsZones", "zone": "dominio.local", "ip": "192.168.10.2", "stamp": None},
            {"name": "@", "zone": "dominio.local", "ip": "192.168.10.2", "stamp": None},
        ], ORA)
        pc = IndirizzoRete.objects.get(ip="192.168.10.21")
        self.assertEqual(pc.nomi_dns, ["pc-vecchio.dominio.local"])
        self.assertTrue(pc.nome_diverso)
        srv = IndirizzoRete.objects.get(ip="192.168.10.2")
        self.assertEqual(srv.tipo, IndirizzoRete.TIPO_DNS)
        self.assertTrue(srv.dns_statico)
        self.assertEqual(srv.nomi_dns, ["dominio.local", "srv-sint.dominio.local"])
        self.assertTrue(svc.dns_vecchio(IndirizzoRete.objects.get(ip="192.168.10.99"), ORA))
        self.assertFalse(svc.dns_vecchio(srv, ORA))
        self.assertFalse(svc.dns_vecchio(pc, ORA))  # ha un lease: non è un record rimasto

    def test_stesso_nome_corto_non_e_diverso(self):
        svc.salva_dhcp("dhcp-sint", _dhcp([_lease(host="PC-SINT-01")]), ORA)
        svc.salva_dns([{"name": "pc-sint-01", "zone": "dominio.local", "ip": "192.168.10.21", "stamp": "2026-10-22T08:00:00Z"}], ORA)
        self.assertFalse(IndirizzoRete.objects.get().nome_diverso)


class AbbinamentoTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="PC-RETE-1", name="PC ufficio tecnico", asset_type=Asset.TYPE_PC)

    def test_mac_del_punto_rete(self):
        AssetEndpoint.objects.create(asset=self.asset, endpoint_name="LAN", mac="AA-BB-CC-00-00-01")
        asset, motivo = match_hub_asset(mac="aa:bb:cc:00:00:01")
        self.assertEqual((asset, motivo), (self.asset, REASON_MAC))

    def test_mac_di_intune_senza_separatori(self):
        DispositivoIntune.objects.create(intune_id="i-1", nome="X", mac_ethernet="AABBCC000001", asset=self.asset)
        asset, motivo = match_hub_asset(mac="AA-BB-CC-00-00-01")
        self.assertEqual((asset, motivo), (self.asset, REASON_MAC))

    def test_proposte_e_non_censiti(self):
        AssetEndpoint.objects.create(asset=self.asset, endpoint_name="LAN", mac="aa:bb:cc:00:00:01")
        svc.salva_dhcp("dhcp-sint", _dhcp([_lease(), _lease("192.168.10.30", "aa:bb:cc:00:00:30", "sconosciuto")]), ORA)
        self.assertEqual(svc.aggiorna_proposte(), 2)
        proposto = IndirizzoRete.objects.get(ip="192.168.10.21")
        self.assertEqual((proposto.asset_proposto, proposto.motivo_proposta), (self.asset, REASON_MAC))
        data = svc.pagina("non_censiti", ora=ORA)
        self.assertEqual([r.ip for r in data["righe"]], ["192.168.10.30"])
        conteggi = {f["code"]: f["count"] for f in data["filtri"]}
        self.assertEqual((conteggi["da_collegare"], conteggi["non_censiti"]), (1, 1))
        self.assertTrue(data["ambiti"][0].pieno)


class PowerShellTests(TestCase):
    def _proc(self, code=0, out=b"", err=b""):
        return MagicMock(returncode=code, stdout=out, stderr=err)

    def test_server_e_zone_solo_nelle_variabili_d_ambiente(self):
        out = json.dumps({"scopes": _scope(), "leases": _lease()}).encode()
        with patch("assets.services.rete_windows.subprocess.run", return_value=self._proc(out=out)) as run:
            dati = svc.leggi_dhcp("dhcp-sint.dominio.local")
        comando = run.call_args.args[0]
        self.assertNotIn("dhcp-sint", " ".join(comando))
        self.assertEqual(run.call_args.kwargs["env"]["PN_RETE_SERVER"], "dhcp-sint.dominio.local")
        # Un solo elemento: ConvertTo-Json dà un oggetto, non un elenco.
        self.assertEqual((len(dati["scopes"]), len(dati["leases"])), (1, 1))

    def test_nome_server_non_valido(self):
        with patch("assets.services.rete_windows.subprocess.run") as run:
            with self.assertRaises(svc.ReteError):
                svc.leggi_dhcp("dhcp; Remove-Item C:\\")
            with self.assertRaises(svc.ReteError):
                svc.leggi_dns("dns-sint", ["zona$(whoami)"])
        run.assert_not_called()

    def test_errori_spiegati(self):
        casi = [
            (b"Access is denied. (Exception from HRESULT: 0x80070005)", "DHCP Users"),
            (b"Import-Module : The specified module 'DhcpServer' was not loaded", "RSAT"),
            (b"Failed to get scopes: The RPC server is unavailable.", "non raggiungibile"),
        ]
        for err, atteso in casi:
            with patch("assets.services.rete_windows.subprocess.run", return_value=self._proc(code=1, err=err)):
                with self.assertRaisesMessage(svc.ReteError, atteso):
                    svc.leggi_dhcp("dhcp-sint")


@override_settings(RETE_DHCP_SERVERS="dhcp-a, dhcp-b", RETE_DNS_SERVER="dns-sint", RETE_DNS_ZONES="dominio.local")
class GiroTests(TestCase):
    def test_un_server_in_errore_non_ferma_gli_altri(self):
        def leggi(server):
            if server == "dhcp-a":
                raise svc.ReteError("Accesso negato")
            return _dhcp()

        with patch.object(svc, "leggi_dhcp", side_effect=leggi), patch.object(svc, "leggi_dns", return_value=[]):
            esito = svc.sincronizza(ORA)
        self.assertFalse(esito["ok"])
        self.assertEqual(esito["errori"], ["DHCP dhcp-a: Accesso negato"])
        self.assertIn("dhcp-b", esito["dhcp"])
        self.assertEqual(IndirizzoRete.objects.count(), 1)
        self.assertEqual(svc.ultimo_giro()["errori"], esito["errori"])

    @override_settings(RETE_DHCP_SERVERS="", RETE_DNS_SERVER="", RETE_DNS_ZONES="")
    def test_task_senza_configurazione(self):
        from assets.tasks import run_rete_windows_sync

        self.assertIs(run_rete_windows_sync()["attivo"], False)


class PaginaTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="adm_rete", email="a@a.it", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.client.force_login(self.admin)
        self.asset = Asset.objects.create(asset_tag="PC-RETE-2", name="pc-sint-01", asset_type=Asset.TYPE_PC)
        svc.salva_dhcp("dhcp-sint", _dhcp([_lease(), _lease("192.168.10.30", "aa:bb:cc:00:00:30", "sconosciuto")]), ORA)
        svc.aggiorna_proposte()

    def test_pagina_e_filtro(self):
        resp = self.client.get(reverse("assets:rete_indirizzi"))
        self.assertContains(resp, "192.168.10.21")
        self.assertContains(resp, "Quasi pieno")
        self.assertContains(resp, "non censito")
        resp = self.client.get(reverse("assets:rete_indirizzi") + "?f=non_censiti")
        self.assertContains(resp, "192.168.10.30")
        self.assertNotContains(resp, "192.168.10.21")

    def test_riconciliazione_e_visto_da(self):
        url = reverse("assets:it_reconciliation")
        resp = self.client.get(url)
        self.assertContains(resp, "Rete (DHCP)")
        riga = IndirizzoRete.objects.get(ip="192.168.10.21")
        self.client.post(url, {"row": f"rete:{riga.pk}:{self.asset.pk}"})
        riga.refresh_from_db()
        self.assertEqual(riga.asset, self.asset)
        fonti = {f["nome"]: f for f in per_asset(self.asset, profilo="workstation", oggi=ORA.date())}
        self.assertEqual(fonti["Rete"]["dettaglio"], "192.168.10.21")

    def test_binding_acl_della_pagina(self):
        self.assertTrue(RoutePermissionBinding.objects.filter(path_pattern="/assets/rete/", is_active=True).exists())



class ConfigurazioneDalPortaleTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="adm_rete_cfg", email="a@a.it", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.client.force_login(self.admin)
        self.url = reverse("assets:rete_indirizzi")

    def test_salva_e_valida(self):
        self.assertEqual(svc.salva_config("dc01, dc02", "dc01", "dominio.local"), [])
        cfg = svc.config()
        self.assertEqual((cfg["dhcp"], cfg["dns"], cfg["zone"], cfg["fonte"]), (["dc01", "dc02"], "dc01", ["dominio.local"], "portale"))
        self.assertTrue(svc.salva_config("dc01; Remove-Item", "", ""))
        self.assertTrue(svc.salva_config("", "dc01", ""))  # DNS senza zone
        self.assertEqual(svc.config()["dhcp"], ["dc01", "dc02"])  # gli errori non salvano niente

    @override_settings(RETE_DHCP_SERVERS="dhcp-env", RETE_DNS_SERVER="", RETE_DNS_ZONES="")
    def test_il_portale_vince_sul_env(self):
        self.assertEqual((svc.config()["dhcp"], svc.config()["fonte"]), (["dhcp-env"], "env"))
        svc.salva_config("dhcp-portale", "", "")
        self.assertEqual(svc.config()["dhcp"], ["dhcp-portale"])

    def test_pagina_salva_e_leggi(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Server DHCP e DNS")
        self.client.post(self.url, {"azione": "salva", "dhcp": "dc01", "dns": "", "zone": ""})
        self.assertEqual(svc.config()["dhcp"], ["dc01"])
        with patch("security.services.letture.accoda", return_value=(True, "In coda.")) as accoda:
            self.client.post(self.url, {"azione": "leggi"})
        accoda.assert_called_once()
        self.assertEqual(accoda.call_args.args[0], "rete_windows")

    def test_solo_amministratori(self):
        utente = get_user_model().objects.create_user(username="rete_nessuno", password="x")
        UserOnboarding.objects.create(user=utente, completed=True)
        self.client.force_login(utente)
        with patch("assets.views_rete.user_can_modulo_action", return_value=False):
            self.assertNotIn(b"Server DHCP e DNS", self.client.get(self.url).content)  # 403 dall'ACL o riquadro nascosto
            self.client.post(self.url, {"azione": "salva", "dhcp": "dc09", "dns": "", "zone": ""})
        self.assertNotEqual(svc.config()["dhcp"], ["dc09"])


class CorrelazioneTests(TestCase):
    """IP fissi, abbinamento da altre fonti, switch, antivirus e memoria dei MAC (dati sintetici)."""

    def setUp(self):
        self.pc = Asset.objects.create(asset_tag="PC-COR-1", name="pc-cor-01", asset_type=Asset.TYPE_PC)

    def test_ip_fisso_solo_dns_e_non_censito(self):
        svc.salva_dns([{"name": "nas-ignoto", "zone": "dominio.local", "ip": "192.168.10.40", "stamp": None},
                       {"name": "pc-dimenticato", "zone": "dominio.local", "ip": "192.168.10.99", "stamp": "2026-08-01T08:00:00Z"}], ORA)
        svc.aggiorna_proposte()
        data = svc.pagina("non_censiti", ora=ORA)
        self.assertEqual([r.ip for r in data["righe"]], ["192.168.10.40"])  # il record DNS vecchio non conta

    def test_proposta_dal_secondo_nome_dns(self):
        svc.salva_dns([{"name": "alias-stampa", "zone": "dominio.local", "ip": "192.168.10.41", "stamp": None},
                       {"name": "pc-cor-01", "zone": "dominio.local", "ip": "192.168.10.41", "stamp": None}], ORA)
        svc.aggiorna_proposte()
        self.assertEqual(IndirizzoRete.objects.get(ip="192.168.10.41").asset_proposto, self.pc)

    def test_mac_di_watchguard_e_nome_collegato_in_intune(self):
        from assets.services.identity_match import REASON_NAME_LINKED
        from security.models import WatchGuardDispositivo

        WatchGuardDispositivo.objects.create(device_id="wg-1", host="pc-cor-01", hub_asset=self.pc,
                                             mac="aa:bb:cc:00:00:07 aa:bb:cc:00:00:08")
        self.assertEqual(match_hub_asset(mac="AA-BB-CC-00-00-08"), (self.pc, REASON_MAC))
        altro = Asset.objects.create(asset_tag="PC-COR-2", name="Portatile commerciale", asset_type=Asset.TYPE_NOTEBOOK)
        DispositivoIntune.objects.create(intune_id="i-cor", nome="NB-COMM-07", asset=altro, presente=True)
        self.assertEqual(match_hub_asset(hostname="nb-comm-07.dominio.local"), (altro, REASON_NAME_LINKED))

    def test_switch_watchguard_senza_agente_e_pc_senza_antivirus(self):
        from contatori.models import DispositivoSNMP, MacPortaSwitch
        from security.models import SoftwareInstallation, WatchGuardDispositivo

        sw = DispositivoSNMP.objects.create(nome="SW-SINT", host="192.0.2.2")
        MacPortaSwitch.objects.create(dispositivo=sw, mac="aa:bb:cc:00:00:01", porta="Gi1/0/12", vlan=10,
                                      mac_sulla_porta=1, letto_il=ORA)
        MacPortaSwitch.objects.create(dispositivo=sw, mac="aa:bb:cc:00:00:01", porta="Te1/1/1", mac_sulla_porta=40, letto_il=ORA)
        WatchGuardDispositivo.objects.create(device_id="unmanaged:1", gestito=False, host="ignoto", mac="aa:bb:cc:00:00:30")
        SoftwareInstallation.objects.create(dedup_key="k-altro", source_kind="watchguard", host="altro", vendor="acme",
                                            product="x", product_raw="x", version_raw="1", fonti=["watchguard"])
        svc.salva_dhcp("dhcp-sint", _dhcp([_lease(), _lease("192.168.10.30", "aa:bb:cc:00:00:30", "sconosciuto")]), ORA)
        IndirizzoRete.objects.filter(ip="192.168.10.21").update(asset=self.pc)
        righe = {r.ip: r for r in svc.pagina(ora=ORA)["righe"]}
        pc, ignoto = righe["192.168.10.21"], righe["192.168.10.30"]
        self.assertEqual((pc.switch.dispositivo.nome, pc.switch.porta), ("SW-SINT", "Gi1/0/12"))  # la porta d'accesso
        self.assertEqual(pc.senza_protezione, "PC del registro senza WatchGuard né Defender")
        self.assertEqual(ignoto.senza_protezione, "WatchGuard lo vede in rete senza agente")
        self.assertIn({"nome": "WatchGuard", "stato": "ko", "titolo": "In rete senza agente WatchGuard"}, ignoto.fonti)
        conteggi = {f["code"]: f["count"] for f in svc.pagina(ora=ORA)["filtri"]}
        self.assertEqual(conteggi["senza_protezione"], 2)

    def test_senza_dati_antivirus_non_si_giudica(self):
        svc.salva_dhcp("dhcp-sint", _dhcp(), ORA)
        IndirizzoRete.objects.update(asset=self.pc)
        self.assertEqual(svc.pagina(ora=ORA)["righe"][0].senza_protezione, "")

    def test_mac_di_asset_normalizza_intune_e_usa_il_dhcp(self):
        from contatori.tabella_mac import mac_di_asset

        DispositivoIntune.objects.create(intune_id="i-norm", nome="X", mac_ethernet="AABBCC0000AA", asset=self.pc)
        IndirizzoRete.objects.create(ip="192.168.10.50", mac="aa:bb:cc:00:00:bb", asset=self.pc, nel_dhcp=True)
        self.assertEqual(mac_di_asset(self.pc), {"aa:bb:cc:00:00:aa", "aa:bb:cc:00:00:bb"})


@override_settings(RETE_DHCP_SERVERS="dhcp-sint", RETE_DNS_SERVER="", RETE_DNS_ZONES="")
class DispositivoNuovoTests(TestCase):
    def _giro(self, leases, ora):
        with patch.object(svc, "leggi_dhcp", return_value=_dhcp(leases)):
            return svc.sincronizza(ora)

    def test_prima_lettura_niente_poi_un_evento_per_mac(self):
        from security.models import SecurityEventRecord

        self.assertEqual(self._giro([_lease()], ORA)["segnalati_soc"], 0)  # prima lettura: tutto «nuovo», niente al SOC
        nuovi = [_lease(), _lease("192.168.10.60", "00:1b:21:00:00:60", "ignoto"),
                 _lease("192.168.10.61", "da:a1:19:00:00:61", "telefono")]  # MAC privato: escluso
        esito = self._giro(nuovi, ORA + timedelta(hours=1))
        self.assertEqual((esito["mac_nuovi"], esito["segnalati_soc"]), (2, 1))
        evento = SecurityEventRecord.objects.get(event_type="rete_dispositivo_nuovo")
        self.assertEqual(evento.payload["dettaglio"]["ip"], "192.168.10.60")
        self.assertEqual(self._giro(nuovi, ORA + timedelta(hours=2))["segnalati_soc"], 0)  # già visto: mai due volte

    def test_mac_casuale(self):
        self.assertTrue(svc.mac_casuale("da:a1:19:00:00:61"))
        self.assertFalse(svc.mac_casuale("00:1b:21:00:00:60"))


class AzioniRigaTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="adm_rete_az", email="a@a.it", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.client.force_login(self.admin)
        self.asset = Asset.objects.create(asset_tag="PC-AZ-1", name="pc-sint-01", asset_type=Asset.TYPE_PC)
        svc.salva_dhcp("dhcp-sint", _dhcp([_lease(), _lease("192.168.10.30", "aa:bb:cc:00:00:30", "sconosciuto")]), ORA)
        svc.aggiorna_proposte()
        self.riga = IndirizzoRete.objects.get(ip="192.168.10.21")
        self.url = reverse("assets:rete_indirizzi")

    def test_conferma_e_scollega(self):
        self.assertContains(self.client.get(self.url), 'value="collega"')
        self.client.post(self.url, {"azione": "collega", "riga": self.riga.pk, "asset": self.asset.pk})
        self.riga.refresh_from_db()
        self.assertEqual(self.riga.asset, self.asset)
        self.client.post(self.url, {"azione": "scollega", "riga": self.riga.pk})
        self.riga.refresh_from_db()
        self.assertIsNone(self.riga.asset)

    def test_conferma_rifiutata_se_la_proposta_e_cambiata(self):
        altro = Asset.objects.create(asset_tag="PC-AZ-2", name="altro", asset_type=Asset.TYPE_PC)
        self.client.post(self.url, {"azione": "collega", "riga": self.riga.pk, "asset": altro.pk})
        self.riga.refresh_from_db()
        self.assertIsNone(self.riga.asset)

    def test_crea_asset_precompilato_e_collegato(self):
        from django.test import RequestFactory

        from assets.views.asset_crud import _collega_indirizzo_creato

        ignoto = IndirizzoRete.objects.get(ip="192.168.10.30")
        self.assertContains(self.client.get(self.url + "?f=non_censiti"), f"?da_rete={ignoto.pk}")
        resp = self.client.get(reverse("assets:asset_create") + f"?da_rete={ignoto.pk}")
        self.assertContains(resp, 'value="192.168.10.30"')
        self.assertContains(resp, 'value="aa:bb:cc:00:00:30"')
        nuovo = Asset.objects.create(asset_tag="NEW-1", name="sconosciuto", asset_type=Asset.TYPE_HW)
        req = RequestFactory().post("/")
        req.user = self.admin
        _collega_indirizzo_creato(req, ignoto, nuovo)
        ignoto.refresh_from_db()
        self.assertEqual(ignoto.asset, nuovo)

    def test_kpi_ambiti_in_italiano_ed_excel(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Indirizzi attivi")
        self.assertContains(resp, "Senza antivirus")
        self.assertContains(resp, "Quasi pieno")
        xlsx = self.client.get(self.url + "?f=tutti&export=xlsx")
        self.assertEqual(xlsx["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_vista_nel_soc_e_nella_scheda_dispositivi(self):
        resp = self.client.get(reverse("security:rete_indirizzi"))
        self.assertContains(resp, "Rete (IP)")
        self.assertContains(resp, "192.168.10.30")
        self.assertNotContains(resp, 'id="config-rete"')  # la configurazione resta in Asset
        self.client.post(reverse("security:rete_indirizzi"), {"azione": "collega", "riga": self.riga.pk, "asset": self.asset.pk})
        self.riga.refresh_from_db()
        self.assertEqual(self.riga.asset, self.asset)
        DispositivoIntune.objects.create(intune_id="i-az", nome="pc-sint-01", asset=self.asset, presente=True)
        self.assertContains(self.client.get(reverse("security:pc_copertura")), "192.168.10.21")
