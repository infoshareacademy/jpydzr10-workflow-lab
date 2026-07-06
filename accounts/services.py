"""Serwisy biznesowe dla zarządzania pracownikami.

Warstwa serwisowa enkapsuluje operacje wykraczające poza pojedynczy save:
rejestrację (User + profil + walidacja hasła), offboarding (terminacja
z kasowaniem sesji) oraz anonimizację (GDPR Art.17, prawo do bycia
zapomnianym). Widoki/admin powinny wołać te funkcje zamiast modyfikować
modele bezpośrednio — daje to spójność transakcyjną i pojedyncze miejsce
do audytu zmian.
"""

from __future__ import annotations

import logging
import re
import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models import EmployeeProfile

User = get_user_model()

logger = logging.getLogger("accounts")


# Mapowanie funkcji pracownika → grupy Django Auth używane przez RBAC.
# Sygnał ``sync_groups_on_employee_save`` używa tej tabeli do synchronizacji
# członkostwa w Group przy każdej zmianie ``EmployeeProfile.function``.
# Klucze odpowiadają wartościom przechowywanym w ``EmployeeProfile.function``
# (wartości enum z :class:`EmployeeProfile.Function`), a grupy docelowe to
# dokładnie te tworzone przez migrację ``accounts.0003_create_rbac_groups``.
#
# ``montażysta`` celowo nie ma grupy — to domyślna funkcja nowych operatorów,
# którym RBAC nie nadaje podwyższonych uprawnień (read-only przez login_required
# wystarcza, principle of least privilege).
FUNCTION_GROUP_MAP: dict[str, list[str]] = {
    "magazynier": ["Magazynierzy"],
    "kierownik": ["Kierownicy"],
    "admin": ["Administratorzy"],
}


def user_for_phone(e164: str | None) -> User | None:
    """Zwraca aktywnego użytkownika przypisanego do numeru w formacie E.164.

    Wykorzystywane do identyfikacji dzwoniącego (caller-ID) w module głosowym:
    numer ``From`` połączenia → konto pracownika → uprawnienia. Zwraca ``None``
    (gość, dostęp tylko do odczytu) gdy numer jest pusty, nieznany, należy do
    profilu nieaktywnego/zanonimizowanego albo do dezaktywowanego użytkownika.
    """
    if not e164:
        return None
    profile = (
        EmployeeProfile.objects.select_related("user")
        .filter(phone=e164, is_active_employee=True, is_anonymized=False)
        .first()
    )
    if profile is None:
        return None
    return profile.user if profile.user.is_active else None


@transaction.atomic
def update_profile(profile: EmployeeProfile, **data) -> EmployeeProfile:
    """Aktualizuje EmployeeProfile via service layer.

    Zapewnia jeden punkt wejścia z full_clean() i save() — co ułatwia
    podpięcie audytu / history_user_id w przyszłości i daje spójną
    walidację niezależnie od miejsca wywołania (view, admin, API).

    Akceptowane pola (whitelist): ``phone``, ``function``, ``theme_preference``,
    ``employee_id``, ``preferred_language``. Pola nieznane (np. ``is_anonymized``) są ignorowane —
    to defensive default chroniący przed przypadkowymi nadpisaniami.

    @transaction.atomic (Wave 4 E2 P1 #12): full_clean() i save() są nieatomowe
    domyślnie — jeśli signal sync_groups_on_employee_save rzuci wyjątek po save,
    profil zostaje w DB ale grupy nie zsynchronizowane (split-brain). @atomic
    rollbackuje całość jako jednostkę.
    """
    allowed = {"phone", "function", "theme_preference", "employee_id", "preferred_language"}
    for key, value in data.items():
        if key in allowed:
            setattr(profile, key, value)
    profile.full_clean()
    profile.save()
    return profile


# PIN głosowy — zbyt oczywiste wartości odrzucane (za łatwe do zgadnięcia).
_TRIVIAL_VOICE_PINS = frozenset(
    {"1234", "4321", "12345", "54321", "123456", "654321", "112233", "121212"}
)


