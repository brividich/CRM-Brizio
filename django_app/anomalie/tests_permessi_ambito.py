"""Gestione anomalie con il sistema dei ruoli: chi vede e chi modifica ogni OP.

Ambito della matrice (tutti / team / propri), «In carico a me» = capocommessa o
CAR, nota che non può lasciare l'anomalia «In attesa», id OP negativi.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from anomalie import views as av
from anomalie.models import AnomalieAccessLevel, AnomalieRoleAccessRule

_OP_ROWS = [
    # OP di cui Mario è capocommessa
    {"item_id": "-1", "op_title": "OP/1", "part_number": "P1", "incaricato": "Anna Neri", "capocommessa": "Mario Rossi",
     "stato": "Aperto", "anomalie_count": 2, "anomalie_aperte_count": 1, "anomalie_da_decidere_count": 1},
    # OP di un collega del team di Mario
    {"item_id": "-2", "op_title": "OP/2", "part_number": "P2", "incaricato": "", "capocommessa": "Luca Bianchi",
     "stato": "Aperto", "anomalie_count": 1, "anomalie_aperte_count": 1, "anomalie_da_decidere_count": 0},
    # OP dove Mario ha solo aperto un'anomalia
    {"item_id": "-3", "op_title": "OP/3", "part_number": "P3", "incaricato": "", "capocommessa": "Paolo Verdi",
     "stato": "Aperto", "anomalie_count": 1, "anomalie_aperte_count": 1, "anomalie_da_decidere_count": 1},
    # OP di nessuno dei due
    {"item_id": "-4", "op_title": "OP/4", "part_number": "P4", "incaricato": "", "capocommessa": "Sara Gialli",
     "stato": "Aperto", "anomalie_count": 1, "anomalie_aperte_count": 0, "anomalie_da_decidere_count": 0},
]
_CREATORI = [{"op": "op/3", "uid": 5}, {"op": "op/4", "uid": 99}]
_NOMI = {5: {"MARIO ROSSI", "ROSSI MARIO"}, 7: {"LUCA BIANCHI", "BIANCHI LUCA"}}


def _fetch(sql, params=None):
    if "FROM ordini_produzione op" in sql:
        return [dict(r) for r in _OP_ROWS]
    if "SELECT DISTINCT LOWER" in sql:
        return list(_CREATORI)
    return []


def _nomi(ids):
    out = set()
    for i in ids:
        out |= _NOMI.get(int(i), set())
    return frozenset(out)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class OrdiniAmbitoRuoliTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-ambito", password="pass12345")
        AnomalieRoleAccessRule.objects.update_or_create(
            role_type="CC", ruolo_operativo=None, defaults={"access_level": AnomalieAccessLevel.EDIT_ASSIGNED},
        )
        AnomalieRoleAccessRule.objects.update_or_create(
            role_type="CAR", ruolo_operativo=None, defaults={"access_level": AnomalieAccessLevel.EDIT_ASSIGNED},
        )

    def _request(self):
        request = RequestFactory().get("/api/anomalie/ordini")
        request.user = self.user
        request.legacy_user = SimpleNamespace(id=5, nome="Mario Rossi", email="")
        return request

    def _ordini(self, *, vedere, modificare, creare=False, per_apertura=False):
        visibili = {"vedere": vedere, "modificare": modificare}
        with (
            patch("core.permessi.sistema_ruoli_attivo", return_value=True),
            patch("core.permessi.utenti_visibili", side_effect=lambda req, mod, az="vedere": visibili[az]),
            patch("core.permessi.decisione", return_value=SimpleNamespace(consentito=creare, ambito="tutti")),
            patch("anomalie.views._fetch_all_dict", side_effect=_fetch),
            patch("anomalie.views.legacy_table_columns", return_value={"created_by_user_id", "id"}),
            patch("anomalie.views._nomi_norm_di_utenti", side_effect=_nomi),
            patch("anomalie.views._current_user_name_norms", return_value={"MARIO ROSSI"}),
        ):
            return {r["id"]: r for r in av._ordini_payload(self._request(), per_apertura=per_apertura)}

    def test_senza_vedere_solo_op_propri(self):
        righe = self._ordini(vedere=frozenset(), modificare=frozenset())
        self.assertEqual(set(righe), {"OP/1", "OP/3"})
        self.assertTrue(righe["OP/1"]["in_carico"])
        self.assertTrue(righe["OP/1"]["can_edit"])
        # Chi ha solo aperto un'anomalia vede l'OP ma non decide.
        self.assertFalse(righe["OP/3"]["in_carico"])
        self.assertFalse(righe["OP/3"]["can_edit"])

    def test_team_vede_e_modifica_gli_op_del_team(self):
        team = frozenset({5, 7})
        righe = self._ordini(vedere=team, modificare=team)
        self.assertEqual(set(righe), {"OP/1", "OP/2", "OP/3"})
        self.assertTrue(righe["OP/2"]["can_edit"])
        self.assertFalse(righe["OP/2"]["in_carico"])

    def test_vedere_tutti_non_rende_tutto_in_carico_ne_modificabile(self):
        righe = self._ordini(vedere=None, modificare=frozenset({5}))
        self.assertEqual(set(righe), {"OP/1", "OP/2", "OP/3", "OP/4"})
        self.assertEqual([k for k, r in righe.items() if r["in_carico"]], ["OP/1"])
        self.assertFalse(righe["OP/4"]["can_edit"])
        self.assertFalse(righe["OP/2"]["can_edit"])
        # «propri» su modificare: l'OP dove ha aperto un'anomalia.
        self.assertTrue(righe["OP/3"]["can_edit"])

    def test_modificare_tutti(self):
        righe = self._ordini(vedere=None, modificare=None)
        self.assertTrue(all(r["can_edit"] for r in righe.values()))

    def test_apertura_con_creare_mostra_tutti_gli_op(self):
        righe = self._ordini(vedere=frozenset(), modificare=frozenset(), creare=True, per_apertura=True)
        self.assertEqual(set(righe), {"OP/1", "OP/2", "OP/3", "OP/4"})

    def test_gestione_con_creare_resta_filtrata(self):
        righe = self._ordini(vedere=frozenset(), modificare=frozenset(), creare=True)
        self.assertEqual(set(righe), {"OP/1", "OP/3"})


class RegoleSalvataggioTests(TestCase):
    def test_nota_con_stato_in_attesa(self):
        self.assertTrue(av._nota_con_stato_in_attesa("Rilavorare", "In attesa"))
        self.assertTrue(av._nota_con_stato_in_attesa("Rilavorare", ""))
        self.assertFalse(av._nota_con_stato_in_attesa("Rilavorare", "Finito trattato"))
        self.assertFalse(av._nota_con_stato_in_attesa("  ", "In attesa"))

    def test_salvataggio_bloccato_con_nota_e_in_attesa(self):
        request = RequestFactory().post("/api/anomalie/salva")
        request.user = SimpleNamespace(is_superuser=True, is_authenticated=True)
        with patch("anomalie.views._can_edit_anomalie_for_op", return_value=True):
            esito = av._salva_riga_anomalia(request, {
                "item_id": "local:1", "op_id": "OP/1", "note": "Rilavorare", "avanzamento": "In attesa",
            })
        self.assertFalse(esito["success"])
        self.assertEqual(esito["status"], 400)
        self.assertIn("In attesa", esito["error"])

    def test_op_lookup_id_negativo(self):
        with (
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views._fetch_all_dict", return_value=[{"sharepoint_item_id": "-3"}]),
        ):
            self.assertEqual(av._resolve_op_lookup_id(None, "OP/3"), -3)
