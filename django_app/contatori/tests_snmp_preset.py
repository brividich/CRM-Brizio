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

    def test_fixture_contains_no_real_identifiers(self):
        text = SYNOLOGY.read_text(encoding="utf-8")
        self.assertNotIn("BACKUPNAS", text.upper().replace("DEVICE-1", ""))
        self.assertNotIn("|64|10.", text)


class AggregazioneMediaTests(TestCase):
    def test_media(self):
        self.assertEqual(aggrega_colonna([34, 3, 9, 4]), 34)
        self.assertEqual(aggrega_colonna([34, 3, 9, 4], "MEDIA"), 12.5)
