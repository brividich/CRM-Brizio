"""Copilota per valutare una richiesta DPI, partendo da cio' che e' gia' successo.

Lo storico dice molto prima ancora dell'AI: quando la persona ha ricevuto l'ultimo DPI dello
stesso tipo rispetto alla vita utile, quante consegne ha avuto nell'anno rispetto alla media
del reparto, se ha gia' una richiesta aperta uguale, se c'e' giacenza, come sono state gestite le
richieste simili e con quali motivi di rifiuto. L'AI legge questi fatti e propone: approvare,
chiedere informazioni o rifiutare, con il messaggio per il richiedente. Il gestore decide;
la sua decisione finisce in ``ai_assistant.apprendimento`` e guida le proposte successive.

Privacy: al modello non arrivano nomi, email o firme. Solo conteggi, date, categoria e reparto.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from .models import ConsegnaDPI, RichiestaDPI, StatoRichiesta

logger = logging.getLogger(__name__)

MODULO = "dpi"
AZIONE = "valutazione_richiesta"
DECISIONI = {"approvare": "Approvare", "chiedere_info": "Chiedere informazioni", "rifiutare": "Rifiutare"}


def _vita_utile(richiesta) -> int | None:
    if richiesta.modello_dpi_id:
        return richiesta.modello_dpi.effective_vita_utile_giorni
    return richiesta.categoria.vita_utile_giorni


def _stesso_dpi(qs, richiesta):
    qs = qs.filter(categoria_id=richiesta.categoria_id)
    return qs.filter(tipo_dpi_id=richiesta.tipo_dpi_id) if richiesta.tipo_dpi_id else qs


def storico_richiesta(richiesta, *, oggi=None) -> dict:
    """Fatti dallo storico, gia' pronti da mostrare. Nessuna AI."""
    oggi = oggi or timezone.localdate()
    anno_fa = oggi - timedelta(days=365)
    vita = _vita_utile(richiesta)
    segnali = []
    fatti = {"vita_utile": vita}

    persona = richiesta.richiedente_legacy_id
    if persona:
        stesso = {"richiesta__categoria_id": richiesta.categoria_id}
        if richiesta.tipo_dpi_id:
            stesso["richiesta__tipo_dpi_id"] = richiesta.tipo_dpi_id
        consegne = list(
            ConsegnaDPI.objects.filter(richiesta__richiedente_legacy_id=persona, richiesta__stato=StatoRichiesta.CONSEGNATA, **stesso)
            .exclude(richiesta_id=richiesta.pk).order_by("-data_consegna")[:20]
        )
        nell_anno = [c for c in consegne if c.data_consegna >= anno_fa]
        fatti["consegne_anno"] = len(nell_anno)
        if consegne:
            ultima = consegne[0]
            giorni = (oggi - ultima.data_consegna).days
            fatti["giorni_da_ultima"] = giorni
            fatti["ultima_consegna"] = ultima.data_consegna
            if vita and giorni < vita:
                quota = round(100 * giorni / vita)
                livello = "warn" if quota < 50 else "info"
                segnali.append((livello, f"Ultima consegna dello stesso DPI {giorni} giorni fa: la durata prevista è {vita} giorni ({quota}% usata)."))
            elif vita:
                segnali.append(("ok", f"Ultima consegna {giorni} giorni fa: la durata prevista ({vita} giorni) è superata, il ricambio è regolare."))
            else:
                segnali.append(("info", f"Ultima consegna dello stesso DPI {giorni} giorni fa."))
        else:
            segnali.append(("ok", "Prima richiesta di questo DPI per la persona."))

        aperte = _stesso_dpi(RichiestaDPI.objects.filter(richiedente_legacy_id=persona,
                                                         stato__in=[StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA]), richiesta).exclude(pk=richiesta.pk).count()
        fatti["altre_aperte"] = aperte
        if aperte:
            segnali.append(("warn", f"La persona ha già {aperte} altra richiesta aperta per lo stesso DPI."))

        # Media del reparto: consegne nell'anno per persona dello stesso reparto, stesso DPI.
        if richiesta.richiedente_reparto:
            reparto = (_stesso_dpi(RichiestaDPI.objects.filter(richiedente_reparto=richiesta.richiedente_reparto,
                                                               stato=StatoRichiesta.CONSEGNATA, consegna__data_consegna__gte=anno_fa), richiesta)
                       .order_by().values("richiedente_legacy_id").annotate(n=Count("id")))
            conteggi = [r["n"] for r in reparto if r["richiedente_legacy_id"]]
            if len(conteggi) >= 3:
                media = sum(conteggi) / len(conteggi)
                fatti["media_reparto"] = round(media, 1)
                if len(nell_anno) >= max(2, 2 * media):
                    segnali.append(("warn", f"Nell'ultimo anno {len(nell_anno)} consegne contro una media di {media:.1f} nel reparto {richiesta.richiedente_reparto}."))

    if richiesta.modello_dpi_id:
        try:
            from . import magazzino

            giacenza = magazzino.giacenza(richiesta.modello_dpi_id)
            fatti["giacenza"] = giacenza
            if giacenza is not None and giacenza < richiesta.quantita:
                segnali.append(("warn", f"In magazzino {giacenza} pezzi: non bastano per {richiesta.quantita}."))
        except Exception:  # noqa: BLE001
            logger.debug("giacenza non disponibile", exc_info=True)

    # Come sono state gestite le richieste simili nell'ultimo anno (di tutti, senza nomi).
    simili = _stesso_dpi(RichiestaDPI.objects.filter(created_at__date__gte=anno_fa).exclude(pk=richiesta.pk), richiesta)
    esiti = dict(simili.filter(stato__in=[StatoRichiesta.APPROVATA, StatoRichiesta.CONSEGNATA, StatoRichiesta.RIFIUTATA])
                 .order_by().values_list("stato").annotate(n=Count("id")))
    approvate = esiti.get(StatoRichiesta.APPROVATA, 0) + esiti.get(StatoRichiesta.CONSEGNATA, 0)
    rifiutate = esiti.get(StatoRichiesta.RIFIUTATA, 0)
    fatti["simili_approvate"], fatti["simili_rifiutate"] = approvate, rifiutate
    fatti["motivi_rifiuto"] = [m.strip()[:160] for m in simili.filter(stato=StatoRichiesta.RIFIUTATA).exclude(note_gestione="")
                               .order_by("-updated_at").values_list("note_gestione", flat=True)[:3]]
    if approvate + rifiutate:
        segnali.append(("info", f"Richieste simili nell'ultimo anno: {approvate} approvate, {rifiutate} rifiutate."))
    fatti["segnali"] = [{"livello": livello, "testo": testo} for livello, testo in segnali]
    return fatti


