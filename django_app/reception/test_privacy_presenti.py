"""Informativa già accettata al chiosco e registrazioni al volo da «Presenti in azienda»."""
from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from fornitori import chiosco

from . import informativa, servizi
from .models import ContattoDitta, DittaAccreditata, Ospite, Preregistrazione, Visita
from .tests import Base


@override_settings(RECEPTION_NATIVA=True, CHIOSCO_ALLOWED_IPS=["127.0.0.1"], SECURE_SSL_REDIRECT=False)
class InformativaRicordataTests(Base):
    def api(self, azione, **dati):
        return self.client.post(reverse("chiosco:api", args=[azione]), json.dumps(dati), content_type="application/json")

    def _letta_ieri(self, ospite, versione=None):
        Ospite.objects.filter(pk=ospite.pk).update(informativa_letta_il=timezone.now() - timedelta(days=1),
                                                   informativa_versione=versione or informativa.versione())
        ospite.refresh_from_db()
        return ospite.informativa_letta_il

    def test_chi_ha_gia_accettato_entra_senza_spunta_e_la_data_resta(self):
        self.entra(); servizi.registra_uscita(Visita.objects.get().pk)
        letta = self._letta_ieri(self.ospite)
        trovato = self.api("riconosci", nome="Mario", cognome="Esempio").json()["trovati"][0]
        self.assertTrue(trovato["privacy_ok"])
        r = self.api("ingresso-ospite", ospite=trovato["chiave"], referente_id=self.ref.pk, motivo="Altro")
        self.assertTrue(r.json()["success"], r.json())
        self.ospite.refresh_from_db()
        self.assertEqual(self.ospite.informativa_letta_il, letta)

    def test_testo_cambiato_si_rilegge(self):
        self.entra(); servizi.registra_uscita(Visita.objects.get().pk)
        self._letta_ieri(self.ospite, versione="vecchia")
        trovato = self.api("riconosci", nome="Mario", cognome="Esempio").json()["trovati"][0]
        self.assertFalse(trovato["privacy_ok"])
        r = self.api("ingresso-ospite", ospite=trovato["chiave"], referente_id=self.ref.pk, motivo="Altro")
        self.assertFalse(r.json()["success"])
        self.assertTrue(self.api("ingresso-ospite", ospite=trovato["chiave"], referente_id=self.ref.pk, motivo="Altro",
                                 gdpr_consent=True).json()["success"])
        self.ospite.refresh_from_db()
        self.assertEqual(self.ospite.informativa_versione, informativa.versione())

    def test_prima_visita_chiede_sempre(self):
        r = self.api("ingresso", first_name="Luisa", last_name="Prova", referente_id=self.ref.pk, motivo="Altro")
        self.assertFalse(r.json()["success"])

    def test_fornitore_riconosciuto(self):
        d = DittaAccreditata.objects.create(nome="Ditta Prova")
        ContattoDitta.objects.create(ditta=d, nome="Mario", cognome="Esempio")
        self._letta_ieri(self.ospite)
        trovato = next(t for t in self.api("riconosci", nome="Mario", cognome="Esempio").json()["trovati"] if t["tipo"] == "fornitore")
        self.assertTrue(trovato["privacy_ok"])
        self.assertTrue(self.api("ingresso-fornitore", fornitore=trovato["chiave"], referente_id=self.ref.pk).json()["success"])

    def test_fornitore_scelto_da_elenco_spunta_sempre(self):
        d = DittaAccreditata.objects.create(nome="Ditta Prova")
        c = ContattoDitta.objects.create(ditta=d, nome="Mario", cognome="Esempio")
        self._letta_ieri(self.ospite)
        r = self.api("ingresso-fornitore", azienda_id=d.pk, nominativo_id=c.pk, referente_id=self.ref.pk)
        self.assertFalse(r.json()["success"])

    def test_codice_d_invito(self):
        self._letta_ieri(self.ospite)
        Preregistrazione.objects.create(codice="ABCD2345", ospite_nome="Mario Esempio", ospite_email="m@example.local",
                                        referente_nome="R", motivo="Altro", scade_il=timezone.now() + timedelta(days=1))
        self.assertTrue(self.api("prereg-cerca", code="ABCD2345").json()["prereg"]["privacy_ok"])
        self.assertEqual(self.api("prereg-entra", code="ABCD2345").json()["badge_number"], "01")

    def test_senza_reception_nell_hub_nessun_ricordo(self):
        self._letta_ieri(self.ospite)
        with override_settings(RECEPTION_NATIVA=False):
            self.assertFalse(chiosco.privacy_ricordata_ospite(self.ospite.pk))


@override_settings(RECEPTION_NATIVA=True)
class PresentiRegistraTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser("adm_pr", "adm@example.local", "x"))

    def test_visitatore_diventa_fornitore(self):
        v = self.entra()
        r = self.client.post(reverse("reception:presenti_come_fornitore", args=[v.pk]))
        self.assertRedirects(r, reverse("presenti:home"), fetch_redirect_response=False)
        v.refresh_from_db()
        self.assertEqual((v.tipo, v.ditta.nome, v.contatto.cognome), (Visita.FORNITORE, "Ditta Prova", "Esempio"))
        self.assertEqual(chiosco.riconosci("Mario", "Esempio")[0]["tipo"], "fornitore")

    def test_senza_azienda_non_converte(self):
        o = servizi.ospite_da_dati(nome="Anna", cognome="Senza", email="a@example.local")
        v = self.entra(o)
        self.client.post(reverse("reception:presenti_come_fornitore", args=[v.pk]))
        v.refresh_from_db()
        self.assertEqual(v.tipo, Visita.NORMALE)

    def test_registra_fornitore_nuovo_senza_mail(self):
        self.client.post(reverse("reception:presenti_registra"), {
            "tipo": "fornitore", "nome": "Luca", "cognome": "Nuovo", "azienda": "Impianti Nuovi Srl",
            "referente": self.ref.pk, "cartellino": "02"})
        v = Visita.objects.get()
        self.assertEqual((v.tipo, v.cartellino, v.creata_da, v.mail_stato), (Visita.FORNITORE, "02", "PRESENTI", Visita.MAIL_INVIATA))
        self.assertTrue(ContattoDitta.objects.filter(ditta__nome="Impianti Nuovi Srl", cognome="Nuovo").exists())

    def test_registra_ospite_senza_cartellino(self):
        self.client.post(reverse("reception:presenti_registra"), {
            "tipo": "ospite", "nome": "Mario", "cognome": "Esempio", "azienda": "Ditta Prova",
            "referente": self.ref.pk, "cartellino": "", "motivo": "Altro"})
        v = Visita.objects.get()
        self.assertEqual((v.ospite_id, v.cartellino, v.tipo), (self.ospite.pk, Visita.SENZA_CARTELLINO, Visita.NORMALE))

    def test_presenti_mostra_i_pulsanti(self):
        self.entra()
        r = self.client.get(reverse("presenti:home"))
        self.assertContains(r, "Registra chi è dentro")
        self.assertContains(r, reverse("reception:presenti_registra"))

    def test_solo_post_e_login(self):
        self.assertEqual(self.client.get(reverse("reception:presenti_registra")).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("reception:presenti_registra")).status_code, 302)

    @override_settings(RECEPTION_NATIVA=False)
    def test_con_guestportal_niente(self):
        self.client.post(reverse("reception:presenti_registra"), {
            "tipo": "ospite", "nome": "X", "cognome": "Y", "referente": self.ref.pk})
        self.assertFalse(Visita.objects.exists())
