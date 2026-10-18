"""Sistema dei permessi sui moduli collegati nel secondo giro.

DPI (con il ponte id anagrafica -> utenti), Anagrafica (elenco, scheda, sezioni
globali), KICK-OFF, Assets, Anomalie, Timbri, Notizie, Procedure. Dati sintetici.
"""
from __future__ import annotations

from unittest.mock import patch

from core.models import AccessGroup, RuoloPermessoModulo
from core.tests_permessi_moduli import ModuliBase, fake_render


def anag(legacy) -> int:
    """Id anagrafica assegnato da ``ModuliBase.nell_organigramma``."""
    return 7000 + legacy.id


# ── DPI ──────────────────────────────────────────────────────────────────────


@patch("dpi.views.render", side_effect=fake_render)
@patch("core.permessi.negato.render", side_effect=fake_render)
class DpiTests(ModuliBase):
    def setUp(self):
        super().setUp()
        from dpi.models import CategoriaDPI, RichiestaDPI

        self.capo, self.capo_l = self.persona("Capo squadra", ruoli=("ruolo-preposto",))
        self.op, self.op_l = self.persona("Operaio")
        self.altro, self.altro_l = self.persona("Altro reparto")
        self.mag, self.mag_l = self.persona("Magazziniere", ruoli=("ruolo-amministrazione",))
        self.nell_organigramma(self.capo_l, self.r_capo)
        self.nell_organigramma(self.op_l, self.r_op)
        self.nell_organigramma(self.altro_l, self.r_capo)  # scheda senza team sotto
        cat = CategoriaDPI.objects.create(nome="Guanti")
        self.rich_op = RichiestaDPI.objects.create(
            categoria=cat, richiedente_legacy_id=anag(self.op_l), richiedente_nome="Operaio", created_by=self.op
        )
        self.rich_altro = RichiestaDPI.objects.create(
            categoria=cat, richiedente_legacy_id=anag(self.altro_l), richiedente_nome="Altro", created_by=self.altro
        )

    def test_proprietario_passa_dall_id_anagrafica_all_account(self, *_):
        from dpi.registro_permessi import proprietario_richiesta

        self.assertEqual(proprietario_richiesta(self.rich_op), self.op_l.id)

    def test_dipendente_vede_solo_le_proprie(self, *_):
        from dpi import views

        ultime = set(views.dashboard(self.req(self.op, self.op_l)).context_data["ultime"])
        self.assertEqual(ultime, {self.rich_op})
        self.assertEqual(views.richiesta_detail(self.req(self.op, self.op_l), self.rich_altro.pk).status_code, 403)

    def test_preposto_approva_il_team_non_gli_altri(self, *_):
        from dpi import views

        request = self.req(self.capo, self.capo_l)
        self.assertTrue(views._can_approve(request, self.rich_op))
        self.assertFalse(views._can_approve(request, self.rich_altro))
        lista = set(views.gestione_list(self.req(self.capo, self.capo_l)).context_data["page_obj"].object_list)
        self.assertEqual(lista, {self.rich_op})

    def test_magazzino_gestisce_ma_non_approva(self, *_):
        from dpi import views

        request = self.req(self.mag, self.mag_l)
        self.assertTrue(views._is_gestore(request))
        self.assertFalse(views._can_approve(request, self.rich_op))
        self.assertEqual(views.gestione_detail(self.req(self.mag, self.mag_l), self.rich_op.pk).status_code, 200)

    def test_nessuno_approva_la_propria_richiesta(self, *_):
        from dpi import views

        self.assertFalse(views._can_approve(self.req(self.op, self.op_l), self.rich_op))

    def test_notifica_va_all_account_non_all_id_anagrafica(self, *_):
        from dpi import views

        with patch("core.notifiche.invia_notifica") as invia, patch("dpi.views.flusso"):
            views.approva_richiesta(self.req(self.capo, self.capo_l, method="post"), self.rich_op.pk)
        self.assertEqual(invia.call_args.kwargs["legacy_user_id"], self.op_l.id)


