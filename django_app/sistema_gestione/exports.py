"""Export PDF/XLSX della Dichiarazione di applicabilità (MOD.165 Control Matrix)."""
from __future__ import annotations

from django.utils import timezone

from report_conformita.exports import PdfSection, render_pdf
from report_conformita.registry import TONE_DANGER, TONE_OK, TONE_WARN, Kpi

from .models import SoaRevisione
from .services.soa import statistiche

COLONNE = [
    "Controllo", "Titolo", "Applicato (0-4)", "Vulnerabilità", "Riferimenti",
    "Giustificazione", "Obbligo", "Azione / responsabile / scadenza",
]


def _fmt_utente(utente) -> str:
    if not utente:
        return ""
    return (utente.get_full_name() or utente.get_username()).strip()


def _righe(revisione: SoaRevisione, oggi):
    righe, toni = [], []
    for voce in revisione.voci.select_related("controllo", "ofi"):
        azione = ""
        if (voce.azione or "").strip():
            parti = [voce.azione.strip()]
            if voce.responsabile:
                parti.append(voce.responsabile)
            if voce.scadenza:
                parti.append(f"entro {voce.scadenza:%d/%m/%Y}")
            if voce.ofi_id:
                parti.append(f"OFI n. {voce.ofi.numero}")
            azione = " · ".join(parti)
        righe.append([
            voce.controllo.codice, voce.controllo.titolo,
            "Non applicato" if voce.livello == 0 else voce.livello,
            voce.vulnerabilita if voce.livello else "",
            voce.riferimenti, voce.giustificazione, voce.obblighi_label, azione,
        ])
        if voce.azione_scaduta(oggi):
            toni.append(TONE_DANGER)
        elif 0 < voce.livello < 4:
            toni.append(TONE_WARN)
        else:
            toni.append("")
    return righe, toni


def kpi_revisione(revisione: SoaRevisione, oggi=None) -> list[Kpi]:
    oggi = oggi or timezone.localdate()
    s = statistiche(revisione, oggi)
    percentuale = f"{s.percentuale_piena}%" if s.percentuale_piena is not None else "n/d"
    return [
        Kpi("Controlli", s.totale),
        Kpi("Pienamente applicati", s.pieni, TONE_OK, f"{percentuale} degli applicabili"),
        Kpi("Applicati in parte", s.parziali, TONE_WARN if s.parziali else ""),
        Kpi("Esclusi", s.esclusi, hint="con giustificazione" if not s.senza_giustificazione else ""),
        Kpi("Azioni aperte", s.azioni_aperte),
        Kpi("Azioni scadute", s.azioni_scadute, TONE_DANGER if s.azioni_scadute else TONE_OK),
    ]


def intestazione(revisione: SoaRevisione) -> list[str]:
    righe = [f"Stato: {revisione.get_stato_display()}."]
    if revisione.preparata_da_id:
        righe.append(f"Preparata da {_fmt_utente(revisione.preparata_da)}"
                     + (f", proposta il {timezone.localtime(revisione.proposta_il):%d/%m/%Y %H:%M}." if revisione.proposta_il else "."))
    if revisione.approvata_il:
        righe.append(
            f"Approvata digitalmente da {_fmt_utente(revisione.approvata_da)} "
            f"il {timezone.localtime(revisione.approvata_il):%d/%m/%Y %H:%M} (registrato nel portale)."
        )
    else:
        righe.append("Non ancora approvata: documento di lavoro, non in vigore.")
    if revisione.motivo:
        righe.append(f"Motivo della revisione: {revisione.motivo}.")
    righe.append("Scala: 4 = controllo pienamente applicato, 0 = non applicato (escluso con giustificazione).")
    return righe


def soa_pdf(revisione: SoaRevisione) -> bytes:
    oggi = timezone.localdate()
    righe, toni = _righe(revisione, oggi)
    return render_pdf(
        title=f"Dichiarazione di applicabilità - Rev.{revisione.numero}",
        subtitle="ISO/IEC 27001:2022 §6.1.3 d) | MOD.165 Control Matrix",
        intro=intestazione(revisione),
        sections=[PdfSection(
            title="", clausole="ISO/IEC 27001:2022 §6.1.3 d) · Allegato A (ISO/IEC 27002:2022)",
            kpis=kpi_revisione(revisione, oggi), columns=COLONNE, rows=righe, row_tones=toni,
        )],
    )


