"""KICK-OFF, sincronia (24/11/2026): ordine del giorno legato alle attività, più macchine come
operazioni, fasi del programma a passi, chiuse sempre nell'elenco, «Conduci incontro»."""
from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .models import MeetingAgendaItem, ProjectTechRef, TaskExtraRef, TaskStatus, TechRefKind
from .services import collegamenti as svc
from .services import programmi_fasi
from .services.filo_incontro import punti_con_filo
from .services.testata import _primaria_incontro
from .tests_collegamenti import CollegamentiBase


class OperazioniMacchinaTests(CollegamentiBase):
    def test_ogni_macchina_nuova_e_l_operazione_successiva(self):
        uno, due = self.macchina("CNC-A1"), self.macchina("CNC-A2")
        self.post(action="collega", tipo="macchina", id=uno.pk)
        self.post(action="collega", tipo="macchina", id=due.pk)
        righe = list(
            TaskExtraRef.objects.filter(task=self.generica, field_code="macchina").order_by("id")
            .values_list("asset__asset_tag", "operazione")
        )
        self.assertEqual(righe, [("CNC-A1", 10), ("CNC-A2", 20)])

    def test_operazione_e_lavorazione_si_salvano_e_ordinano_le_macchine(self):
        uno, due = self.macchina("CNC-B1"), self.macchina("CNC-B2")
        self.post(action="collega", tipo="macchina", id=uno.pk)
        self.post(action="collega", tipo="macchina", id=due.pk)
        r = self.post(action="operazione", chiave=f"mac:{due.pk}", numero="5", lavorazione="Sgrossatura")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        voci = [v for v in svc.collegamenti(self.generica) if v["tipo"] == "macchina"]
        self.assertEqual([(v["codice"], v["operazione"], v["lavorazione"]) for v in voci],
                         [("CNC-B2", 5, "Sgrossatura"), ("CNC-B1", 10, "")])
        self.assertIn("Sgrossatura", r.json()["html"])

    def test_operazione_non_numerica_rifiutata(self):
        uno = self.macchina("CNC-C1")
        self.post(action="collega", tipo="macchina", id=uno.pk)
        r = self.post(action="operazione", chiave=f"mac:{uno.pk}", numero="dieci", lavorazione="")
        self.assertEqual(r.status_code, 400)


class ProgrammaPassiTests(CollegamentiBase):
    def test_scheda_mostra_le_fasi_a_passi_e_il_pulsante_del_passo(self):
        self.post(action="aggiungi", tipo="cam", testo="P-77 fresatura")
        ref = ProjectTechRef.objects.get(task=self.generica, kind=TechRefKind.CAM)
        r = self.client.get(reverse("tasks:detail", args=[self.generica.pk]))
        self.assertContains(r, 'class="kc-passi"')
        passo = programmi_fasi.azioni_possibili(ref)[0][0]
        self.assertContains(r, f'data-kc-passo="{passo}"')
        self.assertEqual(self.post(action="fase", chiave=f"ref:{ref.pk}", valore=passo).status_code, 200)
        r = self.client.get(reverse("tasks:detail", args=[self.generica.pk]))
        self.assertContains(r, 'class="kc-storico"')

    def test_fai_da_compilare_ha_il_pulsante(self):
        self.post(action="aggiungi", tipo="fai", testo="FAI-9")
        r = self.client.get(reverse("tasks:detail", args=[self.generica.pk]))
        self.assertContains(r, "Compila la scheda FAI")


