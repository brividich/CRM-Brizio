"""Assets diviso in quattro moduli della matrice: Inventario, Manutenzione, OdL, Verifiche. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone

from anagrafica.models import Reparto
from core.models import AccessGroup, AccessGroupMembership, RuoloPermessoModulo
from core.permessi.cache import invalida_permessi
from core.permessi.preset import PRESETS, applica_preset
from core.permessi.registro import modulo as modulo_registrato
from core.tests_permessi import PersoneMixin, ensure_anagrafica_table

from .forms import MESSAGGIO_REPARTO_OBBLIGATORIO, _richiedi_reparto
from .models import (
    Asset,
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    WorkOrder,
)
from .registro_permessi import (
    CODICI_MANUTENZIONE,
    CODICI_ODL,
    CODICI_VERIFICHE,
    MODULO_INVENTARIO,
    MODULO_MANUTENZIONE,
    MODULO_ODL,
    MODULO_VERIFICHE,
)
from .services import responsabile_asset, visibilita


class RegistroSottomoduliTests(TestCase):
    def test_quattro_moduli_con_pagine_distinte(self):
        for chiave in (MODULO_INVENTARIO, MODULO_MANUTENZIONE, MODULO_ODL, MODULO_VERIFICHE):
            self.assertIsNotNone(modulo_registrato(chiave), chiave)
        self.assertIn("legacy.assets.assets_maintenance_plans", CODICI_MANUTENZIONE)
        self.assertIn("legacy.assets.assets_wo_close", CODICI_ODL)
        self.assertIn("legacy.assets.assets_deadlines", CODICI_VERIFICHE)
        self.assertFalse(set(CODICI_MANUTENZIONE) & set(CODICI_ODL) & set(CODICI_VERIFICHE))

    def test_i_preset_su_assets_valgono_anche_sui_sottomoduli(self):
        for preset in PRESETS:
            assets = preset.celle.get("assets")
            if not assets:
                continue
            attese = {a: amb for a, amb in assets.items() if a != "impostazioni"}
            for sotto in (MODULO_MANUTENZIONE, MODULO_ODL, MODULO_VERIFICHE):
                self.assertEqual(preset.celle.get(sotto), attese, f"{preset.chiave}.{sotto}")

    def test_tipo_non_it_risponde_al_caporeparto(self):
        capi = {"cn5": (9101, "Capo Sintetico")}
        compressore = Asset(asset_tag="SYN-CMP", name="Compressore", asset_type=Asset.TYPE_OTHER, reparto="CN5")
        self.assertTrue(responsabile_asset.responsabile(compressore, capi).da_caporeparto)
        pc = Asset(asset_tag="SYN-PC", name="PC", asset_type=Asset.TYPE_PC, reparto="CN5")
        self.assertIsNone(responsabile_asset.responsabile(pc, capi))


class RepartoObbligatorioTests(TestCase):
    class _Form:
        def __init__(self):
            self.errori = {}

        def add_error(self, campo, messaggio):
            self.errori[campo] = messaggio

    def test_asset_non_it_senza_reparto_errore(self):
        form = self._Form()
        _richiedi_reparto(form, {"reparto": "  "}, non_it=True)
        self.assertEqual(form.errori, {"reparto": MESSAGGIO_REPARTO_OBBLIGATORIO})

    def test_asset_it_o_con_reparto_nessun_errore(self):
        form = self._Form()
        _richiedi_reparto(form, {"reparto": ""}, non_it=False)
        _richiedi_reparto(form, {"reparto": "CN5"}, non_it=True)
        self.assertEqual(form.errori, {})


class AmbitoSottomoduliTests(PersoneMixin, TestCase):
    """Il CAR con «Propri» su Manutenzione vede piani e scadenze delle sole macchine del suo reparto."""

    def setUp(self):
        cache.clear()
        applica_preset()
        ensure_anagrafica_table()
        self.car, self.car_legacy = self.persona("Capo Sintetico")
        self.tecnico, _ = self.persona("Tecnico Sintetico")
        self.ruolo = AccessGroup.objects.create(code="syn-car-man", label="CAR sintetico", priority=900)
        for modulo in (MODULO_INVENTARIO, MODULO_MANUTENZIONE, MODULO_ODL, MODULO_VERIFICHE):
            RuoloPermessoModulo.objects.create(ruolo=self.ruolo, modulo=modulo, azione="vedere", ambito="propri")
        AccessGroupMembership.objects.create(group=self.ruolo, legacy_user_id=self.car_legacy.id)
        with connection.cursor() as c:
            c.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, reparto, utente_id) VALUES (%s, %s, %s, %s, %s)",
                [9201, "Capo", "Sintetico", "CN5", self.car_legacy.id],
            )
        Reparto.objects.create(nome="CN5", caporeparto_legacy_id=9201)
        Reparto.objects.create(nome="CN6")
        categoria = AssetCategory.objects.create(code="syn-compressori", label="Compressori")
        nuovo = Asset.objects.create
        self.cmp_mio = nuovo(asset_tag="SYN-CMP-5", name="Compressore CN5", asset_type=Asset.TYPE_OTHER,
                             reparto="CN5", asset_category=categoria, status=Asset.STATUS_IN_USE)
        self.cmp_altro = nuovo(asset_tag="SYN-CMP-6", name="Compressore CN6", asset_type=Asset.TYPE_OTHER,
                               reparto="CN6", asset_category=categoria, status=Asset.STATUS_IN_USE)
        self.cnc_altro = nuovo(asset_tag="SYN-CNC-6", name="Fresa CN6", asset_type=Asset.TYPE_CNC,
                               reparto="CN6", status=Asset.STATUS_IN_USE)
        oggi = timezone.localdate()
        # Piano su più reparti (tutti i compressori) e piano solo del CN6.
        self.piano_comune = MaintenanceInterventionTemplate.objects.create(
            code="syn-compressori", label="Spurgo compressori", maintenance_type=MaintenanceInterventionTemplate.TYPE_ROUTINE,
        )
        MaintenancePlanAssignment.objects.create(
            plan=self.piano_comune, target_type=MaintenancePlanAssignment.TARGET_CATEGORY, asset_category=categoria,
            frequency=MaintenancePlanAssignment.FREQ_DAYS, interval=30, warning_days=30, first_due_date=oggi,
        )
        self.piano_cn6 = MaintenanceInterventionTemplate.objects.create(
            code="syn-fresa", label="Ingrassaggio fresa", maintenance_type=MaintenanceInterventionTemplate.TYPE_ROUTINE,
        )
        MaintenancePlanAssignment.objects.create(
            plan=self.piano_cn6, target_type=MaintenancePlanAssignment.TARGET_ASSET, asset=self.cnc_altro,
            frequency=MaintenancePlanAssignment.FREQ_DAYS, interval=30, warning_days=30, first_due_date=oggi,
        )
        occ = MaintenanceOccurrence.objects.create
        self.occ_mia = occ(plan=self.piano_comune, asset=self.cmp_mio, due_date=oggi + timedelta(days=3), warning_days=30)
        self.occ_altra = occ(plan=self.piano_comune, asset=self.cmp_altro, due_date=oggi + timedelta(days=3),
                             warning_days=30)
        self.odl_mio = WorkOrder.objects.create(asset=self.cmp_mio, title="Perdita aria")
        self.odl_altro = WorkOrder.objects.create(asset=self.cnc_altro, title="Mandrino rumoroso")
        self.odl_assegnato = WorkOrder.objects.create(asset=self.cnc_altro, title="Cambio filtro",
                                                      assigned_to=self.car)
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

    def test_piani_visibili_anche_quelli_su_piu_reparti(self):
        piani = visibilita.filtra_piani(self._request(self.car), MaintenanceInterventionTemplate.objects.all())
        self.assertEqual(set(piani), {self.piano_comune})

    def test_scadenze_solo_delle_macchine_del_reparto(self):
        righe = visibilita.filtra_per_asset(
            self._request(self.car), MaintenanceOccurrence.objects.all(), MODULO_MANUTENZIONE
        )
        self.assertEqual(set(righe), {self.occ_mia})

    def test_odl_del_reparto_e_assegnati_alla_persona(self):
        odl = visibilita.filtra_odl(self._request(self.car), WorkOrder.objects.all())
        self.assertEqual(set(odl), {self.odl_mio, self.odl_assegnato})

    def test_pagina_di_un_record_altrui_403(self):
        vista = visibilita.richiede_record_visibile(
            "plan_id", MODULO_MANUTENZIONE, (MaintenanceInterventionTemplate, visibilita.filtra_piani)
        )(lambda request, plan_id: HttpResponse("ok"))
        request = self._request(self.car)
        self.assertEqual(vista(request, plan_id=self.piano_comune.pk).status_code, 200)
        self.assertEqual(vista(request, plan_id=self.piano_cn6.pk).status_code, 403)
        self.assertEqual(vista(request, plan_id=999999).status_code, 200)  # inesistente: decide la vista (404)

    def test_ambito_tutti_su_manutenzione_non_filtra(self):
        RuoloPermessoModulo.objects.filter(ruolo=self.ruolo, modulo=MODULO_MANUTENZIONE).update(ambito="tutti")
        invalida_permessi()
        request = self._request(self.car)
        self.assertFalse(visibilita.ambito_ristretto(request, MODULO_MANUTENZIONE))
        self.assertTrue(visibilita.ambito_ristretto(request, MODULO_ODL))
        self.assertEqual(MaintenanceOccurrence.objects.count(),
                         visibilita.filtra_per_asset(request, MaintenanceOccurrence.objects.all(),
                                                     MODULO_MANUTENZIONE).count())

    def test_sistema_spento_nessun_filtro(self):
        self.attiva_sistema(False)
        request = self._request(self.car)
        self.assertEqual(visibilita.filtra_odl(request, WorkOrder.objects.all()).count(), 3)
