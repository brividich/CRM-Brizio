"""Emissioni del MOD.187 (MT CN 06 §8.4-8.5, 28/11/2026).

- §8.4: il MOD.187 si verifica ogni sei mesi (refresh del CAR, ``skillmatrix_refresh``)
  e si aggiorna a ogni ingresso, cambio di mansione, nuova macchina o fase, non
  conformità di competenza;
- §8.5: ogni emissione o aggiornamento è approvato e firmato da Direzione/RDD.

Un'emissione congela la matrice (stessa struttura del PDF MOD.187) e l'impronta
di ogni reparto. Se la matrice di un reparto oggi ha un'impronta diversa da quella
dell'ultima emissione valida, il reparto è «da emettere». La firma usa il Registro
timbri (``timbri.firme``), come l'organigramma ufficiale: Redazione di chi emette
(Qualità), Approvazione di RDD per la Direzione.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from timbri import firme

from ..models import EmissioneSkm

CHIAVE = "skill_matrix_mod187"

CASELLE_DI_SERIE = [
    {"etichetta": "Redazione", "mittente": True, "varianti": ["FIRMA", "SIGLA"]},
    {"etichetta": "Approvazione", "ruolo_sigla": "RDD", "varianti": ["FIRMA", "TIMBRO"]},
]


def _al_firmato(doc, user) -> None:
    e = EmissioneSkm.objects.select_for_update().get(pk=doc.oggetto_id)
    ultima = [x for x in doc.caselle.all() if x.stato == x.STATO_FIRMATA][-1]
    e.approvata_da = (ultima.nome_firmatario + (f" ({ultima.ruolo.sigla})" if ultima.ruolo_id and ultima.ruolo.sigla
                                                else ""))[:200]
    e.stato = EmissioneSkm.STATO_EMESSA
    e.emessa_il = timezone.now()
    e.save(update_fields=["approvata_da", "stato", "emessa_il"])
    doc.esito_id = e.pk
    doc.save(update_fields=["esito_id"])


firme.registra_tipo(CHIAVE, firme.TipoDocumento(
    nome="Skill Matrix MOD.187", caselle_di_serie=CASELLE_DI_SERIE, al_firmato=_al_firmato,
))


# ── istantanea e impronte ────────────────────────────────────────────────

def istantanea(dati: dict) -> dict:
    """La matrice in JSON, con le chiavi che usa ``skillmatrix_pdf.pdf_mod187``."""
    colonne = [{"nome": c["nome"], "reparto": c["reparto"], "conta": dict(c["conta"]), "totale": c["totale"],
                "macchina": c["macchina"]} for c in dati["colonne"]]
    gruppi, i = [], 0
    for g in dati["gruppi_colonne"]:
        n = len(g["colonne"])
        gruppi.append({"reparto": g["reparto"], "car": g["car"], "colonne": list(range(i, i + n))})
        i += n
    righe = [{
        "nome": r["nome"], "nome_mod": r["nome_mod"], "ruolo": r["ruolo"], "orario": r["orario"], "car": r["car"],
        "reparto": r["reparto"],
        "celle": [({"livello": x["livello"], "sospesa": x["sospesa"]} if x else None) for x in r["celle"]],
    } for r in dati["righe"]]
    return {"colonne": colonne, "gruppi_colonne": gruppi, "righe": righe}


def impronte(ist: dict) -> dict[str, str]:
    """{reparto: SHA-256} della parte di matrice del reparto (colonne, persone, livelli).

    Il ruolo non entra: dipende dal reparto prevalente della persona, quindi da
    cosa c'è a schermo, non dal contenuto del reparto.
    """
    out = {}
    for g in ist["gruppi_colonne"]:
        idx = g["colonne"]
        nomi = [ist["colonne"][i]["nome"] for i in idx]
        persone = []
        for r in ist["righe"]:
            celle = [(ist["colonne"][i]["nome"], r["celle"][i]["livello"], bool(r["celle"][i]["sospesa"]))
                     for i in idx if r["celle"][i]]
            if celle:
                persone.append([r["nome_mod"], r["orario"], celle])
        persone.sort()
        testo = json.dumps({"colonne": nomi, "car": g["car"], "persone": persone}, ensure_ascii=False,
                           separators=(",", ":"))
        out[g["reparto"]] = hashlib.sha256(testo.encode("utf-8")).hexdigest()
    return out


def solo_reparto(ist: dict, reparto: str) -> dict:
    """La parte di un'istantanea che riguarda un reparto (per il PDF di un reparto)."""
    if not reparto:
        return ist
    idx = [i for i, c in enumerate(ist["colonne"]) if c["reparto"].casefold() == reparto.casefold()]
    colonne = [ist["colonne"][i] for i in idx]
    righe = []
    for r in ist["righe"]:
        celle = [r["celle"][i] for i in idx]
        if any(celle):
            righe.append({**r, "celle": celle})
    gruppi = [{**g, "colonne": list(range(len(colonne)))} for g in ist["gruppi_colonne"]
              if g["reparto"].casefold() == reparto.casefold()]
    return {"colonne": colonne, "gruppi_colonne": gruppi, "righe": righe}


