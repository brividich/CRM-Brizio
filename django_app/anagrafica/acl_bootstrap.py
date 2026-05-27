from __future__ import annotations

from core.acl_bootstrap_base import run_bootstrap

_BOOTSTRAP_CACHE_KEY = "anagrafica_acl_bootstrap_v2"

_PULSANTI_DEFINITIONS = [
    {"modulo": "anagrafica", "codice": "anagrafica_index", "label": "Anagrafica - Dashboard", "url": "/anagrafica/", "hide": False},
    {"modulo": "anagrafica", "codice": "anagrafica_dipendenti", "label": "Anagrafica - Lista dipendenti", "url": "/anagrafica/dipendenti/", "hide": False},
    # NOTE: i pulsanti "Fornitori" sono ora gestiti dal modulo `fornitori`
    # (vedere fornitori/acl_bootstrap.py se creato in seguito).
    {"modulo": "anagrafica", "codice": "anagrafica_ruoli_operativi", "label": "Anagrafica - Ruoli operativi", "url": "/anagrafica/ruoli-operativi/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_mansioni", "label": "Anagrafica - Mansioni catalogo", "url": "/anagrafica/mansioni/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_qualifiche", "label": "Anagrafica - Qualifiche catalogo", "url": "/anagrafica/qualifiche/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_widget_layout", "label": "Anagrafica - API widget layout", "url": "/anagrafica/api/widget-layout/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_impostazioni_widget", "label": "Anagrafica - Impostazioni permessi widget", "url": "/anagrafica/impostazioni-widget/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_civile_save", "label": "Anagrafica - Salva anagrafica civile dipendente", "url": "/anagrafica/dipendenti/0/anagrafica-civile/salva/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_aziendale_save", "label": "Anagrafica - Salva anagrafica aziendale dipendente", "url": "/anagrafica/dipendenti/0/anagrafica-aziendale/salva/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_dipendenti_report", "label": "Anagrafica - Report/export dipendenti", "url": "/anagrafica/dipendenti/report/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_aree", "label": "Anagrafica - Aree aziendali catalogo", "url": "/anagrafica/aree/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_ruoli_aziendali", "label": "Anagrafica - Ruoli aziendali catalogo", "url": "/anagrafica/ruoli-aziendali/", "hide": True},
    # ── Formazione HR (PATCH-01 stub — URL definitivi in PATCH-02/03) ──────
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_dashboard", "label": "Formazione - Dashboard", "url": "/anagrafica/formazione/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_piani", "label": "Formazione - Piani formativi", "url": "/anagrafica/formazione/piani/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_corsi", "label": "Formazione - Corsi", "url": "/anagrafica/formazione/corsi/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_sessioni", "label": "Formazione - Sessioni", "url": "/anagrafica/formazione/sessioni/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_istruttori", "label": "Formazione - Istruttori", "url": "/anagrafica/formazione/istruttori/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_scadenzario", "label": "Formazione - Scadenzario", "url": "/anagrafica/formazione/scadenzario/", "hide": True},
    {"modulo": "anagrafica", "codice": "anagrafica_formazione_export", "label": "Formazione - Export Excel", "url": "/anagrafica/formazione/export/", "hide": True},
]


def bootstrap_anagrafica_acl_endpoints(force: bool = False) -> None:
    run_bootstrap(
        _PULSANTI_DEFINITIONS,
        _BOOTSTRAP_CACHE_KEY,
        "anagrafica",
        icona="users",
        section="anagrafica_api",
        force=force,
    )