def soa_xlsx(revisione: SoaRevisione) -> bytes:
    from core.excel_export import build_xlsx_bytes

    righe, _toni = _righe(revisione, timezone.localdate())
    return build_xlsx_bytes(
        columns=COLONNE,
        rows=righe,
        sheet_title=f"SoA Rev.{revisione.numero}",
        title=f"Dichiarazione di applicabilità - Rev.{revisione.numero}",
        subtitle=" ".join(intestazione(revisione)[:3]),
        filters_label=f"Generato il {timezone.localtime():%d/%m/%Y %H:%M}",
    )


def riesame_pdf(riesame) -> bytes:
    """Verbale MOD.062: i dati del portale nella sequenza del modulo. Non ne replica le tabelle dei rischi."""
    from .services.riesame import obiettivi_precedenti

    def _nome(utente) -> str:
        return _fmt_utente(utente)

    if riesame.stato == riesame.STATO_APPROVATO:
        precedenti = [[o["descrizione"], o["risultato_atteso"], o["stato"], o["nota"]]
                      for o in riesame.fotografia_precedenti]
    else:
        precedenti = [[o.descrizione, o.risultato_atteso, o.get_stato_display(), o.nota]
                      for o in obiettivi_precedenti(riesame)]
    argomenti = []
    for a in riesame.argomenti.all():
        indicatori = "; ".join(f"{k['label']}: {k['value']}" for r in a.indicatori for k in r["kpi"])
        argomenti.append([a.codice, a.titolo, indicatori, a.analisi])
    sezioni = [
        PdfSection(title="Partecipanti", clausole="", kpis=[], columns=["Funzione", "Nominativo"],
                   rows=[[p.funzione, p.nominativo] for p in riesame.partecipanti.select_related("utente")],
                   notes=[f"Documenti esaminati: {riesame.documenti_esaminati or '-'}"]),
        PdfSection(title="Obiettivi dei riesami precedenti", clausole="", kpis=[],
                   columns=["Obiettivo", "Risultato atteso", "Esito", "Livello raggiunto e motivi"], rows=precedenti),
        PdfSection(title="Argomenti e decisioni", clausole="", kpis=[],
                   columns=["Rif.", "Argomento", "Indicatori", "Analisi"], rows=argomenti),
        PdfSection(title="Nuovi obiettivi", clausole="", kpis=[],
                   columns=["Obiettivo", "Processo", "Indicatore", "Risultato atteso", "Responsabile", "Risorse", "Scadenza"],
                   rows=[[o.descrizione, o.processo.codice if o.processo_id else "", o.indicatore, o.risultato_atteso,
                          _nome(o.responsabile), o.risorse, f"{o.scadenza:%d/%m/%Y}" if o.scadenza else ""]
                         for o in riesame.obiettivi.select_related("processo", "responsabile")]),
    ]
    if riesame.approvato_il:
        firma = f"Approvato il {timezone.localtime(riesame.approvato_il):%d/%m/%Y %H:%M} da {_nome(riesame.approvato_da)}."
    else:
        firma = f"{riesame.get_stato_display()}: non ancora approvato."
    def _data(valore) -> str:
        return f"{valore:%d/%m/%Y}" if valore else "-"

    intro = [f"Riunioni: riesame intermedio {_data(riesame.data_intermedio)}, pianificazione strategica "
             f"{_data(riesame.data_pianificazione)}, verbale {_data(riesame.data)}. "
             f"Dati dal {riesame.periodo_dal:%d/%m/%Y} al {riesame.periodo_al:%d/%m/%Y}.", firma]
    return render_pdf(title="Verbale di riesame del Sistema di Gestione Integrato",
                      subtitle=f"MOD.062 VRS | Anno {riesame.anno}", sections=sezioni, intro=intro)
