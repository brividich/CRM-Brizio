"""Proposte dai log di utilizzo (21/11): unità e FIR in blocco, numero alla creazione, registrazione già annullata.

Dati sintetici.
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog

from .completa import coppie_fir, proposte_unita, unita_da_testo
from .models import RegistroRifiuti
from .tests_scarico_originario import _mov

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CompletaInBloccoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-bl", email="bl@example.com", password="x")
        self.client.force_login(self.admin)
        self.g = timezone.localdate() - timedelta(days=40)

    def test_unita_dal_testo(self):
        self.assertEqual(unita_da_testo("12.01.01 Sfridi Ferro Kg"), "kg")
        self.assertEqual(unita_da_testo("13.02.08 * Olio Esausto Lt"), "l")
        self.assertEqual(unita_da_testo("20.01.21 * Luci led e lampadineKg"), "kg")
        self.assertEqual(unita_da_testo("17.04.02 Pezzame di Alluminio"), "")
        self.assertEqual(unita_da_testo("12 01 01"), "")

    def test_proposta_unita_scelta_vince_sulla_descrizione(self):
        _mov("C", self.g, 100, codice="12.01.09 * Acqua emulsionata Lt", unita="kg")
        vuota = _mov("C", self.g, 50, codice="12.01.09 * Acqua emulsionata Lt", unita="")
        _mov("C", self.g, 70, codice="13.02.08 * Olio Esausto Lt", unita="", salva=True)
        _mov("C", self.g, 70, codice="13.02.08 * Olio Esausto Lt", unita="", annullato=True)
        per = {p["chiave"]: p for p in proposte_unita()}
        self.assertEqual(per["120109"]["unita"], "kg")
        self.assertEqual(per["120109"]["dal_testo"], "l")
        self.assertEqual(per["130208"]["unita"], "l")
        self.assertEqual((per["130208"]["righe"], per["130208"]["consolidate"]), (1, 1))

        pagina = self.client.get(reverse("rentri_verifica"))
        self.assertContains(pagina, 'id="unita"')
        r = self.client.post(reverse("rentri_completa_unita"), {
            "codice": ["120109", "130208"], "unita_120109": "kg", "unita_130208": "l",
        })
        self.assertEqual(r.status_code, 302)
        vuota.refresh_from_db()
        self.assertEqual(vuota.unita, "kg")
        self.assertEqual(RegistroRifiuti.objects.filter(unita="").count(), 1)  # solo l'annullata
        self.assertTrue(AuditLog.objects.filter(azione="rentri_unita_completata", oggetto_id=str(vuota.pk)).exists())

    def test_sposta_fir_da_r_a_m(self):
        c = _mov("C", self.g, 100)
        n = f"{self.g.year}/8001"
        rett = _mov("R", self.g, None, rif_op=c.id_registrazione, rettifica_scarico=Decimal("90"),
                    id_registrazione=n, arrivo_fir="FIR NR. XXXXX 000071 JY\nSCARICO VERIFICATO")
        eff = _mov("M", self.g, None, rif_op=c.id_registrazione, rettifica_scarico=Decimal("-90"), id_registrazione=n)
        # Coppia consolidata: non si tocca.
        n2 = f"{self.g.year}/8002"
        _mov("R", self.g, None, rettifica_scarico=Decimal("5"), id_registrazione=n2, arrivo_fir="FIR B", salva=True)
        _mov("M", self.g, None, rettifica_scarico=Decimal("-5"), id_registrazione=n2, salva=True)
        self.assertEqual([x["numero"] for x in coppie_fir()], [n])
        r = self.client.post(reverse("rentri_sposta_fir"), {"numero": [n, n2]})
        self.assertEqual(r.status_code, 302)
        rett.refresh_from_db()
        eff.refresh_from_db()
        self.assertEqual(eff.arrivo_fir, "FIR NR. XXXXX 000071 JY SCARICO VERIFICATO")
        self.assertEqual(rett.arrivo_fir, "")
        self.assertEqual(RegistroRifiuti.objects.get(tipo="R", id_registrazione=n2).arrivo_fir, "FIR B")

    def test_azioni_solo_per_i_gestori(self):
        utente = User.objects.create_user(username="rentri-lettore", password="x")
        self.client.force_login(utente)
        r = self.client.post(reverse("rentri_completa_unita"), {"codice": ["120101"], "unita_120101": "kg"})
        self.assertIn(r.status_code, (302, 403))
        self.assertFalse(AuditLog.objects.filter(azione="rentri_unita_completate").exists())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NuovoMovimentoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-nuovo", email="nu@example.com", password="x")
        self.client.force_login(self.admin)
        self.g = timezone.localdate() - timedelta(days=20)

    def nuovo(self, url_name, **dati):
        base = {"data": self.g.isoformat(), "codice": "12.01.01 Sfridi Ferro Kg", "unita": "kg"}
        base.update(dati)
        return self.client.post(reverse(url_name), data=json.dumps(base), content_type="application/json")

    def test_m_da_o_propone_il_numero_della_o(self):
        c = _mov("C", self.g, 2500, codice="12.01.01 Sfridi Ferro Kg", unita="kg")
        o = _mov("O", self.g, -2500, rif_op=c.id_registrazione, codice="12.01.01 Sfridi Ferro Kg", unita="kg")
        pagina = self.client.get(reverse("rentri_scarico_effettivo") + f"?da={o.pk}")
        self.assertContains(pagina, f'value="{o.id_registrazione}"')
        self.assertContains(pagina, f"Stesso numero di O {o.id_registrazione}")
        # Da un carico non si propone (un C non condivide il numero).
        pagina = self.client.get(reverse("rentri_scarico_originale") + f"?da={c.pk}")
        self.assertNotContains(pagina, "Stesso numero di")

        r = self.nuovo("rentri_scarico_effettivo", rif_op=o.id_registrazione, rettifica_scarico="-2480",
                       id_registrazione=o.id_registrazione)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["id_registrazione"], o.id_registrazione)
        self.assertEqual(RegistroRifiuti.objects.filter(id_registrazione=o.id_registrazione).count(), 2)

    def test_numero_vuoto_lo_assegna_il_portale_e_doppio_rifiutato(self):
        c = _mov("C", self.g, 100, codice="12.01.01 Sfridi Ferro Kg", unita="kg")
        r = self.nuovo("rentri_carico", quantita="10")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["id_registrazione"])
        r = self.nuovo("rentri_carico", quantita="10", id_registrazione=c.id_registrazione)
        self.assertEqual(r.status_code, 400)
        self.assertIn("già usato", r.json()["error"])

    def test_registrazione_gia_annullata(self):
        # Storno storico: O positiva su un carico già scaricato, il deposito la rifiuterebbe.
        c = _mov("C", self.g, 2500, codice="12.01.01 Sfridi Ferro Kg", unita="kg")
        _mov("O", self.g, -2500, rif_op=c.id_registrazione, codice="12.01.01 Sfridi Ferro Kg", unita="kg")
        numero = f"{self.g.year}/9862"
        r = self.nuovo("rentri_scarico_originale", quantita="-2500", rif_op=c.id_registrazione,
                       id_registrazione=numero)
        self.assertEqual(r.status_code, 400)
        r = self.nuovo("rentri_scarico_originale", quantita="-2500", rif_op=c.id_registrazione,
                       id_registrazione=numero, annullata="true", motivo_annullamento="no")
        self.assertEqual(r.status_code, 400)
        self.assertIn("motivo", r.json()["error"])
        r = self.nuovo("rentri_scarico_originale", quantita="-2500", rif_op=c.id_registrazione,
                       id_registrazione=numero, annullata="true",
                       motivo_annullamento="Annullata dalla registrazione 9863: quantità errata")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["annullata"])
        o = RegistroRifiuti.objects.get(id_registrazione=numero)
        self.assertTrue(o.annullato)
        self.assertEqual(o.motivo_annullamento, "Annullata dalla registrazione 9863: quantità errata")
        self.assertFalse(RegistroRifiuti.objects.attivi().filter(pk=o.pk).exists())
        voce = AuditLog.objects.filter(azione="rentri_movimento_creato", oggetto_id=str(o.pk)).first()
        self.assertIn("gia_annullata", voce.dettaglio)
