"""Preset SNMP verificati su fixture .snmprec reali (pseudonimizzate).

Il transport e' sostituito da un lettore della fixture: GET su OID esatto,
WALK sulla colonna, con la stessa aggregazione del motore di produzione.
"""
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import TestCase

from contatori import snmp_capture as cap
from contatori.models import ColonnaProfiloSNMP, DispositivoSNMP, ProfiloSNMP, StatoSNMP
from contatori.services import interroga_dispositivo, trova_profilo_snmp
from contatori.snmp import SNMPError, aggrega_colonna

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "snmp"
SYNOLOGY = FIXTURES / "synology_rs2423rp_dsm74.snmprec"


def _python_value(record):
    if record.tag in ("2", "65", "66", "67", "70"):
        return int(record.value)
    if record.tag.endswith("x"):
        return bytes.fromhex(record.value)
    return record.value


class FixtureAgent:
    """Risponde come ``snmp.leggi_specifiche`` leggendo un file snmprec."""

    def __init__(self, path):
        self.values = {r.oid: _python_value(r)
                       for r in cap.parse_snmprec(path.read_text(encoding="utf-8"))}

    def leggi_specifiche(self, host, specifiche, **_kwargs):
        valori, errori = {}, {}
        for spec in specifiche:
            oid = spec["oid"]
            if spec.get("modalita", "GET") == "WALK":
                colonna = [v for k, v in self.values.items() if k.startswith(oid + ".")]
                try:
                    valori[oid] = aggrega_colonna(colonna, spec.get("aggregazione", "PRIMO"))
                except SNMPError as exc:
                    errori[oid] = str(exc)
            elif oid in self.values:
                valori[oid] = self.values[oid]
            else:
                errori[oid] = "No such object"
        if not valori:
            raise SNMPError("nessuna risposta")
        return valori, errori


class SynologyPresetTests(TestCase):
    PROBE = "1.3.6.1.4.1.6574.1.5.1.0"

    def setUp(self):
        self.agent = FixtureAgent(SYNOLOGY)

    def test_preset_columns_are_seeded_and_verified(self):
        profilo = ProfiloSNMP.objects.get(slug="synology")
        self.assertEqual(profilo.oid_riconoscimento, self.PROBE)
        colonne = list(profilo.colonne.filter(attiva=True))
        self.assertGreaterEqual(len(colonne), 17)
        self.assertTrue(all(c.verificata and c.fonte for c in colonne))
        netsnmp = ProfiloSNMP.objects.get(slug="net-snmp")
        self.assertTrue(netsnmp.colonne.filter(oid="1.3.6.1.4.1.2021.4.27.0", verificata=True).exists())

    def test_every_verified_oid_answers_in_fixture(self):
        for colonna in ColonnaProfiloSNMP.objects.filter(verificata=True, fonte__contains="Synology"):
            valori, errori = self.agent.leggi_specifiche("h", [{
                "oid": colonna.oid, "modalita": colonna.modalita,
                "aggregazione": colonna.aggregazione,
            }])
            self.assertIn(colonna.oid, valori, f"{colonna.nome}: {errori}")

    def test_detection_needs_probe_because_sysobjectid_is_net_snmp(self):
        descr = self.agent.values["1.3.6.1.2.1.1.1.0"]
        object_id = self.agent.values["1.3.6.1.2.1.1.2.0"]
        self.assertEqual(object_id, "1.3.6.1.4.1.8072.3.2.10")
        senza = trova_profilo_snmp(sys_object_id=object_id, sys_description=descr)
        self.assertEqual(senza.slug, "net-snmp")
        con = trova_profilo_snmp(sys_object_id=object_id, sys_description=descr,
                                 valori_riconoscimento={self.PROBE: self.agent.values[self.PROBE]})
        self.assertEqual(con.slug, "synology")

    def test_poll_detects_synology_and_reads_health(self):
        dispositivo = DispositivoSNMP.objects.create(nome="NAS", host="192.0.2.250", versione="v2c")
        with mock.patch("contatori.snmp.leggi_specifiche", side_effect=self.agent.leggi_specifiche):
            rilevazione = interroga_dispositivo(dispositivo)
        dispositivo.refresh_from_db()
        self.assertEqual(dispositivo.profilo_snmp.slug, "synology")
        self.assertEqual(dispositivo.categoria, DispositivoSNMP.Categoria.STORAGE)
        valori = {v.sonda.nome: v for v in rilevazione.valori.select_related("sonda")}
        self.assertEqual(valori["Modello"].valore_testo, "RS2423RP+")
        self.assertTrue(valori["Seriale"].valore_testo.startswith("SN-SINT-"))
        self.assertEqual(valori["Versione DSM"].valore_testo, "DSM 7.4-90080")
        self.assertEqual(valori["Temperatura sistema"].valore_numero, Decimal("43"))
        self.assertEqual(valori["Stato peggiore dischi"].valore_numero, Decimal("1"))
        self.assertEqual(valori["Stato peggiore volumi/RAID"].valore_numero, Decimal("1"))
        self.assertEqual(valori["Temperatura massima dischi"].stato, StatoSNMP.OK)
        # TimeTicks -> secondi; RAM in MiB.
        self.assertEqual(valori["Uptime sistema"].valore_numero, Decimal("3543799.29"))
        self.assertAlmostEqual(float(valori["RAM totale"].valore_numero), 15975, delta=5)
        self.assertTrue(0 <= valori["Carico CPU medio"].valore_numero <= 100)
        self.assertEqual(rilevazione.stato, StatoSNMP.OK, {
            k: (v.stato, v.errore) for k, v in valori.items() if v.stato != StatoSNMP.OK})
        self.assertEqual(rilevazione.dati_stampante, {})

    def test_thresholds_copied_to_probes(self):
        dispositivo = DispositivoSNMP.objects.create(nome="NAS", host="192.0.2.251", versione="v2c")
        with mock.patch("contatori.snmp.leggi_specifiche", side_effect=self.agent.leggi_specifiche):
            interroga_dispositivo(dispositivo)
        sonda = dispositivo.sonde.get(nome="Temperatura sistema")
        self.assertEqual((sonda.soglia_warning_max, sonda.soglia_critica_max), (Decimal("55"), Decimal("65")))
        self.assertEqual(sonda.stato_per_valore(Decimal("70")), StatoSNMP.ERROR)

    def test_status_codes_have_labels_and_raid_scrubbing_is_not_critical(self):
        dispositivo = DispositivoSNMP.objects.create(nome="NAS", host="192.0.2.252", versione="v2c")
        with mock.patch("contatori.snmp.leggi_specifiche", side_effect=self.agent.leggi_specifiche):
            rilevazione = interroga_dispositivo(dispositivo)
        valori = {v.sonda.nome: v for v in rilevazione.valori.select_related("sonda")}
        self.assertEqual(valori["Stato sistema"].valore_display, "Normale")
        self.assertEqual(valori["Aggiornamento DSM disponibile"].valore_display, "Nessuno")
        raid = dispositivo.sonde.get(nome="Stato peggiore volumi/RAID")
        self.assertEqual(raid.stato_per_valore(Decimal("13")), StatoSNMP.WARNING)
        self.assertEqual(raid.stato_per_valore(Decimal("1")), StatoSNMP.OK)

    def test_fixture_contains_no_real_identifiers(self):
        text = SYNOLOGY.read_text(encoding="utf-8")
        self.assertNotIn("BACKUPNAS", text.upper().replace("DEVICE-1", ""))
        self.assertNotIn("|64|10.", text)


