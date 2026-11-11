"""Registro cronologico, riepilogo annuale e ordine dei collegabili."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .fili import fili_del_codice
from .models import RegistroRifiuti
from .registro_annuale import registro_cronologico, riepilogo_anno

User = get_user_model()
FERRO = "12.01.01 Sfridi Ferro Kg"


def _mov(tipo, giorno, codice=FERRO, quantita=10, rif_op="", **extra):
    return RegistroRifiuti.objects.create(
        tipo=tipo, data=giorno, codice=codice,
        quantita=Decimal(str(quantita)) if quantita is not None else None,
        rif_op=rif_op, unita=extra.pop("unita", "kg"), **extra,
    )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RiepilogoAnnualeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-anno", email="anno@example.com", password="x")
        self.client.force_login(self.admin)
        # 2025: carico 100, scarico 60 → giacenza a fine 2025 = 40.
        self.c1 = _mov("C", date(2025, 11, 3), quantita=100)
        _mov("O", date(2025, 12, 1), quantita=-60, rif_op=self.c1.id_registrazione, arrivo_fir="FIR A1")
        # 2026: scarico dei 40 rimasti, nuovo carico 30.
        _mov("O", date(2026, 1, 15), quantita=-40, rif_op=self.c1.id_registrazione, arrivo_fir="FIR A2")
        self.c2 = _mov("C", date(2026, 2, 10), quantita=30)
        self.annullato = _mov("C", date(2026, 3, 1), quantita=5, annullato=True, motivo_annullamento="doppio")

    def test_riepilogo_giacenze_inizio_e_fine(self):
        (rg,) = riepilogo_anno(2026)
        self.assertEqual(rg.chiave, "120101")
        self.assertEqual(rg.giacenza_inizio, Decimal("40"))
        self.assertEqual(rg.caricato, Decimal("30"))
        self.assertEqual(rg.scaricato, Decimal("40"))
        self.assertEqual(rg.giacenza_fine, Decimal("30"))
        self.assertEqual(rg.differenza, 0)
        self.assertEqual(rg.fir, ["FIR A2"])
        (r25,) = riepilogo_anno(2025)
        self.assertEqual((r25.giacenza_inizio, r25.giacenza_fine), (Decimal(0), Decimal("40")))

    def test_cronologico_tiene_gli_annullati_in_ordine(self):
        righe = registro_cronologico(2026)
        self.assertEqual([r.tipo for r in righe], ["O", "C", "C"])
        self.assertTrue(righe[-1].annullato)

    def test_pagine_ed_export(self):
        r = self.client.get(reverse("rentri_riepilogo_annuale"), {"anno": "2026"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Riepilogo annuale 2026")
        self.assertContains(r, "12 01 01")
        r = self.client.get(reverse("rentri_riepilogo_annuale"), {"anno": "2026", "export": "pdf"})
        self.assertEqual(r["Content-Type"], "application/pdf")
        r = self.client.get(reverse("rentri_riepilogo_annuale"), {"anno": "2026", "export": "xlsx"})
        from openpyxl import load_workbook

        valori = [[c.value for c in row] for row in load_workbook(BytesIO(r.content)).active.iter_rows()]
        self.assertIn("12 01 01", [v[0] for v in valori])
        r = self.client.get(reverse("rentri_registro_cronologico"), {"anno": "2026"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF"))
        # anno non valido → anno corrente, niente errore
        self.assertEqual(self.client.get(reverse("rentri_registro_cronologico"), {"anno": "x"}).status_code, 200)


class OrdineCollegabiliTests(TestCase):
    def test_liberi_prima_poi_gia_collegati_dal_piu_recente(self):
        vecchio = _mov("C", date(2026, 1, 5), quantita=10)
        recente = _mov("C", date(2026, 3, 5), quantita=10)
        pieno = _mov("C", date(2026, 2, 5), quantita=10)
        _mov("O", date(2026, 2, 6), quantita=-10, rif_op=pieno.id_registrazione)
        voci = fili_del_codice("12 01 01", "O", tutti=True)
        self.assertEqual(
            [v["id_registrazione"] for v in voci],
            [recente.id_registrazione, vecchio.id_registrazione, pieno.id_registrazione],
        )
        self.assertEqual([v["gia_collegato"] for v in voci], [False, False, True])
