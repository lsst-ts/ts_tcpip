# This file is part of ts_tcpip.
#
# Developed for the Rubin Observatory Telescope and Site System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import asyncio
import contextlib
import logging
import typing
import unittest

import pytest
from lsst.ts import tcpip  # type: ignore

# Standard timeout for TCP/IP messages (sec).
TCP_TIMEOUT = 1

# How long to wait for OneClientServer to detect
# that a client has connected (sec).
CONNECTED_TIMEOUT = 1

# Timeout to determine if a StreamReader is open (sec).
# Max time to wait for data (none is expected); this can be quite short.
IS_OPEN_TIMEOUT = 0.1

logging.basicConfig()


class ClientTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client_connect_callback_raises: bool = False
        self.client_connect_queue: asyncio.Queue = asyncio.Queue()
        self.log = logging.getLogger()

    @contextlib.asynccontextmanager
    async def make_server(
        self, host: str, **kwargs: typing.Any
    ) -> typing.AsyncGenerator[tcpip.OneClientServer, None]:
        """Make a OneClientServer with a randomly chosen port.

        Parameters
        ----------
        host : `str`
            Host IP address
        **kwargs
            Additional keyword arguments for OneClientServer

        Returns
        -------
        server : `OneClientServer`
            The server, with port assigned and ready to receive connections.
        """
        async with tcpip.OneClientServer(
            host=host,
            port=0,
            log=self.log,
            connect_callback=None,
            name="test",
            **kwargs,
        ) as server:
            yield server

    @contextlib.asynccontextmanager
    async def make_client(
        self,
        server: tcpip.OneClientServer,
        **kwargs: typing.Any,
    ) -> typing.AsyncGenerator[tcpip.Client, None]:
        """Make a TCP/IP client that talks to the server and wait for it to
        connect.

        Parameters
        ----------
        server : `OneClientServer`
            The server to which to connect.
        **kwargs:
            Additional keywords for `asyncio.open_connection`.

        Returns
        -------
            client : `tcpip.Client`
                The client.
        """
        self.client_connect_queue = asyncio.Queue()
        async with tcpip.Client(
            host=server.host,
            port=server.port,
            log=self.log,
            connect_callback=self.client_connect_callback,
            name="test",
            **kwargs,
        ) as client:
            assert client.should_be_connected
            await asyncio.wait_for(server.connected_task, timeout=CONNECTED_TIMEOUT)
            yield client

    async def client_connect_callback(self, client: tcpip.Client) -> None:
        print(f"client_connect_callback: connected={client.connected}")
        if self.client_connect_callback_raises:
            raise RuntimeError(
                "client_connect_callback raising because self.client_connect_callback_raises is true"
            )
        self.client_connect_queue.put_nowait(client.connected)

    async def assert_next_client_connected(
        self, connected: bool, timeout: int = TCP_TIMEOUT
    ) -> None:
        """Assert results of next client_connect_callback.

        Parameters
        ----------
        connected : `bool`
            Is a client connected to the client connected?
        timeout : `float`
            Time to wait for client_connect_callback (seconds).
        """
        next_connected = await asyncio.wait_for(
            self.client_connect_queue.get(), timeout=timeout
        )
        assert connected == next_connected

    async def check_read_write(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # Check at least 2 writes and reads,
        # to detect extra characters being written.
        assert reader is not None
        assert writer is not None
        for i in range(2):
            data_text = f"some data to write {i}"
            data_bytes = data_text.encode() + tcpip.TERMINATOR
            writer.write(data_bytes)
            await writer.drain()
            read_data_bytes = await reader.readuntil(tcpip.TERMINATOR)
            assert data_bytes == read_data_bytes

    async def test_basic_close(self) -> None:
        async with self.make_server(
            host=tcpip.LOCALHOST_IPV4
        ) as server, self.make_client(server) as client:
            await self.assert_next_client_connected(True)

            await client.basic_close()
            assert not client.connected
            assert client.should_be_connected
            await self.assert_next_client_connected(False)
            with pytest.raises((asyncio.IncompleteReadError, ConnectionResetError)):
                await client.reader.readuntil(tcpip.TERMINATOR)

    async def test_close(self) -> None:
        """Test Client.close"""
        async with self.make_server(
            host=tcpip.LOCALHOST_IPV4
        ) as server, self.make_client(server) as client:
            await self.assert_next_client_connected(True)

            await client.close()
            assert not client.connected
            assert not client.should_be_connected
            await self.assert_next_client_connected(False)
            with pytest.raises((asyncio.IncompleteReadError, ConnectionResetError)):
                await client.reader.readuntil(tcpip.TERMINATOR)

            # Subsequent calls should have no effect
            await client.close()

    async def test_connect_callback_raises(self) -> None:
        self.client_connect_callback_raises = True
        async with self.make_server(host=tcpip.LOCALHOST_IPV4) as server:
            assert not server.connected
            async with self.make_client(server) as client:
                assert client.connected
                assert server.connected
                with pytest.raises(asyncio.TimeoutError):
                    await self.assert_next_client_connected(True)
                await self.check_read_write(reader=server.reader, writer=client.writer)
                await self.check_read_write(reader=client.reader, writer=server.writer)

    async def test_initial_conditions(self) -> None:
        for localhost in (tcpip.LOCALHOST_IPV4, tcpip.LOCALHOST_IPV6):
            async with self.make_server(host=localhost) as server:
                assert server.port != 0
                async with self.make_client(server) as client:
                    assert client.connected
                    assert server.connected
                    await self.assert_next_client_connected(True)

    async def test_read_write(self) -> None:
        for localhost in (tcpip.LOCALHOST_IPV4, tcpip.LOCALHOST_IPV6):
            async with self.make_server(host=localhost) as server, self.make_client(
                server
            ) as client:
                await self.check_read_write(reader=client.reader, writer=server.writer)
                await self.check_read_write(reader=server.reader, writer=client.writer)

    async def test_server_drops_connection(self) -> None:
        async with self.make_server(
            host=tcpip.LOCALHOST_IPV4
        ) as server, self.make_client(server) as client:
            await self.assert_next_client_connected(True)

            await server.close_client()
            await self.assert_next_client_connected(False)
            assert client.should_be_connected
