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
