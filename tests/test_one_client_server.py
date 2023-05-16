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
import logging
import socket
import unittest

import pytest
from lsst.ts import tcpip  # type: ignore

# How long to wait for OneClientServer to detect
# that a client has connected (sec).
CONNECTED_TIMEOUT = 1

# Timeout to determine if a StreamReader is open (sec).
# Max time to wait for data (none is expected); this can be quite short.
IS_OPEN_TIMEOUT = 0.1

logging.basicConfig()


async def is_reader_open(reader: asyncio.StreamReader) -> bool:
    """Return True if a stream reader is open, else False.

    Parameters
    ----------
    reader : `asyncio.StreamReader`
        Stream reader.

    Raises
    ------
    `AssertionError`
        If the stream reader has unread data.
    """
    if reader.at_eof():  # unnecessary, but short-circuits the await read
        return False
    try:
        data = await asyncio.wait_for(reader.read(n=100), timeout=IS_OPEN_TIMEOUT)
    except (asyncio.IncompleteReadError, ConnectionError):
        return False
    except asyncio.TimeoutError:
        return True
    if data:
        raise AssertionError(f"Read {data=} when none expected")
    else:
        return False


class OneClientServerTestCase(tcpip.BaseOneClientServerTestCase):
    """Test OneClientServer and also BaseOneClientServerTestCase."""

    server_class = tcpip.OneClientServer

    def setUp(self) -> None:
        self.callbacks_raise: bool = False

    async def connect_callback(self, server: tcpip.OneClientServer) -> None:
        """This override of connect_callback raises RuntimeError
        if self.callbacks_raise is true.
        """
        if self.callbacks_raise:
            raise RuntimeError(
                "connect_callback raising because self.callbacks_raise is true"
            )
        await super().connect_callback(server)

    def sync_connect_callback(self, server: tcpip.OneClientServer) -> None:
        """A synchronous version of connect_callback.

        TODO DM-37477: drop this method argument when we remove support
        for synchronous connect_callback functions.
        """
        print(f"sync_connect_callback: connected={server.connected}")
        if self.connect_queue is None:
            raise RuntimeError("You must call create_server")
        if self.callbacks_raise:
            raise RuntimeError(
                "connect_callback raising because self.callbacks_raise is true"
            )
        self.connect_queue.put_nowait(server.connected)

    async def check_read_write(
        self, reader: tcpip.BaseClientOrServer, writer: tcpip.BaseClientOrServer
    ) -> None:
        # Check at least 2 writes and reads,
        # to detect extra characters being written.
        assert reader is not None
        assert writer is not None
        for i in range(2):
            write_str = f"some data to write {i}"
            await writer.write_str(write_str)
            read_str = await reader.read_str()
            assert read_str == write_str

    async def test_port_0_ambiguous(self) -> None:
        """Try to create a server that listens on two sockets: IP4 and IP6.

        Do this by specifying host=None, port=0, and family=AF_UNSPEC
        (the default). If successful then check that the port is 0.
        """
        server = tcpip.OneClientServer(
            host=None,
            port=0,
            log=self.log,
            family=socket.AF_UNSPEC,
        )
        try:
            assert server.port == 0
            await server.start_task
            if len(server._server.sockets) != 1:
                assert server.port == 0
            else:
                raise unittest.SkipTest(
                    "Only one socket created, so this test cannot run."
                )
        finally:
            await server.close()

    async def test_assert_next_connected_with_no_server(self) -> None:
        for connected in (False, True):
            with pytest.raises(RuntimeError):
                await self.assert_next_connected(connected)

    async def test_port_0_not_started(self) -> None:
        """Test server.port is 0 until server started, then nonzero."""
        server = tcpip.OneClientServer(
            port=0,
            log=self.log,
        )
        try:
            assert server.port == 0
            await server.start_task
            assert server.port != 0
        finally:
            await server.close()

    async def test_close_client(self) -> None:
        """Test OneClientServer.close_client"""
        async with self.create_server(
            connect_callback=self.connect_callback
        ) as server, self.create_client(server=server) as client:
            await self.assert_next_connected(True)
            # TODO DM-39202: remove these checks using deprecated properties.
            with pytest.warns(DeprecationWarning):
                assert server.reader is not None
            with pytest.warns(DeprecationWarning):
                assert server.writer is not None
            with pytest.warns(DeprecationWarning):
                assert server.server is not None

            await server.close_client()
            assert not server.connected
            # Closing the client should not set done_task done.
            assert not server.done_task.done()
            await self.assert_next_connected(False)
            # TODO DM-39202: remove these checks using deprecated properties.
            with pytest.warns(DeprecationWarning):
                assert server.writer is None
            with pytest.warns(DeprecationWarning):
                assert server.server is not None
            assert client._reader.at_eof()
            with pytest.raises((asyncio.IncompleteReadError, ConnectionError)):
                await client.readline()

            # Subsequent calls should have no effect
            await server.close_client()

    async def test_close(self) -> None:
        """Test OneClientServer.close"""
        async with self.create_server(
            connect_callback=self.connect_callback
        ) as server, self.create_client(server=server) as client:
            await self.assert_next_connected(True)
            assert not server.done_task.done()

            await server.close()
            assert not server.connected
            assert server.done_task.done()
            # TODO DM-39202: remove these checks using deprecated properties.
            with pytest.warns(DeprecationWarning):
                assert server.writer is None
            with pytest.warns(DeprecationWarning):
                assert server.server is None
            await self.assert_next_connected(False)
            with pytest.raises((asyncio.IncompleteReadError, ConnectionError)):
                await client.readline()

            # Subsequent calls should have no effect
            await server.close_client()
            await server.close()

    async def test_connect_callback_raises(self) -> None:
        self.callbacks_raise = True
        async with self.create_server(connect_callback=self.connect_callback) as server:
            assert not server.connected
            assert self.connect_queue.empty()
            async with self.create_client(server=server) as client:
                assert server.connected
                assert server._writer is not None
                with pytest.raises(asyncio.TimeoutError):
                    await self.assert_next_connected(True)
                await self.check_read_write(reader=server, writer=client)
                await self.check_read_write(reader=client, writer=server)

    async def test_initial_conditions(self) -> None:
        async with self.create_server(connect_callback=self.connect_callback) as server:
            assert not server.connected
            assert self.connect_queue.empty()
            assert server.port != 0
            async with self.create_client(server=server):
                assert server.connected
                await self.assert_next_connected(True)

    async def test_only_one_client(self) -> None:
        async with self.create_server(
            connect_callback=self.connect_callback
        ) as server, self.create_client(server=server) as client:
            await self.assert_next_connected(True)
            await self.check_read_write(reader=client, writer=server)
            await self.check_read_write(reader=server, writer=client)

            # Create another client connection and check that it cannot read;
            # note that the client writer gives no hint of problems.
            try:
                bad_reader, bad_writer = await asyncio.open_connection(
                    host=server.host, port=server.port
                )
                read_data = await bad_reader.readline()
                assert read_data == b""
            finally:
                await tcpip.close_stream_writer(bad_writer)

            await self.check_read_write(reader=client, writer=server)
            await self.check_read_write(reader=server, writer=client)

    async def test_reconnect(self) -> None:
        async with self.create_server(connect_callback=self.connect_callback) as server:
            async with self.create_client(server, wait_connected=False):
                await self.assert_next_connected(True)

            # Reconnect as quickly as possible, to make sure
            # we can reconnect before the monitoring loop notices
            # that the client has disconnected.
            # (Leaving the create_client context closes the previous client).
            async with self.create_client(server, wait_connected=False) as client:
                await self.assert_next_connected(False)
                await self.assert_next_connected(True)
                await self.check_read_write(reader=client, writer=server)
                await self.check_read_write(reader=server, writer=client)

                # Give the monitor plenty of time to run and make sure
                # it has not called the connection_callback.
                await asyncio.sleep(server.monitor_connection_interval * 5)
                assert self.connect_queue.empty()

            # Test reconnect after connection monitor notices.
            # (Leaving the create_client context closes the previous client).
            await self.assert_next_connected(False)
            async with self.create_client(server=server) as client:
                await self.assert_next_connected(True)
                await self.check_read_write(reader=client, writer=server)
                await self.check_read_write(reader=server, writer=client)

    async def test_read_write(self) -> None:
        for localhost in (tcpip.LOCALHOST_IPV4, tcpip.LOCALHOST_IPV6):
            with self.subTest(localhost=localhost):
                try:
                    async with self.create_server(
                        host=localhost
                    ) as server, self.create_client(server) as client:
                        await self.check_read_write(reader=client, writer=server)
                        await self.check_read_write(reader=server, writer=client)
                except OSError:
                    if localhost == tcpip.LOCALHOST_IPV6:
                        raise unittest.SkipTest(
                            "The test framework does not support IPV6"
                        )
                    else:
                        raise

    # TODO DM-37477: modify this test to expect a TypeError (and construct
    # the OneClientServer directly, instead of calling create_server)
    # once we drop support for sync connect_callback
    async def test_sync_connect_callback(self) -> None:
        with pytest.warns(DeprecationWarning):
            async with self.create_server(
                connect_callback=self.sync_connect_callback
            ) as server, self.create_client(server):
                await self.assert_next_connected(True)

    async def test_simultaneous_clients(self) -> None:
        """Test several clients connecting at the same time.

        One should connect and the others should be disconnected.
        """
        num_clients = 5
        async with self.create_server(host=tcpip.LOCALHOST_IPV4) as server:

            async def open_connection() -> tuple[
                asyncio.StreamReader, asyncio.StreamWriter
            ]:
                """Open a client connection to ``server``.

                Returns
                -------
                reader_writer : `tuple`[`asyncio.StreamReader`,
                        `asyncio.StreamWriter`]
                    Stream reader and writer.
                """
                return await asyncio.open_connection(host=server.host, port=server.port)

            tasks = [asyncio.create_task(open_connection()) for _ in range(num_clients)]
            await asyncio.wait_for(server.connected_task, timeout=CONNECTED_TIMEOUT)
            for task in tasks:
                assert task.done()
                writers = [task.result()[1] for task in tasks]
            try:
                readers = [task.result()[0] for task in tasks]
                is_open = [await is_reader_open(reader) for reader in reversed(readers)]
                assert len([True for open in is_open if open]) == 1
            finally:
                for writer in writers:
                    await tcpip.close_stream_writer(writer)
