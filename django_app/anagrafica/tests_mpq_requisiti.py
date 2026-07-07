"""MOD.128 MPQ — requisiti del processo (corsi/DPI/visite) + conformità.

Un processo qualificato può dichiarare requisiti (come una mansione di rischio).
Il servizio ``mpq_conformita.verifica_requisiti`` verifica, per una persona
abilitata, se li possiede. Test tramite le **visite** (fixture leggere; la logica
di corsi/DPI è simmetrica). Nessun dato reale.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from .models import (
    AbilitazioneProcesso,
    ClienteQualificante,
    ProcessoQualificato,
    TipoVisitaMedica,
    VisitaMedica,
)
from .services.mpq_conformita import verifica_requisiti


def _proc():
    cli = ClienteQualificante.objects.create(nome=f"Cli {timezone.now().microsecond}")
    return ProcessoQualificato.objects.create(nome="Processo R", cliente=cli)


class RequisitiModelTests(TestCase):
    def test_visite_richieste_m2m(self):
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Sorveglianza sanitaria", durata_mesi=12)
        p.visite_richieste.add(t)
        self.assertEqual(p.visite_richieste.count(), 1)
        # gli altri campi requisito esistono (manager accessibile)
        self.assertEqual(p.corsi_richiesti.count(), 0)
        self.assertEqual(p.dpi_richiesti.count(), 0)


class VerificaRequisitiTests(TestCase):
    def test_nessun_requisito(self):
        p = _proc()
        r = verifica_requisiti(p, legacy_id=50)
        self.assertEqual(r["esito"], "nessuno")
        self.assertEqual(r["voci"], [])

    def test_visita_mancante_incompleto(self):
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Visita A", durata_mesi=12)
        p.visite_richieste.add(t)
        r = verifica_requisiti(p, legacy_id=50)  # nessuna visita registrata
        self.assertEqual(r["esito"], "incompleto")
        self.assertEqual(r["voci"][0]["stato"], "mancante")
        self.assertEqual(r["n_mancanti"], 1)

    def test_visita_scaduta_ko(self):
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Visita B", durata_mesi=12)
        p.visite_richieste.add(t)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=50, tipo=t, data_svolgimento=date(2020, 1, 1))
        r = verifica_requisiti(p, legacy_id=50)
        self.assertEqual(r["esito"], "ko")
        self.assertEqual(r["voci"][0]["stato"], "scaduto")

    def test_visita_valida_ok(self):
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Visita C", durata_mesi=24)
        p.visite_richieste.add(t)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=50, tipo=t,
            data_svolgimento=timezone.localdate() - timedelta(days=30))
        r = verifica_requisiti(p, legacy_id=50)
        self.assertEqual(r["esito"], "ok")
        self.assertEqual(r["voci"][0]["stato"], "ok")


class VisiteBidirezionaliTests(TestCase):
    """La visita richiesta da un processo entra nello scadenzario della persona
    abilitata anche se non deriva da un ruolo operativo (bidirezionalità)."""

    def test_visita_processo_nei_richiesti(self):
        from .services.visite import tipi_visita_richiesti_per_dipendente
        p = _proc()
        # obbligatoria=False: è il processo a renderla obbligatoria, non il tipo
        t = TipoVisitaMedica.objects.create(
            nome="Visita da processo", durata_mesi=12, obbligatoria=False)
        p.visite_richieste.add(t)
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=88, processo=p, stato=AbilitazioneProcesso.STATO_ATTIVA)
        tipi = tipi_visita_richiesti_per_dipendente(88)  # persona senza ruoli
        self.assertIn(t.id, [x.id for x in tipi])

    def test_senza_abilitazione_non_richiesta(self):
        from .services.visite import tipi_visita_richiesti_per_dipendente
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Visita Z", durata_mesi=12)
        p.visite_richieste.add(t)
        # legacy 999 non abilitato → nessuna visita da processo
        self.assertEqual(tipi_visita_richiesti_per_dipendente(999), [])


class DpiIdoneitaBidirezionaleTests(TestCase):
    """I DPI richiesti da un processo entrano nell'idoneità della persona
    abilitata (semaforo conformità), riusando il resolver esistente."""

    def test_requisiti_processo_per_legacy(self):
        from dpi.models import CategoriaDPI
        from .services.mpq_idoneita import requisiti_processo_per_legacy
        p = _proc()
        cat = CategoriaDPI.objects.create(nome="Guanti anticalore")
        p.dpi_richiesti.add(cat)
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=88, processo=p, stato=AbilitazioneProcesso.STATO_ATTIVA)
        req = requisiti_processo_per_legacy([88])
        self.assertIn(cat, req[88]["dpi"])

    def test_idoneita_include_dpi_processo(self):
        from dpi.models import CategoriaDPI
        from .services.conformita import _idoneita_batch
        p = _proc()
        cat = CategoriaDPI.objects.create(
            nome="Occhiali protettivi", obbligatoria_mansionario=False)
        p.dpi_richiesti.add(cat)
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=77, processo=p, stato=AbilitazioneProcesso.STATO_ATTIVA)
        # persona senza mansione: l'obbligo nasce SOLO dal processo
        out = _idoneita_batch([77], {77: ""}, include_visite_dettaglio=True)
        self.assertIn(77, out)
        self.assertIn("DPI: Occhiali protettivi", out[77]["mancanti"])
