"""Storico modifiche dei cataloghi mansioni e ruoli.

Le voci arrivano dall'audit automatico (segnali), ora agganciato al record con
``oggetto_tipo``/``oggetto_id``, più le azioni esplicite che i segnali non vedono
(liste M2M dei requisiti, qualifiche del ruolo). Qui si verifica che la pagina
risponda a «chi ha cambiato cosa, da cosa a cosa» anche per le voci eliminate.
"""
from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.audit import storico_leggibile, storico_oggetto
from core.models import AuditLog

from .models import AmbitoRuolo, Mansione, RuoloOperativo, RuoloQualifica, TipoQualifica

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class StoricoCatalogoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="storico_admin", email="storico_admin@x.local", password="x"
        )
        cls.utente = User.objects.create_user(username="storico_base", password="x")

    def setUp(self):
        self.client.force_login(self.admin)

    # -- aggancio dell'audit automatico ------------------------------------

    def test_creazione_agganciata_al_record(self):
        mansione = Mansione.objects.create(nome="Saldatore TEST")
        azioni = [v.azione for v in storico_oggetto(mansione)]
        self.assertIn("auto_insert", azioni)

    def test_modifica_mostra_prima_e_dopo_con_etichette(self):
        mansione = Mansione.objects.create(nome="Verniciatore TEST", livello_rischio="")
        self.client.post(reverse("anagrafica:mansione_edit", args=[mansione.pk]), {
            "nome": "Verniciatore TEST", "livello_rischio": "A", "colore": "#123456", "is_active": "1",
        })
        voci = storico_leggibile(storico_oggetto(mansione))
        modifica = next(v for v in voci if v.azione == "auto_update")
        self.assertEqual(modifica.azione_label, "Modifica")
        righe = {r["campo"]: r for r in modifica.righe}
        campo_rischio = str(Mansione._meta.get_field("livello_rischio").verbose_name)
        campo_rischio = campo_rischio[:1].upper() + campo_rischio[1:]
        self.assertIn(campo_rischio, righe)
        self.assertEqual(righe[campo_rischio]["prima"], "—")
        self.assertEqual(righe[campo_rischio]["dopo"], dict(Mansione.LIVELLO_RISCHIO_CHOICES)["A"])

        risposta = self.client.get(reverse("anagrafica:mansione_storico", args=[mansione.pk]))
        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "Storico modifiche · Verniciatore TEST")
        self.assertContains(risposta, campo_rischio)
        self.assertContains(risposta, "#storico-cataloghi")

    def test_fk_mostra_il_nome_del_record_collegato(self):
        ambito = AmbitoRuolo.objects.create(nome="Ambito storico TEST")
        ruolo = RuoloOperativo.objects.create(nome="Ruolo storico TEST")
        ruolo.ambito = ambito
        ruolo.save()
        modifica = next(v for v in storico_leggibile(storico_oggetto(ruolo)) if v.azione == "auto_update")
        self.assertIn("Ambito storico TEST", [r["dopo"] for r in modifica.righe])

    # -- voci eliminate e catalogo -----------------------------------------

    def test_mansione_eliminata_resta_nello_storico(self):
        mansione = Mansione.objects.create(nome="Da eliminare TEST")
        pk = mansione.pk
        self.client.post(reverse("anagrafica:mansione_delete", args=[pk]))
        self.assertFalse(Mansione.objects.filter(pk=pk).exists())

        catalogo = self.client.get(reverse("anagrafica:mansioni_storico"))
        self.assertEqual(catalogo.status_code, 200)
        self.assertContains(catalogo, "Eliminazione")
        self.assertContains(catalogo, "Da eliminare TEST")

        voce = self.client.get(reverse("anagrafica:mansione_storico", args=[pk]))
        self.assertEqual(voce.status_code, 200)
        self.assertContains(voce, "La voce è stata eliminata")
        self.assertContains(voce, "Da eliminare TEST")

    def test_qualifiche_del_ruolo_nello_storico_del_ruolo(self):
        ruolo = RuoloOperativo.objects.create(nome="Ruolo qualifiche TEST")
        qualifica = TipoQualifica.objects.create(nome="Patentino storico TEST")
        self.client.post(reverse("anagrafica:ruolo_qualifica_aggiungi", args=[ruolo.pk]),
                         {"qualifica_id": qualifica.pk})
        assoc = RuoloQualifica.objects.get(ruolo=ruolo, qualifica=qualifica)
        self.client.post(reverse("anagrafica:ruolo_qualifica_rimuovi", args=[ruolo.pk, assoc.pk]))

        azioni = [v.azione for v in storico_oggetto(ruolo)]
        self.assertIn("ruolo_qualifica_aggiunta", azioni)
        self.assertIn("ruolo_qualifica_tolta", azioni)
        risposta = self.client.get(reverse("anagrafica:ruolo_operativo_storico", args=[ruolo.pk]))
        self.assertContains(risposta, "Patentino storico TEST")

    def test_pagine_catalogo_e_pulsanti(self):
        mansione = Mansione.objects.create(nome="Pulsanti TEST")
        ruolo = RuoloOperativo.objects.create(nome="Pulsanti ruolo TEST")
        self.assertContains(self.client.get(reverse("anagrafica:ruoli_operativi_storico")), "Pulsanti ruolo TEST")
        lista_mansioni = self.client.get(reverse("anagrafica:mansioni_list"))
        self.assertContains(lista_mansioni, reverse("anagrafica:mansione_storico", args=[mansione.pk]))
        self.assertContains(lista_mansioni, reverse("anagrafica:mansioni_storico"))
        lista_ruoli = self.client.get(reverse("anagrafica:ruoli_operativi_list"))
        self.assertContains(lista_ruoli, reverse("anagrafica:ruolo_operativo_storico", args=[ruolo.pk]))
        self.assertContains(lista_ruoli, reverse("anagrafica:ruoli_operativi_storico"))

    # -- permessi ----------------------------------------------------------

    def test_riservato_a_chi_gestisce_il_catalogo(self):
        self.client.force_login(self.utente)
        risposta = self.client.get(reverse("anagrafica:mansioni_storico"))
        self.assertNotEqual(risposta.status_code, 200)

    # -- comando di ricollegamento -----------------------------------------

    def test_comando_ricollega_le_voci_storiche(self):
        mansione = Mansione.objects.create(nome="Storica TEST")
        # Come le scriveva il segnale prima dell'aggancio.
        AuditLog.objects.filter(oggetto_tipo="anagrafica.mansione", oggetto_id=str(mansione.pk)).update(
            oggetto_tipo="", oggetto_id="",
        )
        self.assertEqual(list(storico_oggetto(mansione)), [])

        out = StringIO()
        call_command("collega_audit_oggetti", "--app", "anagrafica", "--dry-run", stdout=out)
        self.assertEqual(list(storico_oggetto(mansione)), [])
        call_command("collega_audit_oggetti", "--app", "anagrafica", stdout=out)
        self.assertIn("auto_insert", [v.azione for v in storico_oggetto(mansione)])
