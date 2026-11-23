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
        # Una sola per attività: un'altra prende il posto della prima.
        seconda = self.macchina("CNC-K2")
        self.post(action="collega", tipo="macchina", id=seconda.pk)
        self.assertEqual(list(TaskExtraRef.objects.filter(task=self.generica).values_list("asset_id", flat=True)), [seconda.pk])
        self.post(action="scollega", chiave=f"mac:{seconda.pk}")
        self.generica.refresh_from_db()
        self.assertNotIn("macchina", self.generica.extra_data)
        self.assertFalse(TaskExtraRef.objects.filter(task=self.generica).exists())

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

    def test_un_solo_programma_o_fai_per_attivita(self):
        self.post(action="aggiungi", tipo="cam", testo="O1")
        risposta = self.post(action="aggiungi", tipo="cmm", testo="M1")
        self.assertEqual(risposta.status_code, 400)
        self.assertIn("ha già", risposta.json()["reason"])
        # Un'attività che «richiede» il CAM non prende un CMM.
        task = self.attivita()
        self.assertEqual(self.post(task, action="aggiungi", tipo="cmm", testo="M2").status_code, 400)

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
