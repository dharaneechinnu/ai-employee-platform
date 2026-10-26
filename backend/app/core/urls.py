"""Checks for addresses a person gives us to call.

A person can point the platform at their own AI server.
Without a check, that is a way to make our servers call into our own
private network (SSRF): an address like http://169.254.169.254 reads
cloud credentials. So a URL must be public, and is checked after DNS
resolution, because a public name can resolve to a private address.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.config import get_settings
from app.core.errors import ValidationError


def is_private_address(hostname: str) -> bool:
    """True for anything that resolves inside the network, or not at all."""
    try:
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except (socket.gaierror, ValueError):
        return True  # cannot resolve it, so do not call it
    return False


def check_service_url(url: str, *, what: str) -> str:
    """Return a cleaned URL, or raise a plain-English ValidationError.

    HTTPS is required, so keys and tool data never cross the internet
    in the clear. `allow_private_urls` (local development only) lets a
    developer point at a server on their own machine.
    """
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    allow_private = get_settings().allow_private_urls

    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ValidationError(f"The {what} address must be a full URL, like https://example.com.")
    if parsed.username or parsed.password:
        raise ValidationError(f"Put the key in the key field, not in the {what} address.")
    if allow_private:
        return cleaned
    if parsed.scheme != "https":
        raise ValidationError(f"The {what} address must start with https://.")
    if is_private_address(parsed.hostname):
        raise ValidationError(
            f"That {what} address is private or cannot be found. "
            "It must be reachable on the public internet."
        )
    return cleaned