def set_voice_pin(profile: EmployeeProfile, raw_pin: str, *, actor: User | None = None) -> None:
    """Ustawia PIN głosowy pracownika (hash PBKDF2 — NIGDY plaintext).

    Waliduje: 4–6 cyfr, nie trywialny (``1234``/``0000``/ciągi/powtórki). PIN jest
    DRUGIM czynnikiem uwierzytelnienia w agencie głosowym (obok numeru/caller-ID) —
    dzwoniący musi go podać przy każdym połączeniu. Rzuca ``ValidationError`` gdy
    PIN nie spełnia wymagań.
    """
    from django.contrib.auth.hashers import make_password

    pin = (raw_pin or "").strip()
    if not re.fullmatch(r"\d{4,6}", pin):
        raise ValidationError(_("PIN musi składać się z 4–6 cyfr."))
    if pin in _TRIVIAL_VOICE_PINS or len(set(pin)) == 1:
        raise ValidationError(_("PIN jest zbyt prosty — wybierz mniej oczywisty."))
    profile.voice_pin_hash = make_password(pin)
    profile.save(update_fields=["voice_pin_hash", "updated_at"])
    if actor is not None:
        logger.info(
            "set_voice_pin: actor=%s ustawił PIN dla user=%s",
            getattr(actor, "username", "system"),
            profile.user.username,
        )


def verify_voice_pin(profile: EmployeeProfile, raw_pin: str) -> bool:
    """Weryfikuje PIN głosowy (``check_password``). ``False`` gdy brak PIN skonfigurowanego."""
    from django.contrib.auth.hashers import check_password

    if not profile.voice_pin_hash:
        return False
    return check_password((raw_pin or "").strip(), profile.voice_pin_hash)


def clear_voice_pin(profile: EmployeeProfile, *, actor: User | None = None) -> bool:
    """Kasuje PIN głosowy pracownika — ścieżka „admin reset" gdy pracownik zapomni PIN.

    Admin NIE ustawia nowego PIN (nie zna cudzego sekretu) — tylko usuwa hash.
    Pracownik ustawia potem nowy PIN sam (self-service ``set_voice_pin``). To jedyna
    nie-destrukcyjna droga odzyskania dostępu głosowego (alternatywą był tylko
    ``anonymize_employee``, który kasuje całe PII).

    Zwraca ``True`` gdy PIN istniał i został skasowany, ``False`` gdy pracownik
    i tak PIN-u nie miał (idempotentne — brak zapisu). Zdarzenie trafia do dziennika
    przez ``AuditLogMiddleware`` (actor = wywołujący, obiekt = profil); wartość hasha
    NIE jest logowana (audit maskuje ``voice_pin_hash`` — zob. ``core.audit``).
    """
    if not profile.voice_pin_hash:
        return False
    profile.voice_pin_hash = ""
    profile.save(update_fields=["voice_pin_hash", "updated_at"])
    if actor is not None:
        logger.info(
            "clear_voice_pin: actor=%s skasował PIN głosowy user=%s",
            getattr(actor, "username", "system"),
            profile.user.username,
        )
    return True


@transaction.atomic
def register_employee(
    *,
    username: str,
    email: str,
    password: str,
    function: str = EmployeeProfile.Function.MONTAZYSTA,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    actor: User | None = None,
) -> EmployeeProfile:
    """Rejestruje nowego pracownika (User + EmployeeProfile w jednej transakcji).

    Profil jest tworzony automatycznie przez signal post_save, więc tu tylko
    aktualizujemy go o przekazaną funkcję.

    Hasło jest walidowane przez ``AUTH_PASSWORD_VALIDATORS`` (min. długość,
    HIBP breach check, podobieństwo do atrybutów usera) — fail-fast zanim
    zostanie utworzony użytkownik.

    Wave 14-F O-1: ``first_name``, ``last_name``, ``phone``, ``actor``
    dodane jako opcjonalne kwargs (default puste) — pozwala UI form na
    wypełnienie pełnych danych pracownika podczas onboardingu, zachowując
    backward-compat z wywołaniami z testów/seed scripts. ``actor`` zostaje
    zalogowany do audit log (kto utworzył konto).
    """
    validate_password(password)
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name or "",
        last_name=last_name or "",
    )
    profile = user.profile
    profile.function = function
    if phone:
        profile.phone = phone
        profile.save(update_fields=["function", "phone", "updated_at"])
    else:
        profile.save(update_fields=["function", "updated_at"])

    if actor is not None:
        logger.info(
            "register_employee: actor=%s created user=%s function=%s",
            getattr(actor, "username", "system"),
            user.username,
            function,
        )
    return profile


