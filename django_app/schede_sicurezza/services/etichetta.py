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


def _dpi(prodotto: ProdottoChimico) -> list[dict]:
    """DPI obbligatori del prodotto: immagine caricata nella categoria o icona dello sprite."""
    from dpi.models import normalizza_icona_dpi

    voci = []
    for categoria in prodotto.dpi_obbligatori.filter(is_active=True).order_by("order_index", "nome"):
        voci.append({
            "nome": categoria.nome,
            "immagine": categoria.immagine_url,
            "icona": normalizza_icona_dpi(categoria.icona_emoji),
        })
    return voci


def _disponi_segnali(n_ghs: int, n_dpi: int, larghezza: float, altezza: float) -> tuple[float, int, int, bool]:
    """Lato, righe, segnali per riga e se GHS e DPI vanno su righe separate.

    Tutti i segnali hanno lo stesso lato. Se stanno su una riga sola restano in fila
    (prima i pittogrammi di pericolo, poi i DPI); su piu' righe i DPI ripartono a
    capo, cosi' i due gruppi non si mescolano. Si sceglie la disposizione (al
    massimo 3 righe) che li fa piu' grandi.
    """
    n = n_ghs + n_dpi
    if not n:
        return 0.0, 0, 0, False

    def lato_per(per_riga: int, righe: int) -> float:
        in_larghezza = (larghezza - (per_riga - 1) * GAP_PITTOGRAMMI_MM) / per_riga
        lato = min(LATO_PITTOGRAMMA_MAX_MM, in_larghezza, (altezza - (righe - 1) * GAP_PITTOGRAMMI_MM) / righe)
        # Sotto il minimo si prende altezza al nome, ma mai larghezza: la fila non esce di lato.
        return max(lato, min(LATO_PITTOGRAMMA_MIN_MM, in_larghezza))

    candidati = [(lato_per(n, 1), 1, n, False)]
    if n_ghs and n_dpi:
        for per_riga in range(1, max(n_ghs, n_dpi) + 1):
            righe = math.ceil(n_ghs / per_riga) + math.ceil(n_dpi / per_riga)
            if righe <= 3:
                candidati.append((lato_per(per_riga, righe), righe, per_riga, True))
    else:
        for righe in (2, 3):
            if righe <= n:
                per_riga = math.ceil(n / righe)
                candidati.append((lato_per(per_riga, righe), righe, per_riga, False))
    # A parita' di lato (al decimo di mm) vince la disposizione con meno righe.
    lato, righe, per_riga, separati = max(candidati, key=lambda c: (round(c[0], 1), -c[1]))
    return lato, righe, per_riga, separati


def impagina(impostazioni: ImpostazioniEtichetta, prodotto: ProdottoChimico) -> dict:
    """Contenuti e misure dell'etichetta di ``prodotto``."""
    pittogrammi = (
        ghs.dettaglio(prodotto.pittogrammi_effettivi(prodotto.scheda_corrente()))
        if impostazioni.mostra_pittogrammi else []
    )
    dpi = _dpi(prodotto) if impostazioni.mostra_dpi else []
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

    lato, righe_pittogrammi, per_riga, separati = _disponi_segnali(
        len(pittogrammi), len(dpi), colonna_w, spazio,
    )
    n = len(pittogrammi) + len(dpi)
    pittogrammi_h = righe_pittogrammi * lato + max(righe_pittogrammi - 1, 0) * GAP_PITTOGRAMMI_MM

    resto_nome = corpo_h - logo_h - extra_h - pittogrammi_h - (GAP_MM if n else 0.0)
    righe_nome = max(1, min(4, int(resto_nome // riga_nome_h)))

    return {
        "pittogrammi": pittogrammi,
        "dpi": dpi,
        "segnali_separati": separati,
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
            "segnali_w": _mm(per_riga * lato + max(per_riga - 1, 0) * GAP_PITTOGRAMMI_MM),
            "fascia": _mm(fascia_h),
        },
    }
