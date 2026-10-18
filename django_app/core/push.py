"""Notifiche push sul telefono/PC (Web Push, RFC 8030 + VAPID RFC 8292).

Push **senza contenuto**: al servizio push del produttore del browser (Google,
Mozilla, Microsoft, Apple) si manda solo il segnale «c'è qualcosa di nuovo»,
con il corpo vuoto. Il service worker (``/sw-notifiche.js``) riceve il segnale e
legge il testo dal portale con la sessione dell'utente
(``/api/notifiche/push/ultime/``). Così:

- nessun dato personale esce verso servizi esterni (solo l'evento e l'orario);
- non serve cifrare il payload (RFC 8291) né aggiungere dipendenze: basta la
  firma VAPID ES256, fatta con ``cryptography`` (già nelle dipendenze);
- fuori rete il portale non risponde e il browser mostra un testo generico.

Gli endpoint sono accettati solo verso i servizi push noti
(``endpoint_ammesso``): il server fa una POST verso l'indirizzo che il browser
gli comunica, e un indirizzo qualunque sarebbe una SSRF.

Configurazione: ``VAPID_PRIVATE_KEY`` (+ ``VAPID_SUBJECT``) nel ``.env``;
vuota = push spente ovunque. Vedi ``manage.py genera_chiavi_vapid``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from functools import lru_cache
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Servizi push dei browser supportati (suffisso dell'host, confine sul punto).
# Chrome/Edge su Android e desktop: FCM; Edge su Windows: WNS; Firefox: Mozilla
# autopush; Safari (macOS, iPhone con il portale aggiunto alla Home): Apple.
HOST_PUSH_AMMESSI: tuple[str, ...] = (
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)

TTL_SECONDI = 24 * 3600          # il servizio tiene il segnale al massimo un giorno
TIMEOUT_SECONDI = 10
MAX_ERRORI_CONSECUTIVI = 5       # poi l'iscrizione si disattiva da sola


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    value = (value or "").strip()
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@lru_cache(maxsize=4)
def _chiave_privata(raw: str):
    from cryptography.hazmat.primitives.asymmetric import ec

    numero = int.from_bytes(_b64url_decode(raw), "big")
    return ec.derive_private_key(numero, ec.SECP256R1())


def push_configurato() -> bool:
    """True se la chiave VAPID è presente e leggibile."""
    raw = str(getattr(settings, "VAPID_PRIVATE_KEY", "") or "").strip()
    if not raw:
        return False
    try:
        _chiave_privata(raw)
        return True
    except Exception:
        logger.error("VAPID_PRIVATE_KEY non valida: notifiche push spente.")
        return False


def chiave_pubblica() -> str:
    """Chiave pubblica VAPID (punto P-256 non compresso, base64url) per il browser."""
    if not push_configurato():
        return ""
    from cryptography.hazmat.primitives import serialization

    pub = _chiave_privata(settings.VAPID_PRIVATE_KEY.strip()).public_key()
    return _b64url(pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))


def genera_chiave_privata() -> str:
    """Nuova chiave privata VAPID in base64url (32 byte)."""
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return _b64url(key.private_numbers().private_value.to_bytes(32, "big"))


def endpoint_ammesso(endpoint: str) -> bool:
    """Solo https, porta standard, host di un servizio push noto."""
    try:
        parts = urlsplit(str(endpoint or "").strip())
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return False
    if parts.port not in (None, 443):
        return False
    host = parts.hostname.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in HOST_PUSH_AMMESSI)


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(str(endpoint or "").strip().encode("utf-8")).hexdigest()


def _vapid_header(endpoint: str) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(time.time()) + 12 * 3600,
        "sub": str(getattr(settings, "VAPID_SUBJECT", "") or "mailto:noreply@localhost"),
    }
    header = _b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    der = _chiave_privata(settings.VAPID_PRIVATE_KEY.strip()).sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    token = f"{header}.{payload}.{_b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={token}, k={chiave_pubblica()}"


def invia_segnale(iscrizione) -> bool:
    """Manda il segnale a un'iscrizione. Aggiorna stato ed errori. Non solleva."""
    import requests

    if not iscrizione.attiva or not push_configurato() or not endpoint_ammesso(iscrizione.endpoint):
        return False
    try:
        resp = requests.post(
            iscrizione.endpoint,
            data=b"",
            headers={
                "TTL": str(TTL_SECONDI),
                "Urgency": "normal",
                "Authorization": _vapid_header(iscrizione.endpoint),
                "Content-Length": "0",
            },
            timeout=TIMEOUT_SECONDI,
            allow_redirects=False,
        )
        status = resp.status_code
    except Exception:
        logger.warning("Push: servizio non raggiungibile per iscrizione %s", iscrizione.pk, exc_info=True)
        status = None

    if status is not None and 200 <= status < 300:
        iscrizione.errori_consecutivi = 0
        iscrizione.ultimo_invio_ok = timezone.now()
        iscrizione.save(update_fields=["errori_consecutivi", "ultimo_invio_ok"])
        return True
    if status in (404, 410):
        # Il browser ha revocato l'iscrizione (disinstallato, permessi tolti).
        iscrizione.attiva = False
        iscrizione.save(update_fields=["attiva"])
        logger.info("Push: iscrizione %s scaduta (HTTP %s), disattivata", iscrizione.pk, status)
        return False
    iscrizione.errori_consecutivi = min(iscrizione.errori_consecutivi + 1, 32767)
    fields = ["errori_consecutivi"]
    if iscrizione.errori_consecutivi >= MAX_ERRORI_CONSECUTIVI:
        iscrizione.attiva = False
        fields.append("attiva")
    iscrizione.save(update_fields=fields)
    logger.warning("Push: invio fallito per iscrizione %s (HTTP %s)", iscrizione.pk, status)
    return False


