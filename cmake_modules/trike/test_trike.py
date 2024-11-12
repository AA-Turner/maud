from pathlib import Path
from clang.cindex import TokenKind, CursorKind, Index
import textwrap

import trike
from trike import (
    Comment,
    State,
    Tokens,
)


def make_tu(tmp_path, source, clang_args=[]):
    path = tmp_path / "source.cxx"
    path.write_text(textwrap.dedent(source))
    tu = Index.create().parse(str(path), args=clang_args, options=trike.PARSE_FLAGS)
    return tu, path


def get_inline_expectations(path):
    """
    It's trivial to parse a formatted source and extract the
    text of each /// and its line number, as well as whether
    it is floating or not. For directive comments in tests
    which use this helper, we read the last three lines to
    get the expected (directive, argument, namespace).
    """
    floating_comments = []
    directive_comments = []

    lines = path.read_text().splitlines()
    lines = map(lambda line: line.strip().removeprefix("#"), lines)
    lines = enumerate(lines, start=1)
    for i, line in lines:
        if not line.startswith("///"):
            continue

        text = [line]
        for i, line in lines:
            if not line.startswith("///"):
                break
            text.append(line)
        else:
            line = ""

        comment = Comment(path, next_line=i, text=text)
        if line == "":
            floating_comments.append(comment)
            continue

        *_, directive, argument, namespace = comment.stripped_text
        directive_comments.append((directive, argument, namespace, comment))

    return floating_comments, directive_comments


def test_basic(tmp_path):
    _, path = make_tu(
        tmp_path,
        """
        ///cpp:function
        ///int main()
        ///
        int main() {
            return 0
        }

        namespace {
        namespace very {
        namespace {
        namespace anonymous {
        ///cpp:var
        ///int STATIC
        ///very::anonymous
        int STATIC;
        }}}}

        ///.. cpp:enum-struct:: @EmptyLies
        ///
        ///cpp:enum
        ///@EmptyLies
        ///
        enum {};

        /// floating
        /// something

        ///.. c:macro:: EXPECT_(condition...)
        ///
        ///c:macro
        ///EXPECT_(condition...)
        ///
        #define EXPECT_(...) foo

        namespace baz {

        ///cpp:struct
        ///Quux
        ///baz
        struct Quux {
          /// four oopsies
          ///cpp:member
          ///int foo
          ///baz::Quux
          int foo;

          /// beyond available resources
          ///
          ///cpp:member
          ///int bar
          ///baz::Quux
          int bar;

          /// summed up
          ///
          ///cpp:function
          ///int foobar() const
          ///baz::Quux
          int foobar() const { return foo + bar; }
        };

        ///cpp:function
        ///void handle [[preconditions{quux.bar != 0;}]] (Quux quux = {0, 1})
        ///baz
        void handle [[preconditions{quux.bar != 0;}]] (Quux quux = {0, 1}) {
          return quux.foobar();
        }

        /// rEVERSEpASCAL never caught on for some reason
        ///
        ///cpp:type
        ///cHAR = char
        ///baz
        using cHAR = char;

        ///cpp:type
        ///int iNT
        ///baz
        typedef int iNT;

        } // namespace baz

        /// e
        ///
        ///cpp:enum
        ///SomeEnum
        ///
        enum class SomeEnum {
          /// s
          ///
          ///cpp:enumerator
          ///SCOPED
          ///SomeEnum
          SCOPED
        };

        void foo() {
          int a;

        #/// floating but zeroes
        #/// indentation

          (void)a;
        }
        """,
    )

    floating_comments, directive_comments = get_inline_expectations(path)
    file_content = trike.comment_scan(path, clang_args=[])
    assert file_content.module == ""
    assert file_content.floating_comments == floating_comments
    assert file_content.directive_comments == directive_comments

    state = State.empty()
    state.add(path, file_content)

    just_comments = [comment for _, _, _, comment in file_content.directive_comments]

    # We can look comments with a directive up in State
    comment, _ = state.get_directive_comment("cpp:function", "int main()")
    assert comment in just_comments

    # classes/structs are interchangeable on lookup
    comment, _ = state.get_directive_comment("cpp:struct", "Quux", "baz")
    assert comment in just_comments
    comment, _ = state.get_directive_comment("cpp:class", "Quux", "baz")
    assert comment in just_comments
    # enum* are interchangeable on lookup
    comment, _ = state.get_directive_comment("cpp:enum-struct", "SomeEnum")
    assert comment in just_comments

    # ... and get a report of close matches when we make a typo
    comment, close_matches = state.get_directive_comment("cpp:type", "CHAR=char", "baz")
    assert comment is None and "cHAR = char" in close_matches

    # ... and we can look up all members of a namespace
    assert state.members["baz::Quux", ""] == dict(
        [
            ((directive, argument), comment)
            for directive, argument, namespace, comment in file_content.directive_comments
            if namespace == "baz::Quux"
        ]
    )
    state.remove(path)
    assert state == State.empty()


def test_dropping_non_triple(tmp_path):
    _, path = make_tu(
        tmp_path,
        """
        /// Interleaved // are elided from the /// text
        // clang-format off
        /// something clang-format would mangle like a long line with a url https://clang.llvm.org/docs/ClangFormatStyleOptions.html
        // clang-format on
        int frobnicate();
        """,
    )
    file_content = trike.comment_scan(path, clang_args=[])
    assert file_content.directive_comments == [
        (
            "cpp:function",
            "int frobnicate()",
            "",
            Comment(
                path,
                next_line=6,
                text=[
                    "/// Interleaved // are elided from the /// text",
                    (
                        "/// something clang-format would mangle like a long line with a"
                        " url https://clang.llvm.org/docs/ClangFormatStyleOptions.html"
                    ),
                ],
            ),
        ),
    ]


