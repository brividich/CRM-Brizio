from __future__ import annotations

import re


_ANGLE_BRACKETS_RE = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^>]+)>$")


def _normalize_contact(nome: object = "", email: object = "") -> dict[str, str] | None:
    normalized_name = str(nome or "").strip()
    normalized_email = str(email or "").strip()
    if not normalized_name and not normalized_email:
        return None
    return {
        "nome": normalized_name,
        "email": normalized_email,
    }


def parse_contact_people(raw_value: object) -> list[dict[str, str]]:
    people: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in str(raw_value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        name = ""
        email = ""
        match = _ANGLE_BRACKETS_RE.match(line)
        if match:
            name = match.group("name").strip()
            email = match.group("email").strip()
        elif "|" in line:
            left, right = line.split("|", 1)
            name = left.strip()
            email = right.strip()
        elif "@" in line and " " not in line:
            email = line
        else:
            name = line

        normalized = _normalize_contact(name, email)
        if normalized is None:
            continue
        key = (normalized["nome"].lower(), normalized["email"].lower())
        if key in seen:
            continue
        seen.add(key)
        people.append(normalized)
    return people


def coalesce_contact_people(
    people: object,
    *,
    fallback_name: object = "",
    fallback_email: object = "",
) -> list[dict[str, str]]:
    normalized_people: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    if isinstance(people, list):
        for raw_person in people:
            if not isinstance(raw_person, dict):
                continue
            normalized = _normalize_contact(
                raw_person.get("nome", ""),
                raw_person.get("email", ""),
            )
            if normalized is None:
                continue
            key = (normalized["nome"].lower(), normalized["email"].lower())
            if key in seen:
                continue
            seen.add(key)
            normalized_people.append(normalized)
    if normalized_people:
        return normalized_people

    fallback = _normalize_contact(fallback_name, fallback_email)
    return [fallback] if fallback is not None else []


def primary_contact(
    people: object,
    *,
    fallback_name: object = "",
    fallback_email: object = "",
) -> dict[str, str]:
    contacts = coalesce_contact_people(
        people,
        fallback_name=fallback_name,
        fallback_email=fallback_email,
    )
    if contacts:
        return contacts[0]
    return {"nome": "", "email": ""}


def serialize_contact_people(
    people: object,
    *,
    fallback_name: object = "",
    fallback_email: object = "",
) -> str:
    contacts = coalesce_contact_people(
        people,
        fallback_name=fallback_name,
        fallback_email=fallback_email,
    )
    rows: list[str] = []
    for person in contacts:
        if person["nome"] and person["email"]:
            rows.append(f"{person['nome']} | {person['email']}")
        else:
            rows.append(person["nome"] or person["email"])
    return "\n".join(rows)
