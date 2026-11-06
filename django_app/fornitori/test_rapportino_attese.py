"""Ingressi su ticket e OdL chiusi, «Usa nel rapportino», da collegare, ditte attese, riepilogo annuale."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore, FornitoreDocumento
from assets.models import Asset, AssetAdministrativeDeadline, MaintenanceInterventionTemplate, MaintenanceOccurrence, WorkOrder
from tickets.models import StatoTicket, Ticket, TipoTicket

from . import collegamenti as col
from . import guestportal as gp
from . import ingressi as ing
from . import tasks
from .models import AvvisoDittaInArrivo, IngressoIntervento, IngressoSenzaIntervento
from .requisiti import REQUISITI, ditte_attese_non_in_regola


def _accesso(visita=7, azienda="Impianti Esempio Srl", tipo="SUPPLIER", nome="Mario Esempio", uscita=True):
    entrata = datetime.now().replace(second=0, microsecond=0) - timedelta(days=1)
    return gp.Accesso(visita, "CHECKEDOUT" if uscita else "CHECKEDIN", tipo, nome, azienda, "", "", "B1",
                      entrata, entrata + timedelta(hours=4) if uscita else None)


class Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("adm_rp", "adm@example.local", "x")
        self.client.force_login(self.user)
        self.f = Fornitore.objects.create(ragione_sociale="Impianti Esempio Srl", accede_in_sede=True)
        self.asset = Asset.objects.create(asset_tag="T-1", name="Pressa di prova")
        self.oggi = timezone.localdate()
        self.piano = MaintenanceInterventionTemplate.objects.create(code="P1", label="Controllo annuale")

    def _odl(self, **kw):
        return WorkOrder.objects.create(asset=self.asset, title="Riparazione", **kw)

    def _ticket(self, **kw):
        return Ticket.objects.create(tipo=TipoTicket.MAN, titolo="Guasto", **kw)

    def _collega(self, iv, accesso=None):
        with patch.object(gp, "visita", return_value=accesso or _accesso()):
            return ing.collega(iv, 7, utente=self.user, modo="MANUALE")


class CollegaChiusiTests(Base):
    def setUp(self):
        super().setUp()
        patcher = patch("tickets.services.accesso.utente_puo_gestire_ticket", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ticket_chiuso_si_collega_senza_cambiare_ditta(self):
        t = self._ticket(stato=StatoTicket.CHIUSO, closed_at=timezone.now())
        link = self._collega(ing.intervento(ing.TIPO_TICKET, t.pk))
        self.assertEqual(link.ticket_id, t.pk)
        t.refresh_from_db()
        self.assertIsNone(t.delegato_fornitore_id)

    def test_odl_chiuso_si_collega_senza_cambiare_ditta(self):
        w = self._odl(status=WorkOrder.STATUS_DONE, closed_at=timezone.now())
        self._collega(ing.intervento(ing.TIPO_ODL, w.pk))
        w.refresh_from_db()
        self.assertIsNone(w.supplier_id)

    def test_odl_annullato_rifiuta(self):
        w = self._odl(status=WorkOrder.STATUS_CANCELED)
        with self.assertRaises(ing.CollegamentoNonValido):
            self._collega(ing.intervento(ing.TIPO_ODL, w.pk))

    def test_elenco_collega_mostra_i_chiusi_del_periodo_e_i_delegati(self):
        vicino = self._odl(status=WorkOrder.STATUS_DONE, closed_at=timezone.now())
        lontano = self._odl(status=WorkOrder.STATUS_DONE, closed_at=timezone.now() - timedelta(days=200))
        delegato = Ticket.objects.create(tipo=next(t for t in TipoTicket.values if t != TipoTicket.MAN),
                                         titolo="Delegato", delegato_fornitore=self.f)
        with patch.object(gp, "visita", return_value=_accesso()):
            risposta = self.client.get(reverse("fornitori:ingresso_collega", args=[7]))
        trovati = {(iv.tipo, iv.pk) for iv in risposta.context["righe"]}
        self.assertIn((ing.TIPO_ODL, vicino.pk), trovati)
        self.assertNotIn((ing.TIPO_ODL, lontano.pk), trovati)
        self.assertIn((ing.TIPO_TICKET, delegato.pk), trovati)

    def test_la_ricerca_trova_anche_i_chiusi_vecchi(self):
        lontano = self._odl(status=WorkOrder.STATUS_DONE, closed_at=timezone.now() - timedelta(days=200))
        with patch.object(gp, "visita", return_value=_accesso()):
            risposta = self.client.get(reverse("fornitori:ingresso_collega", args=[7]), {"q": str(lontano.pk)})
        self.assertIn((ing.TIPO_ODL, lontano.pk), {(iv.tipo, iv.pk) for iv in risposta.context["righe"]})

    def test_filtro_per_tipo_tiene_i_conteggi(self):
        self._odl()
        self._ticket()
        with patch.object(gp, "visita", return_value=_accesso()):
            risposta = self.client.get(reverse("fornitori:ingresso_collega", args=[7]), {"tipo": ing.TIPO_ODL})
        self.assertEqual({iv.tipo for iv in risposta.context["righe"]}, {ing.TIPO_ODL})
        self.assertIn(ing.TIPO_TICKET, {f["val"] for f in risposta.context["filtri_tipo"]})

    def test_straordinaria_ha_la_sua_etichetta(self):
        w = self._odl(kind=WorkOrder.KIND_CORRECTIVE)
        self.assertEqual(ing.intervento(ing.TIPO_ODL, w.pk).tipo_label, "Straordinaria")


class CollegaPiuVociTests(Base):
    def _scadenza(self, titolo):
        return AssetAdministrativeDeadline.objects.create(asset=self.asset, title=titolo, due_date=self.oggi)

    def _post(self, scelte):
        with patch.object(gp, "visita", return_value=_accesso()):
            return self.client.post(reverse("fornitori:ingresso_collega", args=[7]), {"scelta": scelte}, follow=True)

    def test_stessa_visita_su_piu_scadenze(self):
        a, b = self._scadenza("Certificato CE"), self._scadenza("Verifica messa a terra")
        risposta = self._post([f"amministrativa:{a.pk}", f"amministrativa:{b.pk}", f"amministrativa:{b.pk}"])
        self.assertEqual(IngressoIntervento.objects.filter(visita_gp_id=7, scadenza_asset__isnull=False).count(), 2)
        self.assertContains(risposta, "Ingresso collegato a 2")

    def test_la_pagina_offre_la_scelta_multipla(self):
        self._scadenza("Certificato CE")
        with patch.object(gp, "visita", return_value=_accesso()):
            risposta = self.client.get(reverse("fornitori:ingresso_collega", args=[7]), {"tipo": "amministrativa"})
        self.assertContains(risposta, 'name="scelta"')
        self.assertContains(risposta, "Collega le selezionate")

    def test_una_voce_che_non_va_non_ferma_le_altre(self):
        a = self._scadenza("Certificato CE")
        annullato = self._odl(status=WorkOrder.STATUS_CANCELED)
        risposta = self._post([f"odl:{annullato.pk}", "amministrativa:999999", f"amministrativa:{a.pk}"])
        self.assertEqual(IngressoIntervento.objects.filter(visita_gp_id=7).count(), 1)
        self.assertContains(risposta, "Non collegati")

    def test_senza_permesso_non_collega(self):
        a = self._scadenza("Certificato CE")
        from . import views

        with patch.object(views, "_puo_presenze", return_value=False):
            self._post([f"amministrativa:{a.pk}"])
        self.assertFalse(IngressoIntervento.objects.exists())


class RapportinoTests(Base):
    def test_dati_dagli_ingressi_usciti(self):
        w = self._odl()
        iv = ing.intervento(ing.TIPO_ODL, w.pk)
        self._collega(iv)
        dati = ing.dati_rapportino(iv, list(iv.collegamenti()))
        self.assertEqual(dati["minuti"], 240)
        self.assertEqual(dati["ore"], "4.00")
        self.assertEqual(dati["tecnici"], "Mario Esempio")

    def test_senza_uscita_niente_proposta(self):
        w = self._odl()
        iv = ing.intervento(ing.TIPO_ODL, w.pk)
        self._collega(iv, _accesso(uscita=False))
        self.assertIsNone(ing.dati_rapportino(iv, list(iv.collegamenti())))

    def test_chiuso_niente_proposta(self):
        w = self._odl(status=WorkOrder.STATUS_DONE, closed_at=timezone.now())
        iv = ing.intervento(ing.TIPO_ODL, w.pk)
        self._collega(iv)
        self.assertIsNone(ing.dati_rapportino(iv, list(iv.collegamenti())))

    def test_ore_odl_nel_confronto(self):
        w = self._odl(intervention_duration_minutes=600)
        iv = ing.intervento(ing.TIPO_ODL, w.pk)
        self._collega(iv)
        confronto = ing.confronto_ore(iv, list(iv.collegamenti()))
        self.assertEqual(confronto.dichiarate_minuti, 600)
        self.assertTrue(confronto.da_controllare)

    def test_riquadro_mostra_il_pulsante(self):
        w = self._odl()
        iv = ing.intervento(ing.TIPO_ODL, w.pk)
        self._collega(iv)
        with patch.object(gp, "db_configurato", return_value=False):
            risposta = self.client.get(reverse("fornitori:presenze_intervento", args=[ing.TIPO_ODL, w.pk]))
        self.assertContains(risposta, "Usa nel rapportino (4 h 00 min)")
        self.assertContains(risposta, 'data-ore="4.00"')

    def test_il_riquadro_e_nelle_pagine_di_chiusura(self):
        w = self._odl()
        risposta = self.client.get(reverse("assets:wo_close", args=[w.pk]))
        self.assertContains(risposta, reverse("fornitori:presenze_intervento", args=[ing.TIPO_ODL, w.pk]))
        occ = MaintenanceOccurrence.objects.create(plan=self.piano, asset=self.asset, due_date=self.oggi)
        risposta = self.client.get(reverse("assets:occurrence_complete", args=[occ.pk]))
        self.assertContains(risposta, reverse("fornitori:presenze_intervento", args=[ing.TIPO_ORDINARIA, occ.pk]))


class DaCollegareTests(Base):
    def _pagina(self, **get):
        righe = [_accesso(21), _accesso(22), _accesso(23), _accesso(24, azienda="", tipo="NORMAL", nome="Ospite Prova")]
        with patch.object(gp, "db_configurato", return_value=True), patch.object(gp, "presenti_ora", return_value=[]), \
                patch.object(gp, "storico", side_effect=lambda **kw: ([gp.Accesso(**vars(a)) for a in righe], False)):
            return self.client.get(reverse("fornitori:accessi_esterni"), get)

    def test_contatore_esclude_visitatori_collegati_e_non_serve(self):
        w = self._odl()
        with patch.object(gp, "visita", return_value=_accesso(21)):
            ing.collega(ing.intervento(ing.TIPO_ODL, w.pk), 21, utente=self.user, modo="MANUALE")
        IngressoSenzaIntervento.objects.create(visita_gp_id=22)
        risposta = self._pagina()
        self.assertEqual(risposta.context["n_da_collegare"], 1)
        self.assertEqual(len(risposta.context["storico"]), 4)

    def test_filtro_mostra_solo_quelli_da_collegare(self):
        IngressoSenzaIntervento.objects.create(visita_gp_id=22)
        risposta = self._pagina(da_collegare="1")
        self.assertEqual({a.visita_id for a in risposta.context["storico"]}, {21, 23})

    def test_non_serve_e_annulla(self):
        url = reverse("fornitori:ingresso_non_serve", args=[30])
        self.client.post(url, {"torna": "https://esterno.example/"})
        self.assertTrue(IngressoSenzaIntervento.objects.filter(visita_gp_id=30).exists())
        risposta = self.client.post(url, {"azione": "togli", "torna": "https://esterno.example/"})
        self.assertFalse(IngressoSenzaIntervento.objects.filter(visita_gp_id=30).exists())
        self.assertEqual(risposta.url, reverse("fornitori:accessi_esterni"))

    def test_non_serve_solo_post(self):
        self.assertEqual(self.client.get(reverse("fornitori:ingresso_non_serve", args=[30])).status_code, 405)


class DitteAtteseTests(Base):
    def _documenti(self, scadenza):
        for tipo, _e, obbligatorio in REQUISITI:
            if obbligatorio:
                FornitoreDocumento.objects.create(fornitore=self.f, tipo=tipo, nome=tipo, data_scadenza=scadenza)

    def _manutenzione(self, giorni=10):
        return MaintenanceOccurrence.objects.create(
            plan=self.piano, asset=self.asset, due_date=self.oggi + timedelta(days=giorni), supplier=self.f)

    def test_senza_documenti_e_attesa(self):
        self._manutenzione()
        ditte = ditte_attese_non_in_regola(self.oggi)
        self.assertEqual([d.fornitore_id for d in ditte], [self.f.pk])
        self.assertIn("DURC mancante", ditte[0].problemi)

    def test_documento_che_scade_prima_dell_intervento_conta_e_lo_dice_bene(self):
        self._documenti(self.oggi + timedelta(days=5))
        self._manutenzione(10)
        ditte = ditte_attese_non_in_regola(self.oggi)
        self.assertEqual(len(ditte), 1)
        self.assertIn("scade il", ditte[0].problemi)
        self.assertNotIn("scaduto", ditte[0].problemi)

    def test_in_regola_o_troppo_lontana_non_conta(self):
        self._documenti(self.oggi + timedelta(days=200))
        self._manutenzione(10)
        self.assertEqual(ditte_attese_non_in_regola(self.oggi), [])
        FornitoreDocumento.objects.filter(fornitore=self.f).delete()
        MaintenanceOccurrence.objects.all().update(due_date=self.oggi + timedelta(days=60))
        self.assertEqual(ditte_attese_non_in_regola(self.oggi), [])

    def test_non_lavora_in_sede_non_conta(self):
        self.f.accede_in_sede = False
        self.f.save()
        self._manutenzione()
        self.assertEqual(ditte_attese_non_in_regola(self.oggi), [])

    def test_manutenzione_nel_suo_odl_conta_una_volta(self):
        w = self._odl(supplier=self.f)
        occ = self._manutenzione()
        occ.work_order = w
        occ.save()
        self.assertEqual(ditte_attese_non_in_regola(self.oggi)[0].n_interventi, 1)

    def test_avviso_una_volta_poi_dopo_14_giorni_o_se_cambia(self):
        self._manutenzione()
        with patch.object(tasks, "_destinatari", return_value=[5]), patch("core.notifiche.invia_notifica") as invia:
            self.assertEqual(tasks.avvisa_ditte_attese(self.oggi)["avvisate"], 1)
            self.assertEqual(tasks.avvisa_ditte_attese(self.oggi)["avvisate"], 0)
            self.assertEqual(tasks.avvisa_ditte_attese(self.oggi + timedelta(days=14))["avvisate"], 1)
            FornitoreDocumento.objects.create(fornitore=self.f, tipo="DURC", nome="DURC", data_scadenza=self.oggi + timedelta(days=300))
            self.assertEqual(tasks.avvisa_ditte_attese(self.oggi + timedelta(days=15))["avvisate"], 1)
        self.assertEqual(invia.call_count, 3)

    def test_ditta_a_posto_perde_il_ricordo_dell_avviso(self):
        occ = self._manutenzione()
        with patch.object(tasks, "_destinatari", return_value=[5]), patch("core.notifiche.invia_notifica"):
            tasks.avvisa_ditte_attese(self.oggi)
            occ.status = MaintenanceOccurrence.STATUS_DONE
            occ.save()
            tasks.avvisa_ditte_attese(self.oggi)
        self.assertFalse(AvvisoDittaInArrivo.objects.exists())

    def test_senza_destinatari_non_segna_fatto(self):
        self._manutenzione()
        with patch.object(tasks, "_destinatari", return_value=[]):
            self.assertEqual(tasks.avvisa_ditte_attese(self.oggi)["avvisate"], 0)
        self.assertFalse(AvvisoDittaInArrivo.objects.exists())

    def test_pagina_iniziale_mostra_la_ditta(self):
        self._manutenzione()
        self.assertContains(self.client.get(reverse("fornitori:index")), "Ditte attese con i documenti non in regola")


class RiepilogoTests(Base):
    def _richiesta(self):
        return self.client.get(reverse("fornitori:index")).wsgi_request

    def test_numeri_dell_anno(self):
        adesso = timezone.now()
        self._odl(supplier=self.f, status=WorkOrder.STATUS_DONE, closed_at=adesso, cost_eur=100)
        self._odl(supplier=self.f, status=WorkOrder.STATUS_DONE, closed_at=adesso - timedelta(days=800), cost_eur=70)
        self._odl(supplier=self.f)
        MaintenanceOccurrence.objects.create(plan=self.piano, asset=self.asset, supplier=self.f, due_date=self.oggi - timedelta(days=3),
                                             completed_on=self.oggi, status=MaintenanceOccurrence.STATUS_DONE)
        with patch.object(gp, "db_configurato", return_value=False):
            dati = col.dati_riepilogo(self._richiesta(), self.f, oggi=self.oggi)
        self.assertEqual(dati["manutenzione"]["odl_chiusi"], 1)
        self.assertEqual(dati["manutenzione"]["odl_aperti"], 1)
        self.assertEqual(dati["manutenzione"]["costo"], 100)
        self.assertEqual(dati["manutenzione"]["ordinarie_in_ritardo"], 1)

    def test_ingresso_su_due_interventi_vale_una_volta(self):
        w1, w2 = self._odl(), self._odl()
        self._collega(ing.intervento(ing.TIPO_ODL, w1.pk))
        self._collega(ing.intervento(ing.TIPO_ODL, w2.pk))
        IngressoIntervento.objects.update(fornitore=self.f)
        with patch.object(gp, "db_configurato", return_value=False):
            dati = col.dati_riepilogo(self._richiesta(), self.f, oggi=self.oggi)
        self.assertEqual(dati["presenze"]["collegati"], 1)
        self.assertEqual(dati["presenze"]["ore_label"], "4 h 00 min")

    def test_anno_non_valido_torna_al_corrente(self):
        with patch.object(gp, "db_configurato", return_value=False):
            risposta = self.client.get(reverse("fornitori:fornitore_sezione", args=[self.f.pk, "riepilogo"]), {"anno": "1900"})
        self.assertEqual(risposta.context["anno"], self.oggi.year)
        self.assertNotContains(risposta, "export")

    def test_guestportal_giu_il_riepilogo_si_apre(self):
        with patch.object(gp, "db_configurato", return_value=True), \
                patch.object(gp, "ingressi_ditta", side_effect=gp.GuestPortalNonRaggiungibile("giu")):
            risposta = self.client.get(reverse("fornitori:fornitore_sezione", args=[self.f.pk, "riepilogo"]))
        self.assertEqual(risposta.status_code, 200)
        self.assertIsNone(risposta.context["presenze"]["totali"])
