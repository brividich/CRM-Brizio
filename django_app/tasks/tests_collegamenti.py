"""Riquadro «Collegamenti» dell'attività: macchina, attrezzatura, utensili, programmi, FAI, incontro (23/11/2026)."""
from __future__ import annotations

import json
from datetime import date

from django.urls import reverse

from core.models import RoutePermissionBinding

from .acl_bootstrap import bootstrap_tasks_acl_endpoints
from .models import (
    KickoffMeeting,
    MeetingStatus,
    ProjectTechRef,
    ProjectUtensile,
    Task,
    TaskCategory,
    TaskExtraRef,
    TaskStatus,
    TappaKickoff,
    Utensile,
    UtensileStato,
)
from .services import collegamenti as svc
from .tests_programmi import ProgrammiBase
from .tests_utils import _create_user_with_legacy, make_project


class CollegamentiBase(ProgrammiBase):
    def setUp(self):
        super().setUp()
        self.generica = self.attivita(category=None, title="Preparare il lotto")
        self.url = reverse("tasks:collegamenti_azione", args=[self.generica.pk])
        self.url_cerca = reverse("tasks:collegamenti_cerca", args=[self.project.pk])

    def post(self, task=None, **dati):
        url = reverse("tasks:collegamenti_azione", args=[task.pk]) if task is not None else self.url
        return self.client.post(url, dati, HTTP_ACCEPT="application/json")

    def cerca(self, tipo, q="", task=None):
        return self.client.get(self.url_cerca, {"tipo": tipo, "q": q, "task": (task or self.generica).pk}).json()

    def tipi(self, task=None):
        return [v["tipo"] for v in svc.collegamenti(task or self.generica)]

    def macchina(self, tag="CNC-K1"):
        from assets.models import Asset

        return Asset.objects.create(asset_tag=tag, name="Centro di lavoro prova", asset_type="CNC")

    def incontro(self, numero=1, stato=MeetingStatus.PIANIFICATO):
        return KickoffMeeting.objects.create(
            project=self.project, numero=numero, titolo="Avvio", data=date(2026, 12, 3), stato=stato, created_by=self.user,
        )


class UtensiliAttrezzatureTests(CollegamentiBase):
    def test_utensile_nuovo_entra_in_catalogo_e_si_ritrova_da_un_altra_attivita(self):
        risposta = self.post(action="aggiungi", tipo="utensile", testo="FR-12 Fresa a candela D12")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.assertIn("in catalogo e collegato", risposta.json()["messaggio"])
        utensile = Utensile.objects.get(codice="FR-12")
        self.assertEqual(utensile.descrizione, "Fresa a candela D12")
        riga = ProjectUtensile.objects.get(task=self.generica)
        self.assertEqual((riga.utensile, riga.project), (utensile, self.project))
        self.assertIn("FR-12", risposta.json()["html"])
        # Da un'altra attività lo stesso codice si trova in catalogo, con le commesse in cui è già servito.
        altra = self.attivita(category=None, title="Seconda")
        trovati = self.cerca("utensile", "fr-12", task=altra)
        self.assertEqual([r["codice"] for r in trovati["risultati"]], ["FR-12"])
        self.assertEqual(trovati["risultati"][0]["usi"], "in 1 commessa")
        self.assertFalse(trovati["nuovo"], "il codice esiste: non si propone di aggiungerlo")
        self.post(altra, action="collega", tipo="utensile", id=utensile.pk)
        self.assertEqual(Utensile.objects.count(), 1)
        self.assertEqual(ProjectUtensile.objects.filter(project=self.project).count(), 2)

    def test_codice_gia_in_catalogo_non_si_duplica_nemmeno_scritto_a_mano(self):
        Utensile.objects.create(codice="PT-08", descrizione="Punta D8")
        risposta = self.post(action="aggiungi", tipo="utensile", testo="pt-08 altra descrizione")
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(Utensile.objects.count(), 1)
        self.assertNotIn("in catalogo", risposta.json()["messaggio"])
        # Collegato due volte alla stessa attività resta una riga sola.
        self.post(action="aggiungi", tipo="utensile", testo="PT-08")
        self.assertEqual(ProjectUtensile.objects.filter(task=self.generica).count(), 1)

    def test_utensile_senza_stati_ne_quantita_a_video(self):
        self.post(action="aggiungi", tipo="utensile", testo="AL-12 Alesatore")
        html = self.client.get(reverse("tasks:detail", args=[self.generica.pk])).content.decode()
        self.assertIn("AL-12", html)
        for vietato in ("Da ordinare", "Disponibile a magazzino", " pz", "Richiedi nuovo attrezzo", "Richiedi verifica"):
            self.assertNotIn(vietato, html)

    def test_riga_del_vecchio_percorso_passa_all_attivita_e_tiene_i_suoi_dati(self):
        utensile = Utensile.objects.create(codice="MF-M6", descrizione="Maschio M6")
        vecchia = ProjectUtensile.objects.create(project=self.project, utensile=utensile, quantita=4, stato=UtensileStato.ORDINATO)
        self.post(action="collega", tipo="utensile", id=utensile.pk)
        vecchia.refresh_from_db()
        self.assertEqual((vecchia.task, vecchia.quantita, vecchia.stato), (self.generica, 4, UtensileStato.ORDINATO))
        self.assertEqual(ProjectUtensile.objects.count(), 1)

    def test_scollega_utensile_lo_lascia_in_catalogo(self):
        self.post(action="aggiungi", tipo="utensile", testo="FR-20 Fresa")
        riga = ProjectUtensile.objects.get(task=self.generica)
        risposta = self.post(action="scollega", chiave=f"ut:{riga.pk}")
        self.assertEqual(risposta.status_code, 200)
        self.assertFalse(ProjectUtensile.objects.exists())
        self.assertTrue(Utensile.objects.filter(codice="FR-20").exists())

    def test_attrezzatura_nuova_entra_in_catalogo_senza_richieste(self):
        from attrezzature.models import Attrezzatura, AttrezzaturaKickoffLink, AttrezzaturaTask

        risposta = self.post(action="aggiungi", tipo="attrezzatura", testo="ATR-0312 Staffaggio lato A")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        attrezzo = Attrezzatura.objects.get(codice="ATR-0312")
        self.assertEqual((attrezzo.descrizione, attrezzo.part_number), ("Staffaggio lato A", "PN-1"))
        self.assertTrue(AttrezzaturaKickoffLink.objects.filter(task=self.generica, attrezzatura=attrezzo, project=self.project).exists())
        self.assertFalse(AttrezzaturaTask.objects.exists(), "niente «richiedi» o «verifica»: è solo un codice")
        self.assertEqual(self.tipi(), ["attrezzatura"])
        # In un'altra commessa il codice si ritrova, con le commesse in cui è servito.
        altra_commessa = make_project(name="Altra", created_by=self.user, part_number="PN-2")
        altra = self.attivita(category=None, project=altra_commessa, title="Altra")
        trovati = self.client.get(
            reverse("tasks:collegamenti_cerca", args=[altra_commessa.pk]), {"tipo": "attrezzatura", "q": "atr-03", "task": altra.pk},
        ).json()
        self.assertEqual((trovati["risultati"][0]["codice"], trovati["risultati"][0]["usi"]), ("ATR-0312", "in 1 commessa"))
        self.post(altra, action="aggiungi", tipo="attrezzatura", testo="atr-0312")
        self.assertEqual(Attrezzatura.objects.count(), 1)
        # Togliere il collegamento non cancella l'attrezzatura.
        self.post(action="scollega", chiave=f"att:{attrezzo.pk}")
        self.assertFalse(AttrezzaturaKickoffLink.objects.filter(task=self.generica).exists())
        self.assertTrue(Attrezzatura.objects.filter(pk=attrezzo.pk).exists())


