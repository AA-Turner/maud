from pathlib import Path
from clang.cindex import CursorKind, Index

import trike
from trike import (
    Comment,
    State,
    Tokens,
)


def make_tu(tmp_path, source, clang_args=[]):
    path = tmp_path / "source.cxx"
    path.write_text(source)
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

        /*
        /// e
        enum Enum {
          /// s
          SCOPED
        };
        */
        """,
    )
    file_content = trike.comment_scan(path, clang_args=[])
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
    assert trike.is_documentable(CursorKind.MACRO_DEFINITION)
    assert trike.is_documentable(CursorKind.FUNCTION_DECL)
    assert trike.is_documentable(CursorKind.FUNCTION_TEMPLATE)
    assert trike.is_documentable(CursorKind.CLASS_TEMPLATE)
    assert trike.is_documentable(CursorKind.STRUCT_DECL)
    assert trike.is_documentable(CursorKind.CXX_METHOD)
    assert trike.is_documentable(CursorKind.ENUM_DECL)
    assert trike.is_documentable(CursorKind.ENUM_CONSTANT_DECL)
    assert trike.is_documentable(CursorKind.FIELD_DECL)
    assert trike.is_documentable(CursorKind.VAR_DECL)
    assert trike.is_documentable(CursorKind.TYPEDEF_DECL)
    assert trike.is_documentable(CursorKind.CONSTRUCTOR)
    assert trike.is_documentable(CursorKind.CONCEPT_DECL)

    # TODO maybe add these to the non-documented set
    assert trike.is_documentable(CursorKind.USING_DECLARATION)
    assert trike.is_documentable(CursorKind.USING_DIRECTIVE)
    assert trike.is_documentable(CursorKind.FRIEND_DECL)
    assert trike.is_documentable(CursorKind.TYPE_ALIAS_DECL)
    assert trike.is_documentable(CursorKind.CXX_ACCESS_SPEC_DECL)

    assert not trike.is_documentable(CursorKind.PREPROCESSING_DIRECTIVE)
    assert not trike.is_documentable(CursorKind.UNEXPOSED_DECL)
    assert not trike.is_documentable(CursorKind.STRING_LITERAL)
    assert not trike.is_documentable(CursorKind.BLOCK_EXPR)
    assert not trike.is_documentable(CursorKind.CXX_BASE_SPECIFIER)


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
        """
        module;
        module foo;
        import bar;
        """,
        clang_args=["-std=gnu++20"],
    )

    tokens = Tokens(tu)
    for t in tokens:
        if t.spelling == "module":
            t = next(tokens)
            if t.spelling != ";":
                break
    assert t.spelling == "foo"


def test_test_hxx():
    path = Path(__file__).parent.parent / "test_.hxx"
    file_content = trike.comment_scan(path, clang_args=[])
    for directive, _, _, _ in file_content.directive_comments:
        assert directive == "c:macro"