# ── stato per reparto ────────────────────────────────────────────────────

def stato_reparti(dati_tutti: dict, *, oggi: date | None = None) -> dict[str, dict]:
    """Per ogni reparto della matrice completa: ultima emissione valida, se la matrice
    è cambiata da allora, emissione in firma, verifica semestrale (refresh)."""
    from .skillmatrix_refresh import scadenzario_reparti

    oggi = oggi or timezone.localdate()
    correnti = impronte(istantanea(dati_tutti))
    emesse = list(EmissioneSkm.objects.filter(stato=EmissioneSkm.STATO_EMESSA).order_by("-emessa_il", "-numero")
                  .only("pk", "numero", "reparto", "data_emissione", "impronte", "emessa_il", "approvata_da"))
    in_firma = list(EmissioneSkm.objects.filter(stato=EmissioneSkm.STATO_IN_FIRMA).order_by("-numero")
                    .only("pk", "numero", "reparto", "creata_il"))
    verifiche = {r["reparto"].casefold(): r for r in scadenzario_reparti(oggi)}
    out = {}
    for rep, impronta in correnti.items():
        copre = lambda e: not e.reparto or e.reparto.casefold() == rep.casefold()  # noqa: E731
        ultima = next((e for e in emesse if copre(e)), None)
        out[rep] = {
            "ultima": ultima,
            "modificata": ultima is None or (ultima.impronte or {}).get(rep) != impronta,
            "in_firma": next((e for e in in_firma if copre(e)), None),
            "verifica": verifiche.get(rep.casefold()),
        }
    return out


# ── emissione ────────────────────────────────────────────────────────────

def firma_attiva() -> bool:
    return firme.impostazione(CHIAVE)["attiva"]


def in_firma_per(reparto: str) -> EmissioneSkm | None:
    qs = EmissioneSkm.objects.filter(stato=EmissioneSkm.STATO_IN_FIRMA)
    if reparto:
        qs = qs.filter(Q(reparto="") | Q(reparto__iexact=reparto))
    return qs.first()


def documento(e: EmissioneSkm):
    from timbri.models import DocumentoFirma
    if not e.documento_firma_id:
        return None
    return DocumentoFirma.objects.filter(pk=e.documento_firma_id).prefetch_related("caselle").first()


def emetti(request, dati: dict, *, reparto: str, data_emissione: date, nota: str, user) -> EmissioneSkm:
    """Crea l'emissione; con la firma accesa la invia in firma e firma subito la Redazione."""
    if in_firma_per(reparto) is not None:
        raise firme.FirmaNegata("C'è già un'emissione in firma per questo reparto: firmala o ritirala prima.")
    ist = istantanea(dati)
    if not ist["righe"]:
        raise firme.FirmaNegata("La matrice è vuota: niente da emettere.")
    imp = impronte(ist)
    with transaction.atomic():
        numero = (EmissioneSkm.objects.aggregate(m=Max("numero"))["m"] or 0) + 1
        e = EmissioneSkm.objects.create(
            numero=numero, reparto=reparto, data_emissione=data_emissione, nota=(nota or "")[:2000], contenuto=ist,
            impronte=imp, creata_da=user if getattr(user, "is_authenticated", False) else None,
        )
        if not firma_attiva():
            e.stato = EmissioneSkm.STATO_EMESSA
            e.emessa_il = timezone.now()
            e.approvata_da = firme.nome_utente(user)[:200]
            e.save(update_fields=["stato", "emessa_il", "approvata_da"])
            return e
        impronta_tutto = hashlib.sha256(json.dumps(ist, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        doc = firme.invia(CHIAVE, oggetto_id=e.pk, titolo=f"MOD.187 n.{numero} · {e.ambito}", numero=numero,
                          contenuto={"emissione": e.pk, "reparto": reparto, "data_emissione": data_emissione.isoformat(),
                                     "matrice_sha256": impronta_tutto, "impronte": imp},
                          nota=nota, user=user)
        e.documento_firma_id = doc.pk
        e.save(update_fields=["documento_firma_id"])
        prima = firme.casella_corrente(doc)
        if prima is not None and prima.mittente:
            firme.firma(request, doc, user=user, scelta=request.POST.get("scelta") or "",
                        segreto=request.POST.get("segreto") or "",
                        dichiarazione=request.POST.get("dichiarazione") == "1")
    e.refresh_from_db()
    return e


def chiudi_senza_firma(e: EmissioneSkm, stato: str) -> None:
    e.stato = stato
    e.save(update_fields=["stato"])


def differenze(prima: dict | None, dopo: dict) -> list[dict]:
    """Cosa cambia fra due istantanee: persona, colonna, da → a."""
    def mappa(ist):
        out = {}
        if not ist:
            return out
        for r in ist["righe"]:
            for i, x in enumerate(r["celle"]):
                if x:
                    out[(r["nome"], ist["colonne"][i]["nome"])] = x["livello"] + (" sospesa" if x["sospesa"] else "")
        return out
    a, b = mappa(prima), mappa(dopo)
    righe = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            righe.append({"persona": k[0], "colonna": k[1], "da": a.get(k, ""), "a": b.get(k, "")})
    return righe
