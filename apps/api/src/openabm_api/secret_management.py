from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from openabm_api.settings import Settings


@dataclass(frozen=True)
class SecretCiphertext:
    ciphertext: str
    ciphertext_sha256: str
    encryption_mode: str


class SecretDecryptionError(ValueError):
    pass


class LocalSecretCipher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fernet = Fernet(_fernet_key(settings))

    @property
    def encryption_mode(self) -> str:
        return "local-fernet-v1"

    def encrypt(self, plaintext: str) -> SecretCiphertext:
        ciphertext = self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        return SecretCiphertext(
            ciphertext=ciphertext,
            ciphertext_sha256=hashlib.sha256(ciphertext.encode("utf-8")).hexdigest(),
            encryption_mode=self.encryption_mode,
        )

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            message = "Secret could not be decrypted with configured key."
            raise SecretDecryptionError(message) from exc


def secret_backend_status(settings: Settings) -> dict[str, object]:
    return {
        "active_mode": settings.secret_mode,
        "local_development_secret_mode": {
            "status": "implemented",
            "encryption": "Fernet envelope encryption",
            "key_source": "OPENABM_SECRET_KEY or local dev key derivation",
        },
        "production_external_secret_manager_integration_point": {
            "status": "adapter_boundary",
            "provider": settings.external_secret_provider,
            "expected_operations": ["create", "read", "rotate", "delete", "audit"],
        },
        "secret_refs_only_in_configs": True,
        "plaintext_storage": False,
        "sandbox_mount_default": "disabled",
    }


def redact_secret_ref(secret_ref: str) -> str:
    if len(secret_ref) <= 12:
        return f"{secret_ref[:4]}..."
    return f"{secret_ref[:8]}...{secret_ref[-4:]}"


def _fernet_key(settings: Settings) -> bytes:
    material = settings.secret_key
    if material is None:
        material = f"openabm-local-secret:{settings.environment}:{settings.dev_api_key}"
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)
