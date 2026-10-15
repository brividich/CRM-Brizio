"""Ruoli del portale che arrivano dall'organigramma (core.permessi.organigramma).

Dati sintetici: persone, ruoli d'organigramma e assegnazioni create nel test.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase

from core.models import AccessGroup, AuditLog
from core.permessi.motore import decisione
from core.permessi.preset import applica_preset
from core.tests_permessi import PersoneMixin, ensure_anagrafica_table

User = get_user_model()


class OrganigrammaMixin(PersoneMixin):
    def setUp(self):
        cache.clear()
        ensure_anagrafica_table()
        applica_preset()
        from anagrafica.models import RuoloOperativo

        self.r_personale = RuoloOperativo.objects.create(nome="Addetto ufficio personale TEST")
        self.r_altro = RuoloOperativo.objects.create(nome="Operatore TEST")
        self.hr = AccessGroup.objects.get(code="ruolo-hr")

    def assegna(self, legacy, ruolo):
        from anagrafica.models import DipendenteRuoloOperativo

        with connection.cursor() as c:
            c.execute(
                "INSERT OR IGNORE INTO anagrafica_dipendenti (id, nome, utente_id) VALUES (%s, %s, %s)",
                [9000 + legacy.id, legacy.nome, legacy.id],
            )
        return DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=9000 + legacy.id, ruolo=ruolo)


class RuoliDaOrganigrammaTests(OrganigrammaMixin, TestCase):
    def test_chi_ricopre_il_ruolo_collegato_riceve_il_ruolo_del_portale(self):
        self.r_personale.profili_permessi.add(self.hr)
        user, legacy = self.persona("Personale")
        self.assegna(legacy, self.r_personale)
        user = self.ricarica(user)
        esito = decisione(user, "anagrafica", "vedere")
        self.assertEqual((esito.consentito, esito.ambito), (True, "tutti"))
        self.assertEqual(esito.ruolo, self.hr.label)

    def test_senza_collegamento_vale_solo_il_dipendente(self):
        user, legacy = self.persona("Non collegato")
        self.assegna(legacy, self.r_altro)
        self.assertFalse(decisione(self.ricarica(user), "anagrafica", "vedere").consentito)

    def test_tolta_l_assegnazione_il_ruolo_sparisce(self):
        self.r_personale.profili_permessi.add(self.hr)
        user, legacy = self.persona("Uscente")
        assegnazione = self.assegna(legacy, self.r_personale)
        self.assertTrue(decisione(self.ricarica(user), "anagrafica", "vedere").consentito)
        assegnazione.delete()  # il segnale azzera le cache, nessuna invalidazione a mano
        self.assertFalse(decisione(self.ricarica(user), "anagrafica", "vedere").consentito)

    def test_collegamento_fatto_dopo_vale_subito(self):
        user, legacy = self.persona("Collegato dopo")
        self.assegna(legacy, self.r_personale)
        self.assertFalse(decisione(self.ricarica(user), "anagrafica", "vedere").consentito)
        self.r_personale.profili_permessi.add(self.hr)  # m2m_changed azzera le cache
        self.assertTrue(decisione(self.ricarica(user), "anagrafica", "vedere").consentito)

    def test_amministratore_non_arriva_mai_dall_organigramma(self):
        admin = AccessGroup.objects.get(code="ruolo-amministratore")
        self.r_personale.profili_permessi.add(admin)
        user, legacy = self.persona("Furbo")
        self.assegna(legacy, self.r_personale)
        user = self.ricarica(user)
        self.assertFalse(decisione(user, "gestione_utenti", "gestire").consentito)
        self.assertFalse(decisione(user, "anagrafica", "vedere").consentito)

    def test_ruolo_del_portale_disattivo_non_arriva(self):
        self.r_personale.profili_permessi.add(self.hr)
        AccessGroup.objects.filter(pk=self.hr.pk).update(is_active=False)
        user, legacy = self.persona("Disattivo")
        self.assegna(legacy, self.r_personale)
        self.assertFalse(decisione(self.ricarica(user), "anagrafica", "vedere").consentito)

    def test_ruolo_d_organigramma_disattivo_non_conta(self):
        self.r_personale.profili_permessi.add(self.hr)
        user, legacy = self.persona("Ruolo spento")
        self.assegna(legacy, self.r_personale)
        self.r_personale.is_active = False
        self.r_personale.save()
        self.assertFalse(decisione(self.ricarica(user), "anagrafica", "vedere").consentito)

    def test_si_somma_ai_ruoli_assegnati_a_mano(self):
        self.r_personale.profili_permessi.add(self.hr)
        user, legacy = self.persona("Due ruoli", ruoli=("ruolo-tecnico-it",))
        self.assegna(legacy, self.r_personale)
        user = self.ricarica(user)
        self.assertTrue(decisione(user, "anagrafica", "vedere").consentito)  # dall'organigramma
        self.assertTrue(decisione(user, "soc", "gestire").consentito)  # a mano

    def test_permessi_di_pagina_seguono_i_ruoli_dall_organigramma(self):
        from core.acl_resolver import describe_user_groups, user_group_ids

        self.r_personale.profili_permessi.add(self.hr)
        _user, legacy = self.persona("Pagine")
        self.assegna(legacy, self.r_personale)
        self.assertIn(self.hr.id, user_group_ids(legacy.id))
        self.assertIn(self.hr.id, [g["id"] for g in describe_user_groups(legacy.id)])


class ScadenzaRuoliTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        applica_preset()

    def test_ruolo_a_mano_scaduto_non_conta(self):
        from datetime import timedelta

        from django.utils import timezone

        from core.acl_resolver import user_group_ids
        from core.models import AccessGroupMembership

        user, legacy = self.persona("RSPP esterno", ruoli=("ruolo-sicurezza",))
        rspp = AccessGroup.objects.get(code="ruolo-sicurezza")
        self.assertTrue(decisione(self.ricarica(user), "rilevazione_incidenti", "gestire").consentito)
        oggi = timezone.localdate()
        AccessGroupMembership.objects.filter(legacy_user_id=legacy.id).update(scade_il=oggi)
        self.assertTrue(decisione(self.ricarica(user), "rilevazione_incidenti", "gestire").consentito)  # vale oggi
        AccessGroupMembership.objects.filter(legacy_user_id=legacy.id).update(scade_il=oggi - timedelta(days=1))
        self.assertFalse(decisione(self.ricarica(user), "rilevazione_incidenti", "gestire").consentito)
        self.assertNotIn(rspp.id, user_group_ids(legacy.id))

    def test_amministratore_scaduto_non_e_piu_amministratore(self):
        from datetime import timedelta

        from django.utils import timezone

        from core.models import AccessGroupMembership
        from core.permessi.cache import invalida_permessi, utenti_amministratori_da_ruolo

        _user, legacy = self.persona("Admin a tempo", ruoli=("ruolo-amministratore",))
        self.assertIn(legacy.id, utenti_amministratori_da_ruolo())
        AccessGroupMembership.objects.filter(legacy_user_id=legacy.id).update(
            scade_il=timezone.localdate() - timedelta(days=1)
        )
        invalida_permessi()
        self.assertNotIn(legacy.id, utenti_amministratori_da_ruolo())


class ModelloPresetTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        applica_preset()

    def test_operatore_ha_solo_il_minimo(self):
        user, _ = self.persona("Operatore")
        for modulo, azione in (
            ("assenze", "creare"), ("notizie", "vedere"), ("schede_sicurezza", "vedere"),
            ("rilevazione_incidenti", "creare"), ("dpi", "creare"), ("procedure", "vedere"),
            ("anomalie", "creare"), ("ticket_manutenzione", "creare"),
        ):
            self.assertTrue(decisione(user, modulo, azione).consentito, f"{modulo}.{azione}")
        for modulo, azione in (
            ("ticket_it", "creare"), ("suggestion_corner", "creare"), ("assistente_ai", "vedere"),
            ("glossario", "vedere"), ("sistema_gestione", "vedere"), ("formazione", "vedere"),
        ):
            self.assertFalse(decisione(user, modulo, azione).consentito, f"{modulo}.{azione}")

    def test_referti_solo_a_gestione_personale(self):
        personale, _ = self.persona("Paghe", ruoli=("ruolo-hr",))
        capo, _ = self.persona("Capo", ruoli=("ruolo-responsabile",))
        self.assertTrue(decisione(personale, "visite_mediche", "referti").consentito)
        self.assertTrue(decisione(capo, "visite_mediche", "vedere").consentito)
        self.assertFalse(decisione(capo, "visite_mediche", "referti").consentito)

    def test_registrazioni_sgi_non_si_cancellano_dai_preset(self):
        from core.permessi.preset import PRESETS

        registrazioni = (
            "rilevazione_incidenti", "schede_sicurezza", "rentri", "sistema_gestione", "capa", "timbri", "soc",
        )
        for preset in PRESETS:
            for modulo in registrazioni:
                with self.subTest(preset=preset.chiave, modulo=modulo):
                    self.assertNotIn("cancellare", preset.celle.get(modulo, {}))

    def test_riallineamento_rispetta_le_modifiche_a_mano(self):
        from core.models import RuoloPermessoModulo
        from core.permessi.preset import riallinea_preset_modello

        base = AccessGroup.objects.get(code="ruolo-dipendente")
        base.label, base.priority = "Dipendente", 100
        base.save()
        RuoloPermessoModulo.objects.create(ruolo=base, modulo="ticket_it", azione="creare", ambito="propri",
                                           note="preset dipendente")
        RuoloPermessoModulo.objects.create(ruolo=base, modulo="glossario", azione="vedere", ambito="tutti",
                                           note="modificata a mano")
        riallinea_preset_modello()
        base.refresh_from_db()
        self.assertEqual(base.label, "Operatore")
        self.assertFalse(RuoloPermessoModulo.objects.filter(ruolo=base, modulo="ticket_it").exists())
        self.assertTrue(RuoloPermessoModulo.objects.filter(ruolo=base, modulo="glossario").exists())


class PaginaCollegamentoOrganigrammaTests(OrganigrammaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username="admin.org@example.test", password="x", is_superuser=True)
        self.client.force_login(self.admin)

    def test_collegare_e_scollegare_dalla_matrice(self):
        url = f"/admin-portale/ruoli-portale/organigramma/{self.hr.id}/"
        self.client.post(url, {"ruoli_organigramma": [self.r_personale.id]})
        self.assertEqual(list(self.hr.ruoli_organigramma.all()), [self.r_personale])
        self.assertTrue(AuditLog.objects.filter(azione="permessi_ruolo_organigramma").exists())
        self.client.post(url, {})
        self.assertFalse(self.hr.ruoli_organigramma.exists())

    def test_amministratore_non_si_collega(self):
        admin = AccessGroup.objects.get(code="ruolo-amministratore")
        self.client.post(
            f"/admin-portale/ruoli-portale/organigramma/{admin.id}/", {"ruoli_organigramma": [self.r_personale.id]}
        )
        self.assertFalse(admin.ruoli_organigramma.exists())

    def test_matrice_mostra_i_ruoli_d_organigramma(self):
        risposta = self.client.get(f"/admin-portale/ruoli-portale/?tab=matrice&ruolo={self.hr.id}")
        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "Dall'organigramma")
        self.assertContains(risposta, self.r_personale.nome)

    def test_scadenza_dei_ruoli_dalla_scheda_persona(self):
        from core.models import AccessGroupMembership

        _user, legacy = self.persona("Esterno")
        rspp = AccessGroup.objects.get(code="ruolo-sicurezza")
        url = f"/admin-portale/ruoli-portale/persona/{legacy.id}/"
        self.client.post(url, {"ruoli": [rspp.id], "scade_il": "2030-12-31"})
        self.assertEqual(str(AccessGroupMembership.objects.get(legacy_user_id=legacy.id).scade_il), "2030-12-31")
        self.client.post(url, {"ruoli": [rspp.id], "scade_il": ""})
        self.assertIsNone(AccessGroupMembership.objects.get(legacy_user_id=legacy.id).scade_il)
        self.assertTrue(AuditLog.objects.filter(azione="permessi_scadenza_persona").exists())

    def test_scheda_persona_mostra_da_dove_arriva_il_ruolo(self):
        self.r_personale.profili_permessi.add(self.hr)
        _user, legacy = self.persona("Persona organigramma")
        self.assegna(legacy, self.r_personale)
        risposta = self.client.get(f"/admin-portale/ruoli-portale/?tab=persone&persona={legacy.id}")
        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "perché in organigramma è")
        self.assertContains(risposta, self.r_personale.nome)
