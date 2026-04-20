"""Generatore xlsx MOD.073 VRF Rev.10 dalla compilazione online.

Apre il template distribuito con il codice e scrive i valori compilati sulle
celle canoniche definite in vrf_catalog. Le formule originali del template
(medie, max, K x R, totali) restano intatte: Excel le ricalcola alla prima
apertura. La sorgente di verita' per i totali mostrati in portale resta
pero' VRFRiskAssessment.total_* (cache server-side).

API:
    build_vrf_xlsx(project, assessment) -> bytes
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from . import vrf_catalog

_TEMPLATE_PATH = Path(__file__).parent / "vrf_template" / vrf_catalog.TEMPLATE_FILENAME


def _coerce_header_value(key: str, value: Any) -> Any:
    if value is None:
        return ""
    return value


def build_vrf_xlsx(project, assessment) -> bytes:
    """Ritorna i bytes di un .xlsx compilato per il progetto.

    project: tasks.models.Project (legge vrf_quote_number, part_number, ...)
    assessment: tasks.models.VRFRiskAssessment | None — se None scrive solo header.
    """
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template VRF non trovato: {_TEMPLATE_PATH}")

    wb = load_workbook(_TEMPLATE_PATH)
    ws = wb[vrf_catalog.TEMPLATE_SHEET] if vrf_catalog.TEMPLATE_SHEET in wb.sheetnames else wb.active

    header_values = {
        "vrf_quote_number": getattr(project, "vrf_quote_number", "") or "",
        "versione":         getattr(project, "versione", "") or "",
        "part_number":      getattr(project, "part_number", "") or "",
        "vrf_description":  getattr(project, "vrf_description", "") or "",
        "vrf_esp":          getattr(project, "vrf_esp", "") or "",
        "client_name":      getattr(project, "client_name", "") or "",
    }
    for key, cell in vrf_catalog.HEADER_CELLS.items():
        ws[cell] = _coerce_header_value(key, header_values.get(key))

    data = (assessment.data if assessment else None) or {}
    risks_data = data.get("risks") or {}

    for risk in vrf_catalog.RISKS:
        r_code = risk["code"]
        r_info = risks_data.get(r_code) or {}
        k_vals = r_info.get("k") or risk["k_default"]
        subs = r_info.get("subs") or {}
        for ph in vrf_catalog.PHASES:
            ph_key = ph["key"]
            k_cell = f"{ph['k_col']}{risk['row']}"
            try:
                ws[k_cell] = int(k_vals.get(ph_key, risk["k_default"][ph_key]))
            except (TypeError, ValueError):
                ws[k_cell] = risk["k_default"][ph_key]
            for sub in risk["sub_parameters"]:
                v = (subs.get(sub["code"]) or {}).get(ph_key)
                cell = f"{ph['input_col']}{sub['row']}"
                if v is None or v == "":
                    ws[cell] = None
                else:
                    try:
                        ws[cell] = int(v)
                    except (TypeError, ValueError):
                        ws[cell] = None

    buffer = io.BytesIO()
    wb.save(buffer)
    wb.close()
    return buffer.getvalue()


def vrf_filename_for(project) -> str:
    parts = []
    if getattr(project, "kickoff_number", None):
        parts.append(f"KICKOFF-{project.kickoff_number}")
    if getattr(project, "part_number", ""):
        parts.append(str(project.part_number).replace("/", "-").replace(" ", "_"))
    parts.append("VRF_MOD073_Rev10")
    return "_".join(parts) + ".xlsx"
