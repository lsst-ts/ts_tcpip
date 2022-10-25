.. py:currentmodule:: lsst.ts.tcpip

.. _lsst.ts.tcpip.version_history:

###############
Version History
###############

v0.4.2
------

* Fix unit tests to wait for `OneClientServer`\ s connect_task after making a client connection.
* `OneClientServer`: test multiple simultaneous connection attempts.
* Modernize unit tests to use bare assert.

v0.4.1
------

* Add a timeout to `close_stream_writer` in hopes of avoiding an intermittent hang (a bug in Python).
* Build with pyproject.toml.

v0.4.0
------

* Remove dependency on ts_utils.
* Modernize the continuous integration ``Jenkinsfile``.
* doc/conf.py: tweak to make linters happier.
* git ignore .hypothesis.
* ``setup.cfg``: specify asyncio_mode = auto.

v0.3.8
------

* Fix the conda build.

Requirements:

* ts_utils

v0.3.7
------

* `OneClientServer`:

    * Monitor for a dropped client connection.
      Close the client and call connect_callback if detected.
    * Fix a bug whereby accepting a new connection may not call the ``connect_callback`` (DM-34694).

* Fix documentation that falsely claimed you must read from an `asyncio.StreamReader` in order to detect if the other end drops the connection.

v0.3.6
------

* `write_from`: eliminate a race condition that allows tasks to interleave data.

v0.3.5
------

* Fix a new mypy error by not checking DM's `lsst/__init__.py` files.

v0.3.4
------

* Enhance the User Guide:

    * Add a section on monitoring the stream reader when no data is expected.
    * Fix ``catch`` -> ``except`` in examples.

v0.3.3
------

* Fix cleanup in a unit test file.
* Add ``Jenkinsfile``.

v0.3.2
------

* Prevent pytest from checking the generated ``version.py`` file.
  This is necessary in order to prevent ``mypy`` from checking that file.

v0.3.1
-------

* Configure pytest to run mypy.

v0.3.0
------

* The conda package now gets built for noarch so it is usable on all platforms.

v0.2.0
------

* OneClientServer:

    * Change ``port`` to remain 0 if the user specifies port=0 and the server listens on more than one socket.
      This avoids ambiguity.
    * Add ``family`` constructor argument to support IPv6.
    * Rename the ``connect_callback`` attribute to ``__connect_callback``
      to make it easier to inherit from `OneClientServer`.

v0.1.0
------

First release.
