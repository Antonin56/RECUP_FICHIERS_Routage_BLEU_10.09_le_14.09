"""SignalMar — Abstraction d'envoi de SMS (Phase A, OTP téléphone).

Interface unique ``SmsSender`` derrière laquelle on branchera MessageBird
(ou autre) plus tard sans toucher aux routes. Sélection par variable
d'environnement ``SMS_PROVIDER`` :

    * ``mock`` (défaut) — n'envoie RIEN : logge le message côté serveur et le
      code OTP est TOUJOURS ``123456`` (voir ``fixed_code``) pour permettre
      les tests de bout en bout sans passerelle SMS.
    * ``messagebird`` — à implémenter lors de l'intégration réelle (clé API
      requise) ; ``fixed_code`` retournera alors None → code aléatoire.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("signmar.sms")

MOCK_OTP_CODE = "123456"


class SmsSender(ABC):
    """Contrat minimal d'un fournisseur SMS."""

    @abstractmethod
    async def send(self, phone_e164: str, message: str) -> bool:
        """Envoie ``message`` à ``phone_e164``. Retourne True si accepté."""

    def fixed_code(self) -> Optional[str]:
        """Code OTP imposé (mock uniquement). None → code aléatoire."""
        return None


class MockSmsSender(SmsSender):
    """Aucun SMS réel — log serveur + code fixe 123456."""

    async def send(self, phone_e164: str, message: str) -> bool:
        logger.info("[MOCK SMS] to=%s | %s", phone_e164, message)
        return True

    def fixed_code(self) -> Optional[str]:
        return MOCK_OTP_CODE


def get_sms_sender() -> SmsSender:
    provider = os.environ.get("SMS_PROVIDER", "mock").lower()
    if provider == "mock":
        return MockSmsSender()
    # Fallback défensif : jamais bloquer l'auth à cause d'un provider inconnu.
    logger.warning("SMS_PROVIDER=%s inconnu — fallback mock.", provider)
    return MockSmsSender()
