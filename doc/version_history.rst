.. py:currentmodule:: lsst.ts.tcpip

.. _lsst.ts.tcpip.version_history:

###############
Version History
###############

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
