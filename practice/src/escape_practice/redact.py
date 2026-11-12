"""Strip known practice secrets from logs and CLI errors.

Modeled on CVE-2019-11250 (kube-apiserver incomplete bearer-token redaction).
PRACTICE_KEY and HOTEL_LOCAL_TEST_KEY are public test vectors, not live secrets;
they still must not be echoed so a later live key cannot leak the same way.
"""

from __future__ import annotations

from collections.abc import Iterable


def redact_text(text: str, secrets: Iterable[object]) -> str:
    out = text
    for secret in secrets:
        if secret is None:
            continue
        token = secret.decode("ascii") if isinstance(secret, (bytes, bytearray)) else str(secret)
        if len(token) < 4:
            continue
        out = out.replace(token, "<redacted>")
    return out
