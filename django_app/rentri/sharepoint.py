"""Allineamento del registro con la lista SharePoint RENTRI (Microsoft Graph).

Il registro del portale fa fede. SharePoint è una copia: se non risponde il
movimento resta salvato, l'errore finisce in ``sync_errore`` del movimento e
nel log, e il comando ``rentri_sync_riprova`` lo reinvia.
"""
from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone as dt_timezone

import requests
from django.utils import timezone

from config.env_config import get_first_env_value

from .models import RegistroRifiuti

logger = logging.getLogger(__name__)

def _is_placeholder(value: str) -> bool:
    return not value or value.startswith("<") and value.endswith(">")


def _graph_settings() -> dict[str, str]:
    return {
        "tenant_id": get_first_env_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id": get_first_env_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
        "site_id": get_first_env_value("GRAPH_SITE_ID"),
        "list_id_rentri": get_first_env_value("GRAPH_LIST_ID_RENTRI"),
    }


def _graph_configured() -> bool:
    gs = _graph_settings()
    required = ("tenant_id", "client_id", "client_secret", "site_id", "list_id_rentri")
    return all(not _is_placeholder(gs.get(k, "")) for k in required)


def _graph_base_url() -> str:
    gs = _graph_settings()
    return (
        f"https://graph.microsoft.com/v1.0/sites/{gs['site_id']}"
        f"/lists/{gs['list_id_rentri']}/items"
    )


def _acquire_graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    resp = requests.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _graph_token() -> str:
    if not _graph_configured():
        raise RuntimeError("Configurazione Graph incompleta per RENTRI")
    gs = _graph_settings()
    return _acquire_graph_token(gs["tenant_id"], gs["client_id"], gs["client_secret"])


def _graph_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_graph_token()}", "Content-Type": "application/json"}


def _graph_get_all() -> list[dict]:
    url = f"{_graph_base_url()}?expand=fields&$top=500"
    rows: list[dict] = []
    while url:
        r = requests.get(url, headers=_graph_headers(), timeout=25)
        if r.status_code != 200:
            raise RuntimeError(f"Graph GET {r.status_code}: {r.text[:300]}")
        payload = r.json()
        rows.extend(payload.get("value", []) or [])
        url = payload.get("@odata.nextLink")
    return rows


def _graph_create(fields_payload: dict) -> tuple[bool, dict | str]:
    r = requests.post(
        _graph_base_url(),
        headers=_graph_headers(),
        json={"fields": fields_payload},
        timeout=20,
    )
    if r.status_code in (200, 201):
        return True, r.json()
    return False, r.text


def _graph_update(item_id: str, fields_payload: dict) -> tuple[bool, dict | str]:
    r = requests.patch(
        f"{_graph_base_url()}/{item_id}/fields",
        headers=_graph_headers(),
        json=fields_payload,
        timeout=20,
    )
    if r.status_code in (200, 204):
        if not r.text:
            return True, {}
        try:
            return True, r.json()
        except Exception:
            return True, {}
    return False, r.text


def _graph_delete(item_id: str) -> tuple[bool, str]:
    r = requests.delete(f"{_graph_base_url()}/{item_id}", headers=_graph_headers(), timeout=20)
    if r.status_code in (200, 202, 204):
        return True, ""
    if r.status_code == 404:
        try:
            payload = r.json()
        except ValueError:
            payload = {}
        error_code = str((payload.get("error") or {}).get("code") or "").strip()
        if error_code == "itemNotFound":
            return True, ""
    return False, r.text


# ── Field mapping helpers ─────────────────────────────────────────────────────


def _note_sp(registro: RegistroRifiuti) -> str:
    """Note per SharePoint: un movimento annullato lo dichiara in testa."""
    note = registro.note_rentri or ""
    if registro.annullato:
        return f"[ANNULLATO: {registro.motivo_annullamento}] {note}".strip()
    return note


def _to_sp_fields(registro: RegistroRifiuti) -> dict:
    """Convert a RegistroRifiuti instance to SharePoint field dict."""
    def _dec(v):
        return float(v) if v is not None else None

    fields: dict = {
        "Data": registro.data.isoformat() if registro.data else None,
        "IDRegistrazione": registro.id_registrazione or "",
        "Rif_x002e_Op": registro.rif_op or "",
        "Codice": registro.codice or "",
        "Quantit_x00e0_": _dec(registro.quantita),
        "Carico_x002f_Scarico": registro.carico_scarico or "",
        "RentriSI_x002f_NO": registro.rentri_si_no,
        "Salva": registro.salva,
        "NOTERENTRI": _note_sp(registro),
        "Pericolosit_x00e0_": registro.pericolosita or "",
        "RettificaScarico": _dec(registro.rettifica_scarico),
        "ARRIVOFIR": registro.arrivo_fir or "",
    }
    if registro.aggiornato:
        aggiornato_dt = registro.aggiornato
        if timezone.is_naive(aggiornato_dt):
            aggiornato_dt = timezone.make_aware(aggiornato_dt, timezone.get_current_timezone())
        aggiornato_dt = aggiornato_dt.astimezone(dt_timezone.utc)
        fields["Aggiornato"] = aggiornato_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # Remove None values to avoid SP errors on non-nullable fields
    return {k: v for k, v in fields.items() if v is not None}


