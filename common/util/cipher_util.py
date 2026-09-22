# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Config-secret encryption for the registry center.

encrypt() produces a versioned ciphertext (``enc:v1:<token>``) using
Fernet (AES-128-CBC + HMAC) with a deployment key; decrypt() reverses it.

Backward compatibility: values WITHOUT the ``enc:v1:`` prefix (plaintext
entries written before this implementation existed, or deployments that
provide their own cipher_util) pass through decrypt() unchanged, so
existing configuration files keep working.

Key resolution (first match wins):
1. ``REGISTRY_CIPHER_KEY`` environment variable (Fernet key, urlsafe
   base64-encoded 32 bytes)
2. ``REGISTRY_CIPHER_KEY_FILE`` environment variable pointing at a key file
3. ``etc/conf/cipher.key`` under the installation root — auto-generated
   with 0600 permissions on first use

Deployments that prefer a KMS/HSM can replace this module; the function
signatures are the contract.
"""

import os
import stat
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

DEFAULT_ENCODING = 'utf-8'
_CIPHER_PREFIX = "enc:v1:"
_KEY_ENV = "REGISTRY_CIPHER_KEY"
_KEY_FILE_ENV = "REGISTRY_CIPHER_KEY_FILE"

_fernet: Optional[Fernet] = None


def _key_file_path() -> str:
    from common.util.app_config import get_root_path
    return os.path.join(get_root_path(), "etc", "conf", "cipher.key")


def _load_or_create_key() -> bytes:
    """Resolve the Fernet key: env var, key file, or auto-generated key file."""
    key = os.environ.get(_KEY_ENV, '')
    if key:
        return key.strip().encode(DEFAULT_ENCODING)

    key_file = os.environ.get(_KEY_FILE_ENV, '') or _key_file_path()
    if os.path.exists(key_file):
        with open(key_file, 'r', encoding=DEFAULT_ENCODING) as f:
            stored = f.read().strip()
        if stored:
            return stored.encode(DEFAULT_ENCODING)

    generated = Fernet.generate_key()
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    with open(key_file, 'w', encoding=DEFAULT_ENCODING) as f:
        f.write(generated.decode(DEFAULT_ENCODING))
    try:
        os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:  # pragma: no cover - Windows chmod is best-effort
        pass
    logger.info(f"Generated config-secret cipher key at {key_file}")
    return generated


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = _load_or_create_key()
        try:
            _fernet = Fernet(key)
        except ValueError as e:
            raise ValueError(
                f"Cipher key is not valid Fernet key material (32 url-safe "
                f"base64-encoded bytes): {e}. Fix REGISTRY_CIPHER_KEY or the "
                f"cipher.key file.") from e
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a configuration secret. Output carries the ``enc:v1:`` prefix."""
    if not plaintext:
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode(DEFAULT_ENCODING)).decode(DEFAULT_ENCODING)
    return f"{_CIPHER_PREFIX}{token}"


def decrypt(ciphertext: str) -> bytes:
    """Decrypt a configuration secret.

    Values with the ``enc:v1:`` prefix are Fernet-decrypted; anything else
    is returned unchanged (legacy plaintext entries stay readable). Raises
    ValueError when a prefixed ciphertext cannot be decrypted (wrong key or
    corrupted value) — silently mis-decrypting would produce wrong runtime
    credentials, which is worse than a clear startup failure.
    """
    if not ciphertext:
        return ciphertext.encode(DEFAULT_ENCODING)
    if not ciphertext.startswith(_CIPHER_PREFIX):
        return ciphertext.encode(DEFAULT_ENCODING)
    token = ciphertext[len(_CIPHER_PREFIX):]
    try:
        return _get_fernet().decrypt(token.encode(DEFAULT_ENCODING))
    except InvalidToken as e:
        raise ValueError(
            "Config secret cannot be decrypted: the cipher key does not match "
            "the one used to encrypt this value (wrong REGISTRY_CIPHER_KEY / "
            "cipher.key, or the value was corrupted). Re-encrypt the secret "
            "with the current key.") from e
