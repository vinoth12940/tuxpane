"""Test-only Mac side of pairing, written independently of the agent's session code."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import ssl

from tuxpane import protocol as p
from tuxpane.pairing_protocol import (PAIR_ABORT, PAIR_ACCEPT, PAIR_CONFIRM, PAIR_HELLO, PAIR_NONCE, PAIR_REJECT,
                                      PAIR_REVEAL, commitment, fields, message, sas_code)


async def pair(host: str, port: int, *, mac_name: str = "Test Mac", confirm: bool = True,
               reveal_nonce: bytes | None = None, stop_after: str | None = None) -> dict:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    reader, writer = await asyncio.open_connection(host, port, ssl=context)
    try:
        fingerprint = hashlib.sha256(writer.get_extra_info("ssl_object").getpeercert(binary_form=True)).digest()
        nonce = secrets.token_bytes(32)
        writer.write(message(PAIR_HELLO, v=1, name=mac_name, commit=commitment(nonce)))
        msg_type, payload = await asyncio.wait_for(p.read_message(reader), 5)
        if msg_type == PAIR_REJECT:
            return {"result": "rejected", "reason": fields(payload).get("reason"), "code": None, "accept": None}
        agent_nonce = bytes.fromhex(fields(payload)["nonce"])
        writer.write(message(PAIR_REVEAL, nonce=(reveal_nonce or nonce).hex()))
        code = sas_code(fingerprint, agent_nonce, nonce)
        if stop_after == "reveal":
            return {"result": "stopped", "code": code, "reason": None, "accept": None}
        writer.write(message(PAIR_CONFIRM) if confirm else message(PAIR_ABORT, reason="codes differ"))
        await writer.drain()
        try:
            msg_type, payload = await asyncio.wait_for(p.read_message(reader), 10)
        except asyncio.IncompleteReadError:
            return {"result": "closed", "code": code, "reason": None, "accept": None}
        data = fields(payload)
        if msg_type == PAIR_ACCEPT:
            return {"result": "accepted", "code": code, "reason": None, "accept": data}
        return {"result": "rejected", "code": code, "reason": data.get("reason"), "accept": None}
    finally:
        writer.close()
