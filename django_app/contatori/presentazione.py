"""Layout per tipologia di apparato: cosa mettere in evidenza nella scheda e dove portano i collegamenti.

Leggero per costruzione: lavora solo sui dati che la scheda ha già in memoria (sonde con l'ultimo valore,
ultima rilevazione, disponibilità), **nessuna interrogazione SNMP e nessuna query in più**. Gli indicatori
si riconoscono dal nome della sonda (quelli dei profili predefiniti: «Carica residua», «Temperatura sistema»,
«Stato peggiore volumi/RAID»…), così valgono anche per le sonde aggiunte a mano con un nome simile. Le sonde
non riconosciute restano nella tabella completa sotto.

Per aggiungere un tipo: una voce in ``TIPI`` (titolo, sigla, indicatori, collegamenti). I collegamenti si
mostrano solo se l'utente può aprire la pagina (``acl_allows_path``): la visibilità non protegge niente, il
controllo resta sul server della pagina di destinazione.
"""
from __future__ import annotations

import re
from decimal import Decimal

from django.urls import NoReverseMatch, reverse

# (etichetta, espressione sul nome della sonda, forma) — forma: «pct» anello 0-100, «num» numero, «testo» stato.
_CPU = ("CPU", r"\bcpu\b|processor|carico cpu", "pct")
_MEM = ("Memoria", r"memori|ram (usat|occupat)|memory", "pct")
_TEMP = ("Temperatura", r"temperatur", "num")
_UPTIME = ("Acceso da", r"uptime", "testo")

TIPI = {
    "UPS": {
        "titolo": "Alimentazione", "sigla": "UPS",
        "indicatori": [("Carica batteria", r"carica|charge|capacit", "pct"), ("Autonomia", r"autonom|runtime", "num"),
                       ("Stato batteria", r"stato batteri|battery status", "testo"), ("Su batteria da", r"secondi su batteria|on battery", "num"),
                       ("Carico", r"\bcarico\b|load", "pct"), _TEMP],
        "collegamenti": [("Backup (cosa protegge l'UPS)", "security:backup", "")],
    },
    "AMBIENTE": {
        "titolo": "Sensori", "sigla": "ENV",
        "indicatori": [_TEMP, ("Umidità", r"umidit|humidit", "pct"), ("Allarme", r"allarm|alarm|stato", "testo")],
        "collegamenti": [],
    },
    "FIREWALL": {
        "titolo": "Sicurezza perimetrale", "sigla": "FW",
        "indicatori": [_CPU, _MEM, ("Sessioni", r"session|connession", "num"), ("Tunnel VPN", r"vpn|tunnel", "num"),
                       ("Traffico in", r"traffico ricevuto|in octets|ricevut", "num"), ("Traffico out", r"traffico trasmesso|out octets|trasmess", "num"), _UPTIME],
        "collegamenti": [("Accessi VPN (SOC)", "security:vpn_history", ""), ("Rete (IP)", "security:rete_indirizzi", ""),
                         ("Registro accessi", "security:registro_log_eventi", "")],
    },
    "RETE": {
        "titolo": "Rete", "sigla": "NET",
        "indicatori": [_CPU, _MEM, _TEMP, ("Traffico in", r"traffico ricevuto|in octets|ricevut", "num"),
                       ("Traffico out", r"traffico trasmesso|out octets|trasmess", "num"), _UPTIME],
        "collegamenti": [("Rete (IP) nel SOC", "security:rete_indirizzi", ""), ("Indirizzi IP in Asset", "assets:rete_indirizzi", "")],
    },
    "SERVER": {
        "titolo": "Server", "sigla": "SRV",
        "indicatori": [("Salute generale", r"salute generale|stato ilo|stato sistema|health", "testo"), _CPU, _MEM, _TEMP,
                       ("Ventole", r"ventol|fan", "testo"), ("Alimentatori", r"alimentator|power suppl", "testo"),
                       ("Dischi / controller", r"storage|controller|dischi", "testo"), _UPTIME],
        "collegamenti": [("Server e virtualizzazione (Registro accessi)", "security:registro_log_infra", ""), ("Backup", "security:backup", "")],
    },
    "STORAGE": {
        "titolo": "Storage", "sigla": "NAS",
        "indicatori": [("Stato sistema", r"stato sistema|system status", "testo"), ("Volumi / RAID", r"volum|raid", "testo"),
                       ("Dischi", r"stato peggiore dischi|salute peggiore dischi|disk", "testo"), ("Temperatura dischi", r"temperatura massima dischi|disk temp", "num"),
                       ("Temperatura", r"temperatura sistema|temperatur", "num"), ("Aggiornamento", r"aggiornament|update", "testo"), _UPTIME],
        "collegamenti": [("Backup (SOC)", "security:backup", ""), ("Log dei backup", "security:backup_log", "")],
    },
    "TVCC_NVR": {
        "titolo": "Videoregistratore", "sigla": "NVR",
        "indicatori": [("Dischi", r"disc|hdd|disk", "testo"), ("Canali", r"canal|channel", "num"), ("Registrazione", r"registr|record", "testo"), _TEMP, _UPTIME],
        "collegamenti": [("Tutta la videosorveglianza", "contatori:snmp_centrale", "?categoria=TVCC")],
    },
    "TVCC_CAMERA": {
        "titolo": "Telecamera", "sigla": "CAM",
        "indicatori": [_UPTIME],
        "collegamenti": [("Tutta la videosorveglianza", "contatori:snmp_centrale", "?categoria=TVCC")],
    },
    "LETTORE": {
        "titolo": "Lettore / terminale", "sigla": "LET",
        "indicatori": [("Stato", r"stato|status", "testo"), _UPTIME],
        "collegamenti": [],
    },
    "ALTRO": {"titolo": "Apparato", "sigla": "ALT", "indicatori": [_CPU, _MEM, _TEMP, _UPTIME], "collegamenti": []},
}
TONI = {"OK": "ok", "WARNING": "warn", "ERROR": "danger", "MAI": "muted"}


