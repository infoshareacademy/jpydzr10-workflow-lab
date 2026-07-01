"""Ustawienia dla procesu agenta głosowego (uvicorn na :8010).

Dlaczego osobny moduł, a nie ``dev.py``:

* ``dev.py`` ma ``DEBUG = True`` jako LITERAŁ (zmienna środowiskowa go nie
  zmieni) — agent głosowy działa za publicznym tunelem, więc DEBUG=True
  wystawiłby strony debugowe z danymi wrażliwymi.
* ``dev.py`` BEZWARUNKOWO dodaje ``debug_toolbar`` (apps + middleware), które
  PODNOSI WYJĄTEK przy starcie pod ``DEBUG=False`` — uvicorn nie zbindowałby
  portu (martwa cisza na scenie).
* ``dev.py`` nie zna hosta tunelu, więc pierwszy webhook Twilio = DisallowedHost.

Ten moduł dziedziczy konfigurację bazy/poczty/kluczy z ``dev.py`` (poczta jest
sterowana środowiskiem — przy ustawionym EMAIL_HOST realny SMTP, np. Gmail do
pokazu), a następnie naprawia powyższe trzy problemy.
"""

import os

from .dev import *  # noqa: F403

DEBUG = False

# Usuń debug_toolbar — pod DEBUG=False jego start rzuca wyjątek.
INSTALLED_APPS = [a for a in INSTALLED_APPS if a != "debug_toolbar"]  # noqa: F405
MIDDLEWARE = [m for m in MIDDLEWARE if "debug_toolbar" not in m]  # noqa: F405

# Host tunelu (cloudflared) dla webhooka Twilio i połączenia WS.
VOICE_TUNNEL_HOST = os.environ.get("VOICE_TUNNEL_HOST", "")
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
if VOICE_TUNNEL_HOST:
    ALLOWED_HOSTS.append(VOICE_TUNNEL_HOST)
    CSRF_TRUSTED_ORIGINS = [f"https://{VOICE_TUNNEL_HOST}"]

# Webhook głosowy jest tu wystawiony za PUBLICZNYM tunelem — wymuszamy podpis
# Twilio (fail-closed). Dziedziczymy ``False`` z ``dev.py``, więc jawnie
# przywracamy bezpieczny default: brak ``TWILIO_AUTH_TOKEN`` → webhook odrzucony.
VOICE_REQUIRE_SIGNATURE = True

# Model Gemini Live (zamrożony też w .env). Żaden model Live NIE streamuje TEXT-out
# (API zwraca 1007) — most używa AUDIO-out + transkrypcji tekstowej
# (``output_audio_transcription``), a transkrypt idzie do ConversationRelay jako
# ramki ``text``. Zweryfikowane realnymi połączeniami: gemini-3.1-flash-live-preview
# (niższa latencja) oraz gemini-2.5-flash-native-audio-latest działają.
GEMINI_LIVE_MODEL = os.environ.get("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
