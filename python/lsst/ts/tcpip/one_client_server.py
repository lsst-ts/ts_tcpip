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
import socket
import typing

from . import utils


class OneClientServer:
    """A TCP/IP socket server that serves a single client.

    If additional clients try to connect they are rejected
    (the socket writer is closed).

    Parameters
    ----------
    name : `str`
        Name used for error messages. Typically "Commands" or "Telemetry".
    host : `str` or `None`
        IP address for this server; typically `LOCALHOST` for IP4
        or "::" for IP6. If `None` then bind to all network interfaces
        (e.g. listen on an IPv4 socket and an IPv6 socket).
        None can cause trouble with port=0;
        see port in Attributes for more information.
    port : `int`
        IP port for this server. If 0 then randomly pick an available port
        (or ports, if listening on multiple sockets).
        0 is strongly recommended for unit tests.
    log : `logging.Logger`
        Logger.
    connect_callback : callable or `None`, optional
        Synchronous function to call when a client connects, and when
        close or close_client is called. Note that it is *not* called
        when the client end closes its connection (see Notes).
        It receives one argument: this `OneClientServer`.
    family : socket.AddressFamily
        Can be set to `socket.AF_INET` or `socket.AF_INET6` to limit the server
        to IPv4 or IPv6, respectively. If `socket.AF_UNSPEC` (the default)
        the family will be determined from host, and if host is None,
        the server may listen on both IPv4 and IPv6 sockets.

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

        * IP4: ``host=LOCAL_HOST, port=0``
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
        (after the current client disconnects).
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

    Always check that `connected` is True before reading or writing.

    The only way to detect that the client has dropped the connection
    is to read data from the ``reader``. When the connection is dropped,
    reading will raise `asyncio.IncompleteReadError` or `ConnectionResetError`.
    Once one of these exceptions has been raised, ``reader.at_eof()``
    will be true and the server knows to allow a new client connection.

    Thus you should always read data from the ``reader``, even if you do not
    expect to receive any. And all reads should catch
    `asyncio.IncompleteReadError` and `ConnectionResetError`.
    The usual way to handle these exceptions is to exit from the read task.

    If you want ``connect_callback`` to be called when the client closes
    its connection (this is rarely necessary), then your code that reads data
    from the client must call `call_connect_callback` when the read
    raises one of the exceptions just mentioned. See the User Guide
    for an example.
    """

    def __init__(
        self,
        name: str,
        host: typing.Optional[str],
        port: int,
        log: logging.Logger,
        connect_callback: typing.Optional[typing.Callable],
        family: socket.AddressFamily = socket.AF_UNSPEC,
    ) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.family = family
        self.log = log.getChild(f"OneClientServer({name})")
        self.__connect_callback = connect_callback

        # Was the client connected last time `call_connected_callback`
        # called? Used to prevent multiple calls to ``connect_callback``
        # for the same connected state.
        self._was_connected = False

        self.server: typing.Optional[asyncio.AbstractServer] = None
        self.reader: typing.Optional[asyncio.StreamReader] = None
        self.writer: typing.Optional[asyncio.StreamWriter] = None
        self.connected_task: asyncio.Future = asyncio.Future()
        self.start_task: asyncio.Future = asyncio.create_task(self.start())
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

    async def start(self) -> None:
        """Start the TCP/IP server."""
        if self.server is not None:
            raise RuntimeError("Cannot call start more than once.")
        self.log.debug("Starting server")
        self.server = await asyncio.start_server(
            self._set_reader_writer,
            host=self.host,
            port=self.port,
            family=self.family,
        )
        assert self.server.sockets is not None
        num_sockets = len(self.server.sockets)
        if self.port == 0 and num_sockets == 1:
            self.port = self.server.sockets[0].getsockname()[1]  # type: ignore
        self.log.info(
            f"Server running: host={self.host}; port={self.port}; "
            f"listening on {num_sockets} sockets"
        )

    async def close_client(self) -> None:
        """Close the connected client socket, if any."""
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
            self.call_connect_callback()

    async def close(self) -> None:
        """Close socket server and client socket and set the done_task done.

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
            if self.done_task.done():
                self.done_task.set_result(None)

    def call_connect_callback(self) -> None:
        """Call self.__connect_callback.

        Only call if the connection state has changed since the last time
        this method was called.
        """
        connected = self.connected
        self.log.debug(
            f"call_connect_callback: connected={connected}; "
            f"last_connected={self._was_connected}"
        )
        if self._was_connected != connected:
            if self.__connect_callback is not None:
                try:
                    self.log.info("Calling connect_callback")
                    self.__connect_callback(self)
                except Exception:
                    self.log.exception("connect_callback failed.")
            self._was_connected = connected

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
            print("Rejecting connection")
            self.log.error("Rejecting connection; a socket is already connected.")
            await utils.close_stream_writer(writer)
            return
        self.reader = reader
        self.writer = writer
        if not self.connected_task.done():
            self.connected_task.set_result(None)
        self.call_connect_callback()
