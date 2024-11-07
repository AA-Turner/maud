from dataclasses import dataclass
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import sphinx.util.logging
import docutils.parsers.rst.directives
import difflib
import multiprocessing

from clang.cindex import (
    Cursor,
    CursorKind,
    Index,
    Token,
    TokenKind,
    TranslationUnit,
)
from sphinx.application import Sphinx
from sphinx.util.typing import ExtensionMetadata
from sphinx.util.docutils import SphinxDirective
from docutils.nodes import Node
from docutils.statemachine import StringList
from typing import Self, Sequence, Iterator, Mapping

logger = sphinx.util.logging.getLogger(__name__)


PARSE_FLAGS = (
    TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
    | TranslationUnit.PARSE_SKIP_FUNCTION_BODIES
    | TranslationUnit.PARSE_INCOMPLETE
)


class Tokens:
    def __init__(self, tu: TranslationUnit):
        self.tokens = iter(tu.get_tokens(extent=tu.cursor.extent))
        self._next = None

    def __iter__(self):
        return self

    def __next__(self):
        t, self._next = self._next, None
        return t or next(self.tokens)

    def unget(self, t) -> None:
        self._next = t


type ModuleName = str
type NamespaceName = str
type DirectiveName = str
type DirectiveArgument = str


@dataclass
class Comment:
    """The content of an individual ///"""

    PREFIX = "///"

    file: Path
    next_line: int
    text: list[str]

    @staticmethod
    def read_from_tokens(file: Path, tokens: Tokens) -> Self | None:
        for t in tokens:
            if t.kind == TokenKind.COMMENT and t.spelling.startswith(Comment.PREFIX):
                break
        else:
            return None

        comment = Comment(file, t.extent.end.line + 1, [t.spelling])
        for t in tokens:
            if t.kind != TokenKind.COMMENT or t.extent.start.line > comment.next_line:
                tokens.unget(t)
                break
            comment.next_line = t.extent.end.line + 1

            if t.spelling.startswith(Comment.PREFIX):
                comment.text.append(t.spelling)
            elif t.spelling.startswith("/*"):
                raise RuntimeError(
                    "/// interspersed with C-style comments are not supported"
                )

        return comment

    @property
    def first_line(self) -> int:
        return self.next_line - len(self.text)

    @property
    def stripped_text(self) -> list[str]:
        return [line[len(Comment.PREFIX) + 1 :] for line in self.text]

    def with_directive(
        self, directive: str, argument: str, indent: str = ""
    ) -> Iterator[str]:
        yield ""
        yield f"{indent}.. {directive}:: {argument}"
        # TODO add a link to the decl on GitHub
        yield ""
        for line in self.stripped_text:
            yield f"{indent}  {line}"

    def get_explicit_directive(self):
        # FIXME don't mutate here
        if self.text[0].startswith("///.. "):
            directive, argument = self.text.pop(0).removeprefix("///.. ").split("::", 1)
            return directive.strip(), argument.strip()


@dataclass
class FileContent:
    """A container for all /// content in a file"""

    module: ModuleName
    floating_comments: list[Comment]
    directive_comments: list[
        tuple[DirectiveName, DirectiveArgument, NamespaceName, Comment]
    ]
    clang_diagnostics: list[str]
    mtime_when_parsed: float


