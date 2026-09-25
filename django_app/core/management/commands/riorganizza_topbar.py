"""
Management command: riorganizza_topbar

Porta la topbar alla struttura concordata il 2026-09-25
(docs/UI/TOPNAV_UX_2026-09.md, «Round 2»):

    Per me ▾ · Tickets · Produzione ▾ · Persone ▾ · Sicurezza e ambiente ▾ · Qualità ▾ · IT ▾ · Suggestion Corner

- Categorie: rinomina quelle esistenti (HR → Persone, Manutenzione → Produzione, ...) e crea
  «Per me». Non cancella nulla: una categoria rimasta vuota semplicemente non compare.
- Voci: cercate per `code`, con fallback sulla `route_name` fra le voci topbar; aggiornati solo
  categoria, sottocategoria (`group`), ordine e — dove serve — etichetta. Visibilita' e permessi
  NON vengono toccati: una voce nascosta dal Navigation Builder resta nascosta.
- Voci nuove (4): create solo se la route esiste; la visibilita' la decide l'ACL della route.

Idempotente: una seconda esecuzione non cambia nulla.

Uso:
    python manage.py riorganizza_topbar            # dry-run: mostra cosa cambierebbe
    python manage.py riorganizza_topbar --apply    # applica
"""
from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import NoReverseMatch, reverse

from core.models import ModuleCategory, NavigationItem, SiteConfig
from core.module_registry import MODULE_DEFINITIONS, module_branding_siteconfig_keys
from core.navigation_registry import bump_navigation_registry_version, resolve_navigation_item_permission_code


@dataclass(frozen=True)
class Cat:
    key: str
    label: str
    order: int
    icon: str
    old_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Voce:
    code: str
    route: str
    category: str | None  # Cat.key, None = voce diretta nella barra
    group: str
    order: int
    label: str | None = None  # None = lascia l'etichetta attuale
    icon: str = ""
    create: bool = False
    # Permesso esplicito quando quello ricavato dalla route e' troppo largo
    # (es. la route admin assenze eredita assenze.route.view = tutti).
    permission: str = ""


CATEGORIE: tuple[Cat, ...] = (
    Cat("per-me", "Per me", 10, "user"),
    Cat("produzione", "Produzione", 30, "layers", ("Manutenzione",)),
    Cat("persone", "Persone", 40, "users", ("HR",)),
    Cat("sicurezza-ambiente", "Sicurezza e ambiente", 50, "shield-check", ("Sicurezza",)),
    Cat("qualita", "Qualità", 60, "check-circle", ("Qualità / SGI", "Qualita / SGI")),
    Cat("it", "IT", 70, "server", ("SOC IT - CN",)),
)

