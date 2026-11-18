# ShellDeck Shell

Standalone Rust command interpreter with a reusable library API and a small CLI.
The library has no Qt dependency and currently has no third-party dependencies.

## Current command set

- Built-ins: `cd` (including `cd -`), `pwd`, `help`, `history` (`history -c`),
  `source FILE`/`. FILE`, `jobs`, `wait [JOB_ID]`, `true`, `false`, `clear`,
  `exit [STATUS]`, `return [STATUS]` (inside sourced scripts/functions), `break`,
  `continue` (inside sourced loops), `test`, `[ ]`, `printf`, `local`, `read`
- `cd -` switches to the previous directory and writes the destination path to
  stdout.
- `cd -- PATH` treats `PATH` as a directory argument, so a name beginning with
  `-` or the name `-` itself is not interpreted as an option or a request to
  switch to the previous directory. `cd --` returns to home.
- Successful directory changes through `cd`, `pushd`, or `popd` update `PWD` to
  the resulting current directory and `OLDPWD` to the directory left; both
  values are passed to started programs.
- `pushd [--] [PATH|+N]` changes directory and saves the previous one; `pushd` without
  an argument swaps with the previous directory or most recently saved entry.
  Use `pushd -- PATH` when the path looks like a `+N` stack index, so it is
  handled as a path instead.
  `pushd +N` rotates the stack so numbered entry `N` becomes current. It writes
  the new directory to stdout.
- `popd [+N]` without an index switches to and removes the most recently saved
  directory. With `+N`, it removes the numbered entry; `popd +0` switches to
  the next stack entry. It writes the resulting current directory to stdout.
- `dirs` prints the current directory followed by saved directories from newest
  to oldest. `dirs -p` prints one path per line; `dirs -v` prefixes each path
  with its stack index; `dirs -c` clears the saved stack without changing the
  current directory.
- File commands: `ls`/`dir` (`-a`), UTF-8 `cat`, `mkdir` (`-p`)
- Text and variables: `echo` (`-n`), `read [NAME ...]`, `set NAME=VALUE`, `unset NAME`, `$NAME`,
  and `${NAME}`
- Arithmetic expansion: `$((EXPRESSION))` with signed integer values,
  variables, parentheses, and `+`, `-`, `*`, `/`, `%`
- Arithmetic assignment: `let NAME=EXPRESSION` (multiple assignments may be
  given; its status is 1 when the final result is zero)
- Launch installed programs directly with their argument list; no system shell is
  used to parse or launch commands.
- `ShellHost` may implement an interactive foreground-program hook for a single
  external command without redirections; pipelines and redirected commands use
  the regular process path. Hosts that omit the hook keep their current behavior.
- Single- and double-quoted arguments, including paths with spaces. Single quotes
  leave `$NAME` literal; variables expand in unquoted and double-quoted text.
- An unquoted `~` at the start of a word expands to the host-provided home
  directory; `~/PATH` and `~\PATH` append the remaining path. `~user` and a
  missing host home directory are left unchanged.
- An unquoted `~+` at the start of a word expands to the host's current
  directory; `~+/PATH` appends the remaining path. `~+NAME` stays literal.
- An unquoted `~-` at the start of a word expands to the previous directory;
  `~-/PATH` appends the remaining path. Without a previous directory it stays
  literal.
- `$?` expands to the most recent command status. Expansion is performed while
  parsing the current input line, before any command on that line executes.
- `${NAME-WORD}` uses `WORD` when `NAME` is unset; `${NAME:-WORD}` also uses it
  when `NAME` is empty. The fallback text is inserted literally and is not
  expanded again. Assignment forms such as `${NAME:=WORD}` are not implemented.
- `${NAME+WORD}` inserts `WORD` when `NAME` is set; `${NAME:+WORD}` requires it
  to be nonempty. Otherwise these forms expand to an empty string. The alternate
  text is also inserted literally without nested expansion.
- `${NAME?MESSAGE}` stops parsing the input line with `MESSAGE` when `NAME` is
  unset. The message is literal; an empty message produces a default diagnostic.
- `${NAME:?MESSAGE}` also treats an empty value as missing. Both forms accept
  unset positional and environment variables; their message text is not expanded.
