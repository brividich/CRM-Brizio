"""Pagine d'ingresso delle sezioni di Anagrafica nello «stile C»: una scheda per oggetto.

Ogni sezione (Persone, Ingressi, Qualifiche, Salute e sicurezza, Visite,
Amministrazione, Report) mostra in alto una griglia di schede: una per l'oggetto
che la sezione governa (reparto, posizione aperta, tipo di qualifica, mansione di
rischio, tipo di visita, import, modello), ciascuna con una barra impilata. Qui si
costruiscono i dati delle schede; la resa è in ``components/_fmd_cc_grid.html``.

Le funzioni leggono gli stessi dati dei numeri in alto di ciascuna pagina, così le
schede e i numeri non si contraddicono. Nessuna funzione espone dati sanitari: le
visite arrivano già aggregate per tipo, l'idoneità non compare mai.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.urls import NoReverseMatch, reverse

# Colori dei segmenti (classi CSS ``fmd-k-<chiave>`` in formazione_design.css).
# Stati: ok · s90 · s30 · ko · mai. Categorie (contratti, fasi): nv · cy · vi.
PALETTE_CATEGORIE = ("nv", "cy", "vi", "s90", "s30")


def segmenti(coppie) -> tuple[list[dict], int]:
    """``[(chiave, n), ...]`` → segmenti della barra (solo i non vuoti) e totale."""
    coppie = [(k, int(n or 0)) for k, n in coppie]
    totale = sum(n for _, n in coppie)
    if not totale:
        return [], 0
    return [
        {"chiave": k, "n": n, "perc": round(n * 100 / totale, 2)}
        for k, n in coppie if n
    ], totale


def perc(parte: int, totale: int) -> int:
    return round(parte * 100 / totale) if totale else 0


def pillola(classe: str, testo: str) -> dict:
    return {"classe": classe, "testo": testo}


def tag_slug(valore: str) -> str:
    """Etichetta di filtro senza spazi (gli attributi ``data-tags`` sono separati da spazi)."""
    import re

    return re.sub(r"[^0-9a-z]+", "-", str(valore or "").casefold()).strip("-")


def azione(label: str, url: str, *, post: bool = False, primaria: bool = False) -> dict:
    return {"label": label, "url": url, "post": post, "primaria": primaria}


@dataclass(frozen=True)
class Area:
    rotta: str
    titolo: str
    descrizione: str
    query: str = ""
    icona: str = "i-arrow-right"


def aree_visibili(request, voci) -> list[dict]:
    """Le aree della colonna «Aree» che l'utente può aprire (stessa politica dell'ACL).

    La visibilità non è un confine di sicurezza: il controllo vero resta sulle
    pagine. Serve solo a non mostrare collegamenti che finirebbero in un 403.
    """
    from ..views_admin_hub import _consentita

    out = []
    for v in voci:
        try:
            url = reverse(v.rotta)
        except NoReverseMatch:
            continue
        try:
            if not _consentita(request, url):
                continue
        except Exception:
            continue
        out.append({"url": f"{url}?{v.query}" if v.query else url, "titolo": v.titolo,
                    "descrizione": v.descrizione, "icona": v.icona})
    return out


def griglia(*, id: str, titolo: str, icona: str, aside: str, schede: list[dict], legenda=(),
            filtri=(), ordini=(), etichetta_filtri: str = "Filtra", vuoto_titolo: str = "",
            vuoto_testo: str = "") -> dict:
    """Dati del componente ``_fmd_cc_grid.html``.

    ``filtri``: ``[(valore, etichetta)]`` confrontati con ``scheda["tags"]``.
    ``ordini``: ``[(chiave, etichetta)]``; ``"az"`` ordina per titolo, le altre
    per ``scheda["ordini"][chiave]`` crescente. Il primo è quello di partenza.
    """
    return {
        "id": id, "titolo": titolo, "icona": icona, "aside": aside, "schede": schede,
        "legenda": list(legenda), "filtri": [(tag_slug(v), e) for v, e in filtri], "ordini": list(ordini),
        "etichetta_filtri": etichetta_filtri, "vuoto_titolo": vuoto_titolo, "vuoto_testo": vuoto_testo,
    }


def scheda(*, titolo: str, href: str = "", codice: str = "", meta: str = "", tags=(), seg=(),
           principale: str = "", principale_label: str = "", principale_sub: str = "",
           pillole=(), piede: str = "", piede_muted: bool = False, vai: str = "", ordini=None,
           attiva: bool = False, azioni=()) -> dict:
    """Dati di una scheda. Con ``azioni`` la scheda non è un collegamento unico ma
    porta i suoi pulsanti nel piede (un form non può stare dentro un ``<a>``)."""
    segs, totale = segmenti(seg)
    azioni = list(azioni)
    return {
        "titolo": titolo, "href": "" if azioni else href, "codice": codice, "meta": meta,
        "tags": " ".join(tag_slug(t) for t in tags if t), "segmenti": segs, "totale": totale, "azioni": azioni,
        "aria": ", ".join(f"{s['n']} {s['chiave']}" for s in segs),
        "principale": principale, "principale_label": principale_label, "principale_sub": principale_sub,
        "pillole": [p for p in pillole if p], "piede": piede, "piede_muted": piede_muted, "vai": vai,
        "ordini": ordini or {}, "alfa": (titolo or "").casefold(), "attiva": attiva,
    }


def _ordina_per_indice(schede: list[dict], chiave: str) -> None:
    """Scrive in ``ordini[chiave]`` la posizione della scheda nell'elenco già ordinato."""
    for i, s in enumerate(schede):
        s["ordini"][chiave] = i


