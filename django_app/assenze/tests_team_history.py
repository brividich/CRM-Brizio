"""Regressioni reparto/storico su schema legacy sintetico e anagrafica reale."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, RequestFactory
from django.template.loader import render_to_string
from django.utils import timezone

from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto
from core.legacy_utils import legacy_table_columns
from core.legacy_models import UtenteLegacy
from . import views


class TeamHistoryTests(TestCase):
    def setUp(self):
        for user_id in (7, 8, 17, 18, 19):
            UtenteLegacy.objects.create(id=user_id, nome=f"Utente sintetico {user_id}", password="!")
        with connection.cursor() as c:
            c.execute("CREATE TABLE IF NOT EXISTS anagrafica_dipendenti (id INTEGER PRIMARY KEY, utente_id INTEGER, email TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS capi_reparto (id INTEGER PRIMARY KEY, utente_id INTEGER, nome TEXT, title TEXT, indirizzo_email TEXT)")
            c.execute("""CREATE TABLE IF NOT EXISTS assenze (
                id INTEGER PRIMARY KEY, utente_id INTEGER, capo_reparto_id INTEGER,
                email_esterna TEXT, copia_nome TEXT, tipo_assenza TEXT,
                data_inizio DATETIME, data_fine DATETIME, consenso TEXT,
                moderation_status INTEGER, motivazione_richiesta TEXT)""")
            c.executemany("INSERT INTO anagrafica_dipendenti (id,utente_id,email) VALUES (%s,%s,%s)", [
                (501, 7, "capo@example.test"), (502, 8, "altro@example.test"),
                (601, 17, "dip@example.test"), (602, 18, "esterno@example.test"),
            ])
            # La FK 7 appartiene ad un ALTRO capo: non confondere con utenti.id=7.
            c.executemany("INSERT INTO capi_reparto (id,utente_id,nome,title,indirizzo_email) VALUES (%s,%s,'','','')", [(7, 8), (90, 7)])
        legacy_table_columns.cache_clear()
        self.addCleanup(legacy_table_columns.cache_clear)
        reparto = Reparto.objects.create(nome="Reparto test", caporeparto_legacy_id=502)
        area = AreaAziendale.objects.create(nome="Area test", reparto=reparto, responsabile_legacy_id=501)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=601, area_aziendale=area, caporeparto_legacy_id=502)
        self.area = area
        self.addCleanup(patch.stopall)
        patch("assenze.views._attach_corsi_conflicts").start()
        patch("assenze.views._mark_sharepoint_managed").start()

    def insert(self, id, *, user=17, capo=None, status=0, date=None, email=""):
        date = date or datetime(2026, 10, 1, 8)
        with connection.cursor() as c:
            c.execute("INSERT INTO assenze (id,utente_id,capo_reparto_id,email_esterna,copia_nome,tipo_assenza,data_inizio,data_fine,consenso,moderation_status,motivazione_richiesta) VALUES (%s,%s,%s,%s,'Dipendente sintetico','Ferie',%s,%s,'',%s,'')",
                      [id, user, capo, email, date, date + timedelta(hours=8), status])

    def test_current_team_sees_pending_past_and_future_without_capo_record(self):
        self.insert(1, status=2)
        self.insert(2, date=datetime(2025, 1, 1))
        self.insert(3, date=datetime(2028, 1, 1))
        self.assertEqual([r["id"] for r in views._load_pending_for_manager(7)], [1])
        self.assertEqual([r["id"] for r in views._load_gestite_for_manager(7)], [3, 2])
        self.assertEqual(views.count_pending_for_manager(7), 1)

    def test_current_assignment_wins_over_old_capo_and_denormalized_value(self):
        self.insert(1, capo=7)
        self.assertEqual([r["id"] for r in views._load_gestite_for_manager(7)], [1])
        self.assertEqual(views._load_gestite_for_manager(8), [])
        self.area.responsabile_legacy_id = 502
        self.area.save(update_fields=["responsabile_legacy_id"])
        self.assertEqual(views._load_gestite_for_manager(7), [])
        self.assertEqual([r["id"] for r in views._load_gestite_for_manager(8)], [1])

    def test_legacy_fallback_uses_capo_fk_not_user_id(self):
        self.insert(1, user=18, capo=7)
        self.insert(2, user=18, capo=90)
        self.assertEqual([r["id"] for r in views._load_gestite_for_manager(7)], [2])

    def test_import_without_user_uses_exact_unique_email(self):
        self.insert(1, user=None, email="dip@example.test")
        self.insert(2, user=None, email="dip@different.test")
        self.assertEqual([r["id"] for r in views._load_gestite_for_manager(7)], [1])
        with connection.cursor() as c:
            c.execute("INSERT INTO anagrafica_dipendenti (id,utente_id,email) VALUES (603,19,'dip@example.test')")
        self.assertEqual(views._load_gestite_for_manager(7), [])

    def test_history_paginates_beyond_thirty_without_duplicates(self):
        for id in range(1, 66):
            self.insert(id)
        first = views._load_gestite_for_manager(7, limit=30)
        second = views._load_gestite_for_manager(7, limit=30, offset=30)
        third = views._load_gestite_for_manager(7, limit=30, offset=60)
        self.assertEqual([len(first), len(second), len(third)], [30, 30, 5])
        self.assertEqual(len({r["id"] for r in first + second + third}), 65)

    def test_date_filter_applied_before_pagination_and_global_history(self):
        now = timezone.localtime().replace(tzinfo=None)
        self.insert(1, date=now - timedelta(days=10))
        self.insert(2, date=now + timedelta(days=10))
        self.assertEqual([r["id"] for r in views._load_gestite_for_manager(7, periodo="passate")], [1])
        self.assertEqual([r["id"] for r in views._load_gestite_for_manager(7, periodo="future")], [2])
        self.assertEqual([r["id"] for r in views._load_all_gestite(periodo="future")], [2])

    def test_calendar_matches_team_without_extending_approval(self):
        self.insert(1)
        self.insert(2, user=18)
        events = views._load_events(manager_scope={"legacy_user_id": 7}, colors={})
        self.assertEqual(len(events), 1)
        with patch("assenze.views._assenze_permissions", return_value={
            "can_update_owned": True, "owned_capo_local_ids": {90}, "owned_capo_lookup_ids": set(),
        }):
            self.assertFalse(views._can_manage_record(None, {"id": 1, "capo_reparto_id": None}))


class TeamAccessTests(TestCase):
    def test_read_only_user_has_team_card_and_no_approval_buttons(self):
        html = render_to_string("assenze/pages/menu.html", {"assenze_can_view_team": True})
        self.assertIn("Assenze del reparto", html)
        html = render_to_string("assenze/pages/car_dashboard.html", {
            "da_gestire": [{"id": 1, "can_moderate": False}], "history_page": 1,
        })
        self.assertIn("Sola consultazione", html)
        self.assertNotIn('class="btn-approva"', html)

    def test_personal_scope_cannot_open_dashboard_even_with_all_query(self):
        request = RequestFactory().get("/assenze/car/dashboard?scope=all")
        request.user = SimpleNamespace(is_authenticated=True)
        with patch("assenze.views._assenze_permissions", return_value={"view_scope": "own"}):
            self.assertEqual(views.car_dashboard(request).status_code, 403)

    def test_read_only_does_not_expose_sensitive_fields_or_approve(self):
        row = {"id": 1, "motivo": "dettaglio sintetico", "certificato_medico": "TEST", "note_gestione": "nota"}
        with patch("assenze.views._assenze_permissions", return_value={"can_update_owned": False}):
            views._prepare_team_rows(None, [row])
        self.assertFalse(row["can_moderate"])
        self.assertEqual([row[k] for k in ("motivo", "certificato_medico", "note_gestione")], ["", "", ""])

    def test_dashboard_uses_requested_history_page_and_period(self):
        from contextlib import ExitStack
        from django.http import HttpResponse

        request = RequestFactory().get("/assenze/car/dashboard?pagina_storico=2&periodo_storico=passate&scope=all")
        request.user = SimpleNamespace(is_authenticated=True)
        with ExitStack() as stack:
            stack.enter_context(patch("assenze.views._assenze_permissions", return_value={
                "view_scope": "reparto", "legacy_user_id": 7,
            }))
            stack.enter_context(patch("assenze.views._legacy_identity", return_value=("Capo", "capo@example.test", 7)))
            stack.enter_context(patch("assenze.views._template_perm_context", return_value={}))
            stack.enter_context(patch("assenze.views._load_pending_for_manager", return_value=[]))
            stack.enter_context(patch("assenze.views._load_assenze_car_periodo", return_value=[]))
            history = stack.enter_context(patch("assenze.views._load_gestite_for_manager", return_value=[{"id": i} for i in range(31)]))
            rendered = stack.enter_context(patch("assenze.views.render", return_value=HttpResponse()))
            self.assertEqual(views.car_dashboard(request).status_code, 200)
        self.assertEqual(history.call_args.kwargs["offset"], 30)
        self.assertEqual(history.call_args.kwargs["periodo"], "passate")
        context = rendered.call_args.args[2]
        self.assertEqual(context["pending_scope"], "mine")
        self.assertTrue(context["history_has_next"])
        self.assertEqual(len(context["gestite"]), 30)
