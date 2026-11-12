"""Registro dei tecnici del fornitore: registrazione automatica e a mano, permessi, scadenze."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore
from assets.models import Asset, WorkOrder

from . import collegamenti as col
from . import guestportal as gp
from . import ingressi as ing
from . import tasks, tecnici
from .models import IngressoIntervento, TecnicoFornitore


def _accesso(nome="Mario Esempio", azienda="Tecnici Esempio Srl", visita=1):
    return gp.Accesso(visita, "CHECKEDIN", "SUPPLIER", nome, azienda, "", "", "", datetime(2026, 3, 1, 8), None)


class RegistroTests(TestCase):
    def setUp(self):
        self.f = Fornitore.objects.create(ragione_sociale="Tecnici Esempio Srl")

    def test_stessa_persona_non_si_duplica(self):
        _t, creato = tecnici.registra(self.f.pk, "Mario Esempio", origine="MANUALE")
        self.assertTrue(creato)
        _t, creato = tecnici.registra(self.f.pk, "ESEMPIO mario", origine="GUESTPORTAL")
        self.assertFalse(creato)
        self.assertEqual(self.f.tecnici.count(), 1)

    def test_stessa_persona_su_due_fornitori(self):
        altro = Fornitore.objects.create(ragione_sociale="Altra Srl")
        tecnici.registra(self.f.pk, "Mario Esempio", origine="MANUALE")
        self.assertTrue(tecnici.registra(altro.pk, "Mario Esempio", origine="MANUALE")[1])

    def test_anonimizzati_non_si_registrano(self):
        self.assertEqual(tecnici.registra(self.f.pk, "Ospite anonimizzato", origine="GUESTPORTAL"), (None, False))
        self.assertEqual(tecnici.registra(self.f.pk, "—", origine="GUESTPORTAL"), (None, False))

    def test_task_registra_chi_entra_per_una_ditta_riconosciuta(self):
        presenti = [_accesso(), _accesso(nome="Sconosciuto Tizio", azienda="Non in anagrafica", visita=2)]
        with patch.object(gp, "db_configurato", return_value=True), patch.object(gp, "presenti_ora", return_value=presenti):
            esito = tasks.avvisa_ingressi_non_in_regola()
        self.assertEqual(esito["tecnici_registrati"], 1)
        t = self.f.tecnici.get()
        self.assertEqual((t.nome, t.origine), ("Mario Esempio", TecnicoFornitore.ORIGINE_GUESTPORTAL))
        self.assertEqual(TecnicoFornitore.objects.count(), 1)

    def test_chi_e_stato_disattivato_resta_disattivato_se_rientra(self):
        t, _ = tecnici.registra(self.f.pk, "Mario Esempio", origine="MANUALE")
        t.attivo = False
        t.save()
        with patch.object(gp, "db_configurato", return_value=True), patch.object(gp, "presenti_ora", return_value=[_accesso()]):
            esito = tasks.avvisa_ingressi_non_in_regola()
        self.assertEqual(esito["tecnici_registrati"], 0)
        t.refresh_from_db()
        self.assertFalse(t.attivo)

    def test_errore_del_registro_non_ferma_gli_avvisi(self):
        with patch.object(gp, "db_configurato", return_value=True), \
                patch.object(gp, "presenti_ora", return_value=[_accesso()]), \
                patch.object(tecnici, "registra_da_accessi", side_effect=RuntimeError("giù")):
            esito = tasks.avvisa_ingressi_non_in_regola()
        self.assertEqual(esito["presenti"], 1)
        self.assertNotIn("tecnici_registrati", esito)

    def test_collegare_un_ingresso_registra_il_tecnico(self):
        odl = WorkOrder.objects.create(
            asset=Asset.objects.create(name="Pressa", asset_tag="TEC-1"), supplier=self.f, title="Riparazione",
        )
        iv = ing.intervento(ing.TIPO_ODL, odl.pk)
        with patch.object(gp, "visita", return_value=_accesso()), patch.object(gp, "ditte_guestportal", return_value=[]):
            ing.collega(iv, 1, utente=None, modo=IngressoIntervento.MODO_MANUALE)
        self.assertEqual(self.f.tecnici.get().origine, TecnicoFornitore.ORIGINE_INTERVENTO)


class SchedaTecniciTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin_tec", "admin@example.local", "x")
        self.client.force_login(self.user)
        self.f = Fornitore.objects.create(ragione_sociale="Tecnici Esempio Srl")
        self.sezione = reverse("fornitori:fornitore_sezione", args=[self.f.pk, "tecnici"])

    def test_aggiunta_a_mano(self):
        r = self.client.post(reverse("fornitori:tecnico_add", args=[self.f.pk]),
                             {"nome": "Mario Esempio", "qualifica": "Elettricista", "telefono": "000"})
        self.assertIn("#tab-tecnici", r["Location"])
        t = self.f.tecnici.get()
        self.assertEqual((t.qualifica, t.origine, t.creato_da), ("Elettricista", "MANUALE", self.user))
        self.assertContains(self.client.get(self.sezione), "Elettricista")

    def test_doppione_a_mano_non_salva(self):
        tecnici.registra(self.f.pk, "Mario Esempio", origine="GUESTPORTAL")
        self.client.post(reverse("fornitori:tecnico_add", args=[self.f.pk]), {"nome": "ESEMPIO Mario"})
        self.assertEqual(self.f.tecnici.count(), 1)

    def test_modifica_rinomina_e_data(self):
        t, _ = tecnici.registra(self.f.pk, "Mario Esempio", origine="GUESTPORTAL")
        url = reverse("fornitori:tecnico_edit", args=[self.f.pk, t.pk])
        self.assertContains(self.client.get(url), "Mario Esempio")
        r = self.client.post(url, {"nome": "Mario Rossi Esempio", "attestati_fino_al": "2030-01-31", "attivo": "on"})
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db()
        self.assertEqual(t.chiave, "esempio mario rossi")
        self.assertEqual(t.attestati_fino_al.isoformat(), "2030-01-31")
        # La data salvata torna nel campo: un input date vuole il formato ISO.
        self.assertContains(self.client.get(url), 'value="2030-01-31"')

    def test_tecnico_di_altro_fornitore_404(self):
        altro = Fornitore.objects.create(ragione_sociale="Altra Srl")
        t, _ = tecnici.registra(altro.pk, "Mario Esempio", origine="MANUALE")
        self.assertEqual(self.client.get(reverse("fornitori:tecnico_edit", args=[self.f.pk, t.pk])).status_code, 404)

    def test_eliminazione(self):
        t, _ = tecnici.registra(self.f.pk, "Mario Esempio", origine="MANUALE")
        self.client.post(reverse("fornitori:tecnico_stato", args=[self.f.pk, t.pk]), {"azione": "elimina"})
        self.assertFalse(self.f.tecnici.exists())

    def test_senza_permesso_di_modifica(self):
        t, _ = tecnici.registra(self.f.pk, "Mario Esempio", origine="MANUALE")
        with patch("fornitori.collegamenti.apre", return_value=False):
            for url, dati in (
                (reverse("fornitori:tecnico_add", args=[self.f.pk]), {"nome": "Altro Nome"}),
                (reverse("fornitori:tecnico_stato", args=[self.f.pk, t.pk]), {"azione": "elimina"}),
                (reverse("fornitori:tecnico_registra", args=[self.f.pk]), {"nome": "Altro Nome"}),
                (reverse("fornitori:tecnico_edit", args=[self.f.pk, t.pk]), {"nome": "Altro Nome"}),
            ):
                self.assertEqual(self.client.post(url, dati).status_code, 403, url)
        self.assertEqual(self.f.tecnici.get().nome, "Mario Esempio")

    def test_senza_accessi_esterni_si_vede_il_registro_ma_non_gli_ingressi(self):
        tecnici.registra(self.f.pk, "Mario Esempio", origine="MANUALE")
        with patch("fornitori.collegamenti.apre", return_value=False), \
                patch.object(gp, "db_configurato", return_value=True), \
                patch.object(gp, "tecnici_ditta") as lettura:
            r = self.client.get(self.sezione)
        self.assertEqual(r.status_code, 200)
        lettura.assert_not_called()
        self.assertContains(r, "Mario Esempio")
        self.assertNotContains(r, "Ore in azienda")
        self.assertNotContains(r, "+ Nuovo tecnico")

    def test_registra_chi_e_entrato_uno_e_tutti(self):
        righe = [
            gp.TecnicoDitta("Mario Esempio", 3, 90, None, datetime(2026, 3, 1, 8), False),
            gp.TecnicoDitta("Luisa Prova", 1, 10, None, datetime(2026, 2, 1, 8), True),
            gp.TecnicoDitta("Paolo Terzo", 1, 10, None, datetime(2026, 1, 1, 8), False),
        ]
        with patch.object(gp, "db_configurato", return_value=True), \
                patch.object(gp, "ditte_guestportal", return_value=[]), \
                patch.object(gp, "tecnici_ditta", return_value=(righe, False)), \
                patch.object(gp, "ingressi_ditta", return_value=[]):
            dati = col.dati_tecnici(self.f)
            self.assertEqual(len(dati["da_registrare"]), 3)
            self.client.post(reverse("fornitori:tecnico_registra", args=[self.f.pk]), {"nome": "Mario Esempio"})
            dati = col.dati_tecnici(self.f)
            self.assertEqual([t.nome for t in dati["tecnici"]], ["Mario Esempio"])
            self.assertEqual(dati["tecnici"][0].ingressi, 3)
            self.assertEqual(dati["n_dentro"], 1)
            self.client.post(reverse("fornitori:tecnico_registra", args=[self.f.pk]), {"azione": "tutti"})
        self.assertEqual(self.f.tecnici.count(), 3)
        self.assertEqual(self.f.tecnici.get(nome="Luisa Prova").origine, "GUESTPORTAL")

    def test_attestati_nelle_scadenze_e_conteggio_scheda(self):
        oggi = timezone.localdate()
        t, _ = tecnici.registra(self.f.pk, "Mario Esempio", origine="MANUALE")
        t.attestati_fino_al = oggi + timedelta(days=5)
        t.save()
        spento, _ = tecnici.registra(self.f.pk, "Spento Prova", origine="MANUALE")
        spento.attivo = False
        spento.attestati_fino_al = oggi
        spento.save()
        r = self.client.get(reverse("fornitori:fornitore_sezione", args=[self.f.pk, "scadenze"]))
        self.assertEqual([v["cosa"] for v in r.context["voci"]], ["Mario Esempio"])
        self.assertEqual(r.context["n_in_scadenza"], 1)
        self.assertContains(self.client.get(reverse("fornitori:fornitore_detail", args=[self.f.pk])), "Tecnici (1)")

    def test_ricerca_in_elenco_per_tecnico_senza_doppioni(self):
        tecnici.registra(self.f.pk, "Mario Esempio", origine="MANUALE")
        tecnici.registra(self.f.pk, "Mario Secondo", origine="MANUALE")
        r = self.client.get(reverse("fornitori:fornitori_list"), {"q": "Mario", "attivi": "1"})
        self.assertEqual([x.pk for x in r.context["page_obj"]], [self.f.pk])
