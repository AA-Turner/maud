Simple doc comments for C++
===========================

A Sphinx extension which scans C++ sources and headers
for `///` comments. [libclang](https://libclang.readthedocs.io)
is used to associate these with declarations. These can then be
referenced using `.. trike-put::` and other directives.

For example, given the following C++ and rst sources in your project:

``frob.cxx``
    .. code-block:: c++

      /// Frobnicates the :cpp:var:`whatsit` register.
      ///
      /// :return: false if no frobnication was necessary
      bool frobnicate();

``index.rst``
    .. code-block:: rst

      .. trike-function:: void frobnicate()

The ``trike-function`` directive above will render equivalently to
a [`cpp:function`](https://www.sphinx-doc.org/en/master/usage/domains/cpp.html#directive-cpp-function)
directive with content drawn from the `///`.

.. cpp:function:: void frobnicate()

  Frobnicates the :cpp:var:`whatsit` register.

  :return: false if no frobnication was necessary

The content of ``///`` is interpreted as ReStructuredText, so
they can be as expressive as the rest of your documentation. Of particular
note for those who have used other apidoc systems: cross references from
``///`` comments to labels defined in `*.rst` (or other ``///``) will just work.