class MacchinaTests(CollegamentiBase):
    def test_collega_e_scollega_la_macchina(self):
        asset = self.macchina()
        trovate = self.cerca("macchina", "cnc-k")
        self.assertEqual(trovate["risultati"][0]["codice"], "CNC-K1")
        self.assertFalse(trovate["nuovo"], "le macchine arrivano dall'anagrafica: non se ne aggiungono da qui")
        risposta = self.post(action="collega", tipo="macchina", id=asset.pk)
        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.generica.refresh_from_db()
        self.assertEqual(self.generica.extra_data.get("macchina"), asset.pk)
        self.assertTrue(TaskExtraRef.objects.filter(task=self.generica, field_code="macchina", asset=asset).exists())
        # Più macchine sulla stessa attività: la seconda si aggiunge, la prima resta quella «principale».
        seconda = self.macchina("CNC-K2")
        self.post(action="collega", tipo="macchina", id=seconda.pk)
        self.post(action="collega", tipo="macchina", id=seconda.pk)
        self.assertEqual(
            list(TaskExtraRef.objects.filter(task=self.generica).order_by("id").values_list("asset_id", flat=True)),
            [asset.pk, seconda.pk], "senza doppioni",
        )
        self.assertEqual([v["codice"] for v in svc.collegamenti(self.generica)], ["CNC-K1", "CNC-K2"])
        self.post(action="scollega", chiave=f"mac:{asset.pk}")
        self.generica.refresh_from_db()
        self.assertEqual(self.generica.extra_data.get("macchina"), seconda.pk, "tolta la prima, resta l'altra")
        self.post(action="scollega", chiave=f"mac:{seconda.pk}")
        self.generica.refresh_from_db()
        self.assertNotIn("macchina", self.generica.extra_data)
        self.assertFalse(TaskExtraRef.objects.filter(task=self.generica).exists())

    def _impegna(self, asset, titolo="Fresatura staffa"):
        """Un'altra attività aperta sulla stessa macchina nello stesso periodo."""
        altra = self.attivita(category=None, title=titolo, next_step_due=date(2026, 11, 25), due_date=date(2026, 12, 4))
        TaskExtraRef.objects.create(task=altra, field_code="macchina", asset=asset)
        return altra

    def test_macchina_gia_impegnata_solo_avviso_e_collegamento_salvato(self):
        asset = self.macchina()
        altra = self._impegna(asset)
        Task.objects.filter(pk=self.generica.pk).update(next_step_due=date(2026, 11, 24), due_date=date(2026, 12, 1))
        self.assertEqual(self.cerca("macchina", "cnc-k")["risultati"][0]["stato"], "Già impegnata nel periodo")
        risposta = self.post(action="collega", tipo="macchina", id=asset.pk)
        self.assertEqual(risposta.status_code, 200, "il conflitto non blocca")
        dati = risposta.json()
        self.assertIn("collegata, ma nel periodo è già impegnata", dati["avviso"])
        self.assertIn("Fresatura staffa (25/11–04/12)", dati["avviso"])
        self.assertTrue(TaskExtraRef.objects.filter(task=self.generica, field_code="macchina", asset=asset).exists())
        # L'avviso resta sulla riga del collegamento e nel registro finché il conflitto c'è.
        self.assertIn('class="kc-avviso"', dati["html"])
        self.assertIn("Dal 24/11 al 01/12: Attività già assegnata: Fresatura staffa", dati["html"])
        registro = self.client.get(reverse("tasks:collegamenti_registro", args=[self.project.pk])).json()["html"]
        self.assertEqual(registro.count('class="kc-avviso"'), 2, "le due attività si impegnano a vicenda")
        altra.status = TaskStatus.DONE
        altra.save()
        pagina = self.client.get(reverse("tasks:detail", args=[self.generica.pk])).content.decode()
        self.assertNotIn('class="kc-avviso"', pagina)
        self.assertIn("Libera", pagina)

    def test_avviso_senza_titolo_delle_attivita_che_non_si_vedono(self):
        asset = self.macchina()
        self._impegna(asset, titolo="Titolo riservato")
        conflitti = svc.conflitti_macchina(asset, date(2026, 11, 24), date(2026, 12, 1), visibili=set())
        self.assertEqual(len(conflitti), 1)
        self.assertNotIn("riservato", conflitti[0]["titolo"])
        self.assertTrue(conflitti[0]["grave"])

    def test_aggiungi_non_vale_per_le_macchine(self):
        self.assertEqual(self.post(action="aggiungi", tipo="macchina", testo="CNC-999 nuova").status_code, 400)

    def test_il_form_non_cancella_la_macchina_collegata(self):
        asset = self.macchina()
        self.post(action="collega", tipo="macchina", id=asset.pk)
        from .views._extra_fields import _persist_task_extra_data

        self.generica.refresh_from_db()
        _persist_task_extra_data(self.generica, {})
        self.generica.refresh_from_db()
        self.assertEqual(self.generica.extra_data.get("macchina"), asset.pk)
        self.assertTrue(TaskExtraRef.objects.filter(task=self.generica, asset=asset).exists())
        # Anche su un tipo che ha il campo «macchina»: il form non lo chiede più.
        tipo = TaskCategory.objects.get(tappa=TappaKickoff.MACCHINA)
        self.generica.category = tipo
        self.generica.save()
        _persist_task_extra_data(self.generica, {})
        self.assertTrue(TaskExtraRef.objects.filter(task=self.generica, asset=asset, field_code="macchina").exists())
        campi = self.client.get(reverse("tasks:category_fields_json", args=[tipo.pk])).json()["fields"]
        self.assertNotIn("macchina", [c["code"] for c in campi])

    def test_la_macchina_passa_al_programma_dell_attivita(self):
        asset = self.macchina()
        task = self.attivita()
        self.post(task, action="aggiungi", tipo="cam", testo="O1234")
        self.post(task, action="collega", tipo="macchina", id=asset.pk)
        self.assertEqual(ProjectTechRef.objects.get(task=task).macchina, asset)