def terminate_employee(
    profile: EmployeeProfile,
    *,
    reason: str = "",
    actor: User | None = None,
) -> EmployeeProfile:
    """Kończy zatrudnienie pracownika: deaktywuje konto, kasuje sesje, usuwa z grup.

    Operacje:
    - ``profile.is_active_employee = False``
    - ``profile.termination_date = today``
    - ``profile.termination_reason = reason`` (truncated do 200 znaków)
    - ``user.is_active = False`` (blokuje login)
    - ``user.groups.clear()`` (revoke RBAC; idempotentne — sygnał i tak posprząta)
    - Kasacja wszystkich aktywnych sesji użytkownika z django.contrib.sessions

    Nieodwracalne dla ``user.is_active`` (re-activate przez admina manualnie).
    Historia zmian zachowana przez django-simple-history. Profil zanonimizowany
    nie może być ponownie terminowany — to błąd logiki wołania.
    """
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    if profile.is_anonymized:
        raise ValidationError(_("Nie można zakończyć zatrudnienia zanonimizowanego profilu."))

    with transaction.atomic():
        profile.is_active_employee = False
        profile.termination_date = timezone.localdate()
        profile.termination_reason = (reason or "")[:200]
        profile.save()

        user = profile.user
        user.is_active = False
        user.save(update_fields=["is_active"])
        user.groups.clear()

        # Kasuj wszystkie sesje użytkownika (force-logout we wszystkich urządzeniach).
        #
        # Wave 4 E2 P1 #6: previous Session.objects.all() ładowało CAŁĄ tabelę
        # sesji do pamięci (jeden Session.get_decoded() per row). Dla produkcji
        # z 10 000+ sesji to O(N) memory + iteracja przez każdą sesję nawet jeśli
        # tylko jedna należy do tego usera. ``.iterator(chunk_size=500)`` ogranicza
        # pamięć do bloków po 500 sesji, plus filter(expire_date__gte=now()) wycina
        # expired sessions które Django i tak czyści przez `clearsessions`.
        # Kasacja w jednym DELETE WHERE session_key IN (...) = O(1) round-trip.
        user_id_str = str(user.pk)
        keys_to_delete: list[str] = []
        active_qs = Session.objects.filter(expire_date__gte=timezone.now())
        for session in active_qs.iterator(chunk_size=500):
            data = session.get_decoded()
            if str(data.get("_auth_user_id")) == user_id_str:
                keys_to_delete.append(session.session_key)
        if keys_to_delete:
            Session.objects.filter(session_key__in=keys_to_delete).delete()

    return profile


