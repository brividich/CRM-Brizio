"""Test della reportistica componibile (modelli a blocchi, sezioni, PDF/Excel, archivio).

Persone sintetiche: si sostituisce ``carica_dipendenti`` (che legge la tabella
legacy) con una lista costruita qui, cosi' i calcoli sono verificabili a mano.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import ReportBlocco, ReportGenerato, ReportModello
from anagrafica.reportistica import motore
from anagrafica.reportistica import sezioni as catalogo
from anagrafica.reportistica.dati import Contesto, Dipendente, Perimetro, periodo_da_tipo
from anagrafica.reportistica.predefiniti import MODELLI, crea_predefiniti

User = get_user_model()
OGGI = timezone.localdate()


def _persone() -> list[Dipendente]:
    return [
        Dipendente(id=901, nominativo="ROSSI ANNA", matricola="11", reparto="Produzione", area="Linea A",
                   mansione="Saldatore", contratto="INDETERMINATO", contratto_label="Tempo indeterminato",
                   livello="3", data_assunzione=OGGI - timedelta(days=4000), data_nascita=date(1985, 5, 1), genere="F"),
        Dipendente(id=902, nominativo="BIANCHI LUCA", matricola="12", reparto="Produzione", area="Linea A",
                   mansione="Operaio", contratto="DETERMINATO", contratto_label="Tempo determinato",
                   livello="2", data_assunzione=OGGI - timedelta(days=30), data_nascita=date(1999, 1, 1), genere="M"),
        Dipendente(id=903, nominativo="VERDI GIULIA", matricola="13", reparto="Qualità", area="Laboratorio",
                   mansione="Tecnico", contratto="INDETERMINATO", contratto_label="Tempo indeterminato",
                   livello="5", data_assunzione=OGGI - timedelta(days=2000), genere="F"),
        Dipendente(id=904, nominativo="NERI PAOLO", matricola="14", reparto="Produzione", area="Linea A",
                   mansione="Saldatore", contratto="INDETERMINATO", contratto_label="Tempo indeterminato",
                   livello="3", data_assunzione=OGGI - timedelta(days=3000),
                   data_cessazione=OGGI - timedelta(days=10), genere="M"),
    ]


class _ConPersone(TestCase):
    def setUp(self):
        super().setUp()
        for target in ("anagrafica.reportistica.dati.carica_dipendenti",
                       "anagrafica.reportistica.forms.carica_dipendenti"):
            p = patch(target, side_effect=_persone)
            p.start()
            self.addCleanup(p.stop)

    def ctx(self, **perimetro) -> Contesto:
        return Contesto(date_from=OGGI - timedelta(days=365), date_to=OGGI,
                        perimetro=Perimetro.from_dict(perimetro), today=OGGI)


class TestoMarkdownTest(TestCase):
    def test_paragrafi_titoli_elenchi_grassetto(self):
        pars = motore.paragrafi("## Titolo\nriga uno\nriga due\n\n- voce **forte**\n- altra")
        self.assertEqual(pars[0], ("h", "Titolo"))
        self.assertEqual(pars[1], ("p", "riga uno<br/>riga due"))
        self.assertEqual(pars[2], ("li", "voce <b>forte</b>"))
        self.assertEqual(pars[3], ("li", "altra"))

    def test_html_utente_sempre_escapato(self):
        pars = motore.paragrafi('<script>alert(1)</script> & **<i>x</i>**')
        markup = pars[0][1]
        self.assertNotIn("<script>", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertIn("<b>&lt;i&gt;x&lt;/i&gt;</b>", markup)


class PeriodoTest(TestCase):
    def test_tipi_di_periodo(self):
        oggi = date(2026, 2, 15)
        self.assertEqual(periodo_da_tipo("ANNO_CORRENTE", oggi=oggi), (date(2026, 1, 1), oggi))
        self.assertEqual(periodo_da_tipo("ANNO_PRECEDENTE", oggi=oggi), (date(2025, 1, 1), date(2025, 12, 31)))
        self.assertEqual(periodo_da_tipo("TRIMESTRE_PRECEDENTE", oggi=oggi), (date(2025, 10, 1), date(2025, 12, 31)))
        self.assertEqual(periodo_da_tipo("MESE_PRECEDENTE", oggi=oggi), (date(2026, 1, 1), date(2026, 1, 31)))
        self.assertEqual(
            periodo_da_tipo("PERSONALIZZATO", oggi=oggi, data_da=date(2026, 2, 1), data_a=date(2025, 3, 1)),
            (date(2025, 3, 1), date(2026, 2, 1)),
        )
        # Personalizzato senza date: ripiega sugli ultimi 12 mesi.
        self.assertEqual(periodo_da_tipo("PERSONALIZZATO", oggi=oggi), (oggi - timedelta(days=365), oggi))

    def test_perimetro_robusto_a_json_sporco(self):
        p = Perimetro.from_dict({"reparti": "non-lista", "persone": ["3", "x", 3, None], "includi_cessati": 1})
        self.assertEqual(p.reparti, [])
        self.assertEqual(p.persone, [3])
        self.assertTrue(p.includi_cessati)
        self.assertEqual(Perimetro.from_dict(None).as_dict()["persone"], [])


class SezioniTest(_ConPersone):
    def test_catalogo_chiavi_uniche_e_report_conformita_inclusi(self):
        chiavi = [s.key for s in catalogo.catalogo()]
        self.assertEqual(len(chiavi), len(set(chiavi)))
        self.assertIn("rc:dpi", chiavi)
        self.assertIn("pdr125_indicatori", chiavi)

    def test_ogni_sezione_si_calcola(self):
        ctx = self.ctx()
        for sezione in catalogo.catalogo():
            with self.subTest(sezione=sezione.key):
                res = sezione.builder(ctx)
                self.assertIsInstance(res, catalogo.Risultato)
                self.assertEqual(len(res.righe), len(res.toni))

    def test_predefiniti_usano_sezioni_esistenti(self):
        for spec in MODELLI:
            for b in spec["blocchi"]:
                if b["tipo"] == "SEZIONE":
                    self.assertIsNotNone(catalogo.get(b["sezione"]), b["sezione"])

    def test_perimetro_esclude_cessati_e_filtra(self):
        ctx = self.ctx()
        self.assertEqual({d.id for d in ctx.dipendenti()}, {901, 902, 903})
        self.assertEqual({d.id for d in self.ctx(includi_cessati=True).dipendenti()}, {901, 902, 903, 904})
        self.assertEqual({d.id for d in self.ctx(reparti=["produzione"]).dipendenti()}, {901, 902})
        self.assertEqual({d.id for d in self.ctx(mansioni=["Saldatore"], includi_cessati=True).dipendenti()}, {901, 904})
        self.assertEqual({d.id for d in self.ctx(persone=[903]).dipendenti()}, {903})

    def test_organico_movimenti_e_turnover(self):
        res = catalogo.get("organico_indicatori").builder(self.ctx())
        kpi = {k.label: k.value for k in res.kpis}
        self.assertEqual(kpi["Persone in forza"], 3)
        self.assertEqual(kpi["Assunzioni nel periodo"], 1)
        self.assertEqual(kpi["Cessazioni nel periodo"], 1)
        # Organico a inizio periodo 3 (901, 903, 904), a fine periodo 3 (901, 902, 903): medio 3.
        self.assertEqual(kpi["Turnover in uscita"], "33%")
        self.assertTrue(all(set(r) == {"dimensione", "voce", "n", "pct"} for r in res.righe))

    def test_parita_genere_solo_aggregati(self):
        res = catalogo.get("pdr125_indicatori").builder(self.ctx())
        kpi = {k.label: k.value for k in res.kpis}
        self.assertEqual(kpi["Donne in organico"], "67%")
        self.assertEqual(kpi["Genere non registrato"], 0)
        organico = next(r for r in res.righe if r["indicatore"] == "Persone in forza")
        self.assertEqual((organico["donne"], organico["uomini"], organico["totale"]), (2, 1, 3))
        nomi = {d.nominativo for d in _persone()}
        for riga in res.righe:
            self.assertFalse(nomi & {str(v) for v in riga.values()}, "nessun nominativo nella sezione PdR 125")

    def test_colonne_scelte_e_predefinite(self):
        sezione = catalogo.get("personale_elenco")
        self.assertEqual(sezione.colonne_effettive([]), list(sezione.predefinite))
        self.assertEqual(sezione.colonne_effettive(["mansione", "nominativo", "inventata"]), ["nominativo", "mansione"])


class PredefinitiTest(TestCase):
    def test_migrazione_li_crea_e_il_ripristino_e_idempotente(self):
        codici = {m["codice_sistema"] for m in MODELLI}
        self.assertEqual(set(ReportModello.objects.exclude(codice_sistema="").values_list("codice_sistema", flat=True)), codici)
        self.assertEqual(crea_predefiniti(ReportModello, ReportBlocco), 0)
        ReportModello.objects.filter(codice_sistema="parita_genere_pdr125").delete()
        self.assertEqual(crea_predefiniti(ReportModello, ReportBlocco), 1)


class VisteTest(_ConPersone):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("rp_admin", "rp_admin@example.com", "x")
        self.modello = ReportModello.objects.get(codice_sistema="personale_cliente")

    def test_utente_senza_permessi_respinto(self):
        utente = User.objects.create_user(username="rp_nessuno", password="x")
        self.client.force_login(utente)
        for url in (reverse("anagrafica:reportistica_index"),
                    reverse("anagrafica:reportistica_genera", args=[self.modello.pk]),
                    reverse("anagrafica:reportistica_modello_edit", args=[self.modello.pk])):
            with self.subTest(url=url):
                self.assertNotEqual(self.client.get(url).status_code, 200)

    def test_index_editor_e_anteprima(self):
        self.client.force_login(self.admin)
        index = self.client.get(reverse("anagrafica:reportistica_index"))
        self.assertContains(index, "Qualifica del personale per cliente")
        editor = self.client.get(reverse("anagrafica:reportistica_modello_edit", args=[self.modello.pk]))
        self.assertContains(editor, 'id="rp-tpl"')
        self.assertContains(editor, "personale_qualifiche")
        genera = self.client.get(reverse("anagrafica:reportistica_genera", args=[self.modello.pk]))
        self.assertContains(genera, "ROSSI ANNA")
        self.assertContains(genera, "dati personali nominativi")
        for page in (index, editor, genera):
            self.assertNotContains(page, "{#")

    def _post_genera(self, azione: str, **extra):
        dati = {"titolo": "Qualifica personale", "destinatario": "Cliente Demo S.p.A.",
                "periodo_tipo": "ULTIMI_12_MESI", "azione": azione, **extra}
        return self.client.post(reverse("anagrafica:reportistica_genera", args=[self.modello.pk]), dati)

    def test_pdf_ed_excel_archiviati_e_tracciati(self):
        from core.models import AuditLog

        self.client.force_login(self.admin)
        pdf = self._post_genera("pdf", note_archivio="inviato via PEC")
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        xlsx = self._post_genera("xlsx")
        self.assertTrue(xlsx.content.startswith(b"PK"))
        archivio = list(ReportGenerato.objects.filter(modello=self.modello).order_by("id"))
        self.assertEqual([a.formato for a in archivio], ["pdf", "xlsx"])
        self.assertEqual(archivio[0].note, "inviato via PEC")
        self.assertTrue(archivio[0].contiene_dati_personali)
        self.assertEqual(archivio[0].destinatario, "Cliente Demo S.p.A.")
        self.assertIn("personale_qualifiche", archivio[0].parametri["sezioni"])
        self.assertEqual(
            AuditLog.objects.filter(azione="reportistica_genera", oggetto_id=str(archivio[0].pk)).count(), 1,
        )
        copia = self.client.get(reverse("anagrafica:reportistica_archivio_download", args=[archivio[0].pk]))
        self.assertEqual(copia.content, pdf.content)

    def test_testo_non_inviato_resta_quello_del_modello(self):
        self.client.force_login(self.admin)
        resp = self._post_genera("anteprima")
        self.assertContains(resp, "trasmettiamo l'evidenza della competenza")

    def test_testi_al_volo_e_salvataggio_nel_modello(self):
        self.client.force_login(self.admin)
        blocco = self.modello.blocchi.filter(tipo="TESTO").first()
        resp = self._post_genera("anteprima", **{f"testo_{blocco.pk}": "Testo per {{destinatario}}"})
        self.assertContains(resp, "Testo per Cliente Demo S.p.A.")
        blocco.refresh_from_db()
        self.assertNotEqual(blocco.testo, "Testo per {{destinatario}}")
        self._post_genera("anteprima", salva_nel_modello="on", **{f"testo_{blocco.pk}": "Nuovo testo"})
        blocco.refresh_from_db()
        self.modello.refresh_from_db()
        self.assertEqual(blocco.testo, "Nuovo testo")
        self.assertEqual(self.modello.destinatario, "Cliente Demo S.p.A.")

    def test_sezione_senza_permesso_omessa_e_archivio_negato(self):
        self.client.force_login(self.admin)
        modello = ReportModello.objects.get(codice_sistema="sicurezza_45001")
        self.client.post(reverse("anagrafica:reportistica_genera", args=[modello.pk]),
                         {"titolo": "SSL", "periodo_tipo": "ULTIMI_12_MESI", "azione": "pdf"})
        doc = ReportGenerato.objects.get(modello=modello)
        self.assertIn("sicurezza_sorveglianza", doc.parametri["sezioni"])

        # Chi non ha il permesso sulle visite mediche: sezione omessa, copia archiviata negata.
        senza_visite = lambda self, request: self.key != "sicurezza_sorveglianza"  # noqa: E731
        with patch.object(catalogo.Sezione, "consentita", senza_visite):
            pagina = self.client.get(reverse("anagrafica:reportistica_genera", args=[modello.pk]))
            self.assertContains(pagina, "Sezione omessa")
            negato = self.client.get(reverse("anagrafica:reportistica_archivio_download", args=[doc.pk]))
            self.assertEqual(negato.status_code, 302)

    def test_sorveglianza_richiede_permesso_visite(self):
        sezione = catalogo.get("sicurezza_sorveglianza")
        richiesta = type("R", (), {"user": None})()
        with patch("anagrafica.reportistica.permessi.has_perm", side_effect=lambda req, code: code != "anagrafica.visite.view"):
            self.assertFalse(sezione.consentita(richiesta))
        with patch("anagrafica.reportistica.permessi.has_perm", return_value=True):
            self.assertTrue(sezione.consentita(richiesta))

    def test_editor_crea_modello_con_blocchi_ordinati(self):
        self.client.force_login(self.admin)
        dati = {
            "nome": "Elenco per Cliente X", "titolo_documento": "Personale commessa", "riservatezza": "DATI_PERSONALI",
            "periodo_tipo": "ANNO_CORRENTE", "norme": ["ISO 9001", "UNI/PdR 125:2022"], "persone": ["901", "903"],
            "blocchi-TOTAL_FORMS": "3", "blocchi-INITIAL_FORMS": "0",
            "blocchi-MIN_NUM_FORMS": "0", "blocchi-MAX_NUM_FORMS": "1000",
            "blocchi-0-tipo": "SEZIONE", "blocchi-0-ordine": "20", "blocchi-0-sezione": "personale_elenco",
            "blocchi-0-colonne": ["personale_elenco:nominativo", "personale_elenco:mansione", "personale_qualifiche:stato"],
            "blocchi-0-mostra_tabella": "on",
            "blocchi-1-tipo": "TESTO", "blocchi-1-ordine": "10", "blocchi-1-testo": "Premessa",
            "blocchi-2-tipo": "TESTO", "blocchi-2-ordine": "30", "blocchi-2-testo": "", "blocchi-2-DELETE": "on",
            "dopo": "resta",
        }
        resp = self.client.post(reverse("anagrafica:reportistica_modello_create"), dati)
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context["form"].errors)
        m = ReportModello.objects.get(nome="Elenco per Cliente X")
        self.assertEqual(m.norme, ["ISO 9001", "UNI/PdR 125:2022"])
        self.assertEqual(m.filtri["persone"], [901, 903])
        blocchi = list(m.blocchi.all())
        self.assertEqual([b.tipo for b in blocchi], ["TESTO", "SEZIONE"])
        self.assertEqual([b.ordine for b in blocchi], [10, 20])
        self.assertEqual(blocchi[1].opzioni["colonne"], ["nominativo", "mansione"])
        self.assertFalse(blocchi[1].opzioni["mostra_indicatori"])

        doc = motore.componi(m, motore.Parametri.dal_modello(m), type("R", (), {"user": self.admin})())
        sezione = doc.sezioni_calcolate[0]
        self.assertEqual([label for _k, label in sezione.colonne], ["Nominativo", "Mansione"])
        self.assertEqual([r[0] for r in sezione.righe], ["ROSSI ANNA", "VERDI GIULIA"])

    def test_sezione_obbligatoria_nel_blocco_sezione(self):
        self.client.force_login(self.admin)
        dati = {
            "nome": "Incompleto", "titolo_documento": "X", "riservatezza": "INTERNO", "periodo_tipo": "ULTIMI_12_MESI",
            "blocchi-TOTAL_FORMS": "1", "blocchi-INITIAL_FORMS": "0",
            "blocchi-MIN_NUM_FORMS": "0", "blocchi-MAX_NUM_FORMS": "1000",
            "blocchi-0-tipo": "SEZIONE", "blocchi-0-ordine": "10", "blocchi-0-sezione": "",
        }
        resp = self.client.post(reverse("anagrafica:reportistica_modello_create"), dati)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ReportModello.objects.filter(nome="Incompleto").exists())
        self.assertContains(resp, "Scegli la sezione dati")

    def test_duplica_ed_elimina(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("anagrafica:reportistica_modello_duplica", args=[self.modello.pk]))
        copia = ReportModello.objects.get(nome=f"{self.modello.nome} (copia)")
        self.assertEqual(copia.codice_sistema, "")
        self.assertEqual(copia.blocchi.count(), self.modello.blocchi.count())
        self.client.post(reverse("anagrafica:reportistica_modello_elimina", args=[copia.pk]))
        copia.refresh_from_db()
        self.assertFalse(copia.is_active)


class AclTest(TestCase):
    def test_binding_e_permessi(self):
        from core.models import PermissionDefinition, RoutePermissionBinding

        from anagrafica.acl_bootstrap import _REP_ROUTE_BINDINGS, _bootstrap_reportistica_canonical

        _bootstrap_reportistica_canonical()
        _bootstrap_reportistica_canonical()
        self.assertTrue(PermissionDefinition.objects.filter(code="anagrafica.reportistica.view").exists())
        for route, code in _REP_ROUTE_BINDINGS.items():
            self.assertEqual(RoutePermissionBinding.objects.filter(route_name=route).count(), 1, route)
            self.assertEqual(RoutePermissionBinding.objects.get(route_name=route).permission_id, code)
        # Ogni route della reportistica ha il suo binding (fail-closed con ACL strict).
        from anagrafica import urls

        rotte = {f"anagrafica:{p.name}" for p in urls.urlpatterns if (p.name or "").startswith("reportistica_")}
        self.assertEqual(rotte, set(_REP_ROUTE_BINDINGS))
