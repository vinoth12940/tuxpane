"""Agent entry point for the systemd user service: python3 -m tuxpane --config ~/.config/tuxpane/agent.json."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pathlib
import signal

from .config import CONFIG_DIR, AgentConfig, load_config


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="TuxPane agent")
    ap.add_argument("--config", type=pathlib.Path, default=CONFIG_DIR / "agent.json")
    ap.add_argument("--bind", default="0.0.0.0", help="listen address (peers are still limited to private networks)")
    ap.add_argument("--display", default=os.environ.get("DISPLAY", ":0"))
    return ap.parse_args(argv)


def load_agent_files(config_path: pathlib.Path) -> tuple[AgentConfig, str, pathlib.Path, pathlib.Path]:
    directory = config_path.parent
    cert, key, token_path = directory / "cert.pem", directory / "key.pem", directory / "token"
    missing = [p for p in (config_path, token_path, cert, key) if not p.exists()]
    if missing:
        raise SystemExit(f"missing {', '.join(str(p) for p in missing)}: run the TuxPane installer again")
    try:
        config = load_config(config_path)
    except ValueError as exc:
        raise SystemExit(f"{config_path}: {exc}") from exc
    token = token_path.read_text().strip()
    if len(token) < 16:
        raise SystemExit(f"{token_path}: token too short; run `tuxpane pair --reset`")
    return config, token, cert, key


async def serve(args: argparse.Namespace) -> None:
    from .clipboard import XClipClipboard
    from .cursor import CursorWatcher
    from .display import Display
    from .encoder import Encoder, make_cmd_builder
    from .security import server_tls_context
    from .server import Server
    from .xinput import XTestInjector

    config, token, cert, key = load_agent_files(args.config)
    server = Server(
        token=token,
        injector=XTestInjector(args.display),
        display=Display(match_resolution=config.match_resolution),
        encoder_factory=lambda on_frame, on_failure: Encoder(
            on_frame, display=args.display, fps=config.fps, bitrate_mbps=config.bitrate_mbps,
            cmd_builder=make_cmd_builder(config.encoder, config.vaapi_device), on_failure=on_failure),
        cursor=CursorWatcher(args.display),
        clipboard=XClipClipboard(),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    tcp = await asyncio.start_server(server.handle, args.bind, config.port,
                                     ssl=server_tls_context(cert, key), ssl_handshake_timeout=10)
    logging.info("listening on %s:%d (TLS, encoder %s)", args.bind, config.port, config.encoder)
    async with tcp:
        await stop.wait()
        logging.info("stopping: releasing held input")
        await server.shutdown()


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(serve(parse_args(argv)))


if __name__ == "__main__":
    main()
