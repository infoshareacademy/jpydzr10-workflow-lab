from django.db import models


class TimestampedModel(models.Model):
    """Abstrakcyjny model dodający każdej tabeli pola created_at + updated_at.

    Użycie:
        class Machine(TimestampedModel):
            uid = models.CharField(...)

    Automatycznie wypełniane przez Django:
    - created_at: pierwsza wartość przy save() (auto_now_add).
    - updated_at: aktualizowana przy każdym save() (auto_now).
    """

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Utworzono")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Zaktualizowano")

    class Meta:
        abstract = True