class ProgrammiFaiTests(CollegamentiBase):
    def test_programma_nuovo_riempie_la_riga_dell_attivita(self):
        task = self.attivita()
        vuota = ProjectTechRef.objects.get(task=task)
        self.assertEqual(svc.manca(task), ["cam", "macchina"], "la tappa «Programma CAM» aspetta programma e macchina")
        risposta = self.post(task, action="aggiungi", tipo="cam", testo="O1234 Fresatura lato A")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        ref = ProjectTechRef.objects.get(task=task)
        self.assertEqual((ref.pk, ref.code, ref.note, ref.fase, ref.revisione), (vuota.pk, "O1234", "Fresatura lato A", "IN_SCRITTURA", "A"))
        self.assertNotIn("cam", svc.manca(task))

    def test_programma_cmm_esistente_si_collega_a_un_attivita_qualsiasi_e_resta(self):
        libero = ProjectTechRef.objects.create(project=self.project, kind="CMM", code="M-1", path=r"\\srv\cmm\M-1")
        trovati = self.cerca("cmm", "m-1")
        self.assertEqual(trovati["risultati"][0]["id"], libero.pk)
        risposta = self.post(action="collega", tipo="cmm", id=libero.pk)
        self.assertEqual(risposta.status_code, 200, risposta.content)
        libero.refresh_from_db()
        self.assertEqual((libero.task, libero.assigned_to), (self.generica, self.user))
        self.assertEqual(ProjectTechRef.objects.filter(project=self.project).count(), 1, "nessun doppione")
        # Salvare di nuovo l'attività (tipo che non «richiede» niente) non lo sgancia.
        self.generica.title = "Preparare il lotto 2"
        self.generica.save()
        libero.refresh_from_db()
        self.assertEqual(libero.task, self.generica)

    def test_programma_di_un_altra_commessa_si_riusa_come_copia(self):
        altra = make_project(name="Vecchia", created_by=self.user, part_number="PN-9")
        vecchio = ProjectTechRef.objects.create(project=altra, kind="CAM", code="P-3105", path=r"\\srv\cam\P-3105", revisione="C")
        trovati = self.cerca("cam", "p-31")
        self.assertEqual((trovati["risultati"][0]["codice"], trovati["risultati"][0]["usi"]), ("P-3105 rev. C", "in 1 commessa"))
        self.post(action="collega", tipo="cam", id=vecchio.pk)
        vecchio.refresh_from_db()
        self.assertIsNone(vecchio.task, "il programma dell'altra commessa non si sposta")
        nuovo = ProjectTechRef.objects.get(task=self.generica)
        self.assertEqual((nuovo.project, nuovo.code, nuovo.path, nuovo.revisione, nuovo.fase), (self.project, "P-3105", r"\\srv\cam\P-3105", "C", "IN_SCRITTURA"))

    def test_programma_di_una_commessa_non_visibile_non_si_trova(self):
        from .models import Project

        nascosta = make_project(name="Nascosta", created_by=self.user, part_number="PN-X")
        segreto = ProjectTechRef.objects.create(project=nascosta, kind="CAM", code="SEGRETO-1")
        nessuna = Project.objects.none()
        trovati = svc.cerca(self.project, "cam", "segreto", task=self.generica, progetti_visibili=nessuna)
        self.assertEqual(trovati["risultati"], [])
        with self.assertRaises(svc.CollegamentoNonValido):
            svc.collega(self.generica, "cam", segreto.pk, self.user, progetti_visibili=nessuna)
        # Scritto a mano non lo copia: nasce un programma nuovo di questa commessa, senza cartella.
        voce, nuovo = svc.aggiungi(self.generica, "cam", "SEGRETO-1", self.user, progetti_visibili=nessuna)
        self.assertTrue(nuovo)
        self.assertEqual(ProjectTechRef.objects.get(task=self.generica).path, "")

    def test_piu_programmi_e_un_solo_fai_per_attivita(self):
        self.assertEqual(self.post(action="aggiungi", tipo="cam", testo="O1").status_code, 200)
        self.assertEqual(self.post(action="aggiungi", tipo="cam", testo="O2").status_code, 200)
        self.assertEqual(self.post(action="aggiungi", tipo="cmm", testo="M1").status_code, 200)
        self.assertEqual(self.tipi(), ["cam", "cam", "cmm"])
        self.post(action="aggiungi", tipo="cam", testo="o1")
        self.assertEqual(self.tipi(), ["cam", "cam", "cmm"], "lo stesso codice non si collega due volte")
        self.assertEqual(self.post(action="aggiungi", tipo="fai", testo="FAI-1").status_code, 200)
        secondo = self.post(action="aggiungi", tipo="fai", testo="FAI-2")
        self.assertEqual(secondo.status_code, 400)
        self.assertIn("uno solo per attività", secondo.json()["reason"])
        # Un'attività che «richiede» il CAM non prende un CMM, ma di CAM ne prende più d'uno.
        task = self.attivita()
        self.assertEqual(self.post(task, action="aggiungi", tipo="cmm", testo="M2").status_code, 400)
        self.post(task, action="aggiungi", tipo="cam", testo="O10")
        self.post(task, action="aggiungi", tipo="cam", testo="O11")
        self.assertEqual(
            sorted(ProjectTechRef.objects.filter(task=task).values_list("code", flat=True)), ["O10", "O11"],
            "il primo riempie la riga «da inserire», il secondo si aggiunge",
        )

    def test_attivita_chiusa_solo_quando_tutti_i_programmi_sono_validati(self):
        task = self.attivita()
        self.post(task, action="aggiungi", tipo="cam", testo="O10")
        self.post(task, action="aggiungi", tipo="cam", testo="O11")
        primo, secondo = ProjectTechRef.objects.filter(task=task).order_by("id")
        self.post(task, action="fase", chiave=f"ref:{primo.pk}", valore="valida")
        task.refresh_from_db()
        self.assertNotEqual(task.status, TaskStatus.DONE, "manca ancora il secondo")
        # Un salvataggio qualsiasi dell'attività non riapre il programma già validato.
        task.title = "Programmare fasi 10 e 20"
        task.save()
        primo.refresh_from_db()
        self.assertEqual((primo.fase, primo.status), ("VALIDATO", "DONE"))
        self.post(task, action="fase", chiave=f"ref:{secondo.pk}", valore="valida")
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DONE)
        # Nuova revisione di uno: l'attività si riapre, l'altro resta validato.
        self.post(task, action="fase", chiave=f"ref:{primo.pk}", valore="revisione")
        task.refresh_from_db()
        secondo.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(secondo.fase, "VALIDATO")
        # Tolto quello in lavorazione, restano solo programmi validati: l'attività è fatta.
        self.post(task, action="scollega", chiave=f"ref:{primo.pk}")
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DONE)

    def test_chiudere_e_riaprire_l_attivita_vale_per_tutti_i_programmi(self):
        task = self.attivita()
        self.post(task, action="aggiungi", tipo="cam", testo="O10")
        self.post(task, action="aggiungi", tipo="cam", testo="O11")
        task.refresh_from_db()
        task.status = TaskStatus.DONE
        task.save()
        self.assertEqual(set(ProjectTechRef.objects.filter(task=task).values_list("fase", flat=True)), {"VALIDATO"})
        task.status = TaskStatus.IN_PROGRESS
        task.save()
        self.assertEqual(set(ProjectTechRef.objects.filter(task=task).values_list("fase", flat=True)), {"IN_SCRITTURA"})
        task.delete()
        self.assertEqual(ProjectTechRef.objects.filter(project=self.project, task__isnull=True, code__in=["O10", "O11"]).count(), 2)

    def test_programma_gia_di_un_altra_attivita_non_si_ruba(self):
        prima = self.attivita()
        self.post(prima, action="aggiungi", tipo="cam", testo="O77")
        ref = ProjectTechRef.objects.get(task=prima)
        risposta = self.post(action="collega", tipo="cam", id=ref.pk)
        self.assertEqual(risposta.status_code, 400)
        self.assertIn("già collegato", risposta.json()["reason"])
        self.assertTrue(self.cerca("cam", "o77")["risultati"][0]["bloccato"])

    def test_togli_il_programma_lo_lascia_alla_commessa_senza_attivita(self):
        task = self.attivita()
        self.post(task, action="aggiungi", tipo="cam", testo="O55")
        ref = ProjectTechRef.objects.get(task=task)
        risposta = self.post(task, action="scollega", chiave=f"ref:{ref.pk}")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        ref.refresh_from_db()
        self.assertIsNone(ref.task)
        self.assertEqual(ref.code, "O55")
        # Il tipo richiede il CAM: torna la riga da inserire, e un nuovo salvataggio non riprende quella tolta.
        nuova = ProjectTechRef.objects.get(task=task)
        self.assertEqual((nuova.code, nuova.kind), ("", "CAM"))
        task.title = "Altro titolo"
        task.save()
        self.assertEqual(ProjectTechRef.objects.get(task=task).pk, nuova.pk)
        self.assertEqual(svc.manca(task)[0], "cam")

    def test_fase_e_codice_dal_riquadro(self):
        task = self.attivita()
        self.post(task, action="aggiungi", tipo="cam", testo="O10")
        ref = ProjectTechRef.objects.get(task=task)
        risposta = self.post(task, action="fase", chiave=f"ref:{ref.pk}", valore="da_provare")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        ref.refresh_from_db()
        self.assertEqual(ref.fase, "DA_PROVARE")
        self.assertEqual(self.post(task, action="fase", chiave=f"ref:{ref.pk}", valore="inizia").status_code, 400)
        risposta = self.post(task, action="aggiorna", chiave=f"ref:{ref.pk}", code="O10-B", path=r"\\srv\cam\O10")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        ref.refresh_from_db()
        self.assertEqual((ref.code, ref.path), ("O10-B", r"\\srv\cam\O10"))
        # Validato chiude l'attività, come sempre.
        self.post(task, action="fase", chiave=f"ref:{ref.pk}", valore="valida")
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DONE)

    def test_fai_si_apre_per_la_commessa_senza_catalogo(self):
        altra = make_project(name="Vecchia", created_by=self.user, part_number="PN-9")
        ProjectTechRef.objects.create(project=altra, kind="FAI", code="FAI-2026-041")
        self.assertEqual(self.cerca("fai", "fai-2026")["risultati"], [], "il FAI di un'altra commessa non si riusa")
        risposta = self.post(action="aggiungi", tipo="fai", testo="FAI-2026-052")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.assertIn("aperto", risposta.json()["messaggio"])
        ref = ProjectTechRef.objects.get(task=self.generica)
        self.assertEqual((ref.kind, ref.code, ref.project), ("FAI", "FAI-2026-052", self.project))

    def test_fai_senza_attivita_si_collega(self):
        orfano = ProjectTechRef.objects.create(project=self.project, kind="FAI", code="FAI-1")
        self.assertEqual(self.cerca("fai")["risultati"][0]["id"], orfano.pk)
        self.post(action="collega", tipo="fai", id=orfano.pk)
        orfano.refresh_from_db()
        self.assertEqual(orfano.task, self.generica)


