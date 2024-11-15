====
Maud
====

A low configuration convention for C++ projects.

``Maud`` is built on :cmake:`CMake </>`, but works hard to eliminate
boilerplate. For simple projects, **no** hand written ``cmake`` is required.
Whenever explicit configuration becomes necessary, minimal and focused ``cmake``
can be written wherever makes the most sense for your project.
Read more about :ref:`cmake convention in Maud <cmake>`.

Globbing
--------

``Maud`` extends CMake's built in globbing support with more expressive
patterns, support for exclusion as well as inclusion, and greater performance.
Read more about :ref:`globbing <globbing-case>`.

To briefly summarize, globs are used to find:

- ``cmake_modules`` directories, which are added to the module path
- ``.cmake`` modules, which are automatically included
- ``.in2`` template files, which are rendered
- ``include`` directories, which are added to the include path
- C++ source files, which are scanned for modules and automatically
  attached to build targets

Targets
-------

The executables, libraries, and tests defined by a project are inferred from
scans of C++ sources. Read more about :ref:`automatic targets <targets>`.

More sophisticated options
--------------------------

Maud backwards-compatibly overloads the built-in
:cmake:`option <command/option.html>` function to provide
support for more sophisticated
configuration options:

- uniform declaration for all types of option
- resolution of interdependent option values
- easy access to options in C++ as predefined macros
- clean summarization of all options, complete with multiline help strings
- serialization to :cmake:`preset JSON <manual/cmake-presets.7.html#configure-preset>`
  for repeatability

.. code-block:: cmake

  option(
    FOO_LEVEL
      ENUM LOW MED HI
    "
    What level of FOO API should be requested.
    LOW is primarily used for testing and is not otherwise recommended.
    "
    DEFAULT MED

    REQUIRES
    IF HI
      # LOW or MED levels can be emulated but HI requires a physical FOO endpoint.
      FOO_EMULATED OFF

    ADD_COMPILE_DEFINITIONS
  )

Read more about :ref:`options`.

Built-in support for generated files
------------------------------------

A common source of cmake boilerplate is wiring up rendering of template files,
running schema compilers, and otherwise generating code. ``Maud`` provides a
single build subdirectory for these files to land in and natively supports
including them in any file set: all globs will include matching files in
``${MAUD_DIR}/rendered`` as well as those in ``${CMAKE_SOURCE_DIR}``
(unless :ref:`explicitly excluded <glob-function-exclude_rendered>`).

Additionally, projects using ``Maud`` can use a built-in
:ref:`template format <in2-templates>` inspired by ``configure_file()``
to smoothly render configuration information into generated code.
If the template file ``${CMAKE_SOURCE_DIR}/dir/foo.cxx.in2`` exists,
it will automatically be rendered to ``${MAUD_DIR}/rendered/dir/foo.cxx``
and included in compilation alongside non-generated C++:

.. code-block:: c++.in2

  #define FOO_ENABLED @FOO_ENABLED | if_else(1 0)@
  // renders to
  #define FOO_ENABLED 1

Super easy documentation
------------------------

If a Python3 interpreter is found, Sphinx will be used to build documentation
from the glob of all ``.rst`` files. Read more about :ref:`documentation`.

Utilities
---------

A number of C++ programs are provided:

- simple scanner

- template compiler

Table of Contents
-----------------

.. toctree::
  :glob:

  *
