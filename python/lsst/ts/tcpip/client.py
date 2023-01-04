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
import logging
import types
import typing

from . import utils
from .constants import DEFAULT_MONITOR_CONNECTION_INTERVAL


class Client:
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
        If the other end (server) closes the connection, it may take up to
        ``monitor_connection_interval`` seconds to notice (see Notes).
        The function receives one argument: this `Client`.
    monitor_connection_interval : `float`, optional
        Interval between checking if the connection is still alive (seconds).
        Defaults to DEFAULT_MONITOR_CONNECTION_INTERVAL.
        If ≤ 0 then do not monitor the connection at all.
    name : `str`
        Optional name used for log messages.
    **kwargs : dict[str, Any]
        Additional keyword arguments for `asyncio.open_connection`,
        beyond host and port.

    Attributes
    ----------
    host : `str` | `None`
        IP address; the ``host`` constructor argument.
    port : `int` | `None`
        IP port; the ``port`` constructor argument.
    log : `logging.Logger`
        A child of the ``log`` constructor argument.
    name : `str`
        The ``name`` constructor argument.
    reader : `asyncio.StreamReader` or None
        Stream reader to read data from the server.
        This will be a stream reader (not None) if `connected` is True.
    writer : `asyncio.StreamWriter` or None
        Stream writer to write data to the server.
        This will be a stream writer (not None) if `connected` is True.
    start_task : `asyncio.Future`
        Future that is set done when the connection is made.
    done_task : `asyncio.Future`
        Future that is set done when this client is closed, at which point
        it is no longer usable.
    should_be_connected : `bool`
        True if the connection was made and close not called.
        The connection was unexpectedly lost if ``should_be_connected``
        is true and ``connected`` is false (unless you close the connection
        by calling `basic_close` or manually closing ``writer``).

    Notes
    -----
    See the User Guide for an example.

    Always wait for `start_task` after constructing an instance,
    before using the instance. This indicates the client has connected.

    Always check that `connected` is True before reading or writing.

    Can be used as an async context manager, which may be useful for unit
    tests.
    """

    def __init__(
        self,
        host: str | None,
        port: int | None,
        log: logging.Logger,
        connect_callback: typing.Callable[[Client], typing.Awaitable[None]]
        | None = None,
        monitor_connection_interval: float = DEFAULT_MONITOR_CONNECTION_INTERVAL,
        name: str = "",
        **kwargs: typing.Any,
    ) -> None:
        self.host = host
        self.port = port
        self.log = log.getChild(f"{type(self).__name__}({name})")
        self.__connect_callback = connect_callback
        self.monitor_connection_interval = monitor_connection_interval
        self.name = name

        # Has the connection been made and not closed at this end?
        self.should_be_connected = False

        # Has start been called? Used to prevent calling it more than once.
        self._started = False

        # Was the client connected last time `call_connected_callback`
        # called? Used to prevent multiple calls to ``connect_callback``
        # for the same connected state.
        self._was_connected = False

        self._monitor_connection_task: asyncio.Future = asyncio.Future()
        self._monitor_connection_task.set_result(None)

        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

        # Task which is set done when client connects.
        self.start_task: asyncio.Future = asyncio.create_task(self.start(**kwargs))

        # Task which is set done when the client is closed.
        self.done_task: asyncio.Future = asyncio.Future()

    @property
    def connected(self) -> bool:
        """Return True if this client is connected to a server."""
        return not (
            self.reader is None
            or self.writer is None
            or self.reader.at_eof()
            or self.writer.is_closing()
        )

    async def call_connect_callback(self) -> None:
        """Call self.__connect_callback.

        This is always safe to call. It only calls the callback function
        if that function is not None and if the connection state has changed
        since the last time this method was called.
        """
        connected = self.connected
        self.log.debug(
            f"call_connect_callback: {connected=}; was_connected={self._was_connected}"
        )
        if self._was_connected != connected:
            self._was_connected = connected
            if self.__connect_callback is not None:
                try:
                    await self.__connect_callback(self)
                except Exception:
                    self.log.exception("connect_callback failed.")

    async def basic_close(self) -> None:
        """Close the connected client socket, if any.

        Like `close` except does not clear ``self.should_be_connected``,
        nor cancel ``self._monitor_connection_task``.
        """
        try:
            self.log.info("Closing")
            if self.writer is None:
                return

            writer = self.writer
            self.writer = None
            await utils.close_stream_writer(writer)
        except Exception:
            self.log.exception("close failed; continuing")
        finally:
            await self.call_connect_callback()
            if self.done_task.done():
                self.done_task.set_result(None)

    async def close(self) -> None:
        """Close the connected client socket, if any.

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
        **kwargs : dict[str, Any]
            Additional keyword arguments for `asyncio.open_connection`,
            beyond host and port.

        Raises
        ------
        RuntimeError
            If start already called.
        """
        if self._started:
            raise RuntimeError("Start already called")

        self._started = True
        self.reader, self.writer = await asyncio.open_connection(
            host=self.host, port=self.port, **kwargs
        )
        self.should_be_connected = True
        if self.monitor_connection_interval > 0:
            self._monitor_connection_task = asyncio.create_task(
                self._monitor_connection()
            )
        await self.call_connect_callback()
        self.log.info(f"Client connected to host={self.host}; port={self.port}")

    async def _monitor_connection(self) -> None:
        """Monitor to detect if the other end drops the connection.

        Raises
        ------
        RuntimeError
            If self.monitor_connection_interval <= 0
        """
        if self.monitor_connection_interval <= 0:
            raise RuntimeError(f"Bug: {self.monitor_connection_interval=} <= 0")
        while self.connected:
            await asyncio.sleep(self.monitor_connection_interval)
        await self.basic_close()

    async def __aenter__(self) -> Client:
        await self.start_task
        return self

    async def __aexit__(
        self,
        type: None | BaseException,
        value: None | BaseException,
        traceback: None | types.TracebackType,
    ) -> None:
        await self.close()
