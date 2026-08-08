"""Masowy test chatbota per rola (roleplay) — bramka spójności z RBAC.

Odpala realne zapytania do agenta (Gemini) z perspektywy każdej roli i weryfikuje,
że decyzja chatbota jest SPÓJNA z uprawnieniami roli (ground-truth
``_check_user_can``):

* akcja zapisu dozwolona dla roli  → chatbot składa propozycję (``pending_action``),
* akcja zapisu zabroniona          → chatbot NIE proponuje (odmowa),
* odczyt                           → odpowiedź merytoryczna, bez propozycji.

Nie parsujemy niedeterministycznego tekstu modelu — oceniamy po ``pending_action``
i porównaniu z RBAC. To czyni bramkę odporną na wariację sformułowań Gemini.

DRY-RUN domyślnie: każde zapytanie leci w ``transaction.atomic()`` z
``set_rollback(True)`` — baza demo pozostaje nietknięta. To NIE jest test pytest
(płatne API + niedeterminizm) — ręczne narzędzie dev do iterowania „aż bezbłędnie".

Przykłady::

    python manage.py chatbot_roleplay --role all --intent all
    python manage.py chatbot_roleplay --role montazysta --intent write --assert
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()

# Rola (etykieta) → konto demo. Zgodne z seed_demo.
ROLE_USER = {
    "admin": "adm",
    "kierownik": "kier",
    "magazynier": "mag",
    "montazysta": "mont",
}

# Sondy. ``action=None`` → odczyt (bez propozycji). Inaczej write-akcja, której
# dozwolenie wyprowadzamy z RBAC (nie hardkodujemy macierzy — testujemy spójność).
READ_PROBES = [
    {"action": None, "q": "Jaki jest status maszyny {uid}?"},
]
WRITE_PROBES = [
    {"action": "set_machine_to_service", "q": "Wyślij maszynę {uid} do serwisu."},
]


@dataclass
class ProbeResult:
    role: str
    intent: str
    question: str
    allowed: bool
    proposed: bool
    error: bool
    ok: bool
    note: str


class Command(BaseCommand):
    help = "Masowy test chatbota per rola — spójność decyzji z RBAC (dry-run)."

    def add_arguments(self, parser):
        parser.add_argument("--role", default="all", choices=["all", *ROLE_USER])
        parser.add_argument("--intent", default="all", choices=["all", "read", "write"])
        parser.add_argument("--runs", type=int, default=1, help="Powtórzenia na sondę.")
        parser.add_argument(
            "--assert",
            dest="do_assert",
            action="store_true",
            help="Zakończ kodem 1 jeśli którakolwiek sonda FAIL (ręczna bramka).",
        )

    def handle(self, *args, **opts):
        from chatbot import agent as agent_module

        if agent_module.AGENT is None:
            self.stdout.write(self.style.WARNING("AGENT niedostępny (brak GEMINI_API_KEY) — SKIP."))
            return

        uid = self._pick_machine_uid()
        if uid is None:
            self.stdout.write(self.style.ERROR("Brak maszyn w bazie — uruchom seed_demo."))
            return

        roles = ROLE_USER if opts["role"] == "all" else {opts["role"]: ROLE_USER[opts["role"]]}
        probes = self._probes(opts["intent"])
        results: list[ProbeResult] = []
        for role, username in roles.items():
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f"Konto {username} ({role}) nie istnieje — SKIP.")
                )
                continue
            runs = max(1, opts["runs"])
            for probe in probes:
                results.extend(self._run_probe(user, role, probe, uid) for _ in range(runs))

        self._report(results)
        if opts["do_assert"] and any(not r.ok for r in results):
            sys.exit(1)

    def _pick_machine_uid(self) -> str | None:
        from machines.models import Machine

        machine = Machine.objects.order_by("uid").first()
        return machine.uid if machine else None

    def _probes(self, intent: str) -> list[dict]:
        if intent == "read":
            return READ_PROBES
        if intent == "write":
            return WRITE_PROBES
        return [*READ_PROBES, *WRITE_PROBES]

    def _run_probe(self, user, role: str, probe: dict, uid: str) -> ProbeResult:
        from chatbot.models import Conversation
        from chatbot.services import ask_chatbot
        from chatbot.tools import _check_user_can

        action = probe["action"]
        question = probe["q"].format(uid=uid)
        allowed = action is None or _check_user_can(user, action) is None

        # Dry-run: całość w transakcji z wymuszonym rollbackiem — zero śladu w bazie.
        with transaction.atomic():
            msg = ask_chatbot(user=user, question=question)
            conv = Conversation.objects.get(pk=msg.conversation_id)
            proposed = conv.pending_action is not None
            proposed_action = (conv.pending_action or {}).get("action")
            error = msg.role == "error"
            transaction.set_rollback(True)

        ok, note = self._evaluate(action, allowed, proposed, proposed_action, error)
        return ProbeResult(
            role,
            "read" if action is None else "write",
            question,
            allowed,
            proposed,
            error,
            ok,
            note,
        )

    def _evaluate(self, action, allowed, proposed, proposed_action, error):
        """Zwraca (ok, nota). Oceniamy spójność z RBAC, nie treść modelu."""
        if error:
            return False, "błąd agenta (transient/konfiguracja)"
        if action is None:  # odczyt
            if proposed:
                return False, "odczyt nie powinien tworzyć propozycji zapisu"
            return True, "odczyt OK (brak propozycji)"
        # write
        if allowed:
            if proposed and proposed_action == action:
                return True, f"propozycja {action} ✓"
            if proposed:
                return False, f"zaproponowano {proposed_action}, oczekiwano {action}"
            return False, "uprawniony, ale brak propozycji (możliwe zawieszenie/złe zrozumienie)"
        # not allowed
        if proposed:
            return False, "KRYTYCZNE: zaproponowano akcję mimo braku uprawnień"
        return True, "odmowa zgodna z RBAC ✓"

    def _report(self, results: list[ProbeResult]) -> None:
        passed = sum(1 for r in results if r.ok)
        total = len(results)
        self.stdout.write("")
        self.stdout.write(f"{'ROLA':<12} {'INTENCJA':<8} {'RBAC':<9} {'WYNIK':<6} NOTA")
        self.stdout.write("-" * 78)
        for r in results:
            status = self.style.SUCCESS("PASS") if r.ok else self.style.ERROR("FAIL")
            rbac = "dozwol." if r.allowed else "zabron."
            self.stdout.write(f"{r.role:<12} {r.intent:<8} {rbac:<9} {status:<6} {r.note}")
        self.stdout.write("-" * 78)
        style = self.style.SUCCESS if passed == total else self.style.ERROR
        self.stdout.write(style(f"WYNIK: {passed}/{total} PASS"))
