"""Test di CN-SGI: scaffali, sezioni, chi vede cosa, ricerca, pagine della libreria."""
from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AccessGroup

from . import libreria as lib
from .models import (
    ProcedureDocument,
    ProcedureRevision,
    SgiAperturaGiorno,
    SgiScaffale,
    SgiSyncAction,
    SgiSyncLog,
    SgiTestoEstratto,
    SgiVisibilita,
    SourceType,
)
from .sgi_testo import separa_segni_pagina

User = get_user_model()


def _doc(code, title, cartella="9100_Qualità", sezione="2_MT", testo="", offset=None, n_pagine=None, **kw):
    doc = ProcedureDocument.objects.create(code=code, title=title, category=cartella, sezione=sezione, document_type="MT", **kw)
    rev = ProcedureRevision.objects.create(
        document=doc, revision_code="2", revision_date=date(2026, 10, 1), effective_date=date(2026, 10, 1),
        source_type=SourceType.SHAREPOINT, source_url="https://example.invalid/doc.pdf", file_name=f"{code}.pdf",
        is_current=True,
    )
    if testo:
        SgiTestoEstratto.objects.create(
            revision=rev, file_hash="x", formato="pdf", metodo="test", testo=testo,
            n_pagine=n_pagine, n_caratteri=len(testo), offset_pagine=offset or [],
        )
    return doc


class IdentitaTests(TestCase):
    def test_identita_da_cartella(self):
        self.assertEqual(lib.identita_da_cartella("9100_Qualità")["sigla"], "9100")
        self.assertEqual(lib.identita_da_cartella("9100_Qualità")["nome"], "Qualità")
        self.assertEqual(lib.identita_da_cartella("45001_Sicurezza")["colore"], "#b45309")
        self.assertEqual(lib.identita_da_cartella("_PART 145")["nome"], "PART 145")
        self.assertEqual(lib.identita_da_cartella("_Piani Qualitá")["nome"], "Piani Qualità")
        self.assertEqual(lib.identita_da_cartella("")["nome"], "Altri documenti")

    def test_etichetta_sezione(self):
        self.assertEqual(lib.etichetta_sezione("2_MT"), "MT")
        self.assertEqual(lib.etichetta_sezione("_Modelli"), "Modelli")
        self.assertEqual(lib.etichetta_sezione("Turtle Diagram"), "Turtle Diagram")
        self.assertEqual(lib.etichetta_sezione(""), "Documenti")

    def test_sezione_da_percorso(self):
        radice = r"\\novisrv\sistema gestione integrato"
        self.assertEqual(lib.sezione_da_percorso(radice + r"\9100_Qualità\2_MT\MT CN 01 Rev.2_X.pdf", radice), "2_MT")
        self.assertEqual(lib.sezione_da_percorso(radice + r"\45001_Sicurezza\MT CN 451 Rev.2_DPI.pdf", radice), "")
        self.assertEqual(lib.sezione_da_percorso(r"\\altro\share\a\b\c.pdf", radice), "")


class SegniPaginaTests(TestCase):
    def test_offset_e_testo_pulito(self):
        testo = "\u20630\u2063\n\nPrima pagina\n\n\u20631\u2063\n\nSeconda\n\n\u20632\u2063\n\nTerza"
        pulito, offset = separa_segni_pagina(testo, 3)
        self.assertNotIn("\u2063", pulito)
        self.assertEqual(pulito, "Prima pagina\n\nSeconda\n\nTerza")
        self.assertEqual(len(offset), 3)
        self.assertEqual(pulito[offset[1]:offset[1] + 7], "Seconda")
        self.assertEqual(pulito[offset[2]:offset[2] + 5], "Terza")

    def test_pagina_vuota_prende_la_successiva(self):
        testo = "\u20630\u2063Uno\u20631\u2063\u20632\u2063Tre"
        pulito, offset = separa_segni_pagina(testo, 3)
        self.assertEqual(offset[1], offset[2])
        self.assertEqual(pulito[offset[2]:], "Tre")


