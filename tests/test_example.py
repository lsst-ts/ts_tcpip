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


class EchoServer(tcpip.OneClientReadLoopServer):
    """A trivial echo server.

    Intended as an example for using `OneClientReadLoopServer`,
    so it only serves one client at a time.

    To use:

    * Construct the server. The constructor arguments are the same as
      `OneClientReadLoopServer`.
    * await server.start_task
    * Construct a client
    * await client.start_task and server.connected_task, in either order.
    * Write data to the client and read the echoed data from it.
    * Close the server and client, in either order.

    Parameters
    ----------
    log : `logging.Logger`
        A logger.
    port : `int`
        The port; use 0 to pick a random free port.
    """

    async def read_and_dispatch(self) -> None:
        data = await self.read_str()
        await self.write_str(data)


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

        server = EchoServer(port=0, log=log)
        await server.start_task

        client = tcpip.Client(
            host=server.host,
            port=server.port,
            log=server.log,
        )
        await client.start_task
        await server.connected_task

        for write_str in ("some data", "more data", "yet more data"):
            await asyncio.wait_for(client.write_str(write_str), timeout=TCP_TIMEOUT)
            read_str = await asyncio.wait_for(client.read_str(), timeout=TCP_TIMEOUT)
            assert read_str == write_str

        await client.close()
        await server.close()
