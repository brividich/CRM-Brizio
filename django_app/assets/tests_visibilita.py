"""Ambito «Propri / team» sugli asset: il CAR vede i suoi beni e le macchine del suo reparto. Dati sintetici."""
from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from anagrafica.models import Reparto
from core.models import AccessGroup, AccessGroupMembership, RuoloPermessoModulo
from core.permessi.cache import invalida_permessi
from core.permessi.preset import applica_preset
from core.tests_permessi import PersoneMixin, ensure_anagrafica_table

from .models import Asset
from .services import visibilita
from .views._helpers_c import _plant_layout_ambito


class VisibilitaAssetTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        applica_preset()
        ensure_anagrafica_table()
        self.car, self.car_legacy = self.persona("Capo Sintetico")
        self.altro, self.altro_legacy = self.persona("Operatore Sintetico")
        ruolo = AccessGroup.objects.create(code="syn-car", label="CAR sintetico", priority=900)
        RuoloPermessoModulo.objects.create(ruolo=ruolo, modulo="assets", azione="vedere", ambito="propri")
        AccessGroupMembership.objects.create(group=ruolo, legacy_user_id=self.car_legacy.id)
        with connection.cursor() as c:
            c.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, reparto, utente_id) VALUES (%s, %s, %s, %s, %s)",
                [9101, "Capo", "Sintetico", "CN5", self.car_legacy.id],
            )
        Reparto.objects.create(nome="CN5", caporeparto_legacy_id=9101)
        Reparto.objects.create(nome="CN6")
        nuovo = Asset.objects.create
        self.cnc_mio = nuovo(asset_tag="SYN-CNC-5", name="Fresa CN5", asset_type=Asset.TYPE_CNC, reparto="CN5")
        self.cnc_reparto = nuovo(asset_tag="SYN-CNC-5B", name="Tornio CN5", asset_type=Asset.TYPE_WORK_MACHINE,
                                 assignment_to="Reparto CN5", assignment_reparto="CN5")
        self.cnc_altro = nuovo(asset_tag="SYN-CNC-6", name="Fresa CN6", asset_type=Asset.TYPE_CNC, reparto="CN6")
        self.cnc_persona = nuovo(asset_tag="SYN-CNC-5C", name="Rettifica CN5", asset_type=Asset.TYPE_CNC,
                                 reparto="CN5", assignment_to="Operatore Sintetico",
                                 assigned_legacy_user_id=self.altro_legacy.id)
        self.pc_mio = nuovo(asset_tag="SYN-PC-1", name="PC capo", asset_type=Asset.TYPE_PC,
                            assigned_legacy_user_id=self.car_legacy.id, assignment_to="Capo Sintetico")
        self.pc_altro = nuovo(asset_tag="SYN-PC-2", name="PC operatore", asset_type=Asset.TYPE_PC,
                              assigned_legacy_user_id=self.altro_legacy.id, assignment_to="Operatore Sintetico")
        self.attiva_sistema()

    def tearDown(self):
        # L'interruttore dei ruoli resta in cache: spento, per non contagiare i test successivi.
        cache.clear()
        invalida_permessi()

    def _request(self, user):
        request = RequestFactory().get("/assets/")
        request.user = self.ricarica(user)
        request.session = {}
        return request

    def test_car_con_propri_vede_i_suoi_beni_e_le_macchine_del_reparto(self):
        visibili = visibilita.ids_visibili(self._request(self.car))
        self.assertEqual(visibili, {self.cnc_mio.id, self.cnc_reparto.id, self.pc_mio.id})

    def test_sistema_spento_o_superuser_vedono_tutto(self):
        self.assertIsNone(visibilita.ids_visibili(self._request(self.persona("Admin", superuser=True)[0])))
        self.attiva_sistema(False)
        self.assertIsNone(visibilita.ids_visibili(self._request(self.car)))

    def test_scheda_di_un_asset_altrui_403(self):
        vista = visibilita.richiede_asset_visibile("id")(lambda request, id: HttpResponse("ok"))
        self.assertEqual(vista(self._request(self.car), id=self.cnc_mio.id).status_code, 200)
        self.assertEqual(vista(self._request(self.car), id=self.cnc_altro.id).status_code, 403)
        self.assertEqual(vista(self._request(self.car), id=self.pc_altro.id).status_code, 403)

    def test_team_vede_anche_i_beni_del_team(self):
        RuoloPermessoModulo.objects.filter(modulo="assets", ruolo__code="syn-car").update(ambito="team")
        invalida_permessi()
        request = self._request(self.car)
        from core.permessi.motore import contesto_per

        contesto_per(request).team  # noqa: B018 - il team si calcola dall'organigramma (vuoto qui)
        self.assertTrue({self.cnc_mio.id, self.pc_mio.id} <= visibilita.ids_visibili(request))

    def test_mappa_altre_macchine_in_grigio(self):
        def marker(asset, alert="ok"):
            return {"id": asset.id, "asset_id": asset.id, "label": asset.asset_tag, "x_percent": 10.0,
                    "y_percent": 20.0, "alert": alert, "open_tickets": 0, "machine": {"reparto": asset.reparto}}

        payload = {
            "layout": {"id": 1}, "areas": [{"machines": [{"id": self.cnc_mio.id, "alert": "ok"},
                                                         {"id": self.cnc_altro.id, "alert": "overdue"}]}],
            "markers": [marker(self.cnc_mio), marker(self.cnc_altro, "overdue")],
            "elsewhere": [{"asset_id": self.cnc_altro.id}],
        }
        out = _plant_layout_ambito(payload, {self.cnc_mio.id})
        self.assertEqual([m["asset_id"] for m in out["markers"]], [self.cnc_mio.id])
        self.assertEqual(out["altrui"], [{"label": "SYN-CNC-6", "x_percent": 10.0, "y_percent": 20.0}])
        self.assertEqual(out["areas"][0]["machine_count"], 1)
        self.assertEqual(out["areas"][0]["alert_count"], 0)
        self.assertEqual(out["alert_counts"]["overdue"], 0)
        self.assertEqual(out["elsewhere"], [])
