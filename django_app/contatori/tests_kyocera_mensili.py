"""OID sommati (Kyocera stampa + copia) e recupero delle letture mensili. Dati sintetici."""
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from . import services, snmp, tasks
from .forms import SondaSNMPForm
from .models import LetturaMensileContatori, Macchina, SondaSNMP, StatoSNMP


class SommaOidTests(SimpleTestCase):
    def _leggi(self, risposte, specifiche):
        def finto_get(host, oids, **_kw):
            return ({o: risposte[o] for o in oids if o in risposte},
                    {o: "No such object" for o in oids if o not in risposte})
        with mock.patch.object(snmp, "leggi_oids", side_effect=finto_get):
            return snmp.leggi_specifiche("192.0.2.9", specifiche)

    def test_somma_e_parti_non_esposte(self):
        valori, errori = self._leggi({"1.2.1": 10, "1.2.2": "5", "1.3": 7},
                                     [{"oid": "1.2.1+1.2.2"}, {"oid": "1.3"}])
        self.assertEqual(valori, {"1.2.1+1.2.2": 15, "1.3": 7})
        self.assertEqual(errori, {})

    def test_parte_mancante_fa_fallire_solo_la_somma(self):
        valori, errori = self._leggi({"1.2.1": 10, "1.3": 7}, [{"oid": "1.2.1+1.2.2"}, {"oid": "1.3"}])
        self.assertEqual(valori, {"1.3": 7})
        self.assertIn("1.2.1+1.2.2", errori)

    def test_parte_non_numerica(self):
        _valori, errori = self._leggi({"1.2.1": "abc", "1.2.2": 1, "1.3": 7},
                                      [{"oid": "1.2.1+1.2.2"}, {"oid": "1.3"}])
        self.assertIn("non numerico", errori["1.2.1+1.2.2"])

    def test_validatore_colonna(self):
        campo = SondaSNMP._meta.get_field("oid")
        campo.run_validators("1.3.6.1.4.1.1347.42.3.1.6.1.2.1.3+1.3.6.1.4.1.1347.42.3.1.6.1.2.2.3")
        for errato in ("1.2.3+", "+1.2.3", "1.2.3 + 1.2.4", "1.2.3+abc"):
            with self.assertRaises(ValidationError, msg=errato):
                campo.run_validators(errato)


class SommaOidFormTests(TestCase):
    def test_somma_solo_in_get(self):
        dati = {"nome": "Somma", "oid": "1.2.3+1.2.4", "tipo_valore": "NUMERO", "modalita": "WALK",
                "aggregazione": "PRIMO", "fattore": "1", "ordine": 0, "attiva": "on"}
        form = SondaSNMPForm(data=dati)
        self.assertFalse(form.is_valid())
        self.assertIn("oid", form.errors)
        form = SondaSNMPForm(data={**dati, "modalita": "GET"})
        self.assertTrue(form.is_valid(), form.errors)


class RecuperoMensileTests(TestCase):
    def setUp(self):
        self.m = Macchina.objects.create(reparto="Ufficio", matricola="SYN-M1", host="192.0.2.31")

    def test_macchina_spenta_non_fa_fallire_il_job(self):
        mese = timezone.localdate().replace(day=1).isoformat()
        with mock.patch("contatori.services._leggi_contatori_profilo"), \
                mock.patch("contatori.snmp.leggi_macchina", side_effect=snmp.SNMPError("timeout")):
            esito = tasks.leggi_mensile(self.m.pk, mese)
        self.assertTrue(esito["non_raggiungibile"])
        self.assertFalse(LetturaMensileContatori.objects.exists())
        self.m.refresh_from_db()
        self.assertEqual(self.m.snmp_stato, StatoSNMP.ERROR)

    def _mensile(self, dopo):
        mese = date(2026, 11, 1)
        chiusura = timezone.make_aware(datetime.combine(mese, time.min))
        return LetturaMensileContatori(macchina=self.m, mese=mese, rilevata_il=chiusura + dopo,
                                       a4_bn=1, a3_bn=0, a4_col=0, a3_col=0)

    def test_ritardo_rispetto_alla_chiusura(self):
        self.assertEqual(self._mensile(timedelta(minutes=10)).ritardo_testo, "")
        self.assertEqual(self._mensile(timedelta(hours=31, minutes=45)).ritardo_testo, "+31 h")
        self.assertEqual(self._mensile(timedelta(days=3, hours=2)).ritardo_testo, "+3 gg")

    def test_centrale_in_attesa_poi_saltata(self):
        def titoli(oggi):
            return [t["titolo"] for t in services.cruscotto_operativo(oggi=oggi)["da_fare"]]
        self.assertIn("1 letture mensili in attesa", titoli(date(2026, 11, 3)))
        self.assertIn("1 letture mensili saltate", titoli(date(2026, 11, 8)))
