from __future__ import annotations

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

__all__ = ["Client"]

import asyncio
import inspect
import logging
import typing

from .base_client_or_server import BaseClientOrServer, ConnectCallbackType
from .constants import (
    DEFAULT_ENCODING,
    DEFAULT_MONITOR_CONNECTION_INTERVAL,
    DEFAULT_TERMINATOR,
)

# Default connect_timeout (sec)
DEFAULT_CONNECT_TIMEOUT = 5


class Client(BaseClientOrServer):
    """A TCP/IP socket client.

    A thin wrapper around `asyncio.open_connection`. Like that function,
    it can only be used to connect once. Construct a new instance each
    time you wish to make a new connection.

    Parameters
    ----------
    host : `str` | `None`
        IP address.
    port : `int` | `None`
        IP port.
    log : `logging.Logger`
        Logger.
    connect_callback : callable or `None`, optional
        Asynchronous function to call when the connection state changes.
        If the other end (server) closes the connection, it may take
        ``monitor_connection_interval`` seconds or longer to notice.
        The function receives one argument: this `Client`.
    connect_timeout : `float`, optional
        Default connection timeout (sec).
    monitor_connection_interval : `float`, optional
        Interval between checking if the connection is still alive (seconds).
        Defaults to DEFAULT_MONITOR_CONNECTION_INTERVAL.
        If ≤ 0 then do not monitor the connection at all.
        Monitoring is only useful if you do not regularly read from the reader
        using the read methods of this class (or copying what they do
        to detect and report hangups).
    name : `str`
        Optional name used for log messages.
    encoding : `str`
        The encoding used by `read_str` and `write_str`, `read_json`,
         and `write_json`.
    terminator : `bytes`
        The terminator used by `read_str` and `write_str`, `read_json`,
         and `write_json`.
    **kwargs : `dict` [`str`, `typing.Any`]
        Additional keyword arguments for `asyncio.open_connection`,
        beyond host and port.

    Attributes
    ----------
    host : `str` | `None`
        IP address; the ``host`` constructor argument.
    port : `int` | `None`
        IP port; the ``port`` constructor argument.
    plus...
        Attributes provided by parent class `BaseClientOrServer`.

    Raises
    ------
    `TypeError`
        If `connect_callback` is synchronous.

    Notes
    -----
    See `tests/test_example.py <https://ls.st/514>`_ for an example.

    Always wait for ``start_task`` after constructing an instance,
    before using the instance. This indicates the client has connected.

    This class provides high-level read and write methods that monitor
    the connection (to call ``connect_callback`` as needed) and reject
    any attempt to read or write if not connected. Please use them.

    This class can be used as an async context manager, which may be useful
    for unit tests.
    """

    def __init__(
        self,
        host: str | None,
        port: int | None,
        log: logging.Logger,
        connect_callback: ConnectCallbackType | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        monitor_connection_interval: float = DEFAULT_MONITOR_CONNECTION_INTERVAL,
        name: str = "",
        encoding: str = DEFAULT_ENCODING,
        terminator: bytes = DEFAULT_TERMINATOR,
        **kwargs: typing.Any,
    ) -> None:
        # TODO DM-37477: delete this test and let the base class handle it
        # once we drop support for sync connect_callback
        if connect_callback is not None and not inspect.iscoroutinefunction(
            connect_callback
        ):
            raise TypeError("connect_callback must be asynchronous")
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout

        super().__init__(
            log=log,
            connect_callback=connect_callback,
            monitor_connection_interval=monitor_connection_interval,
            name=name,
            encoding=encoding,
            terminator=terminator,
            **kwargs,
        )

    async def basic_close(self) -> None:
        """Close the connected client socket, if any, and set done_task done.

        Like `close` except does not clear ``self.should_be_connected``,
        nor cancel ``self._monitor_connection_task``.
        """
        self.log.info("Closing")
        try:
            await self._close_client()
        finally:
            if not self.done_task.done():
                self.done_task.set_result(None)

    async def close(self) -> None:
        """Close the connected client socket, if any, and set done_task done.

        Call connect_callback if a client was connected.
        """
        self.should_be_connected = False
        self._monitor_connection_task.cancel()
        await self.basic_close()

    async def start(self, **kwargs: typing.Any) -> None:
        """Connect to the TCP/IP server.

        This is called automatically by the constructor,
        and is not intended to be called by the user.
        It is a public method so that subclasses can override it.

        Parameters
        ----------
        **kwargs : `dict` [`str`, `typing.Any`]
            Additional keyword arguments for `asyncio.open_connection`,
            beyond host and port.

        Raises
        ------
        `RuntimeError`
            If start already called.
        """
        try:
            if self._reader is not None:
                raise RuntimeError("Start already called.")

            self.log.info(f"Connecting to host={self.host}; port={self.port}")
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host=self.host, port=self.port, **kwargs),
                timeout=self.connect_timeout,
            )
            await self._set_reader_writer(reader=reader, writer=writer)
            self._start_monitoring_connection()
            await self.call_connect_callback()
        except Exception as e:
            print(f"start failed: {e!r}")
            raise

    async def _monitor_connection(self) -> None:
        """Monitor to detect if the other end drops the connection.

        Start this when the connection is made.
        It quits when the connection is lost.

        Raises
        ------
        `RuntimeError`
            If self.monitor_connection_interval <= 0
        """
        if self.monitor_connection_interval <= 0:
            raise RuntimeError(f"Bug: {self.monitor_connection_interval=} <= 0")
        while self.connected:
            await asyncio.sleep(self.monitor_connection_interval)
        await self._close_client()
