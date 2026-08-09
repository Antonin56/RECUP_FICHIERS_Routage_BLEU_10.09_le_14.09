"""SignalMar — Helpers du compte SignalMar admin (support).

31/07/2026 — Fonction de capture d'écran + envoi au support réservée au
propriétaire de l'application. La liste des téléphones admin est lue via la
variable d'environnement ``ADMIN_PHONES`` (séparés par des virgules, format
E.164 canonique) et complétée par un fallback par défaut pour ne jamais se
retrouver « verrouillé » en cas de mauvais réglage .env.
"""
from __future__ import annotations

import os

# Format E.164 canonique. Numéro par défaut = compte propriétaire (l'armateur
# a configuré 0760071445 comme compte SignalMar admin). La variable d'env
# ADMIN_PHONES peut ajouter/remplacer cette liste (séparés par des virgules).
_DEFAULT_ADMINS = {"+33760071445"}


def _load_admin_phones() -> set[str]:
    raw = os.environ.get("ADMIN_PHONES", "").strip()
    if not raw:
        return set(_DEFAULT_ADMINS)
    extras = {p.strip() for p in raw.split(",") if p.strip()}
    return _DEFAULT_ADMINS | extras


ADMIN_PHONES: set[str] = _load_admin_phones()


def is_signalmar_admin(user: dict | None) -> bool:
    """True si le compte est le propriétaire SignalMar (fonctions support
    réservées : capture d'écran, inspection de route, etc.)."""
    if not user:
        return False
    phone = (user.get("phone") or "").strip()
    return bool(phone) and phone in ADMIN_PHONES


__all__ = ["is_signalmar_admin", "ADMIN_PHONES"]