VOCI: tuple[Voce, ...] = (
    # Per me — pagine personali (lo scope sulla persona e' della view, verificato).
    Voce("procedure_refresh", "procedure_refresh:my_assignments", "per-me", "Da fare", 11, label="Presa visione"),
    Voce("per-me-kickoff-da-gestire", "tasks:da_gestire", "per-me", "Da fare", 12,
         label="KICK-OFF da gestire", icon="list-todo", create=True),
    Voce("assenze", "assenze_gestione", "per-me", "Richieste", 13, label="Le mie assenze"),
    Voce("per-me-richiedi-assenza", "assenze_richiesta", "per-me", "Richieste", 14,
         label="Richiedi assenza", icon="calendar", create=True),
    Voce("per-me-richiedi-dpi", "dpi:nuova", "per-me", "Richieste", 15,
         label="Richiedi DPI", icon="shield", create=True),
    Voce("notizie", "notizie_lista", "per-me", "Azienda", 16),
    # Tickets: modulo unico (IT + MAN), voce diretta.
    Voce("tickets", "tickets:dashboard", None, "", 20),
    # Produzione
    Voce("vrf-kick-off", "tasks:list", "produzione", "Commesse e reparti", 31),
    Voce("carichi-macchina", "gestione_carichi_macchina:excel", "produzione", "Commesse e reparti", 32),
    Voce("checklist_operativa", "checklist_operativa:gestione", "produzione", "Commesse e reparti", 33),
    Voce("assets", "assets:asset_dashboard", "produzione", "Manutenzione", 34, label="Asset e manutenzione"),
    Voce("gestione-attrezzatura", "attrezzature:list", "produzione", "Manutenzione", 35),
    # Persone (Timbri = registro HR, non le timbrature personali)
    Voce("anagrafica", "anagrafica:index", "persone", "", 41),
    Voce("persone-assenze-hr", "assenze_impostazioni", "persone", "", 42,
         label="Assenze (gestione HR)", icon="clipboard-list", create=True,
         permission="legacy.assenze.admin_assenze"),
    Voce("timbri", "timbri:index", "persone", "", 43),
    Voce("persone-campagne-presa-visione", "procedure_refresh:admin_dashboard", "persone", "", 44,
         label="Campagne presa visione", icon="file-check", create=True),
    # Sicurezza e ambiente
    Voce("diario_preposto", "diario_preposto:lista", "sicurezza-ambiente", "Sul campo", 51),
    Voce("segnalazionisicurezza", "rilevazione_incidenti:lista", "sicurezza-ambiente", "Sul campo", 52),
    Voce("dpi", "dpi:dashboard", "sicurezza-ambiente", "Sul campo", 53),
    Voce("schede-sicurezza", "schede_sicurezza:prodotto_list", "sicurezza-ambiente", "Prodotti e rifiuti", 54),
    Voce("rentri", "rentri_menu", "sicurezza-ambiente", "Prodotti e rifiuti", 55),
    # Qualità (le anomalie sono non conformita' legate agli ordini)
    Voce("gestione_anomalie", "anomalie_menu", "qualita", "", 61),
    Voce("gestione-specifiche", "gestione_specifiche:lista", "qualita", "", 62),
    Voce("ofi_registro", "registro_ofi:lista", "qualita", "", 63),
    Voce("report-conformita", "report_conformita:index", "qualita", "", 64),
    # IT
    Voce("security_center", "security:dashboard", "it", "", 71),
    Voce("contatori", "contatori:dashboard", "it", "", 72),
    Voce("accessi", "", "it", "", 73),
    # Suggestion Corner: voce diretta, fuori da «Per me».
    Voce("suggestion-corner", "suggestion_corner:home", None, "", 80),
)


