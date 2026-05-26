"""Testy dla generatora PDF rezerwacji (`reservations.pdf`).

Pokrywa:
* ``generate_reservation_pdf`` — zwraca non-empty bytes z poprawnym
  PDF magic byte (%PDF-).
* ``ReservationPDFView`` — view zwraca 200 + Content-Type application/pdf
  + Content-Disposition attachment.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.urls import reverse

from reservations.factories import PendingReservationFactory
from reservations.pdf import generate_reservation_pdf


@pytest.mark.django_db
def test_generate_reservation_pdf_returns_non_empty_bytes(machine):
    """generate_reservation_pdf zwraca non-empty bytes z PDF magic byte."""
    reservation = PendingReservationFactory(
        machine=machine,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 10),
        person="Jan Kowalski",
        notes="Dostawa na plac budowy, brama od strony ul. Lipowej.",
    )

    pdf_bytes = generate_reservation_pdf(reservation)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000  # PDF musi mieć więcej niż header
    assert pdf_bytes.startswith(b"%PDF-"), "Brak PDF magic byte na początku"


@pytest.mark.django_db
def test_generate_reservation_pdf_without_site_and_notes(machine):
    """PDF generuje się także gdy reservation.site=None i notes pusty (fallback —)."""
    reservation = PendingReservationFactory(
        machine=machine,
        site=None,
        notes="",
        person="Anna Nowak",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
    )

    pdf_bytes = generate_reservation_pdf(reservation)

    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000


@pytest.mark.django_db
def test_reservation_pdf_view_returns_pdf_response(client_logged, machine):
    """ReservationPDFView zwraca 200 + Content-Type=application/pdf."""
    reservation = PendingReservationFactory(
        machine=machine,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=3),
    )

    response = client_logged.get(reverse("reservations:pdf", args=[reservation.pk]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert "attachment" in response["Content-Disposition"]
    assert f"rezerwacja-{reservation.pk}.pdf" in response["Content-Disposition"]
    assert response.content.startswith(b"%PDF-")


@pytest.mark.django_db
def test_reservation_pdf_view_requires_login(client, machine):
    """Anonimowy user dostaje redirect do login (LoginRequiredMixin)."""
    reservation = PendingReservationFactory(machine=machine)

    response = client.get(reverse("reservations:pdf", args=[reservation.pk]))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url or "login" in response.url.lower()


@pytest.mark.django_db
def test_reservation_pdf_view_404_for_nonexistent_pk(client_logged):
    """Nieistniejące pk → 404 (get_object_or_404)."""
    response = client_logged.get(reverse("reservations:pdf", args=[999999]))
    assert response.status_code == 404


# =============================================================================
# WAVE 14-A BUNDLE 8 — Polish chars rendering (DejaVu Sans)
# =============================================================================


@pytest.mark.django_db
def test_pdf_registers_dejavu_fonts(machine):
    """Wave 14-A Bundle 8: po wygenerowaniu PDF, DejaVu fonts sa zarejestrowane
    w pdfmetrics. Dzieki temu polskie znaki (aeluoszzczn) renderuja sie
    poprawnie zamiast jako garbage (Pyry -> Pradotworczy itp.).
    """
    from reportlab.pdfbase import pdfmetrics

    from reservations import pdf as pdf_module

    # Reset stanu rejestracji (pdf module-level cache)
    pdf_module._FONTS_REGISTERED = False

    reservation = PendingReservationFactory(
        machine=machine,
        person="Łukasz Żurawski",  # polskie znaki w imieniu
        notes="Dostawa: ul. Świętokrzyska 12, Łódź. Operator: brygadzista Kędzierski.",
    )
    generate_reservation_pdf(reservation)

    # Po generacji DejaVuSans powinien byc zarejestrowany.
    registered = pdfmetrics.getRegisteredFontNames()
    assert "PlanerSans" in registered, (
        f"PlanerSans (DejaVu) nie zarejestrowany. Fonts: {registered}"
    )
    assert "PlanerSans-Bold" in registered, (
        f"PlanerSans-Bold (DejaVu Bold) nie zarejestrowany. Fonts: {registered}"
    )


@pytest.mark.django_db
def test_pdf_with_polish_chars_in_all_fields(machine):
    """Wave 14-A Bundle 8: PDF z pelnym zestawem polskich znakow we wszystkich
    polach (person, address, notes) nie crashnie i wygeneruje valid PDF.
    Smoke test -- weryfikuje ze nie ma UnicodeEncodeError przy serialize.
    """
    reservation = PendingReservationFactory(
        machine=machine,
        person="Brygadzista Sławomir Żmigrodzki",
        address="ul. Świętej Jadwigi 5, Łódź, 90-001",
        responsible_person="Kierownik Łukasz Ćmielowski",
        notes=(
            "Maszyna prądotwórcza będzie używana na budowie. "
            "Operator: pan Ąchocki. Wynajem zaczyna się 5 czerwca."
        ),
    )
    pdf_bytes = generate_reservation_pdf(reservation)
    # PDF musi byc valid (zaczyna sie od %PDF-) i miec sensowny rozmiar.
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 2000  # Wiekszy bo bundled DejaVu subset


@pytest.mark.django_db
def test_pdf_fallback_to_helvetica_when_fonts_missing(machine, monkeypatch, tmp_path):
    """Wave 14-A Bundle 8: jesli DejaVu TTF brakuje w static/fonts/, kod NIE
    crashnie -- defensive degradation do Helvetica (z warningiem w log).
    """
    from django.conf import settings

    from reservations import pdf as pdf_module

    # Wskazujemy BASE_DIR na pusty tmp_path -> fonts dir nie istnieje.
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    pdf_module._FONTS_REGISTERED = False

    reservation = PendingReservationFactory(
        machine=machine, person="Anna", notes="Testowa rezerwacja."
    )
    # Powinno zwrocic valid PDF (Helvetica, bez polskich znakow -- defensive).
    pdf_bytes = generate_reservation_pdf(reservation)
    assert pdf_bytes.startswith(b"%PDF-")
    # _FONTS_REGISTERED zostal na False (brak TTF nie pozwolil zarejestrowac).
    assert pdf_module._FONTS_REGISTERED is False