# ── Qualifiche ───────────────────────────────────────────────────────────────

def schede_qualifiche(quals, *, oggi, soglia_30, soglia_60, prossime_per_tipo: dict) -> list[dict]:
    """Una scheda per tipo di qualifica assegnato: valide, ≤60gg, ≤30gg, scadute.

    Stessa classificazione dei numeri del cruscotto (``qualifiche_dashboard``):
    senza scadenza = valida. «Da verificare» è un'etichetta a parte (evidenza
    caricata e non convalidata), non un segmento: si somma agli altri stati.
    """
    per_tipo: dict[int, dict] = {}
    for q in quals:
        t = per_tipo.setdefault(q.tipo_id, {"tipo": q.tipo, "ok": 0, "s90": 0, "s30": 0, "ko": 0, "verifica": 0})
        d = q.data_scadenza
        if d is None or d > soglia_60:
            t["ok"] += 1
        elif d < oggi:
            t["ko"] += 1
        elif d <= soglia_30:
            t["s30"] += 1
        else:
            t["s90"] += 1
        if q.documento and not q.verificata:
            t["verifica"] += 1

    righe = sorted(per_tipo.values(), key=lambda r: (-(r["ko"] * 2 + r["s30"] + r["s90"]), r["tipo"].nome.casefold()))
    out = []
    for r in righe:
        tipo = r["tipo"]
        tot = r["ok"] + r["s90"] + r["s30"] + r["ko"]
        sessione = prossime_per_tipo.get(tipo.pk)
        out.append(scheda(
            titolo=tipo.nome,
            href=reverse("anagrafica:qualifiche_scadenzario") + f"?tipo={tipo.pk}&stato=tutte",
            codice=tipo.get_categoria_display(),
            meta=f"{tipo.get_categoria_display()} · " + (f"validità {tipo.durata_mesi} mesi" if tipo.durata_mesi else "senza scadenza automatica"),
            tags=(tipo.categoria,),
            seg=[("ok", r["ok"]), ("s90", r["s90"]), ("s30", r["s30"]), ("ko", r["ko"])],
            principale=str(tot), principale_label="abilitat" + ("o" if tot == 1 else "i"),
            pillole=[
                pillola("fmd-c-ko", f"{r['ko']} scadut{'a' if r['ko'] == 1 else 'e'}") if r["ko"] else None,
                pillola("fmd-c-s30", f"{r['s30']} ≤30gg") if r["s30"] else None,
                pillola("fmd-c-s90", f"{r['s90']} ≤60gg") if r["s90"] else None,
                pillola("fmd-c-mai", f"{r['verifica']} da verificare") if r["verifica"] else None,
            ],
            piede=(f"Rinnovo: sessione del {sessione.data_conseguimento:%d-%m-%Y}" if sessione
                   else "Nessuna sessione di rinnovo"),
            piede_muted=sessione is None,
            vai="Scadenzario →",
        ))
    _ordina_per_indice(out, "gap")
    return out