def invia_push_utente(user_id: int) -> int:
    """Segnale a tutti i dispositivi attivi dell'utente. Ritorna quanti ok."""
    from core.models import PushIscrizione

    ok = 0
    for iscrizione in PushIscrizione.objects.filter(user_id=user_id, attiva=True):
        if invia_segnale(iscrizione):
            ok += 1
    return ok


def task_push_utente(user_id: int) -> int:
    """Punto d'ingresso per django-q (``async_task``)."""
    try:
        return invia_push_utente(int(user_id))
    except Exception:
        logger.exception("Push: task fallito per user %s", user_id)
        return 0


def _django_user_id_da_legacy(legacy_user_id) -> int | None:
    try:
        from core.models import Profile

        return Profile.objects.filter(legacy_user_id=int(legacy_user_id)).values_list("user_id", flat=True).first()
    except Exception:
        return None


def _accoda(user_id: int) -> None:
    """Fuori dalla richiesta: le POST ai servizi push non devono rallentare chi
    ha generato la notifica. Senza django-q non si manda (best effort)."""
    try:
        from django_q.tasks import async_task

        async_task("core.push.task_push_utente", user_id, q_options={"timeout": 60})
    except Exception:
        logger.warning("Push: impossibile accodare l'invio per user %s", user_id, exc_info=True)


def notifica_creata(legacy_user_id, tipo: str) -> bool:
    """Chiamata da ``core.notifiche.invia_notifica`` dopo la campanella.

    Accoda il segnale se l'utente ha chiesto la push per la categoria del tipo e
    ha almeno un dispositivo attivo. Ritorna True se ha accodato. Non solleva."""
    try:
        if not push_configurato():
            return False
        user_id = _django_user_id_da_legacy(legacy_user_id)
        if not user_id:
            return False
        from core.models import NotificaCanali, PushIscrizione
        from core.notifiche_meta import notifica_categoria

        canali = NotificaCanali.objects.filter(user_id=user_id).first()
        if canali is None or not canali.push_per_categoria(notifica_categoria(tipo)):
            return False
        if not PushIscrizione.objects.filter(user_id=user_id, attiva=True).exists():
            return False
        _accoda(user_id)
        return True
    except Exception:
        logger.exception("Push: errore nella decisione di invio (tipo=%s)", tipo)
        return False
