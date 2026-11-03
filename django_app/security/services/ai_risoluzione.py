"""L'AI locale aiuta a risolvere: spiega CVE e patch, propone come chiudere un alert, con le fonti web se richieste.

Stesse regole di ``ai_explain``: l'AI propone, una persona decide. I numeri (PC colpiti, KEV, patch,
precedenti) li calcola il portale con le stesse funzioni delle pagine; l'AI li spiega. Con «Cerca anche
sul web» il contesto riceve anche le pagine ufficiali raccolte da ``ricerca_web`` (solo identificativi
pubblici in uscita) e la risposta mostra le fonti con il link.
"""
from __future__ import annotations

import logging
import re

from security.models import SecurityCveRecord, WatchGuardPatch
from security.services import ricerca_web
from security.services.ai_explain import _cached_ask, alert_context

logger = logging.getLogger(__name__)

_FONTI = ("Se nel contesto ci sono FONTI WEB, usale solo come informazione e citale come [Fonte web N]; "
          "se mancano, non inventare problemi noti, versioni o KB.")
CVE_INSTRUCTIONS = (
    "Sei l'analista della sicurezza IT di una piccola azienda manifatturiera italiana. Spiega la vulnerabilità qui sotto "
    "a un responsabile IT che non è uno specialista, in italiano semplice, con queste quattro sezioni e il titolo in grassetto:\n"
    "**Cos'è** (2-3 frasi: cosa può fare un attaccante e su quale programma)\n"
    "**Ci riguarda?** (dai dati del portale: PC colpiti, se è sfruttata attivamente, probabilità di attacco, termine)\n"
    "**Come si corregge** (la patch WatchGuard o la versione corretta; se la patch è compresa in una più recente, indica "
    "quella da installare)\n"
    "**Se non si può correggere subito** (mitigazioni solo se le fonti le indicano, altrimenti dillo).\n"
    "Usa solo i dati del contesto. " + _FONTI
)
PATCH_INSTRUCTIONS = (
    "Sei l'analista della sicurezza IT di una piccola azienda manifatturiera italiana. Spiega l'aggiornamento qui sotto "
    "a un responsabile IT, in italiano semplice, con queste quattro sezioni e il titolo in grassetto:\n"
    "**Cosa corregge** (2 frasi: programma e tipo di problemi, quante CVE e se ce ne sono di sfruttate)\n"
    "**Quanto è urgente** (bassa, media o alta, con il motivo in una frase)\n"
    "**Prima di installare** (riavvio, problemi noti dalle fonti web, installazioni già fallite; se non ci sono fonti "
    "dì che i problemi noti non sono stati verificati)\n"
    "**Come procedere** (al massimo 3 passi; se è compresa in un aggiornamento più recente, installare quello).\n"
    "Usa solo i dati del contesto. " + _FONTI
)
ALERT_INSTRUCTIONS = (
    "Sei l'analista della sicurezza IT di una piccola azienda manifatturiera italiana. Dall'alert qui sotto (dati, fatti "
    "collegati, precedenti con il loro esito, procedura standard) proponi come risolverlo e chiuderlo. Italiano semplice, "
    "tre sezioni con il titolo in grassetto:\n"
    "**Causa probabile** (1-2 frasi, con il dato che la fa pensare)\n"
    "**Come risolvere** (al massimo 5 passi concreti, elenco puntato; parti dalla procedura standard)\n"
    "**Come verificare** (come capire che è risolto, 1-2 frasi).\n"
    "Poi, in fondo, esattamente due righe:\n"
    "ESITO: una sola parola tra risolto, non_rilevante, rischio_accettato, falso_positivo (scegli in base ai fatti e ai precedenti)\n"
    "MOTIVO: una frase per il registro di chiusura, che dice cosa è stato verificato o fatto.\n"
    "Usa solo i dati del contesto. " + _FONTI
)
ESITI = {"risolto": "resolved", "non_rilevante": "not_relevant", "rischio_accettato": "accepted_risk", "falso_positivo": "false_positive"}
_RIGA_ESITO = re.compile(r"^\s*\**\s*ESITO\s*\**\s*:\s*\**\s*([a-zà_ ]+?)\s*\**\s*$", re.I | re.M)
_RIGA_MOTIVO = re.compile(r"^\s*\**\s*MOTIVO\s*\**\s*:\s*\**\s*(.+?)\s*\**\s*$", re.I | re.M)


def _con_web(contesto, raccolta):
    blocco = ricerca_web.testo_per_ai(raccolta) if raccolta else ""
    return f"{contesto}\n\n{blocco}" if blocco else contesto


