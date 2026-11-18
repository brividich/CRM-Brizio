"""Tessere KPI cliccabili: ogni contatore porta alla lista filtrata che conta lo stesso numero."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Attrezzatura,
    AttrezzaturaStato,
    AttrezzaturaTask,
    AttrezzaturaTaskStato,
    AttrezzaturaTaskTipo,
    DisponibilitaStato,
)
from .views import _dashboard_counters

User = get_user_model()


class AttrezzatureKpiLinkTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser(username="kpi-admin", password="x"))
        oggi = timezone.localdate()
        ieri = oggi - timedelta(days=1)
        Attrezzatura.objects.create(codice="A1", part_number="PN1", stato=AttrezzaturaStato.IN_CORSO,
                                    data_consegna_prevista=ieri)
        Attrezzatura.objects.create(codice="A2", part_number="PN2", stato=AttrezzaturaStato.READY_FOR_PRODUCTION,
                                    data_consegna_prevista=ieri)
        Attrezzatura.objects.create(codice="A3", part_number="PN3", stato=AttrezzaturaStato.PRONTA_PRODUZIONE)
        Attrezzatura.objects.create(codice="A4", part_number="PN4", stato=AttrezzaturaStato.CLOSED,
                                    data_consegna_prevista=ieri)
        Attrezzatura.objects.create(codice="A5", part_number="PN5", disponibilita_stato=DisponibilitaStato.NON_DISPONIBILE)
        AttrezzaturaTask.objects.create(titolo="T1", tipo=AttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA,
                                        stato=AttrezzaturaTaskStato.APERTA, scadenza=ieri)
        AttrezzaturaTask.objects.create(titolo="T2", tipo=AttrezzaturaTaskTipo.CREAZIONE_ATTREZZO,
                                        stato=AttrezzaturaTaskStato.BLOCCATA)
        # Annullata e scaduta: non è una task «scaduta» (prima la lista la contava, la tessera no).
        AttrezzaturaTask.objects.create(titolo="T3", tipo=AttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA,
                                        stato=AttrezzaturaTaskStato.ANNULLATA, scadenza=ieri)

    def _count(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.context["page"].paginator.count

    def test_tessere_hanno_href_e_destinazione_conta_lo_stesso_numero(self):
        counters = _dashboard_counters()
        lista, tasks = reverse("attrezzature:list"), reverse("attrezzature:task_list")
        attese = {
            "totali": lista,
            "in_corso": f"{lista}?stato=in_corso",
            "non_disponibili": f"{lista}?disponibilita_stato=non_disponibile",
            "in_ritardo": f"{lista}?in_ritardo=1",
            "pronte_produzione": f"{lista}?ready=1",
            "task_aperte": f"{tasks}?aperte=1",
            "task_scadute": f"{tasks}?scadute=1",
            "verifiche_disponibilita_aperte": f"{tasks}?tipo=verifica_disponibilita&aperte=1",
            "creazioni_attrezzo_aperte": f"{tasks}?tipo=creazione_attrezzo&aperte=1",
        }
        html = self.client.get(lista).content.decode()
        for chiave, url in attese.items():
            self.assertIn(f'href="{url.replace("&", "&amp;")}"', html, chiave)
            self.assertEqual(self._count(url), counters[chiave], chiave)

    def test_valori_attesi(self):
        counters = _dashboard_counters()
        # In ritardo: solo A1 (A2 pronta e A4 chiusa non sono in ritardo).
        self.assertEqual(counters["in_ritardo"], 1)
        # Pronte produzione: stato legacy + nuovo workflow.
        self.assertEqual(counters["pronte_produzione"], 2)
        self.assertEqual(counters["task_aperte"], 2)
        self.assertEqual(counters["task_scadute"], 1)
