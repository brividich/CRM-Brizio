"""Affidabilità delle letture SNMP: tentativi UDP, scadenze, tabella MAC parziale, storico.

Nessun apparato vero: trasporti e walk sostituiti, indirizzi 192.0.2.x, community sintetiche."""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from contatori import services, snmp, tabella_mac, tasks
from contatori.forms import ImpostazioniSNMPForm
from contatori.models import DispositivoSNMP, ImpostazioniSNMP, MacPortaSwitch, RilevazioneSNMP, StatoSNMP
from contatori.snmp_capture import CaptureResult, Record


class TentativiUdpTests(TestCase):
    def test_mittente_con_tentativi_espliciti(self):
        send = mock.Mock()
        mittente = snmp.mittente_udp(send, 3)
        self.assertEqual(mittente.keywords, {"timeout": 3, "retries": snmp.TENTATIVI_UDP})
        self.assertLessEqual(snmp.TENTATIVI_UDP, 3)

    def test_leggi_specifiche_rispetta_la_scadenza_passata(self):
        with mock.patch.object(snmp, "leggi_oids", return_value=({"1.2.1": 1}, {})) as oids:
            snmp.leggi_specifiche("192.0.2.1", [{"oid": "1.2.1"}], community="sint", max_duration=5)
        self.assertLessEqual(oids.call_args.kwargs["max_duration"], 5)


class PollScadenzaUnicaTests(TestCase):
    def test_stampante_riceve_il_tempo_che_resta(self):
        disp = DispositivoSNMP.objects.create(nome="prt", host="192.0.2.60", categoria=DispositivoSNMP.Categoria.STAMPANTE)
        valori = {snmp.SYS_DESCR: "Printer sintetica", snmp.SYS_NAME: "prt"}
        dati = {"contatori": [{"indice": "1", "valore": 10}], "consumabili": [], "errori": {}}
        with mock.patch("contatori.snmp.leggi_specifiche", return_value=(valori, {})) as spec, \
                mock.patch("contatori.printer_snmp.leggi_stampante", return_value=dati) as prt:
            services.interroga_dispositivo(disp)
        self.assertLessEqual(spec.call_args.kwargs["max_duration"], snmp.POLL_BUDGET)
        self.assertLessEqual(prt.call_args.kwargs["max_duration"], snmp.POLL_BUDGET)


class DatiStampanteInvariatiTests(TestCase):
    def setUp(self):
        self.disp = DispositivoSNMP.objects.create(nome="prt", host="192.0.2.61",
                                                   categoria=DispositivoSNMP.Categoria.STAMPANTE)
        self.dati = {"contatori": [{"indice": "1", "valore": 100}], "consumabili": [{"indice": "1.1", "pct": 50}]}

    def _ril(self, quando, dati):
        return RilevazioneSNMP.objects.create(dispositivo=self.disp, stato=StatoSNMP.OK, rilevata_il=quando,
                                              dati_stampante=dati)

    def test_precedente_uguale_dello_stesso_giorno_alleggerita(self):
        ora = timezone.localtime().replace(hour=12, minute=0)
        prima = self._ril(ora - timedelta(minutes=15), self.dati)
        nuova = self._ril(ora, dict(self.dati))
        services._alleggerisci_precedente(self.disp, nuova, nuova.dati_stampante)
        prima.refresh_from_db()
        nuova.refresh_from_db()
        self.assertEqual(prima.dati_stampante, services.DATI_STAMPANTE_INVARIATI)
        self.assertEqual(nuova.dati_stampante, self.dati)

    def test_dati_cambiati_o_altro_giorno_restano(self):
        ora = timezone.localtime().replace(hour=12, minute=0)
        diversa = self._ril(ora - timedelta(minutes=15), {**self.dati, "contatori": [{"indice": "1", "valore": 99}]})
        nuova = self._ril(ora, self.dati)
        services._alleggerisci_precedente(self.disp, nuova, nuova.dati_stampante)
        ieri = self._ril(ora - timedelta(days=1), self.dati)
        oggi = self._ril(ora.replace(hour=0, minute=5) + timedelta(days=1), self.dati)
        services._alleggerisci_precedente(self.disp, oggi, oggi.dati_stampante)
        for r in (diversa, ieri):
            r.refresh_from_db()
            self.assertNotEqual(r.dati_stampante, services.DATI_STAMPANTE_INVARIATI)


