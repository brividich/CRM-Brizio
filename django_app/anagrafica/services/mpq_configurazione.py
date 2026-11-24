"""Configurazione di un processo qualificato (MOD.128): cosa è già inserito e cosa manca.

Una lista di controllo calcolata dai dati, mostrata in cima alla pagina del processo e
nelle sezioni dedicate finché manca qualcosa. Ogni voce porta dove si sistema. Le voci di
macchine e utensili compaiono solo se il processo le usa (frequenza macchine o macchine
collegate; utensili critici o Technical Plan registrati).
"""
from __future__ import annotations

from django.urls import reverse
from django.utils import timezone


def _voce(codice, etichetta, ok, dettaglio, url, azione):
    return {"codice": codice, "etichetta": etichetta, "ok": bool(ok), "dettaglio": dettaglio, "url": url,
            "azione": azione}


def voci(processo, *, oggi=None, macchine=None) -> list[dict]:
    """Le voci della lista per un processo. ``macchine`` = righe di ``mpq_macchine.righe_macchine`` già calcolate."""
    from ..models_mpq import AbilitazioneProcesso, TechnicalPlanRevisione

    oggi = oggi or timezone.localdate()
    dettaglio = reverse("anagrafica:mpq_processo_detail", args=[processo.pk])
    out = [
        _voce("stato", "Processo attivo", processo.stato == processo.STATO_ATTIVO,
              processo.get_stato_display(), reverse("anagrafica:mpq_processo_edit", args=[processo.pk]),
              "Modifica il processo"),
    ]
    n_rif = processo.riferimenti.count()
    out.append(_voce("riferimenti", "Documenti di riferimento", n_rif,
                     f"{n_rif} inseriti" if n_rif else "nessuno: istruzione tecnica, moduli, approvazione del cliente",
                     dettaglio + "#riferimenti", "Aggiungi i riferimenti"))
    n_pers = processo.abilitazioni.filter(stato=AbilitazioneProcesso.STATO_ATTIVA).count()
    out.append(_voce("persone", "Persone qualificate", n_pers,
                     f"{n_pers} abilitate" if n_pers else "nessuna persona abilitata",
                     dettaglio + "#persone", "Aggiungi le persone"))
    n_req = processo.requisiti_persona.count() + processo.corsi_richiesti.count()
    out.append(_voce("requisiti", "Cosa serve a una persona", n_req,
                     f"{n_req} requisiti" if n_req else "nessun requisito (es. corso di consapevolezza)",
                     dettaglio + "#requisiti-persone", "Aggiungi i requisiti"))

    if macchine is None:
        from .mpq_macchine import righe_macchine

        macchine = righe_macchine(processo, oggi=oggi)
    collegate = [r for r in macchine if r.get("collegata", True)]
    if collegate or processo.frequenza_macchine_mesi:
        verificate = [r for r in collegate if r["qualifica"] is not None
                      and r["stato"]["codice"] not in ("da_qualificare", "non_richiesta")]
        if not collegate:
            testo = "nessuna macchina collegata"
        else:
            testo = f"{len(verificate)} su {len(collegate)} con verifica MOD.161"
        out.append(_voce("macchine", "Macchine con verifica MOD.161", collegate and len(verificate) == len(collegate),
                         testo, dettaglio + "#attrezzature", "Collega e verifica le macchine"))

    n_ut = processo.utensili_critici.filter(attivo=True).count()
    piani = list(processo.technical_plan.prefetch_related("revisioni"))
    if n_ut or piani:
        approvati = [tp for tp in piani
                     if any(r.stato == TechnicalPlanRevisione.STATO_APPROVATA for r in tp.revisioni.all())]
        if not n_ut:
            testo, ok = "nessun utensile critico", False
        elif not piani:
            testo, ok = f"{n_ut} utensili critici, nessun Technical Plan", False
        else:
            ok = len(approvati) == len(piani)
            testo = f"{n_ut} utensili critici · {len(approvati)} su {len(piani)} Technical Plan approvati"
        out.append(_voce("utensili", "Utensili critici e Technical Plan", ok, testo,
                         reverse("anagrafica:mpq_utensili", args=[processo.pk]), "Apri utensili e Technical Plan"))
    return out


def riepilogo(processo, **kwargs) -> dict:
    """``{"voci", "fatte", "totale", "completa"}`` per il riquadro «Configurazione»."""
    elenco = voci(processo, **kwargs)
    fatte = sum(1 for v in elenco if v["ok"])
    return {"processo": processo, "voci": elenco, "fatte": fatte, "totale": len(elenco),
            "completa": fatte == len(elenco)}


def _norm(testo) -> str:
    import re
    import unicodedata

    t = unicodedata.normalize("NFD", str(testo or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", t)


def processi_simili(*, cliente_id=None, nome: str = "", sigla: str = "", escludi_pk=None) -> list:
    """Processi che sembrano lo stesso: stesso cliente e nome uguale o contenuto, nome uguale con un altro
    cliente, oppure stessa sigla di sezione dedicata. Per l'avviso «esiste già» su «Nuovo processo»."""
    from ..models_mpq import ProcessoQualificato

    chiave = _norm(nome)
    sigla = (sigla or "").strip().upper()
    trovati = []
    for p in ProcessoQualificato.objects.select_related("cliente").exclude(pk=escludi_pk).order_by("nome"):
        altro = _norm(p.nome)
        stesso_cliente = cliente_id is not None and p.cliente_id == cliente_id
        simile = bool(chiave) and (altro == chiave or (stesso_cliente and len(chiave) >= 5 and len(altro) >= 5
                                                       and (chiave in altro or altro in chiave)))
        stessa_sigla = bool(sigla) and p.sezione_dedicata and (p.sezione_sigla or "").upper() == sigla
        if simile or stessa_sigla:
            trovati.append({"processo": p, "stessa_sigla": stessa_sigla and not simile})
    return trovati
