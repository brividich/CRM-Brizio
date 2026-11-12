"""Ruolo base «Operatore» solo per chi non ha altri ruoli (core.permessi.ruolo_base). Dati sintetici."""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase

from core.acl_resolver import user_group_ids
from core.models import AccessGroup, GroupPermissionGrant, PermissionDefinition, RuoloPermessoModulo
from core.permessi.motore import PRESET_BASE, decisione, ruoli_della_persona
from core.permessi.preset import applica_preset
from core.permessi.ruolo_base import NOTA_DAL_BASE, completa_dal_ruolo_base
from core.permessi.simulatore import effetto_modifica
from core.tests_permessi import PersoneMixin


class RuoloBaseTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)  # l'interruttore del sistema resta in cache oltre il rollback
        applica_preset()
        self.base = AccessGroup.objects.get(preset=PRESET_BASE)

    def test_chi_ha_un_ruolo_non_ha_anche_operatore(self):
        _user, legacy = self.persona("Rossi Mario", ruoli=("ruolo-sicurezza",))
        self.assertEqual([g.code for g in ruoli_della_persona(legacy.id)], ["ruolo-sicurezza"])
        _user, senza = self.persona("Bianchi Anna")
        self.assertEqual([g.id for g in ruoli_della_persona(senza.id)], [self.base.id])

    def test_il_ruolo_nuovo_parte_dalle_caselle_di_operatore(self):
        user, _legacy = self.persona("Rossi Mario", ruoli=("ruolo-sicurezza",))
        rspp = AccessGroup.objects.get(code="ruolo-sicurezza")
        cella = RuoloPermessoModulo.objects.get(ruolo=rspp, modulo="assenze", azione="vedere")
        self.assertEqual((cella.note, cella.ambito), (NOTA_DAL_BASE, "propri"))
        self.assertTrue(decisione(user, "assenze", "vedere").consentito)

    def test_togliere_la_casella_dalla_colonna_del_ruolo_la_toglie_davvero(self):
        user, _legacy = self.persona("Rossi Mario", ruoli=("ruolo-sicurezza",))
        collega, _ = self.persona("Bianchi Anna")
        RuoloPermessoModulo.objects.filter(ruolo__code="ruolo-sicurezza", modulo="assenze", azione="vedere").delete()
        self.assertFalse(decisione(self.ricarica(user), "assenze", "vedere").consentito)
        self.assertTrue(decisione(collega, "assenze", "vedere").consentito)

    def test_la_casella_copiata_non_restringe_un_altro_ruolo_della_persona(self):
        # Gestione formazione (455) sta sopra Caporeparto (400): il suo «propri» copiato
        # da Operatore non deve battere il «team» del Caporeparto.
        formazione = AccessGroup.objects.get(code="ruolo-gestione-formazione")
        self.assertTrue(RuoloPermessoModulo.objects.filter(ruolo=formazione, modulo="assenze", azione="vedere",
                                                           note=NOTA_DAL_BASE).exists())
        user, _legacy = self.persona("Verdi Luca", ruoli=("ruolo-responsabile", "ruolo-gestione-formazione"))
        self.assertEqual(decisione(user, "assenze", "vedere").ambito, "team")

    def test_casella_modificata_a_mano_conta_con_l_ordine_del_ruolo(self):
        formazione = AccessGroup.objects.get(code="ruolo-gestione-formazione")
        RuoloPermessoModulo.objects.filter(ruolo=formazione, modulo="assenze", azione="vedere").update(
            consentito=False, note="modificata a mano")
        user, _legacy = self.persona("Verdi Luca", ruoli=("ruolo-responsabile", "ruolo-gestione-formazione"))
        self.assertFalse(decisione(user, "assenze", "vedere").consentito)

    def test_completa_non_tocca_le_caselle_del_ruolo_e_non_copia_i_no(self):
        ruolo = AccessGroup.objects.create(code="ruolo-prova", label="Prova", priority=200)
        RuoloPermessoModulo.objects.create(ruolo=ruolo, modulo="assenze", azione="vedere", ambito="tutti")
        RuoloPermessoModulo.objects.create(ruolo=self.base, modulo="anomalie", azione="vedere", consentito=False)
        completa_dal_ruolo_base([ruolo])
        self.assertEqual(RuoloPermessoModulo.objects.get(ruolo=ruolo, modulo="assenze", azione="vedere").ambito,
                         "tutti")
        self.assertFalse(RuoloPermessoModulo.objects.filter(ruolo=ruolo, modulo="anomalie", azione="vedere").exists())
        self.assertTrue(RuoloPermessoModulo.objects.filter(ruolo=ruolo, modulo="assenze", azione="creare").exists())
        self.assertEqual(completa_dal_ruolo_base([ruolo]), [])  # una seconda volta non copia niente

    def test_ruolo_vede_tutto_non_riceve_le_letture(self):
        ruolo = AccessGroup.objects.create(code="ruolo-vt", label="Vede tutto", priority=200, vede_tutto=True)
        completa_dal_ruolo_base([ruolo])
        self.assertFalse(RuoloPermessoModulo.objects.filter(ruolo=ruolo, azione="vedere").exists())
        self.assertTrue(RuoloPermessoModulo.objects.filter(ruolo=ruolo, modulo="assenze", azione="creare").exists())

    def test_completa_copia_le_pagine_concesse_non_decise_dal_ruolo(self):
        for code in ("prova.aperta", "prova.decisa", "prova.negata"):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code})
        ruolo = AccessGroup.objects.create(code="ruolo-pagine", label="Pagine", priority=200)
        GroupPermissionGrant.objects.create(group=self.base, permission_id="prova.aperta", enabled=True, note="a mano")
        GroupPermissionGrant.objects.create(group=self.base, permission_id="prova.decisa", enabled=True)
        GroupPermissionGrant.objects.create(group=self.base, permission_id="prova.negata", enabled=False)
        GroupPermissionGrant.objects.create(group=ruolo, permission_id="prova.decisa", enabled=False)
        completa_dal_ruolo_base([ruolo])
        mappa = dict(GroupPermissionGrant.objects.filter(group=ruolo, permission__code__startswith="prova.")
                     .values_list("permission_id", "enabled"))
        self.assertEqual(mappa, {"prova.aperta": True, "prova.decisa": False})

    def test_permessi_di_pagina_operatore_solo_senza_altri_ruoli(self):
        self.attiva_sistema()
        _user, legacy = self.persona("Rossi Mario", ruoli=("ruolo-sicurezza",))
        rspp = AccessGroup.objects.get(code="ruolo-sicurezza")
        self.assertEqual(user_group_ids(legacy.id), [rspp.id])
        _user, senza = self.persona("Bianchi Anna")
        self.assertEqual(user_group_ids(senza.id), [self.base.id])

    def test_ruolo_disattivato_non_toglie_operatore(self):
        self.attiva_sistema()
        _user, legacy = self.persona("Rossi Mario", ruoli=("ruolo-sicurezza",))
        AccessGroup.objects.filter(code="ruolo-sicurezza").update(is_active=False)
        self.assertEqual([g.id for g in ruoli_della_persona(legacy.id)], [self.base.id])
        self.assertEqual(user_group_ids(legacy.id), [self.base.id])

    def test_simulatore_toglie_operatore_quando_si_aggiunge_un_ruolo(self):
        user, _legacy = self.persona("Bianchi Anna")
        rspp = AccessGroup.objects.get(code="ruolo-sicurezza")
        RuoloPermessoModulo.objects.filter(ruolo=rspp, modulo="assenze", azione="creare").delete()
        cambi = effetto_modifica(user, aggiungi=[rspp.id])
        perse = {(c["modulo"].chiave, c["label"]) for c in cambi if c["perde"]}
        self.assertIn("assenze", {m for m, _l in perse})