def _fdb(mac_ottetti, porta=1, vlan=1):
    oid = f"{tabella_mac.Q_FDB_PORT}.{vlan}." + ".".join(str(o) for o in mac_ottetti)
    return Record(oid, "2", str(porta))


class TabellaMacParzialeTests(TestCase):
    def setUp(self):
        self.sw = DispositivoSNMP.objects.create(nome="sw", host="192.0.2.70", categoria=DispositivoSNMP.Categoria.RETE)
        MacPortaSwitch.objects.create(dispositivo=self.sw, mac="aa:bb:cc:00:00:01", porta="Gi1/0/1",
                                      letto_il=timezone.now() - timedelta(days=1))

    def _capture(self, completi):
        def capture(host, cred, *, root, **kw):
            righe = {tabella_mac.Q_FDB_PORT: [_fdb([2, 0, 0, 0, 0, 9])],
                     tabella_mac.BASE_PORT_IFINDEX: [Record(f"{tabella_mac.BASE_PORT_IFINDEX}.1", "2", "101")],
                     tabella_mac.IF_NAME: [Record(f"{tabella_mac.IF_NAME}.101", "4", "Gi1/0/9")]}.get(root, [])
            ok = completi.get(root, True)
            return CaptureResult(records=righe, complete=ok, stop_reason="" if ok else "timeout dell'apparato")
        return capture

    def _leggi(self, completi):
        with mock.patch("contatori.snmp_capture.capture", side_effect=self._capture(completi)), \
                mock.patch("contatori.services._community_snmp", return_value="sint"):
            return tabella_mac.run()

    def test_walk_fdb_incompleto_non_tocca_le_righe(self):
        esito = self._leggi({tabella_mac.Q_FDB_PORT: False})
        self.assertEqual(esito["switch"], 0)
        self.assertIn("lettura parziale", esito["parziali"][0])
        self.assertEqual(list(MacPortaSwitch.objects.values_list("mac", flat=True)), ["aa:bb:cc:00:00:01"])

    def test_nomi_porte_incompleti_non_toccano_le_righe(self):
        esito = self._leggi({tabella_mac.IF_NAME: False})
        self.assertIn("nomi delle porte", esito["parziali"][0])
        self.assertTrue(MacPortaSwitch.objects.filter(mac="aa:bb:cc:00:00:01").exists())

    def test_lettura_completa_sostituisce(self):
        esito = self._leggi({})
        self.assertEqual((esito["switch"], esito["mac"]), (1, 1))
        self.assertEqual(list(MacPortaSwitch.objects.values_list("mac", "porta")), [("02:00:00:00:00:09", "Gi1/0/9")])

    def test_switch_oltre_il_budget_rimandati(self):
        DispositivoSNMP.objects.create(nome="sw2", host="192.0.2.71", categoria=DispositivoSNMP.Categoria.RETE)
        orologio = iter([0.0, 0.0])
        with mock.patch.object(tabella_mac, "monotonic", side_effect=lambda: next(orologio, 1000.0)), \
                mock.patch.object(tabella_mac, "leggi_switch", return_value=3) as leggi:
            esito = tabella_mac.run()
        self.assertEqual(leggi.call_count, 1)
        # Prima lo switch mai letto (sw2), poi quello con righe vecchie.
        self.assertEqual(leggi.call_args.args[0].nome, "sw2")
        self.assertEqual(esito["rimandati"], ["sw: lettura rimandata al prossimo giro (tempo del giro esaurito)."])