def test_escaped_line_ending(tmp_path):
    source = textwrap.dedent(
        r"""
    ///.. cpp:function:: template <typename A, \
                                   typename B, \
                                   typename C, \
                                   typename D> \
                         int score()
    /// Long explicit directives may escape newlines with \.
    /// Whitespace on either side will be collapsed to a single " ".
    template <typename... T>
    std::enable_if_t<impl<T...>, int> score();
    """
    )
    _, path = make_tu(tmp_path, source)
    file_content = trike.comment_scan(path, clang_args=[])
    assert file_content.directive_comments == [
        (
            "cpp:function",
            "template <typename A, typename B, typename C, typename D> int score()",
            "",
            Comment(
                path,
                next_line=9,
                text=["\n".join(source.splitlines()[1:6]), *source.splitlines()[6:8]],
            ),
        ),
    ]


def test_is_documentable():
    assert trike.get_directive_name(CursorKind.MACRO_DEFINITION) == "c:macro"

    for kind, directive in {
        #
        CursorKind.MACRO_DEFINITION: "c:macro",
        #
        CursorKind.FUNCTION_DECL: "cpp:function",
        CursorKind.FUNCTION_TEMPLATE: "cpp:function",
        CursorKind.CXX_METHOD: "cpp:function",
        CursorKind.CONSTRUCTOR: "cpp:function",
        #
        CursorKind.CLASS_TEMPLATE: "cpp:struct",
        CursorKind.STRUCT_DECL: "cpp:struct",
        CursorKind.CLASS_DECL: "cpp:struct",
        #
        CursorKind.FIELD_DECL: "cpp:member",
        #
        CursorKind.VAR_DECL: "cpp:var",
        #
        CursorKind.ENUM_DECL: "cpp:enum",
        CursorKind.ENUM_CONSTANT_DECL: "cpp:enumerator",
        #
        CursorKind.TYPEDEF_DECL: "cpp:type",
        CursorKind.TYPE_ALIAS_DECL: "cpp:type",
        #
        CursorKind.CONCEPT_DECL: "cpp:concept",
        #
        CursorKind.USING_DECLARATION: "",  # using std::cout;
        CursorKind.USING_DIRECTIVE: "",  # using namespace std;
        CursorKind.FRIEND_DECL: "",
        CursorKind.CXX_ACCESS_SPEC_DECL: "",
        CursorKind.PREPROCESSING_DIRECTIVE: "",
        CursorKind.UNEXPOSED_DECL: "",
        CursorKind.STRING_LITERAL: "",
        CursorKind.BLOCK_EXPR: "",
        CursorKind.CXX_BASE_SPECIFIER: "",
    }.items():
        assert trike.get_directive_name(kind) == directive, f"{kind=}"


def test_comment_from_tokens(tmp_path):
    tu, path = make_tu(
        tmp_path,
        """
        /// Y
        // clang-format off
        /// Z
        // clang-format on
        int foo = 3;

        /// Foo
        /// Bar
        """,
    )

    tokens = Tokens(tu)
    comment = Comment.read_from_tokens(path, tokens)
    assert comment is not None
    assert comment.next_line == 6
    assert comment.text == ["/// Y", "/// Z"]

    assert next(tokens).spelling == "int"

    comment = Comment.read_from_tokens(path, tokens)
    assert comment is not None
    assert comment.next_line == 10
    assert comment.text == ["/// Foo", "/// Bar"]

    assert Comment.read_from_tokens(path, tokens) is None


def test_documentable_declaration(tmp_path):
    tu, _ = make_tu(
        tmp_path,
        """
        /// Y
        // clang-format off
        /// Z
        // clang-format on
        int foo = 3;

        /// Foo
        /// Bar
        """,
    )

    tokens = Tokens(tu)
    d = trike.get_documentable_declaration(tokens)
    assert d is not None
    directive, argument, cursor = d
    assert (directive, argument) == ("cpp:var", "int foo = 3")
    assert cursor.spelling == "foo"
    assert cursor.kind == CursorKind.VAR_DECL
    assert next(tokens).spelling == "/// Foo"
    assert trike.get_documentable_declaration(tokens) is None


def test_whitespace(tmp_path):
    tu, _ = make_tu(tmp_path, """  int   foo  =3   ;   """)
    assert trike.join_tokens(Tokens(tu)) == """int foo =3 ;"""


def test_modules(tmp_path):
    tu, _ = make_tu(
        tmp_path,
        r"""
        module;
        [[some_attr({})]];
        #define FOO \
                0
        #include <iostream>
        #include "abracadabra.h"
        export module foo.core:what;
        import bar;
        int main() {}
        """,
        clang_args=["-std=gnu++20"],
    )
    assert trike.get_module(tu) == "foo.core"

    path = Path(__file__).parent.parent / "test_.cxx"
    tu = Index.create().parse(
        str(path), args=["-std=gnu++20", "-Dexport="], options=trike.PARSE_FLAGS
    )
    assert trike.get_module(tu) == "test_"


def test_test_hxx():
    path = Path(__file__).parent.parent / "test_.hxx"
    file_content = trike.comment_scan(path, clang_args=[])
    for directive, _, _, _ in file_content.directive_comments:
        assert directive == "c:macro"
