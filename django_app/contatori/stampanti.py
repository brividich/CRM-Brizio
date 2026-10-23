"""Dati delle stampanti oltre a contatori e toner: registro avvisi e stime di consumo.

- :func:`registra_avvisi` tiene il registro degli avvisi (per un dispositivo del Monitor o per una MFC) (inceppamenti, carta, sportelli,
  assistenza) da una lettura all'altra: un avviso si apre quando compare e si chiude quando
  la stampante non lo segnala più.
- :func:`stime` dice quante pagine si stampano al giorno e fra quanti giorni finisce ogni
  toner, dalle letture già salvate (una al giorno, ultimi 60 giorni). Nessuna lettura in più.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

GIORNI_STIME = 60
GIORNI_REGISTRO = 400  # gli avvisi chiusi da più tempo si cancellano
MIN_GIORNI_STIMA = 3
MIN_CALO_PCT = 2


def _chiavi_avvisi(dati):
    """{chiave: campi} degli avvisi presenti in una lettura. Vuoto se la lettura non li ha."""
    out = {}
    for a in dati.get("avvisi") or []:
        chiave = f"prt:{a.get('codice')}:{a.get('gruppo')}:{a.get('gruppo_indice')}:{a.get('testo')}"[:255]
        out[chiave] = {
            "testo": a["testo"][:255], "descrizione": (a.get("descrizione") or "")[:120],
            "gravita": a.get("gravita") or "", "gruppo": a.get("gruppo") or "", "chi": a.get("chi") or "",
            "critico": bool(a.get("critico")), "informativo": bool(a.get("informativo")),
            "da_secondi": a.get("da_secondi"),
        }
    if not out:
        # Senza tabella avvisi: le voci degli errori rilevati (es. «carta inceppata, sportello aperto»).
        stato = dati.get("stato") or {}
        for voce in filter(None, (v.strip() for v in (stato.get("segnalazioni") or "").split(","))):
            out[f"hr:{voce}"[:255]] = {
                "testo": voce.capitalize()[:255], "descrizione": voce, "gravita": "", "gruppo": "stampante", "chi": "",
                "critico": stato.get("segnalazioni_livello") == "ERROR", "informativo": False, "da_secondi": None,
            }
    return out


def _proprietario(stampante):
    """{campo: oggetto} del registro: una MFC a contratto o un dispositivo del Monitor SNMP."""
    from .models import Macchina

    return {"macchina": stampante} if isinstance(stampante, Macchina) else {"dispositivo": stampante}


def registra_avvisi(stampante, dati, adesso=None):
    """Aggiorna il registro avvisi con una lettura. Se la lettura non ha i dati estesi non chiude niente."""
    from .models import AvvisoStampante

    if not dati or "avvisi" not in dati:
        return
    adesso = adesso or timezone.now()
    chi = _proprietario(stampante)
    presenti = _chiavi_avvisi(dati)
    aperti = {a.chiave: a for a in AvvisoStampante.objects.filter(chiuso_il__isnull=True, **chi)}
    for chiave, campi in presenti.items():
        if chiave in aperti:
            AvvisoStampante.objects.filter(pk=aperti[chiave].pk).update(ultimo_visto_il=adesso)
            continue
        da = campi.pop("da_secondi")
        aperto_il = adesso - timedelta(seconds=da) if isinstance(da, int) and 0 <= da < 86400 * 30 else adesso
        AvvisoStampante.objects.create(chiave=chiave, aperto_il=aperto_il, ultimo_visto_il=adesso, **chi, **campi)
    spariti = [a.pk for chiave, a in aperti.items() if chiave not in presenti]
    if spariti:
        AvvisoStampante.objects.filter(pk__in=spariti).update(chiuso_il=adesso)
    AvvisoStampante.objects.filter(chiuso_il__lt=adesso - timedelta(days=GIORNI_REGISTRO), **chi).delete()


def contesto_pannello(stampante, dati):
    """Dati del pannello «La stampante adesso» e del registro avvisi, uguali per MFC e Monitor."""
    from .printer_snmp import problemi_stampante

    problemi = problemi_stampante(dati or {})
    registro = list(stampante.avvisi_stampante.all()[:60])
    return {
        "problemi_stampante": problemi,
        "problemi_gravi": any(livello == "ERROR" for _t, livello in problemi),
        "avvisi_aperti": [a for a in registro if a.chiuso_il is None and not a.informativo],
        "avvisi_registro": registro,
    }


def _letture_giornaliere(dispositivo, adesso):
    """L'ultima lettura con dati stampante di ogni giorno, dalla più vecchia: [(quando, dati)]."""
    since = adesso - timedelta(days=GIORNI_STIME)
    ultime = {}
    for pk, quando in dispositivo.rilevazioni.filter(rilevata_il__gte=since).order_by("rilevata_il", "pk").values_list("pk", "rilevata_il"):
        ultime[timezone.localtime(quando).date()] = pk
    righe = dispositivo.rilevazioni.filter(pk__in=list(ultime.values())).order_by("rilevata_il").only("rilevata_il", "dati_stampante")
    return [(r.rilevata_il, r.dati_stampante) for r in righe if (r.dati_stampante or {}).get("contatori") or (r.dati_stampante or {}).get("consumabili")]