class StoricoAltriApparatiTests(TestCase):
    def setUp(self):
        self.ups = DispositivoSNMP.objects.create(nome="ups", host="192.0.2.83", categoria=DispositivoSNMP.Categoria.UPS)

    def _ril(self, giorni_fa):
        return RilevazioneSNMP.objects.create(dispositivo=self.ups, stato=StatoSNMP.OK,
                                              rilevata_il=timezone.now() - timedelta(days=giorni_fa))

    def test_di_serie_spento_conserva_tutto(self):
        self._ril(400)
        self._ril(1)
        self.assertEqual(tasks.storico_snmp_giorni(), 0)
        esito = tasks.pulisci_rilevazioni_tvcc()
        self.assertNotIn("storico_altri", esito)
        self.assertEqual(RilevazioneSNMP.objects.count(), 2)

    def test_acceso_cancella_le_vecchie_e_tiene_l_ultima(self):
        from core.models import SiteConfig

        SiteConfig.set(tasks.CHIAVE_STORICO_SNMP, "90")
        vecchia = self._ril(400)
        recente = self._ril(1)
        solo = DispositivoSNMP.objects.create(nome="sw", host="192.0.2.84", categoria=DispositivoSNMP.Categoria.RETE)
        unica = RilevazioneSNMP.objects.create(dispositivo=solo, stato=StatoSNMP.OK,
                                               rilevata_il=timezone.now() - timedelta(days=500))
        esito = tasks.pulisci_rilevazioni_tvcc()
        self.assertEqual(esito["storico_altri"]["cancellate"], 1)
        self.assertFalse(RilevazioneSNMP.objects.filter(pk=vecchia.pk).exists())
        self.assertTrue(RilevazioneSNMP.objects.filter(pk__in=[recente.pk, unica.pk]).count() == 2)

    def test_minimo_sessanta_giorni(self):
        from core.models import SiteConfig

        SiteConfig.set(tasks.CHIAVE_STORICO_SNMP, "7")
        self.assertEqual(tasks.storico_snmp_giorni(), tasks.STORICO_SNMP_MINIMO_GIORNI)

    def test_budget_esaurito_rimanda(self):
        from core.models import SiteConfig

        SiteConfig.set(tasks.CHIAVE_STORICO_SNMP, "60")
        self._ril(400)
        self._ril(1)
        esito = tasks.pulisci_rilevazioni_storico(budget=0)
        self.assertEqual(esito["cancellate"], 0)
        self.assertIn("da_completare", esito)

    def test_impostazione_dalla_pagina(self):
        cfg = ImpostazioniSNMP.get_solo()
        base = {"community": "", "port": 161, "timeout": 3, "version": "v1", "tvcc_intervallo_nvr": 5,
                "tvcc_intervallo_telecamere": 30, "tvcc_retention_giorni": 14}
        form = ImpostazioniSNMPForm({**base, "storico_snmp_giorni": 30}, instance=cfg)
        self.assertIn("storico_snmp_giorni", form.errors)
        form = ImpostazioniSNMPForm({**base, "storico_snmp_giorni": 365}, instance=cfg)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(tasks.storico_snmp_giorni(), 365)
        self.assertEqual(ImpostazioniSNMPForm(instance=cfg).fields["storico_snmp_giorni"].initial, 365)


class PrinterScadenzaTests(TestCase):
    def test_colonne_oltre_la_scadenza_in_errore(self):
        import sys
        from types import ModuleType

        from contatori import printer_snmp

        modulo = ModuleType("puresnmp")
        modulo.Client = mock.Mock()
        modulo.PyWrapper = lambda c: SimpleNamespace()
        transport = ModuleType("puresnmp.transport")
        transport.send_udp = mock.Mock()
        with mock.patch.dict(sys.modules, {"puresnmp": modulo, "puresnmp.transport": transport}), \
                mock.patch("contatori.printer_snmp.costruisci_credenziali", return_value=object()):
            dati = printer_snmp.leggi_stampante(SimpleNamespace(host="192.0.2.62"), community="sint", port=161,
                                                timeout=1, version="v2c", max_duration=0)
        self.assertTrue(dati["errori"])
        self.assertTrue(all("Tempo complessivo" in e for e in dati["errori"].values()))
