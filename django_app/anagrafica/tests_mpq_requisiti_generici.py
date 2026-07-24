"""MOD.128 MPQ — requisiti GENERICI tipizzati (1.14, ampliamento 1-N).

Oltre ai tre M2M fissi (corsi/DPI/visite) un processo può dichiarare requisiti
generici tipizzati con scadenza/stato propri: audit, certificato, esame,
esperienza, visione, rif. normativo, altro. Sono requisiti a livello **processo**
(attestazione unica, non per-persona), con evidenza allegabile. La conformità li
valuta insieme ai requisiti per-persona. Nessun dato reale.
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import (
    ClienteQualificante,
    ProcessoQualificato,
    RequisitoQualifica,
)
from .services.mpq_conformita import verifica_requisiti


def _proc():
    cli = ClienteQualificante.objects.create(nome=f"Cli {timezone.now().microsecond}")
    return ProcessoQualificato.objects.create(nome="Processo RG", cliente=cli)


class RequisitoQualificaModelTests(TestCase):
    def test_creazione_e_relazione(self):
        p = _proc()
        r = RequisitoQualifica.objects.create(
            processo=p, tipo=RequisitoQualifica.TIPO_AUDIT,
            descrizione="Audit annuale NADCAP AC7004",
        )
        self.assertEqual(p.requisiti.count(), 1)
        self.assertEqual(r.stato, RequisitoQualifica.STATO_DA_VERIFICARE)
        self.assertTrue(r.obbligatorio)

    def test_scaduto_flag_da_data(self):
        p = _proc()
        r = RequisitoQualifica.objects.create(
            processo=p, tipo=RequisitoQualifica.TIPO_CERTIFICATO,
            descrizione="Certificato X", stato=RequisitoQualifica.STATO_SODDISFATTO,
            data_scadenza=timezone.localdate() - timedelta(days=1),
        )
        self.assertTrue(r.is_scaduto)


class VerificaRequisitiGenericiTests(TestCase):
    def test_requisito_da_verificare_incompleto(self):
        p = _proc()
        RequisitoQualifica.objects.create(
            processo=p, tipo=RequisitoQualifica.TIPO_AUDIT, descrizione="Audit A")
        r = verifica_requisiti(p, legacy_id=50)
        self.assertEqual(r["esito"], "incompleto")
        self.assertEqual(r["voci"][0]["stato"], "mancante")
        self.assertEqual(r["voci"][0]["tipo"], "Audit")

    def test_requisito_scaduto_ko(self):
        p = _proc()
        RequisitoQualifica.objects.create(
            processo=p, tipo=RequisitoQualifica.TIPO_CERTIFICATO, descrizione="Cert",
            stato=RequisitoQualifica.STATO_SODDISFATTO,
            data_scadenza=timezone.localdate() - timedelta(days=5))
        r = verifica_requisiti(p, legacy_id=50)
        self.assertEqual(r["esito"], "ko")
        self.assertEqual(r["voci"][0]["stato"], "scaduto")

    def test_requisito_soddisfatto_ok(self):
        p = _proc()
        RequisitoQualifica.objects.create(
            processo=p, tipo=RequisitoQualifica.TIPO_ESAME, descrizione="Esame",
            stato=RequisitoQualifica.STATO_SODDISFATTO)
        r = verifica_requisiti(p, legacy_id=50)
        self.assertEqual(r["esito"], "ok")
        self.assertEqual(r["voci"][0]["stato"], "ok")

    def test_non_obbligatorio_mancante_non_degrada(self):
        p = _proc()
        RequisitoQualifica.objects.create(
            processo=p, tipo=RequisitoQualifica.TIPO_ALTRO, descrizione="Facoltativo",
            obbligatorio=False)
        r = verifica_requisiti(p, legacy_id=50)
        # la voce compare ma l'esito non degrada a incompleto
        self.assertEqual(len(r["voci"]), 1)
        self.assertEqual(r["esito"], "ok")
        self.assertEqual(r["n_mancanti"], 0)

    def test_non_applicabile_na(self):
        p = _proc()
        RequisitoQualifica.objects.create(
            processo=p, tipo=RequisitoQualifica.TIPO_VISIONE, descrizione="Test visivo",
            stato=RequisitoQualifica.STATO_NON_APPLICABILE)
        r = verifica_requisiti(p, legacy_id=50)
        self.assertEqual(r["voci"][0]["stato"], "na")
        self.assertEqual(r["esito"], "ok")

    def test_requisito_disattivo_escluso(self):
        p = _proc()
        RequisitoQualifica.objects.create(
            processo=p, tipo=RequisitoQualifica.TIPO_AUDIT, descrizione="Vecchio",
            attivo=False)
        r = verifica_requisiti(p, legacy_id=50)
        self.assertEqual(r["voci"], [])
        self.assertEqual(r["esito"], "nessuno")