# ── Visite mediche ───────────────────────────────────────────────────────────

def schede_visite(tipologie_stats: list[dict]) -> list[dict]:
    """Una scheda per tipo di visita attivo: in regola, ≤60g, scadute, senza visita.

    Solo conteggi per tipo (le stesse righe di «Copertura per tipologia»): nessun
    esito, giudizio o nome. «Senza visita» c'è solo se il tipo ha ruoli operativi
    collegati (chi lo deve fare e non ha nessuna visita registrata).
    """
    out = []
    for row in tipologie_stats:
        t = row["tipo"]
        ok, s60, ko = row.get("n_valide", 0), row.get("n_in_scadenza", 0), row.get("n_scadute", 0)
        mai = row.get("senza_visita", 0)
        tot = ok + s60 + ko + mai
        if not tot:
            continue
        out.append(scheda(
            titolo=t.nome,
            href=f"#tipo-row-{t.pk}",
            codice=f"{tot} pers.",
            meta=(f"ogni {t.durata_mesi} mesi" if t.durata_mesi else "senza periodicità")
                 + ("" if getattr(t, "obbligatoria", True) else " · facoltativa"),
            tags=("obbligatoria" if getattr(t, "obbligatoria", True) else "facoltativa",),
            seg=[("ok", ok), ("s90", s60), ("ko", ko), ("mai", mai)],
            principale=f"{perc(ok, tot)}%", principale_label="in regola", principale_sub=f"su {tot}",
            pillole=[
                pillola("fmd-c-ko", f"{ko} scadut{'a' if ko == 1 else 'e'}") if ko else None,
                pillola("fmd-c-mai", f"{mai} senza visita") if mai else None,
                pillola("fmd-c-s90", f"{s60} ≤60g") if s60 else None,
            ],
            piede=(f"Da convocare: {ko + s60 + mai}" if ko + s60 + mai else "Nessuno da convocare"),
            piede_muted=not (ko + s60 + mai),
            vai="Dettaglio ↓",
            ordini={"gap": (perc(ok, tot), -(ko + mai))},
        ))
    out.sort(key=lambda s: s["ordini"]["gap"])
    _ordina_per_indice(out, "gap")
    return out


# ── Salute e sicurezza ───────────────────────────────────────────────────────

ESITI_CONFORMITA = (("ok", "ok"), ("warn", "s30"), ("ko", "ko"), ("na", "mai"))


