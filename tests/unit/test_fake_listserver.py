"""Loopback interoperability tests for the local list-server test double."""

import asyncio
import errno
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from game_tester.fake_listserver import FakeListServer

PYTHON_SERVER_ROOT = Path(__file__).resolve().parents[3] / "pygserver"
sys.path.insert(0, str(PYTHON_SERVER_ROOT))
from pygserver.listserver import ServerListClient


def test_non_loopback_bind_is_refused_before_opening_a_socket():
    async def exercise():
        server = FakeListServer(host="192.0.2.1")
        with pytest.raises(ValueError, match="only to a loopback"):
            await server.start()

    asyncio.run(exercise())


def test_registration_and_account_verification_are_accepted():
    async def exercise():
        config = SimpleNamespace(
            enable_listserver=True,
            listip="127.0.0.1",
            listport=0,
            localip="127.0.0.1",
            serverip="127.0.0.1",
            port=14900,
            hq_password="",
            name="Offline QA",
            description="local test server",
            language="English",
            url="",
            hq_level=1,
        )
        login_completed = asyncio.Event()
        player = SimpleNamespace(
            id=37,
            account_name="any-account",
            connection_type=0,
            logged_in=False,
            send_login=AsyncMock(side_effect=login_completed.set),
        )
        game_server = SimpleNamespace(config=config, players={player.id: player})
        try:
            async with FakeListServer() as fake_server:
                config.listport = fake_server.bound_port
                client = ServerListClient(game_server)
                await client.start()
                try:
                    await asyncio.wait_for(fake_server.registered.wait(), 2.0)
                    assert client.connected
                    await client.verify_account(player, "any-password", "device")
                    await asyncio.wait_for(login_completed.wait(), 2.0)
                    assert player.account_name == "any-account"
                    player.send_login.assert_awaited_once_with()
                finally:
                    await client.stop()
        except OSError as exc:
            bind_denied = exc.errno is None and "could not bind" in str(exc)
            if bind_denied or exc.errno in {
                errno.EACCES,
                errno.EPERM,
                errno.EADDRNOTAVAIL,
            }:
                pytest.skip(f"loopback sockets unavailable: {exc}")
            raise

    asyncio.run(exercise())
