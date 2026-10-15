"""Impaginazione dell'etichetta da contenitore.

Le misure dipendono da formato e contenuto (quanti pittogrammi, se c'e' la riga
emergenza...): si calcolano qui, in millimetri, cosi' il template resta solo
disposizione. I valori escono gia' come stringhe con il punto decimale: nel
template la localizzazione italiana li scriverebbe con la virgola, che in CSS
non vale.
"""
from __future__ import annotations

import math

from django.templatetags.static import static

from .. import pittogrammi as ghs
from ..models import ImpostazioniEtichetta, ProdottoChimico

PADDING_MM = 2.5
GAP_MM = 2.0
GAP_PITTOGRAMMI_MM = 0.8
PT_IN_MM = 0.3528
LATO_PITTOGRAMMA_MAX_MM = 16.0
LATO_PITTOGRAMMA_MIN_MM = 6.0


def _mm(valore: float) -> str:
    return f"{max(valore, 0):.1f}"


def logo_url(impostazioni: ImpostazioniEtichetta) -> str:
    """Logo dell'etichetta: quello caricato qui, poi il logo del portale, poi il predefinito."""
    if impostazioni.logo:
        try:
            return impostazioni.logo.url
        except Exception:
            pass
    try:
        from core.branding import get_portal_branding

        branding = get_portal_branding()
        portale = getattr(branding, "brand_logo_full", "") or getattr(branding, "brand_logo_compact", "")
    except Exception:
        portale = ""
    return portale or static("core/img/logo_novicrom.png")


def impagina(impostazioni: ImpostazioniEtichetta, prodotto: ProdottoChimico) -> dict:
    """Contenuti e misure dell'etichetta di ``prodotto``."""
    pittogrammi = (
        ghs.dettaglio(prodotto.pittogrammi_effettivi(prodotto.scheda_corrente()))
        if impostazioni.mostra_pittogrammi else []
    )
    riga_extra = impostazioni.valore_riga_extra(prodotto)
    larghezza, altezza = float(impostazioni.larghezza_mm), float(impostazioni.altezza_mm)

    fascia_h = 4.5 if impostazioni.testo_emergenza else 0.0
    corpo_h = altezza - 2 * PADDING_MM - (fascia_h + GAP_MM if fascia_h else 0.0)
    testo_qr_h = 3.2 if impostazioni.testo_qr else 0.0
    qr = min(corpo_h - testo_qr_h, larghezza * 0.42)
    colonna_w = larghezza - 2 * PADDING_MM - qr - GAP_MM

    riga_nome_h = impostazioni.nome_dimensione_pt * PT_IN_MM * 1.1
    logo_h = float(impostazioni.logo_altezza_mm) + GAP_MM * 0.75 if impostazioni.mostra_logo else 0.0
    extra_h = 3.5 if riga_extra else 0.0
    # Spazio per i pittogrammi: quello che resta garantendo due righe di nome
    # (il nome e' l'informazione principale: meglio pittogrammi piu' piccoli).
    spazio = corpo_h - logo_h - 2 * riga_nome_h - extra_h - GAP_MM

    n = len(pittogrammi)
    lato = 0.0
    righe_pittogrammi = 0
    if n:
        per_riga = n if n <= 4 else math.ceil(n / 2)
        righe_pittogrammi = math.ceil(n / per_riga)
        lato = min(
            LATO_PITTOGRAMMA_MAX_MM,
            (colonna_w - (per_riga - 1) * GAP_PITTOGRAMMI_MM) / per_riga,
            (spazio - (righe_pittogrammi - 1) * GAP_PITTOGRAMMI_MM) / righe_pittogrammi,
        )
        lato = max(lato, LATO_PITTOGRAMMA_MIN_MM)
    pittogrammi_h = righe_pittogrammi * lato + max(righe_pittogrammi - 1, 0) * GAP_PITTOGRAMMI_MM

    resto_nome = corpo_h - logo_h - extra_h - pittogrammi_h - (GAP_MM if n else 0.0)
    righe_nome = max(1, min(4, int(resto_nome // riga_nome_h)))

    return {
        "pittogrammi": pittogrammi,
        "riga_extra": riga_extra,
        "righe_nome": righe_nome,
        "mm": {
            "larghezza": _mm(larghezza),
            "altezza": _mm(altezza),
            "padding": _mm(PADDING_MM),
            "gap": _mm(GAP_MM),
            "qr": _mm(qr),
            "logo": _mm(impostazioni.logo_altezza_mm),
            "pittogramma": _mm(lato),
            "fascia": _mm(fascia_h),
        },
    }
