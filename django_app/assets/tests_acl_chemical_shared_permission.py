"""Creare/modificare un asset "Prodotto chimico" deve ricadere sotto lo stesso
permesso ACL degli asset normali (assets_new / assets_edit), non su un codice
dedicato: e' solo una categoria di Asset, non un sotto-modulo a se'.

Le route /assets/new/chimico/ e /assets/edit/chimico/<id>/ non hanno un
Pulsante/Permesso proprio: ricadono su assets_new/assets_edit per prefisso URL
(core.acl._match_pulsante), lo stesso meccanismo per cui /assets/edit/<id>/
ricade gia' sul pulsante /assets/edit/.
"""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase, override_settings

from core.acl import check_permesso
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Pulsante, Ruolo, UtenteLegacy
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

RUOLO_OPERATORE_ID = 2
RUOLO_OSPITE_ID = 3


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class ChemicalAssetSharesAssetsPermissionTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()

        Ruolo.objects.create(id=RUOLO_OPERATORE_ID, nome="operatore")
        Ruolo.objects.create(id=RUOLO_OSPITE_ID, nome="ospite")

        Pulsante.objects.create(codice="assets_new", nome_visibile="Nuovo asset", modulo="assets", url="/assets/new/")
        Pulsante.objects.create(codice="assets_edit", nome_visibile="Modifica asset", modulo="assets", url="/assets/edit/")

        Permesso.objects.create(ruolo_id=RUOLO_OPERATORE_ID, modulo="assets", azione="assets_new", consentito=1, can_view=1)
        Permesso.objects.create(ruolo_id=RUOLO_OPERATORE_ID, modulo="assets", azione="assets_edit", consentito=1, can_view=1)
        Permesso.objects.create(ruolo_id=RUOLO_OSPITE_ID, modulo="assets", azione="assets_new", consentito=0, can_view=0)
        Permesso.objects.create(ruolo_id=RUOLO_OSPITE_ID, modulo="assets", azione="assets_edit", consentito=0, can_view=0)

        self.operatore = UtenteLegacy.objects.create(
            nome="Operatore Asset", email="op-asset@example.local", password="x",
            ruolo="operatore", attivo=True, deve_cambiare_password=False, ruolo_id=RUOLO_OPERATORE_ID,
        )
        self.ospite = UtenteLegacy.objects.create(
            nome="Ospite Asset", email="ospite-asset@example.local", password="x",
            ruolo="ospite", attivo=True, deve_cambiare_password=False, ruolo_id=RUOLO_OSPITE_ID,
        )
        bump_legacy_cache_version()

    def test_chi_puo_creare_asset_puo_creare_anche_il_chimico(self):
        self.assertTrue(check_permesso(self.operatore, "/assets/new/chimico/"))

    def test_chi_puo_modificare_asset_puo_modificare_anche_il_chimico(self):
        self.assertTrue(check_permesso(self.operatore, "/assets/edit/chimico/7/"))

    def test_senza_permesso_asset_resta_negato_anche_sul_chimico(self):
        self.assertFalse(check_permesso(self.ospite, "/assets/new/chimico/"))
        self.assertFalse(check_permesso(self.ospite, "/assets/edit/chimico/7/"))