class IncontroTests(CollegamentiBase):
    def test_porta_all_ordine_del_giorno_senza_doppioni(self):
        incontro = self.incontro()
        self.incontro(2, MeetingStatus.SVOLTO)
        trovati = self.cerca("incontro")
        self.assertEqual([r["id"] for r in trovati["risultati"]], [incontro.pk], "solo gli incontri pianificati")
        risposta = self.post(action="collega", tipo="incontro", id=incontro.pk)
        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.assertIn("ordine del giorno", risposta.json()["messaggio"])
        self.post(action="collega", tipo="incontro", id=incontro.pk)
        incontro.refresh_from_db()
        punti = [p for p in incontro.agenda_items if p.get("task_id") == self.generica.pk]
        self.assertEqual(len(punti), 1)
        punto = punti[0]
        self.assertEqual((punto["titolo"], punto["responsabile_id"]), ("Preparare il lotto", self.user.pk))
        self.assertIsNone(punto["durata_minuti"], "nessun tempo per punto")
        # Nella scheda dell'attività si vede e ci si arriva con un clic.
        html = self.client.get(reverse("tasks:detail", args=[self.generica.pk])).content.decode()
        self.assertIn(f"{reverse('tasks:project_meeting_detail', args=[self.project.pk, incontro.pk])}#agenda-item-{punto['id']}", html)
        self.assertNotIn(incontro.pk, [r["id"] for r in self.cerca("incontro")["risultati"]])
        # E nella scheda dell'incontro c'è il punto.
        scheda = self.client.get(reverse("tasks:project_meeting_detail", args=[self.project.pk, incontro.pk])).content.decode()
        self.assertIn("Preparare il lotto", scheda)

    def test_incontro_svolto_non_accetta_punti_e_si_toglie_solo_da_pianificato(self):
        svolto = self.incontro(2, MeetingStatus.SVOLTO)
        self.assertEqual(self.post(action="collega", tipo="incontro", id=svolto.pk).status_code, 400)
        incontro = self.incontro()
        self.post(action="collega", tipo="incontro", id=incontro.pk)
        risposta = self.post(action="scollega", chiave=f"odg:{incontro.pk}")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        incontro.refresh_from_db()
        self.assertEqual(incontro.agenda_items, [])

    def test_incontro_di_un_altra_commessa_rifiutato(self):
        altra = make_project(name="Altra", created_by=self.user, part_number="PN-2")
        fuori = KickoffMeeting.objects.create(project=altra, numero=1, data=date(2026, 12, 3), created_by=self.user)
        self.assertEqual(self.post(action="collega", tipo="incontro", id=fuori.pk).status_code, 400)


