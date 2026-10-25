"""Collector CNC: ricerca in rete, ore lette dalla CNC, avviso a ore, CNC da sistemare, IP ammessi,
report di utilizzo. Dati sintetici (indirizzi di documentazione 192.0.2.x)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    AssetMeter,
    AssetMeterHistory,
    CollegamentoMTConnect,
    MeterIngestClient,
    PeriodoStatoMacchina,
    WorkMachine,
)
from assets.services import collector_cnc, mtconnect


def _macchina(tag, nome, serial=None, **extra):
    asset = Asset.objects.create(asset_tag=tag, name=nome, asset_type=Asset.TYPE_WORK_MACHINE, serial_number=serial, **extra)
    WorkMachine.objects.create(asset=asset, source_key=f"mig-{tag}", cnc_controlled=True)
    return asset


class _Pagina(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.admin = get_user_model().objects.create_superuser(username="adm_cnc_mig", email="a@a.it", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.client.force_login(self.admin)
        self.url = reverse("assets:mtconnect_collegamenti")


# --- ore lette dalla CNC -------------------------------------------------------------------------

class OreDallaCncTests(_Pagina):
    def setUp(self):
        super().setUp()
        self.asset = _macchina("CNC-DM9-SINT", "Fresa sintetica", "SN-9")
        self.ore = AssetMeter.objects.create(asset=self.asset, meter_type=AssetMeter.METER_HOURS, current_value=Decimal("90"),
                                             read_at=timezone.now() - timedelta(hours=2))
        self.coll = CollegamentoMTConnect.objects.create(asset=self.asset, fonte="collector_opcua", opcua_host="192.0.2.23", codice="DM9")

    def _stato(self, **extra):
        riga = {"asset_tag": self.asset.asset_tag, "stato": "LAVORO", "dal": (timezone.now() - timedelta(minutes=1)).isoformat(), **extra}
        return collector_cnc.applica_stati([riga])

    def test_il_collector_manda_valore_grezzo_matricola_e_modello(self):
        self.assertEqual(self._stato(ore_lette=360000, matricola="00810001311", modello="bds")["accepted"], 1)
        self.coll.refresh_from_db()
        self.assertEqual((self.coll.ore_grezzo, self.coll.matricola_opcua, self.coll.modello_dati),
                         (Decimal("360000.00"), "00810001311", "bds"))
        self.assertEqual(collector_cnc.unita_effettiva(self.coll), "s")
        self.assertEqual(collector_cnc.ore_dalla_cnc(self.coll), Decimal("100.00"))
        # La config del collector porta la matricola vista dal server e l'unità scelta.
        macchina = collector_cnc.macchine_per(None)[0]
        self.assertEqual((macchina["serial"], macchina["hours_unit"]), ("00810001311", ""))

    def test_il_portale_converte_le_ore_con_l_unita_scelta(self):
        self._stato(ore_lette=6000, modello="umati")
        self.coll.refresh_from_db()
        self.coll.unita_ore = "min"
        self.coll.save()
        esito = collector_cnc.applica_letture([{"asset_tag": self.asset.asset_tag, "meter_type": "HOURS", "value": 6000,
                                                "read_at": timezone.now().isoformat()}])
        self.assertEqual(esito["accepted"], 1, esito)
        self.ore.refresh_from_db()
        self.assertEqual(self.ore.current_value, Decimal("100.00"))  # 6000 minuti, non 6000 ore

    def test_cambio_di_unita_dalla_pagina_ricalcola_il_contatore(self):
        self._stato(ore_lette=1080000, modello="umati")  # umati = ore: il contatore andrebbe a 1.080.000 h
        self.ore.current_value = Decimal("1080000")
        self.ore.save()
        self.client.post(self.url, {"azione": "salva", "fonte": "collector_opcua", "asset": self.asset.pk,
                                    "opcua_host": "192.0.2.23", "opcua_porta": "4840", "codice": "DM9", "unita_ore": "s"})
        self.coll.refresh_from_db()
        self.ore.refresh_from_db()
        self.assertEqual(self.coll.unita_ore, "s")
        self.assertEqual(self.ore.current_value, Decimal("300.00"))
        storia = AssetMeterHistory.objects.filter(meter=self.ore).latest("id")
        self.assertTrue(storia.is_reset)
        self.assertIn("secondi", storia.note)
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Ore: <strong>300 h</strong>", html=False)
        self.assertContains(pagina, "unità scelta a mano")

    def test_fattori_uguali_a_quelli_del_collector(self):
        from assets.collector_cnc.collector import MODELS
        from assets.collector_cnc.portale import UNITA_ORE

        for modello, fattore in collector_cnc.FATTORE_MODELLO.items():
            self.assertAlmostEqual(float(fattore), MODELS[modello]["hours_factor"])
        for unita, fattore in collector_cnc.FATTORE_UNITA.items():
            self.assertAlmostEqual(float(fattore), UNITA_ORE[unita])

    def test_il_collector_usa_l_unita_del_portale(self):
        from types import SimpleNamespace

        from assets.collector_cnc.portale import Portale, fattore_ore

        m = SimpleNamespace(spec={"hours_factor": 1.0}, hours_unit="s", asset_tag="X", state="LAVORO", counters_at=datetime(2026, 10, 1),
                            values={"cnt_operation_time": 7200, "cnt_parts_overall": None})
        self.assertAlmostEqual(fattore_ore(m), 1 / 3600)
        self.assertEqual(Portale.righe_contatori(m)[0]["value"], 2.0)
        m.hours_unit = ""
        self.assertEqual(fattore_ore(m), 1.0)


# --- avviso a ore --------------------------------------------------------------------------------

class AvvisoOreTests(_Pagina):
    def setUp(self):
        super().setUp()
        self.asset = _macchina("CNC-DM6-SINT", "Fresa DMC sintetica")
        self.ore = AssetMeter.objects.create(asset=self.asset, meter_type=AssetMeter.METER_HOURS, current_value=Decimal("1000"),
                                             read_at=timezone.now())
        self.coll = CollegamentoMTConnect.objects.create(asset=self.asset, fonte="collector_opcua", opcua_host="192.0.2.15", codice="DM6")

    def _salva(self, **extra):
        return self.client.post(self.url, {"azione": "salva", "fonte": "collector_opcua", "asset": self.asset.pk,
                                           "opcua_host": "192.0.2.15", "opcua_porta": "4840", "codice": "DM6", **extra})

    def test_livelli(self):
        self.coll.avviso_ore_ogni, self.coll.avviso_ore_da, self.coll.avviso_ore_testo = Decimal("500"), Decimal("600"), "Controllo mandrino"
        self.assertEqual(collector_cnc.avviso_ore(self.coll, Decimal("700"))["livello"], "ok")
        vicino = collector_cnc.avviso_ore(self.coll, Decimal("1060"))
        self.assertEqual(vicino["livello"], "warn")
        self.assertIn("Controllo mandrino: tra 40 h", vicino["messaggio"])
        self.assertIn("superato di 50 h", collector_cnc.avviso_ore(self.coll, Decimal("1150"))["messaggio"])
        self.coll.avviso_ore_ogni = None
        self.assertIsNone(collector_cnc.avviso_ore(self.coll, Decimal("1150")))

    def test_dalla_pagina_parte_dalle_ore_attuali_e_fatto(self):
        self._salva(avviso_ore_ogni="250", avviso_ore_testo="Ingrassaggio guide")
        self.coll.refresh_from_db()
        self.assertEqual((self.coll.avviso_ore_ogni, self.coll.avviso_ore_da), (Decimal("250.00"), Decimal("1000.00")))
        self.ore.current_value = Decimal("1240")
        self.ore.save()
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Ingrassaggio guide: tra 10 h")
        scheda = mtconnect.per_scheda(self.asset.pk)
        self.assertEqual(scheda["avviso_ore"]["livello"], "warn")
        self.client.post(self.url, {"azione": "fatto_ore", "collegamento": self.coll.pk})
        self.coll.refresh_from_db()
        self.assertEqual(self.coll.avviso_ore_da, Decimal("1240.00"))
        # Niente scadenze o ordini di lavoro: è solo un avviso.
        self.assertFalse(self.asset.maintenance_plan_assignments.exists())

    def test_ore_con_la_virgola_e_valori_sbagliati(self):
        self._salva(avviso_ore_ogni="1.250,5", avviso_ore_da="800")
        self.coll.refresh_from_db()
        self.assertEqual((self.coll.avviso_ore_ogni, self.coll.avviso_ore_da), (Decimal("1250.50"), Decimal("800.00")))
        self._salva(avviso_ore_ogni="tante")
        self.coll.refresh_from_db()
        self.assertEqual(self.coll.avviso_ore_ogni, Decimal("1250.50"))  # non salvato
        self._salva(avviso_ore_ogni="")
        self.coll.refresh_from_db()
        self.assertIsNone(self.coll.avviso_ore_ogni)
        self.assertIsNone(self.coll.avviso_ore_da)


# --- CNC da sistemare e IP ammessi -----------------------------------------------------------------

class DaSistemareEIpTests(_Pagina):
    def test_cnc_senza_scheda_macchina(self):
        padre = AssetCategory.objects.create(code="cnc-sint", label="CNC sintetiche")
        AssetCategory.objects.create(code="macchine-cnc-sint", label="Macchine CNC sintetiche", parent=padre,
                                     base_asset_type=Asset.TYPE_WORK_MACHINE)
        persa = Asset.objects.create(asset_tag="CNC-DM16-SINT", name="Fresa DMC 85 sintetica", asset_category=padre)
        Asset.objects.create(asset_tag="CNC-OLD-SINT", name="Fresa dismessa", asset_category=padre, status=Asset.STATUS_RETIRED)
        _macchina("CNC-OK-SINT", "Fresa con scheda")
        Asset.objects.create(asset_tag="PC-SINT-1", name="Notebook", asset_type=Asset.TYPE_PC)
        self.assertEqual(list(collector_cnc.cnc_da_sistemare()), [persa])
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "CNC da sistemare")
        self.assertContains(pagina, reverse("assets:asset_edit", args=[persa.pk]))

    def test_avviso_rete_senza_maschera(self):
        self.assertEqual(collector_cnc.avvisi_ips(["192.0.2.0/24", "192.0.2.50"]), [])
        self.assertIn("192.0.2.0/24", collector_cnc.avvisi_ips(["192.0.2.0"])[0])
        resp = self.client.post(self.url, {"azione": "collector_crea", "nome": "Collector sintetico", "ips": "192.0.2.0", "tutte": "on"},
                                follow=True)
        self.assertEqual(MeterIngestClient.objects.get().allowed_ips, "192.0.2.0")  # avviso, non blocco
        self.assertContains(resp, "senza «/24» ammette solo quell")
        self.assertContains(self.client.get(self.url), "per tutta la rete scrivi 192.0.2.0/24")


# --- cerca le macchine in rete -------------------------------------------------------------------

def _trovato(ip, matricola="", modello="bds", dmg=True, errore="", credenziali=None):
    return {"ip": ip, "porta": 4840, "dmg": dmg, "matricola": matricola, "modello": modello if dmg else "",
            "credenziali": credenziali, "errore": errore}


class CercaTests(_Pagina):
    def setUp(self):
        super().setUp()
        self.dm6 = _macchina("CNC-DM6-000060148189", "Fresa DMC 125", "000060148189")
        self.dm9 = _macchina("CNC-DM9-00810001311", "Fresa DMC 85", "00810001311")
        self.dm10 = _macchina("CNC-DM10-12280008793", "Fresa DMC 160", "12280008793")
        self.dm11 = _macchina("CNC-DM11-12280009603", "Fresa DMC 65", "12280009603")
        self.altra = Asset.objects.create(asset_tag="CNC-DM16-SINT", name="Fresa non macchina", serial_number="10000005642")
        CollegamentoMTConnect.objects.create(asset=self.dm9, fonte="collector_opcua", opcua_host="192.0.2.23", codice="DM9")
        self.dm10_coll = CollegamentoMTConnect.objects.create(asset=self.dm10, fonte="collector_opcua", opcua_host="192.0.2.99",
                                                              codice="DM10", matricola_opcua="12280008793")

    def _con_risultati(self, risultati):
        async def finta_cerca(rete, porta=4840, credenziali=()):
            self.credenziali_provate = list(credenziali)
            return risultati

        return patch("assets.collector_cnc.cerca.cerca", finta_cerca)

    def test_indirizzi(self):
        from assets.collector_cnc import cerca

        self.assertEqual(len(cerca.indirizzi("192.0.2.0/24")), 254)
        self.assertEqual(cerca.indirizzi("192.0.2.4/30"), ["192.0.2.5", "192.0.2.6"])
        for sbagliata in ("8.8.8.0/24", "192.0.2.0/23", "boh", "fd00::/120"):
            with self.assertRaises(ValueError, msg=sbagliata):
                cerca.indirizzi(sbagliata)

    def test_abbinamenti(self):
        risultati = [
            _trovato("192.0.2.115", "12480000853"),               # matricola diversa dall'asset: si sceglie a mano
            _trovato("192.0.2.23", "00810001311"),                # già collegata a questo indirizzo
            _trovato("192.0.2.125", "12280008793"),               # già vista dal collector, IP cambiato
            _trovato("192.0.2.124", "0012280009603", "umati"),    # numero di serie dell'asset (zeri iniziali ignorati)
            _trovato("192.0.2.137", "10000005642"),               # asset che non è una macchina di lavoro
            _trovato("192.0.2.140", errore="accesso"),
            _trovato("192.0.2.150", dmg=False),
        ]
        with self._con_risultati(risultati):
            righe = collector_cnc.cerca_macchine("192.0.2.0/24", 4840, list(Asset.objects.filter(work_machine__isnull=False)))
        per_ip = {r["ip"]: r for r in righe}
        self.assertEqual([r["ip"] for r in righe], ["192.0.2.23", "192.0.2.115", "192.0.2.124", "192.0.2.125",
                                                    "192.0.2.137", "192.0.2.140", "192.0.2.150"])
        self.assertEqual((per_ip["192.0.2.115"]["asset"], per_ip["192.0.2.115"]["collegabile"]), (None, True))
        self.assertEqual((per_ip["192.0.2.23"]["esito"], per_ip["192.0.2.23"]["collegabile"]), ("Già collegata.", False))
        self.assertEqual(per_ip["192.0.2.125"]["asset"], self.dm10)
        self.assertIn("l'IP è cambiato", per_ip["192.0.2.125"]["esito"])
        self.assertEqual((per_ip["192.0.2.124"]["asset"], per_ip["192.0.2.124"]["codice"], per_ip["192.0.2.124"]["spunta"]),
                         (self.dm11, "DM11", True))
        self.assertEqual((per_ip["192.0.2.137"]["asset"], per_ip["192.0.2.137"]["collegabile"]), (self.altra, False))
        self.assertIn("utente e password", per_ip["192.0.2.140"]["esito"])
        self.assertIn("non è una DMG MORI", per_ip["192.0.2.150"]["esito"])

    def test_pagina_cerca_e_collega(self):
        sorgente = CollegamentoMTConnect.objects.get(asset=self.dm9)
        sorgente.opcua_utente, sorgente.opcua_password = "lettore", collector_cnc.cifra("pw-sintetica")
        sorgente.save()
        with self._con_risultati([_trovato("192.0.2.124", "12280009603", "umati", credenziali=sorgente.pk)]):
            resp = self.client.post(self.url, {"azione": "cerca", "rete": "192.0.2.0/24", "porta": "4840"})
        self.assertEqual(self.credenziali_provate, [("lettore", "pw-sintetica", sorgente.pk)])
        self.assertContains(resp, "Collega le macchine spuntate")
        self.assertContains(resp, 'name="codice_0" value="DM11"', html=False)
        self.client.post(self.url, {"azione": "cerca_collega", "scegli": ["0"], "ip_0": "192.0.2.124", "porta_0": "4840",
                                    "asset_0": str(self.dm11.pk), "codice_0": "DM11", "matricola_0": "12280009603",
                                    "modello_0": "umati", "cred_0": str(sorgente.pk)})
        coll = CollegamentoMTConnect.objects.get(asset=self.dm11)
        self.assertEqual((coll.fonte, coll.opcua_host, coll.codice, coll.matricola_opcua, coll.modello_dati, coll.opcua_utente),
                         ("collector_opcua", "192.0.2.124", "DM11", "12280009603", "umati", "lettore"))
        self.assertEqual(collector_cnc.decifra(coll.opcua_password), "pw-sintetica")
        self.assertEqual(set(AssetMeter.objects.filter(asset=self.dm11).values_list("meter_type", flat=True)), {"HOURS", "CYCLES"})

    def test_collega_rifiuta_indirizzo_gia_usato_e_rete_esterna(self):
        resp = self.client.post(self.url, {"azione": "cerca_collega", "scegli": ["0"], "ip_0": "192.0.2.23", "porta_0": "4840",
                                           "asset_0": str(self.dm6.pk), "codice_0": "DM6"}, follow=True)
        self.assertContains(resp, "è già di Fresa DMC 85")
        self.assertFalse(CollegamentoMTConnect.objects.filter(asset=self.dm6).exists())
        resp = self.client.post(self.url, {"azione": "cerca", "rete": "8.8.8.0/24", "porta": "4840"})
        self.assertContains(resp, "Solo reti IPv4 interne")

    def test_solo_amministratori(self):
        with patch("assets.views_mtconnect._puo_amministrare", return_value=False), \
                self._con_risultati([_trovato("192.0.2.124", "12280009603")]):
            self.client.post(self.url, {"azione": "cerca", "rete": "192.0.2.0/24"})
            self.client.post(self.url, {"azione": "cerca_collega", "scegli": ["0"], "ip_0": "192.0.2.124", "asset_0": str(self.dm11.pk)})
        self.assertFalse(hasattr(self, "credenziali_provate"))
        self.assertFalse(CollegamentoMTConnect.objects.filter(asset=self.dm11).exists())

    def test_lettura_del_server_opcua(self):
        from assets.collector_cnc import cerca

        class Rifiutato(Exception):
            pass

        Rifiutato.__name__ = "BadIdentityTokenRejected"

        class FintoClient:
            def __init__(self, url, timeout=None):
                self.utente = None

            def set_user(self, utente):
                self.utente = utente

            def set_password(self, password):
                self.password = password

            async def connect(self):
                if not self.utente:
                    raise Rifiutato()

            async def get_namespace_array(self):
                return ["http://opcfoundation.org/UA/", "https://DMGMORI.com/Machines/12480000853",
                        "http://opcfoundation.org/UA/MachineTool/"]

            async def disconnect(self):
                return None

        async def leggi(credenziali):
            return await cerca._leggi_server("192.0.2.5", 4840, credenziali, asyncio.Semaphore(1))

        with patch("asyncua.Client", FintoClient):
            esito = asyncio.run(leggi([("lettore", "pw", 7)]))
            negato = asyncio.run(leggi([]))
        self.assertEqual((esito["dmg"], esito["matricola"], esito["modello"], esito["credenziali"], esito["errore"]),
                         (True, "12480000853", "umati", 7, ""))
        self.assertEqual(negato["errore"], "accesso")


# --- report di utilizzo ----------------------------------------------------------------------------

class UtilizzoReportTests(TestCase):
    def setUp(self):
        asset = _macchina("CNC-DM6-SINT", "Fresa sintetica")
        self.coll = CollegamentoMTConnect.objects.create(asset=asset, fonte="collector_opcua", opcua_host="192.0.2.15")
        CollegamentoMTConnect.objects.filter(pk=self.coll.pk).update(creato_il=self._ora(10, 1, 0))
        for stato, dal, al in (("in_lavoro", self._ora(19, 8), self._ora(19, 12)),
                               ("allarme", self._ora(19, 12), self._ora(19, 12, 30)),
                               ("pronta", self._ora(19, 12, 30), self._ora(20, 2)),
                               ("spenta", self._ora(20, 2), self._ora(20, 6))):
            PeriodoStatoMacchina.objects.create(collegamento=self.coll, stato=stato, dal=dal, al=al)

    @staticmethod
    def _ora(giorno, ora=0, minuti=0, mese=10):
        return timezone.make_aware(datetime(2026, mese, giorno, ora, minuti))

    def _report(self, **filtri):
        from assets.services import report_catalog

        definizione = report_catalog.definizioni()["utilizzo-cnc"]
        return definizione.esegui({"dal": "2026-10-19", "al": "2026-10-20", **filtri})

    def test_per_macchina(self):
        r = self._report()
        self.assertEqual(r.intestazioni[2:], ["In lavoro h", "MDI/manuale h", "Ferma h", "Interrotta h", "Allarme/emergenza h",
                                              "Offline h", "Senza dati h", "Utilizzo %"])
        self.assertEqual(r.righe[0][2:], [4.0, 0.0, 13.5, 0.0, 0.5, 4.0, 26.0, 22.2])
        self.assertEqual(r.totali[2], 4.0)

    def test_per_giorno_divide_a_mezzanotte(self):
        r = self._report(raggruppa="giorno")
        self.assertEqual([riga[1] for riga in r.righe], ["19/10/2026", "20/10/2026"])
        self.assertEqual(r.righe[0][2:9], [4.0, 0.0, 11.5, 0.0, 0.5, 0.0, 8.0])
        self.assertEqual(r.righe[1][2:9], [0.0, 0.0, 2.0, 0.0, 0.0, 4.0, 18.0])

    def test_sintesi_e_vista(self):
        from assets.services import report_catalog

        definizione = report_catalog.definizioni()["utilizzo-cnc"]
        risultato, _numeriche = report_catalog.esegui(definizione, {"dal": "2026-10-19", "al": "2026-10-20"})
        self.assertEqual(dict(risultato.riepilogo)["Ore in lavoro"], "4")
        self.assertEqual(risultato.grafico["barre"][0]["valore"], 4.0)