def schede_mansioni_rischio(gruppi, stati: dict | None) -> list[dict]:
    """Una scheda per mansione di rischio (gruppo omogeneo del DVR) con le sue persone.

    Con ``stati`` (esito di conformità per persona, solo per chi ha il permesso
    HR) la barra dice quante persone sono in regola con tutti gli obblighi; senza,
    la scheda mostra solo persone e protocollo. Mai l'idoneità.
    """
    out = []
    for g in gruppi:
        mr = g.mansione_rischio  # voce del catalogo Mansione = mansione di rischio
        ids = {p["legacy_id"] for m in g.mansioni for p in m["persone"]} | {p["legacy_id"] for p in g.aggiunte} | {p["legacy_id"] for p in g.da_mansioni}
        n = len(ids)
        conteggi = {"ok": 0, "s30": 0, "ko": 0, "mai": 0}
        if stati is not None:
            mappa = dict(ESITI_CONFORMITA)
            for lid in ids:
                esito = (stati.get(lid) or {}).get("complessivo", "na")
                conteggi[mappa.get(esito, "mai")] += 1
        livello = mr.get_livello_rischio_display() if mr.livello_rischio else ""
        fattori = ", ".join(f.nome for f in g.fattori[:3]) + ("…" if len(g.fattori) > 3 else "")
        dvr = " ".join(x for x in (mr.dvr_revisione, mr.dvr_data.strftime("%d/%m/%Y") if mr.dvr_data else "") if x)
        kw = {}
        if stati is not None and n:
            kw = {
                "seg": [("ok", conteggi["ok"]), ("s30", conteggi["s30"]), ("ko", conteggi["ko"]), ("mai", conteggi["mai"])],
                "principale": f"{perc(conteggi['ok'], n)}%", "principale_label": "in regola", "principale_sub": f"su {n}",
                "pillole": [
                    pillola("fmd-c-ko", f"{conteggi['ko']} non conform{'e' if conteggi['ko'] == 1 else 'i'}") if conteggi["ko"] else None,
                    pillola("fmd-c-s30", f"{conteggi['s30']} in scadenza") if conteggi["s30"] else None,
                    pillola("fmd-c-mai", f"{conteggi['mai']} da completare") if conteggi["mai"] else None,
                ],
            }
        else:
            kw = {"principale": str(n), "principale_label": "person" + ("a" if n == 1 else "e")}
        out.append(scheda(
            titolo=mr.nome,
            href=reverse("anagrafica:mansione_requisiti", args=[mr.pk]),
            codice=f"DVR {dvr}" if dvr else "",
            meta=" · ".join(x for x in (f"rischio {livello.lower()}" if livello else "", fattori) if x) or "livello di rischio non indicato",
            tags=(mr.livello_rischio or "nd",),
            piede=f"{n} person{'a' if n == 1 else 'e'} · {len(g.visite)} visit{'a' if len(g.visite) == 1 else 'e'} nel protocollo",
            vai="Requisiti →",
            ordini={"gap": (perc(conteggi["ok"], n) if stati is not None and n else 101, -conteggi["ko"], -n)},
            **kw,
        ))
    out.sort(key=lambda s: s["ordini"]["gap"])
    _ordina_per_indice(out, "gap")
    return out


# ── Ingressi ─────────────────────────────────────────────────────────────────

FASI_RECRUITING = (
    ("NUOVO", "mai", "CV ricevuto"),
    ("CV_VALUTATO", "cy", "CV valutato"),
    ("COLLOQUIO_1", "nv", "1° colloquio"),
    ("COLLOQUIO_2", "vi", "2° colloquio"),
    ("OFFERTA", "s30", "offerta"),
    ("ASSUNTO", "ok", "assunto"),
)


def schede_posizioni(righe: list[dict], per_stato: dict[int, dict[str, int]], *, oggi) -> list[dict]:
    """Una scheda per posizione aperta o sospesa con i candidati per fase dell'iter.

    ``righe`` arriva da ``services.recruiting.righe_posizioni`` (stessa fonte dei
    numeri «Posizioni attive» e «in ritardo»); ``per_stato`` ha i conteggi per
    stato del candidato. Gli esiti chiusi (non idoneo, rinuncia, in database)
    non entrano nella barra: sono candidati usciti dall'iter.
    """
    out = []
    for r in righe:
        p = r["posizione"]
        stati = per_stato.get(p.pk, {})
        seg = [(colore, stati.get(stato, 0)) for stato, colore, _ in FASI_RECRUITING]
        in_iter = sum(n for _, n in seg)
        sospesa = p.stato == "SOSPESA"
        tags = ["ritardo" if r["in_ritardo"] else "", "sospesa" if sospesa else ""]
        entro = f" · serve entro {p.entro_il:%d-%m-%Y}" if p.entro_il else ""
        giorni = r.get("giorni_aperta")
        out.append(scheda(
            titolo=p.titolo,
            href=reverse("anagrafica:recruiting_posizione_detail", args=[p.pk]),
            codice=f"{r['assunti']}/{p.posti} coperti",
            meta=" · ".join(x for x in (p.reparto, f"aperta da {giorni} giorni" if giorni is not None else "") if x) + entro,
            tags=tags,
            seg=seg,
            principale=str(in_iter), principale_label="candidat" + ("o" if in_iter == 1 else "i"),
            principale_sub="nell'iter",
            pillole=[
                pillola("fmd-c-ko", "in ritardo") if r["in_ritardo"] else None,
                pillola("fmd-c-mai", "sospesa") if sospesa else None,
                pillola("fmd-c-s30", f"{r['offerte']} offert{'a' if r['offerte'] == 1 else 'e'}") if r["offerte"] else None,
            ],
            piede=f"{r['in_corso']} in selezione" if r["in_corso"] else "Nessun candidato in selezione",
            piede_muted=not r["in_corso"],
            vai="Posizione →",
            ordini={"ritardo": (0 if r["in_ritardo"] else 1, p.entro_il or oggi.replace(year=oggi.year + 50))},
        ))
    out.sort(key=lambda s: s["ordini"]["ritardo"])
    _ordina_per_indice(out, "ritardo")
    return out


