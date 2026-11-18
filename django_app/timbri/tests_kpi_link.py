"""Tessere KPI del registro timbri: ognuna apre l'elenco filtrato che conta lo stesso numero."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from .models import OperatoreTimbri, RegistroTimbro
from .tests import _ensure_anagrafica_table, _insert_dipendente


class TimbriKpiLinkTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="timbri-kpi-admin", email="timbri-kpi@test.local", password="pass12345"
        )
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
        id_attivo = _insert_dipendente("a.attivo", "Aldo", "Attivo", "AT001")
        id_storico = _insert_dipendente("s.storico", "Sara", "Storico", "ST001")
        _insert_dipendente("n.senza", "Nino", "Senza", "SE001")
        op_attivo = OperatoreTimbri.objects.create(legacy_anagrafica_id=id_attivo, nome="Aldo", cognome="Attivo")
        op_storico = OperatoreTimbri.objects.create(legacy_anagrafica_id=id_storico, nome="Sara", cognome="Storico")
        RegistroTimbro.objects.create(operatore=op_attivo, codice_timbro="CNO Q101", is_attivo=True)
        RegistroTimbro.objects.create(operatore=op_attivo, codice_timbro="CNO Q102", is_attivo=True)
        RegistroTimbro.objects.create(operatore=op_storico, codice_timbro="CNO Z900", is_attivo=False, is_archived=True)
        self.client.force_login(self.admin)

    def test_tessere_portano_ai_filtri_con_lo_stesso_numero(self):
        r = self.client.get(reverse("timbri:index"), {"q": "o"})
        self.assertEqual(r.status_code, 200)
        stats, urls = r.context["stats"], r.context["kpi_urls"]
        # I link conservano i filtri su cui le tessere contano.
        self.assertIn("q=o", urls["con_timbri"])
        self.assertIn("stato=con", urls["con_timbri"])
        dip = self.client.get(urls["dipendenti"])
        self.assertEqual(dip.context["page_obj"].paginator.count, stats["dipendenti"])
        con = self.client.get(urls["con_timbri"])
        self.assertEqual(con.context["page_obj"].paginator.count, stats["con_timbri"])
        self.assertEqual(stats["con_timbri"], 2)
        attivi = self.client.get(urls["record_attivi"])
        # La tessera somma i record attivi delle persone che il filtro mostra.
        self.assertEqual(sum(e["active_records"] for e in attivi.context["page_obj"].paginator.object_list),
                         stats["record_attivi"])
