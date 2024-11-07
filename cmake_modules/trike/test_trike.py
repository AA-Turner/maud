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


def test_basic(tmp_path):
    _, path = make_tu(
        tmp_path,
        """
        /// The entry point
        // clang-format off
        /// something clang-format would mangle
        // clang-format on
        int main() {
            return 0
        }

        /// floating something

        ///.. c:macro:: EXPECT_(condition...)
        /// expect doc
        #define EXPECT_(...) foo

        namespace baz {

        /// Metasyntactic value
        struct Quux {
          /// four oopsies
          int foo;
          /// beyond available resources
          int bar;
          /// summed up
          int foobar() const { return foo + bar; }
        };

        /// rEVERSEpASCAL never caught on for some reason
        using cHAR = char;

        } // namespace baz

        /// e
        enum class SomeEnum {
          /// s
          SCOPED
        };
        """,
    )
    file_content = trike.comment_scan(path, clang_args=[])
    assert file_content.module == ""
    assert file_content.directive_comments == [
        (
            "cpp:function",
            "int main()",
            "",
            Comment(
                path,
                next_line=6,
                text=["/// The entry point", "/// something clang-format would mangle"],
            ),
        ),
        (
            "c:macro",
            "EXPECT_(condition...)",
            "",
            Comment(
                path,
                next_line=14,
                text=["/// expect doc"],
            ),
        ),
        (
            "cpp:struct",
            "Quux",
            "baz",
            Comment(
                path,
                next_line=19,
                text=["/// Metasyntactic value"],
            ),
        ),
        (
            "cpp:member",
            "int foo",
            "baz::Quux",
            Comment(
                path,
                next_line=21,
                text=["/// four oopsies"],
            ),
        ),
        (
            "cpp:member",
            "int bar",
            "baz::Quux",
            Comment(
                path,
                next_line=23,
                text=["/// beyond available resources"],
            ),
        ),
        (
            "cpp:function",
            "int foobar() const",
            "baz::Quux",
            Comment(
                path,
                next_line=25,
                text=["/// summed up"],
            ),
        ),
        (
            "cpp:type",
            "cHAR = char",
            "baz",
            Comment(
                path,
                next_line=29,
                text=["/// rEVERSEpASCAL never caught on for some reason"],
            ),
        ),
        (
            "cpp:enum",
            "SomeEnum",
            "",
            Comment(
                path,
                next_line=34,
                text=["/// e"],
            ),
        ),
        (
            "cpp:enumerator",
            "SCOPED",
            "SomeEnum",
            Comment(
                path,
                next_line=36,
                text=["/// s"],
            ),
        ),
    ]
    assert file_content.floating_comments == [
        Comment(
            path,
            next_line=11,
            text=["/// floating something"],
        ),
    ]

    state = State.empty()
    state.add(path, file_content)

    # We can look comments with a directive up in State
    comment, _ = state.get_comment("cpp:function", "int main()")
    assert comment == file_content.directive_comments[0][-1]

    # ... and get a report of close matches when we make a typo
    comment, close_matches = state.get_comment("cpp:type", "CHAR=char", "baz")
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


def test_comment_from_tokens(tmp_path):
    tu, path = make_tu(
        tmp_path,
        """
        /// The entry point
        // clang-format off
        /// something clang-format would mangle
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
    assert comment.text == [
        "/// The entry point",
        "/// something clang-format would mangle",
    ]
    assert next(tokens).spelling == "int"

    comment = Comment.read_from_tokens(path, tokens)
    assert comment is not None
    assert comment.next_line == 10
    assert comment.text == [
        "/// Foo",
        "/// Bar",
    ]

    comment = Comment.read_from_tokens(path, tokens)
    assert comment is None


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


def test_documentable_declaration(tmp_path):
    tu, _ = make_tu(
        tmp_path,
        """
        /// The entry point
        // clang-format off
        /// something clang-format would mangle
        // clang-format on
        int foo = 3;

        /// Foo
        // clang-format off
        /// Bar
        // clang-format on
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
    tu = Index.create().parse(str(path), args=['-std=gnu++20', '-Dexport='], options=trike.PARSE_FLAGS)
    assert trike.get_module(tu) == "test_"


def test_test_hxx():
    path = Path(__file__).parent.parent / "test_.hxx"
    file_content = trike.comment_scan(path, clang_args=[])
    for directive, _, _, _ in file_content.directive_comments:
        assert directive == "c:macro"
