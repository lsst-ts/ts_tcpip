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
import socket
import typing
import unittest

from lsst.ts import tcpip  # type: ignore

# Standard timeout for TCP/IP messages (sec).
TCP_TIMEOUT = 1

logging.basicConfig()


class OneClientServerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.callbacks_raise: bool = False
        self.connect_queue: asyncio.Queue = asyncio.Queue()
        self.log = logging.getLogger()

    @contextlib.asynccontextmanager
    async def make_server(
        self, host, family=socket.AF_UNSPEC
    ) -> typing.AsyncGenerator[tcpip.OneClientServer, None]:
        # Reset connect_queue so we can call make_server multiple times
        # in one unit test.
        self.connect_queue = asyncio.Queue()
        server = tcpip.OneClientServer(
            host=host,
            port=0,
            name="test",
            log=self.log,
            family=family,
            connect_callback=self.connect_callback,
        )
        await server.start_task
        try:
            yield server
        finally:
            await server.close()

    @contextlib.asynccontextmanager
    async def make_client(
        self, server
    ) -> typing.AsyncGenerator[
        typing.Tuple[asyncio.StreamReader, asyncio.StreamWriter], None
    ]:
        """Make a TCP/IP client that talks to the server and wait for it to
        connect.

        Returns (reader, writer).
        """
        (reader, writer) = await asyncio.open_connection(
            host=server.host, port=server.port, family=server.family
        )
        try:
            yield (reader, writer)
        finally:
            writer.close()
            await writer.wait_closed()

    def connect_callback(self, server):
        print(f"connect_callback: connected={server.connected}")
        if self.callbacks_raise:
            raise RuntimeError(
                "connect_callback raising because self.callbacks_raise is true"
            )
        self.connect_queue.put_nowait(server.connected)

    async def assert_next_connected(self, connected, timeout=TCP_TIMEOUT):
        """Assert results of next connect_callback.

        Parameters
        ----------
        connected : `bool`
            Is a client connected to the server connected?
        timeout : `float`
            Time to wait for connect_callback (seconds).
        """
        next_connected = await asyncio.wait_for(
            self.connect_queue.get(), timeout=timeout
        )
        self.assertEqual(connected, next_connected)

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
            self.assertEqual(data_bytes, read_data_bytes)

    async def test_port_0_ambiguous(self) -> None:
        """Try to create a server that listens on two sockets: IP4 and IP6.

        Do this by specifying host=None, port=0, and family=AF_UNSPEC
        (the default). If successful then check that the port is 0.
        """
        server = tcpip.OneClientServer(
            host=None,
            port=0,
            name="test",
            log=self.log,
            connect_callback=None,
            family=socket.AF_UNSPEC,
        )
        try:
            self.assertEqual(server.port, 0)
            await server.start_task
            if len(server.server.sockets) != 1:
                self.assertEqual(server.port, 0)
            else:
                raise unittest.SkipTest(
                    "Only one socket created, so this test cannot run."
                )
        finally:
            await server.close()

    async def test_port_0_not_started(self) -> None:
        """Test server.port is 0 until server started, then nonzero."""
        server = tcpip.OneClientServer(
            host=tcpip.LOCAL_HOST,
            port=0,
            name="test",
            log=self.log,
            connect_callback=None,
        )
        try:
            self.assertEqual(server.port, 0)
            await server.start_task
            self.assertNotEqual(server.port, 0)
        finally:
            await server.close()

    async def test_close_client(self) -> None:
        """Test OneClientServer.close_client"""
        async with self.make_server(host=tcpip.LOCAL_HOST) as server, self.make_client(
            server
        ) as (
            reader,
            writer,
        ):
            await self.assert_next_connected(True)

            await server.close_client()
            self.assertFalse(server.connected)
            await self.assert_next_connected(False)
            assert reader.at_eof()
            with self.assertRaises((asyncio.IncompleteReadError, ConnectionResetError)):
                await reader.readuntil(tcpip.TERMINATOR)

            # Subsequent calls should have no effect
            await server.close_client()

    async def test_close(self) -> None:
        """Test OneClientServer.close"""
        async with self.make_server(host=tcpip.LOCAL_HOST) as server, self.make_client(
            server
        ) as (
            reader,
            writer,
        ):
            await self.assert_next_connected(True)

            await server.close()
            self.assertFalse(server.connected)
            await self.assert_next_connected(False)
            with self.assertRaises((asyncio.IncompleteReadError, ConnectionResetError)):
                await reader.readuntil(tcpip.TERMINATOR)

            # Subsequent calls should have no effect
            await server.close_client()
            await server.close()

    async def test_connect_callback_raises(self) -> None:
        self.callbacks_raise = True
        async with self.make_server(host=tcpip.LOCAL_HOST) as server:
            self.assertFalse(server.connected)
            self.assertTrue(self.connect_queue.empty())
            async with self.make_client(server) as (
                reader,
                writer,
            ):
                self.assertTrue(server.connected)
                self.assertIsNotNone(server.writer)
                with self.assertRaises(asyncio.TimeoutError):
                    await self.assert_next_connected(True)
                await self.check_read_write(reader=server.reader, writer=writer)
                await self.check_read_write(reader=reader, writer=server.writer)

    async def test_initial_conditions(self) -> None:
        for family in (socket.AF_INET, socket.AF_UNSPEC):
            async with self.make_server(host=tcpip.LOCAL_HOST) as server:
                self.assertFalse(server.connected)
                self.assertTrue(self.connect_queue.empty())
                self.assertNotEqual(server.port, 0)
                async with self.make_client(server) as (
                    reader,
                    writer,
                ):
                    self.assertTrue(server.connected)
                    await self.assert_next_connected(True)

    async def test_only_one_client(self) -> None:
        async with self.make_server(host=tcpip.LOCAL_HOST) as server, self.make_client(
            server
        ) as (
            reader,
            writer,
        ):
            await self.assert_next_connected(True)
            await self.check_read_write(reader=reader, writer=server.writer)
            await self.check_read_write(reader=server.reader, writer=writer)

            # Create another client connection and check that it cannot read;
            # note that the client writer gives no hint of problems.
            try:
                bad_reader, bad_writer = await asyncio.open_connection(
                    host=server.host, port=server.port
                )
                with self.assertRaises(
                    (asyncio.IncompleteReadError, ConnectionResetError)
                ):
                    await bad_reader.readuntil(tcpip.TERMINATOR)
            finally:
                await tcpip.close_stream_writer(bad_writer)

            await self.check_read_write(reader=reader, writer=server.writer)
            await self.check_read_write(reader=server.reader, writer=writer)

    async def test_reconnect(self) -> None:
        async with self.make_server(host=tcpip.LOCAL_HOST) as server:
            async with self.make_client(server):
                await self.assert_next_connected(True)

            # Reconnect as quickly as possible, to make sure
            # we can reconnect before the monitoring loop notices
            # that the client has disconnected.
            # (Leaving the make_client context closes the previous client).
            async with self.make_client(server) as (reader, writer):
                await self.assert_next_connected(False)
                await self.assert_next_connected(True)
                await self.check_read_write(reader=reader, writer=server.writer)
                await self.check_read_write(reader=server.reader, writer=writer)

                # Give the monitor plenty of time to run and make sure
                # it has not called the connection_callback.
                await asyncio.sleep(server._monitor_connection_interval * 5)
                assert self.connect_queue.empty()

            # Test reconnect after connection monitor notices.
            # (Leaving the make_client context closes the previous client).
            await self.assert_next_connected(False)
            async with self.make_client(server) as (reader, writer):
                await self.assert_next_connected(True)
                await self.check_read_write(reader=reader, writer=server.writer)
                await self.check_read_write(reader=server.reader, writer=writer)

    async def test_read_write(self) -> None:
        for family in (socket.AF_INET, socket.AF_UNSPEC):
            async with self.make_server(
                host=tcpip.LOCAL_HOST, family=family
            ) as server, self.make_client(server) as (
                reader,
                writer,
            ):
                await self.check_read_write(reader=reader, writer=server.writer)
                await self.check_read_write(reader=server.reader, writer=writer)


if __name__ == "__main__":
    unittest.main()
