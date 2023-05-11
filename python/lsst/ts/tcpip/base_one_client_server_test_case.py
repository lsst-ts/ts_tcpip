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
import contextlib
import logging
import unittest
from typing import Any, AsyncGenerator, Literal

from .base_client_or_server import BaseClientOrServer, ConnectCallbackType
from .client import Client
from .constants import DEFAULT_LOCALHOST
from .one_client_server import OneClientServer

__all__ = ["BaseOneClientServerTestCase"]

# Standard timeout in seconds.
STD_TIMEOUT = 2


class BaseOneClientServerTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class for unit tests of subclasses of OneClienServer.

    Subclasses must set server_class to a subclass of OneClientServer.
    """

    server_class: type[OneClientServer] | None = None

    def run(self, result: Any = None) -> None:
        """Create a log and initialize server = client = None.

        Unlike setUp, a user cannot forget to override this.
        (This is also a good place for context managers).
        """
        self.log = logging.getLogger(type(self).__name__)
        # A queue filled by connect_callback; initialized by create_server.
        self.connect_queue: asyncio.Queue | None = None
        super().run(result=result)

    async def assert_next_connected(
        self, connected: bool, timeout: int = STD_TIMEOUT
    ) -> None:
        """Assert results of next connect_callback.

        Parameters
        ----------
        connected : `bool`
            Is a client connected to the server connected?
        timeout : `float`
            Time to wait for connect_callback (seconds).

        Raises
        ------
        `AssertionError`
            If oldest queued connected value does not match ``connected``.
        `asyncio.TimeoutError`
            If connect_callback is not called in time.
        `RuntimeError`
            If self.connect_queue is not None, which means
            you have not called create_server.
        """
        if self.connect_queue is None:
            raise RuntimeError("You must call create_server")
        next_connected = await asyncio.wait_for(
            self.connect_queue.get(), timeout=timeout
        )
        assert connected == next_connected

    async def connect_callback(self, server: BaseClientOrServer) -> None:
        """Callback function for a server.

        Add server.connected to self.connect_queue.
        """
        print(f"connect_callback: connected={server.connected}")
        if self.connect_queue is None:
            raise RuntimeError("You must call create_server")
        self.connect_queue.put_nowait(server.connected)

    @contextlib.asynccontextmanager
    async def create_server(
        self,
        *,
        port: int = 0,
        host: str = DEFAULT_LOCALHOST,
        connect_callback: ConnectCallbackType | None | Literal[True] = True,
        name: str = "",
        **kwargs: Any,
    ) -> AsyncGenerator[OneClientServer, None]:
        """Create a server of the class being tested.

        Parameters
        ----------
        port : `int`, optional
            IP port; 0 (the default) to pick a random available port.
        host : `str`, optional
            IP host address of server. Defaults to `DEFAULT_LOCALHOST`.
        connect_callback : callable or `None` or `True`, optional
            Asynchronous or (deprecated) synchronous function to call when
            when a client connects or disconnects.
            If `True` (the default): call self.connect_callback.
            If `None`: no callback.
            The function receives one argument: this `OneClientServer`.
        name : `str`, optional
            Name used for log messages, e.g. "Commands" or "Telemetry".
        **kwargs : `dict` [`str`, `Any`]
            Additional keywords for the server constructor.
            Must not include log.

        Raises
        ------
        `RuntimeError`
            If you forgot to set class attribute server_class
            (it defaults to None, which is not a valid value).
        """
        if self.server_class is None:
            raise RuntimeError(
                "You must set class variable server_class to OneClientServer or a subclass"
            )
        self.connect_queue = asyncio.Queue()
        if connect_callback is True:
            connect_callback = self.connect_callback
        async with self.server_class(
            host=host,
            port=port,
            log=self.log,
            connect_callback=connect_callback,
            name=name,
            **kwargs,
        ) as server:
            yield server  # type: ignore # mypy bug?

    @contextlib.asynccontextmanager
    async def create_client(
        self, server: OneClientServer, *, wait_connected: bool = True, **kwargs: Any
    ) -> AsyncGenerator[Client, None]:
        """Make a TCP/IP client that talks to server.

        Parameters
        ----------
        server : `OneClientServer`
            Server to connect to. This provides host and port arguments
            to `Client`.
        wait_connected : `bool`
            Wait for the server to detect the connection before returning?
            True by default.
        **kwargs : `dict` [`str`, `Any`]
            Additional keywords for `Client`.
            Must not include host, port, or log.

        Returns
        -------
        client : `tcpip.Client`
            The TCP/IP client.
        """
        assert (
            server is not None
        ), "You must call create_server before calling create_client"
        async with Client(
            host=server.host, port=server.port, log=self.log, **kwargs
        ) as client:
            if wait_connected:
                await asyncio.wait_for(server.connected_task, timeout=STD_TIMEOUT)
            yield client  # type: ignore # mypy bug?
