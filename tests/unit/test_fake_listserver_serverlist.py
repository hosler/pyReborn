import asyncio
import socket

from reborn_protocol import Gen2Codec, PacketBuilder, SVO

from game_tester.fake_listserver import FakeListServer
from pyreborn.listserver import ListServerClient


def _open_registered_server(port: int) -> socket.socket:
    connection = socket.create_connection(("127.0.0.1", port), timeout=2)
    registration = (
        PacketBuilder()
        .write_gchar(SVO.REGISTERV3)
        .write_string("2.2.2")
        .write_bytes(b"\n")
        .build()
    )
    server_details = PacketBuilder().write_gchar(SVO.NEWSERVER)
    for value in (
        "Chicken Town",
        "A friendly test server",
        "English",
        "2.2.2",
        "https://example.test/",
        "192.0.2.42",
        "14900",
        "10.0.0.42",
    ):
        server_details.write_gstring(value)
    details_bundle = server_details.write_bytes(b"\n").build()

    connection.sendall(registration)
    connection.sendall(Gen2Codec().send_packet(details_bundle))
    return connection


def test_registered_game_server_appears_in_client_serverlist():
    async def exercise_serverlist():
        async with FakeListServer(port=0) as fake_server:
            game_server = await asyncio.to_thread(
                _open_registered_server, fake_server.bound_port
            )
            try:
                await asyncio.wait_for(fake_server.registered.wait(), timeout=2)
                async def details_received():
                    while not any(
                        state.name == "Chicken Town"
                        for state in fake_server._registered_servers.values()
                    ):
                        await asyncio.sleep(0)

                await asyncio.wait_for(details_received(), timeout=2)
                client = ListServerClient("127.0.0.1", fake_server.bound_port)
                response = await asyncio.to_thread(
                    client.login, "test-account", "test-password", 2
                )
                client.disconnect()
            finally:
                game_server.close()

        assert response.success
        chicken_town = next(
            entry for entry in response.servers if entry.name == "Chicken Town"
        )
        assert chicken_town.address == ("192.0.2.42", 14900)

    asyncio.run(exercise_serverlist())
