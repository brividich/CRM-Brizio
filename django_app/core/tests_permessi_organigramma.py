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

    def test_scheda_persona_mostra_da_dove_arriva_il_ruolo(self):
        self.r_personale.profili_permessi.add(self.hr)
        _user, legacy = self.persona("Persona organigramma")
        self.assegna(legacy, self.r_personale)
        risposta = self.client.get(f"/admin-portale/ruoli-portale/?tab=persone&persona={legacy.id}")
        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "perché in organigramma è")
        self.assertContains(risposta, self.r_personale.nome)