class Command(BaseCommand):
    help = "Riorganizza la topbar in Per me / Tickets / Produzione / Persone / Sicurezza e ambiente / Qualità / IT."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Applica le modifiche (default: dry-run).")

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        self.changes = 0
        self.stdout.write(self.style.MIGRATE_HEADING(
            "riorganizza_topbar — " + ("APPLICAZIONE" if apply else "DRY-RUN (nessuna scrittura)")
        ))
        with transaction.atomic():
            cats = self._categorie(apply)
            touched = self._voci(cats, apply)
            self._non_toccate(touched)
            if not apply:
                transaction.set_rollback(True)
        if apply and self.changes:
            bump_navigation_registry_version()
        verb = "applicate" if apply else "da applicare"
        self.stdout.write(self.style.SUCCESS(f"Modifiche {verb}: {self.changes}"))

    # ── categorie ────────────────────────────────────────────────────────────
    def _categorie(self, apply: bool) -> dict[str, ModuleCategory | None]:
        self.stdout.write(self.style.MIGRATE_LABEL("Categorie"))
        out: dict[str, ModuleCategory | None] = {}
        for spec in CATEGORIE:
            # Chiave nostra, poi etichetta gia' rinominata (run precedente), poi etichette storiche.
            cat = ModuleCategory.objects.filter(key=spec.key).first()
            if cat is None:
                for old in (spec.label, *spec.old_labels):
                    cat = ModuleCategory.objects.filter(label__iexact=old).order_by("order", "id").first()
                    if cat:
                        break
            if cat is None:
                self._log(f"  + crea «{spec.label}» (key={spec.key}, ordine {spec.order})")
                cat = ModuleCategory(key=spec.key, label=spec.label, order=spec.order, icon=spec.icon, topbar_color="")
                cat.save()
                out[spec.key] = cat
                continue
            diffs = []
            if cat.label != spec.label:
                diffs.append(f"etichetta «{cat.label}» → «{spec.label}»")
                cat.label = spec.label
            if cat.order != spec.order:
                diffs.append(f"ordine {cat.order} → {spec.order}")
                cat.order = spec.order
            if diffs:
                self._log(f"  ~ {cat.key}: " + ", ".join(diffs))
                cat.save(update_fields=["label", "order"])
            out[spec.key] = cat
        return out

    # ── voci ─────────────────────────────────────────────────────────────────
    def _voci(self, cats: dict[str, ModuleCategory | None], apply: bool) -> set[int]:
        self.stdout.write(self.style.MIGRATE_LABEL("Voci"))
        touched: set[int] = set()
        for spec in VOCI:
            item = NavigationItem.objects.filter(section="topbar", code=spec.code).first()
            if item is None and spec.route:
                item = (
                    NavigationItem.objects.filter(section="topbar", route_name=spec.route)
                    .exclude(pk__in=touched).order_by("order", "id").first()
                )
            if item is None:
                if not spec.create:
                    self.stdout.write(self.style.WARNING(f"  ? {spec.code}: voce non trovata, salto"))
                    continue
                try:
                    reverse(spec.route)
                except NoReverseMatch:
                    self.stdout.write(self.style.WARNING(f"  ? {spec.code}: route {spec.route} inesistente, salto"))
                    continue
                item = NavigationItem(
                    code=spec.code, section="topbar", route_name=spec.route, label=spec.label or spec.code,
                    icon=spec.icon, is_visible=True, is_enabled=True,
                )
                self._log(f"  + crea «{item.label}» ({spec.route})")
            diffs = []
            category = cats.get(spec.category) if spec.category else None
            if item.pk is None or item.category_id != (category.pk if category else None):
                if item.pk is not None:
                    old = item.category.label if item.category_id else "—"
                    diffs.append(f"categoria {old} → {category.label if category else '— (voce diretta)'}")
                item.category = category
            if (item.group or "") != spec.group:
                if item.pk is not None:
                    diffs.append(f"sottocategoria «{item.group}» → «{spec.group}»")
                item.group = spec.group
            if item.order != spec.order:
                if item.pk is not None:
                    diffs.append(f"ordine {item.order} → {spec.order}")
                item.order = spec.order
            if spec.label and item.label != spec.label:
                if item.pk is not None:
                    diffs.append(f"etichetta «{item.label}» → «{spec.label}»")
                item.label = spec.label
            if spec.permission and item.required_permission_code != spec.permission:
                if item.pk is not None:
                    diffs.append(f"permesso «{item.required_permission_code}» → «{spec.permission}»")
                item.required_permission_code = spec.permission
            created = item.pk is None
            if created or diffs:
                item.save()
                if diffs:
                    self._log(f"  ~ {item.code}: " + "; ".join(diffs))
            if created:
                perm = resolve_navigation_item_permission_code(item) or "(nessuno: visibile solo ai ruoli abilitati)"
                self.stdout.write(f"      permesso che decide la visibilita': {perm}")
            if not (item.is_visible and item.is_enabled):
                self.stdout.write(f"      nota: {item.code} e' nascosta/disattivata dal Navigation Builder, resta cosi'")
            if spec.label:
                self._branding_menu_label(item.code, spec.label)
            touched.add(item.pk)
        return touched

    def _branding_menu_label(self, code: str, label: str) -> None:
        """Le voci-modulo prendono il nome dal branding (menu_label), non da NavigationItem.label.

        Il branding si imposta solo se non e' gia' personalizzato: un nome scelto
        dall'admin nella pagina Branding resta suo.
        """
        code_l = str(code or "").strip().lower()
        module_key = next((k for k, d in MODULE_DEFINITIONS.items() if code_l in d.navigation_codes), None)
        if not module_key:
            return
        key = module_branding_siteconfig_keys(module_key).get("menu_label")
        current = (SiteConfig.get(key, "") or "").strip()
        if current == label:
            return
        if current:
            self.stdout.write(f"      nota: branding «{module_key}» personalizzato in «{current}», lo lascio")
            return
        self._log(f"  ~ branding {module_key}: nome nel menu → «{label}»")
        SiteConfig.set(key, label, "Nome del modulo nel menu (riorganizza_topbar)")

    def _non_toccate(self, touched: set[int]) -> None:
        rest = NavigationItem.objects.filter(section="topbar", is_visible=True, is_enabled=True).exclude(pk__in=touched)
        if rest.exists():
            self.stdout.write(self.style.MIGRATE_LABEL("Voci topbar visibili NON previste (lasciate com'erano)"))
            for item in rest.select_related("category").order_by("order", "id"):
                cat = item.category.label if item.category_id else "—"
                self.stdout.write(f"  · {item.code} «{item.label}» [{cat}] {item.route_name or item.url_path}")

    def _log(self, msg: str) -> None:
        self.changes += 1
        self.stdout.write(msg)