class PermessiTests(CollegamentiBase):
    def setUp(self):
        super().setUp()
        self.lettore = _create_user_with_legacy(username="col-lettore", legacy_user_id=692, role_id=2, role_name="tasks")

    def test_json_401_senza_login(self):
        self.client.logout()
        for risposta in (self.post(action="aggiungi", tipo="utensile", testo="FR-1"), self.client.get(self.url_cerca, {"tipo": "utensile"}, HTTP_ACCEPT="application/json")):
            self.assertEqual(risposta.status_code, 401)
            self.assertEqual(risposta["Content-Type"], "application/json")

    def test_chi_non_gestisce_non_collega_e_non_vede_comandi(self):
        self.post(action="aggiungi", tipo="utensile", testo="FR-1 Fresa")
        self.project.add_team_member("programmers", self.lettore)
        self.generica.assigned_to = None
        self.generica.save()
        self.client.force_login(self.lettore)
        scheda = self.client.get(reverse("tasks:detail", args=[self.generica.pk]))
        if scheda.status_code == 200:
            html = scheda.content.decode()
            self.assertIn("FR-1", html)
            # Il team collega le risorse (come prima gli utensili), ma non programmi né incontri.
            self.assertIn('data-kc-tipo="utensile"', html)
            self.assertNotIn('data-kc-tipo="cam"', html)
            self.assertNotIn('data-kc-tipo="incontro"', html)
        risposta = self.post(action="aggiungi", tipo="cam", testo="O1")
        self.assertIn(risposta.status_code, (403, 404))
        self.assertFalse(ProjectTechRef.objects.filter(task=self.generica).exists())
        incontro = self.incontro()
        self.assertIn(self.post(action="collega", tipo="incontro", id=incontro.pk).status_code, (403, 404))
        incontro.refresh_from_db()
        self.assertEqual(incontro.agenda_items, [])

    def test_estraneo_alla_commessa_non_fa_niente(self):
        self.client.force_login(self.lettore)
        risposta = self.post(action="aggiungi", tipo="utensile", testo="FR-9")
        self.assertIn(risposta.status_code, (403, 404))
        self.assertFalse(ProjectUtensile.objects.exists())
        self.assertEqual(risposta["Content-Type"], "application/json") if risposta.status_code == 403 else None

    def test_url_registrati_in_acl(self):
        bootstrap_tasks_acl_endpoints(force=True)
        for nome in ("tasks:collegamenti_azione", "tasks:collegamenti_cerca"):
            self.assertTrue(RoutePermissionBinding.objects.filter(route_name=nome).exists(), nome)

    def test_azione_solo_post_e_cerca_solo_get(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(self.url_cerca, {"tipo": "utensile"}).status_code, 405)


