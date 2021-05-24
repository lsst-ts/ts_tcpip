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
import typing
import unittest

from lsst.ts import tcpip  # type: ignore

# Standard timeout for TCP/IP messages (sec).
TCP_TIMEOUT = 1

logging.basicConfig()


class OneClientServerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Set True to make self.connect_callback raise an exception
        self.callbacks_raise: bool = False

        # Queue of connected values; filled by self.connected_callback
        self.connect_queue: asyncio.Queue = asyncio.Queue()

        log = logging.getLogger()
        log.setLevel(logging.INFO)

        self.reader: typing.Optional[asyncio.StreamReader] = None
        self.writer: typing.Optional[asyncio.StreamWriter] = None
        self.server = tcpip.OneClientServer(
            host=tcpip.LOCAL_HOST,
            port=0,
            name="test",
            log=log,
            connect_callback=self.connect_callback,
        )
        await self.server.start_task

    async def ascynTearDown(self) -> None:
        if self.writer is not None:
            await tcpip.close_stream_writer(self.writer)
        await self.server.close()

    async def make_client(self):
        """Make a TCP/IP client and wait for it to connect.

        Set attributes self.reader and self.writer.
        """
        (self.reader, self.writer) = await asyncio.open_connection(
            host=tcpip.LOCAL_HOST, port=self.server.port
        )
        self.assertTrue(self.server.connected)

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

    async def check_read_write(self) -> None:
        # Check at least 2 writes and reads,
        # to detect extra characters being written.
        for i in range(2):
            data1_text = f"some data to write {i}"
            data1_bytes = data1_text.encode() + tcpip.TERMINATOR
            assert self.reader is not None
            assert self.writer is not None
            assert self.server.reader is not None
            assert self.server.writer is not None
            self.writer.write(data1_bytes)
            await self.writer.drain()
            read_data1_bytes = await self.server.reader.readuntil(tcpip.TERMINATOR)
            self.assertEqual(data1_bytes, read_data1_bytes)

            data2_text = f"different data {i}"
            data2_bytes = data2_text.encode() + tcpip.TERMINATOR
            self.server.writer.write(data2_bytes)
            await self.server.writer.drain()
            read_data2_bytes = await self.reader.readuntil(tcpip.TERMINATOR)
            self.assertEqual(data2_bytes, read_data2_bytes)

    async def test_close_client(self) -> None:
        await self.make_client()
        await self.assert_next_connected(True)

        await self.server.close_client()
        self.assertIsNone(self.server.writer)
        self.assertFalse(self.server.connected)
        await self.assert_next_connected(False)
        assert self.reader is not None
        with self.assertRaises(asyncio.exceptions.IncompleteReadError):
            await self.reader.readuntil(tcpip.TERMINATOR)

        # Subsequent calls should have no effect
        await self.server.close_client()

    async def test_close(self) -> None:
        await self.make_client()
        await self.assert_next_connected(True)

        await self.server.close()
        self.assertIsNone(self.server.writer)
        self.assertFalse(self.server.connected)
        await self.assert_next_connected(False)
        assert self.reader is not None
        with self.assertRaises(asyncio.exceptions.IncompleteReadError):
            await self.reader.readuntil(tcpip.TERMINATOR)

        # Subsequent calls should have no effect
        await self.server.close_client()
        await self.server.close()

    async def test_connect_callback_raises(self) -> None:
        self.callbacks_raise = True
        self.assertFalse(self.server.connected)
        self.assertTrue(self.connect_queue.empty())
        await self.make_client()
        self.assertTrue(self.server.connected)
        self.assertIsNotNone(self.server.writer)
        with self.assertRaises(asyncio.TimeoutError):
            await self.assert_next_connected(True)
        await self.check_read_write()

    async def test_initial_conditions(self) -> None:
        self.assertFalse(self.server.connected)
        self.assertTrue(self.connect_queue.empty())
        await self.make_client()
        self.assertTrue(self.server.connected)
        await self.assert_next_connected(True)

    async def test_only_one_client(self) -> None:
        await self.make_client()
        await self.check_read_write()

        # Create another client connection and check that it cannot read;
        # note that the client writer gives no hint of problems.
        try:
            reader, writer = await asyncio.open_connection(
                host=tcpip.LOCAL_HOST, port=self.server.port
            )
            with self.assertRaises(asyncio.exceptions.IncompleteReadError):
                await reader.readuntil(tcpip.TERMINATOR)
        finally:
            await tcpip.close_stream_writer(writer)

        await self.check_read_write()

    async def test_read_write(self) -> None:
        await self.make_client()
        await self.check_read_write()


if __name__ == "__main__":
    unittest.main()
