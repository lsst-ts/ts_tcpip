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

from lsst.ts import tcpip


class OneClientReadLoopServerTestCase(tcpip.BaseOneClientServerTestCase):
    server_class = tcpip.TestOneClientReadLoopServer

    async def test_read_and_dispatch(self) -> None:
        num_good_writes = 5
        async with self.create_server(
            connect_callback=self.connect_callback
        ) as server, self.create_client(server) as client:
            await self.assert_next_connected(True)
            for i in range(num_good_writes + 1):
                print(f"{i=}; {client.connected=}")
                test_line = f"Test data {i}."
                if i == num_good_writes:
                    server.fail_next_read = True
                await client.write_str(line=test_line)
                await asyncio.sleep(0.1)
                if i < num_good_writes:
                    received_data = await server.get_next_data()
                    assert received_data == test_line
                else:
                    await self.assert_next_connected(False)
                    assert not server.connected
                    assert not client.connected

    async def test_expected_heartbeat(self) -> None:
        async with self.create_server(
            connect_callback=self.connect_callback,
            run_heartbeat_monitor_task=True,
        ) as server, self.create_client(server, run_heartbeat_send_task=True):
            await self.assert_next_connected(True)
            assert not server.read_loop_task.done()

            await asyncio.sleep(0.1)
            # The read_loop_task should not be done because the client
            # sends a heartbeat and the server expects it..
            assert not server.read_loop_task.done()
            assert server.connected

    async def test_unexpected_heartbeat(self) -> None:
        async with self.create_server(
            connect_callback=self.connect_callback
        ) as server, self.create_client(server, run_heartbeat_send_task=True):
            await self.assert_next_connected(True)
            assert not server.read_loop_task.done()

            await asyncio.sleep(0.1)
            # The read_loop_task should be done because the client
            # unexpectedly sends a heartbeat.
            assert server.read_loop_task.done()
            assert not server.connected

    async def test_no_heartbeat_received(self) -> None:
        async with self.create_server(
            connect_callback=self.connect_callback,
            run_heartbeat_monitor_task=True,
            max_heartbeat_interval=1.0,
        ) as server, self.create_client(server):
            await self.assert_next_connected(True)
            assert not server.read_loop_task.done()

            await asyncio.sleep(0.1)
            # The read_loop_task should not be done because the client
            # has not yet had the opportunity to send a heartbeat.
            assert not server.read_loop_task.done()
            assert server.connected

            await asyncio.sleep(1.1)
            # The read_loop_task should be done because the client
            # did not send a heartbeat.
            assert server.read_loop_task.done()
            assert not server.connected