def _fixture_printer(agent):
    """Sostituto di printer_snmp.leggi_stampante basato sulla fixture."""
    from contatori.printer_snmp import COLUMNS, interpreta_stampante

    def leggi(_dispositivo, **_kwargs):
        tabelle = {}
        for nome, base in COLUMNS.items():
            tabelle[nome] = {k[len(base) + 1:]: v for k, v in agent.values.items()
                             if k.startswith(base + ".")}
        return interpreta_stampante(tabelle, {})
    return leggi


class PrinterPresetTests(TestCase):
    def _poll(self, fixture, host):
        agent = FixtureAgent(FIXTURES / fixture)
        dispositivo = DispositivoSNMP.objects.create(nome=fixture, host=host, versione="v2c")
        with mock.patch("contatori.snmp.leggi_specifiche", side_effect=agent.leggi_specifiche), \
                mock.patch("contatori.printer_snmp.leggi_stampante", side_effect=_fixture_printer(agent)):
            rilevazione = interroga_dispositivo(dispositivo)
        dispositivo.refresh_from_db()
        valori = {v.sonda.nome: v for v in rilevazione.valori.select_related("sonda")}
        return dispositivo, rilevazione, valori

    def test_decodifica_errori_stampante(self):
        from contatori.printer_snmp import decodifica_errori_stampante

        self.assertEqual(decodifica_errori_stampante(bytes.fromhex("2000")), ("toner in esaurimento", "WARNING"))
        self.assertEqual(decodifica_errori_stampante("@"), ("carta esaurita", "WARNING"))
        self.assertEqual(decodifica_errori_stampante(bytes.fromhex("0000")), ("nessun errore", "OK"))
        self.assertEqual(decodifica_errori_stampante(bytes.fromhex("0c00"))[1], "ERROR")  # sportello + inceppata

    def test_canon_c5840_full_preset(self):
        dispositivo, rilevazione, valori = self._poll("canon_ir_adv_c5840.snmprec", "192.0.2.212")
        self.assertEqual(dispositivo.profilo_snmp.slug, "canon-ir-adv")
        self.assertEqual(valori["Modello"].valore_testo, "Canon iR-ADV C5840 19.43")
        self.assertEqual(valori["Firmware"].valore_testo, "19.43")
        self.assertEqual(valori["Errori rilevati"].valore_testo, "toner in esaurimento")
        self.assertEqual(valori["Errori rilevati"].stato, StatoSNMP.WARNING)
        self.assertEqual(valori["Stato dispositivo"].stato, StatoSNMP.WARNING)
        self.assertEqual(valori["Messaggio display"].valore_testo, "toner is low (black).")
        attesi = {"Totale (Total 1)": 213402, "Copie": 14671, "Stampe": 198731,
                  "Scansioni": 91977, "Fronte-retro": 3364,
                  "A4 BN Canon": 202416, "A3 BN Canon": 605, "A4 colore Canon": 9999, "A3 colore Canon": 382}
        for nome, valore in attesi.items():
            self.assertEqual(valori[nome].valore_numero, Decimal(valore), nome)
        self.assertEqual(rilevazione.stato, StatoSNMP.WARNING)
        nero = next(c for c in rilevazione.dati_stampante["consumabili"] if c["nome"].endswith("Black Toner"))
        self.assertEqual((nero["pct"], nero["tipo"], nero["colore"]), (26, "toner", "nero"))

    def test_canon_contract_counters_on_every_model(self):
        for fixture in ("canon_ir_adv_c5840.snmprec", "canon_ir_adv_c3822.snmprec",
                        "canon_ir_adv_c5535_iii.snmprec"):
            agent = FixtureAgent(FIXTURES / fixture)
            for numero in (112, 113, 122, 123, 101, 201, 301, 501, 114):
                tabella = 3 if numero in (112, 113, 122, 123) else 4
                self.assertIn(f"1.3.6.1.4.1.1602.1.11.1.{tabella}.1.4.{numero}", agent.values, fixture)

    def test_supply_below_threshold_warns(self):
        from contatori.printer_snmp import consumabili_in_esaurimento

        _d, rilevazione, _v = self._poll("canon_ir_adv_c5535_iii.snmprec", "192.0.2.219")
        bassi = consumabili_in_esaurimento(rilevazione.dati_stampante)
        self.assertTrue(bassi)
        self.assertEqual(rilevazione.stato, StatoSNMP.WARNING)

    def test_kyocera_preset_and_unconfirmed_counters_stay_off(self):
        dispositivo, rilevazione, valori = self._poll("kyocera_taskalfa_5054ci.snmprec", "192.0.2.217")
        self.assertEqual(dispositivo.profilo_snmp.slug, "kyocera")
        self.assertEqual(valori["Modello"].valore_testo, "TASKalfa 5054ci")
        self.assertEqual(valori["Errori rilevati"].valore_testo, "nessun errore")
        self.assertEqual(valori["Messaggio display"].valore_testo, "a riposo...")
        self.assertNotIn("Totale B/N (da confermare)", valori)
        self.assertEqual(rilevazione.stato, StatoSNMP.OK)

    def test_hp_designjet_detected_with_specific_prefix(self):
        dispositivo, _r, valori = self._poll("hp_designjet_t730.snmprec", "192.0.2.46")
        self.assertEqual(dispositivo.profilo_snmp.slug, "hp-printer")
        self.assertEqual(valori["Modello"].valore_testo, "HP DesignJet T730")
        self.assertEqual(valori["Errori rilevati"].valore_testo, "carta esaurita")

    def test_hp_switch_no_longer_matches_printer_profile(self):
        profilo = trova_profilo_snmp(sys_object_id="1.3.6.1.4.1.11.2.3.7.11.181",
                                     sys_description="HP J9729A 2920-48G-POE+ Switch")
        self.assertEqual(profilo.slug, "hpe-aruba")

    def test_zebra_preset(self):
        dispositivo, _r, valori = self._poll("zebra_zd421.snmprec", "192.0.2.220")
        self.assertEqual(dispositivo.profilo_snmp.slug, "zebra-printer")
        self.assertEqual(valori["Modello"].valore_testo, "Zebra Technologies ZD421")
        self.assertNotIn("Totale impressioni (Printer-MIB)", valori)


class AggregazioneMediaTests(TestCase):
    def test_media(self):
        self.assertEqual(aggrega_colonna([34, 3, 9, 4]), 34)
        self.assertEqual(aggrega_colonna([34, 3, 9, 4], "MEDIA"), 12.5)
