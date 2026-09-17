"""La capacita' effettiva tiene conto di cio' che un permesso governa davvero.

Il caso che questo modulo esiste per non ripetere: un permesso legato a un
**prefisso** di URL copre tutto il sottoalbero tranne dove esiste un binding
piu' specifico. Un nome che suona come una lista (``..._lista``) puo' quindi
governare rotte che scrivono o che configurano il modulo, e un livello "Solo
lettura" lo accenderebbe.
"""
from __future__ import annotations

import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.acl_capability import build_capability_index
from core.models import PermissionDefinition, RoutePermissionBinding


class CapabilityIndexTests(TestCase):
    def test_prefisso_su_sottoalbero_alza_la_capacita(self):
        permission = PermissionDefinition.objects.create(
            code="legacy.demo.demo_lista", label="Demo - Lista", module="demo"
        )
        # Dal solo nome sarebbe lettura ("lista").
        index_before = build_capability_index()
        self.assertEqual(index_before.by_name[permission.code], "lettura")
        self.assertEqual(index_before.capabilities[permission.code], "lettura")

        # Legato al prefisso del pannello admin, governa rotte di amministrazione.
        RoutePermissionBinding.objects.create(
            permission=permission,
            path_pattern="/admin-portale/accessi",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            is_active=True,
        )
        index = build_capability_index()
        self.assertEqual(index.by_name[permission.code], "lettura")
        self.assertEqual(index.capabilities[permission.code], "amministrazione")
        self.assertIn(permission.code, index.subtree_routes)
        self.assertEqual(index.promoted()[permission.code], ("lettura", "amministrazione"))

    def test_binding_di_rotta_non_alza_nulla(self):
        """Una rotta con binding proprio e' gia' classificata dal suo nome."""
        permission = PermissionDefinition.objects.create(
            code="legacy.demo.demo_elenco", label="Demo - Elenco", module="demo"
        )
        RoutePermissionBinding.objects.create(
            permission=permission,
            route_name="admin_portale:accessi",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            is_active=True,
        )
        index = build_capability_index()
        self.assertEqual(index.capabilities[permission.code], "lettura")
        self.assertNotIn(permission.code, index.subtree_routes)

    def test_un_permesso_illeggibile_resta_non_classificato(self):
        """L'incertezza non si risolve guardando le rotte: si dichiara."""
        permission = PermissionDefinition.objects.create(
            code="legacy.demo.demo_xyz", label="Demo - Xyz", module="demo"
        )
        RoutePermissionBinding.objects.create(
            permission=permission,
            path_pattern="/admin-portale/accessi",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            is_active=True,
        )
        index = build_capability_index()
        self.assertEqual(index.capabilities[permission.code], "ignoto")
        self.assertIn(permission.code, index.unclassified())

    def test_la_capacita_non_viene_mai_abbassata(self):
        permission = PermissionDefinition.objects.create(
            code="legacy.demo.demo_gestione", label="Demo - Gestione", module="demo"
        )
        RoutePermissionBinding.objects.create(
            permission=permission,
            path_pattern="/admin-portale/accessi",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            is_active=True,
        )
        index = build_capability_index()
        self.assertEqual(index.capabilities[permission.code], "amministrazione")


class CapabilityReportCommandTests(TestCase):
    """Il comando d'audit gira in sola lettura e dice le stesse cose dell'indice."""

    def test_report_json_elenca_livelli_e_promozioni(self):
        permission = PermissionDefinition.objects.create(
            code="legacy.demo.demo_lista", label="Demo - Lista", module="demo"
        )
        RoutePermissionBinding.objects.create(
            permission=permission,
            path_pattern="/admin-portale/accessi",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            is_active=True,
        )
        out = StringIO()
        call_command("acl_capability_report", format="json", stdout=out)
        payload = json.loads(out.getvalue())

        # Il DB di test non e' vuoto (il bootstrap ACL delle app popola il
        # catalogo), quindi si guardano i rapporti, non i totali assoluti.
        self.assertEqual(payload["totale"], sum(payload["per_capacita"].values()))
        self.assertEqual(payload["per_livello"]["nessuno"], 0)
        self.assertEqual(payload["per_livello"]["amministrazione"], payload["totale"])
        self.assertLessEqual(payload["per_livello"]["lettura"], payload["per_livello"]["modifica"])
        promoted = payload["alzati_dal_sottoalbero"][permission.code]
        self.assertEqual(promoted["dal_nome"], "lettura")
        self.assertEqual(promoted["effettiva"], "amministrazione")
        self.assertTrue(promoted["rotte"])

    def test_report_non_scrive_nulla(self):
        PermissionDefinition.objects.create(
            code="legacy.demo.demo_xyz", label="Demo - Xyz", module="demo"
        )
        before = (PermissionDefinition.objects.count(), RoutePermissionBinding.objects.count())
        call_command("acl_capability_report", stdout=StringIO())
        after = (PermissionDefinition.objects.count(), RoutePermissionBinding.objects.count())
        self.assertEqual(before, after)