def _giorni(a, b):
    return (b - a).total_seconds() / 86400


def stime(dispositivo, adesso=None):
    """Pagine al giorno per contatore e durata residua di ogni consumabile."""
    adesso = adesso or timezone.now()
    serie = _letture_giornaliere(dispositivo, adesso)
    if len(serie) < 2:
        return {"pagine": [], "consumabili": [], "giorni": 0}
    contatori = {}
    for quando, dati in serie:
        for c in dati.get("contatori") or []:
            if c.get("indice") is not None and isinstance(c.get("valore"), int):
                contatori.setdefault(c["indice"], []).append((quando, c["valore"], c.get("unita", "")))
    pagine = []
    for indice, punti in contatori.items():
        # Dall'ultimo azzeramento: un contatore che scende riparte da lì.
        inizio = max((i for i in range(1, len(punti)) if punti[i][1] < punti[i - 1][1]), default=0)
        primo, ultimo = punti[inizio], punti[-1]
        giorni = _giorni(primo[0], ultimo[0])
        if giorni >= 1:
            totale = ultimo[1] - primo[1]
            pagine.append({"indice": indice, "unita": ultimo[2], "al_giorno": round(totale / giorni),
                           "totale": totale, "giorni": round(giorni)})
    livelli = {}
    for quando, dati in serie:
        for c in dati.get("consumabili") or []:
            if isinstance(c.get("pct"), int) and c.get("indice") is not None:
                livelli.setdefault(c["indice"], {"nome": c.get("nome", ""), "tipo": c.get("tipo", ""), "punti": []})["punti"].append((quando, c["pct"]))
    consumabili = []
    for indice, info in livelli.items():
        punti = info["punti"]
        if "scarto" in (info["tipo"] or "") or "waste" in (info["nome"] or "").lower():
            continue  # il contenitore di scarto si riempie: non è un consumo da stimare così
        # Dall'ultima sostituzione: un livello che sale di più di 5 punti è un toner nuovo.
        inizio = max((i for i in range(1, len(punti)) if punti[i][1] > punti[i - 1][1] + 5), default=0)
        primo, ultimo = punti[inizio], punti[-1]
        giorni = _giorni(primo[0], ultimo[0])
        calo = primo[1] - ultimo[1]
        riga = {"indice": indice, "nome": info["nome"], "pct": ultimo[1], "sostituito_il": primo[0] if inizio else None}
        if giorni >= MIN_GIORNI_STIMA and calo >= MIN_CALO_PCT:
            al_giorno = calo / giorni
            residui = ultimo[1] / al_giorno
            riga.update({"pct_al_mese": round(al_giorno * 30, 1), "giorni_residui": round(residui),
                         "finisce_il": (timezone.localtime(adesso) + timedelta(days=residui)).date()})
        else:
            riga["nota"] = "consumo troppo basso per una stima" if giorni >= MIN_GIORNI_STIMA else "servono almeno 3 giorni di letture"
        consumabili.append(riga)
    consumabili.sort(key=lambda r: (r.get("giorni_residui") is None, r.get("giorni_residui") or 0, r["nome"]))
    return {"pagine": pagine, "consumabili": consumabili, "giorni": round(_giorni(serie[0][0], serie[-1][0]))}


INTERVALLO_MFC_MINUTI = 15


def leggi_stato_mfc(macchina, adesso=None):
    """Legge dalla MFC a contratto gli stessi dati di una stampante del Monitor e li salva sulla MFC.

    Non tocca contatori di fatturazione, letture e stato SNMP della MFC: quelli restano delle
    letture trimestrali, mensili e dei consumabili. Ritorna i dati letti o ``None`` se non risponde.
    """
    from .printer_snmp import leggi_stampante
    from .services import _community_snmp, _parametri_snmp
    from .models import ImpostazioniSNMP, StatoSNMP
    from .snmp import SNMPError

    if not macchina.host:
        return None
    cfg = ImpostazioniSNMP.get_solo()
    porta, timeout, versione = _parametri_snmp(macchina, cfg)
    try:
        dati = leggi_stampante(macchina, community=_community_snmp(macchina, cfg), port=porta,
                               timeout=timeout, version=versione)
    except SNMPError:
        return None
    if not dati.get("contatori") and not dati.get("consumabili") and "avvisi" not in dati:
        return None  # nessuna risposta utile: si tiene l'ultima lettura buona
    adesso = adesso or timezone.now()
    macchina.dati_stampante, macchina.dati_stampante_il = dati, adesso
    campi = ["dati_stampante", "dati_stampante_il", "snmp_ultimo_controllo"]
    # La stampante ha risposto: è un contatto, come per il Monitor. Un errore delle letture
    # contatori (es. matricola diversa) resta finché la lettura dei contatori non riesce.
    macchina.snmp_ultimo_controllo = adesso
    if macchina.snmp_stato != StatoSNMP.ERROR:
        macchina.snmp_stato = StatoSNMP.OK
        campi.append("snmp_stato")
    macchina.save(update_fields=campi)
    registra_avvisi(macchina, dati, adesso)
    return dati
