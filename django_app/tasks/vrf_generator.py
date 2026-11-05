"""Generatore xlsx MOD.073 VRF dalla compilazione online.

Apre il template distribuito con il codice e scrive i valori compilati sulle
celle canoniche definite in vrf_catalog: intestazione, Probabilita' P dei 9
rischi, azioni correttive e firme. Le formule del template (R = P x D, TR)
restano intatte: Excel le ricalcola all'apertura. La sorgente di verita' per i
totali mostrati in portale resta VRFRiskAssessment.total_tr (cache server-side).

API:
    build_vrf_xlsx(project, assessment) -> bytes
    parse_vrf_xlsx(file_obj) -> dict  (shape di vrf_catalog.default_scores())
    read_header(ws) / select_sheet(wb)
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from core.excel_export import write_cell_at

from . import vrf_catalog

_TEMPLATE_PATH = Path(__file__).parent / "vrf_template" / vrf_catalog.TEMPLATE_FILENAME


def select_sheet(wb):
    """Foglio della scheda: quello del modulo, altrimenti il primo."""
    if vrf_catalog.TEMPLATE_SHEET in wb.sheetnames:
        return wb[vrf_catalog.TEMPLATE_SHEET]
    return wb.active


def read_header(ws) -> dict[str, str]:
    """Campi identificativi del file, mai None."""
    return {key: str(ws[cell].value or "").strip() for key, cell in vrf_catalog.HEADER_CELLS.items()}


def _firma(label: str, value: str) -> str:
    value = (value or "").strip()
    return f"{label}    {value}" if value else f"{label}    __________________"


def _data_it(value: str) -> str:
    """Data ISO del form (AAAA-MM-GG) -> GG/MM/AAAA per il foglio."""
    value = (value or "").strip()
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return f"{value[8:10]}/{value[5:7]}/{value[0:4]}"
    return value


def build_vrf_xlsx(project, assessment) -> bytes:
    """Ritorna i bytes di un .xlsx compilato per il progetto.

    project: tasks.models.Project (legge vrf_quote_number, part_number, ...)
    assessment: tasks.models.VRFRiskAssessment | None — se None scrive solo
    l'intestazione.
    """
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template VRF non trovato: {_TEMPLATE_PATH}")

    wb = load_workbook(_TEMPLATE_PATH)
    ws = select_sheet(wb)

    # Header: testo libero dal progetto (P/N, descrizione, cliente...). Passa da
    # core.excel_export.write_cell_at: `ws[cell] = "=..."` lo scriverebbe come
    # formula viva nel file scaricato (formula injection). Le P sotto restano
    # int/None, quindi non sono iniettabili e conservano le formule del template.
    for key, cell in vrf_catalog.HEADER_CELLS.items():
        valore = getattr(project, key, "") or ""
        if key == "vrf_description" and not valore:
            valore = (getattr(project, "description", "") or "")[:500]
        write_cell_at(ws, cell, valore)

    data = (assessment.data if assessment else None) or {}
    risks_data = data.get("risks") or {}

    for risk in vrf_catalog.RISKS:
        p = vrf_catalog.clamp_p((risks_data.get(risk["code"]) or {}).get("p"))
        ws[f"{vrf_catalog.P_COL}{risk['row']}"] = p
        ws[f"{vrf_catalog.D_COL}{risk['row']}"] = risk["d"]

    azioni = list(data.get("azioni") or [])
    for idx, cell in enumerate(vrf_catalog.AZIONI_CELLS):
        testo = str(azioni[idx]).strip() if idx < len(azioni) and azioni[idx] else ""
        write_cell_at(ws, cell, testo or None)

    firme = data.get("firme") or {}
    write_cell_at(ws, vrf_catalog.FIRMA_CELLS["in1"], _firma("IN1", firme.get("in1", "")))
    write_cell_at(ws, vrf_catalog.FIRMA_CELLS["em"], _firma("EM", firme.get("em", "")))
    for key in ("in1_data", "em_data"):
        valore = _data_it(firme.get(key, ""))
        write_cell_at(ws, vrf_catalog.FIRMA_CELLS[key], f"Data  {valore}" if valore else "Data")

    buffer = io.BytesIO()
    wb.save(buffer)
    wb.close()
    return buffer.getvalue()


def _strip_label(value: Any, label: str) -> str:
    testo = str(value or "").strip()
    if testo.upper().startswith(label.upper()):
        testo = testo[len(label):]
    testo = testo.strip().strip("_").strip()
    return testo


def _data_iso(value: Any) -> str:
    """Rilegge «Data  GG/MM/AAAA» (o un datetime) come AAAA-MM-GG; '' se non e' una data."""
    import datetime as _dt

    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.strftime("%Y-%m-%d")
    testo = _strip_label(value, "Data")
    try:
        return _dt.datetime.strptime(testo, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def parse_vrf_xlsx(file_obj) -> dict[str, Any]:
    """Legge un xlsx VRF (caricato o generato) e ritorna una struttura 'data'
    compatibile con VRFRiskAssessment.data / vrf_catalog.default_scores().

    Usata per pre-popolare la compilazione online a partire dal file gia'
    caricato dal kickoff."""
    wb = load_workbook(file_obj, data_only=True)
    try:
        ws = select_sheet(wb)
        data = vrf_catalog.default_scores()
        for risk in vrf_catalog.RISKS:
            data["risks"][risk["code"]]["p"] = vrf_catalog.clamp_p(ws[f"{vrf_catalog.P_COL}{risk['row']}"].value)
        data["azioni"] = [str(ws[c].value or "").strip() for c in vrf_catalog.AZIONI_CELLS]
        data["firme"] = {
            "in1": _strip_label(ws[vrf_catalog.FIRMA_CELLS["in1"]].value, "IN1"),
            "em": _strip_label(ws[vrf_catalog.FIRMA_CELLS["em"]].value, "EM"),
            "in1_data": _data_iso(ws[vrf_catalog.FIRMA_CELLS["in1_data"]].value),
            "em_data": _data_iso(ws[vrf_catalog.FIRMA_CELLS["em_data"]].value),
        }
        return data
    finally:
        wb.close()


def vrf_filename_for(project) -> str:
    parts = []
    if getattr(project, "kickoff_number", None):
        parts.append(f"KICKOFF-{project.kickoff_number}")
    if getattr(project, "part_number", ""):
        parts.append(str(project.part_number).replace("/", "-").replace(" ", "_"))
    parts.append("VRF_MOD073")
    return "_".join(parts) + ".xlsx"