class VisibilitaTests(TestCase):
    def setUp(self):
        self.qualita = AccessGroup.objects.create(code="qualita_t", label="Qualità T")
        self.prod = AccessGroup.objects.create(code="produzione_t", label="Produzione T")
        self.a = _doc("MT CN 01", "Acquisizione ordini")
        self.b = _doc("MOD.093", "Rapporto NC", sezione="_Modelli")
        self.c = _doc("PDQ A", "Piano qualità A", cartella="_Piani Qualitá", sezione="Cliente A")

    def _vis(self, gruppi=(), gestore=False):
        return lib.Visibilita(None, gestore=gestore, gruppi=set(gruppi), vede_tutto=False)

    def test_senza_regole_tutti_vedono(self):
        self.assertTrue(self._vis().puo_vedere(self.a))
        self.assertEqual(lib.codici_riservati(), set())

    def test_regola_scaffale_e_eccezione_documento(self):
        r = SgiVisibilita.objects.create(scaffale="9100_Qualità")
        r.ruoli.set([self.qualita])
        eccezione = SgiVisibilita.objects.create(scaffale="9100_Qualità", documento=self.b)
        eccezione.ruoli.set([self.prod])
        self.assertFalse(self._vis().puo_vedere(self.a))
        self.assertTrue(self._vis([self.qualita.pk]).puo_vedere(self.a))
        # La regola del documento vince su quella dello scaffale.
        self.assertFalse(self._vis([self.qualita.pk]).puo_vedere(self.b))
        self.assertTrue(self._vis([self.prod.pk]).puo_vedere(self.b))
        self.assertTrue(self._vis().puo_vedere(self.c))
        self.assertEqual(lib.codici_riservati(), {"MT CN 01", "MOD.093"})

    def test_regola_sezione_e_solo_gestori(self):
        SgiVisibilita.objects.create(scaffale="9100_Qualità", sezione="_Modelli", chi="nessuno")
        self.assertTrue(self._vis().puo_vedere(self.a))
        self.assertFalse(self._vis([self.qualita.pk]).puo_vedere(self.b))
        self.assertTrue(self._vis(gestore=True).puo_vedere(self.b))

    def test_sensibile_solo_gestori(self):
        self.a.escludi_dal_rag = True
        self.a.save()
        self.assertFalse(self._vis([self.qualita.pk]).puo_vedere(self.a))
        self.assertTrue(self._vis(gestore=True).puo_vedere(self.a))

    def test_bacheca_esclude_i_riservati(self):
        from .bacheca import build_procedure_group

        SgiVisibilita.objects.create(scaffale="9100_Qualità", chi="nessuno")
        gruppo = build_procedure_group()
        titoli = " ".join(i["title"] for i in gruppo["items"])
        self.assertIn("PDQ A", titoli)
        self.assertNotIn("MT CN 01", titoli)

    def test_assistente_non_cita_i_riservati(self):
        from ai_assistant.services import _sgi_proc_riservato

        cache.delete("cnsgi_codici_riservati")
        SgiVisibilita.objects.create(scaffale="9100_Qualità", chi="nessuno")
        self.assertTrue(_sgi_proc_riservato("proc:MT CN 01#rev2"))
        self.assertFalse(_sgi_proc_riservato("proc:PDQ A#rev2"))
        cache.delete("cnsgi_codici_riservati")


class RicercaTests(TestCase):
    def setUp(self):
        lib._MEMO_TESTI.clear()
        testo = "1. Scopo\nIntro.\n\n4.2 Registrazione\nLa non conformità è registrata sul MOD.093.\n\n5. Chiusura\nVerifica di efficacia."
        pos_pag2 = testo.index("4.2")
        self.doc = _doc("MT CN 06", "Gestione delle non conformità", testo=testo, offset=[0, pos_pag2, len(testo) - 25], n_pagine=3)
        self.altro = _doc("MT CN 05", "Tracciabilità", testo="Nulla da segnalare.", n_pagine=1)

    def test_cerca_titolo_e_testo_senza_accenti(self):
        docs = lib.documenti_in_vigore()
        risultati = lib.cerca("non conformita", docs)
        self.assertEqual([r.doc.code for r in risultati], ["MT CN 06"])
        r = risultati[0]
        self.assertTrue(r.nel_titolo)
        self.assertTrue(r.estratti)
        self.assertEqual(r.estratti[0]["pagina"], 2)
        self.assertEqual(r.estratti[0]["sezione"], "§4.2")

    def test_cerca_solo_titolo(self):
        docs = lib.documenti_in_vigore()
        self.assertEqual(lib.cerca("efficacia", docs, campo="titolo"), [])
        self.assertEqual([r.doc.code for r in lib.cerca("efficacia", docs, campo="testo")], ["MT CN 06"])

    def test_indice_documento(self):
        rev = self.doc.revisions.get(is_current=True)
        indice = lib.indice_documento(rev)
        self.assertEqual([v["sezione"] for v in indice], ["§1", "§4.2", "§5"])
        self.assertEqual(indice[1]["pagina"], 2)


class PagineTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="cnsgi_admin", password="pw", is_superuser=True)
        self.client.force_login(self.admin)
        self.doc = _doc("MT CN 06", "Gestione delle non conformità", testo="4.2 Registrazione\nNon conformità.", n_pagine=1)
        self.pdq = _doc("PDQ A", "Piano qualità A", cartella="_Piani Qualitá", sezione="Cliente A")
        lib.assicura_scaffali()
        SgiSyncLog.objects.create(run_id="1", azione=SgiSyncAction.NUOVA_REVISIONE, document_code="MT CN 06", revision_new="2")

    def test_libreria_scaffale_cerca(self):
        r = self.client.get(reverse("procedure_refresh:libreria"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Scaffali")
        self.assertContains(r, "Nuove revisioni")
        self.assertContains(r, "Piani Qualità")
        slug = lib.slug_scaffale("9100_Qualità")
        r = self.client.get(reverse("procedure_refresh:libreria_scaffale", args=[slug]) + "?vista=elenco")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "MT CN 06")
        self.assertEqual(r.cookies["cnsgi_vista"].value, "elenco")
        r = self.client.get(reverse("procedure_refresh:libreria_cerca") + "?q=conformita")
        self.assertContains(r, "<mark>")

    def test_scheda_htmx_e_pagina(self):
        url = reverse("procedure_refresh:libreria_documento", args=[self.doc.pk])
        r = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Apri il PDF")
        self.assertNotContains(r, "<html")
        r = self.client.get(url)
        self.assertContains(r, "Segnala una modifica")

    def test_apri_conta_e_porta_al_documento(self):
        r = self.client.get(reverse("procedure_refresh:libreria_apri", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SgiAperturaGiorno.objects.get(documento=self.doc).conteggio, 1)

    def test_segnala_crea_la_segnalazione(self):
        from .models import ProcedureChangeRequest

        r = self.client.post(reverse("procedure_refresh:libreria_segnala", args=[self.doc.pk]), {"testo": "Chiarire §4.2", "sezione": "§4.2"})
        self.assertEqual(r.status_code, 302)
        cr = ProcedureChangeRequest.objects.get(document=self.doc)
        self.assertTrue(cr.testo.startswith("[§4.2]"))

    def test_regola_dalla_pagina_e_404_per_chi_non_ha_il_ruolo(self):
        ruolo = AccessGroup.objects.create(code="qualita_p", label="Qualità P")
        r = self.client.post(reverse("procedure_refresh:libreria_visibilita"), {
            "scaffale": "9100_Qualità", "sezione": "", "documento": str(self.doc.pk), "chi": "ruoli", "ruoli": [str(ruolo.pk)],
        })
        self.assertEqual(r.status_code, 302)
        regola = SgiVisibilita.objects.get(documento=self.doc)
        self.assertEqual(list(regola.ruoli.all()), [ruolo])
        r = self.client.get(reverse("procedure_refresh:libreria_visibilita"))
        self.assertContains(r, "Qualità P")

        senza_ruoli = lib.Visibilita(None, gestore=False, gruppi=set(), vede_tutto=False)
        with mock.patch("procedure_refresh.views_libreria.lib.Visibilita", return_value=senza_ruoli):
            self.assertEqual(self.client.get(reverse("procedure_refresh:libreria_documento", args=[self.doc.pk])).status_code, 404)
            self.assertEqual(self.client.get(reverse("procedure_refresh:libreria_apri", args=[self.doc.pk])).status_code, 404)
            r = self.client.get(reverse("procedure_refresh:libreria_cerca") + "?q=conformita")
            self.assertNotContains(r, "MT CN 06")

    def test_gestione_solo_per_chi_gestisce(self):
        utente = User.objects.create_user(username="cnsgi_user", password="pw")
        self.client.force_login(utente)
        with mock.patch("procedure_refresh.views_libreria._can_manage", return_value=False):
            r = self.client.get(reverse("procedure_refresh:libreria_visibilita"))
            self.assertNotEqual(r.status_code, 200)
            r = self.client.post(reverse("procedure_refresh:libreria_scaffali"), {"azione": "allinea"})
            self.assertNotEqual(r.status_code, 200)
        self.assertFalse(SgiVisibilita.objects.exists())

    def test_scaffali_salva(self):
        s = SgiScaffale.objects.get(cartella="9100_Qualità")
        r = self.client.post(reverse("procedure_refresh:libreria_scaffali"), {
            f"s{s.pk}_nome": "Qualità aeronautica", f"s{s.pk}_sigla": "9100", f"s{s.pk}_norma": "EN 9100",
            f"s{s.pk}_colore": "#123456", f"s{s.pk}_ordine": "5", f"s{s.pk}_attivo": "1",
        })
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual((s.nome, s.colore, s.ordine), ("Qualità aeronautica", "#123456", 5))

    def test_guida(self):
        r = self.client.get(reverse("procedure_refresh:libreria") + "?guida=1")
        self.assertContains(r, "Chi vede cosa (per chi gestisce)")

    def test_letture_spostate(self):
        self.assertEqual(reverse("procedure_refresh:my_assignments"), "/procedure-refresh/letture/")
        self.assertEqual(self.client.get(reverse("procedure_refresh:my_assignments")).status_code, 200)


class ControlloOrarioTests(TestCase):
    def test_salta_con_flag_spento(self):
        from .tasks import run_sgi_controllo_orario

        self.assertTrue(run_sgi_controllo_orario()["skipped"])

    def test_sincronizza_solo_se_cambia(self):
        import tempfile
        from pathlib import Path

        from core.models import SiteConfig

        from .tasks import run_sgi_controllo_orario

        SiteConfig.set("pr_sgi_auto_sync_attivo", "1", "test")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "9100_Qualità" / "2_MT").mkdir(parents=True)
            (Path(tmp) / "9100_Qualità" / "2_MT" / "MT CN 01 Rev.2_Acquisizione ordini.pdf").write_bytes(b"%PDF-1.4 test")
            with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=tmp), \
                    mock.patch("procedure_refresh.tasks.accoda_estrazione_sgi", return_value=False):
                primo = run_sgi_controllo_orario()
                secondo = run_sgi_controllo_orario()
        self.assertTrue(primo["cambiato"])
        self.assertFalse(secondo["cambiato"])
        doc = ProcedureDocument.objects.get(code="MT CN 01")
        self.assertEqual(doc.sezione, "2_MT")
        self.assertTrue(SgiScaffale.objects.filter(cartella="9100_Qualità").exists())


