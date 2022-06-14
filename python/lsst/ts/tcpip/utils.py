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

__all__ = ["close_stream_writer", "read_into", "write_from"]

import asyncio
import ctypes
import logging

log = logging.getLogger()


async def close_stream_writer(writer: asyncio.StreamWriter) -> None:
    """Close an asyncio.StreamWriter and wait for it to finish closing.

    Safe to call if the stream is closed or being closed, though in the
    latter case this function may raise `asyncio.CancelledError`.

    This function swallows `ConnectionResetError`, because that means
    the stream writer is closed.

    Parameters
    ----------
    writer : `asyncio.StreamWriter`
        Asynchronous stream writer to close.

    Raises
    ------
    asyncio.CancelledError
        If the writer is already being closed.
        I am not sure if this is expected behavior or a bug in Python.
    """
    try:
        writer.close()
        # Work around https://bugs.python.org/issue39758
        await asyncio.wait_for(writer.wait_closed(), timeout=5)
    except ConnectionResetError:
        log.info(
            f"wait_close({writer}) raised ConnectionResetError; "
            "this probably means the stream was already being closed."
        )
        pass
    except asyncio.TimeoutError:
        log.warning(f"Timed out waiting for wait_close({writer}); continuing.")


async def read_into(reader: asyncio.StreamReader, struct: ctypes.Structure) -> None:
    """Read binary data from a stream reader into a `ctypes.Structure`.

    Parameters
    ----------
    reader :  `asyncio.StreamReader`
        Asynchronous stream reader.
    struct : `ctypes.Structure`
        Structure to set.

    Raises
    ------
    asyncio.IncompleteReadError or ConnectionError
        If the connection is closed.
    """
    nbytes = ctypes.sizeof(struct)
    data = await reader.read(nbytes)
    if not data:
        raise ConnectionError()
    ctypes.memmove(ctypes.addressof(struct), data, nbytes)


async def write_from(writer: asyncio.StreamWriter, *structs: ctypes.Structure) -> None:
    r"""Write binary data from one or more `ctypes.Structure`\ s
    to a stream writer.

    Parameters
    ----------
    writer : `asyncio.StreamWriter`
        Asynchronous stream writer.
    structs : `ctypes.Structure`
        One or more structures to write.
    """
    for struct in structs:
        writer.write(bytes(struct))
    await writer.drain()
