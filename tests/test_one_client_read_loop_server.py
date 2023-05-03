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

from lsst.ts import tcpip


class OneClientReadLoopServerTestCase(tcpip.BaseOneClientReadLoopServerTestCase):
    async def create_server(self) -> tcpip.OneClientReadLoopServer:
        return tcpip.TestOneClientReadLoopServer()

    async def test_read_and_dispatch(self) -> None:
        fail_index = 3
        async with self.create_server_and_client():
            for i in range(5):
                test_line = f"Test data {i}."
                if i == fail_index:
                    self.server.fail_next_read = True
                await self.client.write_str(line=test_line)
                if i > fail_index:
                    assert not self.server.connected
                else:
                    received_data = await self.server.get_next_data()
                    assert received_data == test_line
