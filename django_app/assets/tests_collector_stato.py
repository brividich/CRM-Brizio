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

    def test_eventi_reinviati_non_duplicano(self):
        """Store-and-forward: la chiave ``evento`` scarta i reinvii, anche fuori ordine, senza periodi doppi."""
        e1 = self._riga("LAVORO", 30, evento="ab12:000000000001")
        e2 = self._riga("FERMA", 20, evento="ab12:000000000002")
        e3 = self._riga("LAVORO", 10, evento="ab12:000000000003")
        self.assertEqual(self._post([e1, e2, e3]).json()["accepted"], 3)
        esito = self._post([e1, e2, e3]).json()   # tutto reinviato (es. crash prima di cancellare la coda)
        self.assertEqual((esito["accepted"], esito["ignored"]), (1, 2))   # l'ultimo è il «battito»: aggiorna soltanto
        self.assertEqual(esito["results"][0]["reason"], "evento già applicato (reinvio)")
        coll = CollegamentoMTConnect.objects.get(asset=self.asset)
        self.assertEqual(coll.ultimo_evento, "ab12:000000000003")
        self.assertEqual(list(PeriodoStatoMacchina.objects.filter(collegamento=coll).order_by("dal").values_list("stato", flat=True)),
                         ["in_lavoro", "pronta", "in_lavoro"])
        # un collector nuovo (istanza diversa) riparte dal suo primo evento
        self.assertEqual(self._post([self._riga("FERMA", 1, evento="cd34:000000000001")]).json()["accepted"], 1)
        # una riga senza chiave (collector di versione precedente) si applica come prima
        self.assertEqual(self._post([self._riga("LAVORO", 0)]).json()["accepted"], 1)

    def test_non_leggibile_con_motivo(self):
        motivo = "login DNC rifiutato: su questa macchina serve l'opzione software #18"
        self.assertEqual(self._post([self._riga("NON_LEGGIBILE", 1, errore=motivo)]).json()["accepted"], 1)
        coll = CollegamentoMTConnect.objects.get(asset=self.asset)
        self.assertEqual((coll.stato, coll.get_stato_display(), coll.errore), ("non_leggibile", "Non leggibile", motivo))
        self.assertEqual(mtconnect.STATO_ETICHETTE["non_leggibile"], "Non leggibile")
        self._post([self._riga("LAVORO", 0)])
        coll.refresh_from_db()
        self.assertEqual(coll.errore, "")

    def test_chiave_evento(self):
        from assets.services.collector_cnc import evento_gia_applicato

        self.assertTrue(evento_gia_applicato("x:000000000005", "x:000000000004"))
        self.assertFalse(evento_gia_applicato("x:000000000005", "x:000000000005"))
        self.assertFalse(evento_gia_applicato("x:000000000005", "y:000000000001"))
        self.assertFalse(evento_gia_applicato("", "x:1"))
        self.assertFalse(evento_gia_applicato("x:5", "rotta"))

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


PORTALE_PY = Path(__file__).resolve().parent / "collector_cnc" / "portale.py"


@skipUnless(PORTALE_PY.exists(), "collector non presente in questo pacchetto")
@override_settings(ASSETS_METER_INGEST_ALLOWED_IPS=["127.0.0.1"])
class ContrattoConIlCollectorTests(TestCase):
    """Il payload prodotto da django_app/assets/collector_cnc/portale.py è quello che l'endpoint si aspetta."""

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



