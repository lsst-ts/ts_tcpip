.. py:currentmodule:: lsst.ts.tcpip

.. _lsst.ts.tcpip.version_history:

###############
Version History
###############

v0.3.3
------

Changes:

* Fix cleanup in a unit test file.
* Add ``Jenkinsfile``.

v0.3.2
------

Changes:

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
