"""Chiosco, percorso «Registrato»: ditte fidate per frequenza, tecnici abbreviati, avviso dalle impostazioni."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.models import SiteConfig
from fornitori import chiosco

from . import servizi
from .models import ContattoDitta, DittaAccreditata, Visita
from .tests import Base


@override_settings(RECEPTION_NATIVA=True, CHIOSCO_ALLOWED_IPS=["127.0.0.1"], SECURE_SSL_REDIRECT=False)
class RegistratoTests(Base):
    def setUp(self):
        super().setUp()
        self.alfa = DittaAccreditata.objects.create(nome="Alfa Impianti")
        self.zeta = DittaAccreditata.objects.create(nome="Zeta Servizi")
        self.vuota = DittaAccreditata.objects.create(nome="Beta Senza Tecnici")
        self.spenta = DittaAccreditata.objects.create(nome="Gamma Spenta", attiva=False)
        ContattoDitta.objects.create(ditta=self.spenta, nome="Ugo", cognome="Spento")
        self.a1 = ContattoDitta.objects.create(ditta=self.alfa, nome="Anna", cognome="Prima")
        self.z1 = ContattoDitta.objects.create(ditta=self.zeta, nome="Luca", cognome="Frequente")
        self.z2 = ContattoDitta.objects.create(ditta=self.zeta, nome="Marco", cognome="Raro")
        ContattoDitta.objects.create(ditta=self.zeta, nome="Ivo", cognome="Inattivo", attivo=False)

    def api(self, azione, **dati):
        return self.client.post(reverse("chiosco:api", args=[azione]), json.dumps(dati), content_type="application/json")

    def _visita_passata(self, contatto):
        ospite = servizi.ospite_fornitore(nome=contatto.nome, cognome=contatto.cognome, azienda=contatto.ditta.nome)
        v = servizi.registra_ingresso(ospite, referente_nome="R", tipo=Visita.FORNITORE, ditta=contatto.ditta, contatto=contatto)
        servizi.registra_uscita(v.pk, cartellino=v.cartellino)

    def test_ditte_per_frequenza_solo_attive_con_tecnici(self):
        self.assertEqual([d["nome"] for d in self.api("registrato-ditte").json()["ditte"]], ["Alfa Impianti", "Zeta Servizi"])
        self._visita_passata(self.z1)
        ditte = self.api("registrato-ditte").json()["ditte"]
        self.assertEqual([(d["nome"], d["tecnici"]) for d in ditte], [("Zeta Servizi", 2), ("Alfa Impianti", 1)])

    def test_tecnici_abbreviati_per_frequenza_e_gia_dentro(self):
        self._visita_passata(self.z2)
        self._visita_passata(self.z2)
        tecnici = self.api("registrato-tecnici", azienda_id=self.zeta.pk).json()["tecnici"]
        self.assertEqual([t["nome"] for t in tecnici], ["Raro M.", "Frequente L."])
        self.assertTrue(tecnici[0]["privacy_ok"])
        self.assertNotIn("Marco", json.dumps(tecnici))
        ospite = servizi.ospite_fornitore(nome="Luca", cognome="Frequente", azienda="Zeta Servizi")
        servizi.registra_ingresso(ospite, referente_nome="R", tipo=Visita.FORNITORE, ditta=self.zeta, contatto=self.z1)
        dentro = {t["nome"]: t["dentro"] for t in self.api("registrato-tecnici", azienda_id=self.zeta.pk).json()["tecnici"]}
        self.assertEqual(dentro, {"Raro M.": False, "Frequente L.": True})

    def test_ditta_spenta_o_vuota_rifiutata(self):
        for d in (self.spenta, self.vuota):
            self.assertFalse(self.api("registrato-tecnici", azienda_id=d.pk).json()["success"])
        c = ContattoDitta.objects.get(ditta=self.spenta)
        r = self.api("ingresso-registrato", azienda_id=self.spenta.pk, nominativo_id=c.pk, gdpr_consent=True).json()
        self.assertFalse(r["success"])
        r = self.api("ingresso-registrato", azienda_id=self.alfa.pk, nominativo_id=self.z1.pk, gdpr_consent=True).json()
        self.assertFalse(r["success"])
        self.assertFalse(Visita.objects.exists())

    def test_ingresso_avvisa_l_email_della_ditta_poi_quella_delle_impostazioni(self):
        SiteConfig.set(chiosco.CHIAVE_REFERENTE_REGISTRATO, "reception@example.local", "")
        self.zeta.referente_email = "referente@example.local"
        self.zeta.save()
        r = self.api("ingresso-registrato", azienda_id=self.zeta.pk, nominativo_id=self.z1.pk, gdpr_consent=True).json()
        self.assertTrue(r["success"])
        self.assertTrue(r["avvisato"])
        v = Visita.objects.get(contatto=self.z1)
        self.assertEqual((v.referente_email, v.referente_nome, v.tipo), ("referente@example.local", "Referente Prova", Visita.FORNITORE))
        r = self.api("ingresso-registrato", azienda_id=self.alfa.pk, nominativo_id=self.a1.pk, gdpr_consent=True).json()
        self.assertTrue(r["success"])
        v = Visita.objects.get(contatto=self.a1)
        self.assertEqual((v.referente_email, v.referente_nome), ("reception@example.local", "reception@example.local"))

    def test_senza_email_entra_ma_non_avvisa_nessuno(self):
        r = self.api("ingresso-registrato", azienda_id=self.alfa.pk, nominativo_id=self.a1.pk, gdpr_consent=True).json()
        self.assertTrue(r["success"])
        self.assertFalse(r["avvisato"])
        self.assertEqual(Visita.objects.get().referente_nome, "Reception")

    def test_informativa_va_spuntata_se_mai_accettata(self):
        r = self.api("ingresso-registrato", azienda_id=self.alfa.pk, nominativo_id=self.a1.pk, gdpr_consent=False).json()
        self.assertFalse(r["success"])
        self._visita_passata(self.a1)
        r = self.api("ingresso-registrato", azienda_id=self.alfa.pk, nominativo_id=self.a1.pk, gdpr_consent=False).json()
        self.assertTrue(r["success"])

    def test_pulsante_in_home_e_nel_primo_passo(self):
        self.assertContains(self.client.get(reverse("chiosco:pagina")), "Vengo qui spesso</", count=2)


class ImpostazioniRegistratoTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser("adm_reg", "adm@example.local", "x"))

    def test_email_predefinita_e_della_ditta(self):
        url = reverse("reception:impostazioni")
        self.client.post(url, {"azione": "registrato", "referente_email": "non-valida"})
        self.assertEqual(SiteConfig.get(chiosco.CHIAVE_REFERENTE_REGISTRATO, ""), "")
        self.client.post(url, {"azione": "registrato", "referente_email": "reception@example.local"})
        self.assertEqual(SiteConfig.get(chiosco.CHIAVE_REFERENTE_REGISTRATO, ""), "reception@example.local")
        self.assertContains(self.client.get(url), "reception@example.local")
        d = DittaAccreditata.objects.create(nome="Alfa Impianti")
        self.client.post(reverse("reception:ditte"), {"azione": "referente", "pk": d.pk, "referente_email": "capo@example.local"})
        d.refresh_from_db()
        self.assertEqual(d.referente_email, "capo@example.local")
        self.assertContains(self.client.get(reverse("reception:ditte")), "capo@example.local")