def get_directive_name(kind: CursorKind) -> DirectiveName:
    if kind == CursorKind.MACRO_DEFINITION:
        return "c:macro"

    if not kind.is_declaration() or kind in {
        CursorKind.NAMESPACE,
        CursorKind.INVALID_FILE,
        CursorKind.NAMESPACE_REF,
        CursorKind.TEMPLATE_REF,
        CursorKind.PREPROCESSING_DIRECTIVE,
        CursorKind.MACRO_INSTANTIATION,
        CursorKind.UNEXPOSED_DECL,
    }:
        return ""

    clang_cursor_kind = str(kind).removeprefix("CursorKind.")

    if clang_cursor_kind == "FIELD_DECL":
        return "cpp:member"

    if clang_cursor_kind == "TYPEDEF_DECL" or "TYPE_ALIAS" in clang_cursor_kind:
        return "cpp:type"

    if "FUNCTION" in clang_cursor_kind or clang_cursor_kind in {
        "CXX_METHOD",
        "CONSTRUCTOR",
        "DESTRUCTOR",
    }:
        return "cpp:function"

    if "STRUCT" in clang_cursor_kind or "CLASS" in clang_cursor_kind:
        # Classes and structs are stored together because libclang uses
        # CLASS_TEMPLATE for struct templates. We decide whether to use
        # cpp:struct or cpp:class based on the referencing directive.
        return "cpp:struct"

    if clang_cursor_kind == "ENUM_DECL":
        # All enums are stored together because libclang does not surface the
        # distinction between scoped/unscoped enums in `Cursor.kind`. We decide
        # between cpp:enum{,-struct,-class} based on the referencing directive.
        return "cpp:enum"

    if clang_cursor_kind == "ENUM_CONSTANT_DECL":
        return "cpp:enumerator"

    if clang_cursor_kind == "CONCEPT_DECL":
        return "cpp:concept"

    if "VAR" in clang_cursor_kind:
        return "cpp:var"

    return ""


def contiguous(first: Token | None, second: Token | None) -> bool:
    if first is None or second is None:
        return True
    return first.extent.end == second.extent.start


def join_tokens(tokens: Sequence[Token]) -> str:
    tokens_it = iter(tokens)
    previous = next(tokens_it)
    joined = previous.spelling
    for t in tokens_it:
        if not contiguous(previous, t):
            joined += " "
        joined += t.spelling
        previous = t
    return joined


def get_documentable_declaration(
    tokens: Tokens,
) -> tuple[DirectiveName, DirectiveArgument, Cursor] | None:
    """
    Get a documentable declaration from a token stream, with
    whitespace canonicalized to a single " "
    """
    if t := next(tokens, None):
        min_offset = t.extent.start.offset
        tokens.unget(t)
    else:
        return None

    for t in tokens:
        if t.cursor.extent.start.offset < min_offset:
            # Some of the tokens captured by Clang might be associated with a declaration
            # which *encloses* the decl of interest. For example:
            #
            # .. code-block:: c++
            #
            #   struct Foo {
            #     enum Color { R, G, B };
            #     /// The first token after this doccomment is the return type, for
            #     /// which t.cursor corresponds to Foo::Color rather than get_color.
            #     Color get_color();
            #   };
            continue

        if directive := get_directive_name(t.cursor.kind):
            break
    else:
        return None

    cursor = t.cursor
    cursor_tokens = cursor.get_tokens()
    declaration_tokens = []

    if directive == "c:macro":
        name = next(cursor_tokens)
        declaration_tokens.append(name)
        if maybe_open_paren := next(cursor_tokens, None):
            if maybe_open_paren.spelling == "(" and contiguous(name, maybe_open_paren):
                # function macro; include parameters
                declaration_tokens.append(maybe_open_paren)
                for t in cursor_tokens:
                    declaration_tokens.append(t)
                    if t.spelling == ")":
                        break

    else:
        for t in cursor_tokens:
            if t.spelling in "{;":
                # TECHNICALLY these could occur in an attribute or lambda expression:
                #
                # .. code-block:: c++
                #
                #   /// we only see "IDENTITY = [](auto self)"
                #   auto IDENTITY = [](auto self) { return self; };
                #
                #   /// we only see "[[preconditions"
                #   [[preconditions{ this->foo == 3 }]] int Foo::get_three() const
                #
                # However this doesn't seem critical to support, particularly since
                # if these constructions are necessary it should be sufficient to
                # override the automatic declaration string.
                break

            if t.spelling in {
                "class",
                "struct",
                "export",
                "union",
                "using",
                "typedef",
                "enum",
                "concept",
            }:
                # sphinx decls do not include these; skip them
                #
                # Again, TECHNICALLY these could appear in a template argument *and*
                # be syntactically necessary. Again, simplicity here seems preferable.
                continue

            declaration_tokens.append(t)

    # Advance tokens past what we've consumed from the cursor
    next_line = declaration_tokens[-1].extent.end.line + 1
    for t in tokens:
        if t.extent.end.line >= next_line:
            tokens.unget(t)
            break

    return directive, join_tokens(declaration_tokens), cursor


