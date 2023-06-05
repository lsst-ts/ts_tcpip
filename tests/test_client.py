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
import ctypes
import itertools
import json
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


class ClientTestCase(tcpip.BaseOneClientServerTestCase):
    server_class = tcpip.OneClientServer

    async def check_read_write_not_connected(self, client: tcpip.Client) -> None:
        """Check that all read and write Client methods raise
        ConnectionError if not connected.
        """
        assert not client.connected

        struct = ShortStruct()
        with pytest.raises(ConnectionError):
            await client.read_json()
        with pytest.raises(ConnectionError):
            await client.read_str()
        with pytest.raises(ConnectionError):
            await client.read(1)
        with pytest.raises(ConnectionError):
            await client.readexactly(1)
        with pytest.raises(ConnectionError):
            await client.readline()
        with pytest.raises(ConnectionError):
            await client.readuntil(b"\n")
        with pytest.raises(ConnectionError):
            await client.read_into(struct)
        with pytest.raises(ConnectionError):
            await client.write(b"\n")
        with pytest.raises(ConnectionError):
            await client.write_from(struct)
        with pytest.raises(ConnectionError):
            await client.writelines([b" ", b"\n"])

        # Check that StreamReader.readline reads 0 bytes if disconnected
        assert (
            await asyncio.wait_for(client._reader.readline(), timeout=TCP_TIMEOUT)
            == b""
        )

    async def assert_next_connected(
        self, connected: bool, timeout: int = TCP_TIMEOUT
    ) -> None:
        """Assert results of next connect_callback.

        Parameters
        ----------
        connected : `bool`
            Is a client connected to the client connected?
        timeout : `float`
            Time to wait for connect_callback (seconds).
        """
        next_connected = await asyncio.wait_for(
            self.connect_queue.get(), timeout=timeout
        )
        assert connected == next_connected

    async def check_read_write_methods(
        self, reader: tcpip.BaseClientOrServer, writer: tcpip.BaseClientOrServer
    ) -> None:
        """Check read and write methods by writing from one client or server
        and reading from the opposite.

        Parameters
        ----------
        reader : `tcpip.BaseClientOrServer`
            Server or client.
        writer : `tcpip.BaseClientOrServer`
            Client (if reader is a server) or server (if reader is a client).
        """
        write_bytes = b"data with unicode \xf0\x9f\x98\x80 for read with n=len"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(
            reader.read(n=len(write_bytes)), timeout=TCP_TIMEOUT
        )
        assert read_bytes == write_bytes

        nextra = 5  # extra bytes to wait for; an arbitrary positive value
        write_bytes = b"data with unicode \xf0\x9f\x98\x80 for read with n>len"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(
            reader.read(n=len(write_bytes) + nextra), timeout=TCP_TIMEOUT
        )
        assert read_bytes == write_bytes

        nskip = 5  # arbitrary positive value smaller than the data len
        write_bytes = b"data with unicode \xf0\x9f\x98\x80 for read with n<len"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(
            reader.read(n=len(write_bytes) - nskip), timeout=TCP_TIMEOUT
        )
        assert read_bytes == write_bytes[0:-nskip]
        read_bytes = await asyncio.wait_for(reader.read(nskip), timeout=TCP_TIMEOUT)
        assert read_bytes == write_bytes[-nskip:]

        write_bytes = b"data with unicode \xf0\x9f\x98\x80 for readexactly"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(
            reader.readexactly(n=len(write_bytes)), timeout=TCP_TIMEOUT
        )
        assert read_bytes == write_bytes

        write_bytes = b"terminated data with unicode \xf0\x9f\x98\x80 for readline\n"
        await asyncio.wait_for(writer.write(write_bytes), timeout=TCP_TIMEOUT)
        read_bytes = await asyncio.wait_for(reader.readline(), timeout=TCP_TIMEOUT)
        assert read_bytes == write_bytes

        write_bytes = (
            b"terminated data with unicode \xf0\x9f\x98\x80 for readuntil"
            + tcpip.DEFAULT_TERMINATOR
        )
        await writer.write(write_bytes)
        read_bytes = await asyncio.wait_for(
            reader.readuntil(tcpip.DEFAULT_TERMINATOR), timeout=TCP_TIMEOUT
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

        assert reader.encoding == writer.encoding
        assert reader.terminator == writer.terminator
        initial_encoding = reader.encoding
        initial_terminator = reader.terminator

        try:
            for encoding, terminator in itertools.product(
                ("utf-8", "utf-16", "utf-32"),
                (b"\r\n", b"\n", b"\n\r", b"XYZZY"),
            ):
                with self.subTest(encoding=encoding, terminator=terminator):
                    reader.encoding = encoding
                    reader.terminator = terminator
                    writer.encoding = encoding
                    writer.terminator = terminator

                    write_str = "data with unicode \U0001F600 for read_str"
                    await writer.write_str(write_str)
                    read_str = await asyncio.wait_for(
                        reader.read_str(), timeout=TCP_TIMEOUT
                    )
                    assert read_str == write_str

                    # Make sure the reader and writer are truly using
                    # the desired encoding and terminator.
                    write_bytes = write_str.encode(encoding) + terminator
                    await writer.write(write_bytes)
                    read_str = await asyncio.wait_for(
                        reader.read_str(), timeout=TCP_TIMEOUT
                    )
                    assert read_str == write_str

                    await writer.write_str(write_str)
                    read_bytes = await asyncio.wait_for(
                        reader.readuntil(terminator), timeout=TCP_TIMEOUT
                    )
                    assert read_bytes == write_bytes

                    write_json = {"msg": "data with unicode \U0001F600 for read_json"}
                    await writer.write_json(write_json)
                    read_json = await asyncio.wait_for(
                        reader.read_json(), timeout=TCP_TIMEOUT
                    )
                    assert read_json == write_json
        finally:
            reader.encoding = initial_encoding
            writer.encoding = initial_encoding
            reader.terminator = initial_terminator
            writer.terminator = initial_terminator

    async def test_basic_close(self) -> None:
        async with self.create_server() as server, self.create_client(
            server, connect_callback=self.connect_callback
        ) as client:
            await self.assert_next_connected(True)
            assert not client.done_task.done()

            await asyncio.wait_for(client.basic_close(), timeout=TCP_TIMEOUT)
            assert not client.connected
            assert client.should_be_connected
            assert client.done_task.done()
            await self.assert_next_connected(False)
            await self.check_read_write_not_connected(client)

    async def test_close(self) -> None:
        """Test Client.close"""
        async with self.create_server() as server, self.create_client(
            server, connect_callback=self.connect_callback
        ) as client:
            await self.assert_next_connected(True)
            assert not client.done_task.done()
            # TODO DM-39202: remove these checks using deprecated properties.
            with pytest.warns(DeprecationWarning):
                assert client.reader is not None
            with pytest.warns(DeprecationWarning):
                assert client.writer is not None

            await asyncio.wait_for(client.close(), timeout=TCP_TIMEOUT)
            assert not client.connected
            assert not client.should_be_connected
            assert client.done_task.done()
            # TODO DM-39202: remove these checks using deprecated properties.
            with pytest.warns(DeprecationWarning):
                assert client.writer is None
            await self.assert_next_connected(False)
            await self.check_read_write_not_connected(client)

            # Subsequent calls should have no effect
            await asyncio.wait_for(client.close(), timeout=TCP_TIMEOUT)

    async def test_connect_callback_raises(self) -> None:
        self.connect_callback_raises = True
        async with self.create_server() as server:
            assert not server.connected
            async with self.create_client(server) as client:
                assert client.connected
                assert server.connected
                with pytest.raises(asyncio.TimeoutError):
                    await self.assert_next_connected(True)
                await self.check_read_write_methods(reader=server, writer=client)
                await self.check_read_write_methods(reader=client, writer=server)

    async def test_create_done_client(self) -> None:
        client = tcpip.Client(host="", port=0, log=self.log)
        assert client.start_task.done()
        assert client.done_task.done()
        assert not client.connected
        assert not client.should_be_connected
        await client.close()

    async def test_initial_conditions(self) -> None:
        async with self.create_server(host=tcpip.LOCALHOST_IPV4) as server:
            assert server.port != 0
            async with self.create_client(
                server, connect_callback=self.connect_callback
            ) as client:
                assert client.connected
                assert server.connected
                await self.assert_next_connected(True)

    async def test_read_write_methods(self) -> None:
        for localhost in (tcpip.LOCALHOST_IPV4, tcpip.LOCALHOST_IPV6):
            with self.subTest(localhost=localhost):
                try:
                    async with self.create_server(
                        host=localhost
                    ) as server, self.create_client(server) as client:
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

    async def test_read_json_exception(self) -> None:
        """Test that read_json's decoding exception includes the bad data."""
        invalid_json_data = "not valid json"
        async with self.create_server() as server, self.create_client(server) as client:
            await client.write_str(invalid_json_data)
            with pytest.raises(json.JSONDecodeError, match=invalid_json_data):
                await server.read_json()

    async def test_server_drops_connection(self) -> None:
        async with self.create_server() as server, self.create_client(
            server, connect_callback=self.connect_callback
        ) as client:
            await self.assert_next_connected(True)

            await asyncio.wait_for(server.close_client(), timeout=TCP_TIMEOUT)
            await self.assert_next_connected(False)
            assert client.should_be_connected

    async def test_sync_connect_callback(self) -> None:
        """Make sure sync callbacks are rejected"""

        def sync_callback(_: typing.Any) -> None:
            pass

        async with self.create_server() as server:
            with pytest.raises(TypeError):
                async with self.create_client(server, connect_callback=sync_callback):
                    pass

    async def test_encodings_and_terminators(self) -> None:
        """Test encoding and terminator constructor arguments.

        The actual encoding and decoding is tested in check_read_write_methods.
        """
        async with self.create_server() as server:
            for good_encoding in ("utf-8", "utf_8", "utf-16", "UTF-32"):
                async with self.create_client(server, encoding=good_encoding) as client:
                    assert client.encoding == good_encoding

            for good_terminator in (b"\r\n", b"\r", b"any bytes"):
                async with self.create_client(
                    server, terminator=good_terminator
                ) as client:
                    assert client.terminator == good_terminator

            for bad_encoding in ("no_such_encoder", b"utf_8"):
                with pytest.raises(ValueError):
                    async with self.create_client(server, encoding=bad_encoding):
                        pass

            for bad_terminator in ("\r\n", "any str"):
                with pytest.raises(ValueError):
                    async with self.create_client(server, terminator=bad_terminator):
                        pass