def anonymize_employee(
    profile: EmployeeProfile,
    *,
    actor: User | None = None,
) -> EmployeeProfile:
    """Anonimizuje pracownika zgodnie z GDPR Art.17 (right to erasure).

    PII (imię, nazwisko, email, username, telefon) → zastąpione hashem
    anonimowym (8 bajtów hex). ``is_anonymized=True``, ``anonymized_at=now``.
    User pozostaje (dla integralności FK w rezerwacjach/zadaniach), ale jest
    deactivated + group cleared.

    Operacja idempotentna: drugie wywołanie na zanonimizowanym profilu
    zwraca go bez zmian.

    Jeśli profil jest jeszcze aktywny, najpierw wołamy ``terminate_employee``,
    żeby zachować spójność stanu (session kill, group clear, termination_date).

    Nieodwracalne — oryginalne PII są bezpowrotnie tracone.
    """
    from django.utils import timezone

    if profile.is_anonymized:
        return profile  # idempotent: nic do roboty

    with transaction.atomic():
        if profile.is_active_employee:
            terminate_employee(profile, reason="Anonimizacja (GDPR Art.17)", actor=actor)

        anon_id = secrets.token_hex(8)
        user = profile.user
        user.first_name = "Anonimowy"
        user.last_name = f"Pracownik-{anon_id}"
        user.email = f"anon-{anon_id}@deleted.local"
        user.username = f"anon-{anon_id}"
        user.is_active = False
        user.save()

        profile.phone = None
        profile.voice_pin_hash = ""  # RODO: kasujemy hash PIN-u głosowego
        profile.is_anonymized = True
        profile.anonymized_at = timezone.now()
        profile.save()

        # CASCADE: chatbot conversations & messages (GDPR Art.17 — prawo do
        # bycia zapomnianym musi obejmować PII w historii czatu, np. user
        # napisał "Zarezerwuj koparkę dla Tomka Nowaka" — to PII musi zostać
        # wymazane). Konwersacje zostawiamy (FK CASCADE zerwałoby audit
        # rezerwacji utworzonych przez tools), ale Message.content z rolą
        # USER scrub'ujemy do "[anonimizowano]". Odpowiedzi asystenta
        # zostają — nie zawierają PII (LLM nie loguje user inputu w body).
        # Lokalny import — chatbot importuje accounts (deps direction), więc
        # top-level import dałby circular import.
        from chatbot.models import (
            Conversation,
            Message,
        )

        user_convs = Conversation.objects.filter(user=user)
        user_convs_ids = list(user_convs.values_list("pk", flat=True))
        scrubbed_count = Message.objects.filter(
            conversation_id__in=user_convs_ids,
            role=Message.Role.USER,
        ).update(content="[anonimizowano]")
        # Wave 11 H-1 RODO fix: Conversation.title generowany jest z pierwszego
        # pytania user'a (np. "Tomek Nowak chce KOP-001 na pon-pt") — zawiera PII.
        # Cascade obejmuje też tytuły konwersacji.
        titles_scrubbed = user_convs.update(title="[konwersacja zanonimizowana]")
        logger.info(
            "GDPR anonymize cascade: scrubbed %d user message(s) + %d title(s) in %d conversation(s) for user pk=%s",
            scrubbed_count,
            titles_scrubbed,
            len(user_convs_ids),
            user.pk,
        )

        # RODO Art.17 — dziennik zdarzeń trzyma dane osobowe zanonimizowanego
        # użytkownika (adres IP, identyfikator klienta/User-Agent). Sam fakt akcji
        # zostaje (rozliczalność), ale identyfikatory osobowe wymazujemy. FK
        # ``user`` celowo zostaje — wskazuje na już zanonimizowane konto.
        from core.models import AuditLogEntry

        audit_scrubbed = AuditLogEntry.objects.filter(user=user).update(
            ip_address=None, user_agent=""
        )
        logger.info(
            "GDPR anonymize cascade: scrubbed PII in %d audit log entr(ies) for user pk=%s",
            audit_scrubbed,
            user.pk,
        )

    # Wave 11 H-2 RODO fix: HistoricalEmployeeProfile retencja phone PII.
    # django-simple-history snapshotuje wszystkie pola, w tym phone — anonymize
    # zmienia obecny rekord, ale historyczne wpisy zachowują oryginalny numer.
    # Bulk update na wszystkich historical entries dla tego profile.
    #
    # ``None`` (NIE ``""``) — bieżący profil po ``save()`` ma ``phone=None``
    # (``normalize_phone_e164("")`` → ``None``); historyczne wpisy muszą trzymać
    # tę samą reprezentację „braku numeru", inaczej powstaje rozjazd ''/NULL
    # między rekordem bieżącym a historią (audyt RODO oczekuje spójności).
    profile.history.update(phone=None, voice_pin_hash="")

    return profile
