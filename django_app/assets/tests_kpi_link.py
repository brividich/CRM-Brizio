"""KPI cliccabili del modulo Asset: ogni tessera porta all'elenco filtrato che conta
lo stesso numero (stessa condizione, stesso ambito). Dati sintetici."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    AssetComponent,
    AssistanceContract,
    SoftwareLicense,
    WorkOrder,
)

User = get_user_model()


def _complete_onboarding(user) -> None:
    from core.models import UserOnboarding

    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()}
    )


class _AdminClientMixin:
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="kpi3-admin", password="x", email="kpi3@example.com")
        _complete_onboarding(cls.admin)

    def setUp(self):
        self.client.force_login(self.admin)

    def _wo_count(self, query: str) -> int:
        response = self.client.get(f"{reverse('assets:wo_list')}?{query}")
        self.assertEqual(response.status_code, 200)
        return len(list(response.context["workorders"]))

    def _asset_count(self, query: str) -> int:
        response = self.client.get(f"{reverse('assets:asset_list')}?{query}")
        self.assertEqual(response.status_code, 200)
        return response.context["visible_count"]


class AssetListStatusFilterTests(_AdminClientMixin, TestCase):
    """Il filtro ``status`` dell'inventario (prima i link «?status=IN_USE» del cruscotto
    venivano ignorati e mostravano tutto)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat = AssetCategory.objects.create(code="kpi3-cat", label="KPI3 cat")
        cls.child = AssetCategory.objects.create(code="kpi3-child", label="KPI3 figlia", parent=cls.cat)
        Asset.objects.create(asset_tag="K3-USE", name="In uso", status=Asset.STATUS_IN_USE, asset_category=cls.cat)
        Asset.objects.create(asset_tag="K3-REP", name="Rotto", status=Asset.STATUS_IN_REPAIR, asset_category=cls.child)
        Asset.objects.create(asset_tag="K3-RET", name="Dismesso", status=Asset.STATUS_RETIRED, asset_category=cls.cat)

    def test_status_filtra_e_attivi_esclude_i_dismessi(self):
        self.assertEqual(self._asset_count("status=IN_USE"), Asset.objects.filter(status=Asset.STATUS_IN_USE).count())
        self.assertEqual(self._asset_count("status=RETIRED"), 1)
        self.assertEqual(
            self._asset_count("status=ATTIVI"), Asset.objects.exclude(status=Asset.STATUS_RETIRED).count()
        )

    def test_sottocategorie_zero_conta_solo_la_categoria_esatta(self):
        self.assertEqual(self._asset_count(f"asset_category={self.cat.id}"), 3)
        self.assertEqual(self._asset_count(f"asset_category={self.cat.id}&sottocategorie=0"), 2)

    def test_kpi_della_lista_hanno_link_coerenti(self):
        response = self.client.get(reverse("assets:asset_list"))
        links = response.context["kpi_links"]
        self.assertEqual(links["in_repair"], f"{reverse('assets:asset_list')}?status=IN_REPAIR")
        self.assertContains(response, 'href="/assets/lista/?status=IN_REPAIR"')
        self.assertEqual(self._asset_count("status=IN_REPAIR"), response.context["in_repair_count"])
        self.assertEqual(self._asset_count(""), response.context["total_assets"])


