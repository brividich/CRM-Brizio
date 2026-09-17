"""Perimetro di visibilita' sulle assenze altrui (view_scope).

Tre livelli: "all" (tutta l'azienda), "reparto" (solo i dipendenti di cui si e'
capo assegnato) e "own" (solo le proprie richieste). La fonte canonica sono le
capability ACL `view_all_assenze` / `view_reparto_assenze`, con fallback ai
gruppi legacy finche' non sono state distribuite.
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from .views import _assenze_permissions, _events_manager_scope, _load_events


def _request():
    return SimpleNamespace(
        user=SimpleNamespace(
            is_superuser=False,
            email="u@example.com",
            get_username=lambda: "u",
            get_full_name=lambda: "Utente Uno",
        ),
        legacy_user=SimpleNamespace(id=7, nome="Utente Uno", email="u@example.com"),
    )


def _perms(roles, *, acl=()):
    """Permessi per un utente con questi ruoli legacy e queste capability ACL."""
    concesse = set(acl)
    with patch("assenze.views._role_names", return_value=list(roles)), patch(
        "assenze.views._legacy_capi_table_exists", return_value=False
    ), patch(
        "assenze.views.user_can_modulo_action",
        side_effect=lambda request, modulo, azione: azione in concesse,
    ), patch(
        "assenze.views._owned_capo_ids_for_legacy_user", return_value=(set(), set())
    ):
        return _assenze_permissions(_request())


class ViewScopeFallbackLegacyTests(SimpleTestCase):
    """Senza capability ACL vale la classificazione storica per nome di ruolo."""

    def test_amministrazione_vede_tutto(self):
        perms = _perms(["Amministrazione"])
        self.assertEqual(perms["view_scope"], "all")
        self.assertEqual(perms["view_scope_source"], "legacy_group")
        self.assertTrue(perms["can_view_calendar"])

    def test_caporeparto_vede_il_reparto(self):
        perms = _perms(["Caporeparto"])
        self.assertEqual(perms["view_scope"], "reparto")
        self.assertTrue(perms["can_view_calendar"])

    def test_dipendente_semplice_vede_solo_le_proprie(self):
        perms = _perms(["Utenti"])
        self.assertEqual(perms["view_scope"], "own")
        self.assertFalse(perms["can_view_calendar"])

    def test_direzione_e_hr_senza_acl_restano_su_own(self):
        # Sono i profili che il requisito vuole promuovere: senza capability non
        # possono ereditare nulla dal nome del ruolo, e il fallback li lascia a
        # "own". E' il motivo per cui le capability vanno assegnate al deploy.
        for ruolo in ("Direzione", "HR"):
            with self.subTest(ruolo=ruolo):
                self.assertEqual(_perms([ruolo])["view_scope"], "own")


class ViewScopeAclTests(SimpleTestCase):
    def test_view_all_promuove_un_utente_senza_ruoli(self):
        perms = _perms(["Direzione"], acl={"view_all_assenze"})
        self.assertEqual(perms["view_scope"], "all")
        self.assertEqual(perms["view_scope_source"], "acl")
        self.assertTrue(perms["view_all"])
        self.assertTrue(perms["can_view_calendar"])

    def test_view_reparto_promuove_un_utente_senza_ruoli(self):
        perms = _perms(["HR"], acl={"view_reparto_assenze"})
        self.assertEqual(perms["view_scope"], "reparto")
        self.assertFalse(perms["view_all"])
        self.assertTrue(perms["can_view_calendar"])

    def test_acl_vince_sul_gruppo_legacy(self):
        # Un caporeparto con la capability aziendale vede tutto, senza che il suo
        # ruolo legacy debba cambiare nome.
        perms = _perms(["Caporeparto"], acl={"view_all_assenze"})
        self.assertEqual(perms["view_scope"], "all")

    def test_view_all_prevale_su_view_reparto(self):
        perms = _perms(["Utenti"], acl={"view_all_assenze", "view_reparto_assenze"})
        self.assertEqual(perms["view_scope"], "all")

    def test_la_visibilita_non_concede_l_approvazione(self):
        # Vedere non e' decidere: i pulsanti Approva/Rifiuta restano legati ai
        # gruppi legacy, non alle capability di visibilita'.
        perms = _perms(["Utenti"], acl={"view_all_assenze"})
        self.assertEqual(perms["view_scope"], "all")
        self.assertFalse(perms["can_update_any"])
        self.assertFalse(perms["can_update_owned"])


class EventsManagerScopeTests(SimpleTestCase):
    def test_scope_all_non_filtra(self):
        perms = _perms(["Amministrazione"])
        with patch("assenze.views._assenze_permissions", return_value=perms):
            self.assertIsNone(_events_manager_scope(_request()))

    def test_scope_reparto_porta_l_identita_del_capo(self):
        perms = _perms(["Caporeparto"])
        with patch("assenze.views._assenze_permissions", return_value=perms):
            scope = _events_manager_scope(_request())
        self.assertEqual(scope["legacy_user_id"], 7)
        self.assertEqual(scope["manager_name"], "Utente Uno")
        self.assertEqual(scope["manager_email"], "u@example.com")


class LoadEventsScopeSqlTests(SimpleTestCase):
    """Il filtro deve finire nella query, non essere applicato dopo."""

    def _capture(self, **kwargs):
        catturato = {}

        def _fake_fetch(sql, params):
            catturato["sql"] = sql
            catturato["params"] = params
            return []

        with patch("assenze.views._table_exists", return_value=True), patch(
            "assenze.views._has_assenze_column", return_value=True
        ), patch("assenze.views._fetch_all_dict", side_effect=_fake_fetch), patch(
            "assenze.views._legacy_capi_table_exists", return_value=False
        ), patch(
            "assenze.views.legacy_table_columns", return_value={"capo_reparto_id"}
        ), patch("assenze.views._load_colors", return_value={}):
            _load_events(**kwargs)
        return catturato

    def test_senza_scope_nessun_filtro_sul_capo(self):
        catturato = self._capture()
        self.assertNotIn("a.capo_reparto_id = %s", catturato["sql"])

    def test_con_scope_il_filtro_e_in_sql(self):
        catturato = self._capture(
            manager_scope={
                "legacy_user_id": 7,
                "manager_name": "Utente Uno",
                "manager_email": "u@example.com",
            }
        )
        self.assertIn("a.capo_reparto_id = %s", catturato["sql"])
        self.assertIn(7, catturato["params"])

    def test_i_parametri_restano_allineati_alle_clausole(self):
        # Lo scope viene aggiunto prima di start/end: se l'ordine dei bind si
        # disallineasse, la query filtrerebbe per le date sbagliate.
        from datetime import datetime

        catturato = self._capture(
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 31),
            manager_scope={
                "legacy_user_id": 7,
                "manager_name": "",
                "manager_email": "",
            },
        )
        self.assertEqual(
            catturato["params"],
            [7, datetime(2026, 1, 1), datetime(2026, 1, 31)],
        )

    def test_scope_senza_criteri_e_fail_closed(self):
        # Nessun modo di sapere di chi e' capo: non si mostra nulla, invece di
        # cadere nella query senza filtro (che sarebbe tutta l'azienda).
        with patch("assenze.views._table_exists", return_value=True), patch(
            "assenze.views._has_assenze_column", return_value=True
        ), patch("assenze.views._legacy_capi_table_exists", return_value=False), patch(
            "assenze.views.legacy_table_columns", return_value=set()
        ), patch("assenze.views._fetch_all_dict") as fetch:
            eventi = _load_events(
                manager_scope={"legacy_user_id": None, "manager_name": "", "manager_email": ""}
            )
        self.assertEqual(eventi, [])
        fetch.assert_not_called()
