"""Test per la sessione visite mediche "consona" e la coerenza delle scadenze.

Spec:  docs/superpowers/specs/2026-07-15-visite-mediche-sessione-design.md
Piano: docs/superpowers/plans/2026-07-15-visite-mediche-sessione-scadenze.md
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    DocumentoDipendente,
    RuoloOperativo,
    TipoVisitaMedica,
    VisitaMedica,
)
from .services.visite import ultime_visite_correnti_ids

User = get_user_model()


class UltimeVisiteCorrentiIdsTests(TestCase):
    def setUp(self):
        self.tipo = TipoVisitaMedica.objects.create(nome="Periodica corrente", durata_mesi=12)
        self.tipo_b = TipoVisitaMedica.objects.create(nome="Audiometria corrente", durata_mesi=24)
        self.oggi = timezone.localdate()

    def test_ultima_per_coppia_dipendente_tipo(self):
        VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        recente = VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        altro_tipo = VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo_b,
            data_svolgimento=self.oggi - timedelta(days=200),
        )
        self.assertEqual(ultime_visite_correnti_ids(), {recente.pk, altro_tipo.pk})

    def test_retrodatata_inserita_dopo_non_diventa_corrente(self):
        recente = VisitaMedica.objects.create(
            legacy_anagrafica_id=2, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=5),
        )
        # Inserita DOPO (pk maggiore) ma con data più vecchia: non deve vincere.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=2, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=500),
        )
        self.assertEqual(ultime_visite_correnti_ids(), {recente.pk})

    def test_spareggio_stessa_data_vince_pk_maggiore(self):
        VisitaMedica.objects.create(
            legacy_anagrafica_id=3, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=30),
        )
        seconda = VisitaMedica.objects.create(
            legacy_anagrafica_id=3, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=30),
        )
        self.assertEqual(ultime_visite_correnti_ids(), {seconda.pk})

    def test_filtri_legacy_ids_e_tipo_ids(self):
        v1 = VisitaMedica.objects.create(
            legacy_anagrafica_id=4, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        v2 = VisitaMedica.objects.create(
            legacy_anagrafica_id=5, tipo=self.tipo_b,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        self.assertEqual(ultime_visite_correnti_ids(legacy_ids=[4]), {v1.pk})
        self.assertEqual(ultime_visite_correnti_ids(tipo_ids=[self.tipo_b.pk]), {v2.pk})


class DashboardScadenzeConfermateTests(TestCase):
    """Dopo la registrazione di una nuova visita la vecchia scadenza è
    "confermata": non deve più comparire come scaduta nella dashboard."""

    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-visite-dash", email="su-visite-dash@test.local", password="x"
        )
        self.tipo = TipoVisitaMedica.objects.create(nome="Periodica coerenza", durata_mesi=12)
        self.oggi = timezone.localdate()

    def _dashboard_body(self) -> str:
        from .views import visite_mediche_dashboard
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_dashboard(request)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", errors="ignore")

    def test_scadenza_superata_sparisce_dopo_nuova_visita(self):
        # Visita del 10-03-2024 → scadenza 10-03-2025 (passata).
        VisitaMedica.objects.create(
            legacy_anagrafica_id=70, tipo=self.tipo,
            data_svolgimento=date(2024, 3, 10),
        )
        body = self._dashboard_body()
        # Da sola è la visita corrente: la scadenza vecchia compare sia nella
        # tabella "scadute o in scadenza" sia nel log "ultime registrazioni".
        self.assertGreaterEqual(body.count("10-03-2025"), 2)

        # Rinnovo: la vecchia riga resta SOLO nel log "ultime registrazioni"
        # (storico delle registrazioni), non più tra scadute/KPI/per-tipo.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=70, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=5),
        )
        body = self._dashboard_body()
        self.assertEqual(body.count("10-03-2025"), 1)


class DigestVisiteCorrentiTests(TestCase):
    def test_digest_esclude_righe_superate(self):
        from io import StringIO
        from django.core.management import call_command

        tipo = TipoVisitaMedica.objects.create(nome="Digest corrente", durata_mesi=12)
        oggi = timezone.localdate()
        # Riga vecchia: scadrebbe tra ~20 giorni (dentro la finestra 60gg)...
        VisitaMedica.objects.create(
            legacy_anagrafica_id=90, tipo=tipo,
            data_svolgimento=oggi - timedelta(days=345),
        )
        # ...ma è stata rinnovata ieri: la corrente scade tra ~1 anno.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=90, tipo=tipo,
            data_svolgimento=oggi - timedelta(days=1),
        )
        out = StringIO()
        call_command("send_visite_mediche_digest", "--dry-run", stdout=out)
        self.assertIn("Nessuna visita medica in scadenza", out.getvalue())


class CandidatiSessioneTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Verniciatore")
        self.tipo = TipoVisitaMedica.objects.create(nome="Vernici", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)

    def _candidati(self, tipo=None):
        from .views import _build_candidati_sessione
        return _build_candidati_sessione(tipo or self.tipo, self.oggi)

    def _candidati_ids(self, tipo=None):
        return {c["legacy_id"] for c in self._candidati(tipo)}

    def test_mai_effettuata_proposta_per_ruolo(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=20, ruolo=self.ruolo)
        cand = self._candidati()
        self.assertEqual({c["legacy_id"] for c in cand}, {20})
        self.assertEqual(cand[0]["origine"], "ruolo")
        self.assertEqual(cand[0]["status"], "mai_effettuata")

    def test_cessato_escluso(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=21, ruolo=self.ruolo)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=21,
            data_cessazione=self.oggi - timedelta(days=30),
        )
        self.assertEqual(self._candidati_ids(), set())

    def test_abilitato_processo_mod128_incluso(self):
        from .models_mpq import (
            AbilitazioneProcesso, ClienteQualificante, ProcessoQualificato,
        )
        cliente = ClienteQualificante.objects.create(nome="Cliente MPQ test")
        proc = ProcessoQualificato.objects.create(nome="Saldatura speciale", cliente=cliente)
        proc.visite_richieste.add(self.tipo)
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=22, processo=proc)
        cand = [c for c in self._candidati() if c["legacy_id"] == 22]
        self.assertEqual(len(cand), 1)
        self.assertEqual(cand[0]["origine"], "processo")

    def test_ruolo_configurato_senza_assegnatari_non_degrada_a_storico(self):
        # Il tipo HA un ruolo collegato ma nessuno lo possiede: chi ha solo
        # storico (senza ruolo) NON va proposto.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=33, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        self.assertEqual(self._candidati_ids(), set())

    def test_tipo_senza_vincoli_propone_solo_storico(self):
        tipo_libero = TipoVisitaMedica.objects.create(nome="Libera", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=40, tipo=tipo_libero,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        cand = self._candidati(tipo_libero)
        self.assertEqual({c["legacy_id"] for c in cand}, {40})
        self.assertEqual(cand[0]["origine"], "storico")
        self.assertEqual(cand[0]["data_scadenza"], cand[0]["ultima_visita"].data_scadenza)

    def test_visita_senza_scadenza_non_riproposta(self):
        tipo0 = TipoVisitaMedica.objects.create(nome="Una tantum", durata_mesi=0)
        tipo0.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=50, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=50, tipo=tipo0,
            data_svolgimento=self.oggi - timedelta(days=1000),
        )
        self.assertEqual(self._candidati_ids(tipo0), set())

    def test_visita_valida_oltre_soglia_non_proposta(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=51, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=51, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        self.assertEqual(self._candidati_ids(), set())


class ApiCercaDipendenteTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo)"
                " VALUES (%s, %s, %s, %s)",
                ["m.verdi", "Marco", "Verdi", 1],
            )
            cursor.execute(
                "SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s",
                ["m.verdi"],
            )
            self.legacy_id = int(cursor.fetchone()[0])
        self.user_super = User.objects.create_superuser(
            username="su-api-visite", email="su-api-visite@test.local", password="x"
        )
        self.ruolo = RuoloOperativo.objects.create(nome="Carrellista")
        self.tipo = TipoVisitaMedica.objects.create(nome="Carrelli", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)

    def _get(self, **params):
        from .views import visite_mediche_api_cerca_dipendente
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/api/cerca-dipendente/", params)
        request.user = self.user_super
        resp = visite_mediche_api_cerca_dipendente(request)
        return json.loads(resp.content)

    def test_flag_pertinente_false_se_tipo_non_richiesto(self):
        data = self._get(q="verdi", tipo_id=str(self.tipo.pk))
        self.assertEqual(len(data["results"]), 1)
        self.assertFalse(data["results"][0]["pertinente"])

    def test_flag_pertinente_true_se_ruolo_collegato(self):
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=self.legacy_id, ruolo=self.ruolo,
        )
        data = self._get(q="verdi", tipo_id=str(self.tipo.pk))
        self.assertTrue(data["results"][0]["pertinente"])

    def test_tipo_senza_vincoli_sempre_pertinente(self):
        tipo_libero = TipoVisitaMedica.objects.create(nome="Libera api", durata_mesi=12)
        data = self._get(q="verdi", tipo_id=str(tipo_libero.pk))
        self.assertTrue(data["results"][0]["pertinente"])

    def test_cessato_escluso_dalla_ricerca(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.legacy_id,
            data_cessazione=timezone.localdate() - timedelta(days=10),
        )
        data = self._get(q="verdi", tipo_id=str(self.tipo.pk))
        self.assertEqual(data["results"], [])
