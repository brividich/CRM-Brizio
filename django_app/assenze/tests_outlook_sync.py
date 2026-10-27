"""Assenze approvate nel calendario Outlook (Graph simulato): modo «tutte» e «su richiesta»."""
from datetime import datetime
from unittest.mock import patch

from django.test import TestCase

from automazioni.calendario_outlook import evento_assenza

from . import outlook_sync
from .models import AssenzaOutlook, AssenzeImpostazioniHR


def _riga(**kw):
    base = {"id": 5, "copia_nome": "Rossi Mario", "email_esterna": "", "tipo_assenza": "Ferie",
            "data_inizio": datetime(2026, 11, 2), "data_fine": datetime(2026, 11, 4, 23, 59),
            "motivazione_richiesta": "", "moderation_status": 0, "consenso": "Approvato"}
    base.update(kw)
    return base


class FakeGraph:
    """Registra le chiamate; ``risposte`` decide lo stato per metodo."""

    def __init__(self, stati=None):
        self.chiamate = []
        self.stati = stati or {}

    def scrivi(self, metodo, url, *, permesso, json=None):
        self.chiamate.append((metodo, url, json))
        if metodo == "POST" and url.endswith("/calendars"):
            return 201, {"id": "CAL1"}
        if metodo == "POST":
            return 201, {"id": f"EV{len(self.chiamate)}"}
        return self.stati.get(metodo, 200), {}

    def get_all(self, url, *, permesso, params=None, max_pages=None):
        return []

    def metodi(self):
        return [m for m, url, _ in self.chiamate if "/events" in url]


class SincronizzaTests(TestCase):
    modo = "tutte"

    def setUp(self):
        imp = AssenzeImpostazioniHR.get_solo()
        imp.outlook_capo_attivo = True
        imp.outlook_capo_modo = self.modo
        imp.save()

    def _giro(self, righe, graph, ancora=(), in_attesa=()):
        stati = [{"id": i, "stato": 0} for i in ancora] + [{"id": i, "stato": 2} for i in in_attesa]
        with patch("core.m365_graph.configurato", return_value=True), \
                patch("core.m365_graph.scrivi", side_effect=graph.scrivi), \
                patch("core.m365_graph.get_all", side_effect=graph.get_all), \
                patch("assenze.outlook_sync._richieste_approvate", return_value=righe), \
                patch("assenze.outlook_sync._email_capo", return_value="capo@example.com"), \
                patch("assenze.views._helpers._table_exists", return_value=True), \
                patch("assenze.views._helpers._fetch_all_dict", return_value=stati):
            return outlook_sync.sincronizza()

    def test_spento_non_fa_niente(self):
        imp = AssenzeImpostazioniHR.get_solo()
        imp.outlook_capo_attivo = False
        imp.save()
        self.assertIn("skipped", outlook_sync.sincronizza())

    def test_crea_poi_non_riscrive_poi_aggiorna(self):
        g = FakeGraph()
        self.assertEqual(self._giro([_riga()], g)["creati"], 1)
        rec = AssenzaOutlook.objects.get(assenza_id=5)
        self.assertEqual((rec.email, rec.event_id), ("capo@example.com", "EV2"))
        payload = [j for m, u, j in g.chiamate if m == "POST" and "/events" in u][0]
        self.assertEqual((payload["showAs"], payload["isAllDay"], payload["subject"]), ("free", True, "Ferie: ROSSI MARIO"))
        self.assertEqual(payload["end"]["dateTime"], "2026-11-05T00:00:00")

        g2 = FakeGraph()
        self._giro([_riga()], g2)
        self.assertEqual(g2.metodi(), [])  # niente di cambiato, niente scritture

        g3 = FakeGraph()
        esito = self._giro([_riga(data_fine=datetime(2026, 11, 6, 23, 59))], g3)
        self.assertEqual((esito["aggiornati"], g3.metodi()), (1, ["PATCH"]))

    def test_evento_tolto_dal_capo_non_si_ricrea(self):
        self._giro([_riga()], FakeGraph())
        g = FakeGraph(stati={"PATCH": 404})
        self._giro([_riga(data_fine=datetime(2026, 11, 6, 23, 59))], g)
        self.assertTrue(AssenzaOutlook.objects.get(assenza_id=5).rimosso_da_utente)
        g2 = FakeGraph()
        self._giro([_riga(data_fine=datetime(2026, 11, 6, 23, 59))], g2)
        self.assertEqual(g2.metodi(), [])

    def test_richiesta_non_piu_approvata_esce_dal_calendario(self):
        self._giro([_riga()], FakeGraph())
        g = FakeGraph()
        esito = self._giro([], g)  # rifiutata o eliminata
        self.assertEqual((esito["tolti"], g.metodi()), (1, ["DELETE"]))
        self.assertFalse(AssenzaOutlook.objects.exists())

    def test_approvata_ma_passata_resta_in_outlook(self):
        self._giro([_riga()], FakeGraph())
        g = FakeGraph()
        self._giro([], g, ancora=(5,))
        self.assertEqual(g.metodi(), [])
        self.assertFalse(AssenzaOutlook.objects.exists())

    def test_errore_graph_registrato(self):
        from core.m365_graph import GraphError

        def rotto(*a, **kw):
            raise GraphError("Graph ha risposto 403: manca il permesso", 403)

        with patch("core.m365_graph.configurato", return_value=True), \
                patch("core.m365_graph.scrivi", side_effect=rotto), \
                patch("core.m365_graph.get_all", return_value=[]), \
                patch("assenze.outlook_sync._richieste_approvate", return_value=[_riga()]), \
                patch("assenze.outlook_sync._email_capo", return_value="capo@example.com"):
            self.assertEqual(outlook_sync.sincronizza()["errori"], 1)
        self.assertIn("403", AssenzaOutlook.objects.get(assenza_id=5).ultimo_errore)
        self.assertEqual(outlook_sync.stato()["n_errori"], 1)

    def test_con_graph_attivo_niente_pulsante_nelle_mail(self):
        payload = {"id": 1, "dipendente_nome": "X", "tipo_assenza": "Ferie",
                   "data_inizio": datetime(2026, 11, 2), "data_fine": datetime(2026, 11, 3, 23, 59)}
        self.assertIsNone(evento_assenza("assenze", payload))
        self.assertIsNotNone(evento_assenza("assenze", payload, forza=True))


