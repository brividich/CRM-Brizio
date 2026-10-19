"""Mansionario 19/10/2026: rinomina sicura, wizard «Nuova mansione», Impostazioni, regole.

Dati sintetici; base e helper di ``tests_struttura``.
"""
from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse

from .models import AbilitazioneMacchinaStorico, CompetenzaSkm, SkillMatrixConfig, VoceMacchinaCatalogo
from .services import mansionario_competenze as comp
from .services import mansionario_struttura as svc
from .services import struttura_excel as xl
from .tests_struttura import _Base, _xlsx


def _riga(colonne, **valori):
    r = dict.fromkeys(colonne, "")
    r.update(valori)
    return [r[c] for c in colonne]


class RinominaTests(_Base):
    def test_rinomina_tiene_collegamenti_e_vecchio_nome(self):
        self.processo.ruoli.set([self.ruolo])
        self.processo.mansioni_rischio.set([self.rischio])
        ab = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="U")
        prima = svc.rinomina(self.processo, "  Sbavatura   manuale ")
        self.assertEqual(prima, "Sbavatura")
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.nome, "Sbavatura manuale")
        self.assertEqual(self.processo.competenza_key, "P-SBA")
        self.assertEqual(svc.nomi_precedenti(self.processo), ["Sbavatura"])
        ab.refresh_from_db()
        self.assertEqual(ab.competenza_id, self.processo.pk)
        self.assertEqual(list(self.processo.ruoli.all()), [self.ruolo])
        self.assertEqual(list(self.processo.mansioni_rischio.all()), [self.rischio])
        # Tornare al vecchio nome lo toglie dai precedenti; stesso nome = niente da fare.
        svc.rinomina(self.processo, "Sbavatura")
        self.assertEqual(svc.nomi_precedenti(self.processo), ["Sbavatura manuale"])
        self.assertIsNone(svc.rinomina(self.processo, "Sbavatura"))

    def test_rinomina_rifiuta_doppione_e_vuoto(self):
        with self.assertRaisesMessage(ValueError, "Esiste già"):
            svc.rinomina(self.processo, "fresa fr-09")
        with self.assertRaises(ValueError):
            svc.rinomina(self.processo, "   ")

    def test_seed_mod187_non_rimette_il_vecchio_nome(self):
        from .services.skillmatrix_seed import sincronizza_catalogo

        svc.rinomina(self.processo, "Sbavatura manuale")
        sincronizza_catalogo(catalogo=[{"competenza_key": "P-SBA", "display": "Sbavatura", "tipo": "processo",
                                        "codice": "", "alias_storici": "SBA vecchia", "note": ""}])
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.nome, "Sbavatura manuale")
        self.assertEqual(svc.nomi_precedenti(self.processo), ["Sbavatura", "SBA vecchia"])

    def test_excel_rinomina_e_riconosce_il_vecchio_nome(self):
        file_m = _xlsx({xl.FOGLIO_MANSIONI: [xl.COL_MANSIONI,
                                             _riga(xl.COL_MANSIONI, Chiave="P-SBA", Mansione="Sbavatura manuale")]})
        esito = xl.importa(file_m, applica=True)
        self.assertEqual(esito.errori, 0, [r.dettaglio for r in esito.righe])
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.nome, "Sbavatura manuale")
        # Un file vecchio, senza chiave e col nome di prima, trova ancora la mansione.
        file_c = _xlsx({xl.FOGLIO_COMPETENZE: [xl.COL_COMPETENZE, _riga(
            xl.COL_COMPETENZE, Mansione="Sbavatura", Competenza="Uso lima", **{"Livello minimo": "L"})]})
        esito = xl.importa(file_c, applica=True)
        self.assertEqual(esito.errori, 0, [r.dettaglio for r in esito.righe])
        self.assertTrue(VoceMacchinaCatalogo.objects.filter(mansione=self.processo, nome="Uso lima").exists())

    def test_impostazioni_rinomina_e_scheda(self):
        url = reverse("anagrafica:mansionario_mansione", args=[self.processo.pk])
        r = self.client.post(url, {"nome": "Sbavatura manuale", "attiva": "on", "ruoli": [self.ruolo.pk]})
        self.assertRedirects(r, url + "#impostazioni", fetch_redirect_response=False)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.nome, "Sbavatura manuale")
        r = self.client.get(url)
        self.assertContains(r, "Nomi precedenti: Sbavatura")
        self.assertContains(r, "mns-check-list")
        self.assertNotContains(r, "{#")
        # Doppione: niente salvato, nemmeno i ruoli.
        self.client.post(url, {"nome": "Fresa FR-09", "attiva": "on", "ruoli": [self.capo.pk]})
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.nome, "Sbavatura manuale")
        self.assertEqual(list(self.processo.ruoli.all()), [self.ruolo])

    def test_editor_rinomina_e_riga_modello(self):
        url = reverse("anagrafica:mansionario_struttura_mansione", args=[self.processo.pk])
        r = self.client.post(url, {"nome": "Sbavatura fine", "attiva": "on", "n_righe": "0"})
        self.assertContains(r, "prima «Sbavatura»")
        r = self.client.get(url)
        self.assertContains(r, "data-mst-modello")
        self.assertContains(r, 'name="r__I___nome"')


