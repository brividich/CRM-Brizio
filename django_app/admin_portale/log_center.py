"""Log center: dati per le pagine Audit Log e Attività utenti (stessa vista, due ingressi).

Tutto si calcola qui, il template impagina soltanto: etichette delle azioni,
modifiche «prima → dopo», serie per giorno già in coordinate SVG, classifiche.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.audit import AUTORI_AUDIT, filtra_per_autore

PERIODI = (1, 7, 30, 90, 365)
MAX_VALORE = 160

# Azione → (etichetta, tono). Toni: ok, ko, info, crea, modifica, elimina, neutro.
ETICHETTE_AZIONI: dict[str, tuple[str, str]] = {
    "login_ok": ("Accesso", "ok"),
    "login_fallito": ("Accesso non riuscito", "ko"),
    "logout": ("Uscita", "neutro"),
    "2fa_ok": ("Verifica in due passaggi", "ok"),
    "cambio_password": ("Password cambiata", "info"),
    "onboarding_completato": ("Primo accesso completato", "info"),
    "auto_insert": ("Creato", "crea"),
    "auto_update": ("Modificato", "modifica"),
    "auto_delete": ("Eliminato", "elimina"),
    "postazione_operatore_entra": ("Entrata in postazione", "ok"),
    "postazione_operatore_esce": ("Uscita dalla postazione", "neutro"),
}

# Colori degli avatar: leggibili con testo bianco in entrambi i temi.
_AVATAR = ("#2f5f89", "#0f766e", "#7c3aed", "#b45309", "#be123c", "#1d4ed8", "#4d7c0f", "#a21caf")


def etichetta_azione(azione: str) -> tuple[str, str]:
    if azione in ETICHETTE_AZIONI:
        return ETICHETTE_AZIONI[azione]
    testo = (azione or "").replace("_", " ").strip()
    tono = "ko" if any(p in azione for p in ("negat", "fallit", "bloccat", "rifiut")) else (
        "elimina" if "delete" in azione or "elimin" in azione else "neutro"
    )
    return (testo[:1].upper() + testo[1:]) or "—", tono


def _iniziali(nome: str) -> str:
    parti = [p for p in nome.replace(".", " ").replace("@", " ").split() if p[:1].isalpha()]
    if not parti:
        return "?"
    return (parti[0][0] + (parti[1][0] if len(parti) > 1 else "")).upper()


def _colore(nome: str) -> str:
    return _AVATAR[int(hashlib.md5(nome.lower().encode("utf-8")).hexdigest(), 16) % len(_AVATAR)]


def _breve(valore) -> str:
    if valore is None or valore == "":
        return "—"
    testo = valore if isinstance(valore, str) else json.dumps(valore, ensure_ascii=False, default=str)
    return testo if len(testo) <= MAX_VALORE else testo[:MAX_VALORE] + "…"


def _campo(nome: str) -> str:
    testo = str(nome).replace("_id", "").replace("_", " ").strip()
    return testo[:1].upper() + testo[1:]


def presenta(voce) -> dict:
    """Una riga di AuditLog pronta per il template."""
    dettaglio = voce.dettaglio if isinstance(voce.dettaglio, dict) else {}
    etichetta, tono = etichetta_azione(voce.azione)
    nome = (voce.utente_display or "").strip()
    if nome:
        autore, tipo = nome, "persona"
    elif voce.ip_address:
        autore, tipo = "Non autenticato", "anonimo"
    else:
        autore, tipo = "Processo automatico", "sistema"

    oggetto = str(dettaglio.get("oggetto") or "")
    modello = str(dettaglio.get("model") or "")
    modifiche = [
        {"campo": _campo(k), "prima": _breve((v or {}).get("old")), "dopo": _breve((v or {}).get("new"))}
        for k, v in (dettaglio.get("modifiche") or {}).items()
        if isinstance(v, dict)
    ]
    valori = [
        {"campo": _campo(k), "valore": _breve(v)}
        for k, v in (dettaglio.get("valori") or dettaglio.get("nuovi_valori") or {}).items()
    ]
    campi = list(dettaglio.get("campi") or dettaglio.get("campi_valorizzati") or [])
    noti = {"oggetto", "model", "pk", "modifiche", "valori", "nuovi_valori", "campi", "campi_valorizzati", "campi_tecnici_cambiati"}
    altri = [{"campo": _campo(k), "valore": _breve(v)} for k, v in dettaglio.items() if k not in noti]
    return {
        "voce": voce,
        "autore": autore,
        "tipo_autore": tipo,
        "iniziali": _iniziali(nome) if nome else ("?" if tipo == "anonimo" else "⚙"),
        "colore": _colore(nome) if nome else "",
        "etichetta": etichetta,
        "tono": tono,
        "oggetto": oggetto or modello,
        "modello": modello,
        "modifiche": modifiche,
        "valori": valori,
        "campi": [_campo(c) for c in campi],
        "altri": altri,
        "ha_dettaglio": bool(modifiche or valori or campi or altri),
    }


def leggi_filtri(request, giorni_default: int = 7) -> dict:
    get = request.GET
    chi = (get.get("chi") or "persone").strip()
    if chi not in dict(AUTORI_AUDIT):
        chi = "persone"
    try:
        giorni = int(get.get("giorni") or get.get("days") or giorni_default)
    except ValueError:
        giorni = giorni_default
    if giorni not in PERIODI:
        giorni = giorni_default
    giorno = None
    raw = (get.get("data") or "").strip()
    if raw:
        try:
            giorno = date.fromisoformat(raw)
        except ValueError:
            giorno = None
    return {
        "chi": chi,
        "giorni": giorni,
        "data": giorno,
        "utente": (get.get("legacy_user_id") or "").strip(),
        "modulo": (get.get("modulo") or "").strip(),
        "q": (get.get("q") or get.get("azione") or "").strip(),
    }


def finestra(filtri: dict) -> tuple[date, date]:
    """Giorni (locali) coperti: il giorno scelto, altrimenti gli ultimi N."""
    if filtri["data"]:
        return filtri["data"], filtri["data"]
    oggi = timezone.localdate()
    return oggi - timedelta(days=filtri["giorni"] - 1), oggi


def _inizio(giorno: date):
    return timezone.make_aware(datetime.combine(giorno, datetime.min.time()))


def queryset_finestra(filtri: dict):
    """Righe del periodo con utente/modulo/ricerca, ma senza il filtro «Chi»."""
    from core.models import AuditLog

    dal, al = finestra(filtri)
    qs = AuditLog.objects.filter(created_at__gte=_inizio(dal), created_at__lt=_inizio(al + timedelta(days=1)))
    if filtri["utente"].isdigit():
        qs = qs.filter(legacy_user_id=int(filtri["utente"]))
    if filtri["modulo"]:
        qs = qs.filter(modulo=filtri["modulo"])
    if filtri["q"]:
        q = filtri["q"]
        qs = qs.filter(
            Q(utente_display__icontains=q) | Q(azione__icontains=q) | Q(modulo__icontains=q) | Q(ip_address__icontains=q)
        )
    return qs


def indicatori(base) -> dict:
    """Numeri del periodo (tutti gli autori), per le tessere in cima."""
    senza_autore = Q(legacy_user_id__isnull=True) & Q(utente_display="")
    tot = base.order_by().aggregate(
        totale=Count("id"),
        automatici=Count("id", filter=senza_autore),
        accessi=Count("id", filter=Q(azione="login_ok")),
        falliti=Count("id", filter=Q(azione="login_fallito")),
    )
    persone = filtra_per_autore(base, "persone").exclude(utente_display="").order_by().values("utente_display").distinct().count()
    tot["persone_righe"] = tot["totale"] - tot["automatici"]
    tot["persone"] = persone
    tot["quota_automatici"] = round(100 * tot["automatici"] / tot["totale"]) if tot["totale"] else 0
    return tot


def serie_giornaliera(base, dal: date, al: date) -> dict:
    """Barre impilate persone/processi automatici per giorno, già in coordinate SVG."""
    senza_autore = Q(legacy_user_id__isnull=True) & Q(utente_display="")
    righe = (
        base.annotate(giorno=TruncDate("created_at")).order_by().values("giorno")
        .annotate(persone=Count("id", filter=~senza_autore), automatici=Count("id", filter=senza_autore))
    )
    per_giorno = {r["giorno"]: r for r in righe}
    span = (al - dal).days + 1
    larghezza, altezza, alto, sinistra = 760, 150, 10, 8
    picco = max([r["persone"] + r["automatici"] for r in per_giorno.values()] or [1]) or 1
    slot = (larghezza - sinistra) / span
    barra = max(min(slot * 0.66, 42), 3)
    base_y = alto + altezza
    giorni = []
    for i in range(span):
        g = dal + timedelta(days=i)
        r = per_giorno.get(g, {"persone": 0, "automatici": 0})
        h_p = altezza * r["persone"] / picco
        h_a = altezza * r["automatici"] / picco
        x = sinistra + i * slot + (slot - barra) / 2
        giorni.append({
            "data": g,
            "x": round(x, 1), "w": round(barra, 1), "cx": round(sinistra + i * slot + slot / 2, 1),
            "y_p": round(base_y - h_p, 1), "h_p": round(h_p, 1),
            "y_a": round(base_y - h_p - h_a, 1), "h_a": round(h_a, 1),
            "persone": r["persone"], "automatici": r["automatici"],
            "etichetta": span <= 14 or i % max(span // 10, 1) == 0,
        })
    return {"giorni": giorni, "larghezza": larghezza, "altezza": base_y + 22, "base_y": base_y, "vuota": not per_giorno,
            "picco": picco}


def classifica(qs, campo: str, limite: int = 6) -> list[dict]:
    righe = list(qs.exclude(**{campo: ""}).order_by().values(campo).annotate(n=Count("id")).order_by("-n", campo)[:limite])
    picco = max([r["n"] for r in righe] or [1]) or 1
    return [{"nome": r[campo], "n": r["n"], "quota": round(100 * r["n"] / picco)} for r in righe]


def pagina(request, vista: str):
    """Le due voci di menu (``audit`` e ``attivita``) aprono la stessa pagina."""
    from django.core.paginator import Paginator
    from django.shortcuts import render

    from core.models import AuditLog
    from core.exporting import export_rows_response

    filtri = leggi_filtri(request, giorni_default=7 if vista == "audit" else 30)
    base = queryset_finestra(filtri)
    qs = filtra_per_autore(base, filtri["chi"]).order_by("-created_at", "-id")

    formato = (request.GET.get("export") or "").strip().lower()
    if formato in {"csv", "xlsx"}:
        return export_rows_response(
            rows=qs,
            columns=[
                ("Data/Ora", "created_at"),
                ("Utente", lambda e: (e.utente_display or "").upper()),
                ("Legacy user ID", "legacy_user_id"),
                ("Modulo", "modulo"),
                ("Azione", "azione"),
                ("IP", "ip_address"),
                ("Dettaglio", "dettaglio"),
            ],
            filename="audit_log" if vista == "audit" else "attivita_utente",
            fmt=formato,
        )

    dal, al = finestra(filtri)
    page_obj = Paginator(qs, 50).get_page(request.GET.get("page"))
    righe = [presenta(v) for v in page_obj.object_list]
    oggi = timezone.localdate()
    for riga in righe:
        quando = timezone.localtime(riga["voce"].created_at)
        riga["quando"] = quando
        riga["giorno"] = quando.date()
        riga["giorno_label"] = "Oggi" if riga["giorno"] == oggi else (
            "Ieri" if riga["giorno"] == oggi - timedelta(days=1) else ""
        )
    query = request.GET.copy()
    for chiave in ("page", "export"):
        query.pop(chiave, None)
    senza_chi = query.copy()
    senza_chi.pop("chi", None)
    senza_periodo = query.copy()
    for chiave in ("giorni", "days", "data"):
        senza_periodo.pop(chiave, None)
    utenti = list(
        AuditLog.objects.filter(created_at__gte=_inizio(dal), created_at__lt=_inizio(al + timedelta(days=1)))
        .exclude(legacy_user_id__isnull=True).order_by().values("legacy_user_id", "utente_display")
        .annotate(n=Count("id")).order_by("utente_display", "legacy_user_id")[:300]
    )
    return render(request, "admin_portale/pages/log_center.html", {
        "page_title": "Audit Log" if vista == "audit" else "Attività utenti",
        "vista": vista,
        "filtri": filtri,
        "dal": dal,
        "al": al,
        "periodi": PERIODI,
        "autori": AUTORI_AUDIT,
        "indicatori": indicatori(base),
        "serie": serie_giornaliera(base, dal, al) if 1 < (al - dal).days + 1 <= 90 else None,
        "top_persone": persone_attive(filtra_per_autore(base, "persone")),
        "top_moduli": classifica(qs, "modulo"),
        "top_azioni": [
            {**r, "etichetta": etichetta_azione(r["nome"])[0], "tono": etichetta_azione(r["nome"])[1]}
            for r in classifica(qs, "azione")
        ],
        "page_obj": page_obj,
        "righe": righe,
        "utenti": utenti,
        "moduli_disponibili": AuditLog.objects.order_by().values_list("modulo", flat=True).distinct().order_by("modulo"),
        "query": query.urlencode(),
        "query_senza_chi": senza_chi.urlencode(),
        "query_senza_periodo": senza_periodo.urlencode(),
    })


def persone_attive(qs, limite: int = 6) -> list[dict]:
    righe = list(
        qs.exclude(utente_display="").order_by().values("utente_display", "legacy_user_id")
        .annotate(n=Count("id")).order_by("-n", "utente_display")[:limite]
    )
    picco = max([r["n"] for r in righe] or [1]) or 1
    return [{
        "nome": r["utente_display"], "id": r["legacy_user_id"], "n": r["n"], "quota": round(100 * r["n"] / picco),
        "iniziali": _iniziali(r["utente_display"]), "colore": _colore(r["utente_display"]),
    } for r in righe]
