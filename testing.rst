Unit tests
----------

While scanning modules, ``Maud`` will detect and
:cmake:`register <command/add_test.html>` C++ unit tests.
(This can be disabled by setting ``BUILD_TESTING = OFF``.)
Unit testing is based on :gtest:`GTest </>`, and many basic
concepts like suites of test cases are inherited whole.
Many other aspects of writing tests are simplified.
Instead of duplicating GTest's documentation or explaining
unit tests from the ground up, this documentation will
assume familiarity and mostly describe the ways ``Maud``'s
usage differs.

Instead of defining test suites explicitly with classes,
one test suite is produced for each C++ source which includes
the special module declaration ``module test_``. Each test suite
is compiled into an executable target named ``test_.${SUITE_NAME}``.

In a suite source file, three macros are included in the predefines
buffer (an explicit ``#include`` is unnecessary):
test cases are defined with :c:macro:`TEST_`,
and in a test case assertions are made with :c:macro:`EXPECT_`.
:c:macro:`SUITE_` can optionally be used to
specify resources which should be shared across the suite.

.. code-block:: c++

  module test_;

  SUITE_ { std::string yo = "yo"; };

  TEST_(basic) {
    int three = 3, five = 5;
    EXPECT_(three == five);
    // ~/maud/.build/_maud/project_tests/unit testing/basics.cxx:12: Failure
    // Expected: three == five
    //   Actual:     3 vs 5
    EXPECT_(not three);
    // ~/maud/.build/_maud/project_tests/unit testing/basics.cxx:14: Failure
    // Expected: three
    //     to be false

    // EXPECT_(...) is an expression contextually convertible to bool
    if (not EXPECT_(&three != nullptr)) return;
    EXPECT_(&three != nullptr) or [](std::ostream &os) {
      // A lambda can hook expectation failure and add more context
    };

    EXPECT_(suite_state()->yo == "yo");

    // GMock's matchers are available
    EXPECT_("hello world" >>= HasSubstr("llo"));
  }

  // To check a test body against multiple values, parameterize with a range.
  TEST_(parameterized, {111, 234}) {
    EXPECT_(parameter > 0);
  }

  // To instantiate the test body with multiple types, parameterize with a tuple.
  TEST_(typed, 0, std::string("")) {
    EXPECT_(parameter + parameter == parameter);
  }


Unit test API
~~~~~~~~~~~~~

.. trike-put:: c:macro TEST_(case_name, parameters...)

.. trike-put:: c:macro EXPECT_(condition...)

.. trike-put:: c:macro SUITE_

.. cpp:module:: test_

.. trike-put:: cpp:class template <typename Match, \
                                   typename Describe, \
                                   typename DescribeNegation> \
               Matcher

.. FIXME GTest is not easily includable yet

GTest is added to the include path for the suite, so explicit
``#include <gtest/gtest.h>`` is always available if necessary.
Each suite is linked to ``gtest_main``. Since that defines ``main``
as a weak symbol, a custom main function can be written in a
test suite. To write a custom main function for all test suites,
write an interface unit with ``export module test_:main;`` and
that will replace ``gtest_main``.


Overriding ``test_``
====================

If it is preferable to override ``test_`` entirely (for
example to use a different test library like
`Catch2 <https://github.com/catchorg/Catch2/tree/devel/docs>`_
instead of ``GTest``), write an interface unit with
``export module test_`` and define the cmake function ``maud_add_test``:

.. code-block:: cmake

  maud_add_test(source_file partition out_target_name)

If defined, each source file which declares ``module test_``
or a partition of it will be passed to this function and
added to the target it names. (See project test
``custom unit testing`` for an example.)


Formatting test
~~~~~~~~~~~~~~~

By default, if `ClangFormat <https://clang.llvm.org/docs/ClangFormat.html>`_ is
detected then a test will be added which asserts that files are formatted
consistently::

  $ ctest --build-config Debug --tests-regex formatted --output-on-failure
  Test project ~/maud/.build
      Start 4: check.clang-formatted
  1/1 Test #4: check.clang-formatted ............***Failed    0.07 sec
  Clang-formating 16 files
  ~/maud/in2.cxx:15:42: error: code should be clang-formatted [-Wclang-format-violations]
  export void compile_in2(std::istream &is,   std::ostream &os);
                                           ^

A target will also be added which formats files in place::

  $ ninja -C fix.clang-format

Since the set of files which should be formatted is not necessarily identical to
the set which should be compiled, a separate glob must be provided in the project's
root ``.clang-format`` file::

  # Maud: {
  #   "version": 18,
  #   "patterns": [
  #     "\\.[ch]xx$",
  #     "!rapidyaml\\.hxx"
  #   ]
  # }
  BasedOnStyle: Google
  ColumnLimit: 90
