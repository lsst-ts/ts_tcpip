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
import logging
import typing

from . import utils
from .base_client_or_server import BaseClientOrServer, ConnectCallbackType
from .constants import DEFAULT_MONITOR_CONNECTION_INTERVAL


class OneClientServer(BaseClientOrServer):
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
        Asynchronous or (deprecated) synchronous function to call when
        when a client connects or disconnects.
        If the other end (client) closes the connection, it may take
        ``monitor_connection_interval`` seconds or longer to notice.
        The function receives one argument: this `OneClientServer`.
    monitor_connection_interval : `float`, optional
        Interval between checking if the connection is still alive (seconds).
        Defaults to DEFAULT_MONITOR_CONNECTION_INTERVAL.
        If ≤ 0 then do not monitor the connection at all.
        Monitoring is only useful if you do not regularly read from the reader
        using the read methods of this class (or copying what they do
        to detect and report hangups).
    name : `str`, optional
        Name used for log messages, e.g. "Commands" or "Telemetry".
    **kwargs : `dict` [`str`, `typing.Any`]
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
        connect_callback: ConnectCallbackType | None = None,
        monitor_connection_interval: float = DEFAULT_MONITOR_CONNECTION_INTERVAL,
        name: str = "",
        **kwargs: typing.Any,
    ) -> None:
        self.host = host
        self.port = port
        self.server: asyncio.AbstractServer | None = None
        self.connected_task: asyncio.Future = asyncio.Future()
        super().__init__(
            log=log,
            connect_callback=connect_callback,
            monitor_connection_interval=monitor_connection_interval,
            name=name,
            **kwargs,
        )

    async def start(self, **kwargs: typing.Any) -> None:
        """Start the TCP/IP server.

        This is called automatically by the constructor,
        and is not intended to be called by the user.
        It is a public method so that subclasses can override it.

        Parameters
        ----------
        **kwargs : `dict` [`str`, `typing.Any`]
            Additional keyword arguments for `asyncio.start_server`,
            beyond host and port.

        Raises
        ------
        `RuntimeError`
            If start has already been called and has successfully constructed
            a server.
        """
        if self.server is not None:
            raise RuntimeError("Start already called.")
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
        self._start_monitoring_connection()
        self.log.info(
            f"Server running: host={self.host}; port={self.port}; "
            f"listening on {num_sockets} sockets"
        )

    async def basic_close_client(self) -> None:
        """Close the connected client socket, if any.

        Also:

        * Reset `self.connected_task` to a new Future.
        * Call connect_callback, if a client was connected.

        Unlike `close_client`, this does not touch `self.should_be_connected`.

        Always safe to call.
        """
        self.log.info("Closing the client socket.")
        try:
            await self._close_client()
        finally:
            self.connected_task = asyncio.Future()

    async def close_client(self) -> None:
        """Close the connected client socket, if any.

        Also:

        * Set `self.should_be_connected` false.
        * Reset `self.connected_task` to a new Future.
        * Call connect_callback, if a client was connected.

        Always safe to call.
        """
        self.should_be_connected = False
        await self.basic_close_client()

    async def close(self) -> None:
        """Close socket server and client socket, and set done_task done.

        Call connect_callback if a client was connected.

        Always safe to call.
        """
        try:
            self.log.info("Closing the server.")
            if self.server is not None:
                # Close the asyncio.Server
                self.server.close()
                await self.server.wait_closed()
            await self.close_client()
        except Exception:
            self.log.exception("close failed; continuing")
        finally:
            self._monitor_connection_task.cancel()
            if self.done_task.done():
                self.done_task.set_result(None)

    async def _monitor_connection(self) -> None:
        """Monitor to detect if the client drops the connection.

        Start this when the server is started.
        Cancel this when this class is is closed.

        Raises
        ------
        `RuntimeError`
            If self.monitor_connection_interval <= 0
        """
        while True:
            if self._was_connected and not self.connected:
                await self._close_client()
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