- `${#NAME}` returns the number of Unicode characters in a variable value; an
  unset variable has length zero. `${#}` remains the positional argument count.
- `${NAME#PATTERN}` / `${NAME##PATTERN}` remove the shortest / longest matching
  prefix; `${NAME%PATTERN}` / `${NAME%%PATTERN}` remove the shortest / longest
  matching suffix. Patterns support `*` and `?`, using the same matching rules as
  sourced-script `case` patterns. Other glob syntax is not implemented.
- Shell variables are passed to launched programs as environment overrides.
- Operators: `|`, `;`, `&&`, `||`, `<`, `>`, `>>`, `1>`, `1>>`, `2>`, `2>>`,
  and a final `&` for launching an external pipeline in the background.
- A `ShellHost` interface separates command semantics from filesystem, process,
  environment, and terminal operations.
- `ShellHost::path_kind` provides portable file/directory metadata; its default
  reports unsupported so existing hosts remain source-compatible.

Pipes connect external programs through OS streams. Shell built-ins such as
`echo`, `pwd`, `ls`, and `cat` can also be pipe stages; shell-state changes such
as `cd` and `set` are deliberately rejected inside a pipeline. When a pipeline
crosses a built-in stage, that boundary is captured in memory. `<` applies to
the first stage; `>` and `>>` apply to the last stage. `2>` and `2>>` redirect
the stderr of an external program. `jobs` lists tracked jobs; `wait [JOB_ID]`
waits for one or all jobs. Background mode currently accepts external programs
and external-only pipelines. Their standard input defaults to the null device;
output is inherited unless redirected, so it can appear alongside the prompt.
`;` runs command or pipeline sequences from left to right. A nonzero external
exit status does not prevent later commands; `exit` ends the sequence. Parsing
the whole line happens before any command runs. `&&` runs the next command only
when the last executed command succeeded; `||` runs it only after a nonzero
status. Skipped commands do not change that status. Parse errors and host-level
execution errors stop the line. Interactive foreground control (`fg`, `bg`,
stop/continue and signal handling), `2>&1`, completion, and full PTY/ConPTY job
control remain future work.

The built-ins `true` and `false` return portable statuses 0 and 1. `exit [STATUS]`
accepts a status from 0 to 255; without an argument it uses the last executed
command's status. The standalone CLI returns that status to its parent process.

The built-ins `test` and `[ ... ]` provide portable string and integer
conditions for scripts. They support a nonempty-string check, `-n`, `-z`, string
`=`/`!=`, integer `-eq`, `-ne`, `-lt`, `-le`, `-gt`, `-ge`, and leading `!`.
They also support `-a` (AND) and `-o` (OR), with `-a` taking precedence.
The `[` form requires a closing `]`. Numeric operands must fit a signed
64-bit integer. File tests `-e`, `-f`, and `-d` check existence, regular files,
and directories through the `ShellHost` metadata hook. Hosts that leave the
default hook unchanged report file tests as unsupported. Parentheses are not
implemented; use the shell operators `&&` and `||` to combine conditions.

The built-in `printf FORMAT [VALUE ...]` formats text without adding a newline.
Its portable subset includes `%s`, `%d`, `%i`, `%u`, `%x`, `%X`, `%o`, `%c`,
`%%`, and the escapes `\n`, `\r`, `\t`, and `\\`. The format repeats when
more values remain than one pass consumes. Widths, precision, and flags are not
implemented.

Arithmetic expansion evaluates signed 64-bit integer expressions. It supports
unary `+`/`-`, parentheses, and `+`, `-`, `*`, `/`, `%` with normal arithmetic
precedence. Unset and empty variables evaluate as zero; nonnumeric values,
division by zero, and overflow are errors. For example, `set COUNT=$((COUNT + 1))`
increments an integer shell variable.

`let COUNT=COUNT+1` updates the variable directly. Multiple `let` assignments
are evaluated from left to right, so later expressions see earlier updates.
For example, a script can use `while test "$COUNT" -lt 3; do` and increment
`COUNT` with `let COUNT=COUNT+1` on each pass.

For example, a script can print and consume each argument portably:

```sh
while test "$#" -gt 0; do
    printf '%s\n' "$1"
    shift
done
```

