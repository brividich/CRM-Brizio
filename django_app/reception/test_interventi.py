"""«Le tue visite» e collegamento visita → ticket IT/MAN o OdL (``fornitori.IngressoIntervento``). Dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore
from assets.models import Asset, WorkOrder
from core.models import UserOnboarding
from fornitori.models import DittaGuestPortal, IngressoIntervento
from tickets.models import Ticket

from . import interventi, servizi
from .models import Cartellino, CategoriaVisita, DittaAccreditata, Preregistrazione, Referente, Visita

MAIL = "core.email_utils.send_hub_mail"
EMAIL_REF = "tecnico.ref@example.local"
PUO_ODL = "reception.interventi.puo_collegare_odl"


# ACL legacy spenta: qui si prova la regola della view (referente, ticket, OdL), non i binding.
@override_settings(RECEPTION_NATIVA=True, LEGACY_AUTH_ENABLED=False)
class Base(TestCase):
    def setUp(self):
        cache.clear()
        odl = patch(PUO_ODL, return_value=False)
        odl.start()
        self.addCleanup(odl.stop)
        self.user = get_user_model().objects.create_user("tec_ref", EMAIL_REF, "x", first_name="Tecnico", last_name="Prova")
        UserOnboarding.objects.get_or_create(user=self.user, defaults={"completed": True})
        self.client.force_login(self.user)
        self.ref = Referente.objects.create(nome="Tecnico", cognome="Prova", email=EMAIL_REF)
        CategoriaVisita.objects.create(nome="Riunione")
        CategoriaVisita.objects.create(nome="Manutenzione", collega_interventi=True)
        Cartellino.objects.create(numero="01")
        Cartellino.objects.create(numero="02")
        # Ticket IT aperto dal referente: lo collega anche senza esserne gestore.
        self.ticket = Ticket.objects.create(tipo="IT", titolo="Stampante di rete ferma", descrizione="x", categoria="ALTRO_IT",
                                            richiedente_nome="Tecnico Prova", richiedente_user=self.user)
        self.asset = Asset.objects.create(asset_tag="AST-RC-001", name="Pressa prova")
        self.odl = WorkOrder.objects.create(asset=self.asset, title="Sostituzione guarnizione", assigned_to=self.user)
        self.ospite = servizi.ospite_da_dati(nome="Mario", cognome="Esterno", email="mario@example.local", azienda="Ditta Esempio Srl")

    def visita(self, motivo="Manutenzione", ospite=None, **kw) -> Visita:
        return servizi.registra_ingresso(ospite or self.ospite, referente_nome="Prova Tecnico", referente_email=EMAIL_REF,
                                         motivo=motivo, invia_mail=False, **kw)

    def collega(self, v, **dati):
        return self.client.post(reverse("reception:annuncia_collega", args=["visita", v.pk]), dati)


class CollegabileTests(Base):
    def test_motivo_di_lavoro_ditta_o_gia_collegata(self):
        prima = self.visita()
        self.assertTrue(interventi.collegabile(prima))
        servizi.registra_uscita(prima.pk)
        v = self.visita(motivo="Riunione")
        self.assertFalse(interventi.collegabile(v))
        self.assertTrue(interventi.collegabile(v, collegata=True))
        v.tipo = Visita.FORNITORE
        self.assertTrue(interventi.collegabile(v))


class CollegaTests(Base):
    def test_ticket_it_del_richiedente_diventa_presenza_della_visita(self):
        v = self.visita()
        self.collega(v, intervento=f"t:{self.ticket.pk}")
        link = IngressoIntervento.objects.get(visita_gp_id=v.pk)
        self.assertEqual((link.ticket_id, link.collegato_da_id, link.azienda), (self.ticket.pk, self.user.pk, "Ditta Esempio Srl"))
        self.assertEqual(link.modo, IngressoIntervento.MODO_MANUALE)
        self.assertIn(self.ticket.numero_ticket, self.client.get(reverse("reception:annuncia")).content.decode())

    def test_per_numero_ticket_e_odl(self):
        v = self.visita()
        self.collega(v, numero=self.ticket.numero_ticket.lower())
        with patch(PUO_ODL, return_value=True):
            self.collega(v, numero=f"#{self.odl.pk}")
        self.assertEqual(IngressoIntervento.objects.filter(visita_gp_id=v.pk).count(), 2)

    def test_odl_solo_a_chi_esegue_le_manutenzioni(self):
        v = self.visita()
        with patch(PUO_ODL, return_value=False):
            self.collega(v, intervento=f"o:{self.odl.pk}")
        self.assertFalse(IngressoIntervento.objects.exists())

    def test_togli_solo_il_proprio(self):
        v = self.visita()
        self.collega(v, intervento=f"t:{self.ticket.pk}")
        link = IngressoIntervento.objects.get()
        IngressoIntervento.objects.filter(pk=link.pk).update(collegato_da=None)
        self.assertEqual(self.collega(v, azione="togli", link=link.pk).status_code, 403)
        IngressoIntervento.objects.filter(pk=link.pk).update(collegato_da=self.user)
        self.collega(v, azione="togli", link=link.pk)
        self.assertFalse(IngressoIntervento.objects.exists())

    def test_solo_il_referente(self):
        v = self.visita()
        Visita.objects.filter(pk=v.pk).update(referente_email="altro@example.local")
        self.assertEqual(self.collega(v, intervento=f"t:{self.ticket.pk}").status_code, 403)
        self.assertFalse(IngressoIntervento.objects.exists())

    def test_ticket_di_altri_non_si_collega(self):
        altrui = Ticket.objects.create(tipo="MAN", titolo="Perdita olio", descrizione="x", categoria="ALTRO_MAN", richiedente_nome="Altro")
        v = self.visita()
        self.collega(v, numero=altrui.numero_ticket)
        self.collega(v, intervento=f"t:{altrui.pk}")
        self.assertFalse(IngressoIntervento.objects.exists())

    def test_chi_ha_solo_aperto_il_ticket_non_lo_delega_alla_ditta(self):
        fornitore = Fornitore.objects.create(ragione_sociale="Ditta Esempio Srl")
        v = self.visita()
        self.collega(v, intervento=f"t:{self.ticket.pk}")
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.delegato_fornitore_id)
        self.assertEqual(IngressoIntervento.objects.get().fornitore_id, fornitore.pk)


class FiloInvitoTests(Base):
    def test_ticket_scelto_all_annuncio_si_collega_all_ingresso(self):
        domani = (timezone.localdate() + timedelta(days=1)).isoformat()
        with patch(MAIL):
            self.client.post(reverse("reception:annuncia"), {"nome": "Luca Esterno", "email": "luca@example.local",
                                                             "data_visita": domani, "motivo": "Manutenzione",
                                                             "intervento": f"t:{self.ticket.pk}"})
        pre = Preregistrazione.objects.get()
        self.assertEqual(pre.ticket_id, self.ticket.pk)
        Preregistrazione.objects.filter(pk=pre.pk).update(data_visita=timezone.localdate())
        with patch(MAIL):
            v = servizi.ingresso_da_codice(pre.codice)
        link = IngressoIntervento.objects.get(visita_gp_id=v.pk)
        self.assertEqual((link.ticket_id, link.collegato_da_id), (self.ticket.pk, self.user.pk))

    def test_motivo_non_di_lavoro_ignora_la_scelta(self):
        domani = (timezone.localdate() + timedelta(days=1)).isoformat()
        with patch(MAIL):
            self.client.post(reverse("reception:annuncia"), {"nome": "Luca Esterno", "email": "luca@example.local",
                                                             "data_visita": domani, "motivo": "Riunione",
                                                             "intervento": f"t:{self.ticket.pk}"})
        self.assertIsNone(Preregistrazione.objects.get().ticket_id)

    def test_invito_cambia_e_togli(self):
        pre = servizi.crea_preregistrazione(ospite_nome="Luca Esterno", ospite_email="luca@example.local", referente=self.ref,
                                            creata_da="tec_ref", motivo="Manutenzione", data_visita=timezone.localdate())
        url = reverse("reception:annuncia_collega", args=["invito", pre.pk])
        self.client.post(url, {"intervento": f"t:{self.ticket.pk}"})
        pre.refresh_from_db()
        self.assertEqual(pre.ticket_id, self.ticket.pk)
        self.client.post(url, {"azione": "togli"})
        pre.refresh_from_db()
        self.assertIsNone(pre.ticket_id)


class PaginaTests(Base):
    def test_le_tue_visite_attesi_presenti_passati(self):
        servizi.crea_preregistrazione(ospite_nome="Anna Attesa", ospite_email="anna@example.local", referente=self.ref,
                                      creata_da="tec_ref", motivo="Riunione", data_visita=timezone.localdate() + timedelta(days=1))
        passata = self.visita(motivo="Riunione")
        servizi.registra_uscita(passata.pk)
        altro = servizi.ospite_da_dati(nome="Piero", cognome="Presente", email="piero@example.local")
        self.visita(ospite=altro)
        pagina = self.client.get(reverse("reception:annuncia")).content.decode()
        for testo in ("Le tue visite", "Anna Attesa", "Mario Esterno", "Piero Presente", "Presente", f'value="t:{self.ticket.pk}"'):
            self.assertIn(testo, pagina)

    def test_proposte_odl_solo_a_chi_esegue(self):
        self.visita()
        self.assertNotIn(f'value="o:{self.odl.pk}"', self.client.get(reverse("reception:annuncia")).content.decode())
        with patch(PUO_ODL, return_value=True):
            self.assertIn(f'value="o:{self.odl.pk}"', self.client.get(reverse("reception:annuncia")).content.decode())

    def test_visite_di_altri_referenti_non_si_vedono(self):
        v = self.visita()
        Visita.objects.filter(pk=v.pk).update(referente_email="altro@example.local")
        self.assertNotIn("Mario Esterno", self.client.get(reverse("reception:annuncia")).content.decode())

    def test_ticket_delegato_alla_ditta_proposto_a_chi_lo_gestisce(self):
        fornitore = Fornitore.objects.create(ragione_sociale="Manutenzioni Esempio Spa")
        ditta = DittaAccreditata.objects.create(nome="Manutenzioni Esempio")
        DittaGuestPortal.objects.create(ditta_gp_id=ditta.pk, ditta_gp_nome=ditta.nome, fornitore=fornitore)
        delegato = Ticket.objects.create(tipo="MAN", titolo="Revisione compressore", descrizione="x", categoria="ALTRO_MAN",
                                         richiedente_nome="Altro", delegato_fornitore=fornitore)
        v = self.visita(ditta=ditta, tipo=Visita.FORNITORE)
        self.assertEqual(interventi.fornitore_della_visita(Visita.objects.select_related("ospite", "ditta").get(pk=v.pk)), fornitore)
        self.assertNotIn(f'value="t:{delegato.pk}"', self.client.get(reverse("reception:annuncia")).content.decode())
        with patch("tickets.views._can_manage_tickets", return_value=True):
            self.assertIn(f'value="t:{delegato.pk}"', self.client.get(reverse("reception:annuncia")).content.decode())


class PannelloTests(Base):
    def test_motivi_collegabili_da_impostazioni(self):
        admin = get_user_model().objects.create_superuser("adm_rc", "adm@example.local", "x")
        UserOnboarding.objects.get_or_create(user=admin, defaults={"completed": True})
        self.client.force_login(admin)
        riunione = CategoriaVisita.objects.get(nome="Riunione")
        self.client.post(reverse("reception:impostazioni"), {"azione": "motivi", "motivo": [str(riunione.pk)]})
        self.assertEqual(interventi.motivi_di_lavoro(), {"riunione"})

    def test_scheda_visita_mostra_il_collegamento(self):
        v = self.visita()
        self.collega(v, intervento=f"t:{self.ticket.pk}")
        admin = get_user_model().objects.create_superuser("adm_rc2", "adm2@example.local", "x")
        UserOnboarding.objects.get_or_create(user=admin, defaults={"completed": True})
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("reception:visita_scheda", args=[v.pk])), self.ticket.numero_ticket)
