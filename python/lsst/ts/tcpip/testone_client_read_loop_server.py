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
import logging

from .constants import LOCAL_HOST
from .one_client_read_loop_server import OneClientReadLoopServer

__all__ = ["TestOneClientReadLoopServer"]


class TestOneClientReadLoopServer(OneClientReadLoopServer):
    """An implementation of OneClientReadLoopServer for unit test
    purposes.
    """

    def __init__(self) -> None:
        log = logging.getLogger()
        super().__init__(
            host=LOCAL_HOST,
            port=0,
            log=log,
            name="TestOneClientReadLoopServer",
        )

        self._data_queue: asyncio.Queue = asyncio.Queue()

        # A boolean to make the next read fail or not. This is used by unit
        # tests to mock connection errors.
        self.fail_next_read = False

    async def read_and_dispatch(self) -> None:
        if self.fail_next_read:
            self.fail_next_read = False
            raise ConnectionError("Mock connection error for unit tests.")
        data = await self.read_str()
        await self._data_queue.put(data)

    async def get_next_data(self) -> str:
        """Get the next data.

        Under the hood a FIFO queue is used so the oldest data gets returned.

        Returns
        -------
        str :
            The next data.
        """
        return await self._data_queue.get()
