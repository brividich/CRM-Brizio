"""Uniformare i codici, carichi fermi in deposito, unità usate, andamento annuale."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import RegistroRifiuti
from .uniforma import descrizione_da_testo, proposte

User = get_user_model()


def _mov(tipo, giorno, codice, quantita=10, rif_op="", **extra):
    return RegistroRifiuti.objects.create(
        tipo=tipo, data=giorno, codice=codice,
        quantita=Decimal(str(quantita)) if quantita is not None else None,
        rif_op=rif_op, unita=extra.pop("unita", "kg"), **extra,
    )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class UniformaCodiciTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-unif", email="unif@example.com", password="x")
        self.client.force_login(self.admin)
        g = date(2026, 3, 1)
        self.a = _mov("C", g, "12.01.01 Sfridi Ferro Kg")
        self.b = _mov("C", g, "12.01.01 Sfridi Ferro Kg", salva=True)
        self.c = _mov("C", g, "12 01 01")
        self.ann = _mov("C", g, "12.01.01 vecchio", annullato=True, motivo_annullamento="prova")
        self.ok = _mov("C", g, "15 01 03 Imballaggi in legno")

    def test_descrizione(self):
        self.assertEqual(descrizione_da_testo("12.01.01 Sfridi Ferro Kg"), "Sfridi Ferro")
        self.assertEqual(descrizione_da_testo("08.01.11 * Vernice di Scarto pericolosa Kg"), "Vernice di Scarto pericolosa")
        self.assertEqual(descrizione_da_testo("12 01 01"), "")
        self.assertEqual(descrizione_da_testo("20.01.21 * Luci led e lampadineKg"), "Luci led e lampadine")

    def test_proposte_solo_codici_da_uniformare(self):
        (p,) = proposte()
        self.assertEqual(p["chiave"], "120101")
        self.assertEqual(p["proposta"], "12 01 01 Sfridi Ferro")
        self.assertEqual(p["da_cambiare"], 3)
        self.assertEqual(p["consolidate"], 1)

    def test_applica_con_audit_e_annullati_intatti(self):
        r = self.client.post(reverse("rentri_uniforma_codici"), {"codice": ["120101"], "testo_120101": "12 01 01 Sfridi di ferro"})
        self.assertEqual(r.status_code, 302)
        for x in (self.a, self.b, self.c):
            x.refresh_from_db()
            self.assertEqual(x.codice, "12 01 01 Sfridi di ferro")
        self.ann.refresh_from_db()
        self.assertEqual(self.ann.codice, "12.01.01 vecchio")
        self.assertEqual(proposte(), [])
        from core.models import AuditLog

        self.assertTrue(AuditLog.objects.filter(azione="rentri_codice_uniformato", oggetto_id=str(self.a.pk)).exists())

    def test_non_si_cambia_il_codice(self):
        self.client.post(reverse("rentri_uniforma_codici"), {"codice": ["120101"], "testo_120101": "12 01 02 Altro"})
        self.a.refresh_from_db()
        self.assertEqual(self.a.codice, "12.01.01 Sfridi Ferro Kg")

    def test_verifica_mostra_la_sezione_ai_gestori(self):
        r = self.client.get(reverse("rentri_verifica"))
        self.assertContains(r, "Codici scritti in modi diversi")
        self.assertContains(r, 'value="12 01 01 Sfridi Ferro"')


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FormAiutiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-aiuti", email="aiuti@example.com", password="x")
        self.client.force_login(self.admin)

    def test_carichi_fermi_in_cima_con_giorni(self):
        oggi = timezone.localdate()
        recente = _mov("C", oggi - timedelta(days=3), "12 01 01")
        fermo = _mov("C", oggi - timedelta(days=400), "12 01 01")
        r = self.client.get(reverse("rentri_api_candidati_rif_op"), {"tipo": "O", "codice": "12 01 01"})
        cand = r.json()["candidati"]
        self.assertEqual([c["id_registrazione"] for c in cand], [fermo.id_registrazione, recente.id_registrazione])
        self.assertEqual(cand[0]["tono"], "rosso")
        self.assertEqual(cand[0]["giorni"], 400)
        self.assertEqual(cand[1]["tono"], "")

    def test_unita_usate(self):
        g = date(2026, 3, 1)
        _mov("C", g, "12 01 01", unita="kg")
        _mov("C", g, "12.01.01 Ferro", unita="kg")
        _mov("C", g, "12 01 01", unita="l")
        r = self.client.get(reverse("rentri_api_cer_info"), {"codice": "12 01 01"})
        self.assertEqual(r.json()["unita_usate"], [["kg", 2], ["l", 1]])

    def test_riepilogo_andamento(self):
        _mov("C", date(2025, 5, 1), "12 01 01", quantita=100)
        _mov("C", date(2026, 5, 1), "12 01 01", quantita=150)
        r = self.client.get(reverse("rentri_riepilogo_annuale"), {"anno": "2026"})
        self.assertContains(r, "Andamento per anno (kg)")
        self.assertContains(r, "+50%")
        serie = {s["anno"]: s["caricato"] for s in r.context["andamento"]["serie"]}
        self.assertEqual(serie[2025], 100.0)
        self.assertEqual(serie[2026], 150.0)
