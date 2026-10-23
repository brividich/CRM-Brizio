"""Stato delle CNC dal collector OPC UA (``POST /api/assets/contatori/ingest/stato/``). Dati sintetici."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless

from django.test import TestCase, override_settings
from django.utils import timezone

from assets.models import Asset, AssetMeter, CollegamentoMTConnect, MeterIngestClient, PeriodoStatoMacchina
from assets.services import mtconnect

URL = "/api/assets/contatori/ingest/stato/"


@override_settings(ASSETS_METER_INGEST_ALLOWED_IPS=["127.0.0.1"])
class IngestStatoTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="CNC-COL-1", name="Fresa sintetica", asset_type=Asset.TYPE_CNC)
        self.altro = Asset.objects.create(asset_tag="CNC-COL-2", name="Tornio sintetico", asset_type=Asset.TYPE_CNC)
        self.token = MeterIngestClient.issue_token()
        self.collector = MeterIngestClient(name="Collector CNC (test)")
        self.collector.set_token(self.token)
        self.collector.save()
        self.collector.allowed_assets.add(self.asset)

    def _post(self, macchine, token=None, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token if token is not None else self.token}"}
        headers.update(extra)
        return self.client.post(URL, data=json.dumps({"macchine": macchine}), content_type="application/json", **headers)

    def _riga(self, stato="LAVORO", minuti_fa=5, tag="CNC-COL-1", **extra):
        return {"asset_tag": tag, "stato": stato, "dal": (timezone.now() - timedelta(minutes=minuti_fa)).isoformat(),
                "programma": "DM6_0014_R1", "modalita": "AUTO", **extra}

    def test_primo_invio_crea_il_collegamento(self):
        resp = self._post([self._riga()])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["accepted"], 1)
        coll = CollegamentoMTConnect.objects.get(asset=self.asset)
        self.assertEqual((coll.fonte, coll.stato, coll.programma, coll.url_agent), ("collector_opcua", "in_lavoro", "DM6_0014_R1", ""))
        self.assertTrue(mtconnect.attuale(coll))
        # Il periodo parte dall'istante dichiarato dal collector, non dall'invio.
        self.assertLess(coll.stato_dal, timezone.now() - timedelta(minutes=4))
        self.collector.refresh_from_db()
        self.assertIsNotNone(self.collector.last_seen_at)

    def test_cambi_di_stato_e_allarmi(self):
        self._post([self._riga("LAVORO", 30)])
        allarmi = [{"codice": "2001", "testo": "Pressione lubrificazione bassa", "severita": 900},
                   {"codice": "10", "testo": "Porta aperta", "severita": 500}]
        self._post([self._riga("ALLARME", 2, allarmi=allarmi)])
        self._post([self._riga("ALLARME", 2, allarmi=allarmi)])  # stesso stato: nessun periodo nuovo
        coll = CollegamentoMTConnect.objects.get(asset=self.asset)
        self.assertEqual(coll.stato, "allarme")
        self.assertEqual([a["livello"] for a in coll.allarmi], ["allarme", "avviso"])
        self.assertEqual(list(PeriodoStatoMacchina.objects.filter(collegamento=coll).order_by("dal").values_list("stato", flat=True)),
                         ["in_lavoro", "allarme"])
        live = mtconnect.per_mappa([self.asset.pk])[self.asset.pk]
        self.assertTrue(live["allarme"])
        self.assertEqual(live["fonte"], "Collector OPC UA")

    def test_stati_del_collector(self):
        for stato, atteso in (("SETUP", "setup"), ("INTERROTTA", "ferma"), ("FERMA", "pronta"),
                              ("EMERGENZA", "emergenza"), ("OFFLINE", "spenta")):
            self._post([self._riga(stato, 1)])
            self.assertEqual(CollegamentoMTConnect.objects.get(asset=self.asset).stato, atteso, stato)
        self.assertTrue(mtconnect.per_mappa([self.asset.pk])[self.asset.pk]["allarme"] is False)

    def test_righe_rifiutate(self):
        resp = self._post([
            self._riga(tag="CNC-COL-2"),
            self._riga(tag="NON-ESISTE"),
            self._riga(stato="BOH"),
            {"asset_tag": "CNC-COL-1", "stato": "LAVORO", "dal": "2026-10-20T08:00:00"},
        ]).json()
        self.assertEqual([r["reason"] for r in resp["results"]], [
            "asset non consentito a questo collector", "asset sconosciuto", "stato non valido",
            "dal senza fuso orario (ISO 8601 con offset)"])
        self.assertFalse(CollegamentoMTConnect.objects.exists())

    def test_sospesa_e_mtconnect(self):
        self._post([self._riga()])
        CollegamentoMTConnect.objects.filter(asset=self.asset).update(attivo=False)
        self.assertEqual(self._post([self._riga("FERMA", 1)]).json()["results"][0]["status"], "ignored")
        CollegamentoMTConnect.objects.filter(asset=self.asset).update(attivo=True, fonte="mtconnect", url_agent="http://10.0.5.21:5000")
        self.assertEqual(self._post([self._riga("FERMA", 1)]).json()["results"][0]["reason"],
                         "macchina letta dal portale via MTConnect")

    def test_autenticazione_e_rete(self):
        self.assertEqual(self._post([self._riga()], token="sbagliato").status_code, 401)
        self.assertEqual(self._post([self._riga()], REMOTE_ADDR="203.0.113.7").status_code, 403)
        self.assertEqual(self._post([self._riga()] * 101).status_code, 413)
        self.assertNotEqual(self.client.get(URL).status_code, 200)

    def test_collector_non_letto_dal_polling_mtconnect(self):
        self._post([self._riga()])
        self.assertEqual(mtconnect.leggi_tutti(), {"collegamenti": 0})


PORTALE_PY = Path(__file__).resolve().parents[2] / "tools" / "collector_cnc" / "portale.py"


@skipUnless(PORTALE_PY.exists(), "collector non presente in questo pacchetto")
@override_settings(ASSETS_METER_INGEST_ALLOWED_IPS=["127.0.0.1"])
class ContrattoConIlCollectorTests(TestCase):
    """Il payload prodotto da tools/collector_cnc/portale.py è quello che l'endpoint si aspetta."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("portale_collector", PORTALE_PY)
        self.portale = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.portale)
        self.asset = Asset.objects.create(asset_tag="CNC-COL-9", name="Fresa sintetica", asset_type=Asset.TYPE_CNC)
        self.ore = AssetMeter.objects.create(asset=self.asset, meter_type=AssetMeter.METER_HOURS, current_value=Decimal("100"))
        self.cicli = AssetMeter.objects.create(asset=self.asset, meter_type=AssetMeter.METER_CYCLES, current_value=Decimal("10"))
        self.token = MeterIngestClient.issue_token()
        client = MeterIngestClient(name="Collector contratto (test)")
        client.set_token(self.token)
        client.save()
        client.allowed_assets.add(self.asset)

    def _macchina(self):
        adesso = datetime.now(dt_timezone.utc).replace(tzinfo=None) - timedelta(minutes=3)  # come il collector: UTC senza fuso
        return SimpleNamespace(
            asset_tag="CNC-COL-9", state="ALLARME", state_since=adesso, counters_at=adesso,
            spec={"mode_map": {1: "AUTO"}, "exec_map": {2: "INTERRUPTED"}, "hours_factor": 1 / 3600},
            values={"program": "/_N_MPF_DIR/_N_DM9_0014_MPF", "mode": 1, "exec": 2, "cnt_part_counter": 7,
                    "cnt_operation_time": 360000, "cnt_parts_overall": 25},
            alarms={"n1": {"code": "2001", "message": "Pressione bassa", "severity": 900, "since": adesso}},
        )

    def _post(self, url, body):
        return self.client.post(url, data=json.dumps(body), content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_stato_e_contatori_accettati(self):
        p = self.portale.Portale("http://portale.test", self.token, [], prog_name=lambda x: "DM9_0014")
        m = self._macchina()
        stato = self._post(URL, {"macchine": [p.riga_stato(m)]}).json()
        self.assertEqual(stato["accepted"], 1, stato)
        coll = CollegamentoMTConnect.objects.get(asset=self.asset)
        self.assertEqual((coll.stato, coll.programma, coll.modalita, coll.allarmi[0]["livello"]), ("allarme", "DM9_0014", "AUTO", "allarme"))
        contatori = self._post("/api/assets/contatori/ingest/", {"readings": p.righe_contatori(m)}).json()
        self.assertEqual(contatori["accepted"], 2, contatori)
        self.ore.refresh_from_db()
        self.cicli.refresh_from_db()
        self.assertEqual((self.ore.current_value, self.cicli.current_value), (Decimal("100.00"), Decimal("25.00")))