# ── Anagrafica ───────────────────────────────────────────────────────────────


class AnagraficaTests(ModuliBase):
    def setUp(self):
        super().setUp()
        self.resp, self.resp_l = self.persona("Responsabile", ruoli=("ruolo-responsabile",))
        self.op, self.op_l = self.persona("Operaio")
        self.altro, self.altro_l = self.persona("Altro")
        self.hr, self.hr_l = self.persona("HR", ruoli=("ruolo-hr",))
        self.nell_organigramma(self.resp_l, self.r_capo)
        self.nell_organigramma(self.op_l, self.r_op)
        self.nell_organigramma(self.altro_l, self.r_capo)

    def test_elenco_del_responsabile_e_il_suo_team(self):
        from anagrafica import views

        righe = [{"id": anag(self.op_l)}, {"id": anag(self.altro_l)}, {"id": anag(self.resp_l)}]
        visibili = views.build_dipendenti_rows(self.req(self.resp, self.resp_l), apply_filters=False, base_rows=righe)
        self.assertEqual({r["id"] for r in visibili}, {anag(self.op_l), anag(self.resp_l)})

    def test_hr_vede_tutto_e_i_dati_riservati(self):
        from anagrafica import views

        righe = [{"id": anag(self.op_l)}, {"id": anag(self.altro_l)}]
        request = self.req(self.hr, self.hr_l)
        self.assertEqual(len(views.build_dipendenti_rows(request, apply_filters=False, base_rows=righe)), 2)
        self.assertTrue(views._check_hr_permission(request))
        self.assertTrue(views._can_view_visite_mediche(request))

    def test_responsabile_non_apre_sezioni_globali_ne_dati_riservati(self):
        from anagrafica import views

        request = self.req(self.resp, self.resp_l)
        self.assertFalse(views._check_hr_permission(request))
        self.assertFalse(views._can_view_visite_mediche(request))
        self.assertFalse(views._can_view_formazione(request))
        self.assertFalse(views._is_anagrafica_admin(request))

    def test_scheda_fuori_team_negata(self):
        from anagrafica import views

        with patch("anagrafica.views.dipendenti.fetch_anagrafica_rows",
                   return_value=[{"id": anag(self.altro_l), "utente_id": self.altro_l.id}]), \
             patch("anagrafica.views.dipendenti.ensure_anagrafica_schema"), \
             patch("core.permessi.negato.render", side_effect=fake_render):
            risposta = views.dipendente_detail(self.req(self.resp, self.resp_l), anag(self.altro_l))
        self.assertEqual(risposta.status_code, 403)


# ── KICK-OFF ─────────────────────────────────────────────────────────────────


class KickoffTests(ModuliBase):
    def setUp(self):
        super().setUp()
        from tasks.models import Task

        self.resp, self.resp_l = self.persona("Responsabile", ruoli=("ruolo-responsabile",))
        self.op, self.op_l = self.persona("Operaio")
        self.altro, self.altro_l = self.persona("Altro")
        self.ut, self.ut_l = self.persona("Ufficio tecnico", ruoli=("ruolo-ufficio-tecnico",))
        self.nell_organigramma(self.resp_l, self.r_capo)
        self.nell_organigramma(self.op_l, self.r_op)
        self.t_op = Task.objects.create(title="Attrezzaggio", created_by=self.altro, assigned_to=self.op)
        self.t_altro = Task.objects.create(title="Collaudo", created_by=self.altro, assigned_to=self.altro)

    def visibili(self, user, legacy):
        from tasks.access import scoped_tasks_queryset

        return set(scoped_tasks_queryset(self.req(user, legacy)))

    def test_responsabile_vede_il_team(self):
        self.assertEqual(self.visibili(self.resp, self.resp_l), {self.t_op})

    def test_dipendente_senza_kickoff_non_vede_nulla(self):
        self.assertEqual(self.visibili(self.op, self.op_l), set())

    def test_ufficio_tecnico_vede_e_gestisce_tutto(self):
        from tasks.access import can_manage_task, has_task_permission

        self.assertEqual(self.visibili(self.ut, self.ut_l), {self.t_op, self.t_altro})
        request = self.req(self.ut, self.ut_l)
        self.assertTrue(can_manage_task(request, self.t_altro))
        self.assertTrue(has_task_permission(request, "tasks_admin"))

    def test_responsabile_modifica_le_attivita_del_team(self):
        from tasks.access import can_manage_task

        request = self.req(self.resp, self.resp_l)
        self.assertTrue(can_manage_task(request, self.t_op))
        self.assertFalse(can_manage_task(request, self.t_altro))


