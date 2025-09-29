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

from __future__ import annotations

import abc
import asyncio
import logging
import typing

from lsst.ts import utils

from .base_client_or_server import ConnectCallbackType
from .constants import DEFAULT_ENCODING, DEFAULT_LOCALHOST, DEFAULT_TERMINATOR
from .one_client_server import OneClientServer

__all__ = ["OneClientReadLoopServer", "DEFAULT_MAX_HEARTBEAT_INTERVAL"]

# Default maximum time [sec] between heartbeats before assuming that the
# connection has been dropped.
DEFAULT_MAX_HEARTBEAT_INTERVAL = 10.0

# Heartbeat monitor interval [sec].
HEARTBEAT_MONITOR_INTERVAL = 1.0


class OneClientReadLoopServer(OneClientServer):
    """A OneClientServer that reads and processes data in a loop.

    Parameters
    ----------
    port : `int`
        IP port for this server. If 0 then randomly pick an available port
        (or ports, if listening on multiple sockets).
        0 is strongly recommended for unit tests.
    host : `str` or `None`
        IP address for this server. The default is `DEFAULT_LOCALHOST`.
        Specify `LOCALHOST_IPV4` to force IPV4 or `LOCALHOST_IPV6` for IPV6.
        If `None` then bind to all network interfaces
        (e.g. listen on an IPv4 socket and an IPv6 socket).
        Warning: `None` can cause trouble with ``port=0``; see ``port``
        in the Attributes section for more information.
    log : `logging.Logger`
        Logger.
    connect_callback : callable or `None`, optional
        Asynchronous or (deprecated) synchronous function to call when
        when a client connects or disconnects.
        If the other end (client) closes the connection, it may take
        ``monitor_connection_interval`` seconds or longer to notice.
        The function receives one argument: this `OneClientServer`.
    name : `str`, optional
        Name used for log messages, e.g. "Commands" or "Telemetry".
    encoding : `str`
        The encoding used by `read_str` and `write_str`, `read_json`,
         and `write_json`.
    terminator : `bytes`
        The terminator used by `read_str` and `write_str`, `read_json`,
         and `write_json`.
    run_heartbeat_monitor_task : `bool`
        Should the task to monitor heartbeats be started or not? The default
        is False because the OneClientReadLoopServer delegates reading data
        from the socket to subclasses and by default sending heartbeats would
        be a breaking change.
    max_heartbeat_interval : `float`
        The max time [sec] between heartbeatsbefore the connection is assumed
        to have dropped. The default is `DEFAULT_MAX_HEARTBEAT_INTERVAL` sec.
    **kwargs : `dict` [`str`, `typing.Any`]
        Additional keyword arguments for `asyncio.start_server`,
        beyond host and port.

    Attributes
    ----------
    read_loop_task : `asyncio.Future`
        A task that reads data from the reader in a loop.
    plus...
        Attributes provided by parent classes `OneClientServer`.
    """

    def __init__(
        self,
        *,
        port: int | None,
        host: str | None = DEFAULT_LOCALHOST,
        log: logging.Logger,
        connect_callback: ConnectCallbackType | None = None,
        name: str = "",
        encoding: str = DEFAULT_ENCODING,
        terminator: bytes = DEFAULT_TERMINATOR,
        run_heartbeat_monitor_task: bool = False,
        max_heartbeat_interval: float = DEFAULT_MAX_HEARTBEAT_INTERVAL,
        **kwargs: typing.Any,
    ) -> None:
        self.read_loop_task = utils.make_done_future()

        super().__init__(
            host=host,
            port=port,
            log=log,
            connect_callback=connect_callback,
            monitor_connection_interval=0,
            name=name,
            encoding=encoding,
            terminator=terminator,
            **kwargs,
        )

        # Should the task to monitor heartbeats be started or not?
        self.run_heartbeat_monitor_task = run_heartbeat_monitor_task
        # Maximum time [sec] between heartbeats before assuming that the
        # connection has been dropped.
        self.max_heartbeat_interval = max_heartbeat_interval
        # TAI UNIX timestamp [sec] at which the latest heartbeat was received.
        self.heartbeat_received_tai: float | None = None
        # Monitor received heartbeats.
        self.monitor_heartbeats_task = utils.make_done_future()
        # Start time [TAI sec] of the monitor received heartbeats task.
        self.monitor_heartbeats_task_start: float | None = None

    async def call_connect_callback(self) -> None:
        """A client has connected or disconnected."""
        await super().call_connect_callback()
        if self.connected:
            self.log.info("Client connected.")
            self.read_loop_task.cancel()
            self.monitor_heartbeats_task.cancel()

            try:
                await self.read_loop_task
            except asyncio.CancelledError:
                pass

            try:
                await self.monitor_heartbeats_task
            except asyncio.CancelledError:
                pass

            self.read_loop_task = asyncio.create_task(self.read_loop())
            if self.run_heartbeat_monitor_task:
                self.monitor_heartbeats_task = asyncio.create_task(
                    self.monitor_received_heartbeats()
                )
        else:
            self.log.info("Client disconnected.")

    async def read_loop(self) -> None:
        """Read incoming data and handle them.

        The actual reading is deferred to the `read_and_dispatch` method and
        needs to be implemented by subclasses.
        """
        try:
            self.log.info(f"The read_loop begins connected? {self.connected}")
            while self.connected:
                self.log.debug("Waiting for next incoming data.")
                await self.read_and_dispatch()
        except Exception as e:
            self.log.exception(f"read_loop failed. Disconnecting. {e!r}")
            await self.close_client(cancel_read_loop_task=False)

    @abc.abstractmethod
    async def read_and_dispatch(self) -> None:
        """Read, parse, and dispatch one item of data.

        Subclasses need to implement this method such that it reads and parses
        data and then dispatches handling the data to a method suitable for the
        subclass. Methods that might be helpful include:

        * `read_json` to read json-encoded data
        * `read_str` to read terminated strings
        * `read_into` to read binary structs
        """
        raise NotImplementedError()

    async def handle_received_heartbeat(self) -> None:
        """Handle a received heartbeat.

        Raises
        ------
        RuntimeError
            In case a heartbeat is received but
            run_heartbeat_monitor_task is False.
        """
        if not self.run_heartbeat_monitor_task:
            raise RuntimeError(
                "Unexpectedly received a heartbeat. Please set `run_heartbeat_monitor_task` to True."
            )
        self.heartbeat_received_tai = utils.current_tai()

    async def monitor_received_heartbeats(self) -> None:
        """Monitor received heartbeats.

        Assume that the connection has dropped if no heartbeat was received
        for too long.
        """
        monitor_heartbeats_task_start = utils.current_tai()

        # Wait until the server starts receiving heartbeats.
        while self.heartbeat_received_tai is None:
            if (
                utils.current_tai() - monitor_heartbeats_task_start
                >= self.max_heartbeat_interval
            ):
                self.log.debug("No heartbeat received after client connected.")
                break
            await asyncio.sleep(HEARTBEAT_MONITOR_INTERVAL)

        # If the server has received at least one heartbeat then make sure
        # that is keeps happening. If the server still hasn't received a
        # heartbeat then the next loop will immediately stop.
        if self.heartbeat_received_tai is not None:
            while (
                utils.current_tai() - self.heartbeat_received_tai
                < self.max_heartbeat_interval
            ):
                self.log.debug(
                    f"Received heartbeat. Sleeping for {HEARTBEAT_MONITOR_INTERVAL} sec."
                )
                await asyncio.sleep(HEARTBEAT_MONITOR_INTERVAL)

        # No heartbeat received for too long so assume the client connection
        # has dropped.
        self.log.warning(
            f"No heartbeat received for more than {self.max_heartbeat_interval} seconds. "
            "Assuming the connection with the client has dropped."
        )

        self.heartbeat_received_tai = None
        await self.close_client()

    async def close_client(self, cancel_read_loop_task: bool = True) -> None:
        """Stop the read loop and close the client.

        Parameters
        ----------
        cancel_read_loop_task : `bool`
            Cancel the read loop task or not? Defaults to True and should be
            False when called from the read loop task itself.
        """
        if cancel_read_loop_task:
            self.log.debug("Cancelling read_loop_task.")
            self.read_loop_task.cancel()
            try:
                await self.read_loop_task
            except asyncio.CancelledError:
                pass
        self.log.debug("Closing client.")
        await super().close_client()
