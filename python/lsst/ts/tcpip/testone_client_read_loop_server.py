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
from typing import Any

from .base_client_or_server import ConnectCallbackType
from .one_client_read_loop_server import OneClientReadLoopServer

__all__ = ["TestOneClientReadLoopServer"]


class TestOneClientReadLoopServer(OneClientReadLoopServer):
    """A simple implementation of OneClientReadLoopServer for unit tests.

    Parameters
    ----------
    host : `str` or `None`
        IP address for this server; typically `LOCALHOST` to get
        the default version of IP, or `LOCALHOST_IPV4` for IPV4,
        or `LOCALHOST_IPV6` for IPV6.
        If `None` then bind to all network interfaces
        (e.g. listen on an IPv4 socket and an IPv6 socket).
        Warning: `None` can cause trouble with ``port=0``; see ``port``
        in the `OneClientServer` Attributes section for more information.
    port : `int`
        IP port for this server. If 0 then randomly pick an available port
        (or ports, if listening on multiple sockets).
        0 is strongly recommended for unit tests.
    log : `logging.Logger`
        Logger.
    connect_callback : callable or `None`, optional
        Asynchronous or (deprecated) synchronous function to call when
        when a client connects or disconnects.
        If the other end (client) closes the connection, it may take
        ``monitor_connection_interval`` seconds or longer to notice.
        The function receives one argument: this `OneClientServer`.
    name : `str`, optional
        Name used for log messages, e.g. "Commands" or "Telemetry".
    **kwargs : `dict` [`str`, `typing.Any`]
        Additional keyword arguments for `asyncio.start_server`,
        beyond host and port.
    """

    def __init__(
        self,
        host: str | None,
        port: int | None,
        log: logging.Logger,
        connect_callback: ConnectCallbackType | None = None,
        name: str = "",
        **kwargs: Any,
    ) -> None:
        log = logging.getLogger()
        super().__init__(
            host=host,
            port=port,
            log=log,
            connect_callback=connect_callback,
            name=name,
            **kwargs,
        )

        self._data_queue: asyncio.Queue = asyncio.Queue()

        # A boolean to make the next read fail or not. This is used by unit
        # tests to mock connection errors.
        self.fail_next_read = False

    async def read_and_dispatch(self) -> None:
        if self.fail_next_read:
            self.fail_next_read = False
            raise ConnectionError("Mock connection error for unit tests.")
        data = await self.read_str()
        await self._data_queue.put(data)

    async def get_next_data(self) -> str:
        """Get the next data.

        Under the hood a FIFO queue is used so the oldest data gets returned.

        Returns
        -------
        str :
            The next data.
        """
        return await self._data_queue.get()
