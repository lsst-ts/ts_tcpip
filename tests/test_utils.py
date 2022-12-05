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

import asyncio
import ctypes
import logging
import typing
import unittest

import numpy as np
import numpy.random
from lsst.ts import tcpip  # type: ignore

random = numpy.random.default_rng(47)


# Standard timeout for TCP/IP messages (sec).
TCP_TIMEOUT = 1

# How long to wait for a OneClientServer to start (sec).
START_TIMEOUT = 1

# How long to wait for OneClientServer to detect
# that a client has connected (sec).
CONNECTED_TIMEOUT = 1

logging.basicConfig()

# Length of arrays in the c struct
ARRAY_LEN = 5


class SampleStruct(ctypes.Structure):
    """Sample ctypes struct for testing binary read/write"""

    _pack_ = 1
    _fields_ = [
        ("ushort_0", ctypes.c_ushort),
        ("uint_0", ctypes.c_uint),
        ("int32_0", ctypes.c_int32),
        ("int64_0", ctypes.c_int64),
        ("uint32_0", ctypes.c_uint32),
        ("uint64_0", ctypes.c_uint64),
        ("double_0", ctypes.c_double),
        ("float_0", ctypes.c_float),
        ("ushort_arr_0", ctypes.c_ushort * ARRAY_LEN),
        ("uint_arr_0", ctypes.c_uint * ARRAY_LEN),
        ("int32_arr_0", ctypes.c_int32 * ARRAY_LEN),
        ("int64_arr_0", ctypes.c_int64 * ARRAY_LEN),
        ("uint32_arr_0", ctypes.c_uint32 * ARRAY_LEN),
        ("uint64_arr_0", ctypes.c_uint64 * ARRAY_LEN),
        ("double_arr_0", ctypes.c_double * ARRAY_LEN),
        ("float_arr_0", ctypes.c_float * ARRAY_LEN),
    ]


class UtilsTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Set True to make self.connect_callback raise an exception
        self.callbacks_raise: bool = False

        # Queue of connected values; filled by self.connected_callback
        self.connect_queue: asyncio.Queue = asyncio.Queue()

        log = logging.getLogger()
        log.setLevel(logging.INFO)

        self.reader: typing.Optional[asyncio.StreamReader] = None
        self.writer: typing.Optional[asyncio.StreamWriter] = None
        self.server = tcpip.OneClientServer(
            host=tcpip.LOCAL_HOST,
            port=0,
            name="test",
            log=log,
            connect_callback=None,
        )
        await asyncio.wait_for(self.server.start_task, timeout=START_TIMEOUT)
        (self.reader, self.writer) = await asyncio.open_connection(
            host=tcpip.LOCAL_HOST, port=self.server.port
        )
        await asyncio.wait_for(self.server.connected_task, timeout=CONNECTED_TIMEOUT)
        assert self.server.connected

    async def asyncTearDown(self) -> None:
        if self.writer is not None:
            await tcpip.close_stream_writer(self.writer)
        await self.server.close()

    async def check_read_write(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # Write at least 2 sets of data,
        # to detect extra data being written.
        for i in range(2):
            data = self.make_random_data()
            await tcpip.write_from(writer, data)
            read_data = SampleStruct()
            await tcpip.read_into(reader, read_data)
            for field_name, c_type in data._fields_:
                try:
                    # array
                    nelts = len(getattr(data, field_name))
                    assert nelts == ARRAY_LEN
                    assert (
                        getattr(data, field_name)[:]
                        == getattr(read_data, field_name)[:]
                    )
                except TypeError:
                    # scalar
                    assert getattr(data, field_name) == getattr(read_data, field_name)

    def make_random_data(self) -> SampleStruct:
        # random.integers cannot easily generate values > max int64,
        # so don't bother to try
        max_rand_int = np.iinfo(np.int64).max
        data = SampleStruct()
        for field_name, c_type in data._fields_:
            dtype = np.dtype(c_type)  # type: ignore
            if dtype.subdtype is None:
                scalar_dtype = dtype
            else:
                scalar_dtype = dtype.subdtype[0]

            try:
                iinfo = np.iinfo(scalar_dtype)
                value = random.integers(
                    low=iinfo.min,
                    high=min(iinfo.max, max_rand_int),
                    size=dtype.shape,
                )
            except ValueError:
                # Float, not int
                value = random.random(dtype=scalar_dtype, size=dtype.shape) - 0.5

            if dtype.shape:
                getattr(data, field_name)[:] = value[:]
            else:
                setattr(data, field_name, value)

        return data

    async def test_close_stream_writer(self) -> None:
        assert self.writer is not None
        assert not (self.writer.is_closing())
        await tcpip.close_stream_writer(self.writer)
        assert self.writer.is_closing()
        await tcpip.close_stream_writer(self.writer)
        assert self.writer.is_closing()

    async def test_read_write(self) -> None:
        assert self.reader
        assert self.writer
        await self.check_read_write(reader=self.reader, writer=self.server.writer)
        await self.check_read_write(reader=self.server.reader, writer=self.writer)


if __name__ == "__main__":
    unittest.main()
