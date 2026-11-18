"""Tessere KPI di Sistema di gestione: portano all'elenco che conta lo stesso numero. Dati sintetici."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import Audit, Auditor, Certificazione, CicloAudit, Processo


class KpiLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user("kpi_sg", password="x", is_superuser=True)
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.client.force_login(self.admin)
        self.lead = Auditor.objects.create(user=User.objects.create_user("kpi_lead", password="x"), interno=True)
        Auditor.objects.create(user=User.objects.create_user("kpi_off", password="x"), interno=True, attivo=False)
        self.anno = timezone.localdate().year
        for i, stato in enumerate((Audit.STATO_PIANIFICATO, Audit.STATO_CHIUSO, Audit.STATO_ANNULLATO)):
            Audit.objects.create(numero=f"KPI-{i}", lead_auditor=self.lead, processi="Qualità", punti_norma="9.2",
                                 data_inizio=date(self.anno, 3, 1 + i), stato=stato, created_by=self.admin)

    def test_audit_interni_filtrano_l_elenco(self):
        url = reverse("sistema_gestione:audit_index")
        r = self.client.get(url, {"anno": self.anno})
        self.assertContains(r, f'href="{url}?anno={self.anno}&amp;stato=chiusi#sg-audit-elenco"')
        for stato, chiave in (("programmati", "audit_programmati"), ("chiusi", "audit_chiusi")):
            with self.subTest(stato=stato):
                filtrato = self.client.get(url, {"anno": self.anno, "stato": stato})
                self.assertEqual(len(filtrato.context["audit_list"]), r.context[chiave])
        self.assertEqual((r.context["audit_programmati"], r.context["audit_chiusi"]), (2, 1))
        attivi = self.client.get(reverse("sistema_gestione:auditor_elenco"), {"attivi": "1"}).context["auditor_list"]
        self.assertEqual(len(attivi), r.context["auditor_attivi"])

    def test_esterni_in_vigore_esclude_i_scaduti_ancora_attivi(self):
        oggi = timezone.localdate()
        Certificazione.objects.create(norma="EN9100", ente="E", scade_il=oggi + timedelta(days=60),
                                      prossima_sorveglianza=oggi + timedelta(days=10))
        Certificazione.objects.create(norma="ISO45001", ente="E", scade_il=oggi + timedelta(days=400))
        Certificazione.objects.create(norma="ISO9001", ente="E", scade_il=oggi - timedelta(days=2))
        Certificazione.objects.create(norma="ISO14001", ente="E", scade_il=oggi - timedelta(days=1), attiva=False)
        url = reverse("sistema_gestione:esterni_elenco")
        r = self.client.get(url)
        self.assertEqual(r.context["n_in_vigore"], 2)
        self.assertEqual(len(self.client.get(url, {"filtro": "in_vigore"}).context["certificazioni"]), 2)
        self.assertEqual(len(self.client.get(url, {"filtro": "scadenza"}).context["certificazioni"]),
                         len(r.context["scadenze"]["certificati"]))
        self.assertEqual(len(self.client.get(url, {"filtro": "sorveglianza"}).context["certificazioni"]),
                         len(r.context["scadenze"]["sorveglianze"]))
        self.assertContains(r, f'href="{url}?filtro=in_vigore#sg-certificazioni"')

    def test_ciclo_filtra_la_copertura(self):
        Processo.objects.create(codice="KPI-P1", nome="Senza audit", punti_9100="8.1")
        ciclo = CicloAudit.objects.create(nome="Ciclo KPI", anno_inizio=self.anno, anno_fine=self.anno + 2)
        url = reverse("sistema_gestione:programma_ciclo", args=[ciclo.pk])
        r = self.client.get(url)
        cop = r.context["copertura"]
        self.assertEqual(len(self.client.get(url, {"filtro": "senza_audit"}).context["righe"]), cop["processi_scoperti"])
        righe = self.client.get(url, {"filtro": "clausole"}).context["righe"]
        self.assertEqual(sum(len(x["clausole_scoperte"]) for x in righe), cop["clausole_scoperte"])
        self.assertContains(r, "?filtro=senza_audit#sg-copertura")

    def test_cruscotto_tessere_cliccabili(self):
        r = self.client.get(reverse("sistema_gestione:audit_cruscotto"), {"anno": self.anno})
        self.assertContains(r, 'href="#sg-rilievi-processo"')
        self.assertContains(r, 'id="sg-rilievi-processo"')