class CollectorDalPortaleTests(TestCase):
    """Token, rete ammessa e macchine del collector gestiti dalla pagina Macchine collegate."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        from assets.models import WorkMachine
        from core.models import UserOnboarding

        self.admin = get_user_model().objects.create_superuser(username="adm_collector", email="a@a.it", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.client.force_login(self.admin)
        self.url = reverse("assets:mtconnect_collegamenti")
        self.dm6 = Asset.objects.create(asset_tag="CNC-DM6", name="Fresa DMC 125", asset_type=Asset.TYPE_CNC, serial_number="SN-SINT-6")
        self.dm7 = Asset.objects.create(asset_tag="CNC-DM7", name="Fresa DMC 160", asset_type=Asset.TYPE_CNC)
        for a in (self.dm6, self.dm7):
            WorkMachine.objects.create(asset=a, source_key=f"col-{a.asset_tag}", cnc_controlled=True)

    def _macchina(self, asset, host, codice, **extra):
        return self.client.post(self.url, {"azione": "salva", "fonte": "collector_opcua", "asset": asset.pk,
                                           "opcua_host": host, "opcua_porta": "4840", "codice": codice, **extra})

    def _crea_collector(self, **extra):
        resp = self.client.post(self.url, {"azione": "collector_crea", "nome": "Collector CNC officina", "ips": "127.0.0.1",
                                           "tutte": "on", **extra})
        return resp, resp.context["token_nuovo"]["token"]

    def _config(self, token, **extra):
        return self.client.get("/api/assets/contatori/ingest/config/", HTTP_AUTHORIZATION=f"Bearer {token}", **extra)

    def test_macchina_collector_con_password_cifrata_e_contatori(self):
        self._macchina(self.dm6, "192.0.2.15", "DM6", opcua_utente="lettore", opcua_password="pw-sintetica", crea_contatori="on")
        coll = CollegamentoMTConnect.objects.get(asset=self.dm6)
        self.assertEqual((coll.fonte, coll.opcua_host, coll.codice, coll.opcua_utente), ("collector_opcua", "192.0.2.15", "DM6", "lettore"))
        self.assertNotIn("pw-sintetica", coll.opcua_password)
        self.assertEqual(set(AssetMeter.objects.filter(asset=self.dm6).values_list("meter_type", flat=True)), {"HOURS", "CYCLES"})
        self._macchina(self.dm6, "192.0.2.16", "DM6")  # password vuota = resta quella
        coll.refresh_from_db()
        self.assertEqual(coll.opcua_host, "192.0.2.16")
        self.assertTrue(coll.opcua_password)
        self._macchina(self.dm6, "host con spazi", "DM6")
        coll.refresh_from_db()
        self.assertEqual(coll.opcua_host, "192.0.2.16")

    def test_token_una_volta_e_config_per_il_collector(self):
        self._macchina(self.dm6, "192.0.2.15", "DM6", opcua_utente="lettore", opcua_password="pw-sintetica")
        self._macchina(self.dm7, "192.0.2.20", "DM7")
        resp, token = self._crea_collector()
        self.assertContains(resp, token)
        self.assertNotContains(self.client.get(self.url), token)  # non si rivede
        client = MeterIngestClient.objects.get(name="Collector CNC officina")
        self.assertNotEqual(client.token_hash, token)
        dati = self._config(token).json()
        self.assertEqual(dati["collector"], "Collector CNC officina")
        dm6 = next(m for m in dati["machines"] if m["name"] == "DM6")
        self.assertEqual((dm6["ip"], dm6["port"], dm6["asset_tag"], dm6["serial"], dm6["username"], dm6["password"]),
                         ("192.0.2.15", 4840, "CNC-DM6", "SN-SINT-6", "lettore", "pw-sintetica"))
        # Sospesa = non più nell'elenco.
        CollegamentoMTConnect.objects.filter(asset=self.dm7).update(attivo=False)
        self.assertEqual([m["name"] for m in self._config(token).json()["machines"]], ["DM6"])

    def test_solo_le_macchine_consentite_e_rete_del_collector(self):
        self._macchina(self.dm6, "192.0.2.15", "DM6")
        self._macchina(self.dm7, "192.0.2.20", "DM7")
        _resp, token = self._crea_collector(tutte="", macchine=[str(self.dm7.pk)])
        self.assertEqual([m["name"] for m in self._config(token).json()["machines"]], ["DM7"])
        with override_settings(ASSETS_METER_INGEST_ALLOWED_IPS=[]):
            self.assertEqual(self._config(token).status_code, 200)  # 127.0.0.1 scritto nel collector
            self.assertEqual(self._config(token, REMOTE_ADDR="198.51.100.9").status_code, 403)
        self.assertEqual(self._config("sbagliato").status_code, 401)

    def test_nuovo_token_e_disattiva(self):
        _resp, vecchio = self._crea_collector()
        client = MeterIngestClient.objects.get()
        resp = self.client.post(self.url, {"azione": "collector_token", "collector": client.pk})
        nuovo = resp.context["token_nuovo"]["token"]
        self.assertEqual(self._config(vecchio).status_code, 401)
        self.assertEqual(self._config(nuovo).status_code, 200)
        self.client.post(self.url, {"azione": "collector_disattiva", "collector": client.pk})
        self.assertEqual(self._config(nuovo).status_code, 401)

    def test_ip_non_validi(self):
        self.client.post(self.url, {"azione": "collector_crea", "nome": "X", "ips": "192.168.300.1"})
        self.assertFalse(MeterIngestClient.objects.exists())

    def test_solo_amministratori_per_i_collector(self):
        from unittest.mock import patch

        with patch("assets.views_mtconnect.user_can_modulo_action", return_value=False), \
                patch("assets.views_mtconnect._puo_amministrare", return_value=False):
            self.client.post(self.url, {"azione": "collector_crea", "nome": "Abusivo", "ips": "127.0.0.1", "tutte": "on"})
        self.assertFalse(MeterIngestClient.objects.exists())



@override_settings(ASSETS_METER_INGEST_ALLOWED_IPS=["127.0.0.1"])
class CollectorIntegratoTests(TestCase):
    """Collector «Sul server del portale»: stesso codice, scrittura diretta nel database."""

    def setUp(self):
        from assets.services import collector_cnc

        self.svc = collector_cnc
        self.asset = Asset.objects.create(asset_tag="CNC-INT-1", name="Fresa sintetica", asset_type=Asset.TYPE_CNC)
        AssetMeter.objects.create(asset=self.asset, meter_type=AssetMeter.METER_HOURS, current_value=Decimal("10"))
        CollegamentoMTConnect.objects.create(asset=self.asset, fonte="collector_opcua", opcua_host="192.0.2.30", codice="DM9")

    def _diretto(self):
        from assets.collector_cnc.diretto import PortaleDiretto

        return PortaleDiretto(prog_name=lambda x: str(x or ""))

    def test_modalita_e_elenco(self):
        self.assertEqual(self.svc.modalita(), "pc")
        self.assertEqual(self._diretto().scarica_macchine(), [])  # sul PC: il server non legge niente
        self.svc.imposta_modalita("server")
        self.assertEqual([m["name"] for m in self._diretto().scarica_macchine()], ["DM9"])
        with self.assertRaises(ValueError):
            self.svc.imposta_modalita("boh")

    def test_il_pc_non_riceve_macchine_se_il_collector_e_sul_server(self):
        token = MeterIngestClient.issue_token()
        client = MeterIngestClient(name="PC officina", all_meter_assets=True)
        client.set_token(token)
        client.save()
        url = "/api/assets/contatori/ingest/config/"
        self.assertEqual(len(self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}").json()["machines"]), 1)
        self.svc.imposta_modalita("server")
        dati = self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}").json()
        self.assertEqual((dati["modalita"], dati["machines"]), ("server", []))

    def test_scrive_stato_e_contatori_nel_database(self):
        import asyncio
        from unittest.mock import patch

        from assets.collector_cnc.portale import URL_CONTATORI, URL_STATO

        p = self._diretto()
        adesso = timezone.now()
        riga = {"asset_tag": "CNC-INT-1", "stato": "LAVORO", "dal": (adesso - timedelta(minutes=2)).isoformat(), "programma": "P1"}
        lettura = {"asset_tag": "CNC-INT-1", "meter_type": "HOURS", "value": 12.5, "read_at": adesso.isoformat()}
        # La scrittura (nel servizio gira in un thread di asyncio.to_thread) si prova direttamente:
        # dentro un ciclo asyncio Django aprirebbe un'altra connessione, fuori dalla transazione del test.
        self.assertEqual(p.scrivi(URL_STATO, {"macchine": [riga]})["accepted"], 1)
        self.assertEqual(p.scrivi(URL_CONTATORI, {"readings": [lettura]})["accepted"], 1)
        # invia() passa la stessa scrittura a un thread e dice se è andata.
        chiamate = []

        async def finto_thread(funzione, *args):
            chiamate.append((funzione, args))
            return {"results": []}

        with patch.object(asyncio, "to_thread", finto_thread):
            self.assertTrue(asyncio.run(p.invia(URL_STATO, {"macchine": [riga]})))
        self.assertEqual(chiamate[0][1], (URL_STATO, {"macchine": [riga]}))
        coll = CollegamentoMTConnect.objects.get(asset=self.asset)
        self.assertEqual((coll.stato, coll.programma), ("in_lavoro", "P1"))
        self.assertEqual(AssetMeter.objects.get(asset=self.asset).current_value, Decimal("12.50"))

    def test_battito_e_controllo_infrastruttura(self):
        from datetime import timedelta as td
        from unittest.mock import patch

        from monitoring.health import STATUS_FAIL, STATUS_OK, STATUS_SKIPPED
        from monitoring.infra_checks import check_collector_cnc

        self.assertEqual(check_collector_cnc().status, STATUS_SKIPPED)  # modalità PC
        self.svc.imposta_modalita("server")
        self.assertEqual(check_collector_cnc().status, STATUS_FAIL)  # mai partito
        self.svc.registra_battito(3)
        self.assertEqual(check_collector_cnc().status, STATUS_OK)
        with patch("django.utils.timezone.now", return_value=timezone.now() + td(minutes=10)):
            self.assertEqual(check_collector_cnc().status, STATUS_FAIL)

    def test_comando_prova(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("collector_cnc", "--prova", stdout=out)
        self.assertIn("DM9: 192.0.2.30:4840", out.getvalue())
        self.assertIn("PC dell'officina", out.getvalue())

    def test_esce_quando_si_attiva_una_release_nuova(self):
        from io import StringIO
        from unittest.mock import patch

        from django.core.management import call_command

        async def legge_per_sempre(*args, **kwargs):
            import asyncio

            await asyncio.sleep(3600)

        out = StringIO()
        # Il junction «current» punta a un'altra cartella al primo controllo: il comando esce e il launcher lo riavvia.
        with patch("assets.management.commands.collector_cnc.cartella_release", side_effect=["rel-A", "rel-B"]), \
                patch("assets.collector_cnc.collector.avvia", legge_per_sempre):
            call_command("collector_cnc", stdout=out)
        self.assertIn("Attivata una release nuova", out.getvalue())

    def test_pagina_scelta_modalita(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        from core.models import UserOnboarding

        admin = get_user_model().objects.create_superuser(username="adm_int", email="a@a.it", password="x")
        UserOnboarding.objects.create(user=admin, completed=True)
        self.client.force_login(admin)
        url = reverse("assets:mtconnect_collegamenti")
        self.assertContains(self.client.get(url), "Dove gira il collector")
        self.client.post(url, {"azione": "collector_modalita", "modalita": "server"})
        self.assertEqual(self.svc.modalita(), "server")
        self.assertContains(self.client.get(url), "Mai partito")