def _numero(valore):
    n = getattr(valore, "valore_numero", None)
    return float(n) if isinstance(n, (int, float, Decimal)) else None


def _byte(n):
    """Contatori in byte in unità leggibili (8,5 GB)."""
    for unita in ("byte", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unita == "TB":
            return f"{n:.0f} {unita}" if unita == "byte" else f"{n:.1f} {unita}".replace(".", ",")
        n /= 1024


def _durata(secondi):
    if secondi is None:
        return ""
    giorni, resto = divmod(int(secondi), 86400)
    ore = resto // 3600
    return f"{giorni} g {ore} h" if giorni else f"{ore} h {(resto % 3600) // 60} min"


def _collegamenti(cfg, request, dispositivo):
    from core.middleware import acl_allows_path

    out = []
    for label, rotta, query in cfg["collegamenti"]:
        try:
            url = reverse(rotta)
        except NoReverseMatch:
            continue
        if request is None or acl_allows_path(url, django_user=request.user, request=request):
            out.append({"label": label, "url": url + query})
    return out


def vista(dispositivo, sonde, *, ultima=None, disponibilita=None, request=None):
    """{tipo, titolo, sigla, indicatori, base, collegamenti} per la scheda; ``None`` per le stampanti (hanno il loro pannello)."""
    if dispositivo.categoria == "STAMPANTE":
        return None
    cfg = TIPI.get(dispositivo.categoria, TIPI["ALTRO"])
    con_valore = [s for s in sonde if getattr(s, "ultimo_valore", None) is not None]
    usate, indicatori = set(), []
    for label, espressione, forma in cfg["indicatori"]:
        regex = re.compile(espressione, re.IGNORECASE)
        sonda = next((s for s in con_valore if s.pk not in usate and regex.search(s.nome)), None)
        if sonda is None:
            continue
        usate.add(sonda.pk)
        v = sonda.ultimo_valore
        n = _numero(v)
        pct = round(n) if forma == "pct" and n is not None and 0 <= n <= 100 else None
        in_byte = (getattr(sonda, "unita", "") or "").lower() in ("byte", "bytes", "b")
        valore = _byte(n) if n is not None and in_byte else v.valore_display
        indicatori.append({"label": label, "sonda": sonda.nome, "valore": valore, "pct": pct,
                           "forma": "pct" if pct is not None else ("num" if forma == "num" and n is not None else "testo"),
                           "tono": TONI.get(v.stato, "muted")})
    base = []
    if ultima is not None:
        if ultima.tempo_risposta_ms is not None:
            base.append({"label": "Risposta", "valore": f"{ultima.tempo_risposta_ms} ms", "pct": None,
                         "tono": "ok" if ultima.tempo_risposta_ms < 200 else "warn"})
        if ultima.sys_uptime_seconds and not any(i["label"] == "Acceso da" for i in indicatori):
            base.append({"label": "Acceso da", "valore": _durata(ultima.sys_uptime_seconds), "tono": "muted", "pct": None})
    d24 = (disponibilita or {}).get("24h") or {}
    if d24.get("pct") is not None:
        pct = int(round(float(d24["pct"])))
        base.append({"label": "Disponibilità 24 h", "valore": f"{d24.get('ok', 0)} su {d24.get('totale', 0)} riuscite", "pct": pct,
                     "tono": "ok" if pct >= 99 else ("warn" if pct >= 90 else "danger")})
    return {"tipo": dispositivo.categoria, "titolo": cfg["titolo"], "sigla": cfg["sigla"], "indicatori": indicatori,
            "base": base, "collegamenti": _collegamenti(cfg, request, dispositivo),
            "riconosciute": len(usate), "sonde_totali": len(sonde)}


# --- MFC a contratto: i collegamenti della sua UI -----------------------------------------------

def collegamenti_mfc(macchina, request=None):
    """Le pagine del modulo che riguardano una MFC (letture già filtrate su di lei), per la barra della scheda."""
    from core.middleware import acl_allows_path

    voci = [
        ("Letture di questa MFC", reverse("contatori:letture_gestisci") + f"?macchina={macchina.pk}"),
        ("Letture mensili", reverse("contatori:letture_mensili")),
        ("Consumabili", reverse("contatori:consumabili")),
        ("Fabbisogno", reverse("contatori:consumabili_fabbisogno")),
        ("Fatture", reverse("contatori:fatture")),
        ("Riconciliazione", reverse("contatori:riconciliazione")),
        ("Analisi", reverse("contatori:analisi")),
    ]
    return [{"label": label, "url": url} for label, url in voci
            if request is None or acl_allows_path(url.split("?")[0], django_user=request.user, request=request)]
