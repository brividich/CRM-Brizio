"""Ordini di produzione: elenco, scheda dell'OP, documenti, permessi. Tabelle legacy in SQLite, dati sintetici."""
from __future__ import annotations

from django.db import connection
from django.urls import reverse

from core.legacy_utils import legacy_table_columns
from tasks.models import FaiArticolo, FaiFase, FaiGruppo, FaiOpzione, FaiRecord, ProjectTechRef, TechRefKind
from tasks.tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, make_project

from .acl_bootstrap import PERM_DOCUMENTI, PERM_OP, PERM_VIEW
from .models import DocumentoOP, TipoDocumento


class ProduzioneBase(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        legacy_table_columns.cache_clear()
        self.addCleanup(legacy_table_columns.cache_clear)
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE ordini_produzione (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, "
                "sharepoint_item_id TEXT, part_number TEXT, capocomessa TEXT, incaricato TEXT, stato TEXT)"
            )
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY AUTOINCREMENT, ex_op_nominativo TEXT, "
                "op_lookup_id INTEGER, chiudere INTEGER)"
            )
            cur.executemany(
                "INSERT INTO ordini_produzione (title, sharepoint_item_id, part_number, capocomessa, incaricato, stato) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    ("OP/2025/900", "7", "PN-ALFA-1", "Capo Uno", "Car Uno", "Chiuso"),
                    ("OP/2026/100", "41", "PN-ALFA-1", "Capo Uno", "Car Uno", "Aperto"),
                    ("OP/2026/101", "-3", "PN-BETA-2", "Capo Due", "Car Due", "Aperto"),
                ],
            )
            cur.executemany(
                "INSERT INTO anomalie (ex_op_nominativo, op_lookup_id, chiudere) VALUES (%s, %s, %s)",
                [("OP/2026/100", 41, 0), ("OP/2026/100", 41, 1)],
            )
            cur.execute("SELECT id FROM ordini_produzione WHERE title = 'OP/2026/100'")
            self.pk = cur.fetchone()[0]
        self.admin = _create_user_with_legacy(username="prod-adm", legacy_user_id=681, role_id=1, role_name="admin")
        self.client.force_login(self.admin)
        self.tipo = TipoDocumento.objects.get(etichetta="Ciclo di lavoro")

    def tearDown(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")
            cur.execute("DROP TABLE ordini_produzione")
        super().tearDown()

    def _fai(self, op, pn="PN-ALFA-1"):
        articolo, _ = FaiArticolo.objects.get_or_create(client_name="Cliente Alfa", part_number=pn)
        return FaiRecord.objects.create(
            articolo=articolo, tipo="COMPLETO", op=op, piano_numero=f"PF-{op or 'vuoto'}",
            stato=FaiOpzione.objects.filter(gruppo=FaiGruppo.STATO, fase=FaiFase.IN_CORSO).first(),
        )


class ElencoTest(ProduzioneBase):
    def test_elenco_con_conteggi(self):
        DocumentoOP.objects.create(op="OP/2026/100", tipo=self.tipo, titolo="Ciclo 1")
        self._fai("OP/2026/100")
        pagina = self.client.get(reverse("produzione:elenco"))
        self.assertEqual(pagina.status_code, 200)
        righe = {r["op"]: r for r in pagina.context["pagina"]}
        self.assertEqual(list(righe), ["OP/2026/101", "OP/2026/100", "OP/2025/900"])
        r = righe["OP/2026/100"]
        self.assertEqual((r["n_documenti"], r["n_fai"], r["n_anomalie_aperte"]), (1, 1, 1))

    def test_ricerca_e_stato(self):
        pagina = self.client.get(reverse("produzione:elenco"), {"q": "alfa", "stato": "Aperto"})
        self.assertEqual([r["op"] for r in pagina.context["pagina"]], ["OP/2026/100"])

    def test_senza_tabella_avvisa(self):
        with connection.cursor() as cur:
            cur.execute("ALTER TABLE ordini_produzione RENAME TO op_altrove")
        legacy_table_columns.cache_clear()
        try:
            self.assertContains(self.client.get(reverse("produzione:elenco")), "L'elenco degli OP non è disponibile")
        finally:
            with connection.cursor() as cur:
                cur.execute("ALTER TABLE op_altrove RENAME TO ordini_produzione")


class SchedaTest(ProduzioneBase):
    def test_scheda_raccoglie_documenti_fai_programmi_anomalie(self):
        DocumentoOP.objects.create(op="op/2026/100", tipo=self.tipo, titolo="Ciclo 1", revisione="B")
        fai_op = self._fai("OP/2026/100")
        fai_pn = self._fai("OP/2025/900")
        self._fai("OP/2026/101", pn="PN-BETA-2")
        progetto = make_project(name="Kickoff Alfa", created_by=self.admin, part_number="PN-ALFA-1")
        ProjectTechRef.objects.create(project=progetto, kind=TechRefKind.CMM, code="CMM-ALFA", created_by=self.admin)
        pagina = self.client.get(reverse("produzione:scheda", args=[self.pk]))
        self.assertEqual(pagina.status_code, 200)
        c = pagina.context
        self.assertEqual([d.titolo for d in c["documenti"]], ["Ciclo 1"])
        self.assertEqual(c["fai_op"], [fai_op])
        self.assertEqual(c["fai_pn"], [fai_pn])
        self.assertEqual([r.code for r in c["programmi"]], ["CMM-ALFA"])
        self.assertEqual(c["anomalie"], {"totale": 2, "aperte": 1})
        self.assertEqual([o["op"] for o in c["altri_op"]], ["OP/2025/900"])
        self.assertContains(pagina, "/tasks/fai/nuovo/?op=OP%2F2026%2F100&amp;pn=PN-ALFA-1")
        self.assertContains(pagina, "/gestione-anomalie?op=OP%2F2026%2F100&amp;filter=tutti")

    def test_op_inesistente_404(self):
        self.assertEqual(self.client.get(reverse("produzione:scheda", args=[9999])).status_code, 404)

    def test_nuovo_fai_precompilato_dall_op(self):
        pagina = self.client.get(reverse("tasks:fai_nuovo"), {"op": "OP/2026/100", "pn": "PN-ALFA-1"})
        self.assertContains(pagina, 'value="OP/2026/100"')
        self.assertContains(pagina, 'value="PN-ALFA-1"')
        self.assertIn(reverse("produzione:scheda", args=[self.pk]), pagina.content.decode())


class DocumentiTest(ProduzioneBase):
    def test_aggiungi_modifica_elimina(self):
        url = reverse("produzione:documento", args=[self.pk])
        risposta = self.client.post(url, {"tipo": self.tipo.pk, "titolo": "Ciclo 1", "percorso": r"\\srv\cicli\c1.pdf"})
        self.assertEqual(risposta.status_code, 302)
        doc = DocumentoOP.objects.get()
        self.assertEqual((doc.op, doc.creato_da), ("OP/2026/100", self.admin))
        self.client.post(url, {"documento": doc.pk, "tipo": self.tipo.pk, "titolo": "Ciclo 1", "revisione": "C"})
        doc.refresh_from_db()
        self.assertEqual(doc.revisione, "C")
        self.client.post(reverse("produzione:documento_elimina", args=[self.pk, doc.pk]))
        self.assertFalse(DocumentoOP.objects.exists())

    def test_percorso_non_valido_rifiutato(self):
        risposta = self.client.post(
            reverse("produzione:documento", args=[self.pk]), {"tipo": self.tipo.pk, "percorso": "javascript:alert(1)"}
        )
        self.assertEqual(risposta.status_code, 400)
        self.assertFalse(DocumentoOP.objects.exists())

    def test_documento_di_un_altro_op_non_si_tocca(self):
        altro = DocumentoOP.objects.create(op="OP/2026/101", tipo=self.tipo, titolo="Altrui")
        risposta = self.client.post(reverse("produzione:documento_elimina", args=[self.pk, altro.pk]))
        self.assertEqual(risposta.status_code, 404)

    def test_impostazioni_tipi(self):
        url = reverse("produzione:impostazioni")
        self.client.post(url, {"azione": "nuovo", "etichetta": "Programma robot", "ordine": "5"})
        tipo = TipoDocumento.objects.get(etichetta="Programma robot")
        self.client.post(url, {"azione": "salva", "id": tipo.pk, "etichetta": "Programma robot", "ordine": "5"})
        tipo.refresh_from_db()
        self.assertFalse(tipo.attivo)


class PermessiTest(ProduzioneBase):
    def _utente(self, azioni):
        from core.models import RolePermissionGrant

        from .acl_bootstrap import _bootstrap_canonical

        _ensure_role(3, "operatore")
        _bootstrap_canonical()
        for codice, attivo in azioni.items():
            RolePermissionGrant.objects.update_or_create(
                legacy_role_id=3, permission_id=codice, defaults={"enabled": attivo}
            )
        self.client.force_login(_create_user_with_legacy(username="prod-op", legacy_user_id=682, role_id=3, role_name="operatore"))

    def test_chi_vede_non_modifica(self):
        self._utente({PERM_VIEW: True, PERM_DOCUMENTI: False})
        self.assertEqual(self.client.get(reverse("produzione:elenco")).status_code, 200)
        pagina = self.client.get(reverse("produzione:scheda", args=[self.pk]))
        self.assertEqual(pagina.status_code, 200)
        self.assertNotContains(pagina, "Aggiungi documento")
        self.assertFalse(pagina.context["vede_kickoff"])
        self.assertEqual(self.client.get(reverse("produzione:impostazioni")).status_code, 403)
        risposta = self.client.post(reverse("produzione:documento", args=[self.pk]), {"tipo": self.tipo.pk})
        self.assertEqual(risposta.status_code, 403)
        self.assertFalse(DocumentoOP.objects.exists())


class NuovoOpTest(ProduzioneBase):
    """Creazione con la funzione di Gestione anomalie (qui finta: usa SQL di SQL Server)."""

    DATI = {"causale_doc": "OP", "anno": "2026", "numero": "200", "pn": "PN-GAMMA-3",
            "capocommessa": "Capo Uno", "car": "Car Uno"}

    def _finta(self, request, dati):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO ordini_produzione (title, sharepoint_item_id, part_number, capocomessa, incaricato, stato) "
                "VALUES (%s, '-9', %s, %s, %s, 'Aperto')",
                [f"{dati['causale_doc']}/{dati['anno']}/{dati['numero']}", dati["pn"], dati["capocommessa"], dati["car"]],
            )
        return {"success": True, "op": {}, "error": "", "status": 200}

    def test_crea_e_restituisce_la_scheda(self):
        from unittest.mock import patch

        with patch("anomalie.views.crea_op_da_dati", side_effect=self._finta) as crea:
            risposta = self.client.post(reverse("produzione:op_nuovo"), self.DATI, HTTP_ACCEPT="application/json")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        op = risposta.json()["op"]
        self.assertEqual((op["op"], op["pn"]), ("OP/2026/200", "PN-GAMMA-3"))
        self.assertEqual(op["url"], reverse("produzione:scheda", args=[op["id"]]))
        self.assertFalse(crea.call_args.args[1]["collaudo_benestare"])

    def test_campi_obbligatori_e_doppione(self):
        url = reverse("produzione:op_nuovo")
        errori = self.client.post(url, {"anno": "2026"}, HTTP_ACCEPT="application/json").json()["errori"]
        self.assertEqual(set(errori), {"numero", "pn", "capocommessa", "car"})
        doppio = self.client.post(url, {**self.DATI, "numero": "100"}, HTTP_ACCEPT="application/json")
        self.assertEqual(doppio.status_code, 400)
        self.assertIn("esiste già", doppio.json()["errori"]["numero"])

    def test_pannello_nell_elenco_e_nella_scheda_fai(self):
        self.assertContains(self.client.get(reverse("produzione:elenco")), "data-nuovo-op")
        self.assertContains(self.client.get(reverse("tasks:fai_nuovo")), "data-fai-nuovo-op")

    def test_senza_permesso_niente_pannello_e_403(self):
        PermessiTest._utente(self, {PERM_VIEW: True, PERM_OP: False})
        self.assertNotContains(self.client.get(reverse("produzione:elenco")), "data-nuovo-op")
        risposta = self.client.post(reverse("produzione:op_nuovo"), self.DATI, HTTP_ACCEPT="application/json")
        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(risposta["Content-Type"], "application/json")
