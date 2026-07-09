"""Digest mattutino caporeparto (AU51): aggregazione DPI + incidenti + invio.

Ambito verificato/offline: DPI in attesa (via richiedente_legacy_id) + incidenti
aperti (via nome reparto). Assenze (SharePoint, legame dismesso) e ticket (nessun
legame reparto) sono esclusi per design.
"""
from __future__ import annotations

from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from anagrafica.models import DipendenteAnagraficaAziendale, Reparto
from anagrafica.tests import _ensure_anagrafica_table
from core.caporeparto_digest import build_caporeparto_digest
from dpi.models import CategoriaDPI, RichiestaDPI, StatoRichiesta
from rilevazione_incidenti.models import RilevazioneIncidente

CAPO = 900


def _setup_capo_reparto():
    _ensure_anagrafica_table()
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO anagrafica_dipendenti (id, nome, cognome, email_notifica, attivo) "
            "VALUES (900, 'Capo', 'Reparto', 'capo@x.local', 1)"
        )
    rep = Reparto.objects.create(nome="Saldatura", caporeparto_legacy_id=CAPO)
    DipendenteAnagraficaAziendale.objects.create(
        legacy_anagrafica_id=711, caporeparto_legacy_id=CAPO)
    return rep


class CaporepartoDigestBuildTests(TestCase):
    def test_aggrega_dpi_in_attesa_e_incidenti_aperti(self):
        _setup_capo_reparto()
        cat = CategoriaDPI.objects.create(nome="Guanti")
        RichiestaDPI.objects.create(
            numero="DPI-2026-0001", richiedente_nome="Tizio",
            richiedente_legacy_id=711, categoria=cat,
            stato=StatoRichiesta.INVIATA)
        # DPI consegnata: non deve contare
        RichiestaDPI.objects.create(
            numero="DPI-2026-0002", richiedente_nome="Tizio",
            richiedente_legacy_id=711, categoria=cat,
            stato=StatoRichiesta.CONSEGNATA)
        RilevazioneIncidente.objects.create(reparto="Saldatura", chiusura_rspp=False)
        RilevazioneIncidente.objects.create(reparto="Saldatura", chiusura_rspp=True)   # chiuso
        RilevazioneIncidente.objects.create(reparto="Verniciatura", chiusura_rspp=False)  # altro reparto

        d = build_caporeparto_digest(CAPO)
        self.assertEqual(d["email"], "capo@x.local")
        self.assertEqual(len(d["dpi"]), 1)
        self.assertEqual(len(d["incidenti"]), 1)
        self.assertEqual(d["totale"], 2)


class CaporepartoDigestCommandTests(TestCase):
    def test_invia_email_al_capo_quando_ci_sono_voci(self):
        _setup_capo_reparto()
        cat = CategoriaDPI.objects.create(nome="Guanti")
        RichiestaDPI.objects.create(
            numero="DPI-2026-0001", richiedente_nome="Tizio",
            richiedente_legacy_id=711, categoria=cat,
            stato=StatoRichiesta.INVIATA)
        out = StringIO()
        call_command("send_caporeparto_morning_digest", stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["capo@x.local"])

    def test_noop_senza_voci(self):
        _setup_capo_reparto()
        out = StringIO()
        call_command("send_caporeparto_morning_digest", stdout=out)
        self.assertEqual(len(mail.outbox), 0)
