"""Interventi straordinari: Interno/Esterno, squadra manutenzione, ditta creata al volo,
modifica dell'intervento e scheda di lavoro completa. Solo dati sintetici."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Fornitore
from assets.models import Asset, WorkOrder, WorkOrderChecklist, WorkOrderLog
from assets.services import squadra_manutenzione
from core.models import AccessGroup, AccessGroupMembership, Profile

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="syn.admin", email="syn.admin@example.com", password="x")
        self.asset = Asset.objects.create(
            asset_tag="CNC-SYN-0001",
            name="Fresa sintetica FS1",
            asset_type=Asset.TYPE_OTHER,
            status=Asset.STATUS_IN_USE,
            reparto="Officina",
        )
        self.client.force_login(self.admin)

    def _post_create(self, **extra):
        data = {"kind": WorkOrder.KIND_CORRECTIVE, "title": "Perdita olio sintetica", "downtime_minutes": "0"}
        data.update(extra)
        return self.client.post(reverse("assets:wo_create", args=[self.asset.id]), data)


class SquadraManutenzioneTests(_Base):
    def setUp(self):
        super().setUp()
        self.manutentore = User.objects.create_user(username="syn.manut", first_name="Mario", last_name="Sintetico")
        self.altro = User.objects.create_user(username="syn.altro", first_name="Altro", last_name="Utente")
        Profile.objects.create(user=self.manutentore, legacy_user_id=990001)
        Profile.objects.create(user=self.altro, legacy_user_id=990002)
        gruppo = AccessGroup.objects.create(code="syn-squadra-man", label="Squadra MAN sintetica", priority=300)
        AccessGroupMembership.objects.create(group=gruppo, legacy_user_id=990001)
        squadra_manutenzione.salva_impostazioni(gruppo="syn-squadra-man", assegnatario="syn.manut")

    def test_interno_propone_predefinito_e_limita_alla_squadra(self):
        response = self.client.get(reverse("assets:wo_create", args=[self.asset.id]) + "?kind=CORRECTIVE")
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial.get("execution_mode"), WorkOrder.EXECUTION_INTERNAL)
        self.assertEqual(form.initial.get("assigned_to"), self.manutentore.pk)
        ids = set(form.fields["assigned_to"].queryset.values_list("pk", flat=True))
        self.assertIn(self.manutentore.pk, ids)
        self.assertNotIn(self.altro.pk, ids)
        self.assertContains(response, "Chi lo esegue")
        self.assertNotContains(response, "Risoluzione gia applicata")

    def test_senza_squadra_vale_tutti(self):
        squadra_manutenzione.salva_impostazioni(gruppo="", assegnatario="")
        self.assertIsNone(squadra_manutenzione.membri_squadra())
        response = self.client.get(reverse("assets:wo_create", args=[self.asset.id]))
        ids = set(response.context["form"].fields["assigned_to"].queryset.values_list("pk", flat=True))
        self.assertIn(self.altro.pk, ids)

    def test_impostazioni_salvate_da_gestione_admin(self):
        response = self.client.post(
            reverse("assets:gestione_admin") + "?tab=config",
            {"action": "save_squadra_manutenzione", "squadra_gruppo": "", "squadra_assegnatario": "syn.altro"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(squadra_manutenzione.impostazioni()["assegnatario"], "syn.altro")
        response = self.client.get(reverse("assets:gestione_admin") + "?tab=config")
        self.assertContains(response, "Squadra manutenzione")


class SquadraPredefinitaTests(_Base):
    def test_senza_impostazione_vale_il_ruolo_manutenzione(self):
        manut = User.objects.create_user(username="syn.def.manut")
        altro = User.objects.create_user(username="syn.def.altro")
        Profile.objects.create(user=manut, legacy_user_id=990101)
        gruppo, _ = AccessGroup.objects.get_or_create(code="manutenzione", defaults={"label": "Manutenzione"})
        AccessGroupMembership.objects.create(group=gruppo, legacy_user_id=990101)
        response = self.client.get(reverse("assets:wo_create", args=[self.asset.id]))
        ids = set(response.context["form"].fields["assigned_to"].queryset.values_list("pk", flat=True))
        self.assertIn(manut.pk, ids)
        self.assertNotIn(altro.pk, ids)


class StraordinariaEsternaTests(_Base):
    def test_ditta_nuova_creata_e_collegata(self):
        response = self._post_create(execution_mode="EXTERNAL", supplier_name="  Ditta   Sintetica Nuova  ")
        self.assertEqual(response.status_code, 302)
        wo = WorkOrder.objects.get(asset=self.asset)
        self.assertEqual(wo.execution_mode, WorkOrder.EXECUTION_EXTERNAL)
        self.assertEqual(wo.supplier.ragione_sociale, "Ditta Sintetica Nuova")
        self.assertEqual(wo.supplier.categoria, Fornitore.CATEGORIA_MANUTENZIONE)
        self.assertTrue(WorkOrderLog.objects.filter(work_order=wo, note__contains="anagrafica fornitori").exists())

    def test_ditta_esistente_senza_duplicati(self):
        esistente = Fornitore.objects.create(ragione_sociale="Officina Sintetica Srl")
        self._post_create(execution_mode="EXTERNAL", supplier_name="officina sintetica srl")
        wo = WorkOrder.objects.get(asset=self.asset)
        self.assertEqual(wo.supplier_id, esistente.pk)
        self.assertEqual(Fornitore.objects.filter(ragione_sociale__iexact="officina sintetica srl").count(), 1)

    def test_esterno_senza_ditta_chiede_la_ditta(self):
        response = self._post_create(execution_mode="EXTERNAL", supplier_name="")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Indica la ditta esterna")
        self.assertFalse(WorkOrder.objects.filter(asset=self.asset).exists())

    def test_interno_ignora_la_ditta(self):
        self._post_create(execution_mode="INTERNAL", supplier_name="Ditta che non serve")
        wo = WorkOrder.objects.get(asset=self.asset)
        self.assertIsNone(wo.supplier_id)
        self.assertEqual(wo.execution_mode, WorkOrder.EXECUTION_INTERNAL)
        self.assertFalse(Fornitore.objects.filter(ragione_sociale="Ditta che non serve").exists())


class ModificaInterventoTests(_Base):
    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(
            asset=self.asset, kind=WorkOrder.KIND_CORRECTIVE, status=WorkOrder.STATUS_OPEN, title="Titolo iniziale"
        )

    def test_dettaglio_mostra_modifica(self):
        response = self.client.get(reverse("assets:wo_view", args=[self.wo.id]))
        self.assertContains(response, reverse("assets:wo_edit", args=[self.wo.id]))

    def test_modifica_salva_e_registra(self):
        url = reverse("assets:wo_edit", args=[self.wo.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salva modifiche")
        response = self.client.post(
            url,
            {
                "kind": WorkOrder.KIND_CORRECTIVE,
                "title": "Titolo corretto",
                "downtime_minutes": "15",
                "execution_mode": "EXTERNAL",
                "supplier_name": "Ditta Sintetica Modifica",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.title, "Titolo corretto")
        self.assertEqual(self.wo.status, WorkOrder.STATUS_OPEN)
        self.assertEqual(self.wo.supplier.ragione_sociale, "Ditta Sintetica Modifica")
        log = WorkOrderLog.objects.filter(work_order=self.wo, note__startswith="Intervento modificato").first()
        self.assertIsNotNone(log)
        self.assertIn("Titolo", log.note)

    def test_chiuso_non_modificabile(self):
        self.wo.status = WorkOrder.STATUS_DONE
        self.wo.save(update_fields=["status"])
        response = self.client.get(reverse("assets:wo_edit", args=[self.wo.id]))
        self.assertRedirects(response, reverse("assets:wo_view", args=[self.wo.id]), fetch_redirect_response=False)


class SchedaLavoroTests(_Base):
    def test_scheda_riporta_dati_intervento_e_checklist(self):
        wo = WorkOrder.objects.create(
            asset=self.asset,
            kind=WorkOrder.KIND_CORRECTIVE,
            priority=WorkOrder.PRIORITY_URGENT,
            status=WorkOrder.STATUS_OPEN,
            title="Rumore mandrino",
            notes="Nota sintetica",
            execution_mode=WorkOrder.EXECUTION_INTERNAL,
        )
        WorkOrderChecklist.objects.create(work_order=wo, step_number=1, description="Verifica cuscinetti sintetica")
        response = self.client.get(reverse("assets:workorder_worksheet", args=[wo.id]))
        self.assertEqual(response.status_code, 200)
        for testo in (
            "Fresa sintetica FS1", "CNC-SYN-0001", "Officina", "Correttiva", "Urgente",
            "Interna", "Nota sintetica", "Verifica cuscinetti sintetica",
        ):
            self.assertContains(response, testo)
