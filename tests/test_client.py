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
import ctypes
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


class ShortStruct(ctypes.Structure):
    """Simple ctypes struct for testing read_into and write_from"""

    _pack_ = 1
    _fields_ = [
        ("ushort_0", ctypes.c_ushort),
        ("int64_0", ctypes.c_int64),
        ("double_0", ctypes.c_double),
        ("float_0", ctypes.c_float),
    ]


class ClientTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client_connect_callback_raises: bool = False
        self.client_connect_queue: asyncio.Queue = asyncio.Queue()
        self.log = logging.getLogger()

    @contextlib.asynccontextmanager
    async def make_server(
        self, host: str = tcpip.LOCALHOST_IPV4, **kwargs: typing.Any
    ) -> typing.AsyncGenerator[tcpip.OneClientServer, None]:
        """Make a OneClientServer with a randomly chosen port.

        Parameters
        ----------
        host : `str`
            Host IP address
        **kwargs : `dict` [`str`, `typing.Any`]
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
        **kwargs : `dict` [`str`, `typing.Any`]
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

    async def check_read_write_methods(
        self, reader: tcpip.BaseClientOrServer, writer: tcpip.BaseClientOrServer
    ) -> None:
        write_bytes = b"data for read with n=len"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(
            reader.read(n=len(write_bytes)), timeout=TCP_TIMEOUT
        )
        assert read_bytes == write_bytes

        nextra = 5  # extra bytes to wait for; an arbitrary positive value
        write_bytes = b"data for read with n>len"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(
            reader.read(n=len(write_bytes) + nextra), timeout=TCP_TIMEOUT
        )
        assert read_bytes == write_bytes

        nskip = 5  # arbitrary positive value smaller than the data len
        write_bytes = b"data for read with n<len"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(
            reader.read(n=len(write_bytes) - nskip), timeout=TCP_TIMEOUT
        )
        assert read_bytes == write_bytes[0:-nskip]
        read_bytes = await asyncio.wait_for(reader.read(nskip), timeout=TCP_TIMEOUT)
        assert read_bytes == write_bytes[-nskip:]

        write_bytes = b"data for readexactly"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(
            reader.readexactly(n=len(write_bytes)), timeout=TCP_TIMEOUT
        )
        assert read_bytes == write_bytes

        write_bytes = b"terminated data for readline\n"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(reader.readline(), timeout=TCP_TIMEOUT)
        assert read_bytes == write_bytes

        write_bytes = b"terminated data for readuntil" + tcpip.TERMINATOR
        await writer.write(write_bytes)
        read_bytes = await asyncio.wait_for(
            reader.readuntil(tcpip.TERMINATOR), timeout=TCP_TIMEOUT
        )
        assert read_bytes == write_bytes

        write_struct = ShortStruct(ushort_0=1, int64_0=2, double_0=3.3, float_0=4.4)
        read_struct = ShortStruct()
        await asyncio.wait_for(writer.write_from(write_struct), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(
            reader.read_into(read_struct), timeout=TCP_TIMEOUT
        )
        for field_name, c_type in read_struct._fields_:
            assert getattr(read_struct, field_name) == getattr(write_struct, field_name)

    async def test_basic_close(self) -> None:
        async with self.make_server() as server, self.make_client(server) as client:
            await self.assert_next_client_connected(True)

            await client.basic_close()
            assert not client.connected
            assert client.should_be_connected
            await self.assert_next_client_connected(False)
            with pytest.raises((asyncio.IncompleteReadError, ConnectionResetError)):
                await client.reader.readuntil(tcpip.TERMINATOR)

    async def test_close(self) -> None:
        """Test Client.close"""
        async with self.make_server() as server, self.make_client(server) as client:
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
        async with self.make_server() as server:
            assert not server.connected
            async with self.make_client(server) as client:
                assert client.connected
                assert server.connected
                with pytest.raises(asyncio.TimeoutError):
                    await self.assert_next_client_connected(True)
                await self.check_read_write_methods(reader=server, writer=client)
                await self.check_read_write_methods(reader=client, writer=server)

    async def test_initial_conditions(self) -> None:
        async with self.make_server(host=tcpip.LOCALHOST_IPV4) as server:
            assert server.port != 0
            async with self.make_client(server) as client:
                assert client.connected
                assert server.connected
                await self.assert_next_client_connected(True)

    async def test_read_write_methods(self) -> None:
        for localhost in (tcpip.LOCALHOST_IPV4, tcpip.LOCALHOST_IPV6):
            with self.subTest(localhost=localhost):
                try:
                    async with self.make_server(
                        host=localhost
                    ) as server, self.make_client(server) as client:
                        await self.check_read_write_methods(
                            reader=client, writer=server
                        )
                        await self.check_read_write_methods(
                            reader=server, writer=client
                        )
                except OSError:
                    if localhost == tcpip.LOCALHOST_IPV6:
                        raise unittest.SkipTest(
                            "The test framework does not support IPV6"
                        )
                    else:
                        raise

    async def test_server_drops_connection(self) -> None:
        async with self.make_server() as server, self.make_client(server) as client:
            await self.assert_next_client_connected(True)

            await server.close_client()
            await self.assert_next_client_connected(False)
            assert client.should_be_connected

    async def test_sync_connect_callback(self) -> None:
        """Make sure sync callbacks are rejected"""

        def sync_callback(_: typing.Any) -> None:
            pass

        async with self.make_server() as server:
            with pytest.raises(TypeError):
                tcpip.Client(
                    host=server.host,
                    port=server.port,
                    log=self.log,
                    connect_callback=sync_callback,
                )
