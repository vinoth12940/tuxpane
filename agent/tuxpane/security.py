"""TLS and network-access rules for the agent."""
from __future__ import annotations

import hashlib
import ipaddress
import os
import pathlib
import secrets
import ssl
import subprocess

TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")
# Explicit lists: Python's is_private also covers benchmark, documentation and reserved ranges.
ALLOWED_PEER_IPV4 = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16", "127.0.0.0/8"))
ALLOWED_PEER_IPV6 = tuple(ipaddress.ip_network(n) for n in ("::1/128", "fc00::/7", "fe80::/10"))


def is_allowed_peer(host: str) -> bool:
    """Only LAN, Tailscale and local peers may connect, even if the port is forwarded by mistake."""
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    networks = ALLOWED_PEER_IPV4 if ip.version == 4 else ALLOWED_PEER_IPV6
    return any(ip in network for network in networks)


def server_tls_context(cert, key) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(str(cert), str(key))
    return context


def cert_fingerprint(cert_path) -> str:
    """SHA-256 of the certificate's DER bytes; the Mac pins exactly this value."""
    der = ssl.PEM_cert_to_DER_cert(pathlib.Path(cert_path).read_text())
    return hashlib.sha256(der).hexdigest()


def ensure_security_material(config_dir, run=subprocess.run, reset: bool = False) -> tuple[str, str]:
    """Creates the token and self-signed certificate once; re-installs keep them so pairings survive."""
    config_dir = pathlib.Path(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(config_dir, 0o700)
    token_path, cert, key = config_dir / "token", config_dir / "cert.pem", config_dir / "key.pem"
    if reset:
        for path in (token_path, cert, key):
            path.unlink(missing_ok=True)
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32) + "\n")
    if not (cert.exists() and key.exists()):
        run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)],
            check=True, capture_output=True)
        run(["openssl", "req", "-new", "-x509", "-key", str(key), "-out", str(cert), "-days", "3650",
             "-subj", "/CN=tuxpane"], check=True, capture_output=True)
    for path in (token_path, cert, key):
        os.chmod(path, 0o600)
    return token_path.read_text().strip(), cert_fingerprint(cert)