class Fase2Tests(TestCase):
    def setUp(self):
        from . import collegamenti as col

        col.svuota_cache()
        self.admin = User.objects.create_user(username="cnsgi_f2", password="pw", is_superuser=True)
        self.client.force_login(self.admin)
        self.dpi = _doc("MT CN 451", "Gestione DPI", cartella="45001_Sicurezza", sezione="")
        self.mod = _doc("MOD.093", "Rapporto di non conformità", sezione="_Modelli")
        lib.assicura_scaffali()

    def test_proposte_da_parole_chiave(self):
        from . import collegamenti as col

        proposte = {(p["doc"].code, p["modulo"].chiave, p["compila"]) for p in col.proposte(lib.documenti_in_vigore())}
        self.assertIn(("MT CN 451", "dpi", False), proposte)
        self.assertIn(("MOD.093", "anomalie", True), proposte)

    def test_conferma_etichette_e_compila(self):
        from . import collegamenti as col
        from .models import SgiDocumentoModulo

        url = reverse("procedure_refresh:libreria_collegamenti")
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, {"azione": "conferma", "proposta": [f"{self.mod.pk}:anomalie:1", f"{self.dpi.pk}:dpi:0"]})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(SgiDocumentoModulo.objects.get(documento=self.mod, modulo="anomalie").compila)
        modulo, procedure = col.procedure_della_pagina("/dpi/consegne/")
        self.assertEqual(modulo.chiave, "dpi")
        self.assertEqual([p["codice"] for p in procedure], ["MT CN 451"])
        r = self.client.get(reverse("procedure_refresh:libreria_documento", args=[self.mod.pk]))
        self.assertContains(r, "HUB · Gestione anomalie")
        # Un documento riservato non compare tra le etichette del modulo.
        SgiVisibilita.objects.create(scaffale="45001_Sicurezza", chi="nessuno")
        col.svuota_cache()
        self.assertEqual(col.procedure_della_pagina("/dpi/")[1], [])

    def test_etichetta_nel_sottomenu(self):
        from django.template import Context, Template
        from django.test import RequestFactory

        from . import collegamenti as col
        from .models import SgiDocumentoModulo

        SgiDocumentoModulo.objects.create(documento=self.dpi, modulo="dpi")
        col.svuota_cache()
        req = RequestFactory().get("/dpi/")
        req.user = self.admin
        html = Template("{% load cnsgi %}{% cnsgi_etichette %}").render(Context({"request": req}))
        self.assertIn("MT CN 451", html)
        req = RequestFactory().get("/tickets/")
        req.user = self.admin
        self.assertNotIn("MT CN 451", Template("{% load cnsgi %}{% cnsgi_etichette %}").render(Context({"request": req})))

    def test_pacchetto_audit_e_excel(self):
        slug = lib.slug_scaffale("9100_Qualità")
        r = self.client.get(reverse("procedure_refresh:libreria_audit", args=[slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "MOD.093")
        r = self.client.get(reverse("procedure_refresh:libreria_audit", args=[slug]) + "?formato=xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])

    def test_pacchetto_audit_negato_a_chi_non_gestisce(self):
        senza = lib.Visibilita(None, gestore=False, gruppi=set(), vede_tutto=False)
        with mock.patch("procedure_refresh.views_libreria.lib.Visibilita", return_value=senza):
            r = self.client.get(reverse("procedure_refresh:libreria_audit", args=[lib.slug_scaffale("9100_Qualità")]))
        self.assertEqual(r.status_code, 302)


class Fase3Tests(TestCase):
    def setUp(self):
        from . import collegamenti as col

        col.svuota_cache()
        self.admin = User.objects.create_user(username="cnsgi_f3", password="pw", is_superuser=True)
        self.client.force_login(self.admin)
        self.mt = _doc("MT CN 06", "Gestione delle non conformità")
        self.pdq = _doc("PDQ CLI-A", "Piano della qualità", cartella="_Piani Qualitá", sezione="Avio Aero")
        self.altro = _doc("PDQ CLI-B", "Piano della qualità", cartella="_Piani Qualitá", sezione="Cliente B")

    def test_ricerca_globale_porta_alla_libreria(self):
        r = self.client.get(reverse("api_global_search") + "?q=MT CN 06")
        dati = r.json()["results"]
        proc = [x for x in dati if x.get("tipo") == "procedura"]
        self.assertTrue(proc)
        self.assertEqual(proc[0]["url"], reverse("procedure_refresh:libreria_documento", args=[self.mt.pk]))

    def test_ricerca_globale_nasconde_i_riservati(self):
        SgiVisibilita.objects.create(scaffale="9100_Qualità", chi="nessuno")
        senza = lib.Visibilita(None, gestore=False, gruppi=set(), vede_tutto=False)
        with mock.patch("procedure_refresh.libreria.Visibilita", return_value=senza):
            dati = self.client.get(reverse("api_global_search") + "?q=MT CN 06").json()["results"]
        self.assertFalse([x for x in dati if x.get("tipo") == "procedura"])

    def test_scheda_da_codice_e_fonte_assistente(self):
        from ai_assistant.services import url_scheda_procedura

        url = url_scheda_procedura("proc:MT CN 06#rev2")
        self.assertEqual(url, reverse("procedure_refresh:libreria_documento_codice") + "?c=MT%20CN%2006")
        r = self.client.get(url)
        self.assertRedirects(r, reverse("procedure_refresh:libreria_documento", args=[self.mt.pk]), fetch_redirect_response=False)
        r = self.client.get(reverse("procedure_refresh:libreria_documento_codice") + "?c=NON ESISTE")
        self.assertEqual(r.status_code, 302)
        self.assertIn("cerca", r["Location"])

    def test_piano_qualita_del_cliente_nel_kickoff(self):
        from django.test import RequestFactory

        from . import collegamenti as col
        from .models import SgiDocumentoModulo

        SgiDocumentoModulo.objects.create(documento=self.mt, modulo="kickoff")
        col.svuota_cache()
        req = RequestFactory().get("/tasks/")
        req.user = self.admin
        codici = [d["codice"] for d in col.documenti_per_kickoff(req, "AVIO AERO S.r.l.")]
        self.assertEqual(codici, ["PDQ CLI-A", "MT CN 06"])
        codici = [d["codice"] for d in col.documenti_per_kickoff(req, "Altro cliente")]
        self.assertEqual(codici, ["MT CN 06"])


class ApriFileTests(TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "9100_Qualità" / "2_MT").mkdir(parents=True)
        self.pdf = self.root / "9100_Qualità" / "2_MT" / "MT CN 01 Rev.2_Ordini.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 test")
        self.admin = User.objects.create_user(username="cnsgi_apri", password="pw", is_superuser=True)
        self.client.force_login(self.admin)
        self.doc = ProcedureDocument.objects.create(code="MT CN 01", title="Ordini", category="9100_Qualità", sezione="2_MT")
        self.rev = ProcedureRevision.objects.create(
            document=self.doc, revision_code="2", revision_date=date(2026, 10, 1), effective_date=date(2026, 10, 1),
            source_type=SourceType.FILESERVER, source_path=str(self.pdf), file_name=self.pdf.name, is_current=True,
        )

    def test_apre_il_pdf_inline(self):
        with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=str(self.root)):
            r = self.client.get(reverse("procedure_refresh:libreria_apri", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("inline", r["Content-Disposition"])

    def test_file_sparito_spiega_invece_di_not_found(self):
        self.pdf.unlink()
        with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=str(self.root)):
            r = self.client.get(reverse("procedure_refresh:libreria_apri", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "più nella cartella SGI", status_code=404)

    def test_senza_permesso_sulla_cartella(self):
        with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=str(self.root)), \
                mock.patch("procedure_refresh.views_libreria._safe_sgi_pdf", return_value=None), \
                mock.patch("procedure_refresh.libreria.Path.stat", side_effect=PermissionError):
            r = self.client.get(reverse("procedure_refresh:libreria_apri", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 503)
        self.assertContains(r, "non riesce a leggere la cartella SGI", status_code=503)


class RicercaFlessibileTests(TestCase):
    def setUp(self):
        lib._MEMO_TESTI.clear()
        lib._VOCABOLARIO.update(chiave=None, parole=[])
        self.dpi = _doc("MT CN 451", "Gestione DPI", cartella="45001_Sicurezza", sezione="",
                        testo="4.3 Consegna\nLa consegna dei dispositivi di protezione è registrata con la firma del lavoratore.", n_pagine=2)
        self.nc = _doc("MT CN 06", "Gestione delle non conformità e azioni correttive",
                       testo="4.2 Registrazione\nOgni non conformità rilevata in accettazione viene registrata sul MOD.093.", n_pagine=3)
        self.mod = _doc("MOD.093", "Rapporto di non conformità", sezione="_Modelli")
        self.proc = _doc("MT CN 14", "Procedure di formazione del personale", testo="Le procedure di addestramento.", n_pagine=1)

    def _codici(self, q, **kw):
        return [r.doc.code for r in lib.cerca(q, lib.documenti_in_vigore(), **kw)]

    def test_parole_in_qualunque_ordine_e_parole_vuote(self):
        self.assertIn("MT CN 06", self._codici("correttive azioni della gestione"))
        self.assertEqual(self._codici("dpi gestione")[0], "MT CN 451")

    def test_radici_singolare_plurale(self):
        self.assertIn("MT CN 14", self._codici("procedura formazione"))
        self.assertIn("MT CN 451", self._codici("dispositivo protezione firma"))

    def test_codici_con_e_senza_zeri_e_separatori(self):
        self.assertEqual(self._codici("mt 6")[0], "MT CN 06")
        self.assertEqual(self._codici("mod93")[0], "MOD.093")
        self.assertEqual(self._codici("MT-CN-451")[0], "MT CN 451")

    def test_parola_scritta_male(self):
        risultati = lib.cerca("confromita", lib.documenti_in_vigore())
        self.assertIn("MT CN 06", [r.doc.code for r in risultati])
        self.assertEqual(risultati.corrette[0][1], "conformita")

    def test_manca_una_parola(self):
        risultati = lib.cerca("non conformita zebra", lib.documenti_in_vigore())
        self.assertTrue(risultati.approssimati)
        self.assertIn("MT CN 06", [r.doc.code for r in risultati])

    def test_estratto_evidenzia_la_parola_intera(self):
        r = next(x for x in lib.cerca("registrata accettazione", lib.documenti_in_vigore()) if x.doc.code == "MT CN 06")
        self.assertTrue(r.estratti)
        self.assertIn(r.estratti[0]["trovato"].lower(), ("accettazione", "registrata"))


class SecondoGiroUITests(TestCase):
    def setUp(self):
        from . import esperienza as esp

        cache.delete("cnsgi_glossario_v1")
        lib._MEMO_TESTI.clear()
        self.esp = esp
        self.admin = User.objects.create_user(username="cnsgi_ui2", password="pw", is_superuser=True)
        self.client.force_login(self.admin)
        self.doc = _doc("MT CN 06", "Gestione delle non conformità",
                        testo="1. Scopo\nGestire le NC.\n\n4.2 Registrazione\nLa NC va registrata sul MOD.093 entro 2 giorni.\n\n5. Chiusura\nVerifica.",
                        n_pagine=3)
        vecchia = ProcedureRevision.objects.create(
            document=self.doc, revision_code="1", revision_date=date(2025, 1, 1), effective_date=date(2025, 1, 1),
            source_type=SourceType.SHAREPOINT, source_url="https://example.invalid/old.pdf", file_name="old.pdf", is_current=False,
        )
        SgiTestoEstratto.objects.create(
            revision=vecchia, file_hash="v", formato="pdf", metodo="test",
            testo="1. Scopo\nGestire le NC.\n\n4.2 Registrazione\nLa NC va registrata sul MOD.093 entro 5 giorni.\n\n6. Archivio\nTre anni.",
            n_pagine=3, n_caratteri=100,
        )
        self.vecchio = _doc("MT CN 99", "Procedura antica", testo="Testo.", n_pagine=1)
        ProcedureRevision.objects.filter(document=self.vecchio).update(revision_date=date(2019, 5, 1))
        lib.assicura_scaffali()

    def test_differenze_per_paragrafo(self):
        rev = self.doc.revisions.get(is_current=True)
        vecchia = self.doc.revisions.get(is_current=False)
        cambi = {(c.tipo, c.numero) for c in self.esp.differenze(vecchia.testo_estratto.testo, rev.testo_estratto.testo)}
        self.assertEqual(cambi, {("modificato", "4.2"), ("aggiunto", "5"), ("tolto", "6")})

    def test_scheda_cosa_cambia_anteprima_mappa(self):
        r = self.client.get(reverse("procedure_refresh:libreria_documento", args=[self.doc.pk]) + "?pagina=2", HTTP_HX_REQUEST="true")
        self.assertContains(r, "Cosa cambia · 3")
        self.assertContains(r, "#page=2")
        self.assertContains(r, "assistente su questo documento")

    def test_pdf_si_puo_mostrare_nel_pannello(self):
        r = self.client.get(reverse("procedure_refresh:libreria_apri", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)  # SharePoint: reindirizza
        self.assertNotEqual(r.get("X-Frame-Options"), "DENY")

    def test_stella_e_i_miei_documenti(self):
        from .models import SgiPreferito

        url = reverse("procedure_refresh:libreria_preferito", args=[self.doc.pk])
        r = self.client.post(url, HTTP_HX_REQUEST="true")
        self.assertContains(r, "★")
        self.assertTrue(SgiPreferito.objects.filter(user=self.admin, documento=self.doc).exists())
        r = self.client.get(reverse("procedure_refresh:libreria"))
        self.assertContains(r, "I miei documenti")
        self.client.post(url, HTTP_HX_REQUEST="true")
        self.assertFalse(SgiPreferito.objects.exists())

    def test_ricerca_live_e_suggerimenti(self):
        r = self.client.get(reverse("procedure_refresh:libreria_cerca") + "?q=registrata", HTTP_HX_REQUEST="true")
        self.assertContains(r, "MT CN 06")
        self.assertNotContains(r, "<html")
        r = self.client.get(reverse("procedure_refresh:libreria_suggerimenti") + "?q=mt 6")
        self.assertContains(r, "MT CN 06")
        self.assertContains(r, "anche nel testo")
        self.assertEqual(self.client.get(reverse("procedure_refresh:libreria_suggerimenti") + "?q=m").content.strip(), b"")

    def test_etichette_qr(self):
        r = self.client.get(reverse("procedure_refresh:libreria_etichetta", args=[self.doc.pk]))
        self.assertContains(r, "<svg")
        self.assertContains(r, "MT CN 06")
        r = self.client.get(reverse("procedure_refresh:libreria_etichette", args=[lib.slug_scaffale("9100_Qualità")]))
        self.assertContains(r, "2 etichette")

    def test_da_rivedere_e_filtri_scaffale(self):
        r = self.client.get(reverse("procedure_refresh:libreria_da_rivedere"))
        self.assertContains(r, "MT CN 99")
        self.assertNotContains(r, ">MT CN 06<")
        slug = lib.slug_scaffale("9100_Qualità")
        r = self.client.get(reverse("procedure_refresh:libreria_scaffale", args=[slug]) + "?cambiati=365")
        self.assertContains(r, "MT CN 06")
        self.assertNotContains(r, "MT CN 99")

    def test_glossario_negli_estratti(self):
        from glossario_tecnico.models import Termine

        Termine.objects.create(termine="Registrazione", categoria=Termine._meta.get_field("categoria").choices[0][0],
                               definizione="Annotazione su un modulo", stato=Termine.VALIDATO)
        cache.delete("cnsgi_glossario_v1")
        html = str(self.esp.con_glossario("La registrazione <b> va fatta"))
        self.assertIn('<abbr class="cn-gloss" title="Annotazione su un modulo">registrazione</abbr>', html)
        self.assertIn("&lt;b&gt;", html)


class SegnalazioniRiletturaTests(TestCase):
    def setUp(self):
        from .models import CampaignStatus, ProcedureAssignment, ProcedureCampaign

        self.admin = User.objects.create_user(username="cnsgi_segn", password="pw", is_superuser=True)
        self.lettore = User.objects.create_user(username="cnsgi_lettore", password="pw")
        self.client.force_login(self.admin)
        self.doc = _doc("MT CN 06", "Gestione delle non conformità")
        self.vecchia = ProcedureRevision.objects.create(
            document=self.doc, revision_code="1", revision_date=date(2025, 1, 1), effective_date=date(2025, 1, 1),
            source_type=SourceType.SHAREPOINT, source_url="https://example.invalid/o.pdf", file_name="o.pdf", is_current=False,
        )
        self.rev = self.doc.revisions.get(is_current=True)
        camp = ProcedureCampaign.objects.create(name="Vecchia", status=CampaignStatus.CLOSED, start_date=date(2025, 1, 1),
                                                due_date=date(2025, 2, 1), created_by=self.admin)
        ProcedureAssignment.objects.create(campaign=camp, revision=self.vecchia, user=self.lettore, status="read_confirmed")
        lib.assicura_scaffali()

    def test_nuova_segnalazione_avvisa_chi_gestisce(self):
        with mock.patch("procedure_refresh.segnalazioni.destinatari_gestori", return_value={11, 12}), \
                mock.patch("core.notifiche.invia_notifica") as invia:
            self.client.post(reverse("procedure_refresh:libreria_segnala", args=[self.doc.pk]), {"testo": "Chiarire §4.2"})
        self.assertEqual(invia.call_count, 2)
        self.assertIn("MT CN 06", invia.call_args[0][2])

    def test_cambio_stato_avvisa_chi_ha_segnalato(self):
        from .models import ProcedureChangeRequest

        cr = ProcedureChangeRequest.objects.create(document=self.doc, revision=self.vecchia, created_by=self.lettore, testo="Proposta")
        with mock.patch("procedure_refresh.tasks._legacy_id_map", return_value={self.lettore.pk: 77}), \
                mock.patch("core.notifiche.invia_notifica") as invia:
            self.client.post(reverse("procedure_refresh:change_request_set_status", args=[cr.pk]),
                             {"status": "recepita", "recepita_in_revisione": str(self.rev.pk), "risposta_gestore": "Fatto"})
        invia.assert_called_once()
        self.assertEqual(invia.call_args[0][0], 77)
        self.assertIn("recepita nella Rev.2", invia.call_args[0][2])
        # La segnalazione accolta compare in «Cosa cambia» della revisione che l'ha recepita.
        r = self.client.get(reverse("procedure_refresh:libreria_documento", args=[self.doc.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(r, "Segnalazioni accolte in questa revisione")
        self.assertContains(r, "Proposta")

    def test_le_mie_segnalazioni(self):
        from .models import ProcedureChangeRequest

        ProcedureChangeRequest.objects.create(document=self.doc, revision=self.rev, created_by=self.admin, testo="Refuso al §5")
        r = self.client.get(reverse("procedure_refresh:my_assignments"))
        self.assertContains(r, "Le mie segnalazioni")
        self.assertContains(r, "Refuso al §5")

    def test_chiedi_la_rilettura(self):
        from .models import ProcedureAssignment

        r = self.client.get(reverse("procedure_refresh:libreria_documento", args=[self.doc.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(r, "Chiedi la rilettura")
        with mock.patch("core.notifiche.invia_notifica"):
            r = self.client.post(reverse("procedure_refresh:libreria_rilettura", args=[self.doc.pk]), {"giorni": "10"})
        self.assertEqual(r.status_code, 302)
        a = ProcedureAssignment.objects.get(revision=self.rev, user=self.lettore)
        self.assertEqual(a.campaign.status, "published")
        self.assertEqual(a.due_date, timezone.localdate() + timedelta(days=10))
        # Una seconda richiesta non duplica: nessuno resta da avvisare.
        r = self.client.post(reverse("procedure_refresh:libreria_rilettura", args=[self.doc.pk]))
        self.assertEqual(ProcedureAssignment.objects.filter(revision=self.rev).count(), 1)

    def test_rilettura_solo_per_chi_gestisce(self):
        with mock.patch("procedure_refresh.views_libreria._can_manage", return_value=False):
            self.client.post(reverse("procedure_refresh:libreria_rilettura", args=[self.doc.pk]))
        from .models import ProcedureAssignment

        self.assertFalse(ProcedureAssignment.objects.filter(revision=self.rev).exists())
