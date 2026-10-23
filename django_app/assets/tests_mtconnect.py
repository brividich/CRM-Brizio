"""Stato delle CNC dagli agent MTConnect (assets.services.mtconnect). Agent sempre simulato, dati sintetici."""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from assets.models import Asset, AssetMeter, CollegamentoMTConnect, PeriodoStatoMacchina, WorkMachine
from assets.services import mtconnect as svc
from assets.views._helpers_c import _plant_alert_level
from core.models import RoutePermissionBinding, UserOnboarding

ORA = datetime(2026, 10, 20, 8, 0, tzinfo=dt_timezone.utc)  # nel passato: i contatori rifiutano le letture future
NS = "urn:mtconnect.org:MTConnectStreams:1.3"


def _current(execution="ACTIVE", availability="AVAILABLE", condition="<Normal type=\"SYSTEM\"/>", seconds="36000",
             parts="120", estop="ARMED", device="CNC-SINT-01"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<MTConnectStreams xmlns="{NS}">
  <Header creationTime="2026-10-23T08:00:00Z" instanceId="1" nextSequence="10"/>
  <Streams>
    <DeviceStream name="{device}" uuid="sint-001">
      <ComponentStream component="Device" name="{device}">
        <Events>
          <Availability dataItemId="avail" timestamp="2026-10-23T07:00:00Z">{availability}</Availability>
          <EmergencyStop dataItemId="estop" timestamp="2026-10-23T07:00:00Z">{estop}</EmergencyStop>
        </Events>
        <Samples>
          <EquipmentTimer dataItemId="t_pow" subType="POWERED" timestamp="2026-10-23T08:00:00Z">90000</EquipmentTimer>
          <EquipmentTimer dataItemId="t_op" subType="OPERATING" timestamp="2026-10-23T08:00:00Z">{seconds}</EquipmentTimer>
        </Samples>
      </ComponentStream>
      <ComponentStream component="Path" name="path1">
        <Events>
          <Execution dataItemId="exec1" timestamp="2026-10-23T07:50:00Z">READY</Execution>
          <Execution dataItemId="exec2" timestamp="2026-10-23T07:55:00Z">{execution}</Execution>
          <ControllerMode dataItemId="mode" timestamp="2026-10-23T07:00:00Z">AUTOMATIC</ControllerMode>
          <Program dataItemId="prog" timestamp="2026-10-23T07:30:00Z">O1234</Program>
          <PartCount dataItemId="pc" subType="ALL" timestamp="2026-10-23T07:59:00Z">{parts}</PartCount>
          <PartCount dataItemId="pt" subType="TARGET" timestamp="2026-10-23T07:00:00Z">500</PartCount>
          <Line dataItemId="line" timestamp="2026-10-23T07:59:00Z">UNAVAILABLE</Line>
        </Events>
        <Condition>{condition}</Condition>
      </ComponentStream>
    </DeviceStream>
  </Streams>
</MTConnectStreams>""".encode()


PROBE = """<?xml version="1.0"?><MTConnectDevices xmlns="urn:mtconnect.org:MTConnectDevices:1.3"><Devices>
<Device name="CNC-SINT-01" uuid="sint-001"><DataItems><DataItem type="AVAILABILITY" id="avail"/></DataItems>
<Components><Path id="p"><DataItems><DataItem type="EXECUTION" id="exec"/><DataItem type="PART_COUNT" id="pc"/></DataItems></Path></Components>
</Device></Devices></MTConnectDevices>""".encode()


class LetturaTests(TestCase):
    def test_dati_utili(self):
        dati = svc.leggi_current(_current())
        self.assertEqual(dati["dispositivo"], "CNC-SINT-01")
        self.assertEqual(dati["esecuzione"], "ACTIVE")  # ACTIVE vince su READY dell'altro path
        self.assertEqual(dati["programma"], "O1234")
        self.assertEqual(dati["ore"], Decimal("10.00"))  # OPERATING prima di POWERED
        self.assertEqual(dati["pezzi"], Decimal("120"))  # TARGET ignorato
        self.assertEqual(svc.stato_da(dati), "in_lavoro")

    def test_stati(self):
        self.assertEqual(svc.stato_da(svc.leggi_current(_current(availability="UNAVAILABLE"))), "spenta")
        self.assertEqual(svc.stato_da(svc.leggi_current(_current(execution="FEED_HOLD"))), "ferma")
        self.assertEqual(svc.stato_da(svc.leggi_current(_current(execution="READY"))), "pronta")
        self.assertEqual(svc.stato_da(svc.leggi_current(_current(estop="TRIGGERED"))), "emergenza")
        fault = '<Fault type="SYSTEM" nativeCode="1010" timestamp="2026-10-23T07:58:00Z">Lubrificazione insufficiente</Fault>'
        dati = svc.leggi_current(_current(condition=fault))
        self.assertEqual(svc.stato_da(dati), "allarme")
        self.assertEqual(dati["allarmi"][0], {"livello": "allarme", "tipo": "SYSTEM", "codice": "1010",
                                              "testo": "Lubrificazione insufficiente", "dal": "2026-10-23T07:58:00Z"})
        warn = '<Warning type="TEMPERATURE">Mandrino caldo</Warning>'
        self.assertEqual(svc.stato_da(svc.leggi_current(_current(condition=warn))), "in_lavoro")

    def test_dispositivo_scelto_e_assente(self):
        self.assertEqual(svc.leggi_current(_current(), "CNC-SINT-01")["dispositivo"], "CNC-SINT-01")
        with self.assertRaisesMessage(svc.MTConnectError, "presenti: CNC-SINT-01"):
            svc.leggi_current(_current(), "ALTRA")

    def test_errore_dell_agent_e_xml_pericoloso(self):
        err = b'<MTConnectError xmlns="urn:mtconnect.org:MTConnectError:1.3"><Errors><Error errorCode="NO_DEVICE">Device non trovato</Error></Errors></MTConnectError>'
        with self.assertRaisesMessage(svc.MTConnectError, "Device non trovato"):
            svc.leggi_current(err)
        bomba = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><MTConnectStreams>&a;</MTConnectStreams>'
        with self.assertRaisesMessage(svc.MTConnectError, "XML non valido"):
            svc.leggi_current(bomba)

    def test_probe(self):
        self.assertEqual(svc.leggi_probe(PROBE), [{"nome": "CNC-SINT-01", "uuid": "sint-001",
                                                   "tipi": ["AVAILABILITY", "EXECUTION", "PART_COUNT"]}])


class IndirizziTests(TestCase):
    def test_solo_rete_interna(self):
        self.assertEqual(svc.valida_url("http://10.0.5.21:5000/"), "http://10.0.5.21:5000")
        self.assertEqual(svc.valida_url("http://127.0.0.1:5000"), "http://127.0.0.1:5000")
        for url in ("http://8.8.8.8:5000", "ftp://10.0.5.21", "http://utente:pw@10.0.5.21", "http://10.0.5.21/?x=1", "10.0.5.21"):
            with self.assertRaises(svc.MTConnectError, msg=url):
                svc.valida_url(url)

    def test_nome_dispositivo(self):
        self.assertEqual(svc._percorso("CNC-01", "current"), "/CNC-01/current")
        with self.assertRaises(svc.MTConnectError):
            svc._percorso("../probe", "current")


class _Macchina(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="CNC-MTC-1", name="Fresa sintetica", asset_type=Asset.TYPE_CNC)
        WorkMachine.objects.create(asset=self.asset, source_key="mtc-sint-1", cnc_controlled=True)
        self.ore = AssetMeter.objects.create(asset=self.asset, meter_type=AssetMeter.METER_HOURS, current_value=Decimal("1000"))
        self.cicli = AssetMeter.objects.create(asset=self.asset, meter_type=AssetMeter.METER_CYCLES, current_value=Decimal("5000"))
        self.coll = CollegamentoMTConnect.objects.create(asset=self.asset, url_agent="http://10.0.5.21:5000",
                                                         contatore_ore=self.ore, contatore_pezzi=self.cicli)


class AggiornamentoTests(_Macchina):
    def test_periodi_di_stato(self):
        svc.applica_lettura(self.coll, svc.leggi_current(_current()), ora=ORA)
        svc.applica_lettura(self.coll, svc.leggi_current(_current()), ora=ORA + timedelta(minutes=2))
        svc.applica_lettura(self.coll, svc.leggi_current(_current(execution="READY")), ora=ORA + timedelta(minutes=90))
        svc.applica_lettura(self.coll, None, "Agent non raggiungibile (ConnectTimeout).", ora=ORA + timedelta(minutes=92))
        periodi = list(PeriodoStatoMacchina.objects.order_by("dal").values_list("stato", "al"))
        self.assertEqual([p[0] for p in periodi], ["in_lavoro", "pronta", "non_raggiungibile"])
        self.assertIsNone(periodi[-1][1])
        self.coll.refresh_from_db()
        self.assertEqual(self.coll.stato, "non_raggiungibile")
        self.assertEqual(self.coll.letto_il, ORA + timedelta(minutes=90))  # l'errore non sposta l'ultima lettura buona
        self.assertEqual(svc.ore_in_lavoro_oggi(self.coll, ORA + timedelta(minutes=95)), Decimal("1.5"))

    def test_contatori_per_differenza_al_massimo_ogni_ora(self):
        svc.applica_lettura(self.coll, svc.leggi_current(_current(seconds="36000", parts="100")), ora=ORA)  # base
        self.ore.refresh_from_db()
        self.assertEqual(self.ore.current_value, Decimal("1000"))
        svc.applica_lettura(self.coll, svc.leggi_current(_current(seconds="37800", parts="110")), ora=ORA + timedelta(minutes=30))
        self.ore.refresh_from_db()
        self.assertEqual(self.ore.current_value, Decimal("1000.50"))  # prima registrazione: read_at vuoto
        svc.applica_lettura(self.coll, svc.leggi_current(_current(seconds="39600", parts="5")), ora=ORA + timedelta(minutes=40))
        self.ore.refresh_from_db()
        self.assertEqual(self.ore.current_value, Decimal("1000.50"))  # meno di un'ora: accumulato
        svc.applica_lettura(self.coll, svc.leggi_current(_current(seconds="41400", parts="15")), ora=ORA + timedelta(minutes=95))
        self.ore.refresh_from_db()
        self.cicli.refresh_from_db()
        self.assertEqual(self.ore.current_value, Decimal("1001.50"))
        # 100→110 (+10), azzerato a 5 (+5), poi 15 (+10): 25 pezzi, il contatore non scende mai.
        self.assertEqual(self.cicli.current_value, Decimal("5025"))
        self.assertEqual(self.ore.source, AssetMeter.SOURCE_MTCONNECT)

    def test_giro_con_un_agent_giu(self):
        altro = Asset.objects.create(asset_tag="CNC-MTC-2", name="Tornio sintetico", asset_type=self.asset.asset_type)
        CollegamentoMTConnect.objects.create(asset=altro, url_agent="http://10.0.5.22:5000")

        def scarica(url, dispositivo="", risorsa="current"):
            if url.endswith(".22:5000"):
                raise svc.MTConnectError("Agent non raggiungibile (ConnectTimeout).")
            return _current()

        with patch.object(svc, "scarica", side_effect=scarica):
            esito = svc.leggi_tutti(ORA)
        self.assertEqual(esito, {"collegamenti": 2, "in_lavoro": 1, "non_raggiungibile": 1})

    def test_mappa_e_dato_vecchio(self):
        fault = '<Fault type="SYSTEM" nativeCode="1010">Lubrificazione</Fault>'
        svc.applica_lettura(self.coll, svc.leggi_current(_current(condition=fault)), ora=ORA)
        live = svc.per_mappa([self.asset.pk], ORA + timedelta(minutes=5))[self.asset.pk]
        self.assertEqual(live["stato"], "allarme")
        self.assertEqual(_plant_alert_level({"cnc_alarm": live["stato"] == "allarme"}, open_tickets=2), "alarm")
        vecchio = svc.per_mappa([self.asset.pk], ORA + timedelta(minutes=30))[self.asset.pk]
        self.assertEqual((vecchio["stato"], vecchio["allarmi"]), ("vecchio", []))


class PaginaTests(_Macchina):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="adm_mtc", email="a@a.it", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.client.force_login(self.admin)
        self.url = reverse("assets:mtconnect_collegamenti")

    def test_elenco_e_prova(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Fresa sintetica")
        with patch.object(svc, "scarica", side_effect=lambda url, d="", r="current": PROBE if r == "probe" else _current()):
            resp = self.client.post(self.url, {"azione": "prova", "asset": self.asset.pk, "url_agent": "http://10.0.5.21:5000"})
        self.assertContains(resp, "agent risponde")
        self.assertContains(resp, "10,00 h")

    def test_prova_senza_macchina(self):
        with patch.object(svc, "scarica") as scarica:
            resp = self.client.post(self.url, {"azione": "prova", "url_agent": "http://10.0.5.21:5000"})
        scarica.assert_not_called()
        self.assertContains(resp, "Scegli prima la macchina")

    def test_salva_sospendi_togli(self):
        self.coll.delete()
        self.client.post(self.url, {"azione": "salva", "asset": self.asset.pk, "url_agent": "http://10.0.5.21:5000/",
                                    "usa_ore": "on"})
        coll = CollegamentoMTConnect.objects.get(asset=self.asset)
        self.assertEqual((coll.url_agent, coll.contatore_ore, coll.contatore_pezzi), ("http://10.0.5.21:5000", self.ore, None))
        self.client.post(self.url, {"azione": "sospendi", "collegamento": coll.pk})
        coll.refresh_from_db()
        self.assertFalse(coll.attivo)
        self.client.post(self.url, {"azione": "elimina", "collegamento": coll.pk})
        self.assertFalse(CollegamentoMTConnect.objects.exists())
        self.client.post(self.url, {"azione": "salva", "asset": self.asset.pk, "url_agent": "http://8.8.8.8:5000"})
        self.assertFalse(CollegamentoMTConnect.objects.exists())

    def test_binding_acl(self):
        self.assertTrue(RoutePermissionBinding.objects.filter(path_pattern="/assets/work-machines/mtconnect/", is_active=True).exists())
