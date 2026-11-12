"""Richiesta assenza: al cambio del dipendente il capo si aggiorna anche a video.

La tendina «Capo reparto» ha più di 10 voci e tomselect-init.js la trasforma in
Tom Select: cambiare solo il <select> nativo aggiornava il pannello laterale ma
non la tendina visibile.
"""

from django.template.loader import render_to_string
from django.test import SimpleTestCase


def _render(**extra):
    capi = [{"Value": f"Capo {i}", "Email": f"capo{i}@example.com", "LookupId": i} for i in range(12)]
    ctx = {
        "form_data": {},
        "capi": capi,
        "dipendenti": [{"id": 7, "full_name": "Mario Rossi"}],
        "assenze_can_insert_for_others": True,
        "nome": "Utente Prova",
        **extra,
    }
    return render_to_string("assenze/pages/richiesta_assenze.html", ctx)


class CapoTomSelectTests(SimpleTestCase):
    def test_cambio_dipendente_passa_da_tom_select(self):
        html = _render()
        self.assertIn("/assenze/api/dipendente-capo", html)
        self.assertIn("el.tomselect.setValue(value, true)", html)
        self.assertIn("applicaCapo(capoIniziale, bloccatoIniziale)", html)
        # Niente più scrittura diretta sul select nativo, invisibile con Tom Select.
        self.assertNotIn("capoSel.selectedIndex = i", html)

    def test_blocco_per_chi_non_sceglie_il_capo(self):
        html = _render(assenze_can_choose_capo=False)
        self.assertIn('applicaCapo(data.capo_value || "", true)', html)
        html = _render(assenze_can_choose_capo=True)
        self.assertIn('applicaCapo(data.capo_value || "", false)', html)