class SuRichiestaTests(SincronizzaTests):
    """Modo predefinito: solo le richieste segnate, nel calendario di chi le ha chieste."""

    modo = "richiesta"

    def test_crea_poi_non_riscrive_poi_aggiorna(self):
        outlook_sync.richiedi(5, "capo@example.com")
        super().test_crea_poi_non_riscrive_poi_aggiorna()

    def test_evento_tolto_dal_capo_non_si_ricrea(self):
        outlook_sync.richiedi(5, "capo@example.com")
        super().test_evento_tolto_dal_capo_non_si_ricrea()

    def test_richiesta_non_piu_approvata_esce_dal_calendario(self):
        outlook_sync.richiedi(5, "capo@example.com")
        super().test_richiesta_non_piu_approvata_esce_dal_calendario()

    def test_approvata_ma_passata_resta_in_outlook(self):
        outlook_sync.richiedi(5, "capo@example.com")
        super().test_approvata_ma_passata_resta_in_outlook()

    def test_errore_graph_registrato(self):
        outlook_sync.richiedi(5, "capo@example.com")
        super().test_errore_graph_registrato()

    def test_senza_richiesta_niente_calendario(self):
        g = FakeGraph()
        self.assertEqual(self._giro([_riga()], g)["creati"], 0)
        self.assertEqual(g.metodi(), [])
        self.assertFalse(AssenzaOutlook.objects.exists())

    def test_nel_calendario_di_chi_lo_chiede_anche_in_due(self):
        outlook_sync.richiedi([5], "Car@Example.com", da="link mail")
        outlook_sync.richiedi(5, "dipendente@example.com")
        outlook_sync.richiedi(5, "car@example.com")  # già chiesto: nessun doppione
        g = FakeGraph()
        self.assertEqual(self._giro([_riga()], g)["creati"], 2)
        self.assertEqual(sorted(AssenzaOutlook.objects.values_list("email", flat=True)),
                         ["car@example.com", "dipendente@example.com"])
        self.assertTrue(all("/users/" in u for m, u, _ in g.chiamate))

    def test_in_attesa_aspetta_e_tornata_in_attesa_toglie_solo_l_evento(self):
        outlook_sync.richiedi(5, "car@example.com")
        g = FakeGraph()
        self._giro([], g, in_attesa=(5,))  # non ancora approvata
        self.assertEqual(g.metodi(), [])
        self.assertTrue(AssenzaOutlook.objects.filter(assenza_id=5).exists())
        self._giro([_riga()], FakeGraph())
        g2 = FakeGraph()
        esito = self._giro([], g2, in_attesa=(5,))
        self.assertEqual((esito["tolti"], g2.metodi()), (1, ["DELETE"]))
        self.assertEqual(AssenzaOutlook.objects.get(assenza_id=5).event_id, "")

    def test_richiesta_vale_per_tutta_la_serie(self):
        from .models import AssenzaSerie

        AssenzaSerie.objects.bulk_create([AssenzaSerie(assenza_id=i, capofila_id=10) for i in (10, 11, 12)])
        self.assertEqual(outlook_sync.richiedi(10, "car@example.com"), 3)

    def test_spento_o_email_non_valida_non_segna_niente(self):
        self.assertEqual(outlook_sync.richiedi(5, "senza-chiocciola"), 0)
        imp = AssenzeImpostazioniHR.get_solo()
        imp.outlook_capo_attivo = False
        imp.save()
        self.assertEqual(outlook_sync.richiedi(5, "car@example.com"), 0)
        self.assertFalse(outlook_sync.su_richiesta())


class PagineConSpuntaTests(TestCase):
    """La spunta compare solo con Graph acceso «su richiesta»."""

    def test_contesto_e_pagine(self):
        from django.template.loader import render_to_string

        from .views.richieste import _contesto_calendario

        self.assertFalse(_contesto_calendario("car@example.com", {})["calendario_opzione"])  # spento
        imp = AssenzeImpostazioniHR.get_solo()
        imp.outlook_capo_attivo = True
        imp.save()
        ctx = _contesto_calendario("Car@Example.com", {"calendario": "1"})
        self.assertEqual((ctx["calendario_opzione"], ctx["calendario_email"], ctx["form_calendario"]),
                         (True, "car@example.com", True))
        self.assertFalse(_contesto_calendario("", {})["calendario_opzione"])
        imp.outlook_capo_modo = "tutte"
        imp.save()
        self.assertFalse(_contesto_calendario("car@example.com", {})["calendario_opzione"])

        html = render_to_string("assenze/pages/car_dashboard.html", {
            "da_gestire": [{"id": 1, "can_moderate": True}], "history_page": 1, **ctx,
        })
        self.assertIn('id="car-calendario"', html)
        self.assertIn("Metti nel mio calendario Outlook le richieste che approvo", html)
        html = render_to_string("assenze/pages/richiesta_assenze.html", {"form_data": {}, **ctx})
        self.assertIn('name="calendario" value="1" checked', html)
