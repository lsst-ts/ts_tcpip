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

from __future__ import annotations

import abc
import asyncio
import logging
import typing

from .base_client_or_server import ConnectCallbackType
from .one_client_server import OneClientServer

__all__ = ["OneClientReadLoopServer"]


class OneClientReadLoopServer(OneClientServer):
    """A OneClientServer that reads and processes data in a loop.

    Parameters
    ----------
    host : `str` or `None`
        IP address for this server; typically `LOCALHOST_IPV4` for IPV4
        or `LOCALHOST_IPV6` for IPV6. If `None` then bind to all network
        interfaces (e.g. listen on an IPv4 socket and an IPv6 socket).
        None can cause trouble with port=0;
        see ``port`` in the Attributes section for more information.
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

    Attributes
    ----------
    read_loop_task : `asyncio.Future`
        A task that reads data from the reader in a loop.
    """

    def __init__(
        self,
        host: str | None,
        port: int | None,
        log: logging.Logger,
        connect_callback: ConnectCallbackType | None = None,
        name: str = "",
        **kwargs: typing.Any,
    ) -> None:
        self.read_loop_task: asyncio.Future = asyncio.Future()

        super().__init__(
            host=host,
            port=port,
            log=log,
            connect_callback=connect_callback,
            monitor_connection_interval=0,
            name=name,
            **kwargs,
        )

    async def call_connect_callback(self) -> None:
        """A client has connected or disconnected."""
        await super().call_connect_callback()
        if self.connected:
            self.log.info("Client connected.")
            self.read_loop_task.cancel()
            self.read_loop_task = asyncio.create_task(self.read_loop())
        else:
            self.log.info("Client disconnected.")

    async def read_loop(self) -> None:
        """Read incoming data and handle them.

        The actual reading is deferred to the `read_and_dispatch` method and
        needs to be implemented by subclasses.
        """
        try:
            self.log.info(f"The read_loop begins connected? {self.connected}")
            while self.connected:
                self.log.debug("Waiting for next incoming data.")
                await self.read_and_dispatch()
        except Exception as e:
            self.log.exception(f"read_loop failed. Disconnecting. {e!r}")
            await self.close_client(cancel_read_loop_task=False)

    @abc.abstractmethod
    async def read_and_dispatch(self) -> None:
        """Read, parse, and dispatch one item of data.

        Subclasses need to implement this method such that it reads and parses
        data and then dispatches handling the data to a method suitable for the
        subclass. Methods that might be helpful include:

        * `read_json` to read json-encoded data
        * `read_str` to read terminated strings
        * `read_into` to read binary structs
        """
        raise NotImplementedError()

    async def close_client(self, cancel_read_loop_task: bool = True) -> None:
        """Stop the read loop and close the client.

        Parameters
        ----------
        cancel_read_loop_task : `bool`
            Cancel the read loop task or not? Defaults to True and should be
            False when called from the read loop task itself.
        """
        if cancel_read_loop_task:
            self.log.debug("Cancelling read_loop_task.")
            self.read_loop_task.cancel()
        self.log.debug("Closing client.")
        await super().close_client()
