"""«Cosa manca» della Panoramica: un solo elenco al posto di passi, percorso, prontezza e prossime attività."""
from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .action_register import build_project_actions
from .models import KickoffMeeting, Task, TaskStatus, VRFDocStatus
from .readiness import compute_project_readiness
from .services.cosa_manca import MAX_IN_RITARDO, cosa_manca
from .services.tappe import percorso
from .tests_filo import FiloBase
from .tests_utils import make_project


class CosaMancaTests(FiloBase):
    def setUp(self):
        super().setUp()
        self.project = make_project(name="Commessa manca", created_by=self.user, project_manager=self.user)

    def calcola(self, **kw):
        dati = {"can_manage": True, "puo_assegnare": True}
        dati.update(kw)
        return cosa_manca(
            self.project, tappe=percorso(self.project), readiness=compute_project_readiness(self.project),
            azioni=build_project_actions(self.project), **dati,
        )

    def titoli(self, **kw):
        return [r["titolo"] for r in self.calcola(**kw)["righe"]]

    def test_una_riga_per_tappa_da_assegnare_e_il_primo_incontro(self):
        dati = self.calcola()
        titoli = [r["titolo"] for r in dati["righe"]]
        self.assertIn("Pianifica il primo incontro", titoli)
        # Kickoff appena nato: nove tappe da assegnare stanno in una riga sola, ma nel totale valgono nove.
        riga = next(r for r in dati["righe"] if r["titolo"] == "9 tappe del Percorso da assegnare")
        self.assertIn("Programma CAM", riga["dettaglio"])
        self.assertEqual((riga["url"], riga["azione"], riga["tono"]), ("#percorso", "Assegna", "warn"))
        self.assertEqual(dati["totale"], len(dati["righe"]) + 8 + len(dati["a_posto"]))

    def test_poche_tappe_da_assegnare_una_riga_ciascuna(self):
        self.project.tappe_escluse = ["MATERIALI", "CMM", "ATTREZZATURA", "UTENSILI", "TERZISTA", "PROCESSI", "FAI"]
        self.project.save(update_fields=["tappe_escluse"])
        dati = self.calcola()
        titoli = [r["titolo"] for r in dati["righe"]]
        self.assertIn("Programma CAM", titoli)
        self.assertIn("Macchina", titoli)
        self.assertEqual(dati["totale"], len(dati["righe"]) + len(dati["a_posto"]))
        self.assertIn("FAI (non serve)", dati["a_posto"])

    def test_vrf_da_compilare_e_a_posto(self):
        Project = type(self.project)
        Project.objects.filter(pk=self.project.pk).update(vrf_status=VRFDocStatus.PENDING)
        self.project.refresh_from_db()
        self.assertIn("VRF da compilare", self.titoli())
        Project.objects.filter(pk=self.project.pk).update(vrf_status=VRFDocStatus.UPLOADED)
        self.project.refresh_from_db()
        dati = self.calcola()
        self.assertNotIn("VRF da compilare", [r["titolo"] for r in dati["righe"]])
        self.assertIn("VRF a posto", dati["a_posto"])

    def test_attivita_in_ritardo_con_tetto(self):
        ieri = timezone.localdate() - timedelta(days=1)
        for n in range(MAX_IN_RITARDO + 2):
            Task.objects.create(
                project=self.project, title=f"In ritardo {n}", created_by=self.user,
                status=TaskStatus.TODO, due_date=ieri,
            )
        dati = self.calcola()
        in_ritardo = [r for r in dati["righe"] if r["titolo"].startswith("In ritardo ")]
        self.assertEqual(len(in_ritardo), MAX_IN_RITARDO)
        self.assertTrue(all(r["tono"] == "danger" and r["pannello"] for r in in_ritardo))
        self.assertIn("Altre 2 attività in ritardo", [r["titolo"] for r in dati["righe"]])
        # Le urgenti stanno in testa.
        self.assertEqual(dati["righe"][0]["tono"], "danger")

    def test_chi_non_gestisce_vede_le_righe_senza_comandi(self):
        dati = self.calcola(can_manage=False, puo_assegnare=False)
        self.assertTrue(dati["righe"])
        self.assertFalse([r for r in dati["righe"] if r["url"] and r["azione"] in ("Assegna", "Compila", "Completa", "Pianifica")])

    def test_kickoff_chiuso_non_manca_niente(self):
        self.project.chiuso_il = timezone.now()
        dati = self.calcola()
        self.assertEqual(dati["righe"], [])
        self.assertTrue(dati["chiuso"])

    def test_panoramica_ha_un_solo_blocco(self):
        KickoffMeeting.objects.create(project=self.project, data=timezone.localdate(), created_by=self.user)
        pagina = self.client.get(reverse("tasks:project_overview", args=[self.project.pk]))
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, 'id="cosa-manca"')
        self.assertContains(pagina, "Conduci l")
        for vecchio in ("Prossimi passi", "Prontezza all'avvio", "Prossime attività", "Ultimi incontri"):
            self.assertNotContains(pagina, vecchio)
        # Il Percorso resta, come strumento chiuso finché non serve.
        self.assertContains(pagina, "data-ko-percorso")
        self.assertContains(pagina, 'id="percorso"')


