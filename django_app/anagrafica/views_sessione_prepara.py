"""Percorso guidato di preparazione di una sessione formativa (27/11/2026).

Dopo «Crea sessione» l'utente non torna alla pagina della sessione a cercare i
pezzi: resta qui e passa Dati → Giornate → Iscritti → Pronta. Ogni passo usa le
azioni che esistono già (generatore giornate, aggiunta lezione, candidati del
corso, iscrizione in blocco) e ci ritorna con ``next``. Nessuno stato proprio:
un passo è fatto quando i dati ci sono, quindi si esce e si riprende quando si
vuole. Le sessioni «Online: slide + test» hanno già il loro percorso
(``sessione_online_prepara``) e vengono mandate lì.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import TrainingLezioniGeneraForm
from .models_formazione import TrainingSession
from .views import _helpers

ETICHETTE = {
    "dati": "Dati",
    "giornate": "Giornate",
    "iscritti": "Iscritti",
    "pronta": "Pronta",
}
# Modalità che hanno lezioni, presenze e foglio firme in azienda.
MODALITA_AULA = ("IN_SEDE", "MISTO")


def passi_per(sessione) -> list[str]:
    """Passi del percorso per la modalità della sessione. Presso ente esterno il
    calendario lo tiene l'ente: si iscrivono le persone e si carica l'attestato."""
    if sessione.modalita == "ESTERNO":
        return ["dati", "iscritti", "pronta"]
    return ["dati", "giornate", "iscritti", "pronta"]


def stato_preparazione(sessione, *, n_lezioni: int | None = None, n_iscritti: int | None = None) -> dict:
    """Passi fatti e primo passo mancante: è la stessa regola per il percorso e per
    il richiamo «Riprendi la preparazione» sulla pagina della sessione."""
    if n_lezioni is None:
        n_lezioni = sessione.lezioni.count()
    if n_iscritti is None:
        n_iscritti = sessione.iscrizioni.exclude(stato="RITIRATO").count()
    passi = passi_per(sessione)
    fatti = {"dati": True, "giornate": n_lezioni > 0, "iscritti": n_iscritti > 0}
    mancanti = [p for p in passi if p != "pronta" and not fatti.get(p)]
    return {
        "passi": passi,
        "fatti": fatti,
        "mancanti": mancanti,
        "primo_mancante": mancanti[0] if mancanti else "pronta",
        "completa": not mancanti,
    }


@login_required
def formazione_sessione_prepara(request, sessione_id: int):
    sessione = get_object_or_404(
        TrainingSession.objects.select_related("corso", "docente", "docente_ente"), pk=sessione_id,
    )
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per preparare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione.pk)
    if sessione.modalita == "ONLINE":
        return redirect("anagrafica:sessione_online_prepara", sessione_id=sessione.pk)
    from .services.formazione_integrita import motivo_blocco_edizione
    motivo = motivo_blocco_edizione(sessione)
    if motivo or sessione.stato == "ANNULLATA":
        messages.info(request, motivo or "L'edizione è annullata: non c'è niente da preparare.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione.pk)

    lezioni = list(sessione.lezioni.select_related("docente").order_by("data", "ora_inizio"))
    iscrizioni = list(sessione.iscrizioni.exclude(stato="RITIRATO").order_by("pk"))
    stato = stato_preparazione(sessione, n_lezioni=len(lezioni), n_iscritti=len(iscrizioni))
    passi = stato["passi"]
    passo = request.GET.get("passo")
    if passo not in passi:
        passo = stato["primo_mancante"]
    idx = passi.index(passo)

    ore_pianificate = round(sum(lz.durata_ore for lz in lezioni), 2)
    ore_teoriche = float(sessione.corso.durata_ore_teorica or 0)
    nomi = _helpers._build_nomi_map()
    for isc in iscrizioni:
        isc.nome = nomi.get(isc.legacy_anagrafica_id, f"#{isc.legacy_anagrafica_id}")
    iscrizioni.sort(key=lambda i: i.nome.lower())

    ctx = {
        "sessione": sessione,
        "passo": passo,
        "passi": [
            {"codice": p, "etichetta": ETICHETTE[p], "n": i + 1,
             "fatto": stato["fatti"].get(p, False), "attivo": p == passo}
            for i, p in enumerate(passi)
        ],
        "n_passo": idx + 1,
        "n_passi": len(passi),
        "passo_prec": passi[idx - 1] if idx > 0 else "",
        "passo_succ": passi[idx + 1] if idx + 1 < len(passi) else "",
        "stato": stato,
        "mancanti_etichette": [ETICHETTE[p] for p in stato["mancanti"]],
        "lezioni": lezioni,
        "iscrizioni": iscrizioni,
        "ore_pianificate": ore_pianificate,
        "ore_teoriche": ore_teoriche,
        "ore_scostamento": round(ore_pianificate - ore_teoriche, 2) if ore_teoriche else 0.0,
        "in_aula": sessione.modalita in MODALITA_AULA,
        "qui": f"{request.path}?passo={passo}",
    }

    if passo == "giornate":
        ultima = lezioni[-1] if lezioni else None
        ctx["genera_form"] = TrainingLezioniGeneraForm(initial={
            "ora_inizio": ultima.ora_inizio if ultima else "08:00",
            "ora_fine": ultima.ora_fine if ultima else "17:00",
            "pausa_minuti": ultima.pausa_minuti if ultima else 60,
        })
    elif passo == "iscritti":
        from core.persone_tendine import cessati_anagrafica_ids

        from .services.training_eligibility import candidati_corso
        candidati = candidati_corso(sessione.corso, sessione=sessione)
        gia = {i.legacy_anagrafica_id for i in iscrizioni}
        cessati = cessati_anagrafica_ids()
        ctx["candidati"] = candidati
        ctx["dipendenti_attivi"] = sorted(
            ((lid, nome) for lid, nome in nomi.items() if lid not in cessati and lid not in gia),
            key=lambda x: x[1].lower(),
        )
    return render(request, "anagrafica/pages/formazione_sessione_prepara.html", ctx)
