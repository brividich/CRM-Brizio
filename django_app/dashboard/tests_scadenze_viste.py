"""Scadenzario /scadenze: viste calendario (mese), agenda ed elenco."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard import views_scadenze as vs
from dashboard.scadenze_providers import ORIZZONTE_GIORNI, ScadenzaItem


def _voce(giorni: int, titolo: str, *, source: str = "generiche", soggetto: str = "Uffici") -> ScadenzaItem:
    oggi = timezone.localdate()
    return ScadenzaItem(source=source, kind="k", kind_label="Categoria prova", titolo=titolo, soggetto=soggetto,
                        reparto="", data_scadenza=oggi + timedelta(days=giorni), giorni=giorni, url="/x/")


@override_settings(LEGACY_AUTH_ENABLED=False)
class VisteScadenzarioTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser(username="adm.sint", email="adm@example.com", password="x")
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)

    def _get(self, voci, qs=""):
        with patch("dashboard.views_scadenze.collect_all", return_value=voci) as m:
            resp = self.client.get(reverse("scadenze_globali") + qs)
        self.assertEqual(resp.status_code, 200)
        return resp, m

    def test_apre_sul_calendario_del_mese_corrente(self):
        resp, m = self._get([_voce(0, "Scade oggi"), _voce(-3, "Già scaduta")])
        self.assertEqual(resp.context["vista"], "mese")
        oggi = timezone.localdate()
        celle = [c for riga in resp.context["settimane"] for c in riga]
        self.assertEqual(len(celle) % 7, 0)
        cella_oggi = next(c for c in celle if c["oggi"])
        self.assertEqual([v.titolo for v in cella_oggi["voci"]], ["Scade oggi"])
        self.assertContains(resp, f'data-day="{oggi.isoformat()}"')
        # Orizzonte della raccolta: almeno la finestra dei 90 giorni.
        self.assertGreaterEqual(m.call_args.kwargs["orizzonte"], oggi + timedelta(days=ORIZZONTE_GIORNI))
        self.assertEqual({k["codice"]: k["n"] for k in resp.context["kpi"]}["scaduta"], 1)
        self.assertContains(resp, "Già scaduta")

    def test_mese_lontano_guarda_oltre_i_90_giorni_ma_i_kpi_no(self):
        lontana = _voce(200, "Rinnovo lontano")
        mese = lontana.data_scadenza.strftime("%Y-%m")
        resp, m = self._get([_voce(5, "Vicina"), lontana], f"?vista=mese&mese={mese}")
        self.assertGreaterEqual(m.call_args.kwargs["orizzonte"], lontana.data_scadenza)
        self.assertContains(resp, "Rinnovo lontano")
        self.assertEqual(resp.context["totale"], 1)  # KPI sempre su scadute + 90 giorni

    def test_mese_fuori_intervallo_torna_a_oggi(self):
        resp, _ = self._get([], "?vista=mese&mese=1990-01")
        oggi = timezone.localdate()
        self.assertIn(str(oggi.year), resp.context["mese_label"])
        resp, _ = self._get([], "?vista=mese&mese=abc")
        self.assertTrue(resp.context["mese_corrente"])

    def test_agenda_scadute_in_testa_e_settimane(self):
        resp, m = self._get([_voce(-2, "Scaduta A"), _voce(0, "Oggi B"), _voce(40, "Più avanti C")], "?vista=agenda")
        self.assertIsNone(m.call_args.kwargs["orizzonte"])
        titoli = [g["titolo"] for g in resp.context["gruppi"]]
        self.assertEqual(titoli[0], "Scadute")
        self.assertEqual(titoli[1], "Questa settimana")
        self.assertEqual(sum(g["n"] for g in resp.context["gruppi"]), 3)

    def test_elenco_paginato_e_export_restano(self):
        resp, _ = self._get([_voce(3, "In elenco")], "?vista=elenco")
        self.assertEqual(len(resp.context["page_obj"].object_list), 1)
        self.assertContains(resp, "In elenco")
        with patch("dashboard.views_scadenze.collect_all", return_value=[_voce(3, "Csv"), _voce(150, "Fuori")]):
            csv = self.client.get(reverse("scadenze_globali") + "?format=csv").content.decode("utf-8-sig")
        self.assertIn("Csv", csv)
        self.assertNotIn("Fuori", csv)

    def test_etichette_principale_secondaria(self):
        g = _voce(1, "Contratto pulizie", soggetto="Uffici")
        p = _voce(1, "Visita medica", source="hr", soggetto="Rossi Mario")
        vs._decora([g, p])
        self.assertEqual((g.principale, g.secondario), ("Contratto pulizie", "Uffici"))
        self.assertEqual((p.principale, p.secondario), ("Rossi Mario", "Visita medica"))
        self.assertEqual(g.quando, "scade domani")

    def test_filtri_multipli_e_contatori_a_faccette(self):
        voci = [_voce(-2, "Scaduta gen"), _voce(10, "Vicina hr", source="hr", soggetto="Rossi Mario"),
                _voce(45, "Media capa", source="capa"), _voce(80, "Lontana gen")]
        resp, m = self._get(voci, "?vista=elenco&sorgente=generiche&sorgente=capa&stato=scaduta&stato=60")
        self.assertNotIn("sources", m.call_args.kwargs)  # si raccolgono sempre tutte le fonti
        titoli = [v.titolo for v in resp.context["page_obj"].object_list]
        self.assertEqual(sorted(titoli), ["Media capa", "Scaduta gen"])
        kpi = {k["codice"]: (k["n"], k["on"]) for k in resp.context["kpi"]}
        # La fascia non filtra il proprio contatore: «61–90» conta la generica a 80 giorni.
        self.assertEqual(kpi, {"scaduta": (1, True), "30": (0, False), "60": (1, True), "90": (1, False)})
        fonti = {f["codice"]: (f["n"], f["on"]) for f in resp.context["legenda"]}
        self.assertEqual(fonti["hr"], (0, False)) if "hr" in fonti else None
        self.assertEqual(fonti["generiche"], (1, True))
        # Clic su una fonte già scelta la toglie, le altre restano.
        href = next(f["href"] for f in resp.context["legenda"] if f["codice"] == "capa")
        self.assertIn("sorgente=generiche", href)
        self.assertNotIn("sorgente=capa", href)
        self.assertIn("stato=scaduta", href)

    def test_ricerca_e_reparti(self):
        a = _voce(3, "Revisione furgone")
        a.reparto = "Officina"
        b = _voce(4, "Polizza RC")
        b.reparto = "Uffici"
        resp, _ = self._get([a, b], "?vista=elenco&q=furg")
        self.assertEqual([v.titolo for v in resp.context["page_obj"].object_list], ["Revisione furgone"])
        resp, _ = self._get([a, b], "?vista=elenco&reparto=Uffici&reparto=Officina")
        self.assertEqual(len(resp.context["page_obj"].object_list), 2)
        self.assertEqual(resp.context["reparti"], ["Officina", "Uffici"])

    def test_schermo_intero_resta_nei_link(self):
        resp, _ = self._get([_voce(1, "X")], "?intero=1")
        self.assertTrue(resp.context["intero"])
        self.assertIn("intero=1", resp.context["link_prec"])
        self.assertNotIn("intero", resp.context["link_intero"])
        self.assertNotIn("intero", resp.context["link_csv"])
        self.assertContains(resp, 'class="sc vista-mese intero"')

    def test_fascia(self):
        self.assertEqual([vs._fascia(g) for g in (-1, 0, 30, 31, 60, 61, 90, 91, None)],
                         ["scaduta", "30", "30", "60", "60", "90", "90", "oltre", ""])

    def test_sposta_mese(self):
        self.assertEqual(vs._sposta_mese(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(vs._sposta_mese(date(2026, 1, 1), -1), date(2025, 12, 1))
