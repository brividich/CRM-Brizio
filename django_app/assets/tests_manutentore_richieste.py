"""Richieste della manutenzione del 05/11/2026: ricerca elastica, chiusura
essenziale delle straordinarie con anteprima foto. Solo dati sintetici."""
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from assets.models import Asset, WorkOrder, WorkOrderAttachment
from assets.services.module_search import search
from assets.services.ricerca_flessibile import testo_q

User = get_user_model()

_CAMPI = ("asset_tag", "name", "internal_number")


class RicercaFlessibileTests(TestCase):
    def setUp(self):
        self.spaziato = Asset.objects.create(asset_tag="SYN-RF-1", name="DIXI 80", asset_type=Asset.TYPE_OTHER)
        self.attaccato = Asset.objects.create(asset_tag="SYN-RF-2", name="Dixi80 rettifica", asset_type=Asset.TYPE_OTHER)
        self.trattino = Asset.objects.create(asset_tag="SYN-RF-3", name="Dixi-80 bis", asset_type=Asset.TYPE_OTHER)
        self.altro = Asset.objects.create(asset_tag="SYN-RF-4", name="Tornio 80", asset_type=Asset.TYPE_OTHER)

    def _trova(self, termine):
        return set(Asset.objects.filter(testo_q(termine, _CAMPI)).values_list("pk", flat=True))

    def test_con_e_senza_spazi_e_trattini(self):
        attesi = {self.spaziato.pk, self.attaccato.pk, self.trattino.pk}
        self.assertEqual(self._trova("dixi 80"), attesi)
        self.assertEqual(self._trova("dixi80"), attesi)
        self.assertEqual(self._trova("DIXI-80"), attesi)

    def test_parole_in_qualunque_ordine(self):
        self.assertIn(self.spaziato.pk, self._trova("80 dixi"))
        self.assertNotIn(self.altro.pk, self._trova("dixi 80"))

    def test_ricerca_del_modulo(self):
        admin = User.objects.create_superuser(username="syn.rf.admin", email="syn.rf@example.com", password="x")
        self.client.force_login(admin)
        request = self.client.get(reverse("assets:module_search"), {"q": "dixi80"}).wsgi_request
        gruppi = {g.key: g for g in search(request, "dixi80")}
        self.assertIn("asset", gruppi)
        self.assertEqual(gruppi["asset"].total, 3)

    def test_elenco_asset(self):
        admin = User.objects.create_superuser(username="syn.rf.adm2", email="syn.rf2@example.com", password="x")
        self.client.force_login(admin)
        response = self.client.get(reverse("assets:asset_list"), {"q": "dixi 80"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dixi80 rettifica")
        self.assertNotContains(response, "Tornio 80")


class ChiusuraStraordinariaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="syn.cs.admin", email="syn.cs@example.com", password="x")
        self.manut = User.objects.create_user(username="syn.cs.manut")
        self.asset = Asset.objects.create(asset_tag="SYN-CS-1", name="Pressa sintetica", asset_type=Asset.TYPE_OTHER)
        self.client.force_login(self.admin)

    def _wo(self, kind):
        return WorkOrder.objects.create(
            asset=self.asset, kind=kind, status=WorkOrder.STATUS_OPEN, title="Guasto sintetico",
            assigned_to=self.manut,
        )

    def test_straordinaria_essenziale_con_pulsante_in_fondo(self):
        wo = self._wo(WorkOrder.KIND_CORRECTIVE)
        response = self.client.get(reverse("assets:wo_close", args=[wo.id]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("Rapporto / documento", html)
        self.assertNotIn("Altri dettagli", html)
        self.assertIn('name="assigned_to"', html)  # resta, nascosto
        # Il pulsante di chiusura viene dopo i ricambi e invia il form con form=
        self.assertGreater(html.index('id="workorderCloseSubmit"'), html.index("Caricamento ricambi"))
        self.assertIn('form="workorderCloseForm"', html)
        self.assertContains(response, reverse("assets:wo_edit", args=[wo.id]))

    def test_chiusura_essenziale_non_perde_l_assegnatario(self):
        wo = self._wo(WorkOrder.KIND_CORRECTIVE)
        page = self.client.get(reverse("assets:wo_close", args=[wo.id]))
        form = page.context["form"]
        data = {
            "status": WorkOrder.STATUS_DONE,
            "esito": WorkOrder.OUTCOME_RESOLVED,
            "resolution": "Ripristinato sensore",
            "assigned_to": form["assigned_to"].value() or "",
            "executed_by": self.admin.pk,
            "covered_by_contract": "False",
        }
        response = self.client.post(reverse("assets:wo_close", args=[wo.id]), data)
        self.assertEqual(response.status_code, 302)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrder.STATUS_DONE)
        self.assertEqual(wo.assigned_to_id, self.manut.pk)

    def test_preventiva_mantiene_altri_dettagli(self):
        wo = self._wo(WorkOrder.KIND_PREVENTIVE)
        response = self.client.get(reverse("assets:wo_close", args=[wo.id]))
        self.assertContains(response, "Altri dettagli")
        self.assertContains(response, "Rapporto / documento")

    def test_anteprima_foto(self):
        wo = self._wo(WorkOrder.KIND_CORRECTIVE)
        for nome in ("guasto1.jpg", "guasto2.png", "rapportino.pdf"):
            allegato = WorkOrderAttachment(work_order=wo, original_name=nome)
            allegato.file.save(nome, ContentFile(b"synthetic"), save=True)
        response = self.client.get(reverse("assets:wo_close", args=[wo.id]))
        self.assertContains(response, "data-wof-gal")
        self.assertEqual(len(response.context["workorder_foto"]), 2)
        self.assertContains(response, "1 / 2")
        self.assertContains(response, "Foto successiva")
        detail = self.client.get(reverse("assets:wo_view", args=[wo.id]))
        self.assertContains(detail, "data-wof-gal")