`ls -a` uses the portable dot-name convention for hidden files. `cat` reads and
writes raw bytes. The CLI inherits the current console for child processes.
ShellDeck will need to connect the host interface to its PTY/ConPTY layer before
interactive programs such as Vim can work reliably inside its embedded terminal.

`source FILE [ARG ...]` reads a UTF-8, line-oriented script in the current shell context:
`cd` and variable changes persist, nested `source` is supported up to 32 levels,
blank lines and full-line `#` comments are skipped, and a command error stops the
script with its file and line number. Scripts can use `;`, `&&`, `||` and start
external background jobs. Scripts also support nested `if COMMAND; then` blocks
with zero or more `elif COMMAND; then` branches, an optional `else` branch, and
closing `fi`. A condition succeeds when its command returns status 0; later
conditions are skipped after a branch has matched. The `then` keyword must be on
each `if` or `elif` header line. Sourced scripts can also define reusable
functions; see the function and return rules below.

Sourced scripts support nested `for NAME in WORDS; do` and `while COMMAND; do`
loops, each closed by a standalone `done` line. A `for` list is expanded once
before iteration; each value is assigned to NAME in turn, and the variable keeps
its final value after the loop. A `while` condition runs before each iteration;
a nonzero result exits the loop. An empty `for` list runs no iterations. Loop
nesting is limited to 64 levels and can mix `for` and `while` blocks. `break`
exits the innermost active loop, and `continue` starts its next iteration. Both
take no arguments and work inside nested `if` blocks.

Sourced scripts also support `case VALUE in` blocks with one `PATTERN)` header
per line, `;;` terminators on their own lines, and a standalone `esac`. Separate
alternatives with `|`; the first matching branch runs. Patterns support `*` for
any sequence and `?` for one Unicode character. A catch-all branch uses `*`.
Character classes, fall-through terminators, and inline branch headers are not
implemented. Quoting `*` or `?` does not make the wildcard literal yet.

```sh
case "$1" in
    start|run)
        echo Starting
        ;;
    *.txt)
        echo Text file
        ;;
    *)
        echo Other
        ;;
esac
```

Scripts receive positional values as `$1` through `$9`, `${10}` and higher, and
`$#` for the argument count. A nested `source` gets its own argument list and
restores the caller's list when it returns. Expansion stays within the current
word; the shell does not split an expanded value containing spaces into several
arguments. Use braces for positional indices of 10 or greater. The
`shift [COUNT]` built-in removes that many leading script arguments (one by default);
`shift 0` leaves the list unchanged. A request larger than the available list
returns status 1 and leaves the arguments unchanged.

`return [STATUS]` stops the current sourced script or function immediately and
returns a status from 0 to 255. Without an argument it returns the last command's
status. Nested `source` calls and function calls keep their return scopes
separate.

Sourced scripts can define reusable multiline functions with `NAME() {` and a
matching `}` on its own line. Call a function by name and pass arguments as usual;
`$1` through `${10}` and `$#` refer to that call's arguments, then the caller's
arguments are restored. Functions share the shell's variables and working
directory, and their definitions remain available for the life of the
`ShellEngine`. Function names cannot replace built-ins. Calls cannot be used as
pipeline or background stages and cannot have redirection applied to the call.
`local NAME[=VALUE] ...` creates function-scoped variables. A local name hides
the prior shell value until that function returns; nested functions get their
own local scope. One-line function definitions are not implemented.

`read [NAME ...]` reads one UTF-8 line through the `ShellHost`; without a name,
it assigns to `REPLY`. Multiple names receive whitespace-separated fields, with
the last name receiving the remaining fields joined by spaces. Backslashes are
kept literally. EOF returns status 1 without changing variables. Input redirection
reads the first line of a UTF-8 file; pipelines are not supported. Hosts that do
not implement the optional `read_input_line` hook report interactive input as
unsupported.

## Build

From this directory, with Rust and Cargo installed:

```sh
cargo check
cargo build
cargo run
```

VisualEdit can open this directory directly as a Cargo project. Its current Cargo
verification detects `Cargo.toml` and runs `cargo check`/`cargo test`; use the
VisualEdit terminal for `cargo build` to produce the executable.

## Patch 303

Patch 303 behebt einen Compilerfehler beim Warten auf das letzte Kind einer
Pipeline und entfernt einen unbenutzten Import. Der Patch benötigt Patch 302.

