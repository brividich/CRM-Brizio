"""Team del capo e coda da approvare quando ``assenze.utente_id`` non esiste.

In produzione la tabella assenze viene da SharePoint e non ha la colonna
``utente_id``: il perimetro «team» (sistema dei ruoli) era sempre vuoto, quindi
«Il mio team» non mostrava nessuno e il capo non poteva approvare il suo team.
La persona si riconosce da email e nome della richiesta. Dati sintetici.
"""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from core.legacy_models import UtenteLegacy
from core.legacy_utils import legacy_table_columns

from .views import _helpers, richieste


class TeamSenzaColonnaUtenteTests(TestCase):
    def setUp(self):
        UtenteLegacy.objects.create(id=7, nome="Capo Sintetico", password="!")
        UtenteLegacy.objects.create(id=17, nome="Rossi Mario", email="mario.rossi@example.test", password="!")
        UtenteLegacy.objects.create(id=18, nome="Bianchi Anna", email="", password="!")
        UtenteLegacy.objects.create(id=19, nome="Verdi Luca", email="luca.verdi@example.test", password="!")
        with connection.cursor() as c:
            c.execute("DROP TABLE IF EXISTS assenze")
            c.execute("DROP TABLE IF EXISTS anagrafica_dipendenti")
            c.execute(
                "CREATE TABLE anagrafica_dipendenti (id INTEGER PRIMARY KEY, utente_id INTEGER, "
                "nome TEXT, cognome TEXT, email TEXT)"
            )
            c.execute(
                """CREATE TABLE assenze (
                id INTEGER PRIMARY KEY, email_esterna TEXT, copia_nome TEXT, tipo_assenza TEXT,
                data_inizio DATETIME, data_fine DATETIME, consenso TEXT,
                moderation_status INTEGER, motivazione_richiesta TEXT)"""
            )
            c.executemany(
                "INSERT INTO anagrafica_dipendenti (id,utente_id,nome,cognome,email) VALUES (%s,%s,%s,%s,%s)",
                [(601, 17, "Mario", "Rossi", ""), (602, 18, "Anna", "Bianchi", "anna.b@example.test")],
            )
        legacy_table_columns.cache_clear()
        self.addCleanup(legacy_table_columns.cache_clear)
        self.addCleanup(patch.stopall)
        patch("assenze.views._helpers._attach_corsi_conflicts").start()
        patch("assenze.views._helpers._mark_sharepoint_managed").start()
        patch("assenze.views._helpers.sistema_ruoli_attivo", return_value=True).start()
        patch("core.permessi.team.team_di", return_value=frozenset({17, 18})).start()
        self.oggi = timezone.localtime().replace(tzinfo=None, hour=8, minute=0, second=0, microsecond=0)

    def insert(self, id, *, nome="", email="", status=2, inizio=None):
        inizio = inizio or self.oggi + timedelta(days=3)
        with connection.cursor() as c:
            c.execute(
                "INSERT INTO assenze (id,email_esterna,copia_nome,tipo_assenza,data_inizio,data_fine,consenso,"
                "moderation_status,motivazione_richiesta) VALUES (%s,%s,%s,'Ferie',%s,%s,'',%s,'')",
                [id, email, nome, inizio, inizio + timedelta(hours=8), status],
            )

    def test_coda_del_team_riconosce_nome_nei_due_ordini_ed_email(self):
        self.insert(1, nome="ROSSI MARIO")
        self.insert(2, nome="Mario Rossi ")
        self.insert(3, email="Anna.B@example.test")
        self.insert(4, nome="VERDI LUCA", email="luca.verdi@example.test")  # fuori dal team
        self.assertEqual(sorted(r["id"] for r in _helpers._load_pending_for_manager(7)), [1, 2, 3])
        self.assertEqual(_helpers.count_pending_for_manager(7), 3)
        righe = {r["id"]: r["legacy_user_id"] for r in _helpers._load_pending_for_manager(7)}
        self.assertEqual(righe, {1: 17, 2: 17, 3: 18})

    def test_storico_e_periodo_della_dashboard_usano_lo_stesso_team(self):
        self.insert(1, nome="ROSSI MARIO", status=0)
        self.insert(2, nome="VERDI LUCA", status=0)
        self.assertEqual([r["id"] for r in richieste._load_gestite_for_manager(7, utenti_ids=[17, 18])], [1])
        periodo = richieste._load_assenze_car_periodo(
            7, self.oggi, self.oggi + timedelta(days=7), utenti_ids=[17, 18]
        )
        self.assertEqual([r["id"] for r in periodo], [1])

    def test_team_vuoto_non_vede_niente(self):
        self.insert(1, nome="ROSSI MARIO")
        with patch("core.permessi.team.team_di", return_value=frozenset()):
            self.assertEqual(_helpers._load_pending_for_manager(7), [])
        self.assertEqual(_helpers._where_utenti([], "a"), ("", []))

    def test_capo_approva_solo_le_richieste_del_suo_team(self):
        self.insert(1, nome="ROSSI MARIO")
        self.insert(2, nome="VERDI LUCA")
        perms = {
            "can_update_any": False,
            "can_update_owned": True,
            "view_scope_source": "ruoli",
            "team_utenti_ids": frozenset({17, 18}),
            "legacy_user_id": 7,
        }
        request = SimpleNamespace(_assenze_perm_cache=perms)
        with patch("assenze.views._helpers._capo_scelto_legacy_user_id", return_value=None):
            self.assertTrue(_helpers._can_manage_record(request, _helpers._get_assenza(1)))
            self.assertFalse(_helpers._can_manage_record(request, _helpers._get_assenza(2)))

    def test_coda_esclude_le_richieste_finite_da_oltre_trenta_giorni(self):
        self.insert(1, nome="ROSSI MARIO", inizio=self.oggi - timedelta(days=_helpers.CODA_GIORNI_DOPO_FINE + 5))
        self.insert(2, nome="ROSSI MARIO", inizio=self.oggi - timedelta(days=2))
        self.insert(3, nome="ROSSI MARIO")
        self.assertEqual(sorted(r["id"] for r in _helpers._load_pending_for_manager(7)), [2, 3])
        self.assertEqual(sorted(r["id"] for r in richieste._load_all_pending()), [2, 3])
        self.assertEqual(_helpers.count_pending_for_manager(7), 2)
