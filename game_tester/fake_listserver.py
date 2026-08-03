"""Loopback-only list-server test double for local game-server QA.

This server deliberately accepts every account and password.  It exists only
to let a private, local game server complete logins while offline; it refuses
to bind to a non-loopback interface so the permissive policy cannot
accidentally face a network.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import socket
from contextlib import suppress
from typing import Optional, Set

from reborn_protocol import Gen2Codec, PacketBuilder, PacketReader, SVI, SVO


LOGGER = logging.getLogger(__name__)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 14922


class FakeListServer:
    """Serve the game-server list link on a loopback interface."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = 0):
        self.host = host
        self.port = port
        self.registered = asyncio.Event()
        self._server: Optional[asyncio.AbstractServer] = None
        self._writers: Set[asyncio.StreamWriter] = set()

    @property
    def bound_port(self) -> int:
        """Return the selected TCP port after startup."""
        if self._server is None or not self._server.sockets:
            raise RuntimeError("fake list server is not running")
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> "FakeListServer":
        """Validate the address and start accepting game-server links."""
        if self._server is not None:
            return self
        await self._require_loopback()
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        LOGGER.info("fake list server listening on %s:%d", self.host, self.bound_port)
        return self

    async def close(self) -> None:
        """Close the listener and all accepted links."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        writers = tuple(self._writers)
        for writer in writers:
            writer.close()
        for writer in writers:
            with suppress(ConnectionError):
                await writer.wait_closed()
        self._writers.clear()

    async def __aenter__(self) -> "FakeListServer":
        return await self.start()

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()

    async def _require_loopback(self) -> None:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError:
            address = None
        if address is not None:
            if not address.is_loopback:
                raise ValueError(
                    "fake list server may bind only to a loopback interface"
                )
            return
        loop = asyncio.get_running_loop()
        try:
            addresses = await loop.getaddrinfo(
                self.host,
                self.port,
                type=socket.SOCK_STREAM,
                flags=socket.AI_PASSIVE,
            )
        except socket.gaierror as exc:
            raise ValueError(f"cannot resolve bind address {self.host!r}") from exc
        if not addresses or any(
            not ipaddress.ip_address(address[4][0]).is_loopback
            for address in addresses
        ):
            raise ValueError("fake list server may bind only to a loopback interface")

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        self._writers.add(writer)
        LOGGER.info("game server connected from %r", peer)
        try:
            registration = await reader.readuntil(b"\n")
            await self._handle_registration(registration[:-1])
            codec = Gen2Codec()
            while True:
                header = await reader.readexactly(2)
                length = int.from_bytes(header, "big")
                encoded = await reader.readexactly(length)
                decoded = codec.recv_packet(encoded)
                if decoded is None:
                    raise ValueError("could not decode GEN_2 packet bundle")
                for packet in decoded.split(b"\n"):
                    if packet:
                        await self._handle_packet(packet, writer, codec)
        except (asyncio.IncompleteReadError, ConnectionError):
            LOGGER.info("game server disconnected from %r", peer)
        except Exception:
            LOGGER.exception("fake list-server link failed for %r", peer)
        finally:
            self._writers.discard(writer)
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    async def _handle_registration(self, packet: bytes) -> None:
        reader = PacketReader(packet)
        packet_id = reader.read_gchar()
        name = _enum_name(SVO, packet_id)
        version = reader.remaining().decode("latin1", errors="replace")
        LOGGER.debug(
            "received GEN_1 packet id=%d name=%s version=%r raw=%r",
            packet_id,
            name,
            version,
            packet,
        )
        if packet_id != SVO.REGISTERV3:
            raise ValueError(f"expected REGISTERV3, received {name}")
        self.registered.set()

    async def _handle_packet(
        self,
        packet: bytes,
        writer: asyncio.StreamWriter,
        codec: Gen2Codec,
    ) -> None:
        reader = PacketReader(packet)
        packet_id = reader.read_gchar()
        name = _enum_name(SVO, packet_id)
        LOGGER.debug(
            "received GEN_2 packet id=%d name=%s body=%r raw=%r",
            packet_id,
            name,
            reader.remaining(),
            packet,
        )
        if packet_id != SVO.VERIACC2:
            return
        account = reader.read_gstring()
        password = reader.read_gstring()
        player_id = reader.read_gshort()
        player_type = reader.read_gchar()
        identity = reader.read_gstring_short()
        LOGGER.debug(
            "decoded VERIACC2 account=%r password=%r player_id=%d "
            "player_type=%d identity=%r",
            account,
            password,
            player_id,
            player_type,
            identity,
        )
        response = (
            PacketBuilder()
            .write_gchar(SVI.VERIACC2)
            .write_gchar(len(account.encode("latin1")))
            .write_bytes(account.encode("latin1"))
            .write_gshort(player_id)
            .write_gchar(player_type)
            .write_bytes(b"SUCCESS\n")
            .build()
        )
        writer.write(codec.send_packet(response))
        await writer.drain()


def _enum_name(enum_type, value: int) -> str:
    try:
        return enum_type(value).name
    except ValueError:
        return "UNKNOWN"


async def _run(port: int) -> None:
    server = FakeListServer(port=port)
    async with server:
        await asyncio.Future()


def main() -> None:
    """Run the loopback test double until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(_run(args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