# ── Persone ──────────────────────────────────────────────────────────────────

def schede_reparti(rows: list[dict], tipologia_per_id: dict[int, str], nomi_tipologia: dict[str, str],
                   *, reparto_attivo: str = "") -> tuple[list[dict], list[tuple[str, str]]]:
    """Una scheda per reparto con l'organico diviso per tipo di contratto.

    ``rows`` sono le righe dell'elenco (stesso perimetro visibile all'utente),
    ``tipologia_per_id`` il codice di contratto dall'anagrafica aziendale. I tipi
    di contratto sono configurabili: i quattro più frequenti prendono un colore,
    gli altri finiscono in «altro», chi non ce l'ha in «non indicato».
    """
    from collections import Counter

    freq = Counter(tipologia_per_id.get(int(r.get("id") or 0), "") for r in rows)
    principali = [c for c, _ in freq.most_common() if c][:4]
    colori = dict(zip(principali, PALETTE_CATEGORIE))
    legenda = [(colori[c], nomi_tipologia.get(c, c)) for c in principali]
    altri = any(c and c not in colori for c in freq)
    if altri:
        legenda.append(("s30", "altro"))
    if freq.get(""):
        legenda.append(("mai", "non indicato"))

    per_reparto: dict[str, list[dict]] = {}
    for r in rows:
        per_reparto.setdefault(str(r.get("reparto") or "").strip(), []).append(r)

    out = []
    base = reverse("anagrafica:dipendenti_list")
    from urllib.parse import urlencode
    for nome, persone in per_reparto.items():
        conta = Counter()
        for p in persone:
            c = tipologia_per_id.get(int(p.get("id") or 0), "")
            conta[colori.get(c, "s30" if c else "mai")] += 1
        n = len(persone)
        etichetta = nome or "Senza reparto"
        seg = [(colori[c], conta[colori[c]]) for c in principali] + [("s30", conta["s30"]), ("mai", conta["mai"])]
        out.append(scheda(
            titolo=etichetta,
            href=base + "?" + urlencode({"reparto": nome, "vf": "0"}) if nome else "",
            codice=f"{n} pers.",
            seg=seg,
            principale=str(n), principale_label="person" + ("a" if n == 1 else "e"),
            pillole=[pillola("fmd-c-mai", f"{conta['mai']} senza contratto") if conta["mai"] else None],
            piede="Elenco filtrato per reparto" if nome else "Da assegnare a un reparto",
            piede_muted=not nome,
            vai="Filtra →" if nome else "",
            ordini={"n": (-n, etichetta.casefold())},
            attiva=bool(reparto_attivo) and nome.casefold() == reparto_attivo.casefold(),
        ))
    out.sort(key=lambda s: s["ordini"]["n"])
    _ordina_per_indice(out, "n")
    return out, legenda


# ── Amministrazione ──────────────────────────────────────────────────────────