def comment_scan(path: Path, clang_args: list[str]) -> FileContent:
    tu = Index.create().parse(str(path), args=clang_args, options=PARSE_FLAGS)
    tokens = Tokens(tu)

    module = ""  # TODO detect modules

    floating_comments = []

    directives = []
    arguments = []
    namespaces = []
    comments = []

    sphinx_spelling = {}
    semantic_parents = []

    while True:
        comment = Comment.read_from_tokens(path, tokens)
        if comment is None:
            break

        t = next(tokens, None)
        explicitly_floating = t is None or t.extent.start.line > comment.next_line
        tokens.unget(t)

        directive, argument = "", ""

        if not explicitly_floating:
            if d := get_documentable_declaration(tokens):
                directive, argument, cursor = d
                sphinx_spelling[cursor.canonical.get_usr()] = argument
                semantic_parents.append(cursor.semantic_parent)

        if d := comment.get_explicit_directive():
            # explicit directives override those inferred from decls
            directive, argument = d

        if directive:
            directives.append(directive)
            arguments.append(argument)
            comments.append(comment)
        elif explicitly_floating:
            floating_comments.append(comment)
        else:
            logger.error(
                f"Could not infer directive from {str(path)}:{comment.next_line}"
            )

    for p in semantic_parents:
        namespace = ""
        while p is not None and p != tu.cursor:
            parent_spelling = sphinx_spelling.get(p.canonical.get_usr(), p.spelling)
            p = p.semantic_parent
            namespace = f"{parent_spelling}::{namespace}"
        namespaces.append(namespace.removesuffix("::"))

    return FileContent(
        module,
        floating_comments,
        directive_comments=list(zip(directives, arguments, namespaces, comments)),
        clang_diagnostics=[str(d) for d in tu.diagnostics],
        mtime_when_parsed=path.stat().st_mtime,
    )


@dataclass
class State:
    """A container for all /// content in a project plus tracking metadata"""

    files: dict[Path, FileContent]
    directive_comments: defaultdict[
        tuple[DirectiveName, NamespaceName, ModuleName],
        dict[DirectiveArgument, Comment],
    ]
    members: defaultdict[
        tuple[NamespaceName, ModuleName],
        dict[tuple[DirectiveName, DirectiveArgument], Comment],
    ]

    @staticmethod
    def empty() -> Self:
        return State({}, defaultdict(dict), defaultdict(dict))

    def is_stale(self, path: Path) -> bool:
        return path.stat().st_mtime > self.files[path].mtime_when_parsed

    def add(self, path: Path, file_content: FileContent) -> None:
        self.files[path] = file_content

        module = file_content.module
        for directive, argument, namespace, comment in file_content.directive_comments:
            comments = self.directive_comments[directive, namespace, module]
            stored = comments.setdefault(argument, comment)
            if stored is not comment:
                raise RuntimeError(
                    f"Duplicate /// detected:\n{stored}\n\n  vs\n\n{comment}"
                )
            self.members[namespace, module][directive, argument] = comment

    def remove(self, path: Path) -> None:
        # purge this file's ///s
        file_content = self.files.pop(path)
        module = file_content.module
        for directive, argument, namespace, _ in file_content.directive_comments:
            del self.directive_comments[directive, namespace, module][argument]
            if not self.directive_comments[directive, namespace, module]:
                del self.directive_comments[directive, namespace, module]

            del self.members[namespace, module][directive, argument]
            if not self.members[namespace, module]:
                del self.members[namespace, module]

    def get_comment(
        self,
        directive: DirectiveName,
        argument: DirectiveArgument,
        namespace: NamespaceName = "",
        module: ModuleName = "",
    ) -> tuple[Comment | None, dict[DirectiveArgument, Comment]]:
        comments = self.directive_comments.get(
            (
                directive if directive != "cpp:class" else "cpp:struct",
                namespace,
                module,
            ),
            {},
        )

        if comment := comments.get(argument, None):
            return comment, {}

        return None, {
            m: comments[m] for m in difflib.get_close_matches(argument, comments.keys())
        }


