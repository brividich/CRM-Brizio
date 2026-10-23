"""Import CSV ticket: stato dei chiusi e automazioni silenziate.

Un import storico non deve far partire le automazioni «nuovo ticket» (mail) e
i ticket chiusi su SharePoint non devono risultare APERTA, altrimenti finiscono
nei promemoria SLA ed escalation.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from .models import StatoTicket, Ticket
from .views import _stato_da_riga, api_import_csv

User = get_user_model()

_INTESTAZIONE = (
    "Problema,Descrizione del problema,Tipologia problema,Problema registrato da,"
    "Chiuso,Data chiusura ticket,ID\n"
)


class StatoDaRigaTest(TestCase):
    def test_flag_chiuso_in_tutte_le_forme(self):
        for valore in ("1", "Sì", "si", "Vero", "TRUE", "x", "Chiuso"):
            with self.subTest(valore=valore):
                self.assertEqual(_stato_da_riga({"Chiuso": valore}), StatoTicket.CHIUSO)

    def test_data_chiusura_basta_a_chiudere(self):
        self.assertEqual(
            _stato_da_riga({"Chiuso": "", "Data chiusura ticket": "12/03/2025 10:00"}),
            StatoTicket.CHIUSO,
        )

    def test_colonna_stato_in_italiano(self):
        self.assertEqual(_stato_da_riga({"stato": "Chiusa"}), StatoTicket.CHIUSO)
        self.assertEqual(_stato_da_riga({"stato": "in carico"}), StatoTicket.IN_CARICO)

    def test_senza_indizi_resta_aperta(self):
        self.assertEqual(_stato_da_riga({"Chiuso": "No"}), StatoTicket.APERTA)
        self.assertEqual(_stato_da_riga({"Chiuso": "Falso"}), StatoTicket.APERTA)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ImportCsvTest(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("tk-imp", "tk-imp@example.local", "pass12345")
        self.factory = RequestFactory()

    def _importa(self, righe: str):
        f = SimpleUploadedFile("ticket.csv", (_INTESTAZIONE + righe).encode("utf-8"), "text/csv")
        request = self.factory.post("/tickets/api/import-csv/", {"csv_file": f, "tipo_override": "MAN"})
        request.user = self.su
        return api_import_csv(request)

    def test_chiusi_importati_chiusi_e_automazioni_silenziate(self):
        with mock.patch("tickets.views._silenzia_automazioni_import") as silenzia:
            resp = self._importa(
                "Perdita olio,Perde olio,MECCANICO,Mario Rossi,Vero,,101\n"
                "Luce rotta,Neon spento,ELETTRICO,Anna Bianchi,0,05/02/2025 09:30,102\n"
                "Porta bloccata,Non apre,MECCANICO,Anna Bianchi,0,,103\n"
            )

        self.assertEqual(resp.status_code, 200)
        stati = dict(Ticket.objects.values_list("sharepoint_item_id", "stato"))
        self.assertEqual(stati, {
            "101": StatoTicket.CHIUSO,
            "102": StatoTicket.CHIUSO,
            "103": StatoTicket.APERTA,
        })
        silenzia.assert_called_once()
        self.assertCountEqual(silenzia.call_args.args[0], list(Ticket.objects.values_list("pk", flat=True)))

    def test_export_sharepoint_vero_falso_e_priorita_rovinata(self):
        intestazione = (
            "Problema,Descrizione del problema,Tipologia problema,Problema registrato da,"
            "Chiuso,Impatto su sicurezza,Priorit�,ID\n"
        )
        f = SimpleUploadedFile("t.csv", (intestazione + (
            "Perdita olio,Perde olio,MECCANICO,Mario Rossi,Vero,Falso,Alta,301\n"
            "Porta,Non apre,MECCANICO,Anna Bianchi,Falso,Falso,Bassa,302\n"
        )).encode("utf-8"), "text/csv")
        request = self.factory.post("/tickets/api/import-csv/", {"csv_file": f, "tipo_override": "MAN"})
        request.user = self.su
        api_import_csv(request)

        t1 = Ticket.objects.get(sharepoint_item_id="301")
        t2 = Ticket.objects.get(sharepoint_item_id="302")
        self.assertEqual((t1.stato, t1.priorita, t1.incide_sicurezza), (StatoTicket.CHIUSO, "ALTA", False))
        self.assertEqual((t2.stato, t2.priorita), (StatoTicket.APERTA, "BASSA"))

    def test_coda_assente_non_rompe_import(self):
        resp = self._importa("Perdita olio,Perde olio,MECCANICO,Mario Rossi,1,,201\n")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Ticket.objects.get(sharepoint_item_id="201").stato, StatoTicket.CHIUSO)
