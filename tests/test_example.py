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
import unittest

from lsst.ts import tcpip  # type: ignore

# Standard timeout for TCP/IP messages (sec).
TCP_TIMEOUT = 1


class EchoServer(tcpip.OneClientServer):
    """A trivial echo server for data terminated with ``tcpip.TERMINATOR``.

    Intended as an example for using `OneClientServer`,
    so it only serves one client at a time.

    To use:

    * Construct the server
    * await server.start_task
    * Construct a client
    * await client.start_task and server.connected_task, in either order.
    * Write data to the client and read the echoed data from it.
    * Close the server and client, in either order.

    Parameters
    ----------
    host : `str`
        The host; typically ``tcpip.LOCALHOST_IPV4`` (the default)
        or ``tcpip.LOCALHOST_IPV6``.
    port : `int`
        The port; use 0 to pick a random free port.
    """

    def __init__(self, host: str, port: int, log: logging.Logger) -> None:
        self.read_loop_task: asyncio.Future = asyncio.Future()
        super().__init__(
            host=host,
            port=port,
            log=log,
            connect_callback=self.connect_callback,
        )

    async def connect_callback(self, server: tcpip.OneClientServer) -> None:
        """Called when a client connects or disconnects."""
        self.read_loop_task.cancel()
        if server.connected:
            self.read_loop_task = asyncio.create_task(self.read_loop())

    async def close_client(self) -> None:
        """Override close_client to also cancel the read loop.

        This makes for a cleaner shutdown.
        """
        self.read_loop_task.cancel()
        await super().close_client()

    async def read_loop(self) -> None:
        """Read and echo data terminated with tcpip.TERMINATOR."""
        self.log.info("Read loop begins")
        try:
            while self.connected:
                data = await self.readuntil(tcpip.TERMINATOR)
                self.log.info(f"Read loop read {data!r}")
                await self.write(data)
            self.log.info("Read loop ends; no client connected")
        except asyncio.CancelledError:
            # This is the usual end if the server writer is closed.
            self.log.info("Read loop cancelled")
        except asyncio.IncompleteReadError:
            # This is the usual end if the client writer is closed.
            self.log.info("Read loop ends: the other end hung up")
        except Exception:
            self.log.exception("Read loop fails")


def configure_log(log: logging.Logger) -> None:
    """Make the log have just one stream handler and use level INFO.

    Another option is logging.basicConfig, but that was not working
    for me on my mac.
    """
    log.level = logging.INFO
    while log.handlers:
        log.removeHandler(log.handlers[-1])
    log.addHandler(logging.StreamHandler())


class ExampleTestCase(unittest.IsolatedAsyncioTestCase):
    """This exists as an example of how to use Client, OneClientServer.

    It is written as a unit test in order to avoid bit rot.
    """

    async def test_echo_server(self) -> None:
        log = logging.getLogger()
        configure_log(log)

        server = EchoServer(host=tcpip.LOCALHOST_IPV4, port=0, log=log)
        await server.start_task

        client = tcpip.Client(
            host=server.host,
            port=server.port,
            log=server.log,
        )
        await client.start_task
        await server.connected_task

        for write_str in ("some data", "more data", "yet more data"):
            write_bytes = write_str.encode() + tcpip.TERMINATOR
            await asyncio.wait_for(client.write(write_bytes), timeout=TCP_TIMEOUT)
            read_bytes = await asyncio.wait_for(
                client.readuntil(tcpip.TERMINATOR), timeout=TCP_TIMEOUT
            )
            assert read_bytes == write_bytes

        await client.close()
        await server.close()
