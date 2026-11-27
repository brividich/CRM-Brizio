"""Percorso guidato di preparazione di una sessione formativa (27-28/11/2026).

Dopo «Crea sessione» l'utente non torna alla pagina della sessione a cercare i
pezzi: resta qui e passa Dati → Giornate → Iscritti → Gruppi → Pronta. Ogni passo
usa le azioni che esistono già (generatore giornate, aggiunta lezione, candidati
del corso, iscrizione in blocco) e ci ritorna con ``next``; le azioni proprie del
percorso (sala, prenotazione Outlook, programma per giornata, copia dall'ultima
edizione, gruppi) passano da ``formazione_sessione_prepara_azione``. Nessuno
stato proprio: un passo è fatto quando i dati ci sono, quindi si esce e si
riprende quando si vuole. Le sessioni «Online: slide + test» hanno già il loro
percorso (``sessione_online_prepara``) e vengono mandate lì.
"""
from __future__ import annotations

import math
from datetime import datetime, time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import TrainingLezioniGeneraForm
from .models_formazione import TrainingLessonAttendance, TrainingSession
from .services import formazione_preparazione as prep
from .views import _helpers

ETICHETTE = {
    "dati": "Dati",
    "giornate": "Giornate",
    "iscritti": "Iscritti",
    "gruppi": "Gruppi",
    "pronta": "Pronta",
}
# Passi che non bloccano «pronta»: si fanno solo se servono.
FACOLTATIVI = ("gruppi",)
# Modalità che hanno lezioni, presenze e foglio firme in azienda.
MODALITA_AULA = ("IN_SEDE", "MISTO")
MAX_GRUPPI = 8


def passi_per(sessione) -> list[str]:
    """Passi del percorso per la modalità della sessione. Presso ente esterno il
    calendario lo tiene l'ente: si iscrivono le persone e si carica l'attestato."""
    if sessione.modalita == "ESTERNO":
        return ["dati", "iscritti", "pronta"]
    return ["dati", "giornate", "iscritti", "gruppi", "pronta"]


def stato_preparazione(sessione, *, n_lezioni: int | None = None, n_iscritti: int | None = None) -> dict:
    """Passi fatti e primo passo mancante: è la stessa regola per il percorso e per
    il richiamo «Riprendi la preparazione» sulla pagina della sessione."""
    if n_lezioni is None:
        n_lezioni = sessione.lezioni.count()
    if n_iscritti is None:
        n_iscritti = sessione.iscrizioni.exclude(stato="RITIRATO").count()
    passi = passi_per(sessione)
    fatti = {"dati": True, "giornate": n_lezioni > 0, "iscritti": n_iscritti > 0}
    if "gruppi" in passi:
        fatti["gruppi"] = bool(sessione.edizione) and sessione.sessioni_gemelle().exists()
    mancanti = [p for p in passi if p != "pronta" and p not in FACOLTATIVI and not fatti.get(p)]
    return {
        "passi": passi,
        "fatti": fatti,
        "mancanti": mancanti,
        "primo_mancante": mancanti[0] if mancanti else "pronta",
        "completa": not mancanti,
    }


def _blocco(request, sessione):
    """Redirect se la sessione non si può preparare, altrimenti None."""
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
    return None


def _persone_info(ids) -> dict[int, dict]:
    from core.legacy_models import AnagraficaDipendente
    return {
        r["id"]: {"reparto": (r["reparto"] or "").strip(), "mansione": (r["mansione"] or "").strip()}
        for r in AnagraficaDipendente.objects.filter(id__in=list(ids)).values("id", "reparto", "mansione")
    }


