"""Store SQL Server secrets in the macOS Keychain, never in project files."""

from __future__ import annotations

import sys


KEYCHAIN_SERVICE = "com.analytics-studio.sql-server"


class CredentialStoreError(RuntimeError):
    """The macOS Keychain is unavailable or rejected a credential operation."""


def get_password(credential_ref: str) -> str | None:
    keyring = _macos_keyring()
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, credential_ref)
    except Exception as exc:
        raise CredentialStoreError(
            "Could not read the SQL Server password from macOS Keychain."
        ) from exc


def set_password(credential_ref: str, password: str) -> None:
    if not credential_ref or not password:
        raise CredentialStoreError("A SQL Server credential reference and password are required.")
    keyring = _macos_keyring()
    try:
        keyring.set_password(KEYCHAIN_SERVICE, credential_ref, password)
        if keyring.get_password(KEYCHAIN_SERVICE, credential_ref) != password:
            raise CredentialStoreError("The SQL Server password could not be verified in macOS Keychain.")
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError(
            "Could not save the SQL Server password in macOS Keychain."
        ) from exc


def delete_password(credential_ref: str) -> None:
    keyring = _macos_keyring()
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, credential_ref)
    except Exception as exc:
        raise CredentialStoreError(
            "Could not remove the unused SQL Server password from macOS Keychain."
        ) from exc


def _macos_keyring():
    if sys.platform != "darwin":
        raise CredentialStoreError("SQL Server credential storage requires macOS Keychain.")
    try:
        import keyring

        backend = keyring.get_keyring()
    except Exception as exc:
        raise CredentialStoreError(
            "Could not access macOS Keychain. Install the application dependencies and unlock Keychain."
        ) from exc
    backend_module = type(backend).__module__.casefold()
    if "macos" not in backend_module:
        raise CredentialStoreError(
            "The active credential backend isn't macOS Keychain. SQL Server passwords aren't saved to this backend."
        )
    return keyring
