"""Verifica annuale dell'operato degli amministratori di sistema (Garante 27/11/2008, punto 4.4).

Il report raccoglie, per l'anno scelto, quello che chi verifica deve guardare:

1. chi erano gli amministratori di sistema e con quale nomina;
2. i loro accessi (per sistema, fuori orario, non riusciti) e le modifiche sensibili fatte;
3. gli account con privilegi di amministratore senza nomina;
4. la tenuta dell'archivio: giorni sigillati, verifiche d'integrità, interruzioni della raccolta.

La conclusione (esito, rilievi, azioni) la scrive chi verifica: :class:`VerificaAnnuale`.
Il PDF porta l'impronta SHA-256 del riepilogo, salvata con la verifica.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from django.db.models import Count, Q
from django.utils import timezone

MODIFICHE_SENSIBILI = ("gruppo_privilegiato", "gruppo_modificato", "account_creato", "account_eliminato",
                       "account_modificato", "audit_modificato", "registro_cancellato", "servizio_installato",
                       "configurazione")


def _limiti(anno: int) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    return datetime(anno, 1, 1, tzinfo=tz), datetime(anno + 1, 1, 1, tzinfo=tz)


def _nome_breve(account: str) -> str:
    return account.split("\\")[-1].split("@")[0].lower()


def riepilogo(anno: int) -> dict:
    from .models import AccountAD, AmministratoreSistema, EventoRegistro, Interruzione, SigilloGiorno

    dal, al = _limiti(anno)
    inizio, fine = date(anno, 1, 1), date(anno, 12, 31)
    oggi = timezone.localdate()
    ultimo = min(fine, oggi)

    ads = [a for a in AmministratoreSistema.objects.all()
           if (a.nominato_il is None or a.nominato_il <= fine) and (a.revocato_il is None or a.revocato_il >= inizio)]
    eventi = EventoRegistro.objects.filter(quando__gte=dal, quando__lt=al)
    per_account = defaultdict(lambda: {"accessi": 0, "fuori_orario": 0, "falliti": 0, "modifiche": 0, "sistemi": Counter()})
    righe = (eventi.filter(Q(categoria__in=("accesso", "accesso_privilegiato", "accesso_fallito")) | Q(categoria__in=MODIFICHE_SENSIBILI))
             .exclude(account="").values("account", "categoria", "fuori_orario", "host").annotate(n=Count("id")))
    for r in righe:
        a = per_account[_nome_breve(r["account"])]
        if r["categoria"] in ("accesso", "accesso_privilegiato"):
            a["accessi"] += r["n"]
            a["fuori_orario"] += r["n"] if r["fuori_orario"] else 0
            a["sistemi"][r["host"] or "?"] += r["n"]
        elif r["categoria"] == "accesso_fallito":
            a["falliti"] += r["n"]
        else:
            a["modifiche"] += r["n"]

    elenco = []
    nominati = set()
    for a in ads:
        account = [_nome_breve(x) for x in a.lista_account()]
        nominati.update(account)
        tot = {"accessi": 0, "fuori_orario": 0, "falliti": 0, "modifiche": 0, "sistemi": Counter()}
        for acc in account:
            p = per_account.get(acc)
            if p:
                for k in ("accessi", "fuori_orario", "falliti", "modifiche"):
                    tot[k] += p[k]
                tot["sistemi"].update(p["sistemi"])
        elenco.append({
            "nome": a.nome, "account": ", ".join(a.lista_account()) or "—", "tipo": a.get_tipo_display(),
            "societa": a.societa, "ambito": a.ambito, "nominato_il": a.nominato_il, "revocato_il": a.revocato_il,
            "nomina": bool(a.documento_nomina), "accessi": tot["accessi"], "fuori_orario": tot["fuori_orario"],
            "falliti": tot["falliti"], "modifiche": tot["modifiche"],
            "sistemi": ", ".join(f"{h} ({n})" for h, n in tot["sistemi"].most_common(5)) or "—",
        })

    senza_nomina = [
        {"sam": x.sam, "nome": x.nome or x.anagrafica_nome, "gruppi": ", ".join(x.gruppi_privilegiati)}
        for x in AccountAD.objects.filter(sparito_il__isnull=True, abilitato=True).exclude(gruppi_privilegiati=[])
        if x.gruppi_privilegiati and x.sam.lower() not in nominati and x.sam.lower() != "krbtgt"
    ]
    modifiche = [
        {"quando": e.quando, "host": e.host or e.fonte_nome, "descrizione": e.descrizione, "account": e.account}
        for e in eventi.filter(categoria__in=("gruppo_privilegiato", "audit_modificato", "registro_cancellato")).order_by("quando")[:300]
    ]

    sigilli = SigilloGiorno.objects.filter(giorno__gte=inizio, giorno__lte=fine)
    # Il conto parte dal primo giorno di raccolta: i giorni prima (anno dell'avvio) li copre il sistema precedente.
    primo_assoluto = SigilloGiorno.objects.order_by("giorno").values_list("giorno", flat=True).first()
    da = max(inizio, primo_assoluto) if primo_assoluto else inizio
    giorni_attesi = (ultimo - da).days + 1 if ultimo >= da else 0
    s_tot = sigilli.count()
    archivio = {
        "giorni_attesi": giorni_attesi, "giorni_sigillati": s_tot,
        "verificati_ok": sigilli.filter(verifica_ok=True).count(),
        "non_integri": list(sigilli.filter(verifica_ok=False).values_list("giorno", flat=True)),
        "senza_righe": sigilli.filter(righe=0).count(),
        "righe": sum(sigilli.values_list("righe", flat=True)),
        "copiati": sigilli.filter(copia_il__isnull=False).count(),
        "primo": sigilli.order_by("giorno").values_list("giorno", flat=True).first(),
    }
    interruzioni = []
    for i in Interruzione.objects.filter(dal__lt=al).filter(Q(al__isnull=True) | Q(al__gte=dal)).order_by("dal"):
        fine_i = i.al or timezone.now()
        durata = max(timedelta(0), min(fine_i, al) - max(i.dal, dal))
        interruzioni.append({"dal": i.dal, "al": i.al, "motivo": i.get_motivo_display(), "fonte": i.fonte_nome or "Raccoglitore",
                             "durata_min": round(durata.total_seconds() / 60), "dettaglio": i.dettaglio,
                             "giustificazione": i.giustificazione})
    non_giustificate = [i for i in interruzioni if not i["giustificazione"] and i["durata_min"] >= 30]

    contesto = {
        "anno": anno, "generato_il": timezone.now(), "amministratori": elenco, "senza_nomina": senza_nomina,
        "modifiche_critiche": modifiche, "archivio": archivio, "interruzioni": interruzioni,
        "non_giustificate": len(non_giustificate),
        "eventi_totali": eventi.count(),
        "indice_da": EventoRegistro.objects.order_by("quando").values_list("quando", flat=True).first(),
    }
    contesto["controlli"] = controlli(contesto)
    contesto["impronta"] = impronta(contesto)
    return contesto


def controlli(c: dict) -> list[dict]:
    """La lista di controllo che chi verifica spunta: ogni voce dice se torna e perché."""
    a = c["archivio"]
    voci = [
        ("Elenco degli amministratori di sistema presente", bool(c["amministratori"]),
         f"{len(c['amministratori'])} amministratori nell'anno." if c["amministratori"] else "Nessun amministratore registrato."),
        ("Ogni amministratore ha la nomina allegata", all(x["nomina"] for x in c["amministratori"]) and bool(c["amministratori"]),
         ", ".join(x["nome"] for x in c["amministratori"] if not x["nomina"]) or "Tutte allegate."),
        ("Nessun account con privilegi senza nomina", not c["senza_nomina"],
         ", ".join(x["sam"] for x in c["senza_nomina"]) or "Tutti gli account privilegiati sono nominati."),
        ("Registro degli accessi completo per l'anno", a["giorni_sigillati"] >= a["giorni_attesi"] - 1 and a["giorni_attesi"] > 0,
         f"{a['giorni_sigillati']} giorni sigillati su {a['giorni_attesi']}."
         + (f" Archivio dal {a['primo']:%d/%m/%Y}: i giorni prima vanno coperti dal sistema precedente (export da conservare)."
            if a["primo"] and (a["primo"].month, a["primo"].day) != (1, 1) else "")),
        ("Archivio integro (catena di impronte verificata)", not a["non_integri"] and a["giorni_sigillati"] > 0,
         f"Giorni non integri: {', '.join(d.strftime('%d/%m') for d in a['non_integri'])}." if a["non_integri"]
         else f"{a['verificati_ok']} giorni verificati integri."),
        ("Seconda copia dell'archivio", a["copiati"] >= a["giorni_sigillati"] and a["giorni_sigillati"] > 0,
         f"{a['copiati']} giorni copiati su {a['giorni_sigillati']}."),
        ("Interruzioni della raccolta giustificate", c["non_giustificate"] == 0,
         f"{c['non_giustificate']} interruzioni di almeno 30 minuti senza giustificazione." if c["non_giustificate"]
         else f"{len(c['interruzioni'])} interruzioni, tutte brevi o giustificate."),
        ("Nessuna cancellazione dei registri né modifica dell'audit", not any(
            "cancellato" in m["descrizione"].lower() or "audit" in m["descrizione"].lower() for m in c["modifiche_critiche"]),
         "Vedi elenco delle modifiche critiche." if c["modifiche_critiche"] else "Nessuna."),
    ]
    return [{"voce": v, "ok": ok, "nota": nota} for v, ok, nota in voci]


def impronta(c: dict) -> str:
    def norm(v):
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        return str(v)

    dati = {k: v for k, v in c.items() if k not in ("generato_il", "impronta")}
    return hashlib.sha256(json.dumps(dati, sort_keys=True, default=norm, ensure_ascii=False).encode("utf-8")).hexdigest()


def pdf(c: dict, verifica=None) -> bytes:
    from security.services.soc_pdf import _Doc, _dt

    d = _Doc("Verifica annuale degli amministratori di sistema", f"Anno {c['anno']}", landscape=True)
    d.para("Provvedimento del Garante per la protezione dei dati personali del 27/11/2008 (punto 4.4) e "
           "ISO/IEC 27001:2022 (controlli 5.18, 8.2, 8.15, 8.16). Dati dal Registro accessi di NOVICROM HUB.")
    d.space()
    if verifica:
        d.section("Esito della verifica")
        d.facts([("Eseguita il", verifica.eseguita_il.strftime("%d/%m/%Y")), ("Da", verifica.eseguita_da),
                 ("Esito", verifica.get_esito_display()), ("Registrata da", verifica.registrata_da or "-"),
                 ("Rilievi", verifica.rilievi or "-"), ("Azioni", verifica.azioni or "-")])
    d.section("Lista di controllo")
    d.table(["Controllo", "Esito", "Nota"], [[x["voce"], "OK" if x["ok"] else "Da vedere", x["nota"]] for x in c["controlli"]],
            widths=[5, 1.2, 7])
    d.section("Amministratori di sistema nell'anno")
    d.table(["Nome", "Account", "Tipo", "Nominato il", "Revocato il", "Nomina", "Accessi", "Fuori orario", "Non riusciti",
             "Modifiche", "Sistemi più usati"],
            [[x["nome"] + (f" ({x['societa']})" if x["societa"] else ""), x["account"], x["tipo"], _dt(x["nominato_il"], "%d/%m/%Y"),
              _dt(x["revocato_il"], "%d/%m/%Y"), "sì" if x["nomina"] else "no", x["accessi"], x["fuori_orario"], x["falliti"],
              x["modifiche"], x["sistemi"]] for x in c["amministratori"]],
            widths=[2.6, 2.2, 1.3, 1.3, 1.3, 0.9, 1, 1, 1, 1, 3.4], empty="Nessun amministratore di sistema registrato.")
    d.section("Account con privilegi di amministratore senza nomina")
    d.table(["Account", "Nome", "Gruppi"], [[x["sam"], x["nome"], x["gruppi"]] for x in c["senza_nomina"]],
            widths=[2, 3, 6], empty="Nessuno.")
    d.section("Modifiche critiche (gruppi di amministratori, audit, registri cancellati)")
    d.table(["Quando", "Sistema", "Cosa", "Account"],
            [[_dt(m["quando"]), m["host"], m["descrizione"], m["account"]] for m in c["modifiche_critiche"]],
            widths=[1.6, 2.4, 6, 2], empty="Nessuna.")
    a = c["archivio"]
    d.section("Archivio e continuità della raccolta")
    d.facts([("Giorni sigillati", f"{a['giorni_sigillati']} su {a['giorni_attesi']}"), ("Verificati integri", a["verificati_ok"]),
             ("Non integri", ", ".join(x.strftime("%d/%m/%Y") for x in a["non_integri"]) or "nessuno"),
             ("Righe archiviate", a["righe"]), ("Copiati nella seconda destinazione", a["copiati"]),
             ("Eventi importanti nell'indice", c["eventi_totali"])])
    d.table(["Dal", "Al", "Motivo", "Fonte", "Minuti", "Giustificazione"],
            [[_dt(i["dal"]), _dt(i["al"]) if i["al"] else "in corso", i["motivo"], i["fonte"], i["durata_min"],
              i["giustificazione"] or "-"] for i in c["interruzioni"]],
            widths=[1.6, 1.6, 2.4, 2.2, 0.9, 4.5], empty="Nessuna interruzione nell'anno.")
    d.para(f"Impronta SHA-256 del riepilogo: {c['impronta']}", "small" if "small" in d.styles else "body")
    return d.build()