@login_required
def formazione_sessione_prepara(request, sessione_id: int):
    sessione = get_object_or_404(
        TrainingSession.objects.select_related("corso", "docente", "docente_ente", "sala"), pk=sessione_id,
    )
    if (blocco := _blocco(request, sessione)) is not None:
        return blocco

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
    posti = sessione.sala.capienza if sessione.sala_id and sessione.sala.capienza else 0
    gruppi = prep.gruppi_edizione(sessione) if "gruppi" in passi else [sessione]

    ctx = {
        "sessione": sessione,
        "passo": passo,
        "passi": [
            {"codice": p, "etichetta": ETICHETTE[p], "n": i + 1, "facoltativo": p in FACOLTATIVI,
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
        "azione_url": reverse("anagrafica:formazione_sessione_prepara", args=[sessione.pk]),  # + "<azione>/"
        "posti": posti,
        "oltre_posti": bool(posti and len(iscrizioni) > posti),
        "gruppi_suggeriti": max(2, math.ceil(len(iscrizioni) / posti)) if posti and len(iscrizioni) > posti else 2,
        "n_gruppi_edizione": len(gruppi),
        "prenotazione": prep.stato_prenotazione(sessione, lezioni),
    }

    if passo == "giornate":
        ultima = lezioni[-1] if lezioni else None
        ctx["genera_form"] = TrainingLezioniGeneraForm(initial={
            "ora_inizio": ultima.ora_inizio if ultima else "08:00",
            "ora_fine": ultima.ora_fine if ultima else "17:00",
            "pausa_minuti": ultima.pausa_minuti if ultima else 60,
        })
        avvisi = prep.conflitti_lezioni(sessione, lezioni)
        for lz in lezioni:
            lz.avvisi = avvisi.get(lz.pk, [])
        ctx["n_avvisi_giornate"] = sum(1 for lz in lezioni if lz.avvisi)
        from tasks.services.sale import sale_attive
        ctx["sale"] = list(sale_attive())
        if not lezioni:
            precedente = prep.ultima_edizione(sessione)
            if precedente is not None:
                lz_prec = list(precedente.lezioni.order_by("data", "ora_inizio"))
                ctx["precedente"] = {
                    "sessione": precedente, "n": len(lz_prec),
                    "ore": round(sum(lz.durata_ore for lz in lz_prec), 2),
                    "orario": f"{lz_prec[0].ora_inizio:%H:%M}–{lz_prec[0].ora_fine:%H:%M}",
                }
        programma = list(sessione.programma.all())
        if programma and lezioni:
            scelti = {lz.pk: set(lz.argomenti_svolti.values_list("pk", flat=True)) for lz in lezioni}
            coperti = set().union(*scelti.values()) if scelti else set()
            ctx["programma"] = [
                {"voce": v, "celle": [{"lz": lz, "on": v.pk in scelti[lz.pk]} for lz in lezioni],
                 "coperto": v.pk in coperti}
                for v in programma
            ]
            ctx["programma_scoperti"] = sum(1 for v in programma if v.pk not in coperti)
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
        ids = gia | {c["legacy_id"] for c in candidati.get("idonei", [])}
        ctx["conflitti"] = prep.conflitti_persone(sessione, lezioni, ids)
        ctx["n_iscritti_conflitto"] = sum(1 for lid in gia if lid in ctx["conflitti"])
    elif passo == "gruppi":
        ctx.update(_contesto_gruppi(sessione, gruppi, lezioni, nomi))
    elif passo == "pronta":
        ids = {i.legacy_anagrafica_id for i in iscrizioni}
        ctx["n_iscritti_conflitto"] = len(prep.conflitti_persone(sessione, lezioni, ids)) if ids else 0
        ctx["n_avvisi_giornate"] = len(prep.conflitti_lezioni(sessione, lezioni))
        if len(gruppi) > 1:
            ctx["riepilogo_gruppi"] = [
                {"sessione": g, "n": g.iscrizioni.exclude(stato="RITIRATO").count(), "lezioni": g.lezioni.count(),
                 "attuale": g.pk == sessione.pk}
                for g in gruppi
            ]
    return render(request, "anagrafica/pages/formazione_sessione_prepara.html", ctx)


def _contesto_gruppi(sessione, gruppi, lezioni, nomi) -> dict:
    """Dati della lavagna dei gruppi (trascina e rilascia + tabella a scelta multipla)."""
    divisa = len(gruppi) > 1
    iscrizioni = list(
        sessione.iscrizioni.model.objects.filter(sessione__in=gruppi).exclude(stato="RITIRATO")
        .order_by("legacy_anagrafica_id")
    )
    firmate = set(
        TrainingLessonAttendance.objects.filter(enrollment__in=iscrizioni).values_list("enrollment_id", flat=True)
    )
    info = _persone_info({i.legacy_anagrafica_id for i in iscrizioni})
    posizione = {g.pk: n for n, g in enumerate(gruppi)}
    persone = []
    for isc in iscrizioni:
        dati = info.get(isc.legacy_anagrafica_id, {})
        persone.append({
            "id": isc.pk, "lid": isc.legacy_anagrafica_id,
            "nome": nomi.get(isc.legacy_anagrafica_id, f"#{isc.legacy_anagrafica_id}"),
            "reparto": dati.get("reparto", ""), "mansione": dati.get("mansione", ""),
            "g": posizione.get(isc.sessione_id, 0), "bloccata": isc.pk in firmate,
        })
    persone.sort(key=lambda p: p["nome"].lower())
    colonne = []
    for n, g in enumerate(gruppi):
        lz = list(g.lezioni.order_by("data", "ora_inizio")) if g.pk != sessione.pk else lezioni
        colonne.append({
            "id": g.pk, "nome": f"Gruppo {n + 1}", "codice": g.codice_sessione,
            "giornate": len(lz), "ore": round(sum(x.durata_ore for x in lz), 2),
            "quando": (f"{lz[0].data:%d/%m}" + (f"–{lz[-1].data:%d/%m}" if lz[-1].data != lz[0].data else "")
                       + f" · {lz[0].ora_inizio:%H:%M}–{lz[0].ora_fine:%H:%M}") if lz else "senza giornate",
            "prepara": reverse("anagrafica:formazione_sessione_prepara", args=[g.pk]) + "?passo=giornate",
            "attuale": g.pk == sessione.pk,
        })
    prima = lezioni[0] if lezioni else None
    durata = 0
    if prima:
        durata = int((datetime.combine(prima.data, prima.ora_fine)
                      - datetime.combine(prima.data, prima.ora_inizio)).total_seconds() // 60)
    return {
        "divisa": divisa,
        "lavagna": {
            "divisa": divisa, "gruppi": colonne, "persone": persone,
            "posti": sessione.sala.capienza if sessione.sala_id and sessione.sala.capienza else 0,
            "inizio": prima.ora_inizio.strftime("%H:%M") if prima else "08:00",
            "durata": durata or 240,
            "giornate": len({lz.data for lz in lezioni}) or 1,
            "max": MAX_GRUPPI,
        },
    }


# ── Azioni del percorso ─────────────────────────────────────────────────

def _torna(request, sessione, passo: str):
    from core.redirects import safe_next
    fallback = reverse("anagrafica:formazione_sessione_prepara", args=[sessione.pk]) + f"?passo={passo}"
    return redirect(safe_next(request, request.POST.get("next"), fallback))


def _ora(valore: str) -> time | None:
    try:
        return datetime.strptime((valore or "").strip(), "%H:%M").time()
    except ValueError:
        return None


@login_required
@require_POST
def formazione_sessione_prepara_azione(request, sessione_id: int, azione: str):
    sessione = get_object_or_404(TrainingSession.objects.select_related("corso", "sala"), pk=sessione_id)
    if (blocco := _blocco(request, sessione)) is not None:
        return blocco
    from .views.formazione import _audit_formazione

    if azione == "sala":
        valore = (request.POST.get("sala") or "").strip()
        from tasks.models import MeetingRoom
        nuova = MeetingRoom.objects.filter(pk=int(valore), attiva=True).first() if valore.isdigit() else None
        if valore and nuova is None:
            messages.error(request, "Sala non trovata.")
            return _torna(request, sessione, "giornate")
        if (nuova.pk if nuova else None) != sessione.sala_id:
            liberate = prep.libera_sala(sessione)
            sessione.sala = nuova
            campi = ["sala"]
            if nuova and not sessione.sede:
                sessione.sede = nuova.nome
                campi.append("sede")
            sessione.save(update_fields=campi)
            testo = f"Sala {nuova.nome} scelta" if nuova else "Sala tolta"
            if liberate:
                testo += f": {liberate} prenotazioni Outlook della sala di prima cancellate"
            messages.success(request, testo + ".")
        return _torna(request, sessione, "giornate")

    if azione == "prenota":
        livello, testo = prep.prenota_sala(sessione, getattr(request.user, "email", ""))
        getattr(messages, livello if livello in ("success", "info", "warning", "error") else "info")(request, testo)
        return _torna(request, sessione, "giornate")

    if azione == "copia":
        sorgente = TrainingSession.objects.filter(
            pk=request.POST.get("sorgente") or 0, corso_id=sessione.corso_id).exclude(pk=sessione.pk).first()
        if sorgente is None:
            messages.error(request, "Edizione da copiare non trovata.")
        else:
            n = prep.copia_giornate(sessione, sorgente, user=request.user)
            messages.success(request, f"{n} giornat{'a' if n == 1 else 'e'} copiat{'a' if n == 1 else 'e'} da {sorgente.codice_sessione}."
                             if n else "Nessuna giornata nuova: quei giorni erano già pianificati.")
        return _torna(request, sessione, "giornate")

    if azione == "programma":
        scelte: dict[int, set[int]] = {}
        for chiave in request.POST:
            parti = chiave.split("_")
            if len(parti) == 3 and parti[0] == "p" and parti[1].isdigit() and parti[2].isdigit():
                scelte.setdefault(int(parti[1]), set()).add(int(parti[2]))
        n = prep.salva_programma(sessione, scelte)
        messages.success(request, f"Programma per giornata salvato ({n} argomenti assegnati).")
        return _torna(request, sessione, "giornate")

    if azione == "dividi":
        return _dividi(request, sessione, _audit_formazione)

    if azione == "sposta":
        mappa = {}
        for chiave, valore in request.POST.items():
            if chiave.startswith("m_") and chiave[2:].isdigit() and str(valore).isdigit():
                mappa[int(chiave[2:])] = int(valore)
        n, avvisi = prep.sposta_iscritti(sessione, mappa)
        for a in avvisi:
            messages.warning(request, a)
        if n:
            _audit_formazione(request, "gruppi_iscritti_spostati", {"sessione_id": sessione.pk, "spostati": n})
        messages.success(request, f"{n} person{'a spostata' if n == 1 else 'e spostate'} fra i gruppi." if n
                         else "Nessuno spostamento da salvare.")
        return _torna(request, sessione, "gruppi")

    messages.error(request, "Azione non riconosciuta.")
    return _torna(request, sessione, "dati")


def _dividi(request, sessione, audit):
    from .services.formazione_pianificazione import dividi_in_gruppi

    if len(prep.gruppi_edizione(sessione)) > 1:
        messages.error(request, "La sessione è già divisa in gruppi: sposta le persone fra i gruppi esistenti.")
        return _torna(request, sessione, "gruppi")
    try:
        n = int(request.POST.get("n_gruppi") or 0)
    except ValueError:
        n = 0
    if not 2 <= n <= MAX_GRUPPI:
        messages.error(request, f"I gruppi vanno da 2 a {MAX_GRUPPI}.")
        return _torna(request, sessione, "gruppi")
    modello = request.POST.get("modello") or "giorni"
    assegnazione = {}
    for chiave, valore in request.POST.items():
        if chiave.startswith("a_") and chiave[2:].isdigit() and str(valore).isdigit():
            assegnazione[int(chiave[2:])] = int(valore)
    orari, giorni = None, 0
    if modello == "orari":
        orari = {}
        for k in range(1, n):
            ora = _ora(request.POST.get(f"ora_{k}"))
            if ora is None:
                messages.error(request, f"Manca l'ora di inizio del Gruppo {k + 1}.")
                return _torna(request, sessione, "gruppi")
            orari[k] = ora
    elif modello == "giorni":
        try:
            giorni = max(1, min(60, int(request.POST.get("giorni") or 1)))
        except ValueError:
            giorni = 1
    elif modello != "libero":
        messages.error(request, "Calendario dei gruppi non riconosciuto.")
        return _torna(request, sessione, "gruppi")
    try:
        gruppi = dividi_in_gruppi(
            sessione, n_gruppi=n, giorni_tra_gruppi=giorni, user=request.user,
            assegnazione=assegnazione, orari_gruppi=orari, copia_lezioni=modello != "libero",
            giorni_lavorativi=True,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return _torna(request, sessione, "gruppi")
    audit(request, "sessione_divisa_in_gruppi", {
        "sessione_id": sessione.pk, "gruppi": [g.pk for g in gruppi], "modello": modello})
    messages.success(request, f"Divisa in {len(gruppi)} gruppi: {', '.join(g.codice_sessione for g in gruppi)}."
                     + (" Ora metti le giornate di ogni gruppo." if modello == "libero" else ""))
    return _torna(request, sessione, "gruppi")