def _from_sp_item(item: dict) -> dict:
    """Map a SharePoint item to RegistroRifiuti field values."""
    fields = item.get("fields") or {}

    def _as_bool(v) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        try:
            return bool(int(v))
        except Exception:
            return str(v).strip().lower() in {"1", "true", "yes", "on", "si"}

    def _as_decimal(v):
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    def _parse_date(v):
        if not v:
            return None
        try:
            return datetime.fromisoformat(str(v)[:10]).date()
        except Exception:
            return None

    def _parse_dt(v):
        if not v:
            return None
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, dt_timezone.utc)
            return timezone.localtime(dt, timezone.get_current_timezone()).replace(tzinfo=None)
        except Exception:
            return None

    return {
        "sharepoint_item_id": str(item.get("id") or ""),
        "data": _parse_date(fields.get("Data")),
        "id_registrazione": str(fields.get("IDRegistrazione") or "").strip(),
        "rif_op": str(fields.get("Rif_x002e_Op") or "").strip(),
        "codice": str(fields.get("Codice") or "").strip(),
        "quantita": _as_decimal(fields.get("Quantit_x00e0_")),
        "carico_scarico": str(fields.get("Carico_x002f_Scarico") or "").strip(),
        "rentri_si_no": _as_bool(fields.get("RentriSI_x002f_NO")),
        "salva": _as_bool(fields.get("Salva")),
        "note_rentri": str(fields.get("NOTERENTRI") or "").strip(),
        "pericolosita": str(fields.get("Pericolosit_x00e0_") or "").strip(),
        "rettifica_scarico": _as_decimal(fields.get("RettificaScarico")),
        "arrivo_fir": str(fields.get("ARRIVOFIR") or "").strip(),
        "aggiornato": _parse_dt(fields.get("Aggiornato")),
    }


def sincronizza(registro: RegistroRifiuti) -> bool:
    """Invia un movimento a SharePoint (crea o aggiorna). Mai bloccante.

    Ritorna ``True`` se allineato (o Graph non configurato), ``False`` se
    l'invio è fallito: in quel caso l'errore resta su ``sync_errore``.
    """
    if not _graph_configured():
        return True
    errore = ""
    try:
        fields = _to_sp_fields(registro)
        if registro.sharepoint_item_id:
            ok, result = _graph_update(registro.sharepoint_item_id, fields)
        else:
            ok, result = _graph_create(fields)
            if ok and isinstance(result, dict):
                sp_id = str((result.get("id") or (result.get("fields") or {}).get("id") or "")).strip()
                if sp_id:
                    RegistroRifiuti.objects.filter(pk=registro.pk).update(sharepoint_item_id=sp_id)
                    registro.sharepoint_item_id = sp_id
        if not ok:
            errore = f"SharePoint ha rifiutato l'invio: {str(result)[:300]}"
    except Exception as exc:  # noqa: BLE001 - rete, token, risposta non JSON
        logger.warning("RENTRI: invio a SharePoint fallito per il movimento %s", registro.pk, exc_info=True)
        errore = f"SharePoint non raggiungibile: {type(exc).__name__}"
    errore = errore[:500]
    if errore != (registro.sync_errore or ""):
        RegistroRifiuti.objects.filter(pk=registro.pk).update(sync_errore=errore)
        registro.sync_errore = errore
    return not errore


def pull(utente: str = "") -> dict:
    """Legge la lista SharePoint e porta nel portale i movimenti nuovi.

    Il portale fa fede: un movimento già presente si aggiorna solo se è ancora
    una bozza e SharePoint è più recente; consolidati e annullati non si toccano.
    Un elemento nuovo senza tipo riconoscibile (C/O/M/R) non si indovina: viene
    scartato e contato.
    """
    items = _graph_get_all()
    creati = aggiornati = invariati = scartati = 0
    for item in items:
        sp_id = str(item.get("id") or "").strip()
        if not sp_id:
            continue
        mapped = _from_sp_item(item)
        if not mapped.get("data"):
            scartati += 1
            continue
        existing = RegistroRifiuti.objects.filter(sharepoint_item_id=sp_id).first()
        if existing:
            sp_agg = mapped.get("aggiornato")
            loc_agg = timezone.localtime(existing.updated_at).replace(tzinfo=None) if existing.updated_at else None
            if existing.bloccato or not sp_agg or (loc_agg and sp_agg <= loc_agg):
                invariati += 1
                continue
            mapped.pop("id_registrazione", None)  # il numero non cambia mai
            for campo, valore in mapped.items():
                setattr(existing, campo, valore)
            existing.save()
            aggiornati += 1
            continue
        tipo = str(mapped.get("carico_scarico") or "").strip().upper()[:1]
        if tipo not in ("C", "O", "M", "R"):
            scartati += 1
            continue
        RegistroRifiuti.objects.create(tipo=tipo, origine="sharepoint", inserito_da=utente[:200], **mapped)
        creati += 1
    return {"created": creati, "updated": aggiornati, "unchanged": invariati, "skipped": scartati, "total": len(items)}
