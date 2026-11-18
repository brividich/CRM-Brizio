"""Tessere KPI dei fornitori: portano all'elenco che conta lo stesso numero. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore, FornitoreOrdine

from .models import TecnicoFornitore


class KpiLinkTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("kpi_forn", "kpi@example.local", "x"))
        self.attivi = [Fornitore.objects.create(ragione_sociale=f"Ditta Attiva {i}") for i in range(3)]
        self.inattivi = [Fornitore.objects.create(ragione_sociale=f"Ditta Ferma {i}", is_active=False) for i in range(2)]
        oggi = timezone.localdate()
        FornitoreOrdine.objects.create(fornitore=self.attivi[0], data_ordine=oggi, importo=Decimal("100"))
        FornitoreOrdine.objects.create(fornitore=self.attivi[0], data_ordine=oggi, importo=Decimal("40"),
                                       stato=FornitoreOrdine.STATO_ANNULLATO)

    def _lista(self, query):
        return self.client.get(reverse("fornitori:fornitori_list") + query).context["page_obj"].paginator.count

    def test_cruscotto_attivi_e_inattivi(self):
        r = self.client.get(reverse("fornitori:index"))
        lista = reverse("fornitori:fornitori_list")
        self.assertContains(r, f'href="{lista}?attivi=1"')
        self.assertContains(r, f'href="{lista}?attivi=0"')
        self.assertEqual(self._lista("?attivi=1"), r.context["n_fornitori"])
        self.assertEqual(self._lista("?attivi=0"), r.context["n_fornitori_inattivi"])
        self.assertEqual(r.context["n_fornitori_inattivi"], 2)

    def test_elenco_totali_attivi_e_inattivi(self):
        r = self.client.get(reverse("fornitori:fornitori_list"))
        lista = reverse("fornitori:fornitori_list")
        self.assertContains(r, f'href="{lista}?attivi=tutti"')
        self.assertEqual(self._lista("?attivi=tutti"), r.context["stats_totale"])
        self.assertEqual(self._lista("?attivi=1"), r.context["stats_attivi"])
        # Prima «add:"-"» dava stringa vuota: il numero degli inattivi non compariva.
        self.assertContains(r, "2 inattivi")

    def test_filtro_inattivi_resta_nella_paginazione(self):
        r = self.client.get(reverse("fornitori:fornitori_list") + "?attivi=0")
        self.assertIn("attivi=0", r.context["query_filtri"])
        self.assertContains(r, "Togli il filtro")

    def test_spesa_esclude_gli_annullati(self):
        self.assertEqual(self.client.get(reverse("fornitori:index")).context["spesa_totale"], Decimal("100"))
        self.assertEqual(self.client.get(reverse("fornitori:fornitori_list")).context["spesa_totale"], Decimal("100"))
        r = self.client.get(reverse("fornitori:fornitore_detail", args=[self.attivi[0].pk]))
        self.assertEqual(r.context["spesa_totale"], Decimal("100"))
        for scheda in ("#tab-ordini", "#tab-val", "#tab-asset"):
            self.assertContains(r, f'href="{scheda}"')

    def test_scadenze_filtrate_contano_come_le_tessere(self):
        f = self.attivi[1]
        oggi = timezone.localdate()
        for giorni, nome in ((-5, "Tecnico Uno"), (10, "Tecnico Due"), (200, "Tecnico Tre")):
            TecnicoFornitore.objects.create(fornitore=f, nome=nome, attestati_fino_al=oggi + timedelta(days=giorni))
        url = reverse("fornitori:fornitore_sezione", args=[f.pk, "scadenze"])
        tutte = self.client.get(url).context
        for stato, chiave in (("scaduta", "n_scadute"), ("in_scadenza", "n_in_scadenza")):
            with self.subTest(stato=stato):
                r = self.client.get(f"{url}?stato={stato}")
                self.assertEqual(len(r.context["voci_mostrate"]), tutte[chiave])
                self.assertEqual(r.context[chiave], tutte[chiave])
                self.assertEqual(tutte[chiave], 1)
        self.assertEqual(self.client.get(f"{url}?stato=boh").context["filtro_stato"], "")


class CopieKpiLinkTests(TestCase):
    """Scheda «Copie MFC»: le tessere aprono gli elenchi di Contatori filtrati sul fornitore."""

    def setUp(self):
        from datetime import date

        from contatori.models import Fattura, LetturaContatori, Macchina

        self.client.force_login(get_user_model().objects.create_superuser("kpi_copie", "kpic@example.local", "x"))
        self.base = Fornitore.objects.create(ragione_sociale="BASE SPA")
        m1 = Macchina.objects.create(reparto="Ufficio A", matricola="SYN-B1", fornitore="BASE", contratto="C-B1")
        Macchina.objects.create(reparto="Ufficio B", matricola="SYN-B2", fornitore="BASE", attiva=False)
        altra = Macchina.objects.create(reparto="Ufficio C", matricola="SYN-C1", fornitore="COPYLAB")
        for numero, trimestre, fornitore in (("FB-1", "2025-Q1", "BASE"), ("FB-2", "2025-Q3", "BASE"),
                                             ("FC-1", "2025-Q2", "COPYLAB")):
            anno, q = int(trimestre[:4]), int(trimestre[-1])
            Fattura.objects.create(numero=numero, data=date(anno, q * 3, 28), trimestre=trimestre,
                                   periodo_al=date(anno, q * 3, 28), fornitore=fornitore)
        # 2025-Q2: letture della macchina BASE senza fattura BASE (la fattura è di un altro fornitore).
        LetturaContatori.objects.create(macchina=m1, trimestre="2025-Q2", data=date(2025, 7, 1))
        LetturaContatori.objects.create(macchina=altra, trimestre="2025-Q4", data=date(2026, 1, 2))

    def test_tessere_e_elenchi_contatori_contano_uguale(self):
        r = self.client.get(reverse("fornitori:fornitore_sezione", args=[self.base.pk, "copie"]))
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        self.assertEqual((ctx["macchine_attive"], len(ctx["fatture"]), ctx["scoperti"]), (1, 2, ["2025-Q2"]))
        self.assertEqual(ctx["query_fornitore"], "fornitore=BASE")
        macchine = reverse("contatori:macchine") + "?fornitore=BASE"
        fatture = reverse("contatori:fatture") + "?fornitore=BASE"
        self.assertContains(r, f'href="{macchine}"')
        self.assertContains(r, f'href="{fatture}"', count=2)
        self.assertEqual(len(self.client.get(macchine).context["macchine"]), ctx["macchine_attive"])
        archivio = self.client.get(fatture)
        self.assertEqual(archivio.context["totale_fatture"], len(ctx["fatture"]))
        self.assertEqual([a["trimestre"] for a in archivio.context["scoperti"]], ctx["scoperti"])
        self.assertContains(archivio, "data-filtro-fornitore")

    def test_codice_sconosciuto_ignorato(self):
        tutte = self.client.get(reverse("contatori:macchine")).context["macchine"]
        r = self.client.get(reverse("contatori:macchine") + "?fornitore=NON-ESISTE")
        self.assertEqual(len(r.context["macchine"]), len(tutte))
        self.assertEqual(self.client.get(reverse("contatori:fatture") + "?fornitore=NON-ESISTE").context["totale_fatture"], 3)
