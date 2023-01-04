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

__all__ = ["OneClientServer"]

import asyncio
import inspect
import logging
import types
import typing
import warnings

from . import utils
from .constants import DEFAULT_MONITOR_CONNECTION_INTERVAL


class OneClientServer:
    """A TCP/IP socket server that serves a single client.

    If additional clients try to connect, they are rejected.

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
        Asynchronous function to call when the connection state changes.
        If the client closes the connection it may take up to 0.1 seconds
        to notice (see Notes).
        It receives one argument: this `OneClientServer`.
        For backwards compatibility the function may be synchronous,
        but that is deprecated.
    monitor_connection_interval : `float`, optional
        Interval between checking if the connection is still alive (seconds).
        Defaults to DEFAULT_MONITOR_CONNECTION_INTERVAL.
        If ≤ 0 then do not monitor the connection at all.
    name : `str`, optional
        Name used for log messages, e.g. "Commands" or "Telemetry".
    **kwargs : dict[str, Any]
        Additional keyword arguments for `asyncio.start_server`,
        beyond host and port.

    Attributes
    ----------
    port : `int`
        The port on which this server is running.

        If you specify port=0 and the server is only listening on one socket,
        then the port attribute is set to the randomly chosen port.
        However, if the server is listening on more than one socket,
        the port is ambiguous (since each socket will have a different port)
        and will be left at 0; in that case you will have to examine
        server.sockets to determine the port you want.

        To make the server listen on only one socket with port=0,
        specify the host as a string instead of None. For example:

        * IP4: ``host=LOCALHOST_IPV4, port=0``
        * IP6: ``host="::", port=0``

        An alternative that allows host=None is to specify family as
        `socket.AF_INET` for IPv4, or `socket.AF_INET6` for IPv6.
    socket : `asyncio.AbstractServer` or None
        The socket server. None until start_task is done.
    reader : `asyncio.StreamReader` or None
        Stream reader to read data from the client.
        This will be a stream reader (not None) if `connected` is True.
    writer : `asyncio.StreamWriter` or None
        Stream writer to write data to the client.
        This will be a stream writer (not None) if `connected` is True.
    start_task : `asyncio.Future`
        Future that is set done when the socket server has started running
        and listening for connections.
    connected_task : `asyncio.Future`
        Future that is set done when a client connects.
        You may set replace it with a new `asyncio.Future`
        if you want to detect when another connection is made
        after the current client disconnects.
    done_task : `asyncio.Future`
        Future that is set done when this server is closed, at which point
        it is no longer usable.

    Warnings
    --------
    If you specify port=0 and host=None then it is not safe to rely on
    the `port` property to give you the port, because the server is likely
    to be listening on more than one socket, each with its own different port.
    You can inspect `server.sockets` to obtain the necessary information.

    Notes
    -----
    See the User Guide for an example.

    Always wait for `start_task` after constructing an instance,
    before using the instance. This indicates that the server
    has started listening for a connection.

    You may wait for ``connected_task`` to wait until a client connects.

    Always check that `connected` is True before reading or writing.

    Can be used as an async context manager, which may be useful for unit
    tests.
    """

    def __init__(
        self,
        host: str | None,
        port: int | None,
        log: logging.Logger,
        connect_callback: typing.Callable[
            [OneClientServer], None | typing.Awaitable[None]
        ]
        | None = None,
        monitor_connection_interval: float = DEFAULT_MONITOR_CONNECTION_INTERVAL,
        name: str = "",
        **kwargs: typing.Any,
    ) -> None:
        self.host = host
        self.port = port
        self.log = log.getChild(f"{type(self).__name__}({name})")
        self.__connect_callback = connect_callback
        # TODO DM-37477: remove this block
        # once we drop support for sync connect_callback
        if connect_callback is not None and not inspect.iscoroutinefunction(
            connect_callback
        ):
            warnings.warn(
                "connect_callback should be asynchronous", category=DeprecationWarning
            )
        self.name = name

        # Was the client connected last time `call_connected_callback`
        # called? Used to prevent multiple calls to ``connect_callback``
        # for the same connected state.
        self._was_connected = False
        self._monitor_connection_task: asyncio.Future = asyncio.Future()
        self._monitor_connection_task.set_result(None)
        self.monitor_connection_interval = monitor_connection_interval

        self.server: asyncio.AbstractServer | None = None
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.connected_task: asyncio.Future = asyncio.Future()
        self.start_task: asyncio.Future = asyncio.create_task(self.start(**kwargs))
        self.done_task: asyncio.Future = asyncio.Future()

    @property
    def connected(self) -> bool:
        """Return True if a client is connected to this server."""
        return not (
            self.reader is None
            or self.writer is None
            or self.reader.at_eof()
            or self.writer.is_closing()
        )

    async def start(self, **kwargs: typing.Any) -> None:
        """Start the TCP/IP server.

        This is called automatically by the constructor,
        and is not intended to be called by the user.
        It is a public method so that subclasses can override it.

        Parameters
        ----------
        **kwargs
            Additional keyword arguments for `asyncio.start_server`,
            beyond host and port.

        Raises
        ------
        RuntimeError
            If start has already been called and has successfully constructed
            a server.
        """
        if self.server is not None:
            raise RuntimeError("Cannot call start more than once.")
        self.log.debug("Starting server")
        self.server = await asyncio.start_server(
            self._set_reader_writer,
            host=self.host,
            port=self.port,
            **kwargs,
        )
        assert self.server.sockets is not None
        num_sockets = len(self.server.sockets)
        if self.port == 0 and num_sockets == 1:
            self.port = self.server.sockets[0].getsockname()[1]  # type: ignore
        if self.monitor_connection_interval > 0:
            self._monitor_connection_task = asyncio.create_task(
                self._monitor_connection()
            )
        self.log.info(
            f"Server running: host={self.host}; port={self.port}; "
            f"listening on {num_sockets} sockets"
        )

    async def close_client(self) -> None:
        """Close the connected client socket, if any.

        Call connect_callback if a client was connected.
        """
        try:
            self.log.info("Closing the client socket.")
            if self.writer is None:
                return

            writer = self.writer
            self.writer = None
            await utils.close_stream_writer(writer)
            self.connected_task = asyncio.Future()
        except Exception:
            self.log.exception("close_client failed; continuing")
        finally:
            await self.call_connect_callback()

    async def close(self) -> None:
        """Close socket server and client socket and set the done_task done.

        Call connect_callback if a client was connected.

        Always safe to call.
        """
        try:
            self.log.info("Closing the server.")
            if self.server is not None:
                self.server.close()
            await self.close_client()
        except Exception:
            self.log.exception("close failed; continuing")
        finally:
            self._monitor_connection_task.cancel()
            if self.done_task.done():
                self.done_task.set_result(None)

    async def call_connect_callback(self) -> None:
        """Call self.__connect_callback.

        This is always safe to call. It only calls the callback function
        if that function is not None and if the connection state has changed
        since the last time this method was called.
        """
        connected = self.connected
        self.log.debug(
            f"call_connect_callback: connected={connected}; "
            f"was_connected={self._was_connected}"
        )
        if self._was_connected != connected:
            if self.__connect_callback is not None:
                try:
                    self.log.info("Calling connect_callback")
                    # TODO DM-37477: simplify this block to
                    # ``await self._connect_callback(self)``
                    # once we drop support for sync connect_callback
                    result = self.__connect_callback(self)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    self.log.exception("connect_callback failed.")
            self._was_connected = connected

    async def _monitor_connection(self) -> None:
        """Monitor to detect if the client drops the connection."""
        while True:
            if self._was_connected and not self.connected:
                await self.close_client()
            await asyncio.sleep(self.monitor_connection_interval)

    async def _set_reader_writer(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Set self.reader and self.writer.

        Called when a client connects to this server.

        Parameters
        ----------
        reader : `asyncio.StreamReader`
            Socket reader.
        writer : `asyncio.StreamWriter`
            Socket writer.
        """
        if self.connected:
            self.log.error("Rejecting connection; a socket is already connected.")
            await utils.close_stream_writer(writer)
            return

        if self._was_connected:
            # The client dropped the connection but _monitor_connection
            # has not yet noticed.
            await self.close_client()

        # Accept the connection
        self.reader = reader
        self.writer = writer
        if not self.connected_task.done():
            self.connected_task.set_result(None)
        await self.call_connect_callback()

    async def __aenter__(self) -> OneClientServer:
        await self.start_task
        return self

    async def __aexit__(
        self,
        type: None | BaseException,
        value: None | BaseException,
        traceback: None | types.TracebackType,
    ) -> None:
        await self.close()
