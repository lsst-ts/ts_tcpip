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


class OneClientServer:
    """A TCP/IP socket server that serves a single client.

    If additional clients try to connect they are rejected
    (the socket writer is closed).

    Parameters
    ----------
    name : `str`
        Name used for error messages. Typically "Commands" or "Telemetry".
    host : `str` or `None`
        IP address for this server.
        If `None` then bind to all network interfaces.
    port : `int`
        IP port for this server. If 0 then use a random port.
    log : `logging.Logger`
        Logger.
    connect_callback : callable or `None`, optional
        Synchronous function to call when a client connects, and when
        close or close_client is called. Note that it is *not* called
        when the client end closes its connection (see Notes).
        It receives one argument: this `OneClientServer`.

    Attributes
    ----------
    reader : `asyncio.StreamReader` or None
        Stream reader to read data from the client.
        This will be a stream reader (not None) if `connected` is True.
    writer : `asyncio.StreamWriter` or None
        Stream writer to write data to the client.
        This will be a stream writer (not None) if `connected` is True.

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
    ) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.log = log.getChild(f"OneClientServer({name})")
        self.connect_callback = connect_callback

        # Was the client connected last time `call_connected_callback`
        # called? Used to prevent multiple calls to ``connect_callback``
        # for the same connected state.
        self._was_connected = False

        # TCP/IP socket server, or None until start_task is done.
        self.server: typing.Optional[asyncio.AbstractServer] = None
        # Client socket reader, or None if a client not connected.
        self.reader: typing.Optional[asyncio.StreamReader] = None
        # Client socket writer, or None if a client not connected.
        self.writer: typing.Optional[asyncio.StreamWriter] = None
        # Task that is set done when a client connects to this server.
        self.connected_task: asyncio.Future = asyncio.Future()
        # Task that is set done when the TCP/IP server is started.
        self.start_task: asyncio.Future = asyncio.create_task(self.start())
        # Task that is set done when the TCP/IP server is closed,
        # making this object unusable.
        self.done_task: asyncio.Future = asyncio.Future()

    @property
    def connected(self) -> bool:
        """Return True if a client is connected to this server."""
        return not (
            self.writer is None
            or self.writer.is_closing()
            or self.reader is None
            or self.reader.at_eof()
        )

    async def start(self) -> None:
        """Start the TCP/IP server."""
        if self.server is not None:
            raise RuntimeError("Cannot call start more than once.")
        self.log.debug("Starting server")
        self.server = await asyncio.start_server(
            self._set_reader_writer, host=self.host, port=self.port
        )
        if self.port == 0:
            self.port = self.server.sockets[0].getsockname()[1]  # type: ignore
        self.log.info(f"Server running: host={self.host}; port={self.port}")

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
        """Call self.connect_callback.

        Only call if the connection state has changed since the last time
        this method was called.
        """
        connected = self.connected
        self.log.debug(
            f"call_connect_callback: connected={connected}; "
            f"last_connected={self._was_connected}"
        )
        if self._was_connected != connected:
            if self.connect_callback is not None:
                try:
                    self.log.info("Calling connect_callback")
                    self.connect_callback(self)
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
