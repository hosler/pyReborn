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
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from reborn_protocol import (
    Gen2Codec,
    Gen5Codec,
    PacketBuilder,
    PacketReader,
    SVI,
    SVO,
)
from reborn_protocol.encryption import LIST_SERVER_COMPRESSION


LOGGER = logging.getLogger(__name__)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 14922


@dataclass
class RegisteredServer:
    """Client-facing state advertised by one live game-server link."""

    remote_ip: str
    name: str = ""
    description: str = ""
    language: str = ""
    version: str = ""
    url: str = ""
    ip: str = ""
    port: str = ""
    local_ip: str = ""
    player_ids: Set[int] = field(default_factory=set)


class FakeListServer:
    """Serve the game-server list link on a loopback interface."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = 0):
        self.host = host
        self.port = port
        self.registered = asyncio.Event()
        self._server: Optional[asyncio.AbstractServer] = None
        self._writers: Set[asyncio.StreamWriter] = set()
        self._registered_servers: Dict[asyncio.StreamWriter, RegisteredServer] = {}

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
        self._registered_servers.clear()

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
        LOGGER.info("list-server peer connected from %r", peer)
        try:
            first_byte = await reader.readexactly(1)
            if first_byte[0] == int(SVO.REGISTERV3) + 32:
                registration = first_byte + await reader.readuntil(b"\n")
                await self._handle_game_server(registration[:-1], reader, writer)
            else:
                await self._handle_game_client(first_byte, reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            LOGGER.info("list-server peer disconnected from %r", peer)
        except Exception:
            LOGGER.exception("fake list-server link failed for %r", peer)
        finally:
            self._registered_servers.pop(writer, None)
            self._writers.discard(writer)
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    async def _handle_game_server(
        self,
        registration: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        remote_ip = str(peer[0]) if peer else "127.0.0.1"
        state = RegisteredServer(remote_ip=remote_ip)
        self._registered_servers[writer] = state
        self._handle_registration(registration)
        codec = Gen2Codec()
        while True:
            decoded = await self._read_frame(reader, codec)
            for packet in decoded.split(b"\n"):
                if packet:
                    await self._handle_game_server_packet(packet, writer, codec, state)

    def _handle_registration(self, packet: bytes) -> None:
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

    async def _handle_game_server_packet(
        self,
        packet: bytes,
        writer: asyncio.StreamWriter,
        codec: Gen2Codec,
        state: RegisteredServer,
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
        if packet_id == SVO.NEWSERVER:
            fields = [reader.read_gstring() for _ in range(8)]
            (
                state.name,
                state.description,
                state.language,
                state.version,
                state.url,
                state.ip,
                state.port,
                state.local_ip,
            ) = fields
            self._resolve_auto_address(state)
            return

        field_names = {
            SVO.SETNAME: "name",
            SVO.SETDESC: "description",
            SVO.SETLANG: "language",
            SVO.SETVERS: "version",
            SVO.SETURL: "url",
            SVO.SETIP: "ip",
            SVO.SETPORT: "port",
            SVO.SETLOCALIP: "local_ip",
        }
        if packet_id in field_names:
            setattr(state, field_names[packet_id], reader.remaining().decode("latin1"))
            self._resolve_auto_address(state)
            return
        if packet_id == SVO.SETPLYR:
            state.player_ids.clear()
            return
        if packet_id == SVO.PLYRADD:
            state.player_ids.add(reader.read_gshort())
            return
        if packet_id == SVO.PLYRREM:
            state.player_ids.discard(reader.read_gshort())
            return
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

    async def _handle_game_client(
        self,
        first_byte: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        init_bundle = await self._read_frame(reader, Gen2Codec(), first_byte)
        init_packet = self._single_packet(init_bundle)
        init_reader = PacketReader(init_packet)
        packet_id = init_reader.read_gchar()
        if packet_id != 7:
            raise ValueError(f"expected client encryption setup, received {packet_id}")
        encryption_key = init_reader.read_gchar()
        init_reader.skip(8)
        client_type = init_reader.remaining().decode("ascii", errors="replace")
        LOGGER.debug("client setup key=%d type=%r", encryption_key, client_type)

        codec = Gen5Codec(encryption_key, LIST_SERVER_COMPRESSION)
        login_packet = self._single_packet(await self._read_frame(reader, codec))
        login_reader = PacketReader(login_packet)
        packet_id = login_reader.read_gchar()
        if packet_id != 1:
            raise ValueError(f"expected client serverlist login, received {packet_id}")
        account = login_reader.read_gstring()
        password = login_reader.read_gstring()
        LOGGER.debug("accepted client login account=%r password=%r", account, password)

        live_servers = [
            state for state in self._registered_servers.values() if state.name
        ]
        client_peer = writer.get_extra_info("peername")
        client_ip = str(client_peer[0]) if client_peer else ""
        serverlist = bytearray((32, len(live_servers) + 32))
        for state in live_servers:
            advertised_ip = (
                state.local_ip if client_ip == state.ip and state.local_ip else state.ip
            )
            serverlist.append(8 + 32)
            for value in (
                state.name,
                state.language,
                state.description,
                state.url,
                state.version,
                str(len(state.player_ids)),
                advertised_ip,
                state.port,
            ):
                encoded = value.encode("cp1252", errors="replace")[:223]
                serverlist.append(len(encoded) + 32)
                serverlist.extend(encoded)
        serverlist.append(ord("\n"))
        writer.write(codec.send_packet(bytes(serverlist)))
        await writer.drain()

    @staticmethod
    async def _read_frame(
        reader: asyncio.StreamReader,
        codec,
        first_byte: bytes = b"",
    ) -> bytes:
        header = first_byte + await reader.readexactly(2 - len(first_byte))
        encoded = await reader.readexactly(int.from_bytes(header, "big"))
        decoded = codec.recv_packet(encoded)
        if decoded is None:
            raise ValueError("could not decode packet bundle")
        return decoded

    @staticmethod
    def _single_packet(bundle: bytes) -> bytes:
        packets = [packet for packet in bundle.split(b"\n") if packet]
        if len(packets) != 1:
            raise ValueError(f"expected one packet, received {len(packets)}")
        return packets[0]

    @staticmethod
    def _resolve_auto_address(state: RegisteredServer) -> None:
        if state.ip in {"AUTO", "$AUTO"}:
            state.ip = state.remote_ip


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
