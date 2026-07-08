"""Collegamento anagrafica lavorativa <-> AreaAziendale (Fase 2 dell'inversione
gerarchia Reparto/AreaAziendale, spec 2026-07-08-anagrafica-lavorativa-area-aziendale).

Copre: la FK area_aziendale sul dipendente, la sincronizzazione centralizzata in
_sync_aziendale_from_reparto (invariante area<->reparto), le due viste che la
scrivono (mini-form rapido + form completo), il context/markup del cascading in
dipendente_detail, il match per ID in training_eligibility, e il report di sola
lettura sulle regole di formazione per area.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteAreaAziendaleFieldTests(TestCase):
    """Il dipendente si collega alla nuova AreaAziendale con una FK vera (non più
    il CharField area_aziendale_nome, rimosso con l'inversione gerarchia)."""

    def test_dipendente_ha_fk_area_aziendale_non_piu_charfield(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        az = DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=901, area="UT", area_aziendale=area,
        )
        self.assertFalse(hasattr(az, "area_aziendale_nome"))
        self.assertEqual(az.area_aziendale_id, area.pk)

    def test_area_aziendale_nullable(self):
        az = DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=902)
        self.assertIsNone(az.area_aziendale_id)

    def test_elimina_area_aziendale_azzera_riferimento_dipendente(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        az = DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=903, area_aziendale=area,
        )
        area.delete()
        az.refresh_from_db()
        self.assertIsNone(az.area_aziendale_id)