class OrdineDelGiornoVivoTests(CollegamentiBase):
    def test_punto_scritto_a_mano_si_aggancia_all_attivita_con_lo_stesso_titolo(self):
        m = self.incontro()
        MeetingAgendaItem.objects.create(meeting=m, ordine=1, item_id="p1", titolo="preparare il lotto ")
        punti = punti_con_filo(m, m.agenda_items)
        self.assertEqual(punti[0]["vivo"]["task"].pk, self.generica.pk)
        self.assertEqual(MeetingAgendaItem.objects.get(meeting=m, item_id="p1").task_id, self.generica.pk)

    def test_attivita_completata_segna_trattato_il_punto(self):
        m = self.incontro()
        MeetingAgendaItem.objects.create(
            meeting=m, ordine=1, item_id="p1", titolo="Lotto", task=self.generica, task_label=self.generica.title,
        )
        self.generica.status = TaskStatus.DONE
        self.generica.save(update_fields=["status"])
        punti = punti_con_filo(m, m.agenda_items)
        self.assertTrue(punti[0]["done"])
        self.assertEqual(punti[0]["vivo"]["stato"], "Completata")
        self.assertTrue(MeetingAgendaItem.objects.get(meeting=m, item_id="p1").done)

    def test_fotografia_tolta_e_macchine_nel_punto(self):
        m = self.incontro()
        uno = self.macchina("CNC-D1")
        self.post(action="collega", tipo="macchina", id=uno.pk)
        MeetingAgendaItem.objects.create(
            meeting=m, ordine=1, item_id="p1", titolo="Lotto", task=self.generica,
            custom_fields=[{"label": "Stato", "value": "Da assegnare"}, {"label": "Fornitore", "value": "X"}],
        )
        punto = punti_con_filo(m, m.agenda_items)[0]
        self.assertEqual([f["label"] for f in punto["custom_fields"]], ["Fornitore"])
        self.assertEqual([v["codice"] for v in punto["vivo"]["operazioni"]], ["CNC-D1"])

    def test_voce_incontro_dice_il_numero_del_punto(self):
        m = self.incontro()
        MeetingAgendaItem.objects.create(meeting=m, ordine=1, item_id="a", titolo="Altro")
        MeetingAgendaItem.objects.create(meeting=m, ordine=2, item_id="b", titolo="Lotto", task=self.generica)
        voce = next(v for v in svc.collegamenti(self.generica) if v["tipo"] == "incontro")
        self.assertEqual(voce["punto"], 2)
        self.assertIn("punto 2 dell'ordine del giorno", voce["descrizione"])


class ElencoEConduciTests(CollegamentiBase):
    def test_le_chiuse_restano_nell_elenco_in_fondo(self):
        chiusa = self.attivita(category=None, title="Gia fatta")
        chiusa.status = TaskStatus.DONE
        chiusa.save(update_fields=["status"])
        r = self.client.get(reverse("tasks:project_actions", args=[self.project.pk]))
        self.assertContains(r, "Gia fatta")
        self.assertContains(r, "Completate e chiuse")
        self.assertNotContains(r, "Solo aperte")
        html = r.content.decode()
        self.assertLess(html.index("Preparare il lotto"), html.index("Gia fatta"))

    def test_incontro_di_ieri_ha_anche_conduci(self):
        m = self.incontro()
        m.data = timezone.localdate() - timedelta(days=1)
        primaria = _primaria_incontro(self.project, m, "", gestisce=True, puo_creare=True, oggi=timezone.localdate())
        self.assertEqual(primaria["label"], "Registra l'esito")
        self.assertEqual(primaria["secondaria"]["label"], "Conduci incontro")


class AttivitaDalPuntoTests(CollegamentiBase):
    """Dal punto dell'ordine del giorno l'attività si crea e si apre nel pannello laterale."""

    def test_form_dal_punto_propone_il_titolo_e_al_salvataggio_lega_il_punto(self):
        m = self.incontro()
        MeetingAgendaItem.objects.create(meeting=m, ordine=1, item_id="p1", titolo="Verifica grezzo")
        url = reverse("tasks:create") + f"?project={self.project.pk}&incontro={m.pk}&punto=p1"
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'value="Verifica grezzo"')
        dati = {
            "title": "Verifica grezzo", "task_scope": "project", "project_link_mode": "existing",
            "project_choice": self.project.pk, "priority": "MEDIUM", "status": "TODO",
            "next_step_due": "2026-12-01", "due_date": "2026-12-04",
        }
        self.client.post(url, dati)
        punto = MeetingAgendaItem.objects.get(meeting=m, item_id="p1")
        self.assertIsNotNone(punto.task_id)
        self.assertEqual(punto.task.title, "Verifica grezzo")

    def test_scheda_prima_ha_i_pulsanti_attivita(self):
        m = self.incontro()
        MeetingAgendaItem.objects.create(meeting=m, ordine=1, item_id="a", titolo="Senza attività xyz")
        MeetingAgendaItem.objects.create(meeting=m, ordine=2, item_id="b", titolo="Altro", task=self.generica)
        r = self.client.get(reverse("tasks:project_meeting_detail", args=[self.project.pk, m.pk]))
        self.assertContains(r, f"incontro={m.pk}&amp;punto=a")
        self.assertContains(r, f'data-preview="{reverse("tasks:detail", args=[self.generica.pk])}"')

    def test_form_convocazione_ha_i_punti_aggiornati(self):
        from .services.odg_vivo import per_form

        m = self.incontro()
        MeetingAgendaItem.objects.create(
            meeting=m, ordine=1, item_id="p1", titolo="Lotto", task=self.generica,
            custom_fields=[{"label": "Stato", "value": "Da assegnare"}],
        )
        punto = per_form(m, m.agenda_items)[0]
        self.assertNotIn("vivo", punto)
        self.assertEqual(punto["custom_fields"], [])
