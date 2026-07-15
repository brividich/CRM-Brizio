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
