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