class SchedaFormTests(CollegamentiBase):
    def test_scheda_un_solo_riquadro(self):
        task = self.attivita()
        html = self.client.get(reverse("tasks:detail", args=[task.pk])).content.decode()
        self.assertEqual(html.count('id="collegamenti"'), 1)
        self.assertEqual(html.count("data-kc "), 1)
        self.assertNotIn('id="programma-attivita"', html)
        self.assertNotIn("td-attrezzatura", html)
        # Il tipo «Programmazione CAM» aspetta il programma: chip evidenziato e stato che lo dice.
        self.assertIn("Manca: programma CAM", html)
        self.assertRegex(html, r'class="kc-chip is-serve" data-kc-tipo="cam"')
        for tipo in svc.TIPI:
            self.assertIn(f'data-kc-tipo="{tipo}"', html)

    def test_form_senza_modi_attrezzatura_e_con_il_riquadro(self):
        html = self.client.get(reverse("tasks:edit", args=[self.generica.pk])).content.decode()
        for vietato in ("tooling_mode", "Richiedi nuovo attrezzo", "Richiedi verifica disponibilita"):
            self.assertNotIn(vietato, html)
        self.assertEqual(html.count("data-kc "), 1)
        self.assertNotIn('name="collegamenti_json"', html, "su un'attività che esiste i collegamenti si salvano subito")

    def test_nuova_attivita_applica_i_collegamenti_scelti(self):
        from datetime import timedelta

        from django.utils import timezone

        asset = self.macchina()
        incontro = self.incontro()
        url = f"{reverse('tasks:create')}?project={self.project.pk}"
        html = self.client.get(url).content.decode()
        self.assertIn('name="collegamenti_json"', html)
        self.assertIn("data-kc-attesa", html)
        scelte = [
            {"tipo": "utensile", "testo": "FR-30 Fresa nuova"},
            {"tipo": "macchina", "id": asset.pk},
            {"tipo": "incontro", "id": incontro.pk},
            {"tipo": "boh", "id": 1},
        ]
        oggi = timezone.localdate()
        risposta = self.client.post(url, {
            "title": "Nata dal form", "description": "", "tags": "", "status": TaskStatus.TODO, "priority": "MEDIUM",
            "next_step_due": oggi.isoformat(), "due_date": (oggi + timedelta(days=5)).isoformat(), "next_step_text": "",
            "assigned_to": str(self.user.pk), "task_scope": "project", "project_choice": str(self.project.pk),
            "project_new_name": "", "project_new_description": "", "collegamenti_json": json.dumps(scelte),
        })
        self.assertEqual(risposta.status_code, 302, risposta.content[:2000])
        task = Task.objects.get(title="Nata dal form")
        self.assertEqual(self.tipi(task), ["macchina", "utensile", "incontro"])
        self.assertTrue(Utensile.objects.filter(codice="FR-30").exists())


class PercorsoIndiceTests(CollegamentiBase):
    """Passo 2: il Percorso è l'indice delle tappe, senza campi propri."""

    def setUp(self):
        super().setUp()
        self.url_tappe = reverse("tasks:tappa_azione", args=[self.project.pk])

    def assegna(self, tappa):
        return self.client.post(self.url_tappe, {"tappa": tappa, "action": "assegna"}, HTTP_ACCEPT="application/json")

    def riga(self, tappa):
        from .services import tappe

        return next(r for r in tappe.percorso(self.project)["righe"] if r["key"] == tappa)

    def test_assegna_crea_l_attivita_e_dice_dove_aprirla(self):
        risposta = self.assegna("CMM")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        dati = risposta.json()
        task = Task.objects.get(pk=dati["task_id"])
        self.assertEqual((task.category.tappa, task.title, task.assigned_to), ("CMM", "Programmazione CMM", None))
        # Si apre nel pannello laterale, già sul collegamento che la tappa si aspetta.
        self.assertEqual(dati["apri"], f"{reverse('tasks:detail', args=[task.pk])}?kc=cmm")
        self.assertIn(f'data-tp-task="{task.pk}"', dati["html"])
        self.assertIn("Manca: programma CMM", dati["html"])
        scheda = self.client.get(dati["apri"], HTTP_X_REQUESTED_WITH="XMLHttpRequest").content.decode()
        self.assertIn('data-kc-apri="cmm"', scheda)
        self.assertNotIn("<html", scheda)
        # Una tappa senza collegamenti attesi si apre sulla scheda e basta.
        materiali = self.assegna("MATERIALI").json()
        self.assertNotIn("?kc=", materiali["apri"])

    def test_stato_manca_finche_il_collegamento_non_c_e(self):
        task = Task.objects.get(pk=self.assegna("CAM").json()["task_id"])
        riga = self.riga("CAM")
        self.assertEqual((riga["stato"], riga["stato_label"], riga["chip"]), ("manca", "Manca: programma CAM, macchina", "warn"))
        self.post(task, action="aggiungi", tipo="cam", testo="O1234")
        self.assertEqual(self.riga("CAM")["stato_label"], "Manca: macchina")
        self.post(task, action="collega", tipo="macchina", id=self.macchina().pk)
        riga = self.riga("CAM")
        self.assertEqual(riga["stato"], "fare")
        self.assertEqual([(c["tipo"], c["codice"]) for c in riga["collegamenti"]], [("macchina", "CNC-K1"), ("cam", "O1234 rev. A")])
        html = self.client.get(self.url_tappe, HTTP_ACCEPT="application/json").json()["html"]
        self.assertIn('<span class="tp-lk">Programma CAM <b>O1234 rev. A</b>', html)
        # Chiusa l'attività la tappa è fatta, anche se qualcosa non era stato collegato.
        altra = Task.objects.get(pk=self.assegna("UTENSILI").json()["task_id"])
        altra.status = TaskStatus.DONE
        altra.save()
        self.assertEqual(self.riga("UTENSILI")["stato"], "fatta")

    def test_il_ritardo_viene_prima_di_manca(self):
        task = Task.objects.get(pk=self.assegna("FAI").json()["task_id"])
        self.assertEqual(self.riga("FAI")["stato_label"], "Manca: FAI")
        task.due_date = date(2020, 1, 1)
        task.save()
        self.assertEqual(self.riga("FAI")["stato"], "ritardo")

    def test_indice_si_rilegge_in_get_e_non_scrive(self):
        risposta = self.client.get(self.url_tappe, HTTP_ACCEPT="application/json")
        self.assertEqual(risposta.status_code, 200)
        self.assertIn("Percorso del kickoff", risposta.json()["html"])
        self.assertEqual(Task.objects.filter(project=self.project).count(), 1)
        self.client.logout()
        self.assertEqual(self.client.get(self.url_tappe, HTTP_ACCEPT="application/json").status_code, 401)

    def test_percorso_nella_scheda_dell_incontro(self):
        incontro = self.incontro()
        self.assegna("CMM")
        pagina = self.client.get(reverse("tasks:project_meeting_detail", args=[self.project.pk, incontro.pk])).content.decode()
        self.assertIn("Manca: programma CMM", pagina)
        self.assertNotIn("data-tp-form", pagina)
        self.assertIn("tasks/js/collegamenti.js", pagina)

    def test_cosa_manca_dice_il_collegamento_mancante(self):
        self.assegna("CMM")
        pagina = self.client.get(reverse("tasks:project_overview", args=[self.project.pk]))
        righe = [r for r in pagina.context["cosa_manca"]["righe"] if r["titolo"] == "Programma CMM"]
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["tono"], "warn")
        self.assertIn("Manca: programma CMM", righe[0]["dettaglio"])

    def test_chi_non_e_del_team_non_assegna(self):
        lettore = _create_user_with_legacy(username="col-fuori-team", legacy_user_id=693, role_id=2, role_name="tasks")
        self.client.force_login(lettore)
        risposta = self.assegna("CMM")
        self.assertIn(risposta.status_code, (403, 404))
        self.assertEqual(Task.objects.filter(project=self.project).count(), 1)


