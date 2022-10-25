.. py:currentmodule:: lsst.ts.tcpip

.. _lsst.ts.tcpip:

#############
lsst.ts.tcpip
#############

Python code to support TCP/IP communication using asyncio.

.. _lsst.ts.tcpip-user_guide:

User Guide
==========

Here is an overview of how to use this package.

This guide also serves as a very basic tutorial for using `asyncio streams`_,
and covers a few points I found unclear in that documentation.

In the examples below ``reader`` is an `asyncio.StreamReader` and ``writer`` is an `asyncio.StreamWriter`.

* Use `asyncio.open_connection` to construct a TCP/IP client.
  For example::

    import asyncio

    reader, writer = await asyncio.open_connection(host=..., port=...)

* When you write data, be sure to call drain::

    writer.write(data_bytes)
    await writer.drain()

* When you read data, check for a closed connection as follows::

    try:
        data = reader.readuntil(tcpip.TERMINATOR) # or reader.read or reader.readline
        # If data is empty then the connection is closed and reader.at_eof() will be True.
        # If there was unread data on the reader, then a partial result will be returned.
        # reader.at_eof() will be true if the result is partial.

        # There are other read methods that handle EOF differently.
        # reader.readexactly and tcpip.read_into raise asyncio.IncompleteReadError
        # if the connection is closed before enough data is available.
    except (asyncio.IncompleteReadError, ConnectionResetError):
        # Connection is closed.
        # Do something to tell your application not to write any more data,
        # such as cancelling the write loop...
        
        # Close the writer
        await lsst.ts.tcpip.close_stream_writer(writer)

        # Deal with lack of data, e.g. by raising an exception,
        # or returning None, or...

  Note that you can only reliably detect a closed connection in the stream reader;
  writing to stream writer after the other end has diconnected does not raise an exception.
  Also note that when a reader is closed, ``reader.at_eof()`` is not false right away,
  but it go false when you read data, or if you simply wait long enough.
  
* To read and write text data::

    # Reading
    try:
        read_bytes = reader.readuntil(tcpip.TERMINATOR)
        read_text = read_data.decode().strip()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        # Connection is closed
        ...handle the closed connection

    # Writing
    text_to_write = "some text to write"
    writer.write(text_to_write.encode() + tcpip.TERMINATOR)
    await writer.drain()


  Note that ``tcpip.TERMINATOR = b"\r\n"``; this is a common way to terminate TCP/IP text.

* To read and write binary data, define a `ctypes.Structure` and use `read_into` and `write_from`.
  For example::

    import ctypes

    from lsst.ts import tcpip


    class TrivialStruct(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("a_double", ctypes.c_double),
            ("three_ints", ctypes.c_int64 * 3)

    # Reading
    data = TrivialStruct()
    try:
        await tcpip.read_into(reader, data)
    except (asyncio.IncompleteReadError, ConnectionResetError):
        # Connection is closed
        ...handle the closed connection

    # Writing (write_from does call writer.drain)
    data = TrivialStruct()
    data.a_double = 1.2e3
    data.three_ints[:] = (-1, 2, 3)
    await write_from(writer, data)

* When you are done with a TCP/IP stream, close the stream writer (you cannot close a stream reader).
  To close a stream writer, call `close_stream_writer`::

    from lsst.ts import tcpip

    await tcpip.close_stream_writer(writer)

  This convenience function calls `asyncio.StreamWriter.close` and `asyncio.StreamWriter.wait_closed`.
  It also catches and ignores `ConnectionResetError`, which is raised if the writer is already closed.

  Warning: `asyncio.StreamWriter.wait_closed` may raise `asyncio.CancelledError` if the writer is being closed.
  `close_stream_writer` does not catch and ignore that exception, because I felt that was too risky.

* `OneClientServer` is a TCP/IP server that allows at most one client to connect.
  If an additional client tries to connect, the server closes the server-side stream writer to that client and ignores all data from it.

  When a client is connected, `OneClientServer.connected` is true and the ``reader`` and ``writer`` attributes are instances of `asyncio.StreamReader` and `asyncio.StreamWriter`.
  When `OneClientServer.connected` is false, do not access the ``reader`` and ``writer`` attributes.
  For example, here is a trivial echo server that also makes sure ``connect_callback`` is called when the client closes its connection::

    from __future__ import annotations

    import asyncio
    import logging

    from lsst.ts import tcpip


    class EchoServer(tcpip.OneClientServer):
        """An echo server that only serves one client at a time.

        Parameters
        ----------
        port
            Port number; 0 to pick an available port.
        """

        def __init__(self, port: int) -> None:
            self.log = logging.getLogger("EchoServer")
            self.read_loop_task: asyncio.Future = asyncio.Future()
            super().__init__(
                host=tcpip.LOCAL_HOST,
                port=port,
                name=self.log.name,
                log=self.log,
                connect_callback=self.connect_callback,
            )

        @classmethod
        async def amain(cls, port: int) -> None:
            """Run the echo server

            Parameters
            ----------
            port
                Port number; 0 to pick an available port.
            """
            print("Starting echo server; use ctrl-C to quit")
            echo_server = cls(port=port)
            await echo_server.start_task
            print(f"Echo server running on port {echo_server.port}")
            await asyncio.Future()

        def connect_callback(self, server: EchoServer) -> None:
            """A client has connected or disconnected."""
            self.read_loop_task.cancel()
            if server.connected:
                self.read_loop_task = asyncio.create_task(self.read_loop())

        async def read_loop(self) -> None:
            """Read and echo text."""
            try:
                while self.connected:
                    try:
                        data_bytes = await self.reader.readuntil(tcpip.TERMINATOR)
                        self.log.debug("read %s", data_bytes)
                    except (asyncio.IncompleteReadError, ConnectionResetError):
                        self.log.info("Connection lost")
                        break

                    self.writer.write(data_bytes)
                    await self.writer.drain()
            except Exception:
                self.log.exception("read_loop failed")
            finally:
                asyncio.create_task(self.close_client())

.. _asyncio streams: https://docs.python.org/3/library/asyncio-stream.html

.. _lsst.ts.tcpip-pyapi:

Python API reference
====================

.. automodapi:: lsst.ts.tcpip
   :no-main-docstr:
   :no-inheritance-diagram:

.. _lsst.ts.tcpip-contributing:

Contributing
============

``lsst.ts.tcpip`` is developed at https://github.com/lsst-ts/ts_tcpip.
You can find Jira issues for this module at `labels=ts_tcpip <https://jira.lsstcorp.org/issues/?jql=project%20%3D%20DM%20AND%20labels%20%20%3D%20ts_tcp>`_.

Version History
===============

.. toctree::
    version_history
    :maxdepth: 1
