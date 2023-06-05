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
import json
import logging
import types
import typing
import warnings

from . import utils
from .constants import (
    DEFAULT_ENCODING,
    DEFAULT_MONITOR_CONNECTION_INTERVAL,
    DEFAULT_TERMINATOR,
)


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
        The function receives one argument: this `BaseClientOrServer`.

        Note: if the connection is unexpectedly lost and you are not reading
        from the socket, it may take ``monitor_connection_interval`` seconds
        or longer to notice.
    monitor_connection_interval : `float`, optional
        Interval between checking if the connection is still alive (seconds).
        Defaults to DEFAULT_MONITOR_CONNECTION_INTERVAL.
        If ≤ 0 then do not monitor the connection at all.

        Monitoring is only useful if you do not regularly read from the reader
        using the read methods of this class.
    name : `str`
        Optional name used for log messages.
    do_start : `bool`, optional
        Call start in the constructor? Normally True (the default),
        but set False by Client when creating an already-closed Client.
    encoding : `str`
        The encoding used by `read_str` and `write_str`, `read_json`,
         and `write_json`.
    terminator : `bytes`
        The terminator used by `read_str` and `write_str`, `read_json`,
         and `write_json`.

    **kwargs : `dict` [`str`, `typing.Any`]
        Keyword arguments for start_task.

    Attributes
    ----------
    log : `logging.Logger`
        A child of the ``log`` constructor argument.
    name : `str`
        The ``name`` constructor argument.
    encoding : `str`
        The ``encoding`` constructor argument.
    terminator : `bytes`
        The ``terminator`` constructor argument.
    reader : `asyncio.StreamReader` or None
        Stream reader to read data from the server.
        This will be a stream reader (not None) if `connected` is True.
    writer : `asyncio.StreamWriter` or None
        Stream writer to write data to the server.
        This will be a stream writer (not None) if `connected` is True.
    start_task : `asyncio.Future`
        Future that is set done when:

        * The connection is made, for the `Client` subclass.
        * The server is ready to receive connections, for Server subclasses.

    done_task : `asyncio.Future`
        Future that is set done when this instance is closed, at which point
        the instance is no longer usable.
    should_be_connected : `bool`
        This flag helps you determine if you unexpectedly lost the connection
        (e.g. if the other end hung up). It is set true when the connection
        is made and false when you call `close`, or
        `OneClientServer.close_client`. The connection was unexpectedy lost
        if `connected` is false and ``should_be_connected`` is true.

        If your CSC unexpectedly loses its connection to a low-level
        controller, you should send the CSC to fault state.

    Notes
    -----
    Always wait for ``start_task`` after constructing an instance,
    before using the instance.

    This class provides high-level read and write methods that monitor
    the connection (to call ``connect_callback`` as needed) and reject
    any attempt to read or write if not connected. Please use them.

    This class can be used as an async context manager, which may be useful
    for unit tests.

    Subclasses should call `_start_monitoring_connection` from the `start`
    method, if monitoring is needed.
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
        do_start: bool = True,
        encoding: str = DEFAULT_ENCODING,
        terminator: bytes = DEFAULT_TERMINATOR,
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
        if not isinstance(terminator, bytes):
            raise ValueError(f"{terminator=!r} must be a bytes")
        try:
            " ".encode(encoding)
        except Exception as e:
            raise ValueError(f"{encoding=!r} is not a valid encoding: {e!r}")

        self.log = log.getChild(f"{type(self).__name__}({name})")
        self.__connect_callback = connect_callback
        self.monitor_connection_interval = monitor_connection_interval
        self.name = name
        self.encoding = encoding
        self.terminator = terminator

        # Has the connection been made and not closed at this end?
        self.should_be_connected = False

        # Was the client connected last time `call_connected_callback`
        # called? Used to prevent multiple calls to ``connect_callback``
        # for the same connected state.
        self._was_connected = False

        self._monitor_connection_task: asyncio.Future = asyncio.Future()
        self._monitor_connection_task.set_result(None)

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

        # Task which is set done when the client is closed.
        self.done_task: asyncio.Future = asyncio.Future()

        # Task which is set done when client connects.
        self.start_task: asyncio.Future = (
            asyncio.create_task(self.start(**kwargs)) if do_start else asyncio.Future()
        )

    @property
    def connected(self) -> bool:
        """Return True if self._reader and self._writer are connected.

        Note: if the other end drops the connection and if you are not trying
        to read data (e.g. in a background loop), then it takes the operating
        system awhile to realize the connection is lost. So this can return
        true for some unknown time after the connection has been dropped.
        """
        return not (
            self._reader is None
            or self._writer is None
            or self._reader.at_eof()
            or self._writer.is_closing()
        )

    # TODO DM-39202: remove this property.
    @property
    def reader(self) -> asyncio.StreamReader | None:
        """Deprecated access to the underlying stream reader.

        Use this classes' read methods instead.
        """
        warnings.warn(
            "Accessing the reader directly is deprecated; use read methods instead.",
            DeprecationWarning,
        )
        return self._reader

    # TODO DM-39202: remove this property.
    @property
    def writer(self) -> asyncio.StreamWriter | None:
        """Deprecated access to the underlying stream writer.

        Use this classes' write methods instead.
        """
        warnings.warn(
            "Accessing the writer directly is deprecated; use write methods instead.",
            DeprecationWarning,
        )
        return self._writer

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
        n : `int`
            The number of bytes to read. If -1 then block until
            the other end closes its writer, then return all data seen.

        Raises
        ------
        `ConnectionError`
            If the connection is lost before, or while, reading.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self._reader is not None  # make mypy happy
        try:
            return await self._reader.read(n)
        except (asyncio.IncompleteReadError, ConnectionError):
            await self._close_client()
            raise

    async def readexactly(self, n: int) -> bytes:
        """Read exactly n bytes.

        Parameters
        ----------
        n : `int`
            The number of bytes to read.

        Raises
        ------
        `ConnectionError`
            If the connection is lost before, or while, reading.
        `asyncio.IncompleteReadError`
            If EOF is reached before ``n`` bytes can be read. Use the
            `IncompleteReadError.partial` attribute to get the partially
            read data.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self._reader is not None  # make mypy happy
        try:
            return await self._reader.readexactly(n)
        except (asyncio.IncompleteReadError, ConnectionError):
            await self._close_client()
            raise

    async def readline(self) -> bytes:
        r"""Read a sequence of bytes ending with ``\n``.

        If EOF is received and ``\n`` was not found, the method returns
        partially read data.

        Raises
        ------
        `ConnectionError`
            If the connection is lost before, or while, reading.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self._reader is not None  # make mypy happy
        try:
            return await self._reader.readline()
        except ConnectionError:
            await self._close_client()
            raise

    async def readuntil(self, separator: bytes = b"\n") -> bytes:
        """Read one line, where “line” is a sequence of bytes ending with
        ``separator``.

        Read data from the stream until separator is found.

        On success, the data and separator will be removed from the internal
        buffer (consumed). Returned data will include the separator at the end.

        See also `read_str`, which is more convenient for most use cases.

        Parameters
        ----------
        separator : `bytes`
            The desired separator. The default matches the standard library,
            rather than using ``terminator``.

        Raises
        ------
        `ConnectionError`
            If the connection is lost before, or while, reading.
        `asyncio.IncompleteReadError`
            If EOF is reached before the complete separator is found
            and the internal buffer is reset.
        `LimitOverrunError`
            If the amount of data read exceeds the configured stream lmit.
            The data is left in the internal buffer and can be read again.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self._reader is not None  # make mypy happy
        try:
            return await self._reader.readuntil(separator)
        except (asyncio.IncompleteReadError, ConnectionError):
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
            If the connection is lost before, or while, reading.
        `asyncio.IncompleteReadError`
            If EOF is reached before ``n`` bytes can be read. Use the
            `IncompleteReadError.partial` attribute to get the partially
            read data.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self._reader is not None  # make mypy happy
        try:
            await utils.read_into(reader=self._reader, struct=struct)
        except (asyncio.IncompleteReadError, ConnectionError):
            await self._close_client()
            raise

    async def read_str(self) -> str:
        """Read and decode a terminated str; strip the terminator.

        Read until ``self.terminator``, strip the terminator, and decode
        the data as ``self.encoding`` with strict error handling.

        Returns
        -------
        line : `str`
            Line of data, as a str with the terminator stripped.

        Raises
        ------
        `ConnectionError`
            If the connection is lost before, or while, reading.
        `asyncio.IncompleteReadError`
            If EOF is reached before the complete separator is found
            and the internal buffer is reset.
        `LimitOverrunError`
            If the amount of data read exceeds the configured stream lmit.
            The data is left in the internal buffer and can be read again.
        `UnicodeError`
            If decoding fails.
        """
        data = await self.readuntil(self.terminator)
        term_len = len(self.terminator)
        return data[0:-term_len].decode(encoding=self.encoding, errors="strict")

    async def read_json(self) -> typing.Any:
        """Read JSON data.

        Read the data with `read_str` and return the json-decoded result.

        Returns
        -------
        data : `typing.Any`
            Data decoded from JSON.

        Raises
        ------
        `ConnectionError`
            If the connection is lost before, or while, reading.
        `asyncio.IncompleteReadError`
            If EOF is reached before the complete separator is found
            and the internal buffer is reset.
        `LimitOverrunError`
            If the amount of data read exceeds the configured stream lmit.
            The data is left in the internal buffer and can be read again.
        `TypeError`
            If the data are of a type that cannot be decoded from JSON.
        `json.JSONDecodeError`
            If the data cannot be decoded from JSON.
        """
        data = await self.read_str()
        try:
            return json.loads(data)
        except json.JSONDecodeError as e:
            # Expand the uninformative message in the raised exception
            # to include the invalid data.
            raise json.JSONDecodeError(
                msg=f"{data=!r} is not valid json", doc=e.doc, pos=e.pos
            )

    async def write(self, data: bytes) -> None:
        """Write data and call ``drain``.

        Parameters
        ----------
        data : `bytes`
            The data to write.

        Raises
        ------
        `ConnectionError`
            If ``self.connected`` false before writing begins.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self._writer is not None  # make mypy happy
        self._writer.write(data)
        await self._writer.drain()

    async def writelines(self, lines: collections.abc.Iterable) -> None:
        """Write an iterable of bytes and call ``drain``.

        Parameters
        ----------
        lines : `collections.abc.Iterable` [`bytes`]
            The data to write, as an iterable collection of `bytes`.

        Raises
        ------
        `ConnectionError`
            If ``self.connected`` false before writing begins.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self._writer is not None  # make mypy happy
        self._writer.writelines(lines)
        await self._writer.drain()

    async def write_from(self, *structs: ctypes.Structure) -> None:
        r"""Write binary data from one or more `ctypes.Structure`\ s.

        Parameters
        ----------
        structs : `list` [`ctypes.Structure`]
            Structures to write.

        Raises
        ------
        `ConnectionError`
            If ``self.connected`` false before writing begins.
        """
        if not self.connected:
            raise ConnectionError("Not connected")
        assert self._writer is not None  # make mypy happy
        await utils.write_from(self._writer, *structs)

    async def write_str(self, line: str) -> None:
        """Encode, terminate, and write a str.

        Encode the str as ``self.encoding`` with strict error handling,
        and append ``self.terminator``.

        Parameters
        ----------
        line : `str`
            The line of data to be written.

        Raises
        ------
        `ConnectionError`
            If the connection is lost before, or while, reading.
        `UnicodeError`
            If encoding fails.
        """
        data = line.encode(encoding=self.encoding, errors="strict") + self.terminator
        await self.write(data)

    async def write_json(self, data: typing.Any) -> None:
        """Write data in JSON format.

        Encode the data as json and write the result with `write_str`.

        Parameters
        ----------
        data : `any`
            The data to be written. Typically a dict,
            but any json-encodable data is acceptable.

        Raises
        ------
        `ConnectionError`
            If the connection is lost before, or while, reading.
        `UnicodeError`
            If encoding fails.
        `json.JSONEncodeError`
            If the data cannot be json-encoded.
        """
        line = json.dumps(data)
        await self.write_str(line)

    @abc.abstractmethod
    async def start(self, **kwargs: typing.Any) -> None:
        """Start asynchronous processes.

        This is called automatically by the constructor.

        A server should construct and start the server.
        A client should connect and set reader and writer.
        Both should call `_start_monitoring_connection` on success.
        Both should raise `RuntimeError` if `start` has already been called.

        Raises
        ------
        `RuntimeError`
            If already called.
        """
        raise NotImplementedError()

    async def _close_client(self) -> None:
        """Close self._writer, after setting it to None,
        then call connect_callback.

        Does not set self.should_be_connected or stop the connection
        monitor.

        Does not touch self._reader, since it cannot be closed
        and subclasses may find it useful for it to be non-None.
        """
        if self._writer is None:
            return

        try:
            writer = self._writer
            self._writer = None
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
        """Set self._reader and self._writer to open streams.

        Set self.should_be_connected true.
        Does not start monitoring the connection.

        Parameters
        ----------
        reader : `asyncio.StreamReader`
            An open stream reader.
        writer : `asyncio.StreamWriter`
            An open stream writer.
        """
        self.should_be_connected = True
        self._reader = reader
        self._writer = writer

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