def _builder_inited(app: Sphinx) -> None:
    if not hasattr(app.env, "trike_state"):
        app.env.trike_state = State.empty()

    stored = set(app.env.trike_state.files.keys())
    required = set(app.config.trike_files)
    unnecessary = stored - required
    new = required - stored
    stale = {path for path in stored if app.env.trike_state.is_stale(path)}
    removed = unnecessary | stale
    scanned = list(new | stale)

    for path in removed:
        app.env.trike_state.remove(path)

    with multiprocessing.Pool(app.parallel) as pool:
        futures = []
        for path in scanned:
            if isinstance(app.config.trike_clang_args, list):
                clang_args = app.config.trike_clang_args
            else:
                clang_args = app.config.trike_clang_args.get(path, [])

            if app.parallel > 1:
                futures.append(pool.apply_async(comment_scan, [path, clang_args]))
            else:
                app.env.trike_state.add(path, comment_scan(path, clang_args))

        if futures:
            for path, future in zip(scanned, futures):
                app.env.trike_state.add(path, future.get())


class PutDirective(SphinxDirective):
    has_content = True
    required_arguments = 2
    optional_arguments = 1000
    option_spec = {
        "members": docutils.parsers.rst.directives.flag,
    }

    @contextmanager
    def cpp(self):
        tmp = {}
        tmp["highlight_language"] = self.env.temp_data.get("highlight_language", None)
        self.env.temp_data["highlight_language"] = "cpp"
        tmp["default_domain"] = self.env.temp_data.get("default_domain", None)
        self.env.temp_data["default_domain"] = self.env.domains.get("cpp")
        try:
            yield
        finally:
            for key, value in tmp.items():
                if value is None:
                    del self.env.temp_data[key]
                else:
                    self.env.temp_data[key] = value

    def run(self) -> list[Node]:
        directive = self.arguments[0]
        argument = " ".join(filter(lambda arg: arg != "\\", self.arguments[1:]))
        namespace = self.env.temp_data.get("cpp:namespace_stack", [""])[-1]
        module = self.env.temp_data.get("cpp:module", "")
        # TODO provide directive to set module
        with_members = "members" in self.options

        comment, close_matches = self.env.trike_state.get_comment(
            directive, argument, namespace, module
        )
        if comment is not None:
            self.env.note_dependency(comment.file)

            text = []
            text.extend(comment.with_directive(directive, argument))
            text.append("")
            text.extend(f"  {line}" for line in self.content)

            if with_members:
                member_namespace = (namespace and namespace + "::") + argument
                members = self.env.trike_state.members[member_namespace, module]
                for (directive, argument), comment in members.items():
                    text.extend(comment.with_directive(directive, argument, "  "))

            # FIXME "test_.hxx:73:<trike>" should appear in the sphinx error log if
            # a /// fails to parse; I'm not sure what's wrong with the below
            text = StringList(text, f"{comment.file}:{comment.first_line}:<trike>")
            with self.cpp(), sphinx.util.docutils.switch_source_input(self.state, text):
                return self.parse_text_to_nodes(text)  # type: ignore

        message = f"found no declaration matching `{argument}`\n"
        message += f"{directive=} {namespace=} {module=}"
        for argument, comment in close_matches.items():
            message += (
                f"\n  close match: `{argument}` {str(comment.file)}:{comment.next_line}"
            )
        logger.error(message)
        return []


def setup(app: Sphinx) -> ExtensionMetadata:
    app.add_config_value(
        "trike_files",
        [],
        "env",
        types=[list[Path]],
        description="All files which will be scanned for ///",
    )

    app.add_config_value(
        "trike_clang_args",
        [],
        "env",
        types=[list[str], Mapping[Path, str]],
        description="Arguments which will be passed to clang (or per-file mapping)",
    )

    app.connect("builder-inited", _builder_inited)
    app.add_directive("trike-put", PutDirective)
    # TODO trike-function etc as a shortcut for trike-put:: cpp:function

    logger.info("trike setup")
    return {
        "version": "0.1",
        "env_version": 1,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
