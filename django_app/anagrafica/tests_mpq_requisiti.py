"""MOD.128 MPQ — visite e DPI richiesti dal processo («Cosa serve a una persona») + conformità.

Dal 13/11 i requisiti per persona sono un solo elenco (``RequisitoPersona``):
lo stato di una persona lo dà ``mpq_persone.stato_persona``. Nessun dato reale.
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
from .models_mpq import RequisitoPersona
from .services.mpq_conformita import verifica_requisiti
from .services.mpq_persone import stato_persona


def _proc():
    cli = ClienteQualificante.objects.create(nome=f"Cli {timezone.now().microsecond}")
    return ProcessoQualificato.objects.create(nome="Processo R", cliente=cli)


def _visita(p, t):
    """Visita uguale per tutti i ruoli, che segue la durata del tipo."""
    return RequisitoPersona.objects.create(processo=p, tipo=RequisitoPersona.TIPO_VISITA, tipo_visita=t)


def _dpi(p, cat):
    return RequisitoPersona.objects.create(processo=p, tipo=RequisitoPersona.TIPO_DPI, categoria_dpi=cat)


def _stato(p, legacy_id=50):
    ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=legacy_id, processo=p,
                                             stato=AbilitazioneProcesso.STATO_ATTIVA)
    return stato_persona(ab)


class RequisitiModelTests(TestCase):
    def test_visita_requisito_persona(self):
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Sorveglianza sanitaria", durata_mesi=12)
        r = _visita(p, t)
        self.assertEqual(r.etichetta, "Sorveglianza sanitaria")
        self.assertIn(RequisitoPersona.TIPO_VISITA, RequisitoPersona.TIPI_DA_ALTRI_MODULI)


class VerificaRequisitiTests(TestCase):
    def test_nessun_requisito(self):
        p = _proc()
        r = verifica_requisiti(p, legacy_id=50)
        self.assertEqual(r["esito"], "nessuno")
        self.assertEqual(r["voci"], [])

    def test_visita_mancante_incompleto(self):
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Visita A", durata_mesi=12)
        _visita(p, t)
        r = _stato(p)  # nessuna visita registrata
        self.assertEqual(r["esito"], "incompleto")
        self.assertEqual(r["voci"][0]["stato"], "mancante")
        self.assertEqual(r["n_mancanti"], 1)

    def test_visita_scaduta_ko(self):
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Visita B", durata_mesi=12)
        _visita(p, t)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=50, tipo=t, data_svolgimento=date(2020, 1, 1))
        r = _stato(p)
        self.assertEqual(r["esito"], "ko")
        self.assertEqual(r["voci"][0]["stato"], "scaduto")

    def test_visita_valida_ok(self):
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Visita C", durata_mesi=24)
        _visita(p, t)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=50, tipo=t,
            data_svolgimento=timezone.localdate() - timedelta(days=30))
        r = _stato(p)
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
        _visita(p, t)
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=88, processo=p, stato=AbilitazioneProcesso.STATO_ATTIVA)
        tipi = tipi_visita_richiesti_per_dipendente(88)  # persona senza ruoli
        self.assertIn(t.id, [x.id for x in tipi])

    def test_senza_abilitazione_non_richiesta(self):
        from .services.visite import tipi_visita_richiesti_per_dipendente
        p = _proc()
        t = TipoVisitaMedica.objects.create(nome="Visita Z", durata_mesi=12)
        _visita(p, t)
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
        _dpi(p, cat)
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
        _dpi(p, cat)
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=77, processo=p, stato=AbilitazioneProcesso.STATO_ATTIVA)
        # persona senza mansione: l'obbligo nasce SOLO dal processo
        out = _idoneita_batch([77], {77: ""}, include_visite_dettaglio=True)
        self.assertIn(77, out)
        self.assertIn("DPI: Occhiali protettivi", out[77]["mancanti"])