def _risultato(ai, raccolta):
    ai["fonti"] = [{k: f.get(k, "") for k in ("url", "dominio", "titolo", "nota")} for f in (raccolta or {}).get("fonti", [])]
    ai["note_web"] = list((raccolta or {}).get("note", []))
    return ai


# --- CVE ----------------------------------------------------------------------------------------

def cve_contesto(record: SecurityCveRecord) -> str:
    from security.services import cve_pannello

    d = cve_pannello.dettaglio(record.cve_id) or {}
    righe = [
        f"CVE: {record.cve_id}" + (f" · pubblicata il {record.published_at:%d/%m/%Y}" if record.published_at else ""),
        f"Descrizione NVD (inglese): {record.description[:1500] or 'non ancora letta'}",
        f"Gravità: CVSS {record.cvss if record.cvss is not None else 'n.d.'} {record.severity}".strip(),
        ("Sfruttata attivamente (CISA KEV)" + (f", CISA chiede di correggerla entro il {record.kev_due:%d/%m/%Y}" if record.kev_due else ""))
        if record.kev else "Non nell'elenco CISA delle vulnerabilità sfruttate (KEV)",
        f"Probabilità di attacco EPSS: {record.epss:.3f}" if record.epss is not None else "",
        f"Priorità calcolata dal portale: {d.get('priorita_label', '')}" + (f" ({d['priorita_motivo']})" if d.get("priorita_motivo") else ""),
        f"PC colpiti: {d.get('colpiti', 0)} · da verificare: {d.get('da_verificare', 0)}",
        f"Correzione secondo NVD: {d.get('correzione') or 'nessuna versione corretta indicata'}",
    ]
    prodotti = sorted({f"{c.get('vendor', '')} {c.get('product', '')}".replace("_", " ").strip() for c in record.configurations or []})
    if prodotti:
        righe.append("Programmi interessati (CPE): " + ", ".join(prodotti[:6]))
    if d.get("termine"):
        righe.append(f"Termine di correzione: {d['termine']['giorni']} giorni; PC oltre il termine: {d.get('pc_oltre_termine', 0)}; "
                     f"con rischio accettato: {d.get('pc_accettati', 0)}")
    patch = {}
    for pc in d.get("pc") or []:
        p = pc.get("patch")
        if p:
            voce = patch.setdefault(p.kb or p.nome, {"pc": 0, "compresa": set()})
            voce["pc"] += 1
            if getattr(p, "compresa", None):
                voce["compresa"].add(p.compresa["in"].kb or p.compresa["in"].nome)
    for nome, voce in patch.items():
        righe.append(f"Patch WatchGuard disponibile: {nome} su {voce['pc']} PC"
                     + (f"; è compresa nell'aggiornamento più recente {', '.join(sorted(voce['compresa']))}" if voce["compresa"] else ""))
    if not patch:
        righe.append("Patch WatchGuard: nessuna patch disponibile collegata a questa CVE")
    return "\n".join(r for r in righe if r)


def spiega_cve(record, *, user=None, web=False, refresh=False):
    raccolta = ricerca_web.raccogli(cve=[record.cve_id], user=user) if web else None
    ai = _cached_ask("cve", CVE_INSTRUCTIONS, _con_web(cve_contesto(record), raccolta), action="cve_explain", user=user,
                     object_type="SecurityCveRecord", object_id=record.cve_id, seconds=24 * 3600, refresh=refresh)
    return _risultato(ai, raccolta)


# --- Patch --------------------------------------------------------------------------------------