def schede_import(*, ultima_retribuzioni, ultimo_cedolini, contratti: dict, ratei_mese=None) -> list[dict]:
    """Una scheda per flusso amministrativo: ultimo caricamento, righe abbinate e scartate."""
    out = []
    if ultima_retribuzioni is not None:
        imp = ultima_retribuzioni
        out.append(scheda(
            titolo="Retribuzioni",
            href=reverse("anagrafica:retribuzioni_globale") + "#importazione",
            codice=f"{imp.data_competenza:%m/%Y}",
            meta=f"Ultimo import: {imp.data_importazione:%d-%m-%Y}" + (f" · {imp.file_nome}" if imp.file_nome else ""),
            seg=[("ok", imp.righe_ok), ("ko", imp.righe_errore)],
            principale=str(imp.righe_ok), principale_label="righe abbinate",
            pillole=[pillola("fmd-c-ko", f"{imp.righe_errore} scartat{'a' if imp.righe_errore == 1 else 'e'}") if imp.righe_errore
                     else pillola("fmd-c-ok", "pulito")],
            piede="Importa il mese successivo", vai="Import →",
        ))
    if ultimo_cedolini is not None:
        imp = ultimo_cedolini
        scarti = imp.righe_errore + imp.righe_non_trovate
        out.append(scheda(
            titolo="Ferie e permessi",
            href=reverse("anagrafica:ratei_list") + "#importazione",
            codice=f"{imp.data_competenza:%m/%Y}",
            meta=f"Ultimo import: {imp.data_importazione:%d-%m-%Y}" + (f" · {imp.file_nome}" if imp.file_nome else ""),
            seg=[("ok", imp.righe_ok), ("mai", imp.righe_non_trovate), ("ko", imp.righe_errore)],
            principale=str(imp.righe_ok), principale_label="righe abbinate",
            pillole=[
                pillola("fmd-c-mai", f"{imp.righe_non_trovate} non abbinat{'a' if imp.righe_non_trovate == 1 else 'e'}") if imp.righe_non_trovate else None,
                pillola("fmd-c-ko", f"{imp.righe_errore} in errore") if imp.righe_errore else None,
                None if scarti else pillola("fmd-c-ok", "pulito"),
            ],
            piede="Saldi ferie, ROL ed ex festività dal file cedolini", vai="Import →",
        ))
    if contratti.get("totale"):
        out.append(scheda(
            titolo="Contratti",
            href=reverse("anagrafica:contratti_import"),
            codice=f"{contratti['totale']} in corso",
            meta=(f"Ultimo caricamento: {contratti['ultimo']:%d-%m-%Y}" if contratti.get("ultimo") else "Storico contrattuale"),
            seg=[("ok", contratti["indeterminato"]), ("cy", contratti["termine_oltre"]), ("s90", contratti["s60"]), ("s30", contratti["s30"])],
            principale=str(contratti["totale"]), principale_label="contratti in corso",
            pillole=[
                pillola("fmd-c-s30", f"{contratti['s30']} scadono ≤30gg") if contratti["s30"] else None,
                pillola("fmd-c-s90", f"{contratti['s60']} ≤60gg") if contratti["s60"] else None,
            ],
            piede="Import e storico contrattuale", vai="Contratti →",
        ))
    return out


# ── Report ───────────────────────────────────────────────────────────────────

def schede_modelli(modelli, *, can_manage: bool = False) -> list[dict]:
    """Una scheda per modello di report: quante volte è stato generato negli ultimi 30 giorni."""
    out = []
    for m in modelli:
        n30 = getattr(m, "n_30", 0) or 0
        norme = [str(n) for n in (getattr(m, "norme", []) or []) if n]
        azioni = [azione("Genera", reverse("anagrafica:reportistica_genera", args=[m.pk]), primaria=True)]
        if can_manage:
            azioni += [
                azione("Modifica", reverse("anagrafica:reportistica_modello_edit", args=[m.pk])),
                azione("Duplica", reverse("anagrafica:reportistica_modello_duplica", args=[m.pk]), post=True),
            ]
        ultima = getattr(m, "ultima_generazione", None)
        out.append(scheda(
            titolo=m.nome,
            codice="Pronto" if m.codice_sistema else "",
            meta=" · ".join(x for x in ((m.descrizione or "")[:140], m.get_periodo_tipo_display(),
                                        f"per {m.destinatario}" if m.destinatario else "", f"{m.n_blocchi} blocchi") if x),
            tags=norme,
            principale=str(n30), principale_label="generat" + ("o" if n30 == 1 else "i"), principale_sub="negli ultimi 30 giorni",
            pillole=[pillola("fmd-c-norma", n) for n in norme[:4]],
            piede=(f"Ultimo invio: {ultima:%d-%m-%Y}" if ultima else "Mai generato"),
            piede_muted=not ultima,
            azioni=azioni,
            ordini={"uso": (-n30, m.nome.casefold())},
        ))
    out.sort(key=lambda s: s["ordini"]["uso"])
    _ordina_per_indice(out, "uso")
    return out
