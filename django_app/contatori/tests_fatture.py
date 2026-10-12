"""Fatture da interfaccia e riconciliazione operativa. Dati sintetici."""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from . import services
from .models import Fattura, LetturaContatori, Macchina, RigaFattura
from .tests import _AuthedClientMixin


def _righe_post(righe, iniziali=0):
    data = {"righe-TOTAL_FORMS": str(len(righe)), "righe-INITIAL_FORMS": str(iniziali),
            "righe-MIN_NUM_FORMS": "0", "righe-MAX_NUM_FORMS": "1000"}
    for i, riga in enumerate(righe):
        for k, v in riga.items():
            data[f"righe-{i}-{k}"] = v
    return data


class FattureTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = Macchina.objects.create(reparto="Ufficio A", matricola="SYN-A", contratto="C-1")
        self.b = Macchina.objects.create(reparto="Ufficio B", matricola="SYN-B", contratto="C-1")
        self.c = Macchina.objects.create(reparto="Officina", matricola="SYN-C", contratto="C-2")
        self.testata = {"numero": "F-100", "data": "2026-07-05", "fornitore": "BASE",
                        "trimestre": "2026-Q2", "periodo_dal": "2026-04-01", "periodo_al": "2026-06-30"}

    def test_nuova_fattura_precompila_contratti_attivi(self):
        r = self.client.get(reverse("contatori:fattura_nuova") + "?trimestre=2026-Q2")
        self.assertEqual(r.status_code, 200)
        righe = r.context["righe"]
        self.assertEqual([f.initial["contratto"] for f in righe.forms], ["C-1", "C-2"])
        self.assertEqual(righe.forms[0].initial["descrizione"], "Ufficio A + Ufficio B")
        self.assertEqual(r.context["form"]["trimestre"].value(), "2026-Q2")

    def test_salva_fattura_ignora_righe_vuote(self):
        data = {**self.testata, **_righe_post([
            {"contratto": "C-1", "descrizione": "pool", "a4_bn": "100", "a3_bn": "0", "a4_col": "5", "a3_col": "0"},
            {"contratto": "C-2", "descrizione": "", "a4_bn": "0", "a3_bn": "0", "a4_col": "0", "a3_col": "0"},
        ])}
        # La seconda riga ricalca l'iniziale (non modificata): non va salvata.
        r = self.client.post(reverse("contatori:fattura_nuova"), data)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["righe"].errors)
        fattura = Fattura.objects.get(numero="F-100")
        self.assertEqual(list(fattura.righe.values_list("contratto", flat=True)), ["C-1"])

    def test_contratto_sconosciuto_bloccato(self):
        data = {**self.testata, **_righe_post([
            {"contratto": "XX", "a4_bn": "1", "a3_bn": "0", "a4_col": "0", "a3_col": "0"}])}
        r = self.client.post(reverse("contatori:fattura_nuova"), data)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Fattura.objects.exists())
        self.assertIn("contratto", r.context["righe"].forms[0].errors)

    def test_periodo_invertito_bloccato(self):
        data = {**self.testata, "periodo_dal": "2026-07-01", **_righe_post([])}
        r = self.client.post(reverse("contatori:fattura_nuova"), data)
        self.assertEqual(r.status_code, 200)
        self.assertIn("periodo_al", r.context["form"].errors)

    def test_modifica_ed_elimina(self):
        f = Fattura.objects.create(numero="F-1", data=date(2026, 7, 1), trimestre="2026-Q2",
                                   periodo_al=date(2026, 6, 30))
        riga = RigaFattura.objects.create(fattura=f, contratto="C-2", a4_bn=10)
        data = {**self.testata, "numero": "F-1", **_righe_post([
            {"id": str(riga.pk), "contratto": "C-2", "a4_bn": "12", "a3_bn": "0", "a4_col": "0", "a3_col": "0"}],
            iniziali=1)}
        r = self.client.post(reverse("contatori:fattura_edit", args=[f.pk]), data)
        self.assertEqual(r.status_code, 302)
        riga.refresh_from_db()
        self.assertEqual(riga.a4_bn, 12)
        r = self.client.post(reverse("contatori:fattura_elimina", args=[f.pk]))
        self.assertRedirects(r, reverse("contatori:riconciliazione_trim", args=["2026-Q2"]))
        self.assertFalse(Fattura.objects.exists())

    def test_riconciliazione_mostra_letture_mancanti_con_link(self):
        f = Fattura.objects.create(numero="F-2", data=date(2026, 7, 1), trimestre="2026-Q2",
                                   periodo_al=date(2026, 6, 30))
        RigaFattura.objects.create(fattura=f, contratto="C-1", a4_bn=100)
        LetturaContatori.objects.create(macchina=self.a, trimestre="2026-Q2", data=date(2026, 7, 3), a4_bn=60)
        righe, riepilogo = services.riconcilia("2026-Q2")
        self.assertEqual(riepilogo["letture_mancanti"], 1)
        self.assertEqual([m.pk for m in righe[0]["mancanti"]], [self.b.pk])
        r = self.client.get(reverse("contatori:riconciliazione_trim", args=["2026-Q2"]))
        self.assertContains(r, f"?macchina={self.b.pk}&amp;trimestre=2026-Q2")

    def test_riconciliazione_senza_fattura_invita_a_inserirla(self):
        LetturaContatori.objects.create(macchina=self.c, trimestre="2026-Q2", data=date(2026, 7, 3))
        r = self.client.get(reverse("contatori:riconciliazione_trim", args=["2026-Q2"]))
        self.assertContains(r, "Nessuna fattura caricata")

    def test_lettura_precompilata_da_link(self):
        r = self.client.get(reverse("contatori:importa_lettura") + f"?macchina={self.b.pk}&trimestre=2026-Q2")
        self.assertEqual(str(r.context["form"]["macchina"].value()), str(self.b.pk))
        self.assertEqual(r.context["form"]["trimestre"].value(), "2026-Q2")


