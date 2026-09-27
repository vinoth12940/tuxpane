# Security

## Security model

TuxPane assumes an attacker may be able to reach the agent's TCP port from the local network. A connection must still pass all of these checks:

1. The peer address must be private LAN, link-local, loopback, or Tailscale CGNAT space.
2. TLS 1.3 protects video, clipboard, keyboard, and pointer traffic.
3. The Mac pins the exact certificate fingerprint contained in the pairing code.
4. The client must present the random pairing token before capture or input begins.

The Linux private key and token are readable only by the installing user. Pairing tokens are stored in the macOS Keychain rather than UserDefaults.

## Pairing-code safety

A pairing code contains private addresses, the agent port, its certificate fingerprint, and an authentication token. Anyone who obtains it and can reach the machine may control the desktop. Do not post it in issues, logs, screenshots, or chat rooms.

Revoke every existing pairing with:

```bash
tuxpane pair --reset
```

Then pair trusted Macs again using the newly generated code.

## Network exposure

Do not forward the TuxPane port through a public router or expose it with a public tunnel. The agent rejects non-private source addresses, but this is defense in depth—not a reason to publish the service.

## Reporting vulnerabilities

Do not open a public issue containing a working exploit, pairing code, key, token, or private network information. Contact the maintainer privately through the security-reporting channel configured on the GitHub repository.
