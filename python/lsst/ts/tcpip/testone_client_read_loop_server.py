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
from .constants import (
    DEFAULT_ENCODING,
    DEFAULT_LOCALHOST,
    DEFAULT_TERMINATOR,
    HEARTBEAT,
)
from .one_client_read_loop_server import (
    DEFAULT_MAX_HEARTBEAT_INTERVAL,
    OneClientReadLoopServer,
)

__all__ = ["TestOneClientReadLoopServer"]


class TestOneClientReadLoopServer(OneClientReadLoopServer):
    """A simple implementation of OneClientReadLoopServer for unit tests.

    Parameters
    ----------
    port : `int`
        IP port for this server. If 0 then randomly pick an available port
        (or ports, if listening on multiple sockets).
        0 is strongly recommended for unit tests.
    host : `str` or `None`
        IP address for this server. The default is `DEFAULT_LOCALHOST`.
        Specify `LOCALHOST_IPV4` to force IPV4 or `LOCALHOST_IPV6` for IPV6.
        If `None` then bind to all network interfaces
        (e.g. listen on an IPv4 socket and an IPv6 socket).
        Warning: `None` can cause trouble with ``port=0``; see ``port``
        in the Attributes section for more information.
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
    encoding : `str`
        The encoding used by `read_str` and `write_str`, `read_json`,
         and `write_json`.
    terminator : `bytes`
        The terminator used by `read_str` and `write_str`, `read_json`,
         and `write_json`.
    run_heartbeat_monitor_task : `float`
        Should the task to monitor heartbeats be started or not? The default
        is False because the OneClientReadLoopServer delegates reading data
        from the socket to subclasses and by default sending heartbeats would
        be a breaking change.
    max_heartbeat_interval : `float`
        The max time [sec] between heartbeatsbefore the connection is assumed
        to have dropped. The default is `DEFAULT_MAX_HEARTBEAT_INTERVAL` sec.
    **kwargs : `dict` [`str`, `typing.Any`]
        Additional keyword arguments for `asyncio.start_server`,
        beyond host and port.
    """

    def __init__(
        self,
        *,
        port: int | None,
        host: str | None = DEFAULT_LOCALHOST,
        log: logging.Logger,
        connect_callback: ConnectCallbackType | None = None,
        name: str = "",
        encoding: str = DEFAULT_ENCODING,
        terminator: bytes = DEFAULT_TERMINATOR,
        run_heartbeat_monitor_task: bool = False,
        max_heartbeat_interval: float = DEFAULT_MAX_HEARTBEAT_INTERVAL,
        **kwargs: Any,
    ) -> None:
        log = logging.getLogger()
        super().__init__(
            host=host,
            port=port,
            log=log,
            connect_callback=connect_callback,
            name=name,
            encoding=encoding,
            terminator=terminator,
            run_heartbeat_monitor_task=run_heartbeat_monitor_task,
            max_heartbeat_interval=max_heartbeat_interval,
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
        try:
            data = await self.read_str()
        except asyncio.IncompleteReadError:
            data = ""
        if HEARTBEAT.decode() in data:
            await self.handle_received_heartbeat()
        else:
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