class RegistroTests(CollegamentiBase):
    """Passo 3: «Programmi e FAI» è il registro della commessa costruito dalle attività."""

    def setUp(self):
        super().setUp()
        self.url_registro = reverse("tasks:collegamenti_registro", args=[self.project.pk])
        self.pagina = reverse("tasks:project_tech_refs", args=[self.project.pk])
        self.cam_task = self.attivita()
        self.post(self.cam_task, action="aggiungi", tipo="cam", testo="O1234 Fresatura lato A")
        self.ref = ProjectTechRef.objects.get(task=self.cam_task)
        self.post(action="aggiungi", tipo="utensile", testo="FR-12 Fresa")
        self.orfano = ProjectTechRef.objects.create(project=self.project, kind="FAI", code="FAI-2026-041")

    def reg(self, **dati):
        return self.client.post(self.url_registro, dati, HTTP_ACCEPT="application/json")

    def righe(self):
        return {(r["tipo"], r["codice"]): r for r in svc.registro(self.project)["righe"]}

    def test_una_riga_per_collegamento_e_i_senza_attivita(self):
        righe = self.righe()
        self.assertEqual(set(righe), {("utensile", "FR-12"), ("cam", "O1234 rev. A"), ("fai", "FAI-2026-041")})
        self.assertEqual(righe[("cam", "O1234 rev. A")]["task"], self.cam_task)
        self.assertEqual(righe[("utensile", "FR-12")]["task"], self.generica)
        self.assertIsNone(righe[("fai", "FAI-2026-041")]["task"])
        conta = {f["codice"]: f["conta"] for f in svc.registro(self.project)["filtri"]}
        self.assertEqual(conta, {"tutti": 3, "programmi": 1, "fai": 1, "macchina": 0, "attrezzatura": 0, "utensile": 1})
        # L'incontro non è una riga del registro: è l'ordine del giorno.
        self.post(action="collega", tipo="incontro", id=self.incontro().pk)
        self.assertEqual(len(self.righe()), 3)

    def test_pagina_con_filtri_e_comandi_per_chi_gestisce(self):
        html = self.client.get(self.pagina).content.decode()
        for filtro in ("Tutti 3", "Programmi 1", "FAI 1", "Macchine 0", "Attrezzature 0", "Utensili 1"):
            self.assertIn(filtro, html)
        self.assertIn("+ Collegamento", html)
        self.assertEqual(html.count("data-rc-fase"), 1)
        self.assertEqual(html.count("data-rc-orfano"), 1)
        self.assertEqual(html.count("data-rc-togli"), 2)
        self.assertEqual(html.count("data-rc-elimina"), 1)
        # Un clic sull'attività la apre (nel pannello laterale).
        self.assertIn(f'data-preview="{reverse("tasks:detail", args=[self.cam_task.pk])}"', html)
        self.assertNotIn("Da ordinare", html)

    def test_fase_dal_registro(self):
        risposta = self.reg(action="fase", chiave=f"ref:{self.ref.pk}", valore="da_provare")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.fase, "DA_PROVARE")
        self.assertIn("Da provare in macchina", risposta.json()["html"])
        # Un passaggio che da qui non si fa: errore, e la tabella torna com'è.
        risposta = self.reg(action="fase", chiave=f"ref:{self.ref.pk}", valore="inizia")
        self.assertEqual(risposta.status_code, 400)
        self.assertIn("html", risposta.json())

    def test_togli_dal_registro(self):
        risposta = self.reg(action="togli", task=self.cam_task.pk, chiave=f"ref:{self.ref.pk}")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.ref.refresh_from_db()
        self.assertIsNone(self.ref.task, "il programma resta nella commessa, senza attività")
        riga = ProjectUtensile.objects.get(task=self.generica)
        self.reg(action="togli", task=self.generica.pk, chiave=f"ut:{riga.pk}")
        self.assertFalse(ProjectUtensile.objects.exists())
        self.assertTrue(Utensile.objects.filter(codice="FR-12").exists())

    def test_fai_senza_attivita_si_collega_dal_registro(self):
        risposta = self.reg(action="orfano", task=self.generica.pk, chiave=f"ref:{self.orfano.pk}")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.orfano.refresh_from_db()
        self.assertEqual(self.orfano.task, self.generica)
        self.assertIn("collegato a «Preparare il lotto»", risposta.json()["messaggio"])
        self.assertNotIn("data-rc-orfano", risposta.json()["html"])
        # Già collegato: non è più fra i senza attività.
        self.assertEqual(self.reg(action="orfano", task=self.cam_task.pk, chiave=f"ref:{self.orfano.pk}").status_code, 400)

    def test_utensile_del_vecchio_percorso_senza_attivita(self):
        utensile = Utensile.objects.create(codice="MF-M6")
        vecchia = ProjectUtensile.objects.create(project=self.project, utensile=utensile, quantita=3)
        self.assertIsNone(self.righe()[("utensile", "MF-M6")]["task"])
        self.reg(action="orfano", task=self.generica.pk, chiave=f"ut:{vecchia.pk}")
        vecchia.refresh_from_db()
        self.assertEqual((vecchia.task, vecchia.quantita), (self.generica, 3))

    def test_elimina_solo_voci_senza_attivita(self):
        self.assertEqual(self.reg(action="elimina", chiave=f"ref:{self.ref.pk}").status_code, 400)
        self.assertTrue(ProjectTechRef.objects.filter(pk=self.ref.pk).exists())
        self.assertEqual(self.reg(action="elimina", chiave=f"ref:{self.orfano.pk}").status_code, 200)
        self.assertFalse(ProjectTechRef.objects.filter(pk=self.orfano.pk).exists())

    def test_attivita_di_un_altra_commessa_rifiutata(self):
        altra = make_project(name="Altra", created_by=self.user, part_number="PN-2")
        fuori = self.attivita(category=None, project=altra, title="Fuori")
        self.assertEqual(self.reg(action="orfano", task=fuori.pk, chiave=f"ref:{self.orfano.pk}").status_code, 404)
        self.orfano.refresh_from_db()
        self.assertIsNone(self.orfano.task)

    def test_chi_non_gestisce_vede_senza_comandi(self):
        lettore = _create_user_with_legacy(username="col-reg-lettore", legacy_user_id=694, role_id=2, role_name="tasks")
        from .models import TaskAccessLevel, TaskUserAccessRule

        TaskUserAccessRule.objects.create(user=lettore, access_level=TaskAccessLevel.READ_ALL)
        self.client.force_login(lettore)
        pagina = self.client.get(self.pagina)
        self.assertEqual(pagina.status_code, 200)
        html = pagina.content.decode()
        self.assertIn("O1234", html)
        self.assertIn("senza attività", html)
        for comando in ("data-rc-fase", "data-rc-orfano", "data-rc-togli", "data-rc-elimina", "data-rc-nuovo", "+ Collegamento"):
            self.assertNotIn(comando, html)
        for dati in (
            {"action": "fase", "chiave": f"ref:{self.ref.pk}", "valore": "da_provare"},
            {"action": "togli", "task": self.cam_task.pk, "chiave": f"ref:{self.ref.pk}"},
            {"action": "orfano", "task": self.generica.pk, "chiave": f"ref:{self.orfano.pk}"},
            {"action": "elimina", "chiave": f"ref:{self.orfano.pk}"},
            {"action": "fai_non_richiesto", "valore": "1"},
        ):
            risposta = self.reg(**dati)
            self.assertEqual(risposta.status_code, 403, dati)
            self.assertEqual(risposta["Content-Type"], "application/json")
        self.ref.refresh_from_db()
        self.orfano.refresh_from_db()
        self.assertEqual((self.ref.fase, self.ref.task, self.orfano.task), ("IN_SCRITTURA", self.cam_task, None))

    def test_il_responsabile_del_programma_cambia_la_fase_ma_non_toglie(self):
        resp = _create_user_with_legacy(username="col-reg-resp", legacy_user_id=695, role_id=2, role_name="tasks")
        self.cam_task.assigned_to = resp
        self.cam_task.save()
        self.client.force_login(resp)
        html = self.client.get(self.pagina).content.decode()
        self.assertEqual(html.count("data-rc-fase"), 1)
        self.assertNotIn("data-rc-togli", html)
        self.assertEqual(self.reg(action="fase", chiave=f"ref:{self.ref.pk}", valore="da_provare").status_code, 200)
        self.assertEqual(self.reg(action="togli", task=self.cam_task.pk, chiave=f"ref:{self.ref.pk}").status_code, 403)

    def test_json_401_e_acl(self):
        bootstrap_tasks_acl_endpoints(force=True)
        self.assertTrue(RoutePermissionBinding.objects.filter(route_name="tasks:collegamenti_registro").exists())
        self.assertEqual(self.client.get(self.url_registro, HTTP_ACCEPT="application/json").status_code, 200)
        self.client.logout()
        for risposta in (self.reg(action="elimina", chiave="ref:1"), self.client.get(self.url_registro, HTTP_ACCEPT="application/json")):
            self.assertEqual(risposta.status_code, 401)
            self.assertEqual(risposta["Content-Type"], "application/json")

    def test_registri_di_modulo_non_toccati(self):
        for nome in ("tasks:programmi_registro", "tasks:fai_registro"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)
        self.assertContains(self.client.get(reverse("tasks:programmi_registro")), "O1234")
