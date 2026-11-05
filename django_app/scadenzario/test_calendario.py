"""Scadenzario /scadenze: festività, presa in carico, «solo le mie», viste salvate,
vista anno, andamento (fotografie), rinnovo dal calendario, schermo intero automatico."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.scadenze_providers import ScadenzaItem
from scadenzario import calendario as cal
from scadenzario.models import (
    CategoriaScadenza, FotoScadenze, PresaInCarico, ScadenzaGenerica, VistaSalvata,
)


def _voce(giorni=3, titolo="Revisione furgone", soggetto="Officina", source="generiche", url="/x/1/", extra=None):
    oggi = timezone.localdate()
    return ScadenzaItem(source=source, kind="k", kind_label="Mezzi", titolo=titolo, soggetto=soggetto, reparto="",
                        data_scadenza=oggi + timedelta(days=giorni), giorni=giorni, url=url, extra=extra or {})


class ChiaveDistintaTests(TestCase):
    def test_stesso_corso_e_data_ma_persone_diverse(self):
        from scadenzario.calendario import chiave_scadenza

        comune = dict(source="hr", kind="formazione", kind_label="", titolo="Corso sintetico", reparto="",
                      data_scadenza=date(2027, 1, 1), giorni=1, url="/x", elemento="Corso sintetico")
        a = ScadenzaItem(soggetto="Persona Uno", **comune)
        b = ScadenzaItem(soggetto="Persona Due", **comune)
        self.assertNotEqual(chiave_scadenza(a), chiave_scadenza(b))

    def test_generica_rinominata_tiene_la_chiave(self):
        from scadenzario.calendario import chiave_scadenza

        comune = dict(source="generiche", kind="cat-1", kind_label="", reparto="", data_scadenza=date(2027, 1, 1),
                      giorni=1, url="/x", elemento="s1")
        self.assertEqual(chiave_scadenza(ScadenzaItem(titolo="A", soggetto="A", **comune)),
                         chiave_scadenza(ScadenzaItem(titolo="B", soggetto="B", **comune)))


class FestivitaTests(TestCase):
    def test_pasqua_e_feste(self):
        self.assertEqual(cal.pasqua(2026), date(2026, 4, 5))
        self.assertEqual(cal.pasqua(2027), date(2027, 3, 28))
        feste = cal.festivi([2026])
        self.assertEqual(feste[date(2026, 4, 6)], "Lunedì dell'Angelo")
        self.assertEqual(feste[date(2026, 12, 25)], "Natale")
        self.assertEqual(cal.non_lavorativo(date(2026, 11, 8), feste), "domenica")
        self.assertEqual(cal.non_lavorativo(date(2026, 11, 9), feste), "")

    def test_patrono_da_siteconfig(self):
        from core.models import SiteConfig

        SiteConfig.objects.update_or_create(chiave=cal.CHIAVE_PATRONO, defaults={"valore": "06-29 San Pietro"})
        self.assertEqual(cal.festivi([2026])[date(2026, 6, 29)], "San Pietro")
        SiteConfig.objects.update_or_create(chiave=cal.CHIAVE_PATRONO, defaults={"valore": "boh"})
        self.assertNotIn(date(2026, 6, 29), cal.festivi([2026]))

    def test_parametri_vista_ripuliti(self):
        self.assertEqual(cal.pulisci_parametri("vista=anno&sorgente=hr&mese=2026-01&intero=1&format=csv&x=1"),
                         "vista=anno&sorgente=hr")


@override_settings(LEGACY_AUTH_ENABLED=False)
class PaginaTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        U = get_user_model()
        self.user = U.objects.create_superuser(username="mario.sint", email="m@example.com", password="x",
                                               first_name="Mario", last_name="Rossi")
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)

    def _get(self, voci, qs=""):
        with patch("dashboard.views_scadenze.collect_all", return_value=voci):
            resp = self.client.get(reverse("scadenze_globali") + qs)
        return resp

    def test_presa_in_carico_solo_se_visibile_e_lascia(self):
        v = _voce()
        chiave = cal.chiave_scadenza(v)
        url = reverse("scadenzario:presa_in_carico")
        dati = {"chiave": chiave, "data": v.data_scadenza.isoformat(), "nota": "chiamato il fornitore", "next": "/scadenze?vista=agenda"}
        with patch("dashboard.scadenze_providers.collect_all", return_value=[]):
            self.assertEqual(self.client.post(url, dati).status_code, 403)
        with patch("dashboard.scadenze_providers.collect_all", return_value=[v]):
            resp = self.client.post(url, dati)
        self.assertRedirects(resp, "/scadenze?vista=agenda", fetch_redirect_response=False)
        p = PresaInCarico.objects.get(chiave=chiave)
        self.assertEqual((p.utente_id, p.nota), (self.user.id, "chiamato il fornitore"))
        # Compare in pagina con il nome e la voce diventa «mia».
        resp = self._get([_voce()], "?vista=elenco&mie=1")
        self.assertEqual(len(resp.context["page_obj"].object_list), 1)
        resp = self._get([_voce()], "?vista=agenda")
        self.assertContains(resp, "· chiamato il fornitore</span>")
        self.assertContains(resp, "✕ Lascia")
        # next fuori dallo scadenzario: si torna comunque a /scadenze.
        resp = self.client.post(url, {"chiave": chiave, "azione": "lascia", "next": "https://esempio.test/"})
        self.assertRedirects(resp, reverse("scadenze_globali"), fetch_redirect_response=False)
        self.assertFalse(PresaInCarico.objects.exists())

    def test_solo_le_mie_per_nome_e_responsabile(self):
        mia_nome = _voce(titolo="Visita medica", soggetto="ROSSI Mario", source="hr", url="/a/")
        mia_resp = _voce(titolo="Polizza", url="/b/", extra={"responsabile_id": self.user.id})
        altrui = _voce(titolo="Altro", soggetto="Bianchi Anna", source="hr", url="/c/")
        resp = self._get([mia_nome, mia_resp, altrui], "?vista=elenco&mie=1")
        self.assertEqual(sorted(v.titolo for v in resp.context["page_obj"].object_list), ["Polizza", "Visita medica"])
        resp = self._get([mia_nome, mia_resp, altrui], "?vista=elenco")
        self.assertEqual(resp.context["n_mie"], 2)

    def test_viste_salvate_e_predefinita(self):
        self.client.post(reverse("scadenzario:vista_salva"), {
            "nome": "Antincendio", "parametri": "vista=agenda&stato=scaduta&intero=1", "predefinita": "1"})
        vs = VistaSalvata.objects.get(utente=self.user)
        self.assertEqual((vs.parametri, vs.predefinita), ("vista=agenda&stato=scaduta", True))
        resp = self._get([], "")
        self.assertRedirects(resp, reverse("scadenze_globali") + "?vista=agenda&stato=scaduta", fetch_redirect_response=False)
        self.client.post(reverse("scadenzario:vista_predefinita", args=[vs.pk]))
        self.assertEqual(self._get([], "").status_code, 200)
        altro = get_user_model().objects.create_user(username="altro.sint", password="x")
        vs_altro = VistaSalvata.objects.create(utente=altro, nome="Sua")
        self.assertEqual(self.client.post(reverse("scadenzario:vista_elimina", args=[vs_altro.pk])).status_code, 404)

    def test_vista_anno_e_link_al_giorno(self):
        oggi = timezone.localdate()
        resp = self._get([_voce(0, "Oggi"), _voce(1, "Domani")], f"?vista=anno&anno={oggi.year}")
        self.assertEqual(resp.status_code, 200)
        mesi = resp.context["mesi_anno"]
        self.assertEqual(len(mesi), 12)
        celle = [c for riga in mesi[oggi.month - 1]["settimane"] for c in riga if c and c["num"] == oggi.day]
        self.assertEqual(celle[0]["n"], 1)
        self.assertIn(f"giorno={oggi.isoformat()}", celle[0]["href"])
        resp = self._get([_voce(0, "Oggi")], f"?vista=mese&giorno={oggi.isoformat()}")
        self.assertEqual(resp.context["giorno_sel"], oggi.isoformat())
        resp = self._get([], "?vista=mese&giorno=x';alert(1)")
        self.assertEqual(resp.context["giorno_sel"], "")

    def test_festa_nel_mese_e_voce_non_lavorativa(self):
        resp = self._get([], "?vista=mese&mese=2026-12")
        celle = {c["iso"]: c for riga in resp.context["settimane"] for c in riga}
        self.assertEqual(celle["2026-12-25"]["festa"], "Natale")
        self.assertContains(resp, "sc-festa")

    def test_rinnovo_dal_calendario_torna_alla_pagina(self):
        cat = CategoriaScadenza.objects.create(nome="Mezzi")
        s = ScadenzaGenerica.objects.create(categoria=cat, titolo="Revisione", data_scadenza=timezone.localdate(),
                                            validita_mesi=12)
        resp = self.client.post(reverse("scadenzario:scadenza_rinnovo", args=[s.pk]),
                                {"eseguito_il": timezone.localdate().isoformat(), "next": "/scadenze?vista=mese"})
        self.assertRedirects(resp, "/scadenze?vista=mese", fetch_redirect_response=False)
        s.refresh_from_db()
        self.assertGreater(s.data_scadenza, timezone.localdate())
        # In pagina il pulsante compare per chi gestisce la categoria.
        from scadenzario.fonte import collect_generiche  # noqa: F401  (fonte reale)

        with patch("dashboard.views_scadenze.collect_all",
                   return_value=[_voce(2, extra={"categoria_id": cat.pk, "scadenza_id": s.pk, "validita_mesi": 12})]):
            resp = self.client.get(reverse("scadenze_globali") + "?vista=agenda")
        self.assertContains(resp, "✓ Rinnovato")
        # Senza validità il rinnovo non saprebbe la prossima scadenza: niente pulsante rapido.
        with patch("dashboard.views_scadenze.collect_all",
                   return_value=[_voce(2, extra={"categoria_id": cat.pk, "scadenza_id": s.pk})]):
            resp = self.client.get(reverse("scadenze_globali") + "?vista=agenda")
        self.assertNotContains(resp, "✓ Rinnovato")

    def test_andamento_solo_per_chi_gestisce(self):
        oggi = timezone.localdate()
        for i, n in ((40, 9), (10, 6), (0, 4)):
            FotoScadenze.objects.create(data=oggi - timedelta(days=i), fonte="generiche", scadute=n, entro_30=2, totale=n + 2)
        resp = self._get([], "?vista=andamento")
        a = resp.context["andamento"]
        self.assertFalse(a["vuoto"])
        self.assertEqual((a["scadute_oggi"], a["delta30"]), (4, -5))
        self.assertContains(resp, "<svg class=\"sc-chart\"")
        normale = get_user_model().objects.create_user(username="norm.sint", password="x")
        from core.models import UserOnboarding

        UserOnboarding.objects.create(user=normale, completed=True)
        self.client.force_login(normale)
        with patch("dashboard.views_scadenze._puo_pannello", return_value=False):
            resp = self._get([], "?vista=andamento")
        self.assertEqual(resp.context["vista"], "mese")

    def test_schermo_intero_aggiornamento_automatico(self):
        resp = self._get([], "?intero=1&auto=10")
        self.assertEqual(resp.context["auto"], 10)
        self.assertContains(resp, "var minuti = 10;")
        resp = self._get([], "?auto=10")  # fuori dallo schermo intero non si ricarica
        self.assertEqual(resp.context["auto"], 0)
        resp = self._get([], "?intero=1&auto=3")
        self.assertEqual(resp.context["auto"], 0)


class FotoTests(TestCase):
    def test_scatta_foto_per_fonte_e_rilanciabile(self):
        oggi = timezone.localdate()
        voci = [_voce(-2), _voce(-1), _voce(10), _voce(80), _voce(200), _voce(5, source="hr")]
        with patch("dashboard.scadenze_providers.collect_sistema", return_value=voci):
            cal.scatta_foto(oggi)
            cal.scatta_foto(oggi)
        g = FotoScadenze.objects.get(data=oggi, fonte="generiche")
        self.assertEqual((g.scadute, g.entro_30, g.totale), (2, 1, 4))
        self.assertEqual(FotoScadenze.objects.get(data=oggi, fonte="hr").entro_30, 1)
        self.assertEqual(FotoScadenze.objects.filter(data=oggi, fonte="generiche").count(), 1)
