"""Formularze HTML dla chatbota.

Tylko jeden — :class:`ChatMessageForm` — formularz wprowadzania pytania.
Ograniczenia są celowo restrykcyjne (3..2000 znaków) żeby chronić provider
Gemini przed kosztownymi promptami i odsiać przypadkowe puste/enter-only
submissions.
"""

from __future__ import annotations

from django import forms


class ChatMessageForm(forms.Form):
    """Pojedyncze pytanie do agenta + opcjonalne id istniejącej konwersacji."""

    question = forms.CharField(
        label="Pytanie",
        min_length=3,
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "Np. Czy maszyna KOP-001 jest dostępna od 1 do 5 czerwca?",
                "class": (
                    "w-full px-3 py-2 border border-gray-300 rounded-md "
                    "focus:outline-none focus:ring-2 focus:ring-brand-500 "
                    "dark:bg-gray-800 dark:border-gray-600 dark:text-gray-100"
                ),
            }
        ),
        error_messages={
            "required": "Pytanie jest wymagane.",
            "min_length": "Pytanie musi mieć co najmniej 3 znaki.",
            "max_length": "Pytanie nie może przekraczać 2000 znaków.",
        },
    )
    conversation_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