# ── Moduli con cancello di gestione ──────────────────────────────────────────


class CancelliGestioneTests(ModuliBase):
    def test_assets_amministrato_da_it_e_manutenzione(self):
        from assets.views import _is_assets_admin

        self.assertTrue(_is_assets_admin(self.req(*self.persona("IT", ruoli=("ruolo-tecnico-it",)))))
        self.assertFalse(_is_assets_admin(self.req(*self.persona("UT", ruoli=("ruolo-ufficio-tecnico",)))))

    def test_timbri_dalla_matrice_non_dal_nome_del_ruolo(self):
        from timbri.views import _can_download_timbri, _can_edit_timbri

        qualita = self.req(*self.persona("Qualità", ruoli=("ruolo-qualita",)))
        self.assertTrue(_can_edit_timbri(qualita))
        self.assertTrue(_can_download_timbri(qualita))
        self.assertFalse(_can_edit_timbri(self.req(*self.persona("Dipendente"))))

    def test_notizie_gestite_da_hr_e_sicurezza(self):
        from notizie.views import _is_admin_or_hr

        self.assertTrue(_is_admin_or_hr(self.req(*self.persona("HR", ruoli=("ruolo-hr",)))))
        self.assertFalse(_is_admin_or_hr(self.req(*self.persona("Dipendente"))))

    def test_procedure_gestite_da_sicurezza(self):
        from procedure_refresh.views import _is_manager

        self.assertTrue(_is_manager(self.req(*self.persona("RSPP", ruoli=("ruolo-sicurezza",)))))
        self.assertFalse(_is_manager(self.req(*self.persona("Resp", ruoli=("ruolo-responsabile",)))))

    def test_anomalie_livello_globale_dalla_matrice(self):
        from anomalie.models import AnomalieAccessLevel
        from anomalie.views import _request_anomalie_global_access_level

        qualita = self.req(*self.persona("Qualità", ruoli=("ruolo-qualita",)))
        self.assertEqual(_request_anomalie_global_access_level(qualita), AnomalieAccessLevel.EDIT_ALL)
        ut = self.req(*self.persona("UT", ruoli=("ruolo-ufficio-tecnico",)))
        self.assertEqual(_request_anomalie_global_access_level(ut), AnomalieAccessLevel.READ_ALL)
        self.assertEqual(
            _request_anomalie_global_access_level(self.req(*self.persona("Dipendente"))), AnomalieAccessLevel.NONE
        )

    def test_azione_extra_dati_riservati_in_matrice(self):
        from core.permessi import decisione

        # Dati riservati solo a Gestione personale, non a tutta l'Amministrazione.
        amm = self.persona("Contabile", ruoli=("ruolo-amministrazione",))[0]
        self.assertFalse(decisione(amm, "anagrafica", "dati_riservati").consentito)
        personale = self.persona("Paghe", ruoli=("ruolo-hr",))[0]
        self.assertTrue(decisione(personale, "anagrafica", "dati_riservati").consentito)
        ruolo = AccessGroup.objects.get(code="ruolo-hr")
        self.assertTrue(RuoloPermessoModulo.objects.filter(ruolo=ruolo, azione="dati_riservati").exists())
