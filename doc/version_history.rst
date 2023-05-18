.. py:currentmodule:: lsst.ts.tcpip

.. _lsst.ts.tcpip.version_history:

###############
Version History
###############

v1.1.2
------

* `BaseClientOrServer`: improve the exception raised by read_json for invalid data, so that the messagse includes the invalid data.

v1.1.1
------

* Fix backwards compatibility issues with version 1.0:

  * `Client`: allow non-keyword constructor arguments.
  * `OneClientServer`: allow non-keyword constructor arguments and remove the (new in v1.1.0) default value for the ``host`` argument.
    Note that `OneClientReadLoopServer` is unchanged: the constructor arguments are keyword-only and ``host`` has a default value.

v1.1.0
------

* Deprecation warning: do not access the ``reader``, ``writer``, or (in the case of `OneClientServer`) ``server`` attributes.
  Use the provided read and write methods, instead, and let `OneClientServer` manage its asyncio server.
* Add `OneClientReadLoopServer`: an abstract subclass of `OneClientServer` that includes a read loop.
* `BaseClientOrServer`: add ``read_str``, ``write_str``, ``read_json`` and ``write_json`` methods.
* `BaseClientOrServer` and subclasses:

      This also applies to the `Client` and `OneClientServer` subclasses.
    * Add optional ``encoding`` and ``terminator`` constructor arguments.
    * Make constructor arguments keyword-only.

* Add `BaseOneClientServerTestCase`: a base clase for unit tests of `OneClientServer` and subclasses.
* Add new constants:

    * ``DEFAULT_LOCALHOST``, the same as deprecated ``LOCAL_HOST``
    * ``DEFAULT_TERMINATOR``, the same as deprecated ``TERMINATOR``.
    * ``DEFAULT_ENCODING``.

* `Client`:

    * Make constructor arguments keyword-only.
    * Fix setting ``done_task`` done.

* `OneClientServer` and subclasses:

    * Make constructor arguments keyword-only.
    * Provide a default for the ``host`` constructor argument: ``DEFAULT_LOCALHOST``.
    * Fix setting ``done_task`` done.

* Improve class documentation.
* Use ts_pre_commit_conf.
* Remove scons support.

v1.0.1
------

* pre-commit: update black to 23.1.0, isort to 5.12.0, mypy to 1.0.0, and pre-commit-hooks to v4.4.0.
* ``Jenkinsfile``: do not run as root.

v1.0.0
------

* Deprecation warning: the ``connect_callback`` `OneClientServer` constructor argument should now be asynchronous.
* Add `Client` class: a TCP/IP client modeled on `OneClientServer`.
* Add constants ``LOCALHOST_IPV4`` and ``LOCALHOST_IPV6`` and deprecated constant ``LOCAL_HOST``.
* Modify `OneClientServer`:

    * The ``connect_callback`` function may now be asynchronous, and synchronous functions are deprecated.
    * Add read and write methods that check if a client is connected.
    * Add optional ``monitor_connection_interval`` constructor argument.
      The default value matches the current behavior, but you can now specify 0 to disable monitoring.
    * Replace optional ``family`` constructor argument with ``**kwargs``, adding flexibility.
    * Make the ``name`` constructor argument optional.
    * Wait for the asyncio server to close in `OneClientServer.close`.

* `read_into` bug fix: read exactly the correct number of bytes, instead of up to the desired number.
* Change `ConnectionResetError` to `ConnectionError` everywhere.
  This catches a few extra conditions and is shorter.
* Expand some unit tests to test IPV6, if supported, else skip that sub test.

v0.4.4
------

* Modernize conda/meta.yaml.

v0.4.3
------

* Run isort.
* Add isort and mypy to pre-commit and update other pre-commit tasks.

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