class WorkOrderKpiFilterTests(_AdminClientMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from anagrafica.models import Fornitore

        cls.supplier = Fornitore.objects.create(ragione_sociale="Ditta KPI3")
        cls.machine = Asset.objects.create(asset_tag="K3-CNC", name="CNC", asset_type=Asset.TYPE_CNC)
        cls.pc = Asset.objects.create(asset_tag="K3-PC", name="PC", asset_type=Asset.TYPE_PC)
        cls.retired = Asset.objects.create(asset_tag="K3-OLD", name="Vecchia", status=Asset.STATUS_RETIRED)
        now = timezone.now()
        WorkOrder.objects.create(asset=cls.machine, title="aperto vecchio", opened_at=now - timedelta(days=400),
                                 supplier=cls.supplier)
        WorkOrder.objects.create(asset=cls.pc, title="aperto nuovo", opened_at=now)
        WorkOrder.objects.create(asset=cls.retired, title="aperto su dismesso", opened_at=now)
        WorkOrder.objects.create(asset=cls.machine, title="chiuso oggi", status=WorkOrder.STATUS_DONE,
                                 opened_at=now - timedelta(days=2), closed_at=now, supplier=cls.supplier)
        WorkOrder.objects.create(asset=cls.machine, title="chiuso un anno fa", status=WorkOrder.STATUS_DONE,
                                 opened_at=now - timedelta(days=500), closed_at=now - timedelta(days=380))

    def test_filtri_dei_kpi(self):
        self.assertEqual(self._wo_count("status=OPEN"), 3)
        self.assertEqual(self._wo_count("status=OPEN&attivi=1"), 2)
        self.assertEqual(self._wo_count("status=OPEN&ritardo=1"), 1)
        self.assertEqual(self._wo_count("status=OPEN&produzione=1"), 1)
        self.assertEqual(self._wo_count("status=OPEN&tipo_asset=PC,NON_ESISTE"), 1)
        self.assertEqual(self._wo_count(f"status=OPEN&supplier={self.supplier.id}"), 1)
        month_start = timezone.localdate().replace(day=1).isoformat()
        self.assertEqual(self._wo_count(f"status=DONE&chiusi_dal={month_start}"), 1)
        self.assertEqual(self._wo_count("status=DONE&chiusi_dal=data-sbagliata"), 2)

    def test_chip_dei_filtri_kpi(self):
        response = self.client.get(f"{reverse('assets:wo_list')}?status=OPEN&ritardo=1&attivi=1")
        labels = {chip["label"] for chip in response.context["active_filter_chips"]}
        self.assertTrue({"Ritardo", "Asset"} <= labels)

    def test_scheda_fornitore_porta_agli_stessi_odl(self):
        response = self.client.get(reverse("assets:maintenance_supplier_detail", args=[self.supplier.id]))
        links = response.context["supplier_kpi_links"]
        self.assertEqual(self._wo_count(links["open"].split("?", 1)[1]), response.context["open_total"])
        self.assertEqual(self._wo_count(links["closed_12m"].split("?", 1)[1]), response.context["closed_12m"])
        self.assertContains(response, "kpi-link")


class DashboardKpiLinkTests(_AdminClientMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat = AssetCategory.objects.create(code="kpi3-fam", label="Famiglia KPI3")
        a1 = Asset.objects.create(asset_tag="K3-D1", name="D1", status=Asset.STATUS_IN_USE, asset_category=cls.cat)
        Asset.objects.create(asset_tag="K3-D2", name="D2", status=Asset.STATUS_IN_REPAIR, asset_category=cls.cat)
        Asset.objects.create(asset_tag="K3-D3", name="D3", status=Asset.STATUS_RETIRED, asset_category=cls.cat)
        now = timezone.now()
        WorkOrder.objects.create(asset=a1, title="aperto", opened_at=now)
        WorkOrder.objects.create(asset=a1, title="chiuso", status=WorkOrder.STATUS_DONE, opened_at=now, closed_at=now)

    def test_tessere_e_numeri_coincidono_con_gli_elenchi(self):
        response = self.client.get(reverse("assets:asset_dashboard"))
        self.assertEqual(response.status_code, 200)
        kpis = response.context["kpis"]
        month_start = timezone.localdate().replace(day=1).isoformat()
        self.assertContains(response, "?status=ATTIVI")
        self.assertContains(response, "status=OPEN&amp;ritardo=1&amp;attivi=1")
        self.assertEqual(self._asset_count("status=ATTIVI"), kpis["totale_asset"])
        self.assertEqual(self._asset_count("status=IN_USE"), kpis["asset_in_uso"])
        self.assertEqual(self._asset_count("status=IN_REPAIR"), kpis["asset_in_riparazione"])
        self.assertEqual(self._wo_count("status=OPEN"), kpis["wo_aperte"])
        self.assertEqual(self._wo_count(f"status=DONE&chiusi_dal={month_start}"), kpis["wo_chiuse_mese"])
        dash_wo = response.context["dash_wo"]
        self.assertEqual(self._wo_count("status=OPEN&attivi=1"), dash_wo["total"])
        self.assertEqual(self._wo_count("view=unassigned&attivi=1"), dash_wo["unassigned"])

    def test_kpi_per_famiglia(self):
        response = self.client.get(f"{reverse('assets:asset_dashboard')}?family={self.cat.id}")
        fk = response.context["family_kpis"]
        base = f"asset_category={self.cat.id}&sottocategorie=0"
        self.assertEqual(self._asset_count(f"status=ATTIVI&{base}"), fk["totale_asset_famiglia"])
        self.assertEqual(self._asset_count(f"status=IN_USE&{base}"), fk["asset_in_uso_famiglia"])
        self.assertEqual(self._wo_count(f"status=OPEN&attivi=1&category={self.cat.id}"), fk["wo_aperte_famiglia"])
        self.assertContains(response, f"asset_category={self.cat.id}&amp;sottocategorie=0")

    def test_scadenze_90_cumulative(self):
        from assets.views.dashboard import _compute_dashboard_kpis
        from types import SimpleNamespace

        today = timezone.localdate()
        dues = [SimpleNamespace(due_date=today + timedelta(days=d), asset=SimpleNamespace(id=1)) for d in (5, 60)]
        request = mock.Mock(user=self.admin)
        with mock.patch("assets.services.deadline_feed.administrative_dues", return_value=dues), \
                mock.patch("assets.services.visibilita.ids_visibili", return_value=None):
            kpis = _compute_dashboard_kpis(request, today)
        self.assertEqual((kpis["scadenze_30gg"], kpis["scadenze_90gg"]), (1, 2))


class StatoContattiLicenzeComponentiTests(_AdminClientMixin, TestCase):
    """Le tessere per stato contano PRIMA del filtro di stato: cliccandole si apre
    lo stesso numero (prima con un filtro attivo le altre tessere davano 0)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from anagrafica.models import Fornitore

        today = timezone.localdate()
        cls.supplier = Fornitore.objects.create(ragione_sociale="Assistenza KPI3")
        AssistanceContract.objects.create(supplier=cls.supplier, title="attivo", end_date=today + timedelta(days=200))
        AssistanceContract.objects.create(supplier=cls.supplier, title="in scadenza", end_date=today + timedelta(days=10))
        AssistanceContract.objects.create(supplier=cls.supplier, title="spento", is_active=False)
        SoftwareLicense.objects.create(product_name="Lic A", expiry_date=today + timedelta(days=10))
        SoftwareLicense.objects.create(product_name="Lic B", expiry_date=today - timedelta(days=1))
        SoftwareLicense.objects.create(product_name="Lic C", assigned_legacy_user_id=999001)
        asset = Asset.objects.create(asset_tag="K3-COMP", name="Con componenti")
        AssetComponent.objects.create(asset=asset, name="Attivo", code="C1")
        AssetComponent.objects.create(asset=asset, name="Spento", code="C2", is_active=False)

    def _contracts(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response

    def test_contratti(self):
        response = self._contracts(f"{reverse('assets:assistance_contract_list')}?state=expiring")
        self.assertEqual(response.context["active_count"], 1)
        self.assertEqual(response.context["expiring_count"], 1)
        links = response.context["contract_kpi_links"]
        self.assertEqual(self._contracts(links["active"]).context["contract_total"], 1)
        self.assertEqual(
            self._contracts(f"{reverse('assets:assistance_contract_list')}?supplier={self.supplier.id}&state=enabled")
            .context["contract_total"],
            2,
        )

    def test_licenze(self):
        response = self.client.get(f"{reverse('assets:software_license_list')}?status=expired")
        self.assertEqual(response.context["expiring_count"], 1)
        self.assertEqual(response.context["expired_count"], 1)
        links = response.context["license_kpi_links"]
        self.assertEqual(self.client.get(links["expiring"]).context["license_total"], 1)
        # Lic C e' assegnata a un utente legacy: non e' «da assegnare».
        response = self.client.get(reverse("assets:software_license_list"))
        unassigned = response.context["unassigned_count"]
        self.assertEqual(unassigned, 2)
        self.assertEqual(
            self.client.get(response.context["license_kpi_links"]["unassigned"]).context["license_total"], unassigned
        )

    def test_componenti_disattivi_contati_anche_col_filtro_predefinito(self):
        response = self.client.get(reverse("assets:asset_component_list"))
        self.assertEqual(response.context["inactive_component_count"], 1)
        link = response.context["component_kpi_links"]["inactive"]
        self.assertEqual(self.client.get(link).context["component_total"], 1)
        self.assertContains(response, "kpi-link")


class AltrePagineKpiTests(_AdminClientMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        now = timezone.now()
        asset = Asset.objects.create(asset_tag="K3-H", name="Storico")
        WorkOrder.objects.create(asset=asset, title="fatto", status=WorkOrder.STATUS_DONE, opened_at=now, closed_at=now)

    def test_storico_conta_sui_queryset_e_porta_alla_stessa_origine(self):
        response = self.client.get(reverse("assets:maintenance_history"))
        self.assertEqual(response.context["history_workorder_count"], 1)
        link = response.context["history_kpi_links"]["workorders"]
        self.assertIn("source=workorders", link)
        self.assertEqual(self.client.get(link).context["history_total"], 1)

    def test_scadenzario_accetta_il_filtro_piani_dei_kpi(self):
        from assets.models import MaintenanceInterventionTemplate, MaintenanceOccurrence

        asset = Asset.objects.get(asset_tag="K3-H")
        today = timezone.localdate()
        ordinaria = MaintenanceInterventionTemplate.objects.create(code="k3-ord", label="Ingrassaggio K3")
        amministrativa = MaintenanceInterventionTemplate.objects.create(
            code="k3-adm", label="Revisione K3", maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE
        )
        MaintenanceOccurrence.objects.create(plan=ordinaria, asset=asset, due_date=today - timedelta(days=3))
        MaintenanceOccurrence.objects.create(plan=amministrativa, asset=asset, due_date=today - timedelta(days=3))
        response = self.client.get(f"{reverse('assets:maintenance_scadenze')}?plan_type=piani&window=overdue")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["plan_type"], "piani")
        self.assertEqual([row["occurrence"].plan_id for row in response.context["rows"]], [ordinaria.id])

    def test_impostazioni_tessere_cliccabili(self):
        response = self.client.get(reverse("assets:gestione_admin"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="kpi kpi-link" href="/assets/lista/?status=IN_USE"')
        self.assertEqual(self._asset_count("status=IN_USE"), response.context["assets_by_status"].get("IN_USE", 0))
        self.assertEqual(self._wo_count("view=all"), response.context["total_wo"])


class DashboardTicketManKpiTests(_AdminClientMixin, TestCase):
    """Tessere sui ticket di manutenzione del cruscotto: aprono «Gestione ticket»
    filtrata sulle stesse righe (registro, famiglia, chiusura, urgenza)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from decimal import Decimal

        from tickets.models import PrioritaTicket, StatoTicket, Ticket, TipoTicket

        cls.cat = AssetCategory.objects.create(code="kpi7-fam", label="Famiglia KPI7")
        cls.other = AssetCategory.objects.create(code="kpi7-altra", label="Altra KPI7")
        a1 = Asset.objects.create(asset_tag="K7-A1", name="A1", asset_category=cls.cat)
        a2 = Asset.objects.create(asset_tag="K7-A2", name="A2", asset_category=cls.other)
        old = Asset.objects.create(asset_tag="K7-OLD", name="Old", status=Asset.STATUS_RETIRED, asset_category=cls.cat)
        now = timezone.now()

        def ticket(titolo, **extra):
            data = {"tipo": TipoTicket.MAN, "descrizione": "x", "categoria": "ALTRO", "richiedente_nome": "Mario Rossi",
                    "priorita": PrioritaTicket.MEDIA, "stato": StatoTicket.APERTA}
            data.update(extra)
            return Ticket.objects.create(titolo=titolo, **data)

        ticket("aperto famiglia", asset=a1)
        ticket("in carico famiglia urgente", asset=a1, stato=StatoTicket.IN_CARICO, priorita=PrioritaTicket.ALTA)
        ticket("aperto altra famiglia", asset=a2)
        ticket("aperto su dismesso", asset=old)
        ticket("aperto senza asset, sicurezza", incide_sicurezza=True)
        ticket("aperto fuori registro", asset=a1, include_in_maintenance_register=False,
               priorita=PrioritaTicket.URGENTE)
        ticket("chiuso nel mese", asset=a1, stato=StatoTicket.CHIUSO, closed_at=now, ore_fermo_macchina=Decimal("2.5"))
        ticket("risolto nel mese altra", asset=a2, stato=StatoTicket.RISOLTO, closed_at=now)
        ticket("chiuso mesi fa", asset=a1, stato=StatoTicket.CHIUSO, closed_at=now - timedelta(days=70))
        ticket("annullato nel mese", asset=a1, stato=StatoTicket.ANNULLATO, closed_at=now)
        ticket("IT urgente", tipo=TipoTicket.IT, priorita=PrioritaTicket.URGENTE)

    def setUp(self):
        super().setUp()
        # Il superuser di test non ha il ruolo di gestore ticket: qui interessa il conteggio.
        patcher = mock.patch("tickets.views._can_manage_tickets", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _ticket_count(self, query: str) -> int:
        response = self.client.get(f"{reverse('tickets:gestione_list')}?{query}")
        self.assertEqual(response.status_code, 200)
        return response.context["tickets_lista"].count()

    def _mese(self) -> str:
        today = timezone.localdate()
        first = today.replace(day=1)
        last = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        return f"chiusi_dal={first.isoformat()}&chiusi_al={last.isoformat()}"

    def test_kpi_per_famiglia_e_elenco_ticket(self):
        for family, attesi in ((self.cat.id, (2, 1)), (None, (3, 2))):
            url = reverse("assets:asset_dashboard") + (f"?family={family}" if family else "")
            response = self.client.get(url)
            fk = response.context["family_kpis"]
            fam = f"&famiglia={family}" if family else ""
            self.assertEqual((fk["ticket_man_aperti_famiglia"], fk["ticket_man_chiusi_mese_famiglia"]), attesi)
            self.assertEqual(self._ticket_count(f"tipo=MAN&vista=fare&registro=asset{fam}"),
                             fk["ticket_man_aperti_famiglia"])
            self.assertEqual(self._ticket_count(f"tipo=MAN&vista=chiusi&registro=asset&{self._mese()}{fam}"),
                             fk["ticket_man_chiusi_mese_famiglia"])
            fam_html = fam.replace("&", "&amp;")
            self.assertContains(response, f"?tipo=MAN&amp;vista=fare&amp;registro=asset{fam_html}\"")
            self.assertContains(
                response,
                f"?tipo=MAN&amp;vista=chiusi&amp;registro=asset&amp;{self._mese().replace('&', '&amp;')}{fam_html}\"",
            )

    def test_segnalazioni_e_elenco_ticket(self):
        response = self.client.get(reverse("assets:asset_dashboard"))
        seg = response.context["segnalazioni"]
        self.assertEqual((seg["open_total"], seg["urgenti"], seg["nuove"]), (5, 2, 4))
        self.assertEqual(self._ticket_count("tipo=MAN&vista=fare&registro=1"), seg["open_total"])
        self.assertEqual(self._ticket_count("tipo=MAN&vista=fare&registro=1&urgenza=1"), seg["urgenti"])
        self.assertEqual(self._ticket_count("tipo=MAN&stato=APERTA&registro=1"), seg["nuove"])
        self.assertEqual(self._ticket_count("tipo=MAN&stato=IN_CARICO&registro=1"), seg["in_carico"])
        self.assertContains(response, "?tipo=MAN&amp;vista=fare&amp;registro=1&amp;urgenza=1")
        self.assertNotContains(response, "?tipo=MAN&stato=")

    def test_filtri_non_validi_ignorati_e_etichette(self):
        tutti = self._ticket_count("tipo=MAN&vista=fare")
        self.assertEqual(self._ticket_count("tipo=MAN&vista=fare&registro=boh&famiglia=abc&chiusi_dal=31-12&urgenza=si"),
                         tutti)
        response = self.client.get(f"{reverse('tickets:gestione_list')}?tipo=MAN&registro=asset&famiglia={self.cat.id}")
        self.assertIn("famiglia Famiglia KPI7", response.context["filtri_cruscotto"])
        self.assertContains(response, "data-filtri-cruscotto")


class DashboardScadenzarioKpiTests(_AdminClientMixin, TestCase):
    """KPI scadenze del cruscotto = righe dello Scadenzario che aprono (occorrenze,
    scadenze amministrative, verifiche impianti e piani periodici non convertiti)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from assets.models import (
            AssetAdministrativeDeadline,
            MaintenanceInterventionTemplate,
            MaintenanceOccurrence,
            PeriodicVerification,
        )

        today = timezone.localdate()
        cls.fire = AssetCategory.objects.filter(code="antincendio").first() or AssetCategory.objects.create(
            code="antincendio", label="Antincendio"
        )
        cls.fire_child = AssetCategory.objects.create(code="kpi7-estintori", label="Estintori KPI7", parent=cls.fire)
        a1 = Asset.objects.create(asset_tag="K7-SC1", name="Pressa", reparto="Officina KPI7")
        a2 = Asset.objects.create(asset_tag="K7-SC2", name="Estintore", asset_category=cls.fire)
        a3 = Asset.objects.create(asset_tag="K7-SC3", name="Estintore figlio", asset_category=cls.fire_child)
        a4 = Asset.objects.create(asset_tag="K7-SC4", name="Estintore dismesso", asset_category=cls.fire,
                                  status=Asset.STATUS_RETIRED)
        ordinaria = MaintenanceInterventionTemplate.objects.create(code="k7-ord", label="Ingrassaggio K7")
        amministrativa = MaintenanceInterventionTemplate.objects.create(
            code="k7-adm", label="Revisione K7", maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE
        )
        for giorni in (-10, -2, 5, 20, 60):
            MaintenanceOccurrence.objects.create(plan=ordinaria, asset=a1, due_date=today + timedelta(days=giorni))
        MaintenanceOccurrence.objects.create(plan=ordinaria, asset=a1, due_date=today - timedelta(days=4),
                                             status=MaintenanceOccurrence.STATUS_DONE, completed_on=today)
        MaintenanceOccurrence.objects.create(plan=amministrativa, asset=a1, due_date=today - timedelta(days=1))
        MaintenanceOccurrence.objects.create(plan=amministrativa, asset=a1, due_date=today + timedelta(days=80))
        for asset, giorni in ((a2, -7), (a2, 12), (a3, -3), (a4, -30), (a1, 45)):
            AssetAdministrativeDeadline.objects.create(
                asset=asset, title=f"Scadenza {asset.asset_tag} {giorni}", due_date=today + timedelta(days=giorni)
            )
        PeriodicVerification.objects.create(name="Piano non convertito scaduto",
                                            next_verification_date=today - timedelta(days=6))
        PeriodicVerification.objects.create(name="Piano non convertito vicino",
                                            next_verification_date=today + timedelta(days=9))
        PeriodicVerification.objects.create(name="Piano convertito", next_verification_date=today - timedelta(days=6),
                                            is_legacy=True)

    def _scadenzario(self, query: str) -> int:
        response = self.client.get(f"{reverse('assets:maintenance_scadenze')}?{query}")
        self.assertEqual(response.status_code, 200)
        return response.context["total"]

    def test_kpi_e_scadenzario_contano_uguale(self):
        response = self.client.get(reverse("assets:asset_dashboard"))
        kpis, dd = response.context["kpis"], response.context["dash_deadlines"]
        fire = response.context["fire_safety_kpis"]
        attesi = {
            "reparto=&plan_type=ordinary&window=overdue": (dd["maintenance_overdue"], 2),
            "reparto=&plan_type=ordinary&window=30": (dd["maintenance_due_soon"], 2),
            # L'estintore dismesso (a4, -30) non conta: ne' nel KPI ne' nello Scadenzario.
            "reparto=&plan_type=administrative&window=overdue": (kpis["scadenze_scadute"], 3),
            "reparto=&plan_type=administrative&window=30": (kpis["scadenze_30gg"], 1),
            "reparto=&plan_type=administrative&window=90": (kpis["scadenze_90gg"], 3),
            "reparto=&plan_type=piani&window=overdue": (kpis["verifiche_scadute"], 3),
            "reparto=&plan_type=piani&window=30": (kpis["verifiche_30gg"], 3),
            "reparto=&window=overdue": (dd["overdue"], 6),
            "reparto=&window=30": (dd["due_soon"], 4),
            f"reparto=&plan_type=administrative&window=overdue&category={self.fire.id}":
                (fire["antincendio_scadenze_scadute"], 2),
            f"reparto=&plan_type=administrative&window=30&category={self.fire.id}":
                (fire["antincendio_scadenze_30gg"], 1),
        }
        for query, (kpi, atteso) in attesi.items():
            with self.subTest(query=query):
                self.assertEqual(kpi, atteso)
                self.assertEqual(self._scadenzario(query), kpi)
        html = response.content.decode()
        for query in ("reparto=&amp;plan_type=ordinary&amp;window=overdue",
                      "reparto=&amp;plan_type=administrative&amp;window=overdue",
                      "reparto=&amp;plan_type=piani&amp;window=30", "reparto=&amp;window=overdue"):
            self.assertIn("?" + query, html)

    def test_caporeparto_il_link_non_restringe_al_suo_reparto(self):
        # Senza ``reparto=`` lo Scadenzario si preimposta sui reparti guidati: il KPI no.
        with mock.patch("assets.views_maintenance.user_reparti", return_value=["Officina KPI7"]):
            response = self.client.get(reverse("assets:asset_dashboard"))
            kpi = response.context["kpis"]["scadenze_scadute"]
            self.assertEqual(self._scadenzario("reparto=&plan_type=administrative&window=overdue"), kpi)
            self.assertLess(self._scadenzario("plan_type=administrative&window=overdue"), kpi)

    def test_ambito_ristretto_vale_anche_per_scadenze_e_verifiche(self):
        visibili = set(Asset.objects.filter(asset_tag="K7-SC2").values_list("id", flat=True))
        with mock.patch("assets.views_maintenance.ids_visibili", return_value=visibili), \
                mock.patch("assets.views_maintenance.filtra_per_asset",
                           side_effect=lambda request, qs, modulo=None: qs.filter(asset_id__in=visibili)):
            self.assertEqual(self._scadenzario("reparto=&plan_type=administrative&window=overdue"), 1)
            self.assertEqual(self._scadenzario("reparto=&plan_type=piani&window=overdue"), 0)
