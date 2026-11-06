"""Ingressi esterni collegati a manutenzione ordinaria, scadenza dell'asset e attività dello Scadenzario."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore
from assets.models import Asset, AssetAdministrativeDeadline, MaintenanceInterventionTemplate, MaintenanceOccurrence
from scadenzario.models import CategoriaScadenza, ScadenzaGenerica

from . import collegamenti as col
from . import guestportal as gp
from . import ingressi as ing
from .models import IngressoIntervento


def _accesso(azienda="Impianti Esempio Srl", visita=7):
    return gp.Accesso(visita, "CHECKEDOUT", "SUPPLIER", "Mario Esempio", azienda, "", "", "B1",
                      datetime(2026, 3, 1, 8), datetime(2026, 3, 1, 12))


class Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("adm_sc", "adm@example.local", "x")
        self.client.force_login(self.user)
        self.f = Fornitore.objects.create(ragione_sociale="Impianti Esempio Srl")
        self.asset = Asset.objects.create(asset_tag="T-1", name="Pressa di prova")
        self.piano = MaintenanceInterventionTemplate.objects.create(code="P1", label="Controllo annuale")
        self.oggi = timezone.localdate()
        self.occ = MaintenanceOccurrence.objects.create(plan=self.piano, asset=self.asset, due_date=self.oggi, supplier=self.f)
        self.dl = AssetAdministrativeDeadline.objects.create(asset=self.asset, title="Certificato CE", due_date=self.oggi, issuer="IMPIANTI ESEMPIO S.R.L.")
        self.cat = CategoriaScadenza.objects.create(nome="Legali")
        self.sc = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Rinnovo autorizzazione", data_scadenza=self.oggi, fornitore=self.f)

    def _collega(self, iv, accesso=None):
        with patch.object(gp, "visita", return_value=accesso or _accesso()):
            return ing.collega(iv, 7, utente=self.user, modo="MANUALE")


class CollegaTests(Base):
    def test_si_collega_a_tutte_e_tre(self):
        for tipo, oggetto, campo in (("ordinaria", self.occ, "occorrenza"), ("amministrativa", self.dl, "scadenza_asset"),
                                     ("scadenza", self.sc, "scadenza")):
            link = self._collega(ing.intervento(tipo, oggetto.pk))
            self.assertEqual(getattr(link, campo), oggetto)
            self.assertEqual(link.fornitore, self.f)
            self.assertEqual(ing.intervento_del_link(link).oggetto, oggetto)
        self.assertEqual(IngressoIntervento.objects.count(), 3)
        self.assertEqual(self.f.tecnici.count(), 1)

    def test_non_registra_la_manutenzione_e_non_rinnova(self):
        self._collega(ing.intervento("ordinaria", self.occ.pk))
        self._collega(ing.intervento("scadenza", self.sc.pk))
        self.occ.refresh_from_db()
        self.sc.refresh_from_db()
        self.assertEqual(self.occ.status, MaintenanceOccurrence.STATUS_OPEN)
        self.assertEqual(self.sc.data_scadenza, self.oggi)
        self.assertFalse(self.sc.rinnovi.exists())

    def test_stesso_ingresso_due_volte_rifiutato(self):
        iv = ing.intervento("scadenza", self.sc.pk)
        self._collega(iv)
        with self.assertRaises(ing.CollegamentoNonValido):
            self._collega(iv)

    def test_il_vincolo_vuole_una_sola_destinazione(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            IngressoIntervento.objects.create(visita_gp_id=9, occorrenza=self.occ, scadenza=self.sc)
        with self.assertRaises(IntegrityError), transaction.atomic():
            IngressoIntervento.objects.create(visita_gp_id=9)

    def test_manutenzione_eseguita_si_collega_annullata_no(self):
        self.occ.status = MaintenanceOccurrence.STATUS_DONE
        self.occ.completed_on = self.oggi
        self.occ.save()
        iv = ing.intervento("ordinaria", self.occ.pk)
        self.assertFalse(iv.chiuso)
        self.assertIn(f"/assets/{self.asset.pk}", iv.url.replace("/view/", "/"))
        self.occ.status = MaintenanceOccurrence.STATUS_CANCELED
        self.occ.save()
        self.assertTrue(ing.intervento("ordinaria", self.occ.pk).chiuso)

    def test_scadenze_sospese_non_si_collegano(self):
        self.sc.is_active = False
        self.sc.save()
        with self.assertRaises(ing.CollegamentoNonValido):
            self._collega(ing.intervento("scadenza", self.sc.pk))


class DittaTests(Base):
    def test_senza_ditta_prende_quella_dell_ingresso(self):
        self.occ.supplier = None
        self.occ.save()
        self.sc.fornitore = None
        self.sc.save()
        self.dl.issuer = ""
        self.dl.save()
        for tipo, pk in (("ordinaria", self.occ.pk), ("scadenza", self.sc.pk), ("amministrativa", self.dl.pk)):
            self.assertTrue(self._collega(ing.intervento(tipo, pk)).nota_ditta)
        self.occ.refresh_from_db()
        self.sc.refresh_from_db()
        self.dl.refresh_from_db()
        self.assertEqual((self.occ.supplier, self.sc.fornitore, self.dl.issuer), (self.f, self.f, self.f.ragione_sociale))

    def test_l_ente_scritto_a_mano_non_si_sovrascrive(self):
        self.dl.issuer = "Ente Notificato Prova"
        self.dl.save()
        iv = ing.intervento("amministrativa", self.dl.pk)
        self.assertIsNone(iv.fornitore)
        self.assertFalse(iv.puo_prendere_ditta)
        link = self._collega(iv)
        self.assertEqual(link.nota_ditta, "")
        self.dl.refresh_from_db()
        self.assertEqual(self.dl.issuer, "Ente Notificato Prova")

    def test_la_ditta_gia_presente_non_cambia(self):
        altra = Fornitore.objects.create(ragione_sociale="Altra Srl")
        self.occ.supplier = altra
        self.occ.save()
        self._collega(ing.intervento("ordinaria", self.occ.pk))
        self.occ.refresh_from_db()
        self.assertEqual(self.occ.supplier, altra)


class PagineTests(Base):
    def _pagina_collega(self, q=""):
        with patch.object(gp, "visita", return_value=_accesso()):
            return self.client.get(reverse("fornitori:ingresso_collega", args=[7]), {"q": q} if q else {})

    def test_elenco_con_tutti_i_tipi_e_la_ditta_prima(self):
        r = self._pagina_collega()
        tipi = {iv.tipo for iv in r.context["righe"]}
        self.assertLessEqual({"ordinaria", "amministrativa", "scadenza"}, tipi)
        self.assertContains(r, "Controllo annuale")
        self.assertContains(r, "Certificato CE")
        self.assertContains(r, "Rinnovo autorizzazione")

    def test_lontane_e_di_altri_si_trovano_solo_cercando(self):
        lontana = self.oggi + timedelta(days=900)
        altra = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Lontanissima", data_scadenza=lontana)
        self.assertNotIn(altra.pk, [iv.pk for iv in self._pagina_collega().context["righe"] if iv.tipo == "scadenza"])
        self.assertContains(self._pagina_collega("Lontanissima"), "Lontanissima")

    def test_collega_dalla_pagina_e_compare_in_accessi_esterni(self):
        with patch.object(gp, "visita", return_value=_accesso()):
            self.client.post(reverse("fornitori:ingresso_collega", args=[7]), {"tipo": "ordinaria", "pk": self.occ.pk})
        self.assertEqual(IngressoIntervento.objects.get().occorrenza, self.occ)
        voce = ing.interventi_per_visite([7])[7][0]
        self.assertEqual(voce[0], "Manutenzione: Controllo annuale")

    def test_riquadri_nelle_tre_pagine(self):
        with patch.object(gp, "db_configurato", return_value=False):
            for tipo, pk in (("ordinaria", self.occ.pk), ("amministrativa", self.dl.pk), ("scadenza", self.sc.pk)):
                r = self.client.get(reverse("fornitori:presenze_intervento", args=[tipo, pk]))
                self.assertEqual(r.status_code, 200, tipo)
                self.assertContains(r, "Presenze in azienda della ditta")
        hx = "fornitori/presenze/"
        self.assertContains(self.client.get(reverse("assets:occurrence_complete", args=[self.occ.pk])), hx)
        self.assertContains(self.client.get(reverse("assets:asset_administrative_deadline_edit", args=[self.dl.pk])), hx)
        self.assertContains(self.client.get(reverse("scadenzario:scadenza_dettaglio", args=[self.sc.pk])), hx)

    def test_manutenzione_interna_senza_riquadro(self):
        self.occ.supplier = None
        self.occ.save()
        r = self.client.get(reverse("assets:occurrence_complete", args=[self.occ.pk]))
        if not self.occ.is_external:
            self.assertNotContains(r, "fornitori/presenze/")

    def test_permesso_negato_sulla_scadenza(self):
        with patch("scadenzario.permessi.puo_gestire_categoria", return_value=False), \
                patch.object(gp, "visita", return_value=_accesso()):
            r = self.client.post(reverse("fornitori:presenze_collega", args=["scadenza", self.sc.pk]), {"visita_id": 7})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(IngressoIntervento.objects.exists())

    def test_permesso_negato_sulla_manutenzione(self):
        with patch("assets.views_maintenance.can_execute_maintenance", return_value=False), \
                patch.object(gp, "visita", return_value=_accesso()):
            r = self.client.post(reverse("fornitori:presenze_collega", args=["ordinaria", self.occ.pk]), {"visita_id": 7})
        self.assertEqual(r.status_code, 403)

    def test_tipo_sconosciuto_404(self):
        self.assertEqual(self.client.get(reverse("fornitori:presenze_intervento", args=["boh", 1])).status_code, 404)


class SchedaFornitoreTests(Base):
    def _sezione(self, nome):
        return self.client.get(reverse("fornitori:fornitore_sezione", args=[self.f.pk, nome]))

    def test_scadenze_mostra_manutenzioni_ed_ente_con_gli_ingressi(self):
        self._collega(ing.intervento("ordinaria", self.occ.pk))
        with patch.object(gp, "db_configurato", return_value=False):
            r = self._sezione("scadenze")
        self.assertContains(r, "Controllo annuale")
        self.assertContains(r, "Certificato CE")
        voce = next(v for v in r.context["voci"] if v["tipo"] == "Manutenzione")
        self.assertEqual(voce["ingressi"], 1)
        self.assertContains(r, "Ingressi collegati")

    def test_attivita_senza_data_non_rompe_la_scheda(self):
        ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Senza data", fornitore=self.f)
        r = self._sezione("scadenze")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Senza data")

    def test_manutenzione_mostra_le_ordinarie_aperte(self):
        ritardo = MaintenanceOccurrence.objects.create(plan=self.piano, asset=self.asset, due_date=self.oggi - timedelta(days=5), supplier=self.f)
        r = self._sezione("manutenzione")
        self.assertEqual(r.context["n_ordinarie"], 2)
        self.assertEqual(r.context["n_ordinarie_ritardo"], 1)
        self.assertEqual(r.context["ordinarie"][0], ritardo)
        self.assertContains(r, "Manutenzioni ordinarie affidate alla ditta")

    def test_eseguite_non_compaiono_tra_le_aperte(self):
        self.occ.status = MaintenanceOccurrence.STATUS_DONE
        self.occ.save()
        self.assertEqual(self._sezione("manutenzione").context["n_ordinarie"], 0)

    def test_tecnici_mostra_l_ingresso_collegato_alla_scadenza(self):
        self._collega(ing.intervento("scadenza", self.sc.pk))
        with patch.object(gp, "db_configurato", return_value=False):
            r = self._sezione("tecnici")
        self.assertContains(r, "Rinnovo autorizzazione")
        self.assertEqual(col.collegamenti_del_fornitore(self.f).count(), 1)