## Patch 304

Patch 304 adds conditional blocks to sourced scripts; it requires Patch 303.

## Patch 305

Patch 305 adds `elif` branches to sourced-script conditionals; it requires
Patch 304.

## Patch 306

Patch 306 adds the explicit source lifetime required by the script condition
parser; it requires Patch 305.

## Patch 307

Patch 307 adds positional arguments to sourced scripts; it requires Patch 306.

## Patch 308

Patch 308 adds `shift [COUNT]` for consuming sourced-script arguments; it
requires Patch 307.

## Patch 309

Patch 309 adds `for NAME in WORDS; do` loops to sourced scripts; it requires
Patch 308.

## Patch 310

Patch 310 adds `break` and `continue` to sourced `for` loops; each controls the
innermost active loop and takes no arguments. It requires Patch 309.

## Patch 311

Patch 311 adds `while COMMAND; do` loops to sourced scripts. It supports nesting
with `for` loops and requires Patch 310.

## Patch 312

Patch 312 removes an unused `last_result` initialization reported by `cargo check`
for Patch 311; it requires Patch 311.

## Patch 313

Patch 313 adds portable `test` and `[ ... ]` built-ins for string and integer
conditions; it requires Patch 312.

## Patch 314

Patch 314 adds `-a` and `-o` to `test` and `[ ... ]`, with AND precedence over
OR. It requires Patch 313.

## Patch 315

Patch 315 adds a portable `printf` subset and requires Patch 314.

## Patch 316

Patch 316 adds the optional `ShellHost::path_kind` metadata hook and its CLI
implementation; it requires Patch 315.

## Patch 317

Patch 317 adds `test -e`, `test -f`, and `test -d` using `ShellHost::path_kind`;
it requires Patch 316.

## Patch 318

Patch 318 adds `$((EXPRESSION))` signed integer arithmetic expansion and
requires Patch 317.

## Patch 319

Patch 319 adds `let NAME=EXPRESSION` arithmetic assignments and requires Patch 318.

## Patch 320

Patch 320 adds `return [STATUS]` for ending the current sourced script and
requires Patch 319.

## Patch 321

Patch 321 adds reusable multiline functions to sourced scripts and requires
Patch 320.

## Patch 322

Patch 322 adds function-scoped `local NAME[=VALUE]` variables and requires
Patch 321.

## Patch 323

Patch 323 adds the `read [NAME ...]` built-in and the optional
`ShellHost::read_input_line` hook; it requires Patch 322.

## Patch 324

Patch 324 adds `$?` status expansion and requires Patch 323.

## Patch 325

Patch 325 adds `case` blocks with `*` and `?` matching to sourced scripts and
requires Patch 324.

## Patch 326

Patch 326 adds `${NAME-WORD}` and `${NAME:-WORD}` default-value expansions and
requires Patch 325.

## Patch 327

Patch 327 adds `${NAME+WORD}` and `${NAME:+WORD}` alternate-value expansions and
requires Patch 326.

## Patch 328

Patch 328 adds `${NAME?MESSAGE}` required-value diagnostics for unset variables
and requires Patch 327.

## Patch 329

Patch 329 adds `${NAME:?MESSAGE}` diagnostics for unset or empty variables and
requires Patch 328.

## Patch 330

Patch 330 adds `${#NAME}` Unicode-character length expansion and requires Patch
329.

## Patch 331

Patch 331 adds shortest and longest prefix/suffix removal expansions and
requires Patch 330.

## Patch 332

Patch 332 adds unquoted leading-tilde expansion using the host home directory
and requires Patch 331.

## Patch 333

Patch 333 adds unquoted `~+` and `~+/PATH` expansion using the current working
directory and requires Patch 332.

## Patch 334

Patch 334 adds unquoted `~-` and `~-/PATH` expansion using the previous working
directory and requires Patch 333.

## Patch 335

Patch 335 makes `cd -` print the destination path after a successful switch and
requires Patch 334.

## Patch 336

Patch 336 adds `pushd [PATH]`, the directory stack, and previous-directory swap
behavior for argument-less `pushd`; it requires Patch 335.

## Patch 337

