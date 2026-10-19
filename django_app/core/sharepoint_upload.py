"""Caricamento di un file in una cartella di SharePoint/OneDrive (Microsoft Graph).

Usato dall'export mensile dell'audit sigillato (``core.audit_sigilli``). Destinazione
in SiteConfig: ``audit_export_sp_drive_id`` (id della raccolta documenti) e
``audit_export_sp_cartella`` (percorso dentro la raccolta). Permesso applicativo:
``Sites.Selected`` con grant ``write`` sul sito (consigliato) o ``Sites.ReadWrite.All``.
La destinazione si imposta dal link della cartella: ``audit_sigilli --cartella-sharepoint``
(``configura_da_link``: API ``/shares`` di Graph + scrittura di prova del LEGGIMI).

File fino a 4 MB con un PUT; oltre, sessione di upload a blocchi. Il file non viene
mai sovrascritto (``@microsoft.graph.conflictBehavior=fail``): un export già
presente è un errore, non un rimpiazzo.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SIMPLE_MAX = 4 * 1024 * 1024
CHUNK = 5 * 320 * 1024  # multiplo di 320 KiB, come chiede Graph
TIMEOUT = 60


class SharePointUploadError(RuntimeError):
    pass


def destinazione() -> tuple[str, str]:
    from core.models import SiteConfig

    drive = str(SiteConfig.get("audit_export_sp_drive_id", "") or "").strip()
    cartella = str(SiteConfig.get("audit_export_sp_cartella", "") or "").strip().strip("/")
    return drive, cartella


def configurato() -> bool:
    drive, cartella = destinazione()
    return bool(drive and cartella)


def _token() -> str:
    from core.graph_utils import acquire_graph_token, is_placeholder_value
    from core.outlook_calendar import _graph_settings

    cfg = _graph_settings()
    if any(is_placeholder_value(v) for v in cfg.values()):
        raise SharePointUploadError("Credenziali Graph non configurate (GRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET).")
    return acquire_graph_token(cfg["tenant_id"], cfg["client_id"], cfg["client_secret"])


def _path_url(drive_id: str, path: str, suffix: str) -> str:
    return f"{GRAPH}/drives/{quote(drive_id, safe='!')}/root:/{quote(path, safe='/')}:/{suffix}"


def carica(nome_file: str, contenuto: bytes, *, drive_id: str | None = None, cartella: str | None = None) -> str:
    """Carica ``contenuto`` come ``<cartella>/<nome_file>``. Ritorna il webUrl."""
    import requests

    if drive_id is None or cartella is None:
        drive_id, cartella = destinazione()
    if not drive_id or not cartella:
        raise SharePointUploadError("Cartella SharePoint per l'export non configurata.")
    if "/" in nome_file or "\\" in nome_file or ".." in nome_file:
        raise SharePointUploadError("Nome file non valido.")
    path = f"{cartella.strip('/')}/{nome_file}"
    headers = {"Authorization": f"Bearer {_token()}"}

    if len(contenuto) <= SIMPLE_MAX:
        resp = requests.put(
            _path_url(drive_id, path, "content") + "?@microsoft.graph.conflictBehavior=fail",
            data=contenuto, headers={**headers, "Content-Type": "application/octet-stream"}, timeout=TIMEOUT,
        )
        if resp.status_code not in (200, 201):
            raise SharePointUploadError(_errore(resp))
        return str(resp.json().get("webUrl") or path)

    sess = requests.post(
        _path_url(drive_id, path, "createUploadSession"),
        json={"item": {"@microsoft.graph.conflictBehavior": "fail"}}, headers=headers, timeout=TIMEOUT,
    )
    if sess.status_code != 200:
        raise SharePointUploadError(_errore(sess))
    upload_url = sess.json().get("uploadUrl") or ""
    if not upload_url.startswith("https://"):
        raise SharePointUploadError("Sessione di upload non valida.")
    total = len(contenuto)
    resp = None
    for start in range(0, total, CHUNK):
        chunk = contenuto[start:start + CHUNK]
        end = start + len(chunk) - 1
        resp = requests.put(
            upload_url, data=chunk, timeout=TIMEOUT,
            headers={"Content-Length": str(len(chunk)), "Content-Range": f"bytes {start}-{end}/{total}"},
        )
        if resp.status_code not in (200, 201, 202):
            raise SharePointUploadError(_errore(resp))
    return str(resp.json().get("webUrl") or path) if resp is not None else path


LEGGIMI = "LEGGIMI-portale-audit.txt"
LEGGIMI_TESTO = (
    "Cartella dell'audit sigillato di NOVICROM HUB.\n"
    "Ogni mese il portale carica qui due file: audit-AAAA-MM.jsonl.gz (le azioni registrate) e\n"
    "audit-AAAA-MM.sigillo.json (l'impronta SHA-256 del mese, legata a quella del mese prima).\n"
    "Non modificare né cancellare i file: servono a dimostrare che il registro non è stato alterato.\n"
)


def _link_diretto(link: str) -> str:
    """Il link della barra degli indirizzi di una raccolta («…/Forms/AllItems.aspx?id=/sites/…/Cartella»)
    diventa l'indirizzo diretto della cartella; gli altri link restano come sono."""
    from urllib.parse import parse_qs, unquote, urlsplit

    parti = urlsplit(link)
    if parti.path.lower().endswith(".aspx"):
        ids = parse_qs(parti.query).get("id") or parse_qs(parti.query).get("RootFolder") or []
        if ids and ids[0].startswith("/"):
            return f"{parti.scheme}://{parti.netloc}{unquote(ids[0])}"
    return link


