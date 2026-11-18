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