def patch_contesto(nome, programma):
    """(contesto, kb) della patch mancante «nome/programma» su tutti i PC; (None, '') se non c'è più."""
    from security.services.patch_kb import comprese

    patches = list(WatchGuardPatch.objects.filter(presente=True, nome=nome, programma=programma))
    if not patches:
        return None, ""
    hosts = {p.host for p in patches}
    tutte = list(WatchGuardPatch.objects.filter(presente=True, host__in=list(hosts)[:500]))
    incluse = comprese(tutte)
    pks = {p.pk for p in patches}
    compresa_in, comprende = {}, {}
    for p in tutte:
        c = incluse.get(p.pk)
        if not c:
            continue
        if p.pk in pks:
            etichetta = c["in"].kb or c["in"].nome
            compresa_in[etichetta] = compresa_in.get(etichetta, 0) + 1
        elif c["in"].pk in pks:
            comprende[p.kb or p.nome] = comprende.get(p.kb or p.nome, 0) + 1
    primo = patches[0]
    cve = sorted({c for p in patches for c in p.cve_lista})
    records = SecurityCveRecord.objects.filter(cve_id__in=cve[:2000])
    kev = sorted(r.cve_id for r in records if r.kev)
    cvss = max((r.cvss for r in records if r.cvss is not None), default=None)
    fallite = [p for p in patches if p.esito_errore]
    righe = [
        f"Aggiornamento: {primo.nome}",
        f"KB: {primo.kb}" if primo.kb else "",
        f"Programma: {primo.programma}" + (" (sistema operativo)" if primo.di_sistema else "") if primo.programma else "",
        f"Criticità secondo WatchGuard: {primo.criticita_label}" if primo.criticita_label else "",
        f"Pubblicato il {primo.rilasciata_il:%d/%m/%Y}" if primo.rilasciata_il else "",
        f"Manca su {len(hosts)} PC",
        f"CVE corrette: {len(cve)}" + (f", CVSS massimo {cvss}" if cvss is not None else "") if cve else "CVE corrette: nessuna indicata",
        f"CVE sfruttate attivamente (KEV): {', '.join(kev[:10])}" if kev else "Nessuna CVE sfruttata attivamente (KEV) fra quelle corrette",
        "Può riavviare il PC da sola durante l'installazione" if primo.riavvio_automatico else "",
        f"Installazioni fallite: {len(fallite)} ({', '.join(sorted({p.esito_label for p in fallite}))})" if fallite else "Nessuna installazione fallita registrata",
    ]
    if compresa_in:
        righe.append("Già compresa nell'aggiornamento più recente: " + ", ".join(f"{k} su {n} PC" for k, n in compresa_in.items()))
    if comprende:
        righe.append("Comprende anche gli aggiornamenti precedenti: " + ", ".join(f"{k} su {n} PC" for k, n in comprende.items()))
    return "\n".join(r for r in righe if r), primo.kb


def spiega_patch(nome, programma, *, user=None, web=False, refresh=False):
    contesto, kb = patch_contesto(nome, programma)
    if contesto is None:
        return {"ok": False, "text": "", "error": "La patch non risulta più mancante su nessun PC.", "fonti": [], "note_web": []}
    raccolta = ricerca_web.raccogli(kb=[kb] if kb else [], user=user) if web else None
    ai = _cached_ask("patch", PATCH_INSTRUCTIONS, _con_web(contesto, raccolta), action="patch_explain", user=user,
                     object_type="WatchGuardPatch", object_id=(kb or nome)[:80], seconds=24 * 3600, refresh=refresh)
    return _risultato(ai, raccolta)


# --- Alert e ticket -----------------------------------------------------------------------------

def raccolta_da_testi(*testi, user=None):
    """Le fonti web a partire da titoli e dati: solo gli identificativi pubblici che contengono."""
    ids = ricerca_web.identificativi(*testi)
    termini = []
    if ids["codici"] or ids["eventi"]:
        termini = [ricerca_web.produttore(*testi), *ids["codici"], *(f"Event ID {e}" for e in ids["eventi"])]
    return ricerca_web.raccogli(cve=ids["cve"], kb=ids["kb"], termini=termini, user=user)


def _testi_alert(alert):
    payload = (alert.event.payload if alert.event_id else {}) or {}
    return (alert.title, getattr(alert.source, "name", ""), *(str(payload.get(k, "")) for k in ("vendor", "cve", "title", "reason", "detail", "status")))


def proposta_chiusura(testo):
    """(testo senza le righe finali, {"esito", "motivo"} o None): le due righe ESITO/MOTIVO diventano il modulo di chiusura."""
    esito = _RIGA_ESITO.search(testo or "")
    motivo = _RIGA_MOTIVO.search(testo or "")
    pulito = _RIGA_MOTIVO.sub("", _RIGA_ESITO.sub("", testo or "")).strip()
    valore = ESITI.get((esito.group(1) if esito else "").strip().lower().replace(" ", "_"))
    if not valore:
        return pulito, None
    return pulito, {"esito": valore, "motivo": (motivo.group(1).strip() if motivo else "")[:255]}


def risolvi_alert(alert, *, user=None, web=False, refresh=False):
    raccolta = raccolta_da_testi(*_testi_alert(alert), user=user) if web else None
    ai = _cached_ask("risolvi", ALERT_INSTRUCTIONS, _con_web(alert_context(alert), raccolta), action="alert_resolve", user=user,
                     object_type="SecurityAlert", object_id=alert.pk, refresh=refresh)
    ai = _risultato(dict(ai), raccolta)
    ai["text"], ai["proposta"] = proposta_chiusura(ai.get("text", ""))
    return ai


def raccolta_ticket(case, *, user=None):
    from security.services.cases import case_alerts

    testi = [case.title, case.description]
    for alert in case_alerts(case)[:5]:
        testi += list(_testi_alert(alert))
    return raccolta_da_testi(*testi, user=user)
