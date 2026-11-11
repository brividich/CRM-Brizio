"""ESXi/vCenter e iLO/iDRAC (registro_log.infra): proxy, errori leggibili, budget del giro.

Nessuna rete: requests e pyvmomi sono sostituiti. Indirizzi della documentazione (192.0.2.x)."""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest import mock

import requests
from django.test import TestCase

from . import infra
from .models import ApparatoInfra


class _Resp:
    def __init__(self, status=200, dati=None, tipo="application/json", server=""):
        self.status_code = status
        self._dati = dati if dati is not None else {}
        self.headers = {"Content-Type": tipo, **({"Server": server} if server else {})}

    def json(self):
        if isinstance(self._dati, Exception):
            raise self._dati
        return self._dati


def _apparato(**kw):
    dati = {"nome": "bmc-sintetico", "tipo": ApparatoInfra.TIPO_REDFISH, "indirizzo": "192.0.2.10", "porta": 443,
            "utente": "lettore", "password_cifrata": "x"}
    dati.update(kw)
    return ApparatoInfra.objects.create(**dati)


class RedfishTests(TestCase):
    def setUp(self):
        self.app = _apparato()
        patcher = mock.patch.object(infra, "decifra", return_value="segreto-sintetico")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sessione_senza_proxy_dell_ambiente(self):
        sessioni = []

        class Sessione(requests.Session):
            def __init__(self):
                super().__init__()
                sessioni.append(self)

            def get(self, url, **kw):
                if url.endswith("/redfish/v1/"):
                    return _Resp(dati={"Vendor": "Sintetico", "Product": "BMC"})
                return _Resp(dati={"Members": []})

        with mock.patch("requests.Session", Sessione):
            stato, problemi = infra.leggi_redfish(self.app)
        self.assertFalse(sessioni[0].trust_env)
        self.assertEqual(stato["produttore"], "Sintetico")
        self.assertEqual(problemi, [])

    def test_errori_di_rete_distinti_con_l_indirizzo(self):
        casi = [
            (requests.exceptions.ProxyError("p"), "proxy"),
            (requests.exceptions.ConnectTimeout("t"), "nessuna risposta alla connessione"),
            (requests.exceptions.SSLError("s"), "certificato"),
        ]
        for errore, atteso in casi:
            with mock.patch("requests.Session.get", side_effect=errore):
                with self.assertRaises(RuntimeError) as ctx:
                    infra.leggi_redfish(self.app)
            self.assertIn("https://192.0.2.10:443", str(ctx.exception))
            self.assertIn(atteso, str(ctx.exception))

    def test_risposta_html_dice_chi_ha_risposto(self):
        risposta = _Resp(dati=ValueError("non json"), tipo="text/html", server="Proxy-Sintetico")
        with mock.patch("requests.Session.get", return_value=risposta):
            with self.assertRaises(RuntimeError) as ctx:
                infra.leggi_redfish(self.app)
        self.assertIn("Proxy-Sintetico", str(ctx.exception))
        self.assertIn("non arriva da Redfish", str(ctx.exception))

    def test_scadenza_passata_non_chiama(self):
        with mock.patch("requests.Session.get") as get:
            with self.assertRaises(infra.TempoScaduto):
                infra.leggi_redfish(self.app, scadenza=infra.time.monotonic() - 1)
        get.assert_not_called()


class VsphereTests(TestCase):
    def test_timeout_di_richiesta_passato_a_pyvmomi(self):
        app = _apparato(tipo=ApparatoInfra.TIPO_VSPHERE)
        connect = ModuleType("pyVim.connect")
        connect.SmartConnect = mock.Mock(side_effect=TimeoutError("sintetico"))
        connect.Disconnect = mock.Mock()
        pyvim = ModuleType("pyVim")
        pyvim.connect = connect
        pyvmomi = ModuleType("pyVmomi")
        pyvmomi.vim = SimpleNamespace()
        with mock.patch.dict(sys.modules, {"pyVim": pyvim, "pyVim.connect": connect, "pyVmomi": pyvmomi}), \
                mock.patch.object(infra, "decifra", return_value="segreto-sintetico"):
            with self.assertRaises(RuntimeError) as ctx:
                infra.leggi_vsphere(app)
        kwargs = connect.SmartConnect.call_args.kwargs
        self.assertEqual(kwargs["httpConnectionTimeout"], infra.TIMEOUT)
        self.assertIn("192.0.2.10:443", str(ctx.exception))


class GiroTests(TestCase):
    def test_apparati_oltre_il_budget_rimandati(self):
        primo = _apparato(nome="primo")
        secondo = _apparato(nome="secondo", indirizzo="192.0.2.11")
        orologio = iter([0.0, 0.0, 0.0, 85.0, 85.0])

        def leggi(app, scadenza=None):
            ApparatoInfra.objects.filter(pk=app.pk).update(errore="", letto_il=infra.timezone.now())

        with mock.patch.object(infra.time, "monotonic", side_effect=lambda: next(orologio, 85.0)), \
                mock.patch.object(infra, "leggi", side_effect=leggi) as letto:
            esito = infra.aggiorna()
        self.assertEqual(letto.call_count, 1)
        self.assertEqual(letto.call_args.args[0].pk, primo.pk)
        self.assertEqual(esito["letti"], 1)
        self.assertEqual(esito["rimandati"], ["secondo: lettura rimandata al prossimo giro (tempo del giro esaurito)."])
        # Al giro dopo il rimandato (mai letto) passa per primo.
        ordine = list(ApparatoInfra.objects.filter(attivo=True).order_by(
            infra.F("letto_il").asc(nulls_first=True), "pk").values_list("pk", flat=True))
        self.assertEqual(ordine[0], secondo.pk)

    def test_errore_salvato_nella_fotografia(self):
        app = _apparato()
        with mock.patch.object(infra, "leggi_redfish", side_effect=RuntimeError("https://192.0.2.10:443: proxy")):
            infra.leggi(app)
        app.refresh_from_db()
        self.assertIn("192.0.2.10", app.errore)
