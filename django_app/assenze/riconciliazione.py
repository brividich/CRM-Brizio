"""RA1 — Riconciliazione presenze certificate ↔ assenze approvate.

Incrocia i record ``CertificazionePresenza`` (presenza certificata in un giorno)
con le richieste della tabella legacy ``assenze`` **approvate**, per evidenziare
le incongruenze: una persona marcata presente in un giorno coperto da un'assenza
a **giornata intera** approvata (ferie/malattia) → non può essere insieme presente
e in ferie/malattia.

Sola lettura. Principi:

- Il match dipendente è per **nome normalizzato** (``nome_dipendente`` ↔
  ``copia_nome``), la stessa chiave già usata altrove nel modulo (rischio omonimi,
  da validare su dati reali).
- Se la presenza è **esplicitamente collegata** (``assenza_id``) alla stessa
  assenza che la copre, NON è un conflitto: è l'accoppiamento atteso, non una
  doppia prenotazione.
- I **permessi** (orari, stesso giorno) e la **flessibilità** NON generano
  conflitto: sono compatibili con una presenza parziale. Contano solo i tipi a
  giornata intera.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

# Tipi assenza a giornata intera: una presenza nello stesso giorno è incongruente.
_FULL_DAY_TIPI = {"ferie", "malattia"}

_TIPO_LABEL = {"ferie": "Ferie", "malattia": "Malattia"}


def _norm_nome(value) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _norm_tipo_key(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (ValueError, TypeError):
        return None


@dataclass
class Conflitto:
    presenza_id: int | None
    nome: str
    data: date
    ore_presenza: float | None
    assenza_id: int | None
    tipo_assenza: str
    tipo_label: str


def trova_conflitti(presenze, assenze_approvate) -> list[Conflitto]:
    """Logica pura di matching (testabile senza DB legacy).

    - ``presenze``: iterable con attributi ``id``, ``nome_dipendente``, ``data``,
      ``ore_totali``, ``assenza_id`` (es. istanze ``CertificazionePresenza``).
    - ``assenze_approvate``: lista di dict con ``id``, ``copia_nome``,
      ``data_inizio``, ``data_fine``, ``tipo_assenza``.
    """
    full_day = []
    for a in assenze_approvate:
        if _norm_tipo_key(a.get("tipo_assenza")) not in _FULL_DAY_TIPI:
            continue
        di = _as_date(a.get("data_inizio"))
        df = _as_date(a.get("data_fine"))
        if di is None or df is None:
            continue
        if df < di:
            di, df = df, di
        full_day.append((a, _norm_nome(a.get("copia_nome")), di, df))

    conflitti: list[Conflitto] = []
    for p in presenze:
        p_data = _as_date(getattr(p, "data", None))
        if p_data is None:
            continue
        nome = _norm_nome(getattr(p, "nome_dipendente", ""))
        if not nome:
            continue
        for a, a_nome, di, df in full_day:
            if a_nome != nome or not (di <= p_data <= df):
                continue
            assenza_id = a.get("id")
            p_assenza_id = getattr(p, "assenza_id", None)
            if p_assenza_id and p_assenza_id == assenza_id:
                continue  # link esplicito: accoppiamento atteso, non conflitto
            tipo_key = _norm_tipo_key(a.get("tipo_assenza"))
            conflitti.append(
                Conflitto(
                    presenza_id=getattr(p, "id", None),
                    nome=getattr(p, "nome_dipendente", "") or nome,
                    data=p_data,
                    ore_presenza=getattr(p, "ore_totali", None),
                    assenza_id=assenza_id,
                    tipo_assenza=tipo_key,
                    tipo_label=_TIPO_LABEL.get(tipo_key, tipo_key.capitalize()),
                )
            )
            break

    conflitti.sort(key=lambda c: (c.data, c.nome))
    return conflitti


def assenze_approvate(da: date, a: date) -> list[dict]:
    """Legge dalla tabella legacy ``assenze`` le richieste approvate nel periodo.

    Difensivo: se la tabella legacy non esiste (es. DB di test pulito) ritorna [].
    Riusa gli helper di ``assenze.views`` (single source of truth su query/stato).
    """
    from core.legacy_utils import legacy_table_columns
    from . import views as v

    if not v._table_exists("assenze"):
        return []
    cols = set(legacy_table_columns("assenze"))
    if not {"id", "data_inizio", "data_fine"} <= cols:
        return []
    wanted = [
        c
        for c in (
            "id", "copia_nome", "email_esterna", "tipo_assenza",
            "data_inizio", "data_fine", "consenso", "moderation_status",
        )
        if c in cols
    ]
    sql = v._select_limited(
        f"SELECT {v._quoted_columns(wanted)} FROM assenze "
        "WHERE data_fine >= %s AND data_inizio <= %s",
        "ORDER BY data_inizio",
        5000,
    )
    rows = v._fetch_all_dict(sql, [da, a])
    out = []
    for r in rows:
        _parsed, label = v._effective_status(r.get("consenso"), r.get("moderation_status"))
        if label == "Approvato":
            out.append(r)
    return out


def conflitti(da: date, a: date) -> list[Conflitto]:
    """Conflitti presenza↔assenza nel periodo [da, a] (estremi inclusi)."""
    from .models import CertificazionePresenza

    presenze = (
        CertificazionePresenza.objects
        .filter(data__gte=da, data__lte=a)
        .order_by("data", "nome_dipendente")
    )
    return trova_conflitti(presenze, assenze_approvate(da, a))


def parse_periodo(da_str, a_str, *, default_da: date, default_a: date) -> tuple[date, date]:
    """Normalizza i parametri periodo dalla querystring con fallback sicuri."""
    da = _as_date(da_str) or default_da
    a = _as_date(a_str) or default_a
    if a < da:
        da, a = a, da
    return da, a
