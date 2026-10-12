"""Store SQL Server secrets in the macOS Keychain, never in project files."""

from __future__ import annotations

import hashlib
import json
import sys


KEYCHAIN_SERVICE = "com.analytics-studio.sql-server"


class CredentialStoreError(RuntimeError):
    """The macOS Keychain is unavailable or rejected a credential operation."""


def credential_account(credential_ref: str, connection: dict | None = None) -> str:
    """Bind a Keychain account to the exact SQL Server connection settings.

    Omitting ``connection`` addresses the legacy account name. Controller code
    always supplies it, so a copied project cannot redirect an existing local
    password to a different server by reusing its credential reference.
    """
    if connection is None:
        return credential_ref
    identity = {
        key: connection.get(key)
        for key in ("server", "port", "database", "username", "driver", "encrypt")
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"v1:{credential_ref}:{digest}"


def get_password(
    credential_ref: str,
    connection: dict | None = None,
) -> str | None:
    keyring = _macos_keyring()
    try:
        return keyring.get_password(
            KEYCHAIN_SERVICE,
            credential_account(credential_ref, connection),
        )
    except Exception as exc:
        raise CredentialStoreError(
            "Could not read the SQL Server password from macOS Keychain."
        ) from exc


def set_password(
    credential_ref: str,
    password: str,
    connection: dict | None = None,
) -> None:
    if not credential_ref or not password:
        raise CredentialStoreError("A SQL Server credential reference and password are required.")
    keyring = _macos_keyring()
    account = credential_account(credential_ref, connection)
    try:
        keyring.set_password(KEYCHAIN_SERVICE, account, password)
        if keyring.get_password(KEYCHAIN_SERVICE, account) != password:
            raise CredentialStoreError("The SQL Server password could not be verified in macOS Keychain.")
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError(
            "Could not save the SQL Server password in macOS Keychain."
        ) from exc


def delete_password(
    credential_ref: str,
    connection: dict | None = None,
) -> None:
    keyring = _macos_keyring()
    try:
        accounts = [credential_account(credential_ref, connection)]
        if connection is not None and accounts[0] != credential_ref:
            accounts.append(credential_ref)
        for account in accounts:
            if keyring.get_password(KEYCHAIN_SERVICE, account) is not None:
                keyring.delete_password(KEYCHAIN_SERVICE, account)
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
