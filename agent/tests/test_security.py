import asyncio
import hashlib
import pathlib
import shutil
import ssl
import subprocess
import tempfile
import unittest

from tuxpane.security import cert_fingerprint, is_allowed_peer, server_tls_context


def make_cert(directory: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    key, cert = directory / "key.pem", directory / "cert.pem"
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "req", "-new", "-x509", "-key", str(key), "-out", str(cert), "-days", "1",
                    "-subj", "/CN=tuxpane"], check=True, capture_output=True)
    return cert, key


class PeerFilterTest(unittest.TestCase):
    def test_private_networks_are_allowed(self):
        for host in ("127.0.0.1", "::1", "192.168.1.5", "10.0.0.2", "172.20.1.1", "169.254.3.4",
                     "100.64.100.27", "fd7a:115c:a1e0::1234:5678", "::ffff:192.168.1.5", "fe80::1%eth0"):
            self.assertTrue(is_allowed_peer(host), host)

    def test_public_and_garbage_are_refused(self):
        for host in ("8.8.8.8", "81.2.69.160", "100.128.0.1", "2001:4860:4860::8888", "", "not-an-ip"):
            self.assertFalse(is_allowed_peer(host), host)


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI required")
class TlsTest(unittest.IsolatedAsyncioTestCase):
    async def test_server_presents_the_fingerprinted_certificate_over_tls13(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert, key = make_cert(pathlib.Path(tmp))

            async def echo(reader, writer):
                writer.write(await reader.readexactly(4))
                await writer.drain()
                writer.close()

            server = await asyncio.start_server(echo, "127.0.0.1", 0, ssl=server_tls_context(cert, key))
            port = server.sockets[0].getsockname()[1]
            client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            client.check_hostname = False
            client.verify_mode = ssl.CERT_NONE
            reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=client)
            tls = writer.get_extra_info("ssl_object")
            self.assertEqual(tls.version(), "TLSv1.3")
            self.assertEqual(hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest(), cert_fingerprint(cert))
            writer.write(b"ping")
            self.assertEqual(await reader.readexactly(4), b"ping")
            writer.close()
            server.close()
            await server.wait_closed()


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI required")
class SecurityMaterialTest(unittest.TestCase):
    def test_creates_private_token_and_certificate(self):
        from tuxpane.security import ensure_security_material
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp) / "tuxpane"
            token, fingerprint = ensure_security_material(d)
            self.assertGreaterEqual(len(token), 40)
            self.assertEqual(fingerprint, cert_fingerprint(d / "cert.pem"))
            self.assertEqual(d.stat().st_mode & 0o777, 0o700)
            for name in ("token", "cert.pem", "key.pem"):
                self.assertEqual((d / name).stat().st_mode & 0o777, 0o600, name)

    def test_security_material_is_reused(self):
        from tuxpane.security import ensure_security_material
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            self.assertEqual(ensure_security_material(d), ensure_security_material(d))

    def test_reset_rotates_token_and_certificate(self):
        from tuxpane.security import ensure_security_material
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            first = ensure_security_material(d)
            second = ensure_security_material(d, reset=True)
            self.assertNotEqual(first[0], second[0])
            self.assertNotEqual(first[1], second[1])


class ExplicitPeerPolicyTest(unittest.TestCase):
    def test_special_purpose_ranges_are_not_private_enough(self):
        for host in ("198.18.0.1", "192.0.0.1", "240.0.0.1", "203.0.113.9", "2001:db8::1"):
            self.assertFalse(is_allowed_peer(host), host)

    def test_ipv6_unique_local_is_allowed(self):
        self.assertTrue(is_allowed_peer("fd00::1"))


if __name__ == "__main__":
    unittest.main()