class TrimestriTests(TestCase):
    def test_trimestre_di_e_validazione(self):
        self.assertEqual(services.trimestre_di(date(2026, 11, 3)), "2026-Q4")
        self.assertTrue(services.trimestre_valido("2026-Q1"))
        self.assertFalse(services.trimestre_valido("2026-Q5"))
        self.assertFalse(services.trimestre_valido("Q1-2026"))

    def test_opzioni_includono_corrente_e_precedenti(self):
        opzioni = services.opzioni_trimestri(indietro=4)
        self.assertEqual(opzioni[0], services.trimestre_corrente())
        self.assertEqual(len(opzioni), 5)


class RiconciliazioneTotaliTests(_AuthedClientMixin, TestCase):
    """Fattura «solo totali» (Copylab): B/N e colore contro A4 + A3 interni, anche in pool."""

    def setUp(self):
        super().setUp()
        self.a = Macchina.objects.create(reparto="Prove A", matricola="SYN-TA", contratto="K-T")
        self.b = Macchina.objects.create(reparto="Prove B", matricola="SYN-TB", contratto="K-T")
        self.f = Fattura.objects.create(numero="CL-1", data=date(2026, 7, 5), fornitore="COPYLAB",
                                        dettaglio=Fattura.Dettaglio.TOTALI, trimestre="2026-Q2",
                                        periodo_al=date(2026, 6, 30))
        RigaFattura.objects.create(fattura=self.f, contratto="K-T", a4_bn=1000, a4_col=300)
        LetturaContatori.objects.create(macchina=self.a, trimestre="2026-Q2", data=date(2026, 7, 3),
                                        a4_bn=500, a3_bn=100, a4_col=100, a3_col=20)
        LetturaContatori.objects.create(macchina=self.b, trimestre="2026-Q2", data=date(2026, 7, 3),
                                        a4_bn=350, a3_bn=60, a4_col=150, a3_col=10)

    def test_totali_confrontati_con_a4_piu_a3_del_pool(self):
        righe, riepilogo = services.riconcilia("2026-Q2")
        self.assertEqual([(r["contatore"], r["fornitore"], r["ns"], r["scarto"]) for r in righe],
                         [("BN totale", 1000, 1010, 10), ("COL totale", 300, 280, -20)])
        self.assertEqual(riepilogo["anomalie"], 1)
        gruppo = riepilogo["gruppi"][0]
        self.assertTrue(gruppo["pool"] and gruppo["totali"])
        self.assertEqual(gruppo["livello"], "danger")
        self.assertEqual(gruppo["copie_in_eccesso"], 20)
        self.assertEqual([x["giorni"] for x in gruppo["macchine"]], [3, 3])
        self.assertEqual([(m.pk, v) for m, v in righe[0]["per_macchina"]],
                         [(self.a.pk, 600), (self.b.pk, 410)])

    def test_pagina_schede_e_filtro_da_verificare(self):
        c = Macchina.objects.create(reparto="Solo", matricola="SYN-TC", contratto="K-OK")
        RigaFattura.objects.create(fattura=self.f, contratto="K-OK", a4_bn=10, a4_col=1)
        LetturaContatori.objects.create(macchina=c, trimestre="2026-Q2", data=date(2026, 7, 3),
                                        a4_bn=10, a4_col=1)
        url = reverse("contatori:riconciliazione_trim", args=["2026-Q2"])
        r = self.client.get(url)
        self.assertContains(r, "pool · 2 MFC")
        self.assertContains(r, "Solo totali B/N e colore")
        self.assertContains(r, "Da controllare · 20 copie fatturate in più")
        self.assertEqual(len(r.context["gruppi"]), 2)
        r = self.client.get(url + "?vista=da-verificare")
        self.assertEqual([g["contratto"] for g in r.context["gruppi"]], ["K-T"])

    def test_salvataggio_senza_dettaglio_resta_per_formato(self):
        data = {"numero": "F-9", "data": "2026-07-05", "fornitore": "BASE", "trimestre": "2026-Q2",
                "periodo_dal": "2026-04-01", "periodo_al": "2026-06-30",
                **_righe_post([{"contratto": "K-T", "a4_bn": "5", "a3_bn": "0", "a4_col": "0", "a3_col": "0"}])}
        self.client.post(reverse("contatori:fattura_nuova"), data)
        self.assertEqual(Fattura.objects.get(numero="F-9").dettaglio, Fattura.Dettaglio.FORMATO)

    def test_guida(self):
        r = self.client.get(reverse("contatori:riconciliazione_guida"))
        self.assertContains(r, "Più MFC sullo stesso contratto (pool)")
        self.assertContains(r, "COPIE EFFETTUATE COLORE")
