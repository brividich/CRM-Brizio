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

    def test_contatori_usano_gli_stessi_op_dell_elenco(self):
        visibili = {"vedere": frozenset(), "modificare": frozenset()}
        with (
            patch("core.permessi.sistema_ruoli_attivo", return_value=True),
            patch("core.permessi.utenti_visibili", side_effect=lambda req, mod, az="vedere": visibili[az]),
            patch("core.permessi.decisione", return_value=SimpleNamespace(consentito=False, ambito="")),
            patch("anomalie.views._fetch_all_dict", side_effect=_fetch),
            patch("anomalie.views.legacy_table_columns", return_value={"created_by_user_id", "id"}),
            patch("anomalie.views._nomi_norm_di_utenti", side_effect=_nomi),
            patch("anomalie.views._current_user_name_norms", return_value={"MARIO ROSSI"}),
        ):
            where, params = av._anomalie_scope_where(self._request())
        self.assertEqual(len(where), 1)
        self.assertEqual(params, ["op/1", "op/3"])

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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RiaperturaTests(TestCase):
    """Riapre un'anomalia chiusa chi ne è incaricato: CC, CAR, controllore, chi modifica l'OP."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="anom-riapri", password="pass12345")

    def _request(self, legacy_id=5):
        request = RequestFactory().post("/api/anomalie/riapri")
        request.user = self.user
        request.legacy_user = SimpleNamespace(id=legacy_id, nome="Mario Rossi", email="")
        return request

    def _righe(self, *, edit=False, persone=None, legacy_id=5, controlli=()):
        rows = [
            {"local_id": 1, "chiudere": True, "controllo_id": None},
            {"local_id": 2, "chiudere": True, "controllo_id": 40},
            {"local_id": 3, "chiudere": False, "controllo_id": None},
        ]
        with (
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=edit),
            patch("anomalie.views._op_persone_row", return_value=persone or {}),
            patch("anomalie.views._request_name_norms", return_value={"MARIO ROSSI"}),
            patch("anomalie.views._controlli_dell_utente", return_value=set(controlli)),
        ):
            av._segna_riapribili(self._request(legacy_id), rows, "OP/1", {1: 5, 2: 99, 3: 5})
        return {r["local_id"]: r["can_riaprire"] for r in rows}

    def test_capocommessa_riapre_tutte_le_chiuse(self):
        self.assertEqual(self._righe(persone={"capocomessa": "Mario Rossi"}), {1: True, 2: True, 3: False})

    def test_car_riapre(self):
        self.assertEqual(self._righe(persone={"incaricato": "Mario Rossi"}), {1: True, 2: True, 3: False})

    def test_chi_modifica_l_op_riapre(self):
        self.assertEqual(self._righe(edit=True), {1: True, 2: True, 3: False})

    def test_controllore_riapre_solo_le_sue(self):
        # Autore della riga 1 (created_by) e operatore del controllo 40 (riga 2).
        self.assertEqual(self._righe(controlli={40}), {1: True, 2: True, 3: False})
        self.assertEqual(self._righe(legacy_id=8), {1: False, 2: False, 3: False})

    def _post(self, riga, *, consentito):
        import json

        request = self._request()
        request._body = json.dumps({"local_id": 1}).encode()
        with (
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views._fetch_all_dict", return_value=[riga]),
            patch("anomalie.views._can_riaprire_anomalia", return_value=consentito),
        ):
            return av.api_riapri.__wrapped__(request)

    def test_api_nega_chi_non_e_incaricato(self):
        resp = self._post({"id": 1, "ex_op_nominativo": "OP/1", "chiudere": 1}, consentito=False)
        self.assertEqual(resp.status_code, 403)

    def test_api_rifiuta_anomalia_gia_aperta(self):
        resp = self._post({"id": 1, "ex_op_nominativo": "OP/1", "chiudere": 0}, consentito=True)
        self.assertEqual(resp.status_code, 400)


class ServeAzioneRigheTests(TestCase):
    """Le righe di /api/anomalie/anomalie dicono quali anomalie non si possono chiudere
    senza l'azione effettuata (prima decisione «Azione di recupero»)."""

    def test_flag_serve_azione(self):
        from django.utils import timezone

        from anomalie.quality_models import AnomaliaSchedaQualita

        AnomaliaSchedaQualita.objects.create(anomalia_id=11, primo_avanzamento="Azione di recupero")
        AnomaliaSchedaQualita.objects.create(anomalia_id=12, primo_avanzamento="Azione di recupero",
                                             azione_effettuata_il=timezone.now())
        AnomaliaSchedaQualita.objects.create(anomalia_id=13, primo_avanzamento="Accetto lo stato")
        rows = [{"local_id": 11, "chiudere": False}, {"local_id": 12, "chiudere": False},
                {"local_id": 13, "chiudere": False}, {"local_id": 14, "chiudere": True}]
        av._segna_serve_azione(rows)
        self.assertEqual([r["serve_azione"] for r in rows], [True, False, False, False])
