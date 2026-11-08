"""Cruscotto del Diario preposto: numeri, andamenti e attività recenti.

Una sola fonte per ogni numero mostrato nell'elenco: la vista passa il queryset
già filtrato (visibilità per ruolo, ricerca, preposto) e qui si contano le
stesse righe che l'utente vede in tabella. Tutte le date sono «data della
segnalazione» in ora locale, tranne il ritardo di registrazione che confronta
la data della segnalazione con il momento dell'inserimento nel portale.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone

MESI_BREVI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
GIORNI_BREVI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]

# Oltre questi giorni fra il fatto e l'inserimento la segnalazione conta come
# registrata in ritardo: il registro deve essere tenuto «in tempo reale».
GIORNI_RITARDO_REGISTRAZIONE = 2
MESI_ANDAMENTO = 12
TOP_PREPOSTI = 6


def _locale(dt):
    return timezone.localtime(dt) if timezone.is_aware(dt) else dt


def _primo_del_mese(d: date, mesi_indietro: int) -> date:
    anno, mese = d.year, d.month - mesi_indietro
    while mese <= 0:
        mese += 12
        anno -= 1
    return date(anno, mese, 1)


def _barre(valori: list[tuple[str, int, str]]) -> list[dict]:
    """(etichetta, valore, descrizione) -> barre con altezza in % del massimo."""
    massimo = max((v for _e, v, _d in valori), default=0)
    return [
        {
            "etichetta": etichetta,
            "valore": valore,
            "descrizione": descrizione,
            "percento": round(valore * 100 / massimo) if massimo else 0,
            "massimo": massimo > 0 and valore == massimo,
        }
        for etichetta, valore, descrizione in valori
    ]


def calcola_cruscotto(qs, *, oggi: date | None = None) -> dict:
    """Numeri e grafici del registro per il queryset ricevuto (già filtrato)."""
    oggi = oggi or timezone.localdate()
    inizio_andamento = _primo_del_mese(oggi, MESI_ANDAMENTO - 1)

    righe = list(
        qs.order_by()
        .annotate(n_allegati_attivi=Count("allegati", filter=Q(allegati__rimosso_il__isnull=True)))
        .values_list("data_segnalazione", "created_at", "n_allegati_attivi")
    )
    date_locali = [(_locale(ds).date(), _locale(cr), n) for ds, cr, n in righe if ds]

    ultimi_7 = sum(1 for d, _c, _n in date_locali if d > oggi - timedelta(days=7))
    ultimi_30 = sum(1 for d, _c, _n in date_locali if d > oggi - timedelta(days=30))
    precedenti_30 = sum(1 for d, _c, _n in date_locali if oggi - timedelta(days=60) < d <= oggi - timedelta(days=30))
    mese_corrente = sum(1 for d, _c, _n in date_locali if d.year == oggi.year and d.month == oggi.month)
    senza_allegati = sum(1 for _d, _c, n in date_locali if not n)
    in_ritardo = sum(
        1 for d, creata, _n in date_locali if (creata.date() - d).days > GIORNI_RITARDO_REGISTRAZIONE
    )

    # Andamento: ultimi 12 mesi, mese corrente compreso.
    per_mese = Counter((d.year, d.month) for d, _c, _n in date_locali if d >= inizio_andamento)
    mesi = []
    for i in range(MESI_ANDAMENTO - 1, -1, -1):
        m = _primo_del_mese(oggi, i)
        n = per_mese.get((m.year, m.month), 0)
        etichetta = MESI_BREVI[m.month - 1]
        mesi.append((etichetta, n, f"{etichetta} {m.year}: {n} segnalazion{'e' if n == 1 else 'i'}"))
    andamento = _barre(mesi)
    for barra, i in zip(andamento, range(MESI_ANDAMENTO - 1, -1, -1)):
        barra["anno_nuovo"] = _primo_del_mese(oggi, i).month == 1

    # Giorno della settimana sugli stessi 12 mesi: dove si concentrano i fatti.
    per_giorno = Counter(d.weekday() for d, _c, _n in date_locali if d >= inizio_andamento)
    giorni = _barre([
        (GIORNI_BREVI[g], per_giorno.get(g, 0),
         f"{GIORNI_BREVI[g]}: {per_giorno.get(g, 0)} negli ultimi 12 mesi")
        for g in range(7)
    ])

    # Preposti con più segnalazioni negli ultimi 12 mesi. order_by() azzera
    # l'ordinamento di Meta: su SQL Server finirebbe nel GROUP BY.
    preposti_qs = (
        qs.filter(data_segnalazione__date__gte=inizio_andamento)
        .exclude(preposto="")
        .order_by()
        .values("preposto")
        .annotate(n=Count("id"))
        .order_by("-n", "preposto")
    )
    preposti = _barre([
        (r["preposto"], r["n"], f"{r['preposto']}: {r['n']} negli ultimi 12 mesi")
        for r in preposti_qs[:TOP_PREPOSTI]
    ])

    delta = ultimi_30 - precedenti_30
    return {
        "totale": len(date_locali),
        "ultimi_7": ultimi_7,
        "ultimi_30": ultimi_30,
        "precedenti_30": precedenti_30,
        "delta_30": delta,
        "delta_30_abs": abs(delta),
        "mese_corrente": mese_corrente,
        "mese_corrente_label": f"{MESI_BREVI[oggi.month - 1]} {oggi.year}",
        "senza_allegati": senza_allegati,
        "in_ritardo": in_ritardo,
        "giorni_ritardo": GIORNI_RITARDO_REGISTRAZIONE,
        "andamento": andamento,
        "andamento_totale": sum(b["valore"] for b in andamento),
        "giorni_settimana": giorni,
        "preposti": preposti,
    }


def stato_ispezioni(esecuzioni_qs, frequenza_giorni: int, *, oggi: date | None = None) -> dict:
    """Ultima ispezione visibile, prossima scadenza e se è già scaduta."""
    oggi = oggi or timezone.localdate()
    ultima = esecuzioni_qs.order_by("-data_esecuzione").first()
    if ultima is None:
        return {"ultima": None, "prossima_scadenza": None, "scaduta": False, "giorni_alla_scadenza": None,
                "frequenza_giorni": frequenza_giorni}
    prossima = timezone.localtime(ultima.data_esecuzione).date() + timedelta(days=frequenza_giorni)
    return {
        "ultima": ultima,
        "prossima_scadenza": prossima,
        "scaduta": prossima < oggi,
        "giorni_alla_scadenza": (prossima - oggi).days,
        "frequenza_giorni": frequenza_giorni,
    }


AZIONI_FEED = {
    "auto_insert": "Nuova segnalazione",
    "auto_update": "Modifica",
    "auto_delete": "Cancellazione definitiva",
    "allegato_aggiunto": "Allegato aggiunto",
    "allegato_rimosso": "Allegato rimosso",
}


def attivita_recenti(id_visibili: set[int], *, limite: int = 8) -> list[dict]:
    """Ultime operazioni sulle segnalazioni che l'utente può vedere."""
    from core.models import AuditLog

    from .models import SegnalazionePreposto

    if not id_visibili:
        return []
    tipo = SegnalazionePreposto._meta.label_lower
    voci = (
        AuditLog.objects.filter(oggetto_tipo=tipo, azione__in=list(AZIONI_FEED))
        .order_by("-created_at")
        .only("azione", "oggetto_id", "utente_display", "created_at", "dettaglio")[:200]
    )
    scelte = []
    for voce in voci:
        try:
            pk = int(voce.oggetto_id)
        except (TypeError, ValueError):
            continue
        if pk not in id_visibili:
            continue
        etichetta = AZIONI_FEED[voce.azione]
        modifiche = (voce.dettaglio or {}).get("modifiche") if isinstance(voce.dettaglio, dict) else None
        if voce.azione == "auto_update" and isinstance(modifiche, dict):
            if "eliminata_il" in modifiche:
                etichetta = "Eliminata" if (modifiche["eliminata_il"] or {}).get("new") else "Ripristinata"
            elif set(modifiche) <= {"updated_at"}:
                continue
        scelte.append({"azione": voce.azione, "etichetta": etichetta, "pk": pk,
                       "utente": voce.utente_display, "quando": voce.created_at})
        if len(scelte) >= limite:
            break
    segnalazioni = SegnalazionePreposto.objects.in_bulk({s["pk"] for s in scelte})
    for s in scelte:
        seg = segnalazioni.get(s["pk"])
        s["codice"] = getattr(seg, "codice_identificativo", "") or f"#{s['pk']}"
        s["titolo"] = getattr(seg, "titolo", "")
        s["eliminata"] = bool(seg and seg.is_eliminata)
    return scelte


def notifiche_non_partite(giorni: int = 30) -> int:
    """Mail automatiche del diario finite in errore negli ultimi ``giorni``."""
    try:
        from automazioni.models import EmailInviata
    except Exception:
        return 0
    da = timezone.now() - timedelta(days=giorni)
    try:
        return EmailInviata.objects.filter(
            sorgente="diario_preposto", esito=EmailInviata.ESITO_ERRORE, inviata_il__gte=da
        ).count()
    except Exception:
        return 0
