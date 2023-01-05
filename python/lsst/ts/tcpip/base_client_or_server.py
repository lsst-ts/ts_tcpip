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

__all__ = ["BaseClientOrServer", "ConnectCallbackType"]

import abc
import asyncio
import collections.abc
import ctypes
import inspect
import logging
import types
import typing
import warnings

from . import utils
from .constants import DEFAULT_MONITOR_CONNECTION_INTERVAL


class BaseClientOrServer(abc.ABC):
    """Abstract base class for a TCP/IP client or server.

    Manage a stream reader and writer:

    * Provide high-level methods for reading and writing.
    * Optionally call a callback function when the connection state changes.
    * Optionally monitor the connection in the background.

    Parameters
    ----------
    log : `logging.Logger`
        Logger.
    connect_callback : callable or `None`, optional
        Asynchronous or (deprecated) synchronous function to call when
        the connection state changes.
        If the other end closes the connection, it may take
        ``monitor_connection_interval`` seconds or longer to notice.
        The function receives one argument: this `BaseClientOrServer`.
    monitor_connection_interval : `float`, optional
        Interval between checking if the connection is still alive (seconds).
        Defaults to DEFAULT_MONITOR_CONNECTION_INTERVAL.
        If ≤ 0 then do not monitor the connection at all.
        Monitoring is only useful if you do not regularly read from the reader
        using the read methods of this class (or copying what they do
        to detect and report hangups).
    name : `str`
        Optional name used for log messages.
    **kwargs : `dict` [`str`, `typing.Any`]
        Keyword arguments for start_task.

    Attributes
    ----------
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
    Users should always wait for `start_task` after constructing an instance,
    before using the instance. This indicates the client has connected.

    This class provides high-level read and write methods that monitor
    the connection and reject any attempt to read or write if not connected.
    If you prefer to use the ``reader`` or ``writer`` attributes directly,
    please be sure to:

    * Check that `connected` is True before reading or writing.
      This is especially important for writing, since writing to a closed
      socket does not raise an exception.
    * Catch (asyncio.IncompleteReadError, ConnectionResetError)
      when reading, and call a method to close the client if triggered:
      `Client.basic_close` or `OneClientServer.basic_close_client`.

    This class cay be used as an async context manager, which may be useful
    for unit tests.

    Subclasses should call `_start_monitoring_connection` from the `start`
    method.
    """

    def __init__(
        self,
        *,
        log: logging.Logger,
        connect_callback: typing.Callable[
            [BaseClientOrServer], None | typing.Awaitable[None]
        ]
        | None = None,
        monitor_connection_interval: float = DEFAULT_MONITOR_CONNECTION_INTERVAL,
        name: str = "",
        **kwargs: typing.Any,
    ) -> None:
        if connect_callback is not None and not inspect.iscoroutinefunction(
            connect_callback
        ):
            # TODO DM-37477: modify this to raise (and update the doc string)
            # once we drop support for sync connect_callback
            warnings.warn(
                "connect_callback should be asynchronous", category=DeprecationWarning
            )

        self.log = log.getChild(f"{type(self).__name__}({name})")
        self.__connect_callback = connect_callback
        self.monitor_connection_interval = monitor_connection_interval
        self.name = name

        # Has the connection been made and not closed at this end?
        self.should_be_connected = False

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
        """Return True if self.reader and self.writer are connected."""
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
                    # TODO DM-37477: simplify this to
                    # `await self._connect_callback(self)`
                    # once we drop support for sync connect_callback
                    result = self.__connect_callback(self)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    self.log.exception("connect_callback failed.")

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the client or server, making it unusable."""
        raise NotImplementedError()

    async def read(self, n: int) -> bytes:
        """Read up to n bytes.

        Parameters
        ----------
        n : `int`, optional
            The number of bytes to read. If -1 then block until
            the other end closes its writer, then return all data seen.

        Raises
        ------
        `ConnectionError`
            If self.connected false before reading begins.
        `ConnectionResetError`
            If the connection is lost while reading.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self.reader is not None  # make mypy happy
        try:
            return await self.reader.read(n)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            await self._close_client()
            raise

    async def readexactly(self, n: int) -> bytes:
        """Read exactly n bytes.

        Parameters
        ----------
        n : `int`, optional
            The number of bytes to read.

        Raises
        ------
        `ConnectionError`
            If self.connected false before reading begins.
        `asyncio.IncompleteReadError`
            If EOF is reached before ``n`` bytes can be read. Use the
            `IncompleteReadError.partial` attribute to get the partially
            read data.
        `ConnectionResetError`
            If the connection is lost while reading.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self.reader is not None  # make mypy happy
        try:
            return await self.reader.readexactly(n)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            await self._close_client()
            raise

    async def readline(self) -> bytes:
        r"""Read a sequence of bytes ending with ``\n``.

        If EOF is received and ``\n`` was not found, the method returns
        partially read data.

        Raises
        ------
        `ConnectionError`
            If self.connected false before reading begins.
        `ConnectionResetError`
            If the connection is lost while reading.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self.reader is not None  # make mypy happy
        try:
            return await self.reader.readline()
        except ConnectionResetError:
            await self._close_client()
            raise

    async def readuntil(self, separator: bytes = b"\n") -> bytes:
        """Read one line, where “line” is a sequence of bytes ending with \n.

        Read data from the stream until separator is found.

        On success, the data and separator will be removed from the internal
        buffer (consumed). Returned data will include the separator at the end.

        Raises
        ------
        `ConnectionError`
            If self.connected false before reading begins.
        `ConnectionResetError`
            If the connection is lost while reading.
        `asyncio.IncompleteReadError`
            If EOF is reached before the complete separator is found
            and the internal buffer is reset.
        `LimitOverrunError`
            If the amount of data read exceeds the configured stream lmit.
            The data is left in the internal buffer and can be read again.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self.reader is not None  # make mypy happy
        try:
            return await self.reader.readuntil(separator)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            await self._close_client()
            raise

    async def read_into(self, struct: ctypes.Structure) -> None:
        """Read binary data from a stream reader into a `ctypes.Structure`.

        Parameters
        ----------
        struct : `ctypes.Structure`
            Structure to set.

        Raises
        ------
        `ConnectionError`
            If self.connected false before reading begins.
        `asyncio.IncompleteReadError`
            If EOF is reached before ``n`` bytes can be read. Use the
            `IncompleteReadError.partial` attribute to get the partially
            read data.
        `ConnectionResetError`
            If the connection is lost while reading.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self.reader is not None  # make mypy happy
        try:
            await utils.read_into(reader=self.reader, struct=struct)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            await self._close_client()
            raise

    async def write(self, data: bytes) -> None:
        """Write data and call ``drain``.

        Parameters
        ----------
        data : `bytes`
            The data to write.

        Raises
        ------
        `ConnectionError`
            If self.connected false before writing begins.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self.writer is not None  # make mypy happy
        self.writer.write(data)
        await self.writer.drain()

    async def writelines(self, lines: collections.abc.Iterable) -> None:
        """Write an iterable of bytes and call ``drain``.

        Parameters
        ----------
        lines : `collections.abc.Iterable` [`bytes`]
            The data to write, as an iterable collection of `bytes`.

        Raises
        ------
        `ConnectionError`
            If self.connected false before writing begins.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self.writer is not None  # make mypy happy
        self.writer.writelines(lines)
        await self.writer.drain()

    async def write_from(self, *structs: ctypes.Structure) -> None:
        r"""Write binary data from one or more `ctypes.Structure`\ s.

        Parameters
        ----------
        struct : `ctypes.Structure`
            Structure to write.

        Raises
        ------
        `ConnectionError`
            If self.connected false before reading begins.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self.writer is not None  # make mypy happy
        await utils.write_from(self.writer, *structs)

    @abc.abstractmethod
    async def start(self, **kwargs: typing.Any) -> None:
        """Start asynchronous processes.

        This is called automatically by the constructor.

        A server should construct and start the server.
        A client should connect and set reader and writer.
        Both should call _start_monitoring_connection on success.
        Both should raise RuntimError if start has already been called.

        Raises
        ------
        RuntimeError
            If already called.
        """
        raise NotImplementedError()

    async def _close_client(self) -> None:
        """Close self.writer, after setting it to None,
        then call connect_callback.

        Does not set self.should_be_connected or stop the connection
        monitor.

        Does not touch self.reader, since it cannot be closed
        and subclasses may find it useful for it to be non-None.
        """
        if self.writer is None:
            return

        try:
            writer = self.writer
            self.writer = None
            await utils.close_stream_writer(writer)
        except Exception:
            self.log.exception("Failed to close the writer; continuing.")
        finally:
            await self.call_connect_callback()

    @abc.abstractmethod
    async def _monitor_connection(self) -> None:
        """Monitor to detect if the other end drops the connection.

        Raises
        ------
        `RuntimeError`
            If self.monitor_connection_interval <= 0
        """
        raise NotImplementedError()

    def _start_monitoring_connection(self) -> None:
        """Start or re-start monitoring the connection."""
        self._monitor_connection_task.cancel()
        if self.monitor_connection_interval > 0:
            self._monitor_connection_task = asyncio.create_task(
                self._monitor_connection()
            )

    async def _set_reader_writer(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Set self.reader and self.writer to open streams.

        Set self.should_be_connected true.
        Does not start monitoring the connection.

        Parameters
        ----------
        reader : asyncio.StreamReader
            An open stream reader.
        writer : asyncio.StreamWriter
            An open stream writer.
        """
        self.should_be_connected = True
        self.reader = reader
        self.writer = writer

    async def __aenter__(self) -> BaseClientOrServer:
        await self.start_task
        return self

    async def __aexit__(
        self,
        type: None | BaseException,
        value: None | BaseException,
        traceback: None | types.TracebackType,
    ) -> None:
        await self.close()


# TODO DM-37477: simplify this by changing
# "None | typing.Awaitable[None]" to "typing.Awaitable[None]"
# once we drop support for sync connect_callback
ConnectCallbackType = typing.Callable[
    [BaseClientOrServer], None | typing.Awaitable[None]
]
