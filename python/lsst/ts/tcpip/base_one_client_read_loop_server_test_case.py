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

import abc
import asyncio
import contextlib
import logging
import unittest
from typing import AsyncGenerator

from .client import Client
from .one_client_read_loop_server import OneClientReadLoopServer

__all__ = ["BaseOneClientReadLoopServerTestCase"]

# Standard timeout in seconds.
TIMEOUT = 2


class BaseOneClientReadLoopServerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.log = logging.getLogger(type(self).__name__)

    @contextlib.asynccontextmanager
    async def create_server_and_client(self) -> AsyncGenerator[None, None]:
        self.server = await self.create_server()
        try:
            await self.server.start_task

            async with Client(
                host=self.server.host, port=self.server.port, log=self.log, name="test"
            ) as self.client:
                await asyncio.wait_for(self.server.connected_task, timeout=TIMEOUT)
                assert self.client.connected
                yield
        finally:
            await self.server.close()

    @abc.abstractmethod
    async def create_server(self) -> OneClientReadLoopServer:
        raise NotImplementedError()