Patch 337 adds `popd` to restore and remove the most recently saved directory;
it requires Patch 336.

## Patch 338

Patch 338 adds `dirs` to display the current directory and the directory stack;
it requires Patch 337.

## Patch 339

Patch 339 adds `dirs -p` line-oriented output and `dirs -c` stack clearing; it
requires Patch 338.

## Patch 340

Patch 340 adds numbered `dirs -v` output for directory-stack entries and
requires Patch 339.

## Patch 341

Patch 341 adds indexed `pushd +N` rotation and `popd +N` removal based on the
`dirs -v` numbering; it requires Patch 340.

## Patch 342

Patch 342 updates `PWD` and `OLDPWD` after successful `cd` operations and
requires Patch 341.

## Patch 343

Patch 343 also updates `PWD` and `OLDPWD` after successful `pushd` and `popd`
directory changes; it requires Patch 342.

## Patch 344

Patch 344 adds `cd -- [PATH]` to disambiguate paths beginning with `-`; without
a path, `cd --` returns to the home directory. It requires Patch 343.

## Patch 345

Patch 345 adds `pushd -- PATH` to treat a `+N`-looking value as a path instead
of an indexed stack operation; `pushd --` behaves like `pushd` without an
argument. It requires Patch 344.

## Patch 346

Patch 346 adds an optional `ShellHost::run_interactive_program` hook. Hosts can
use it to attach foreground programs to their terminal; existing hosts fall
back to the pipeline API. It requires Patch 345.

## Patch 347

Patch 347 routes a single foreground external command without redirections
through the interactive hook. Pipelines, background jobs, and redirected
commands continue through the existing pipeline API; it requires Patch 346.


## Optional ShellDeck GUI backend (Patches 348–349)

ShellDeck can offer this Rust CLI as an explicitly selected terminal backend
when it finds an already-built executable. Build it from this directory with
`cargo build --release`, then restart ShellDeck. The executable is expected at
`target/release/shelldeck-shell` (`shelldeck-shell.exe` on Windows). `cargo check`
checks the source but does not create this executable. ShellDeck keeps its
existing default backend and all installed system shells selectable.

The GUI starts the CLI inside its existing PTY/ConPTY process layer and uses its
prompt to track directory changes. The CLI's line editor handles shell prompt
editing, while foreground programs inherit the terminal through the host hook.


Patch 349 teaches the GUI to recognize the CLI's `PATH >` prompt, synchronize
`PWD`/`VIRTUAL_ENV` after directory-stack commands, and map `cls` to `clear` on
all platforms. Patches 350–352 add interactive foreground execution and an
editable command line to the Rust CLI.


## Patch 355

The CLI now uses Reedline 0.52.1 for interactive input. In ShellDeck's VT view,
left-clicking the active command line moves the insertion cursor. Right-click
continues to open ShellDeck's context menu, and middle-click continues to paste
the primary selection. The ShellDeck prompt is green. The terminal renderer
already supports ANSI 16-color, 256-color, and truecolor output; color can be
checked with a command that emits SGR colors, such as `printf`.

Reedline 0.52.1 requires Rust 1.95 or newer. When updating from Patch 354,
`cargo check` refreshes the Cargo lockfile for the new line-editor dependency.
Reedline is MIT-licensed; include its attribution in ShellDeck's third-party
notices when distributing a build that contains the Rust CLI.


## Patch 350

The standalone CLI implements `ShellHost::run_interactive_program` for a single
foreground command without redirection. The child inherits stdin, stdout, and
stderr, uses the shell's current directory and variable overrides, and returns
its exit status to the shell. Commands with redirected stderr fall back to the
pipeline path. This enables a terminal host's PTY/ConPTY to reach the child.


## Patch 351

The CLI prompt loop now reads through `ShellHost::read_input_line`, the same
host operation used by the `read` built-in. Command input and the `read`
built-in therefore use one host entry point, which can be adapted consistently
if the CLI later gains a richer input layer.


## Patch 352

The CLI host uses Rustyline for interactive command input. The line editor
handles arrow keys, cursor movement, deletion, and an in-memory command history;
it restores terminal input mode before the shell starts a foreground program.
When stdin is not a terminal, Rustyline keeps a direct line-reading fallback.
The library ShellHost interface remains independent of Rustyline.
