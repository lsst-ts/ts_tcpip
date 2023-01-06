.. py:currentmodule:: lsst.ts.tcpip

.. _lsst.ts.tcpip:

#############
lsst.ts.tcpip
#############

Python code to support TCP/IP communication using asyncio.

.. _lsst.ts.tcpip-user_guide:

User Guide
==========

The basic classes are:

* `Client`: a TCP/IP client.
  One use case is CSCs that communicate via TCP/IP with low-level controllers.
  Providing a connect_callback makes it easy to report the connection state as an event, and also allows you to detect and handle a failed connection.
* `OneClientServer`: a TCP/IP server that only accepts a single client connection at a time (rejecting extra attempts to connect).
  One common use case is mock servers in CSC packages.

An example of using these two classes together is provided in `tests/test_example.py <https://github.com/lsst-ts/ts_tcpip/blob/develop/tests/test_example.py>`_.
This example is written as a unit test in order to avoid bit rot.

Both classes are designed so to be inherited from, in order to add application-specific behavior.
An example of inheriting from `OneClientServer` is ``MockDomeController`` in ts_atdome, and indeed most mock controllers in CSC packages inherit from `OneClientServer`.
An example of inheriting from `Client` is ``CommandTelemetryClient`` in ts_hexrotcomm.


Details of using `asyncio.StreamReader` and `asyncio.StreamWriter`
------------------------------------------------------------------

The asyncio documentation is good, but I found a few things surprising.
`Client` and `OneClientServer` are designed to hide some of these details, but this information may still be helpful.

In the examples below ``reader`` is an `asyncio.StreamReader` and ``writer`` is an `asyncio.StreamWriter`.

* You may construct a ``reader`` and ``writer`` using `asyncio.open_connection`::

    import asyncio

    reader, writer = await asyncio.open_connection(host=..., port=...)

    # When finished, close the writer using:
    await tcpip.close_stream_writer(writer)

  The `Client` class provides a high-level wrapper around asyncio.open_connection.

* When you write data, be sure to call drain, else the data may not actually be written::

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

* You can only reliably detect a closed connection in the stream reader;
  writing to stream writer after the other end has diconnected does not raise an exception.
  
* When a reader is closed, ``reader.at_eof()`` is not false right away,
  but it does go to false if you read data, or if you simply wait long enough.
  
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

* To read and write a binary struct, define a `ctypes.Structure` and use `read_into` and `write_from`.
  For example::

    import ctypes

    from lsst.ts import tcpip


    class TrivialStruct(ctypes.Structure):
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