def risolvi_link(link: str) -> tuple[str, str, str]:
    """Da un link di cartella SharePoint (barra degli indirizzi o «Copia collegamento») ricava
    ``(drive_id, cartella, webUrl)`` con l'API ``/shares`` di Graph."""
    import base64
    from urllib.parse import urlsplit

    import requests

    link = (link or "").strip()
    host = urlsplit(link).hostname or ""
    if not link.startswith("https://") or not host.endswith(".sharepoint.com"):
        raise SharePointUploadError("Serve un link https://<azienda>.sharepoint.com/… di una cartella.")
    diretto = _link_diretto(link)
    codice = "u!" + base64.urlsafe_b64encode(diretto.encode("utf-8")).decode("ascii").rstrip("=")
    resp = requests.get(
        f"{GRAPH}/shares/{codice}/driveItem",
        headers={"Authorization": f"Bearer {_token()}"}, timeout=TIMEOUT,
    )
    if resp.status_code == 404:
        raise SharePointUploadError("Cartella non trovata: controlla il link (o l'app Graph non vede quel sito).")
    if resp.status_code != 200:
        raise SharePointUploadError(_errore(resp))
    item = resp.json()
    if "folder" not in item:
        raise SharePointUploadError("Il link non porta a una cartella.")
    if "root" in item:
        raise SharePointUploadError("Il link porta alla raccolta intera: crea e indica una cartella dentro la raccolta.")
    parent = item.get("parentReference") or {}
    drive_id = str(parent.get("driveId") or "")
    relativo = str(parent.get("path") or "").split("root:", 1)[-1] if "root:" in str(parent.get("path") or "") else ""
    cartella = f"{relativo.strip('/')}/{item.get('name') or ''}".strip("/")
    if not drive_id or not cartella:
        raise SharePointUploadError("Risposta di SharePoint incompleta: raccolta o percorso mancanti.")
    from urllib.parse import unquote

    return drive_id, unquote(cartella), str(item.get("webUrl") or "")


def configura_da_link(link: str) -> dict:
    """Ricava raccolta e cartella dal link, prova a scrivere il LEGGIMI (verifica il
    permesso di scrittura) e solo allora salva la destinazione in SiteConfig."""
    from core.models import SiteConfig

    drive_id, cartella, web_url = risolvi_link(link)
    try:
        carica(LEGGIMI, LEGGIMI_TESTO.encode("utf-8"), drive_id=drive_id, cartella=cartella)
        leggimi = "creato"
    except SharePointUploadError as exc:
        if "esiste già" not in str(exc):
            raise
        leggimi = "già presente"
    SiteConfig.set("audit_export_sp_drive_id", drive_id, "Audit sigillato: id della raccolta SharePoint")
    SiteConfig.set("audit_export_sp_cartella", cartella, "Audit sigillato: cartella dentro la raccolta")
    return {"drive_id": drive_id, "cartella": cartella, "web_url": web_url, "leggimi": leggimi}


def _errore(resp) -> str:
    code = ""
    try:
        code = str((resp.json().get("error") or {}).get("code") or "")
    except Exception:  # noqa: BLE001
        pass
    if resp.status_code in (401, 403):
        return f"SharePoint ha risposto {resp.status_code}: l'app Graph non ha il permesso di scrittura sul sito ({code})."
    if resp.status_code == 409:
        return "Il file esiste già nella cartella SharePoint: export non sovrascritto."
    return f"SharePoint ha risposto {resp.status_code} ({code or 'errore'})."