class WizardTests(_Base):
    def _url(self):
        return reverse("anagrafica:mansionario_struttura_nuova")

    def test_get_mostra_i_cinque_passi(self):
        r = self.client.get(self._url())
        for testo in ("Come si chiama la mansione?", "Sotto quale ruolo", "Quali mansioni di rischio",
                      "Quali competenze servono?", "Controlla e crea", "Sbavatura"):
            self.assertContains(r, testo)
        self.assertNotContains(r, "{#")

    def test_crea_tutto_in_un_colpo(self):
        r = self.client.post(self._url(), {
            "nome": "Collaudo T", "ruoli": [self.ruolo.pk], "reparto": str(self.reparto.pk),
            "mansioni_rischio": [self.rischio.pk], "n_righe": "3",
            "r0_nome": "Lettura disegno", "r0_livello_minimo": "L", "r0_bloccante": "on",
            "r0_requisito": f"qualifica:{self.qualifica.pk}",
            "r1_nome": "", "r2_nome": "Uso calibro", "r2_livello_minimo": "U",
        })
        m = CompetenzaSkm.objects.get(display="Collaudo T")
        self.assertRedirects(r, reverse("anagrafica:mansionario_mansione", args=[m.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(m.tipo, CompetenzaSkm.TIPO_PROCESSO)
        self.assertEqual(m.reparto_id, self.reparto.pk)
        self.assertEqual(list(m.ruoli.all()), [self.ruolo])
        self.assertEqual(list(m.mansioni_rischio.all()), [self.rischio])
        voci = list(VoceMacchinaCatalogo.objects.filter(mansione=m).order_by("ordine"))
        self.assertEqual([(v.nome, v.livello_minimo, v.bloccante, v.qualifica_id) for v in voci],
                         [("Lettura disegno", "L", True, self.qualifica.pk), ("Uso calibro", "U", False, None)])

    def test_errore_competenze_non_crea_niente(self):
        r = self.client.post(self._url(), {"nome": "Collaudo T", "n_righe": "2",
                                           "r0_nome": "Doppia", "r1_nome": "doppia"})
        self.assertContains(r, "Niente creato")
        self.assertContains(r, 'data-passo="4"')
        self.assertContains(r, 'value="Collaudo T"')
        self.assertFalse(CompetenzaSkm.objects.filter(display="Collaudo T").exists())

    def test_non_admin_non_entra(self):
        with patch("anagrafica.views._helpers._is_anagrafica_admin", return_value=False):
            r = self.client.get(self._url())
        self.assertEqual(r.status_code, 302)


class RegoleTests(_Base):
    def setUp(self):
        super().setUp()
        self.config = SkillMatrixConfig.get_instance()
        self.v1 = comp.salva_competenza(self.processo, nome="A", livello_minimo="I")
        self.v2 = comp.salva_competenza(self.processo, nome="B", livello_minimo="I", bloccante=True)
        self.ab = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="I")
        # O + L bloccante: media U, tetto L → L con la regola di default.
        comp.registra_livelli(self.ab, {self.v1.pk: "O", self.v2.pk: "L"})
        self.ab.refresh_from_db()

    def test_simula_non_salva(self):
        from .services import mansionario_regole as reg

        self.assertEqual(self.ab.livello, "L")
        imp = reg.simula("U", "MEDIA", 2)
        self.assertEqual(imp.n_cambi, 1)
        self.assertEqual((imp.cambi[0]["livello_prima"], imp.cambi[0]["livello_dopo"]), ("L", "U"))
        self.assertEqual((imp.operativi_prima, imp.operativi_dopo), (0, 1))
        self.config.refresh_from_db()
        self.assertEqual(self.config.regola_multivoce, "MEDIA_TETTO")
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "L")

    def test_applica_salva_e_ricalcola(self):
        n_storico = AbilitazioneMacchinaStorico.objects.count()
        r = self.client.post(reverse("anagrafica:mansionario_regole"),
                             {"soglia": "U", "regola": "MEDIA", "uomo_solo": "3", "azione": "applica"})
        self.assertRedirects(r, reverse("anagrafica:mansionario_regole"), fetch_redirect_response=False)
        self.config.refresh_from_db()
        self.assertEqual((self.config.regola_multivoce, self.config.soglia_uomo_solo), ("MEDIA", 3))
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "U")
        self.assertEqual(AbilitazioneMacchinaStorico.objects.count(), n_storico + 1)

    def test_pagina_e_prova(self):
        r = self.client.get(reverse("anagrafica:mansionario_regole"))
        self.assertContains(r, "Regole del Mansionario")
        self.assertNotContains(r, "{#")
        r = self.client.post(reverse("anagrafica:mansionario_regole"),
                             {"soglia": "U", "regola": "MEDIA", "uomo_solo": "2", "azione": "prova"})
        self.assertContains(r, "Cosa cambierebbe")
        self.assertContains(r, "Applica le regole e ricalcola i livelli")
        r = self.client.post(reverse("anagrafica:mansionario_regole"),
                             {"soglia": "Z", "regola": "MEDIA", "uomo_solo": "2", "azione": "prova"})
        self.assertContains(r, "Scegli la soglia operativa")

    def test_permessi(self):
        with patch("anagrafica.views_mansionario._puo_valutare", return_value=False):
            r = self.client.post(reverse("anagrafica:mansionario_regole"),
                                 {"soglia": "O", "regola": "MIN", "uomo_solo": "2", "azione": "applica"})
        self.assertEqual(r.status_code, 302)
        self.config.refresh_from_db()
        self.assertEqual(self.config.soglia_operativa, "U")