class SuggerimentiAttivitaTests(FiloBase):
    """Il campo «cosa va fatto» propone le attività già usate, ovunque siano nate."""

    def test_un_elenco_solo_per_piano_incontro_e_tipi(self):
        from .models import CatalogoTipo, CatalogoVoce, TaskCategory
        from .services.catalogo import chiave, suggerimenti

        CatalogoVoce.objects.create(tipo=CatalogoTipo.AZIONE, testo="Sollecitare il fornitore", chiave=chiave("Sollecitare il fornitore"), usi=3)
        CatalogoVoce.objects.create(tipo=CatalogoTipo.ATTIVITA, testo="Sollecitare il fornitore", chiave=chiave("Sollecitare il fornitore"), usi=2)
        CatalogoVoce.objects.create(tipo=CatalogoTipo.ATTIVITA, testo="Collaudo primo pezzo", chiave=chiave("Collaudo primo pezzo"), usi=1)
        tipo = TaskCategory.objects.filter(is_active=True).first()
        for richiesto in (CatalogoTipo.ATTIVITA, CatalogoTipo.AZIONE):
            testi = [v.testo for v in suggerimenti(richiesto)]
            self.assertEqual(testi.count("Sollecitare il fornitore"), 1)
            self.assertIn("Collaudo primo pezzo", testi)
            self.assertEqual(testi[0], "Sollecitare il fornitore")  # usi sommati: 5
            if tipo is not None:
                self.assertIn(tipo.name, testi)

    def test_il_form_piu_attivita_ha_i_suggerimenti(self):
        from .models import CatalogoTipo, CatalogoVoce
        from .services.catalogo import chiave

        project = make_project(name="Commessa suggerimenti", created_by=self.user, project_manager=self.user)
        CatalogoVoce.objects.create(tipo=CatalogoTipo.AZIONE, testo="Verificare il calibro", chiave=chiave("Verificare il calibro"), usi=1)
        pagina = self.client.get(reverse("tasks:create"), {"project": project.pk})
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, 'list="cat-attivita"')
        self.assertContains(pagina, '<option value="Verificare il calibro">')

    def test_attrezzatura_fuori_dalle_righe_rapide_d_incontro(self):
        project = make_project(name="Commessa attrezzi", created_by=self.user, project_manager=self.user)
        m = KickoffMeeting.objects.create(project=project, data=timezone.localdate(), created_by=self.user)
        pagina = self.client.get(reverse("tasks:project_meeting_detail", args=[project.pk, m.pk]))
        self.assertEqual(pagina.status_code, 200)
        self.assertNotContains(pagina, "Nessuna azione attrezzatura")
        self.assertNotContains(pagina, "ctm-tooling-mode")
