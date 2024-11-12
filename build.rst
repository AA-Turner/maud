.. _targets:

=======
Targets
=======

The executables, libraries, and tests defined by a project are inferred from
scans of C++ sources.

- Interface units (source files with an ``export module foo;`` decl) produce
  static or shared libraries according to the value of ``BUILD_SHARED_LIBS``.

  - Interface units whose name ends in ``_`` produce non-installed ``OBJECT``
    libraries. This is useful for projects which produce multiple executables
    with shared source but do not wish to expose the shared source as a library.

- Implementation units (source files with a ``module foo;`` decl) are added as
  source files to their interface unit's library target.

- Sources which ``import executable;`` produce
  executable targets. The name of the target is derived by stripping the source
  file's name of extensions - the ``STEM`` of the source file.

- Sources which ``import test_;`` produce
  a test. By default, this will:

  - Create an executable target.
  - Pass that executable to :cmake:`add_test() <command/add_test.html>`.
  - Link the test executable to ``gtest``.

    - If an interface unit of ``module test_:main`` is found then it will be linked
      with each test executable, otherwise ``gtest_main`` will be linked.

  - If the command ``maud_add_test(source_file_path out_target_name)``
    is defined it will be invoked on each test source as it is scanned, allowing
    you to override what a unit test is for your project.

Other source files will not be automatically attached to any target.
Other target types require explicit cmake. For example, to produce a shared
library instead of a static library for ``module foo;`` you can write
``add_library(foo SHARED)`` in any included cmake module. This predefines the
target to which interface and implementation units of ``foo`` will be added.

Directories named ``include`` are globbed up and added to ``INCLUDE_DIRECTORIES``,
so ``$project_root/subtool/include/subtool/foo.hxx`` can be included with
``#include "subtool/foo.hxx"`` from any header or source.
