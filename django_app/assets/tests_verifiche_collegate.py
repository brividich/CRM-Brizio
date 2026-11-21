"""Verifiche impianti collegate: ingressi della ditta, scadenza amministrativa, registro scadenze,
«Registra» nella scheda asset e cartelle documento per singolo asset."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore
from assets.models import (
    Asset,
    AssetAdministrativeDeadline,
    AssetCategory,
    AssetCategoryDocumentFolder,
    AssetDocumentFolder,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
)
from assets.services import deadline_feed as feed
from assets.services import periodic_checks as checks
from fornitori import guestportal as gp
from fornitori import ingressi as ing
from fornitori.models import IngressoIntervento

User = get_user_model()


def _accesso(visita=7, giorno=None, azienda="Verifiche Esempio Srl"):
    giorno = giorno or timezone.localdate()
    return gp.Accesso(visita, "CHECKEDOUT", "SUPPLIER", "Tecnico Esempio", azienda, "", "", "B7",
                      datetime.combine(giorno, datetime.min.time()).replace(hour=8),
                      datetime.combine(giorno, datetime.min.time()).replace(hour=11))


@override_settings(LEGACY_AUTH_ENABLED=False)
class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="vc-admin", password="x", email="vc@example.local")
        cls.oggi = timezone.localdate()
        cls.fornitore = Fornitore.objects.create(ragione_sociale="Verifiche Esempio Srl")
        cls.categoria = AssetCategory.objects.create(code="SOLL", label="Sollevamento")
        cls.asset = Asset.objects.create(asset_tag="IMT-PROVA-001", name="Carroponte di prova", asset_category=cls.categoria)
        cls.system = PeriodicCheckSystem.objects.create(name="Sollevamento", asset=cls.asset)
        cls.check_type = PeriodicCheckType.objects.create(
            system=cls.system, name="Verifica trimestrale funi", frequency_months=3,
            method=PeriodicCheckType.METHOD_REPORT, supplier=cls.fornitore,
            next_due_date=cls.oggi + timedelta(days=10),
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self._tmp = tempfile.TemporaryDirectory()
        override = override_settings(ASSETS_PRIVATE_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._tmp.cleanup)

    def _session(self, **kw):
        data = {"check_type": self.check_type, "performed_on": self.oggi, "supplier": self.fornitore}
        data.update(kw)
        return PeriodicCheckSession.objects.create(**data)


class IngressiVerificaTests(Base):
    def test_intervento_verifica_e_collegamento(self):
        session = self._session()
        iv = ing.intervento(ing.TIPO_VERIFICA, session.pk)
        self.assertEqual(iv.fornitore, self.fornitore)
        self.assertEqual(iv.tipo_label, "Verifica impianto")
        self.assertIn("Sollevamento", iv.titolo)
        self.assertEqual(iv.url, reverse("assets:periodic_check_session_detail", args=[session.pk]))
        with mock.patch.object(gp, "visita", return_value=_accesso()):
            link = ing.collega(iv, 7, utente=self.admin, modo="MANUALE")
        self.assertEqual(link.verifica, session)
        self.assertEqual(ing.intervento_del_link(link).oggetto, session)
        self.assertEqual(ing.interventi_per_visite([7])[7][0][1], iv.url)

    def test_verifica_senza_ditta_prende_quella_dell_ingresso(self):
        session = self._session(supplier=None)
        self.check_type.supplier = None
        self.check_type.save()
        iv = ing.intervento(ing.TIPO_VERIFICA, session.pk)
        self.assertTrue(iv.puo_prendere_ditta)
        with mock.patch.object(gp, "visita", return_value=_accesso()):
            link = ing.collega(iv, 7, utente=self.admin, modo="MANUALE")
        session.refresh_from_db()
        self.assertEqual(session.supplier, self.fornitore)
        self.assertIn("verifica", link.nota_ditta)

    def test_vincolo_una_sola_destinazione_anche_con_verifica(self):
        session = self._session()
        dl = AssetAdministrativeDeadline.objects.create(asset=self.asset, title="Verifica SAT", due_date=self.oggi)
        with self.assertRaises(IntegrityError), transaction.atomic():
            IngressoIntervento.objects.create(visita_gp_id=9, verifica=session, scadenza_asset=dl)

    def test_verifiche_tra_le_voci_da_collegare_partendo_dall_ingresso(self):
        session = self._session()
        request = mock.Mock(user=self.admin, legacy_user=None)
        with mock.patch.object(ing, "puo_collegare_ordinaria", return_value=False), \
                mock.patch.object(ing, "puo_collegare_scadenza_asset", return_value=False), \
                mock.patch.object(ing, "puo_collegare_verifica", return_value=True), \
                mock.patch("scadenzario.permessi.categorie_gestibili", return_value=[]):
            voci, _tagliato = ing.scadenze_da_collegare(request, fornitore=self.fornitore, accesso=_accesso())
        self.assertIn((ing.TIPO_VERIFICA, session.pk), [(v.tipo, v.pk) for v in voci])

    def test_riquadro_presenze_nella_verifica(self):
        session = self._session()
        response = self.client.get(reverse("fornitori:presenze_intervento", args=["verifica", session.pk]))
        self.assertEqual(response.status_code, 200)
        page = self.client.get(reverse("assets:periodic_check_session_detail", args=[session.pk]))
        self.assertContains(page, reverse("fornitori:presenze_intervento", args=["verifica", session.pk]))


class RegistraConVisiteTests(Base):
    def test_riquadro_visite_senza_guestportal(self):
        with mock.patch.object(gp, "db_configurato", return_value=False):
            response = self.client.get(reverse("assets:periodic_check_register_visits", args=[self.check_type.pk]))
        self.assertContains(response, "Accessi esterni non configurati")

    def test_riquadro_visite_propone_gli_ingressi_del_giorno_spuntati(self):
        with mock.patch.object(gp, "db_configurato", return_value=True), \
                mock.patch.object(ing, "ingressi_della_ditta", return_value=[_accesso(visita=41)]), \
                mock.patch.object(gp, "storico", return_value=([_accesso(visita=42, azienda="Altra Ditta")], False)):
            response = self.client.get(
                reverse("assets:periodic_check_register_visits", args=[self.check_type.pk]),
                {"performed_on": self.oggi.isoformat(), "supplier": self.fornitore.pk},
            )
        self.assertContains(response, 'value="41" checked')
        self.assertContains(response, 'value="42"')
        self.assertNotContains(response, 'value="42" checked')
        self.assertContains(response, "Altre ditte entrate")

    def test_registrazione_collega_le_visite_spuntate(self):
        with mock.patch.object(gp, "visita", return_value=_accesso(visita=41)):
            response = self.client.post(
                reverse("assets:periodic_check_register", args=[self.check_type.pk]),
                {"performed_on": self.oggi.isoformat(), "outcome": PeriodicCheckSession.OUTCOME_OK,
                 "supplier": self.fornitore.pk, "visita_id": ["41"]},
            )
        session = PeriodicCheckSession.objects.get(check_type=self.check_type)
        self.assertRedirects(response, reverse("assets:periodic_check_session_detail", args=[session.pk]),
                             fetch_redirect_response=False)
        self.assertTrue(IngressoIntervento.objects.filter(verifica=session, visita_gp_id=41).exists())

    def test_pagina_di_registrazione_carica_il_riquadro(self):
        response = self.client.get(reverse("assets:periodic_check_register", args=[self.check_type.pk]))
        self.assertContains(response, reverse("assets:periodic_check_register_visits", args=[self.check_type.pk]))


class ScadenzaCollegataTests(Base):
    def setUp(self):
        super().setUp()
        self.deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset, title="Verifica SAT", due_date=self.oggi + timedelta(days=5),
            recurrence_months=12,
        )
        self.check_type.administrative_deadline = self.deadline
        self.check_type.save()

    def test_registrare_la_verifica_rinnova_la_scadenza(self):
        session = checks.register_session(checks.SessionInput(
            check_type=self.check_type, performed_on=self.oggi, outcome=PeriodicCheckSession.OUTCOME_OK,
        ), user=self.admin)
        self.deadline.refresh_from_db()
        self.check_type.refresh_from_db()
        self.assertEqual(self.deadline.due_date, self.check_type.next_due_date)
        completion = self.deadline.completions.get()
        self.assertEqual(completion.periodic_check_session, session)
        self.assertEqual(completion.completed_on, self.oggi)
        # Una seconda conferma della stessa verifica non registra due volte.
        self.assertIsNone(checks.renew_linked_deadline(session, user=self.admin))
        self.assertEqual(self.deadline.completions.count(), 1)

    def test_verifica_vecchia_non_torna_indietro(self):
        checks.register_session(checks.SessionInput(
            check_type=self.check_type, performed_on=self.oggi, outcome=PeriodicCheckSession.OUTCOME_OK,
        ), user=self.admin)
        due = AssetAdministrativeDeadline.objects.get(pk=self.deadline.pk).due_date
        checks.register_session(checks.SessionInput(
            check_type=self.check_type, performed_on=self.oggi - timedelta(days=100),
            outcome=PeriodicCheckSession.OUTCOME_OK,
        ), user=self.admin)
        self.deadline.refresh_from_db()
        self.assertEqual(self.deadline.due_date, due)
        self.assertEqual(self.deadline.completions.count(), 1)

    def test_una_riga_sola_nel_registro_con_registra_verifica(self):
        rows = feed.collect(start=None, end=self.oggi + timedelta(days=60),
                            filters=feed.FeedFilters(asset_id=self.asset.id), today=self.oggi)
        keys = [r.key for r in rows]
        self.assertIn(f"dl-{self.deadline.id}", keys)
        self.assertNotIn(f"chk-{self.check_type.id}", keys)
        row = next(r for r in rows if r.key == f"dl-{self.deadline.id}")
        self.assertEqual(row.register_action["url"], reverse("assets:periodic_check_register", args=[self.check_type.id]))

    def test_controllo_di_coerenza_date(self):
        self.assertTrue(any("Date diverse" in i for i in checks.deadline_link_issues(self.check_type)))
        response = self.client.get(reverse("assets:periodic_check_type_detail", args=[self.check_type.id]))
        self.assertContains(response, "non allineate")
        self.assertContains(response, "Adempie: Verifica SAT")

    def test_form_del_tipo_salva_il_collegamento(self):
        response = self.client.get(reverse("assets:periodic_check_type_edit", args=[self.check_type.id]))
        self.assertContains(response, "Scadenza amministrativa che adempie")
        self.assertContains(response, "IMT-PROVA-001 · Verifica SAT")


class RegistroScadenzeTests(Base):
    def test_verifica_impianto_nel_registro(self):
        rows = feed.collect(start=None, end=self.oggi + timedelta(days=60),
                            filters=feed.FeedFilters(asset_id=self.asset.id), today=self.oggi)
        row = next(r for r in rows if r.key == f"chk-{self.check_type.id}")
        self.assertEqual(row.kind, feed.KIND_CHECK)
        self.assertEqual(row.asset_id, self.asset.id)
        self.assertEqual(row.register_action["url"], reverse("assets:periodic_check_register", args=[self.check_type.id]))

    def test_amministrativa_senza_verifica_si_registra_dall_elenco(self):
        dl = AssetAdministrativeDeadline.objects.create(asset=self.asset, title="Certificato CE", due_date=self.oggi)
        rows = feed.collect(start=None, end=self.oggi, filters=feed.FeedFilters(kinds=frozenset({feed.KIND_ADMINISTRATIVE})),
                            today=self.oggi)
        row = next(r for r in rows if r.key == f"dl-{dl.id}")
        self.assertIn(f"focus_deadline={dl.id}", row.register_action["url"])

    def test_scheda_verifiche_impianti_nello_scadenzario(self):
        response = self.client.get(reverse("assets:maintenance_scadenze"), {"window": "30", "plan_type": "checks"})
        self.assertContains(response, "Verifica trimestrale funi")
        self.assertContains(response, reverse("assets:periodic_check_register", args=[self.check_type.id]))

    def test_filtro_fornitore_non_svuota_le_scadenze(self):
        response = self.client.get(reverse("assets:maintenance_scadenze"),
                                   {"window": "30", "plan_type": "checks", "supplier": self.fornitore.pk})
        self.assertContains(response, "Verifica trimestrale funi")

    def test_da_fare_mostra_amministrative_e_verifiche(self):
        AssetAdministrativeDeadline.objects.create(asset=self.asset, title="Certificato CE scaduto",
                                                   due_date=self.oggi - timedelta(days=2))
        response = self.client.get(reverse("assets:maintenance_da_fare"), {"mio": "0"})
        self.assertContains(response, "Scadenze amministrative e verifiche impianti")
        self.assertContains(response, "Certificato CE scaduto")
        self.assertContains(response, "Verifica trimestrale funi")


class SchedaAssetTests(Base):
    def test_pulsante_registra_in_testata_e_nelle_righe(self):
        response = self.client.get(reverse("assets:asset_view", args=[self.asset.id]))
        self.assertContains(response, "af-register-menu")
        register_url = reverse("assets:periodic_check_register", args=[self.check_type.id])
        self.assertContains(response, f'href="{register_url}"')
        self.assertContains(response, "Nuovo intervento straordinario")

    def test_cartella_solo_di_questo_asset(self):
        other = Asset.objects.create(asset_tag="IMT-PROVA-002", name="Altro carroponte", asset_category=self.categoria)
        response = self.client.post(reverse("assets:asset_view", args=[self.asset.id]),
                                    {"action": "add_asset_document_folder", "folder_name": "Verbali SAT",
                                     "folder_scope": "asset"})
        self.assertEqual(response.status_code, 302)
        folder = AssetDocumentFolder.objects.get(asset=self.asset)
        self.assertEqual(folder.slug, "verbali-sat")
        self.assertFalse(AssetCategoryDocumentFolder.objects.exists())
        from assets.views import _asset_document_folder_specs

        self.assertIn("verbali-sat", [s["code"] for s in _asset_document_folder_specs(self.asset)])
        self.assertNotIn("verbali-sat", [s["code"] for s in _asset_document_folder_specs(other)])
        # Una cartella di categoria con lo stesso nome non si crea: i documenti finirebbero mescolati.
        self.client.post(reverse("assets:asset_view", args=[self.asset.id]),
                         {"action": "add_asset_document_folder", "folder_name": "Verbali SAT", "folder_scope": "category"})
        self.assertFalse(AssetCategoryDocumentFolder.objects.exists())
        # Disattivazione.
        self.client.post(reverse("assets:asset_view", args=[self.asset.id]),
                         {"action": "deactivate_asset_document_folder", "folder_scope": "asset", "folder_id": folder.id})
        folder.refresh_from_db()
        self.assertFalse(folder.is_active)

    def test_cartella_di_categoria_resta_possibile(self):
        self.client.post(reverse("assets:asset_view", args=[self.asset.id]),
                         {"action": "add_asset_document_folder", "folder_name": "Collaudi", "folder_scope": "category"})
        self.assertTrue(AssetCategoryDocumentFolder.objects.filter(category=self.categoria, slug="collaudi").exists())


class RegistraChiudeScadenzeTests(Base):
    def setUp(self):
        super().setUp()
        self.sat = AssetAdministrativeDeadline.objects.create(
            asset=self.asset, title="Verifica SAT", due_date=self.oggi + timedelta(days=5), recurrence_months=12,
        )
        self.check_type.administrative_deadline = self.sat
        self.check_type.save()
        self.altra = AssetAdministrativeDeadline.objects.create(
            asset=self.asset, title="Certificato funi", due_date=self.oggi, recurrence_months=6,
        )
        self.senza_periodo = AssetAdministrativeDeadline.objects.create(
            asset=self.asset, title="Collaudo una tantum", due_date=self.oggi,
        )

    def _registra(self, **extra):
        data = {"performed_on": self.oggi.isoformat(), "outcome": PeriodicCheckSession.OUTCOME_OK,
                "supplier": self.fornitore.pk, "deadlines_shown": "1"}
        data.update(extra)
        return self.client.post(reverse("assets:periodic_check_register", args=[self.check_type.pk]), data)

    def test_campo_con_la_collegata_gia_scelta(self):
        response = self.client.get(reverse("assets:periodic_check_register", args=[self.check_type.pk]))
        self.assertContains(response, "Scadenze amministrative da chiudere e rinnovare")
        self.assertContains(response, f'value="{self.sat.pk}" selected')

    def test_chiude_e_rinnova_le_scadenze_scelte(self):
        atteso_altra = AssetAdministrativeDeadline.objects.get(pk=self.altra.pk).next_due_after(self.oggi)
        self._registra(deadlines=[self.sat.pk, self.altra.pk, self.senza_periodo.pk])
        session = PeriodicCheckSession.objects.get(check_type=self.check_type)
        self.check_type.refresh_from_db()
        for dl in (self.sat, self.altra, self.senza_periodo):
            dl.refresh_from_db()
            self.assertEqual(dl.completions.get().periodic_check_session, session)
        self.assertEqual(self.sat.due_date, self.check_type.next_due_date)
        self.assertEqual(self.altra.due_date, atteso_altra)
        # Senza periodicità propria prende quella della verifica.
        self.assertEqual(self.senza_periodo.due_date, self.check_type.next_due_date)
        self.assertTrue(self.senza_periodo.is_active)

    def test_togliere_la_collegata_non_la_rinnova(self):
        self._registra(deadlines=[self.altra.pk])
        self.sat.refresh_from_db()
        self.assertFalse(self.sat.completions.exists())
        self.assertTrue(AssetAdministrativeDeadline.objects.get(pk=self.altra.pk).completions.exists())