def contesto(richiesta, fatti: dict) -> str:
    righe = [
        f"Richiesta DPI: {richiesta.categoria.nome}"
        + (f" / {richiesta.tipo_dpi.nome}" if richiesta.tipo_dpi_id else "")
        + (f" / modello {richiesta.modello_dpi.nome}" if richiesta.modello_dpi_id else "")
        + f", quantità {richiesta.quantita}, reparto {richiesta.richiedente_reparto or 'n.d.'}.",
        f"Motivazione scritta dal richiedente: {(richiesta.motivazione or '(nessuna)')[:400]}",
        f"Durata prevista del DPI: {fatti.get('vita_utile') or 'non indicata'} giorni.",
    ]
    righe += [f"Fatto: {s['testo']}" for s in fatti["segnali"]]
    if fatti.get("motivi_rifiuto"):
        righe.append("Motivi con cui il gestore ha rifiutato richieste simili: " + " | ".join(fatti["motivi_rifiuto"]))
    try:
        from ai_assistant.apprendimento import lezioni_testo

        lezioni = lezioni_testo(MODULO, AZIONE, etichette={"decisione": "decisione"})
        if lezioni:
            righe.append(lezioni)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(righe)


ISTRUZIONI = (
    "Sei l'assistente di chi gestisce i DPI in un'azienda manifatturiera italiana. Valuta la richiesta dai fatti del "
    "contesto e rispondi SOLO con JSON: {\"decisione\": \"approvare\" | \"chiedere_info\" | \"rifiutare\", \"messaggio\": "
    "frase cortese per il richiedente (max 2 frasi), \"motivazione\": una frase per il gestore con il fatto decisivo}. "
    "Regole: la sicurezza viene prima del risparmio, quindi un DPI rotto o perso si sostituisce anche prima della scadenza; "
    "se la consegna precedente è recente e la motivazione non spiega perché, proponi di chiedere informazioni (non di "
    "rifiutare); proponi di rifiutare solo per un doppione di una richiesta già aperta o per motivi già usati dal gestore "
    "in casi uguali. Segui le correzioni del gestore indicate nel contesto. Non inventare fatti."
)


def proponi_valutazione(richiesta, *, user=None) -> dict:
    fatti = storico_richiesta(richiesta)
    raw = ""
    try:
        from ai_assistant.services import chat_with_ollama

        raw = getattr(chat_with_ollama(ISTRUZIONI, runtime_context=contesto(richiesta, fatti), timeout=90), "content", "") or ""
    except Exception as exc:  # noqa: BLE001
        logger.info("copilota DPI richiesta: AI non disponibile: %s", exc)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except Exception:  # noqa: BLE001
        data = {}
    decisione = str(data.get("decisione") or "").strip().lower()
    decisione = decisione if decisione in DECISIONI else ""
    proposta = {
        "proposto": True,
        "ai_disponibile": bool(raw),
        "decisione": decisione,
        "decisione_label": DECISIONI.get(decisione, ""),
        "messaggio": str(data.get("messaggio") or "").strip()[:400],
        "motivazione": str(data.get("motivazione") or "").strip()[:300],
        "fatti": fatti,
    }
    try:
        from ai_assistant.apprendimento import lezioni, registra_proposta

        if decisione:
            registra_proposta(modulo=MODULO, azione=AZIONE, oggetto_ref=richiesta.pk, proposta={"decisione": decisione}, user=user)
        proposta["apprendimento"] = lezioni(MODULO, AZIONE)
    except Exception:  # noqa: BLE001
        proposta["apprendimento"] = None
    return proposta


def registra_esito(richiesta, decisione: str, user=None) -> None:
    """Il gestore ha approvato o rifiutato: lo confronta con la proposta (se c'era)."""
    try:
        from ai_assistant.apprendimento import registra_decisione

        registra_decisione(modulo=MODULO, azione=AZIONE, oggetto_ref=richiesta.pk, decisione={"decisione": decisione}, user=user)
    except Exception:  # noqa: BLE001
        logger.exception("Esito valutazione DPI non registrato")
