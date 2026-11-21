//! A reusable command interpreter, independent from Qt and ShellDeck's UI.
//!
//! Filesystem, output, and process operations are supplied by `ShellHost`.
//! This leaves the language core portable and lets future desktop hosts connect
//! the same interpreter to their own terminal process layer.

use std::collections::BTreeMap;
use std::error::Error;
use std::ffi::OsString;
use std::fmt;
use std::io;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DirectoryEntry {
    pub name: String,
    pub is_directory: bool,
    /// Portable first-stage convention: names beginning with `.` are hidden.
    pub is_hidden: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShellPathKind {
    File,
    Directory,
    Other,
}

#[derive(Debug, Clone)]
pub enum PipelineInput {
    Inherit,
    Bytes(Vec<u8>),
    File(PathBuf),
}

#[derive(Debug, Clone)]
pub enum StreamTarget {
    Inherit,
    Capture,
    File { path: PathBuf, append: bool },
}

#[derive(Debug, Clone)]
pub enum ErrorTarget {
    Inherit,
    File { path: PathBuf, append: bool },
}

#[derive(Debug, Clone)]
pub struct ProcessCommand {
    pub program: OsString,
    pub args: Vec<OsString>,
    pub stderr: ErrorTarget,
}

#[derive(Debug, Default)]
pub struct ProcessResult {
    pub status: i32,
    /// Populated when the final stdout target is `StreamTarget::Capture`.
    pub stdout: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BackgroundJobInfo {
    pub id: u32,
    pub command: String,
    /// `None` while the job is still running; otherwise the final pipeline status.
    pub status: Option<i32>,
}

/// Operations the shell needs from its host application.
pub trait ShellHost {
    fn write_stdout(&mut self, text: &str) -> io::Result<()>;
    fn write_stdout_bytes(&mut self, bytes: &[u8]) -> io::Result<()>;
    fn write_stderr(&mut self, text: &str) -> io::Result<()>;
    fn current_dir(&self) -> io::Result<PathBuf>;
    fn home_dir(&self) -> Option<PathBuf>;
    fn env_var(&self, name: &str) -> Option<String>;
    /// Reads one line from the host's interactive input. Hosts without an
    /// interactive input source can keep the default unsupported behavior.
    fn read_input_line(&mut self) -> io::Result<Option<String>> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "interactive line input is not supported by this shell host",
        ))
    }
    fn set_current_dir(&mut self, path: &Path) -> io::Result<()>;
    /// Returns portable path metadata; `None` means the path does not exist.
    /// Hosts that do not provide metadata can keep their current implementation;
    /// file-test built-ins will report that the operation is unsupported.
    fn path_kind(&self, _path: &Path) -> io::Result<Option<ShellPathKind>> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "path metadata is not supported by this shell host",
        ))
    }
    fn read_dir(&mut self, path: &Path) -> io::Result<Vec<DirectoryEntry>>;
    fn read_file_bytes(&mut self, path: &Path) -> io::Result<Vec<u8>>;
    fn write_file_bytes(&mut self, path: &Path, bytes: &[u8], append: bool) -> io::Result<()>;
    fn create_dir(&mut self, path: &Path, recursive: bool) -> io::Result<()>;
    fn run_pipeline(
        &mut self,
        commands: &[ProcessCommand],
        working_dir: &Path,
        variables: &BTreeMap<String, String>,
        stdin: PipelineInput,
        stdout: StreamTarget,
    ) -> io::Result<ProcessResult>;
    /// Optionally runs one foreground program attached to the host's
    /// interactive terminal. Return `Some(status)` when handled; return `None`
    /// to let the shell use `run_pipeline` instead. The default preserves the
    /// existing non-interactive host behavior.
    fn run_interactive_program(
        &mut self,
        _command: &ProcessCommand,
        _working_dir: &Path,
        _variables: &BTreeMap<String, String>,
    ) -> io::Result<Option<i32>> {
        Ok(None)
    }
    /// Starts an external pipeline without waiting for completion.
    /// Hosts that do not support jobs can keep their existing implementation;
    /// the shell will report this operation as unsupported when requested.
    fn start_background_pipeline(
        &mut self,
        _commands: &[ProcessCommand],
        _working_dir: &Path,
        _variables: &BTreeMap<String, String>,
        _stdin: PipelineInput,
        _stdout: StreamTarget,
        _command: &str,
    ) -> io::Result<u32> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "background jobs are not supported by this shell host",
        ))
    }
    fn background_jobs(&mut self) -> io::Result<Vec<BackgroundJobInfo>> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "background jobs are not supported by this shell host",
        ))
    }
    /// Waits for one job, or all current jobs when `job_id` is `None`.
    /// A host should remove successfully waited jobs from its job table.
    fn wait_background_job(
        &mut self,
        _job_id: Option<u32>,
    ) -> io::Result<Vec<BackgroundJobInfo>> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "waiting for background jobs is not supported by this shell host",
        ))
    }
    fn clear_screen(&mut self) -> io::Result<()>;
}

#[derive(Debug)]
pub enum ShellError {
    Parse(String),
    Script(String),
    Host(io::Error),
}

impl fmt::Display for ShellError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Parse(message) => f.write_str(message),
            Self::Script(message) => f.write_str(message),
            Self::Host(error) => write!(f, "shell host error: {error}"),
        }
    }
}

impl Error for ShellError {}

impl From<io::Error> for ShellError {
    fn from(error: io::Error) -> Self {
        Self::Host(error)
    }
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct CommandResult {
    pub status: i32,
    pub should_exit: bool,
}

#[derive(Debug)]
struct ScriptConditional {
    parent_active: bool,
    branch_taken: bool,
    in_else_branch: bool,
    line_number: usize,
}

#[derive(Debug, Clone)]
struct ScriptFunction {
    body: Vec<String>,
    path: PathBuf,
    line_offset: usize,
}

#[derive(Debug)]
struct VirtualEnvironmentState {
    previous_path: Option<String>,
    previous_virtual_env: Option<String>,
    previous_virtual_env_prompt: Option<String>,
}

#[derive(Debug)]
struct ScriptCaseBranch {
    patterns: Vec<String>,
    body_start: usize,
    body_end: usize,
}

#[derive(Debug)]
enum ParameterExpansion {
    Simple(String),
    Length(String),
    RemovePattern {
        name: String,
        pattern: String,
        from_prefix: bool,
        longest: bool,
    },
    Default {
        name: String,
        word: String,
        when_empty: bool,
    },
    Alternate {
        name: String,
        word: String,
        when_nonempty: bool,
    },
    Required {
        name: String,
        message: String,
        when_empty: bool,
    },
}

impl ScriptConditional {
    fn is_active(&self) -> bool {
        self.parent_active
            && if self.in_else_branch {
                !self.branch_taken
            } else {
                self.branch_taken
            }
    }
}

fn script_block_is_active(conditionals: &[ScriptConditional]) -> bool {
    conditionals.iter().all(ScriptConditional::is_active)
}

fn starts_script_keyword(command: &str, keyword: &str) -> bool {
    command == keyword
        || command
            .strip_prefix(keyword)
            .is_some_and(|rest| rest.chars().next().is_some_and(char::is_whitespace))
}

fn script_function_header(command: &str) -> Result<Option<String>, String> {
    let Some(candidate) = command.strip_suffix("() {") else {
        return Ok(None);
    };
    let name = candidate.trim();
    if !valid_variable_name(name)
        || is_builtin(name)
        || matches!(name, "if" | "elif" | "else" | "fi" | "for" | "while" | "done")
    {
        return Err(format!("Ungültiger oder reservierter Funktionsname: {name}"));
    }
    Ok(Some(name.to_owned()))
}

fn find_script_function_end(lines: &[&str], start: usize) -> Option<usize> {
    let mut depth = 1usize;
    for (index, line) in lines.iter().enumerate().skip(start + 1) {
        let command = line.trim();
        if command.is_empty() || command.starts_with('#') {
            continue;
        }
        if command.ends_with("() {") {
            depth += 1;
        } else if command == "}" {
            depth -= 1;
            if depth == 0 {
                return Some(index);
            }
        }
    }
    None
}

fn parse_script_case_header<H: ShellHost>(
    command: &str,
    variables: &BTreeMap<String, String>,
    previous_dir: Option<&Path>,
    script_arguments: &[String],
    last_status: i32,
    host: &H,
) -> Result<String, String> {
    let mut words = Vec::new();
    for token in tokenize(
        command,
        variables,
        previous_dir,
        script_arguments,
        last_status,
        host,
    )? {
        match token {
            Token::Word(word) => words.push(word),
            _ => return Err("case-Kopf darf nur Argumente enthalten.".to_owned()),
        }
    }
    if words.len() != 3 || words[0] != "case" || words[2] != "in" {
        return Err("Syntax: case WERT in".to_owned());
    }
    Ok(words.remove(1))
}

fn find_script_case_end(lines: &[&str], start: usize) -> Option<usize> {
    let mut depth = 1usize;
    for (index, line) in lines.iter().enumerate().skip(start + 1) {
        let command = line.trim();
        if command.is_empty() || command.starts_with('#') {
            continue;
        }
        if starts_script_keyword(command, "case") {
            depth += 1;
        } else if command == "esac" {
            depth -= 1;
            if depth == 0 {
                return Some(index);
            }
        }
    }
    None
}

fn parse_script_case_patterns<H: ShellHost>(
    line: &str,
    variables: &BTreeMap<String, String>,
    previous_dir: Option<&Path>,
    script_arguments: &[String],
    last_status: i32,
    host: &H,
) -> Result<Vec<String>, String> {
    let patterns = line
        .trim()
        .strip_suffix(')')
        .ok_or_else(|| "case-Zweig erwartet PATTERN) als eigene Zeile.".to_owned())?
        .trim();
    if patterns.is_empty() {
        return Err("case-Zweig benötigt mindestens ein Muster.".to_owned());
    }

    let mut alternatives = Vec::new();
    let mut start = 0usize;
    let mut quote = None;
    let mut escaped = false;
    for (index, character) in patterns.char_indices() {
        if escaped {
            escaped = false;
            continue;
        }
        if character == '\\' {
            escaped = true;
            continue;
        }
        if let Some(quote_character) = quote {
            if character == quote_character {
                quote = None;
            }
            continue;
        }
        if matches!(character, '\'' | '"') {
            quote = Some(character);
        } else if character == '|' {
            alternatives.push(patterns[start..index].trim());
            start = index + character.len_utf8();
        }
    }
    if quote.is_some() {
        return Err("Nicht geschlossenes Anführungszeichen im case-Muster.".to_owned());
    }
    alternatives.push(patterns[start..].trim());

    let mut parsed = Vec::with_capacity(alternatives.len());
    for alternative in alternatives {
        if alternative.is_empty() {
            return Err("Leeres Muster in case-Alternativen.".to_owned());
        }
        let mut tokens = tokenize(
            alternative,
            variables,
            previous_dir,
            script_arguments,
            last_status,
            host,
        )?;
        match tokens.pop() {
            Some(Token::Word(pattern)) if tokens.is_empty() => parsed.push(pattern),
            _ => return Err("Jedes case-Muster muss genau ein Wort ergeben.".to_owned()),
        }
    }
    Ok(parsed)
}

fn parse_script_case_branches<H: ShellHost>(
    lines: &[&str],
    start: usize,
    end: usize,
    variables: &BTreeMap<String, String>,
    previous_dir: Option<&Path>,
    script_arguments: &[String],
    last_status: i32,
    host: &H,
) -> Result<Vec<ScriptCaseBranch>, String> {
    let mut branches = Vec::new();
    let mut index = start + 1;
    while index < end {
        let command = lines[index].trim();
        if command.is_empty() || command.starts_with('#') {
            index += 1;
            continue;
        }
        let patterns = parse_script_case_patterns(
            command,
            variables,
            previous_dir,
            script_arguments,
            last_status,
            host,
        )?;
        let body_start = index + 1;
        index = body_start;
        let mut nested_case_depth = 0usize;
        let mut body_end = None;
        while index < end {
            let body_command = lines[index].trim();
            if starts_script_keyword(body_command, "case") {
                nested_case_depth += 1;
            } else if body_command == "esac" && nested_case_depth > 0 {
                nested_case_depth -= 1;
            } else if body_command == ";;" && nested_case_depth == 0 {
                body_end = Some(index);
                index += 1;
                break;
            } else if body_command == "esac" && nested_case_depth == 0 {
                return Err("case-Zweig endet ohne `;;`.".to_owned());
            }
            index += 1;
        }
        let body_end = body_end.ok_or_else(|| "case-Zweig endet ohne `;;`.".to_owned())?;
        branches.push(ScriptCaseBranch {
            patterns,
            body_start,
            body_end,
        });
    }
    Ok(branches)
}

fn case_pattern_matches(pattern: &str, value: &str) -> bool {
    let pattern: Vec<char> = pattern.chars().collect();
    let value: Vec<char> = value.chars().collect();
    let mut pattern_index = 0usize;
    let mut value_index = 0usize;
    let mut last_star = None;
    let mut star_value_index = 0usize;

    while value_index < value.len() {
        if pattern_index < pattern.len()
            && (pattern[pattern_index] == '?' || pattern[pattern_index] == value[value_index])
        {
            pattern_index += 1;
            value_index += 1;
        } else if pattern_index < pattern.len() && pattern[pattern_index] == '*' {
            last_star = Some(pattern_index);
            pattern_index += 1;
            star_value_index = value_index;
        } else if let Some(star_index) = last_star {
            star_value_index += 1;
            value_index = star_value_index;
            pattern_index = star_index + 1;
        } else {
            return false;
        }
    }
    while pattern_index < pattern.len() && pattern[pattern_index] == '*' {
        pattern_index += 1;
    }
    pattern_index == pattern.len()
}

fn remove_parameter_pattern(
    value: &str,
    pattern: &str,
    from_prefix: bool,
    longest: bool,
) -> String {
    let candidates = value
        .char_indices()
        .map(|(index, _)| index)
        .chain(std::iter::once(value.len()));
    let matching: Vec<usize> = candidates
        .filter(|index| {
            let candidate = if from_prefix {
                &value[..*index]
            } else {
                &value[*index..]
            };
            case_pattern_matches(pattern, candidate)
        })
        .collect();
    let selected = match (from_prefix, longest) {
        (true, false) | (false, true) => matching.first(),
        (true, true) | (false, false) => matching.last(),
    };
    let Some(index) = selected else {
        return value.to_owned();
    };
    if from_prefix {
        value[*index..].to_owned()
    } else {
        value[..*index].to_owned()
    }
}

fn tilde_prefix_can_expand(next: Option<char>) -> bool {
    match next {
        None => true,
        Some(character) => {
            character.is_whitespace()
                || matches!(character, '/' | '\\' | '|' | ';' | '&' | '<' | '>')
        }
    }
}

fn script_condition<'a>(command: &'a str, keyword: &str) -> Option<&'a str> {
    let rest = command.strip_prefix(keyword)?;
    if !rest.chars().next().is_some_and(char::is_whitespace) {
        return None;
    }
    let rest = rest.trim_start();
    let before_then = rest.strip_suffix("then")?.trim_end();
    let condition = before_then.strip_suffix(';')?.trim();
    (!condition.is_empty()).then_some(condition)
}

fn script_while_condition(command: &str) -> Option<&str> {
    let rest = command.strip_prefix("while")?;
    if !rest.chars().next().is_some_and(char::is_whitespace) {
        return None;
    }
    let condition = rest.trim_start().strip_suffix("; do")?.trim();
    (!condition.is_empty()).then_some(condition)
}

fn parse_script_for_header<H: ShellHost>(
    command: &str,
    variables: &BTreeMap<String, String>,
    previous_dir: Option<&Path>,
    script_arguments: &[String],
    last_status: i32,
    host: &H,
) -> Result<(String, Vec<String>), String> {
    let header = command
        .strip_suffix("; do")
        .ok_or_else(|| "Syntax: for NAME in WERT...; do".to_owned())?;
    let mut words = Vec::new();
    for token in tokenize(
        header,
        variables,
        previous_dir,
        script_arguments,
        last_status,
        host,
    )? {
        match token {
            Token::Word(word) => words.push(word),
            _ => return Err("for-Kopf darf nur Argumente enthalten.".to_owned()),
        }
    }
    if words.len() < 3
        || words[0] != "for"
        || words[2] != "in"
        || !valid_variable_name(&words[1])
    {
        return Err("Syntax: for NAME in WERT...; do".to_owned());
    }
    let variable = words[1].clone();
    let values = words.into_iter().skip(3).collect();
    Ok((variable, values))
}

fn find_script_loop_end(lines: &[&str], start: usize) -> Option<usize> {
    let mut depth = 1usize;
    for (index, line) in lines.iter().enumerate().skip(start + 1) {
        let command = line.trim();
        if command.is_empty() || command.starts_with('#') {
            continue;
        }
        if starts_script_keyword(command, "for") || starts_script_keyword(command, "while") {
            depth += 1;
        } else if command == "done" {
            depth -= 1;
            if depth == 0 {
                return Some(index);
            }
        }
    }
    None
}

#[derive(Debug, Default)]
pub struct ShellEngine {
    history: Vec<String>,
    variables: BTreeMap<String, String>,
    virtual_environment_state: Option<VirtualEnvironmentState>,
    functions: BTreeMap<String, ScriptFunction>,
    function_local_stack: Vec<BTreeMap<String, Option<String>>>,
    script_arguments: Vec<String>,
    previous_dir: Option<PathBuf>,
    directory_stack: Vec<PathBuf>,
    script_depth: usize,
    script_return_stack: Vec<Option<i32>>,
    loop_depth: usize,
    pending_loop_control: Option<LoopControl>,
    last_status: i32,
}

impl ShellEngine {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn history(&self) -> &[String] {
        &self.history
    }

    pub fn variables(&self) -> &BTreeMap<String, String> {
        &self.variables
    }

    fn shell_variable_or_host<H: ShellHost>(&self, name: &str, host: &H) -> Option<String> {
        self.variables
            .get(name)
            .cloned()
            .or_else(|| host.env_var(name))
            .filter(|value| !value.trim().is_empty())
    }

    fn shell_path_entries<H: ShellHost>(&self, host: &H) -> Vec<PathBuf> {
        self.shell_variable_or_host("PATH", host)
            .map(|path| std::env::split_paths(&OsString::from(path)).collect())
            .unwrap_or_default()
    }

    fn active_python_venv_path<H: ShellHost>(
        &self,
        host: &H,
    ) -> Result<Option<PathBuf>, ShellError> {
        // An empty shell-local value explicitly masks an inherited host
        // environment after `deactivate`; do not rediscover it from PATH.
        if self
            .variables
            .get("VIRTUAL_ENV")
            .is_some_and(|value| value.trim().is_empty())
        {
            return Ok(None);
        }
        if let Some(path) = self.shell_variable_or_host("VIRTUAL_ENV", host) {
            return Ok(Some(PathBuf::from(path)));
        }

        // Some activation mechanisms only prepend the venv's bin/Scripts
        // directory to PATH. Detect that standard layout as a fallback.
        let Some(first_path) = self.shell_path_entries(host).into_iter().next() else {
            return Ok(None);
        };
        let scripts_name = first_path
            .file_name()
            .map(|name| name.to_string_lossy().to_ascii_lowercase())
            .unwrap_or_default();
        if !matches!(scripts_name.as_str(), "bin" | "scripts") {
            return Ok(None);
        }
        let Some(venv_path) = first_path.parent() else {
            return Ok(None);
        };
        let config = venv_path.join("pyvenv.cfg");
        if host.path_kind(&config)? == Some(ShellPathKind::File) {
            Ok(Some(venv_path.to_path_buf()))
        } else {
            Ok(None)
        }
    }

    fn venv_python_path<H: ShellHost>(
        &self,
        venv_path: &Path,
        host: &H,
    ) -> Result<Option<PathBuf>, ShellError> {
        let candidates: &[&str] = if cfg!(windows) {
            &["Scripts/python.exe", "Scripts/python3.exe"]
        } else {
            &["bin/python", "bin/python3"]
        };
        for candidate in candidates {
            let path = venv_path.join(candidate);
            if host.path_kind(&path)? == Some(ShellPathKind::File) {
                return Ok(Some(path));
            }
        }
        Ok(None)
    }

    fn find_python_on_path<H: ShellHost>(
        &self,
        name: &str,
        host: &H,
    ) -> Result<Option<PathBuf>, ShellError> {
        let mut names = vec![name.to_owned()];
        if cfg!(windows) && Path::new(name).extension().is_none() {
            let extensions = self
                .shell_variable_or_host("PATHEXT", host)
                .unwrap_or_else(|| ".COM;.EXE;.BAT;.CMD".to_owned());
            for extension in extensions.split(';').filter(|value| !value.is_empty()) {
                names.push(format!("{name}{extension}"));
            }
        }
        for directory in self.shell_path_entries(host) {
            for candidate_name in &names {
                let candidate = directory.join(candidate_name);
                if host.path_kind(&candidate)? == Some(ShellPathKind::File) {
                    return Ok(Some(candidate));
                }
            }
        }
        Ok(None)
    }

    fn append_venv_info<H: ShellHost>(
        &self,
        output: &mut Vec<u8>,
        host: &mut H,
    ) -> Result<(), ShellError> {
        if let Some(venv_path) = self.active_python_venv_path(host)? {
            output.extend_from_slice(b"Python-venv: aktiv\n");
            output.extend_from_slice(format!("Pfad: {}\n", venv_path.display()).as_bytes());
            if let Some(name) = venv_path.file_name() {
                output.extend_from_slice(
                    format!("Name: {}\n", name.to_string_lossy()).as_bytes(),
                );
            }
            let config = venv_path.join("pyvenv.cfg");
            if host.path_kind(&config)? == Some(ShellPathKind::File) {
                if let Ok(contents) = host.read_file_bytes(&config) {
                    let contents = String::from_utf8_lossy(&contents);
                    if let Some(version) = contents.lines().find_map(|line| {
                        let (key, value) = line.split_once('=')?;
                        key.trim()
                            .eq_ignore_ascii_case("version")
                            .then(|| value.trim())
                    }) {
                        output.extend_from_slice(
                            format!("Python-Version laut pyvenv.cfg: {version}\n").as_bytes(),
                        );
                    }
                }
            }
            if let Some(python_path) = self.venv_python_path(&venv_path, host)? {
                output.extend_from_slice(
                    format!("Python-Interpreter: {}\n", python_path.display()).as_bytes(),
                );
            } else {
                output.extend_from_slice(b"Python-Interpreter: im venv nicht gefunden\n");
            }
        } else {
            output.extend_from_slice(b"Python-venv: nicht aktiv\n");
        }
        Ok(())
    }

    fn append_python_info<H: ShellHost>(
        &self,
        output: &mut Vec<u8>,
        host: &mut H,
    ) -> Result<(), ShellError> {
        self.append_venv_info(output, host)?;
        for name in ["python", "python3"] {
            match self.find_python_on_path(name, host)? {
                Some(path) => output.extend_from_slice(
                    format!("{name} auf PATH: {}\n", path.display()).as_bytes(),
                ),
                None => output.extend_from_slice(format!("{name} auf PATH: nicht gefunden\n").as_bytes()),
            }
        }
        Ok(())
    }

    fn append_path_info<H: ShellHost>(
        &self,
        output: &mut Vec<u8>,
        host: &H,
    ) -> Result<(), ShellError> {
        let entries = self.shell_path_entries(host);
        output.extend_from_slice(format!("PATH-Einträge: {}\n", entries.len()).as_bytes());
        if entries.is_empty() {
            output.extend_from_slice(b"PATH ist nicht gesetzt oder leer.\n");
            return Ok(());
        }
        for (index, entry) in entries.iter().enumerate() {
            let state = match host.path_kind(entry)? {
                Some(ShellPathKind::Directory) => "Verzeichnis vorhanden",
                Some(ShellPathKind::File) => "Datei statt Verzeichnis",
                Some(ShellPathKind::Other) => "kein Verzeichnis",
                None => "nicht vorhanden",
            };
            output.extend_from_slice(
                format!("[{}] {} — {}\n", index + 1, entry.display(), state).as_bytes(),
            );
        }
        Ok(())
    }

    fn append_shell_info<H: ShellHost>(
        &self,
        output: &mut Vec<u8>,
        host: &mut H,
    ) -> Result<(), ShellError> {
        output.extend_from_slice(
            format!(
                "ShellDeck Shell: {}\nBetriebssystem: {}\nArchitektur: {}\nArbeitsverzeichnis: {}\nShell-Variablen: {}\nPATH-Einträge: {}\n",
                env!("CARGO_PKG_VERSION"),
                std::env::consts::OS,
                std::env::consts::ARCH,
                host.current_dir()?.display(),
                self.variables.len(),
                self.shell_path_entries(host).len(),
            )
            .as_bytes(),
        );
        self.append_venv_info(output, host)
    }

    fn append_diagnostics<H: ShellHost>(
        &self,
        args: &[String],
        output: &mut Vec<u8>,
        host: &mut H,
    ) -> Result<(), ShellError> {
        if args.len() > 1
            || args
                .first()
                .is_some_and(|section| !matches!(section.as_str(), "venv" | "python" | "path" | "shell"))
        {
            return Err(ShellError::Parse(
                "Verwendung: diagnose [venv|python|path|shell]".to_owned(),
            ));
        }
        match args.first().map(String::as_str) {
            Some("venv") => self.append_venv_info(output, host),
            Some("python") => self.append_python_info(output, host),
            Some("path") => self.append_path_info(output, host),
            Some("shell") => self.append_shell_info(output, host),
            Some(_) => Err(ShellError::Parse(
                "Verwendung: diagnose [venv|python|path|shell]".to_owned(),
            )),
            None => {
                output.extend_from_slice(b"=== ShellDeck Shell ===\n");
                self.append_shell_info(output, host)?;
                output.extend_from_slice(b"\n=== Python-Aufloesung ===\n");
                self.append_python_info(output, host)
            }
        }
    }

    /// Parses and executes one line without delegating to a system shell.
    pub fn execute_line<H: ShellHost>(
        &mut self,
        line: &str,
        host: &mut H,
    ) -> Result<CommandResult, ShellError> {
        let line = line.trim();
        if line.is_empty() {
            return Ok(CommandResult::default());
        }
        self.history.push(line.to_owned());
        let tokens = tokenize(
            line,
            &self.variables,
            self.previous_dir.as_deref(),
            &self.script_arguments,
            self.last_status,
            host,
        )
        .map_err(ShellError::Parse)?;
        let commands = parse_tokens(tokens).map_err(ShellError::Parse)?;
        let mut last_result = CommandResult::default();
        for command in commands {
            let should_run = match command.condition {
                CommandCondition::Always => true,
                CommandCondition::OnSuccess => last_result.status == 0,
                CommandCondition::OnFailure => last_result.status != 0,
            };
            if !should_run {
                continue;
            }
            let command_label = format_command_label(&command.stages, command.background);
            last_result = self.execute_stages(
                command.stages,
                command.background,
                &command_label,
                host,
            )?;
            self.last_status = last_result.status;
            if last_result.should_exit
                || self.pending_loop_control.is_some()
                || self.script_return_requested()
            {
                return Ok(last_result);
            }
        }
        Ok(last_result)
    }

    fn execute_stages<H: ShellHost>(
        &mut self,
        stages: Vec<ParsedStage>,
        background: bool,
        command_line: &str,
        host: &mut H,
    ) -> Result<CommandResult, ShellError> {
        if stages
            .iter()
            .any(|stage| self.functions.contains_key(&stage.words[0]))
        {
            if background || stages.len() != 1 {
                return Err(ShellError::Parse(
                    "Shell-Funktionen können derzeit nicht im Hintergrund oder in Pipes laufen."
                        .to_owned(),
                ));
            }
            let stage = &stages[0];
            if stage.stdin.is_some() || stage.stdout.is_some() || stage.stderr.is_some() {
                return Err(ShellError::Parse(
                    "Shell-Funktionen können derzeit nicht umgeleitet werden.".to_owned(),
                ));
            }
            return self.execute_script_function(&stage.words[0], &stage.words[1..], host);
        }
        if background && stages.iter().any(|stage| is_builtin(&stage.words[0])) {
            return Err(ShellError::Parse(
                "Hintergrundjobs unterstützen derzeit nur externe Programme und Pipes.".to_owned(),
            ));
        }
        let stage_count = stages.len();
        let mut index = 0;
        let mut piped_bytes: Option<Vec<u8>> = None;
        let mut last_result = CommandResult::default();

        while index < stage_count {
            if is_builtin(&stages[index].words[0]) {
                if stage_count > 1 && !pipeline_safe_builtin(&stages[index].words) {
                    return Err(ShellError::Parse(
                        "Dieser zustandsändernde Shell-Befehl darf nicht in einer Pipe laufen."
                            .to_owned(),
                    ));
                }
                if stages[index].stderr.is_some() {
                    return Err(ShellError::Parse(
                        "2> ist in dieser Stufe nur für gestartete Programme verfügbar.".to_owned(),
                    ));
                }
                if matches!(stages[index].words[0].as_str(), "source" | ".")
                    && (stages[index].stdin.is_some() || stages[index].stdout.is_some())
                {
                    return Err(ShellError::Parse(
                        "source-Skripte können in dieser Stufe nicht umgeleitet werden.".to_owned(),
                    ));
                }
                if stages[index].words[0] == "clear"
                    && (stage_count > 1 || stages[index].stdout.is_some())
                {
                    return Err(ShellError::Parse(
                        "clear kann nicht umgeleitet oder in eine Pipe gesetzt werden.".to_owned(),
                    ));
                }

                let stdin_bytes = if index == 0 {
                    match &stages[index].stdin {
                        Some(path) => {
                            let path = resolve_path(path, host)?;
                            Some(host.read_file_bytes(&path)?)
                        }
                        None => None,
                    }
                } else {
                    piped_bytes.take()
                };
                let (result, output) = self.execute_builtin(
                    &stages[index].words,
                    stdin_bytes.as_deref(),
                    host,
                )?;
                last_result = result;

                if index + 1 == stage_count {
                    write_final_output(&stages[index], output, host)?;
                } else {
                    piped_bytes = Some(output);
                }
                index += 1;
                continue;
            }

            let start = index;
            while index < stage_count && !is_builtin(&stages[index].words[0]) {
                index += 1;
            }
            let end = index;
            let mut commands = Vec::with_capacity(end - start);
            for stage in &stages[start..end] {
                let stderr = match &stage.stderr {
                    Some(redirection) => ErrorTarget::File {
                        path: resolve_path(&redirection.path, host)?,
                        append: redirection.append,
                    },
                    None => ErrorTarget::Inherit,
                };
                commands.push(ProcessCommand {
                    program: OsString::from(stage.words[0].as_str()),
                    args: stage.words[1..]
                        .iter()
                        .map(|arg| OsString::from(arg.as_str()))
                        .collect(),
                    stderr,
                });
            }

            let stdin = if start == 0 {
                match &stages[start].stdin {
                    Some(path) => PipelineInput::File(resolve_path(path, host)?),
                    None => PipelineInput::Inherit,
                }
            } else {
                PipelineInput::Bytes(piped_bytes.take().unwrap_or_default())
            };
            let is_final_group = end == stage_count;
            let stdout = if !is_final_group {
                StreamTarget::Capture
            } else if let Some(redirection) = &stages[end - 1].stdout {
                StreamTarget::File {
                    path: resolve_path(&redirection.path, host)?,
                    append: redirection.append,
                }
            } else {
                StreamTarget::Inherit
            };
            let working_dir = host.current_dir()?;
            let can_run_interactively = !background
                && stage_count == 1
                && stages[0].stdin.is_none()
                && stages[0].stdout.is_none()
                && stages[0].stderr.is_none();
            if can_run_interactively {
                if let Some(status) = host.run_interactive_program(
                    &commands[0],
                    &working_dir,
                    &self.variables,
                )? {
                    last_result = CommandResult {
                        status,
                        should_exit: false,
                    };
                    break;
                }
            }
            if background {
                let job_id = host.start_background_pipeline(
                    &commands,
                    &working_dir,
                    &self.variables,
                    stdin,
                    stdout,
                    command_line,
                )?;
                host.write_stdout(&format!("[{job_id}] gestartet\n"))?;
                last_result = CommandResult::default();
                break;
            }
            let process_result = host.run_pipeline(
                &commands,
                &working_dir,
                &self.variables,
                stdin,
                stdout.clone(),
            )?;
            last_result = CommandResult {
                status: process_result.status,
                should_exit: false,
            };
            if matches!(stdout, StreamTarget::Capture) {
                piped_bytes = Some(process_result.stdout);
            }
        }
        Ok(last_result)
    }

    fn execute_builtin<H: ShellHost>(
        &mut self,
        words: &[String],
        stdin_bytes: Option<&[u8]>,
        host: &mut H,
    ) -> Result<(CommandResult, Vec<u8>), ShellError> {
        let command = words[0].as_str();
        let args = &words[1..];
        let mut output = Vec::new();

        match command {
            "help" => {
                if args.is_empty()
                    || (args.len() == 1 && matches!(args[0].as_str(), "--help" | "-h"))
                {
                    output.extend_from_slice(HELP_TEXT.as_bytes());
                } else if args.len() == 1 {
                    let text = match args[0].as_str() {
                        "venv" => VENV_HELP_TEXT,
                        "diagnose" => DIAGNOSE_HELP_TEXT,
                        "wait" => WAIT_HELP_TEXT,
                        _ => {
                            return Err(ShellError::Parse(
                                "Eigene Detailhilfe: help [venv|diagnose|wait]".to_owned(),
                            ));
                        }
                    };
                    output.extend_from_slice(text.as_bytes());
                } else {
                    return Err(ShellError::Parse(
                        "Verwendung: help [venv|diagnose|wait]".to_owned(),
                    ));
                }
            }
            "pwd" => {
                output.extend_from_slice(format!("{}\n", host.current_dir()?.display()).as_bytes())
            }
            "dirs" => {
                if args.len() > 1 {
                    return Err(ShellError::Parse("Verwendung: dirs [-p|-v|-c]".to_owned()));
                }
                match args.first().map(String::as_str) {
                    Some("-c") => self.directory_stack.clear(),
                    Some("-v") => {
                        output.extend_from_slice(
                            format!("{:>3} {}\n", 0, host.current_dir()?.display()).as_bytes(),
                        );
                        for (index, path) in self.directory_stack.iter().rev().enumerate() {
                            output.extend_from_slice(
                                format!("{:>3} {}\n", index + 1, path.display()).as_bytes(),
                            );
                        }
                    }
                    Some("-p") => {
                        output.extend_from_slice(
                            format!("{}\n", host.current_dir()?.display()).as_bytes(),
                        );
                        for path in self.directory_stack.iter().rev() {
                            output.extend_from_slice(format!("{}\n", path.display()).as_bytes());
                        }
                    }
                    None => {
                        output.extend_from_slice(
                            host.current_dir()?.display().to_string().as_bytes(),
                        );
                        for path in self.directory_stack.iter().rev() {
                            output.push(b' ');
                            output.extend_from_slice(path.display().to_string().as_bytes());
                        }
                        output.push(b'\n');
                    }
                    Some(_) => {
                        return Err(ShellError::Parse("Verwendung: dirs [-p|-v|-c]".to_owned()));
                    }
                }
            }
            "cd" => return self.change_directory(args, host),
            "pushd" => return self.push_directory(args, host),
            "popd" => return self.pop_directory(args, host),
            "source" | "." => {
                if args.is_empty() {
                    return Err(ShellError::Parse(
                        "Verwendung: source DATEI [ARGUMENT ...]".to_owned(),
                    ));
                }
                return self
                    .source_script(&args[0], &args[1..], host)
                    .map(|result| (result, output));
            }
            "deactivate" => {
                if !args.is_empty() {
                    return Err(ShellError::Parse("Verwendung: deactivate".to_owned()));
                }
                return self
                    .deactivate_python_venv(host)
                    .map(|result| (result, output));
            }
            "venv" => {
                let valid_arguments = args.is_empty()
                    || (args.len() == 1
                        && matches!(args[0].as_str(), "info" | "status" | "--help" | "-h"));
                if !valid_arguments {
                    return Err(ShellError::Parse(
                        "Verwendung: venv [info|status|--help]".to_owned(),
                    ));
                }
                if args.first().is_some_and(|arg| matches!(arg.as_str(), "--help" | "-h")) {
                    output.extend_from_slice(VENV_HELP_TEXT.as_bytes());
                } else {
                    self.append_venv_info(&mut output, host)?;
                }
            }
            "diagnose" => {
                if args.len() == 1 && matches!(args[0].as_str(), "--help" | "-h") {
                    output.extend_from_slice(DIAGNOSE_HELP_TEXT.as_bytes());
                } else {
                    self.append_diagnostics(args, &mut output, host)?;
                }
            }
            "history" => {
                if args.len() == 1 && args[0] == "-c" {
                    self.history.clear();
                } else if args.is_empty() {
                    for (index, entry) in self.history.iter().enumerate() {
                        output.extend_from_slice(format!("{:>4}  {entry}\n", index + 1).as_bytes());
                    }
                } else {
                    return Err(ShellError::Parse("Verwendung: history [-c]".to_owned()));
                }
            }
            "jobs" => {
                if !args.is_empty() {
                    return Err(ShellError::Parse("Verwendung: jobs".to_owned()));
                }
                let jobs = host.background_jobs()?;
                if jobs.is_empty() {
                    output.extend_from_slice(b"Keine Hintergrundjobs.\n");
                } else {
                    for job in jobs {
                        let state = match job.status {
                            Some(status) => format!("beendet, Status {status}"),
                            None => "läuft".to_owned(),
                        };
                        output.extend_from_slice(
                            format!("[{}] {state}  {}\n", job.id, job.command).as_bytes(),
                        );
                    }
                }
            }
            "wait" => {
                if args.len() == 1 && matches!(args[0].as_str(), "--help" | "-h") {
                    output.extend_from_slice(WAIT_HELP_TEXT.as_bytes());
                    return Ok((CommandResult::default(), output));
                }
                if args.len() > 1 {
                    return Err(ShellError::Parse("Verwendung: wait [JOB_ID]".to_owned()));
                }
                let job_id = match args.first() {
                    Some(value) => Some(value.parse::<u32>().ok().filter(|id| *id > 0).ok_or_else(
                        || ShellError::Parse("JOB_ID muss eine positive Zahl sein.".to_owned()),
                    )?),
                    None => None,
                };
                let completed = host.wait_background_job(job_id)?;
                if let Some(job) = completed.last() {
                    return Ok((
                        CommandResult {
                            status: job.status.unwrap_or(0),
                            should_exit: false,
                        },
                        output,
                    ));
                }
            }
            "clear" => host.clear_screen()?,
            "echo" => {
                let (newline, values) = if args.first().is_some_and(|arg| arg == "-n") {
                    (false, &args[1..])
                } else {
                    (true, args)
                };
                output.extend_from_slice(values.join(" ").as_bytes());
                if newline {
                    output.push(b'\n');
                }
            }
            "printf" => output.extend_from_slice(&format_printf(args).map_err(ShellError::Parse)?),
            "read" => {
                return self
                    .read_variables(args, stdin_bytes, host)
                    .map(|result| (result, output));
            }
            "test" | "[" => {
                let expression = if command == "[" {
                    if args.last().map(String::as_str) != Some("]") {
                        return Err(ShellError::Parse(
                            "Verwendung: [ AUSDRUCK ]".to_owned(),
                        ));
                    }
                    &args[..args.len() - 1]
                } else {
                    args
                };
                let success = evaluate_test_expression(expression, host)
                    .map_err(ShellError::Parse)?;
                return Ok((
                    CommandResult {
                        status: if success { 0 } else { 1 },
                        should_exit: false,
                    },
                    output,
                ));
            }
            "let" => {
                return self
                    .assign_arithmetic_variables(args, host)
                    .map(|result| (result, output));
            }
            "true" => {}
            "break" | "continue" => {
                if !args.is_empty() {
                    return Err(ShellError::Parse(format!("Verwendung: {command}")));
                }
                if self.loop_depth == 0 {
                    return Err(ShellError::Parse(format!(
                        "{command} darf nur innerhalb einer Schleife verwendet werden."
                    )));
                }
                self.pending_loop_control = Some(if command == "break" {
                    LoopControl::Break
                } else {
                    LoopControl::Continue
                });
            }
            "return" => {
                if args.len() > 1 {
                    return Err(ShellError::Parse("Verwendung: return [STATUS]".to_owned()));
                }
                let status = match args.first() {
                    Some(value) => value
                        .parse::<u8>()
                        .map(i32::from)
                        .map_err(|_| ShellError::Parse(
                            "STATUS muss eine Zahl zwischen 0 und 255 sein.".to_owned(),
                        ))?,
                    None => self.last_status,
                };
                let Some(frame) = self.script_return_stack.last_mut() else {
                    return Err(ShellError::Parse(
                        "return darf nur in einem source-Skript oder einer Shell-Funktion verwendet werden."
                            .to_owned(),
                    ));
                };
                *frame = Some(status);
                return Ok((
                    CommandResult {
                        status,
                        should_exit: false,
                    },
                    output,
                ));
            }
            "false" => {
                return Ok((
                    CommandResult {
                        status: 1,
                        should_exit: false,
                    },
                    output,
                ));
            }
            "set" => self.set_variable(args, &mut output)?,
            "local" => self.set_local_variables(args)?,
            "unset" => self.unset_variables(args)?,
            "shift" => {
                if args.len() > 1 {
                    return Err(ShellError::Parse("Verwendung: shift [ANZAHL]".to_owned()));
                }
                let count = match args.first() {
                    Some(value) => value.parse::<usize>().map_err(|_| {
                        ShellError::Parse(
                            "shift: ANZAHL muss eine nichtnegative Ganzzahl sein.".to_owned(),
                        )
                    })?,
                    None => 1,
                };
                if count > self.script_arguments.len() {
                    host.write_stderr(&format!(
                        "shift: {count} Argumente können nicht entfernt werden; verfügbar: {}.\n",
                        self.script_arguments.len()
                    ))?;
                    return Ok((
                        CommandResult {
                            status: 1,
                            should_exit: false,
                        },
                        output,
                    ));
                }
                drop(self.script_arguments.drain(..count));
            }
            "ls" | "dir" => self.list_directory(args, host, &mut output)?,
            "cat" => self.print_files(args, stdin_bytes, host, &mut output)?,
            "mkdir" => self.make_directories(args, host)?,
            "exit" => {
                if args.len() > 1 {
                    return Err(ShellError::Parse("Verwendung: exit [STATUS]".to_owned()));
                }
                let status = match args.first() {
                    Some(value) => value
                        .parse::<u8>()
                        .map(i32::from)
                        .map_err(|_| ShellError::Parse(
                            "STATUS muss eine Zahl zwischen 0 und 255 sein.".to_owned(),
                        ))?,
                    None => self.last_status,
                };
                return Ok((
                    CommandResult {
                        status,
                        should_exit: true,
                    },
                    output,
                ));
            }
            _ => {
                return Err(ShellError::Parse(format!("Kein interner Befehl: {command}")));
            }
        }
        Ok((CommandResult::default(), output))
    }

    fn change_directory<H: ShellHost>(
        &mut self,
        args: &[String],
        host: &mut H,
    ) -> Result<(CommandResult, Vec<u8>), ShellError> {
        if args.len() > 2 || (args.len() == 2 && args[0] != "--") {
            return Err(ShellError::Parse(
                "Verwendung: cd [--] [PFAD|-]".to_owned(),
            ));
        }
        let print_target = args.len() == 1 && args[0] == "-";
        let old_dir = host.current_dir()?;
        let target = match args {
            [] => host
                .home_dir()
                .ok_or_else(|| ShellError::Parse("Kein Home-Verzeichnis verfügbar.".to_owned()))?,
            [marker] if marker == "--" => host
                .home_dir()
                .ok_or_else(|| ShellError::Parse("Kein Home-Verzeichnis verfügbar.".to_owned()))?,
            [path] if path == "-" => self
                .previous_dir
                .clone()
                .ok_or_else(|| ShellError::Parse("Kein vorheriges Verzeichnis.".to_owned()))?,
            [path] | [_, path] => match host.home_dir() {
                Some(home) => expand_home(path, &home),
                None => PathBuf::from(path),
            },
            _ => unreachable!("cd arguments were validated above"),
        };
        host.set_current_dir(&target)?;
        let current_dir = host.current_dir()?;
        self.previous_dir = Some(old_dir.clone());
        self.update_directory_variables(&old_dir, &current_dir);
        let output = if print_target {
            format!("{}\n", target.display()).into_bytes()
        } else {
            Vec::new()
        };
        Ok((CommandResult::default(), output))
    }

    fn update_directory_variables(&mut self, previous: &Path, current: &Path) {
        self.variables.insert(
            "OLDPWD".to_owned(),
            previous.to_string_lossy().into_owned(),
        );
        self.variables
            .insert("PWD".to_owned(), current.to_string_lossy().into_owned());
    }

    fn push_directory<H: ShellHost>(
        &mut self,
        args: &[String],
        host: &mut H,
    ) -> Result<(CommandResult, Vec<u8>), ShellError> {
        if args.len() > 2 || (args.len() == 2 && args[0] != "--") {
            return Err(ShellError::Parse(
                "Verwendung: pushd [--] [PFAD|+N]".to_owned(),
            ));
        }
        let path = match args {
            [] => None,
            [marker] if marker == "--" => None,
            [path] => Some(path.as_str()),
            [_, path] => Some(path.as_str()),
            _ => unreachable!("pushd arguments were validated above"),
        };
        if args.len() == 1 {
            let argument = args[0].as_str();
            if let Some(index) = parse_directory_stack_index(argument).map_err(ShellError::Parse)? {
                return self.rotate_directory_stack(index, host);
            }
        }
        let old_dir = host.current_dir()?;
        let target = if let Some(path) = path {
            resolve_path(path, host)?
        } else {
            self.directory_stack
                .last()
                .cloned()
                .or_else(|| self.previous_dir.clone())
                .ok_or_else(|| {
                    ShellError::Parse("Kein Verzeichnis zum Tauschen vorhanden.".to_owned())
                })?
        };
        host.set_current_dir(&target)?;
        let current_dir = host.current_dir()?;
        if path.is_none() && !self.directory_stack.is_empty() {
            self.directory_stack.pop();
        }
        self.directory_stack.push(old_dir.clone());
        self.previous_dir = Some(old_dir.clone());
        self.update_directory_variables(&old_dir, &current_dir);
        let output = format!("{}\n", target.display()).into_bytes();
        Ok((CommandResult::default(), output))
    }

    fn rotate_directory_stack<H: ShellHost>(
        &mut self,
        index: usize,
        host: &mut H,
    ) -> Result<(CommandResult, Vec<u8>), ShellError> {
        let old_dir = host.current_dir()?;
        let mut entries = Vec::with_capacity(self.directory_stack.len() + 1);
        entries.push(old_dir.clone());
        entries.extend(self.directory_stack.iter().rev().cloned());
        if index >= entries.len() {
            return Err(ShellError::Parse(format!(
                "Verzeichnisstack-Index +{index} liegt außerhalb des Stacks."
            )));
        }
        entries.rotate_left(index);
        let target = entries[0].clone();
        host.set_current_dir(&target)?;
        let current_dir = host.current_dir()?;
        entries.remove(0);
        self.directory_stack = entries.into_iter().rev().collect();
        self.previous_dir = Some(old_dir.clone());
        self.update_directory_variables(&old_dir, &current_dir);
        let output = format!("{}\n", target.display()).into_bytes();
        Ok((CommandResult::default(), output))
    }

    fn pop_directory<H: ShellHost>(
        &mut self,
        args: &[String],
        host: &mut H,
    ) -> Result<(CommandResult, Vec<u8>), ShellError> {
        if args.len() > 1 {
            return Err(ShellError::Parse("Verwendung: popd [+N]".to_owned()));
        }
        if let Some(argument) = args.first() {
            let index = parse_directory_stack_index(argument)
                .map_err(ShellError::Parse)?
                .ok_or_else(|| ShellError::Parse("Verwendung: popd [+N]".to_owned()))?;
            return self.remove_directory_stack_entry(index, host);
        }
        let target = self
            .directory_stack
            .last()
            .cloned()
            .ok_or_else(|| ShellError::Parse("Der Verzeichnisstack ist leer.".to_owned()))?;
        let old_dir = host.current_dir()?;
        host.set_current_dir(&target)?;
        let current_dir = host.current_dir()?;
        self.directory_stack.pop();
        self.previous_dir = Some(old_dir.clone());
        self.update_directory_variables(&old_dir, &current_dir);
        let output = format!("{}\n", target.display()).into_bytes();
        Ok((CommandResult::default(), output))
    }

    fn remove_directory_stack_entry<H: ShellHost>(
        &mut self,
        index: usize,
        host: &mut H,
    ) -> Result<(CommandResult, Vec<u8>), ShellError> {
        let old_dir = host.current_dir()?;
        let mut entries = Vec::with_capacity(self.directory_stack.len() + 1);
        entries.push(old_dir.clone());
        entries.extend(self.directory_stack.iter().rev().cloned());
        if index >= entries.len() {
            return Err(ShellError::Parse(format!(
                "Verzeichnisstack-Index +{index} liegt außerhalb des Stacks."
            )));
        }
        if index == 0 && entries.len() == 1 {
            return Err(ShellError::Parse(
                "Das aktuelle Verzeichnis kann nicht entfernt werden, wenn der Stack leer ist."
                    .to_owned(),
            ));
        }
        entries.remove(index);
        let target = if index == 0 {
            let target = entries[0].clone();
            host.set_current_dir(&target)?;
            let current_dir = host.current_dir()?;
            self.previous_dir = Some(old_dir.clone());
            self.update_directory_variables(&old_dir, &current_dir);
            target
        } else {
            old_dir
        };
        self.directory_stack = entries.into_iter().skip(1).rev().collect();
        let output = format!("{}\n", target.display()).into_bytes();
        Ok((CommandResult::default(), output))
    }

    fn source_script<H: ShellHost>(
        &mut self,
        path: &str,
        arguments: &[String],
        host: &mut H,
    ) -> Result<CommandResult, ShellError> {
        const MAX_SCRIPT_DEPTH: usize = 32;
        if self.script_depth >= MAX_SCRIPT_DEPTH {
            return Err(ShellError::Script(format!(
                "Maximale Verschachtelungstiefe von {MAX_SCRIPT_DEPTH} Skripten überschritten."
            )));
        }
        let resolved = resolve_path(path, host)?;
        if arguments.is_empty() {
            if let Some((venv_root, scripts_directory)) =
                self.python_venv_from_activation_path(&resolved, host)?
            {
                self.activate_python_venv(&venv_root, &scripts_directory, host)?;
                return Ok(CommandResult::default());
            }
        }
        let bytes = host.read_file_bytes(&resolved).map_err(|error| {
            ShellError::Script(format!("Skript kann nicht gelesen werden ({}): {error}", resolved.display()))
        })?;
        let contents = String::from_utf8(bytes).map_err(|_| {
            ShellError::Script(format!("Skript ist keine UTF-8-Datei: {}", resolved.display()))
        })?;
        let previous_arguments =
            std::mem::replace(&mut self.script_arguments, arguments.to_vec());
        self.script_depth += 1;
        self.script_return_stack.push(None);
        let contents = contents.strip_prefix('\u{feff}').unwrap_or(&contents);
        let lines: Vec<&str> = contents.lines().collect();
        let result = self.execute_script_lines(&lines, &resolved, 0, host, 0);
        let return_status = self.script_return_stack.pop().flatten();
        self.script_depth -= 1;
        self.script_arguments = previous_arguments;
        match (result, return_status) {
            (Ok(mut result), Some(status)) => {
                result.status = status;
                Ok(result)
            }
            (result, _) => result,
        }
    }

    fn python_venv_from_activation_path<H: ShellHost>(
        &self,
        script_path: &Path,
        host: &H,
    ) -> Result<Option<(PathBuf, PathBuf)>, ShellError> {
        let file_name = script_path
            .file_name()
            .map(|name| name.to_string_lossy().to_ascii_lowercase())
            .unwrap_or_default();
        if !matches!(
            file_name.as_str(),
            "activate" | "activate.fish" | "activate.bat" | "activate.ps1"
        ) {
            return Ok(None);
        }

        let Some(scripts_directory) = script_path.parent() else {
            return Ok(None);
        };
        let scripts_name = scripts_directory
            .file_name()
            .map(|name| name.to_string_lossy().to_ascii_lowercase())
            .unwrap_or_default();
        if !matches!(scripts_name.as_str(), "bin" | "scripts") {
            return Ok(None);
        }
        let Some(venv_root) = scripts_directory.parent() else {
            return Ok(None);
        };
        let marker = venv_root.join("pyvenv.cfg");
        if host.path_kind(&marker)? != Some(ShellPathKind::File)
            || host.path_kind(scripts_directory)? != Some(ShellPathKind::Directory)
        {
            return Ok(None);
        }
        Ok(Some((venv_root.to_path_buf(), scripts_directory.to_path_buf())))
    }

    fn activate_python_venv<H: ShellHost>(
        &mut self,
        venv_root: &Path,
        scripts_directory: &Path,
        host: &H,
    ) -> Result<(), ShellError> {
        // Switching environments first restores the state from the previous
        // native activation, just as Python's activate script does.
        if self.virtual_environment_state.is_some() {
            self.deactivate_python_venv(host)?;
        }

        let previous_path = self
            .variables
            .get("PATH")
            .cloned()
            .or_else(|| host.env_var("PATH"));
        let previous_virtual_env = self
            .variables
            .get("VIRTUAL_ENV")
            .cloned()
            .or_else(|| host.env_var("VIRTUAL_ENV"));
        let previous_virtual_env_prompt = self
            .variables
            .get("VIRTUAL_ENV_PROMPT")
            .cloned()
            .or_else(|| host.env_var("VIRTUAL_ENV_PROMPT"));

        let mut path_entries = vec![scripts_directory.to_path_buf()];
        if let Some(path) = previous_path.as_deref() {
            path_entries.extend(std::env::split_paths(&OsString::from(path)));
        }
        let path = std::env::join_paths(path_entries)
            .map_err(|_| ShellError::Parse("Der PATH der Python-Umgebung ist ungültig.".to_owned()))?
            .into_string()
            .map_err(|_| ShellError::Parse("Der PATH enthält nicht darstellbare Zeichen.".to_owned()))?;
        let venv_name = venv_root
            .file_name()
            .map(|name| name.to_string_lossy().into_owned())
            .filter(|name| !name.is_empty())
            .unwrap_or_else(|| "venv".to_owned());

        self.virtual_environment_state = Some(VirtualEnvironmentState {
            previous_path,
            previous_virtual_env,
            previous_virtual_env_prompt,
        });
        self.variables.insert("PATH".to_owned(), path);
        self.variables.insert(
            "VIRTUAL_ENV".to_owned(),
            venv_root.to_string_lossy().into_owned(),
        );
        self.variables.insert(
            "VIRTUAL_ENV_PROMPT".to_owned(),
            format!("({venv_name})"),
        );
        Ok(())
    }

    fn deactivate_python_venv<H: ShellHost>(
        &mut self,
        host: &H,
    ) -> Result<CommandResult, ShellError> {
        if let Some(state) = self.virtual_environment_state.take() {
            restore_shell_variable(&mut self.variables, "PATH", state.previous_path);
            restore_shell_variable(
                &mut self.variables,
                "VIRTUAL_ENV",
                state.previous_virtual_env,
            );
            restore_shell_variable(
                &mut self.variables,
                "VIRTUAL_ENV_PROMPT",
                state.previous_virtual_env_prompt,
            );
            return Ok(CommandResult::default());
        }

        if !self.clear_inherited_python_venv(host)? {
            return Err(ShellError::Parse(
                "Keine aktive Python-Umgebung vorhanden.".to_owned(),
            ));
        }
        Ok(CommandResult::default())
    }

    /// Clears the Python venv inherited from the parent application. ShellDeck
    /// calls this before the first prompt in GUI terminal tabs; standalone CLI
    /// sessions keep their inherited environment unless explicitly requested.
    pub fn clear_inherited_python_venv<H: ShellHost>(
        &mut self,
        host: &H,
    ) -> Result<bool, ShellError> {
        if self.virtual_environment_state.is_some() {
            return Ok(false);
        }
        let Some(venv_root) = self.active_python_venv_path(host)? else {
            return Ok(false);
        };
        let scripts_directory = venv_root.join(if cfg!(windows) { "Scripts" } else { "bin" });
        let path_value = self
            .shell_variable_or_host("PATH", host)
            .unwrap_or_default();
        let path_value_os = OsString::from(path_value);
        let path_entries = std::env::split_paths(&path_value_os);
        let filtered_entries: Vec<PathBuf> = path_entries
            .filter(|entry| !same_path_entry(entry, &scripts_directory))
            .collect();
        let path = std::env::join_paths(filtered_entries)
            .map_err(|_| ShellError::Parse("Der PATH der Python-Umgebung ist ungültig.".to_owned()))?
            .into_string()
            .map_err(|_| ShellError::Parse("Der PATH enthält nicht darstellbare Zeichen.".to_owned()))?;

        self.variables.insert("PATH".to_owned(), path);
        self.variables.insert("VIRTUAL_ENV".to_owned(), String::new());
        self.variables
            .insert("VIRTUAL_ENV_PROMPT".to_owned(), String::new());
        Ok(true)
    }

    fn execute_script_function<H: ShellHost>(
        &mut self,
        name: &str,
        arguments: &[String],
        host: &mut H,
    ) -> Result<CommandResult, ShellError> {
        const MAX_FUNCTION_DEPTH: usize = 64;
        if self.script_return_stack.len() >= MAX_FUNCTION_DEPTH {
            return Err(ShellError::Script(format!(
                "Maximale Verschachtelungstiefe von {MAX_FUNCTION_DEPTH} Skript- und Funktionsaufrufen überschritten."
            )));
        }
        let function = self.functions.get(name).cloned().ok_or_else(|| {
            ShellError::Parse(format!("Unbekannte Shell-Funktion: {name}"))
        })?;
        let previous_arguments =
            std::mem::replace(&mut self.script_arguments, arguments.to_vec());
        self.function_local_stack.push(BTreeMap::new());
        self.script_return_stack.push(None);
        let lines: Vec<&str> = function.body.iter().map(String::as_str).collect();
        let result = self.execute_script_lines(
            &lines,
            &function.path,
            function.line_offset,
            host,
            0,
        );
        let return_status = self.script_return_stack.pop().flatten();
        self.restore_function_locals();
        self.script_arguments = previous_arguments;
        match (result, return_status) {
            (Ok(mut result), Some(status)) => {
                result.status = status;
                Ok(result)
            }
            (result, _) => result,
        }
    }

    fn execute_script_lines<H: ShellHost>(
        &mut self,
        lines: &[&str],
        path: &Path,
        line_offset: usize,
        host: &mut H,
        control_depth: usize,
    ) -> Result<CommandResult, ShellError> {
        const MAX_CONTROL_DEPTH: usize = 64;
        if control_depth > MAX_CONTROL_DEPTH {
            return Err(ShellError::Script(format!(
                "{}: maximale Verschachtelung von Skriptblöcken überschritten.",
                path.display()
            )));
        }

        let mut last_result = CommandResult::default();
        let mut conditionals: Vec<ScriptConditional> = Vec::new();
        let mut index = 0;
        while index < lines.len() {
            let source_line = line_offset + index + 1;
            let command = lines[index].trim();
            if command.is_empty() || command.starts_with('#') {
                index += 1;
                continue;
            }

            let function_name = script_function_header(command).map_err(|error| {
                ShellError::Script(format!("{}:{source_line}: {error}", path.display()))
            })?;
            if let Some(name) = function_name {
                let end = find_script_function_end(lines, index).ok_or_else(|| {
                    ShellError::Script(format!(
                        "{}:{source_line}: Funktionsblock endet ohne schließende Klammer `}}`.",
                        path.display()
                    ))
                })?;
                if script_block_is_active(&conditionals) {
                    let body = lines[index + 1..end]
                        .iter()
                        .map(|line| (*line).to_owned())
                        .collect();
                    self.functions.insert(
                        name,
                        ScriptFunction {
                            body,
                            path: path.to_path_buf(),
                            line_offset: line_offset + index + 1,
                        },
                    );
                    last_result = CommandResult::default();
                    self.last_status = 0;
                }
                index = end + 1;
                continue;
            }

            if command == "}" {
                return Err(ShellError::Script(format!(
                    "{}:{source_line}: schließende Funktionsklammer ohne passenden Funktionskopf.",
                    path.display()
                )));
            }

            if starts_script_keyword(command, "case") {
                let value = parse_script_case_header(
                    command,
                    &self.variables,
                    self.previous_dir.as_deref(),
                    &self.script_arguments,
                    self.last_status,
                    host,
                )
                .map_err(|error| {
                    ShellError::Script(format!("{}:{source_line}: {error}", path.display()))
                })?;
                let end = find_script_case_end(lines, index).ok_or_else(|| {
                    ShellError::Script(format!(
                        "{}:{source_line}: case-Block endet ohne esac.",
                        path.display()
                    ))
                })?;
                let branches = parse_script_case_branches(
                    lines,
                    index,
                    end,
                    &self.variables,
                    self.previous_dir.as_deref(),
                    &self.script_arguments,
                    self.last_status,
                    host,
                )
                .map_err(|error| {
                    ShellError::Script(format!("{}:{source_line}: {error}", path.display()))
                })?;

                if script_block_is_active(&conditionals) {
                    if let Some(branch) = branches.iter().find(|branch| {
                        branch
                            .patterns
                            .iter()
                            .any(|pattern| case_pattern_matches(pattern, &value))
                    }) {
                        last_result = self.execute_script_lines(
                            &lines[branch.body_start..branch.body_end],
                            path,
                            line_offset + branch.body_start,
                            host,
                            control_depth + 1,
                        )?;
                        self.last_status = last_result.status;
                        if last_result.should_exit
                            || self.script_return_requested()
                            || self.pending_loop_control.is_some()
                        {
                            return Ok(last_result);
                        }
                    } else {
                        last_result = CommandResult::default();
                        self.last_status = 0;
                    }
                }
                index = end + 1;
                continue;
            }

            if command == "esac" || command == ";;" {
                return Err(ShellError::Script(format!(
                    "{}:{source_line}: {command} ohne passenden case-Block.",
                    path.display()
                )));
            }

            if starts_script_keyword(command, "while") {
                let condition = script_while_condition(command).ok_or_else(|| {
                    ShellError::Script(format!(
                        "{}:{source_line}: Syntax: while BEFEHL; do",
                        path.display()
                    ))
                })?;
                let end = find_script_loop_end(lines, index).ok_or_else(|| {
                    ShellError::Script(format!(
                        "{}:{source_line}: while-Block endet ohne done.",
                        path.display()
                    ))
                })?;

                if script_block_is_active(&conditionals) {
                    self.last_status = 0;
                    self.loop_depth += 1;
                    let loop_result: Result<CommandResult, ShellError> = (|| {
                        let mut body_result = CommandResult::default();
                        loop {
                            let condition_result = self
                                .execute_line(condition, host)
                                .map_err(|error| {
                                    ShellError::Script(format!(
                                        "{}:{source_line}: {error}",
                                        path.display()
                                    ))
                                })?;
                            if condition_result.should_exit {
                                return Ok(condition_result);
                            }
                            if self.script_return_requested() {
                                return Ok(condition_result);
                            }
                            match self.pending_loop_control.take() {
                                Some(LoopControl::Break) => {
                                    body_result = condition_result;
                                    break;
                                }
                                Some(LoopControl::Continue) => continue,
                                None => {}
                            }
                            if condition_result.status != 0 {
                                break;
                            }

                            body_result = self.execute_script_lines(
                                &lines[index + 1..end],
                                path,
                                line_offset + index + 1,
                                host,
                                control_depth + 1,
                            )?;
                            if body_result.should_exit {
                                return Ok(body_result);
                            }
                            if self.script_return_requested() {
                                return Ok(body_result);
                            }
                            match self.pending_loop_control.take() {
                                Some(LoopControl::Break) => break,
                                Some(LoopControl::Continue) => continue,
                                None => {}
                            }
                        }
                        Ok(body_result)
                    })();
                    self.loop_depth -= 1;
                    last_result = loop_result?;
                    self.last_status = last_result.status;
                    if last_result.should_exit {
                        return Ok(last_result);
                    }
                    if self.script_return_requested() {
                        return Ok(last_result);
                    }
                }
                index = end + 1;
                continue;
            }

            if starts_script_keyword(command, "for") {
                let (variable, values) = parse_script_for_header(
                    command,
                    &self.variables,
                    self.previous_dir.as_deref(),
                    &self.script_arguments,
                    self.last_status,
                    host,
                )
                .map_err(|error| {
                    ShellError::Script(format!("{}:{source_line}: {error}", path.display()))
                })?;
                let end = find_script_loop_end(lines, index).ok_or_else(|| {
                    ShellError::Script(format!(
                        "{}:{source_line}: for-Block endet ohne done.",
                        path.display()
                    ))
                })?;

                if script_block_is_active(&conditionals) {
                    last_result = CommandResult::default();
                    self.last_status = 0;
                    for value in values {
                        self.variables.insert(variable.clone(), value);
                        self.last_status = 0;
                        self.loop_depth += 1;
                        let body_result = self.execute_script_lines(
                            &lines[index + 1..end],
                            path,
                            line_offset + index + 1,
                            host,
                            control_depth + 1,
                        );
                        self.loop_depth -= 1;
                        let body_result = body_result?;
                        if body_result.should_exit {
                            return Ok(body_result);
                        }
                        if self.script_return_requested() {
                            return Ok(body_result);
                        }
                        last_result = body_result;
                        match self.pending_loop_control.take() {
                            Some(LoopControl::Break) => break,
                            Some(LoopControl::Continue) => continue,
                            None => {}
                        }
                    }
                }
                index = end + 1;
                continue;
            }

            if command == "done" {
                return Err(ShellError::Script(format!(
                    "{}:{source_line}: done ohne passendes for.",
                    path.display()
                )));
            }

            if starts_script_keyword(command, "if") {
                let condition = script_condition(command, "if").ok_or_else(|| {
                    ShellError::Script(format!(
                        "{}:{source_line}: Syntax: if BEFEHL; then",
                        path.display()
                    ))
                })?;
                let parent_active = script_block_is_active(&conditionals);
                let branch_taken = if parent_active {
                    let command_result = self.execute_line(condition, host).map_err(|error| {
                        ShellError::Script(format!("{}:{source_line}: {error}", path.display()))
                    })?;
                    if command_result.should_exit {
                        return Ok(command_result);
                    }
                    if self.script_return_requested() {
                        return Ok(command_result);
                    }
                    if self.pending_loop_control.is_some() {
                        return Ok(command_result);
                    }
                    last_result = CommandResult::default();
                    self.last_status = 0;
                    command_result.status == 0
                } else {
                    false
                };
                conditionals.push(ScriptConditional {
                    parent_active,
                    branch_taken,
                    in_else_branch: false,
                    line_number: source_line,
                });
                index += 1;
                continue;
            }

            if starts_script_keyword(command, "elif") {
                let condition = script_condition(command, "elif").ok_or_else(|| {
                    ShellError::Script(format!(
                        "{}:{source_line}: Syntax: elif BEFEHL; then",
                        path.display()
                    ))
                })?;
                let Some(conditional) = conditionals.last() else {
                    return Err(ShellError::Script(format!(
                        "{}:{source_line}: elif ohne passendes if.",
                        path.display()
                    )));
                };
                if conditional.in_else_branch {
                    return Err(ShellError::Script(format!(
                        "{}:{source_line}: elif darf nicht nach else kommen.",
                        path.display()
                    )));
                }
                let should_evaluate = conditional.parent_active && !conditional.branch_taken;
                if should_evaluate {
                    let command_result = self.execute_line(condition, host).map_err(|error| {
                        ShellError::Script(format!("{}:{source_line}: {error}", path.display()))
                    })?;
                    if command_result.should_exit {
                        return Ok(command_result);
                    }
                    if self.script_return_requested() {
                        return Ok(command_result);
                    }
                    if self.pending_loop_control.is_some() {
                        return Ok(command_result);
                    }
                    if let Some(conditional) = conditionals.last_mut() {
                        conditional.branch_taken = command_result.status == 0;
                    }
                    last_result = CommandResult::default();
                    self.last_status = 0;
                }
                index += 1;
                continue;
            }

            if command == "else" {
                let Some(conditional) = conditionals.last_mut() else {
                    return Err(ShellError::Script(format!(
                        "{}:{source_line}: else ohne passendes if.",
                        path.display()
                    )));
                };
                if conditional.in_else_branch {
                    return Err(ShellError::Script(format!(
                        "{}:{source_line}: else darf pro if nur einmal vorkommen.",
                        path.display()
                    )));
                }
                conditional.in_else_branch = true;
                index += 1;
                continue;
            }

            if command == "fi" {
                if conditionals.pop().is_none() {
                    return Err(ShellError::Script(format!(
                        "{}:{source_line}: fi ohne passendes if.",
                        path.display()
                    )));
                }
                index += 1;
                continue;
            }

            if !script_block_is_active(&conditionals) {
                index += 1;
                continue;
            }

            match self.execute_line(command, host) {
                Ok(command_result) => {
                    last_result = command_result;
                    if last_result.should_exit {
                        return Ok(last_result);
                    }
                    if self.script_return_requested() {
                        return Ok(last_result);
                    }
                    if self.pending_loop_control.is_some() {
                        return Ok(last_result);
                    }
                }
                Err(error) => {
                    return Err(ShellError::Script(format!(
                        "{}:{source_line}: {error}",
                        path.display()
                    )));
                }
            }
            index += 1;
        }

        if let Some(conditional) = conditionals.last() {
            return Err(ShellError::Script(format!(
                "{}:{}: if-Block endet ohne fi.",
                path.display(),
                conditional.line_number
            )));
        }
        Ok(last_result)
    }

    fn script_return_requested(&self) -> bool {
        self.script_return_stack
            .last()
            .is_some_and(|status| status.is_some())
    }

    fn set_local_variables(&mut self, args: &[String]) -> Result<(), ShellError> {
        if args.is_empty() {
            return Err(ShellError::Parse(
                "Verwendung: local NAME[=WERT] [NAME[=WERT] ...]".to_owned(),
            ));
        }
        if self.function_local_stack.is_empty() {
            return Err(ShellError::Parse(
                "local darf nur innerhalb einer Shell-Funktion verwendet werden.".to_owned(),
            ));
        }

        let mut declarations = Vec::with_capacity(args.len());
        for declaration in args {
            let (name, value) = match declaration.split_once('=') {
                Some((name, value)) => (name, value.to_owned()),
                None => (declaration.as_str(), String::new()),
            };
            if !valid_variable_name(name) {
                return Err(ShellError::Parse(format!(
                    "Ungültiger lokaler Variablenname: {name}"
                )));
            }
            declarations.push((name.to_owned(), value));
        }

        for (name, value) in declarations {
            let previous_value = self.variables.get(&name).cloned();
            if let Some(scope) = self.function_local_stack.last_mut() {
                scope.entry(name.clone()).or_insert(previous_value);
            }
            self.variables.insert(name, value);
        }
        Ok(())
    }

    fn read_variables<H: ShellHost>(
        &mut self,
        args: &[String],
        stdin_bytes: Option<&[u8]>,
        host: &mut H,
    ) -> Result<CommandResult, ShellError> {
        let names = if args.is_empty() {
            vec!["REPLY".to_owned()]
        } else {
            args.to_vec()
        };
        if names.iter().any(|name| !valid_variable_name(name)) {
            return Err(ShellError::Parse(
                "Verwendung: read [NAME ...]".to_owned(),
            ));
        }

        let input = match stdin_bytes {
            Some(bytes) => {
                let line_bytes = match bytes.iter().position(|byte| *byte == b'\n') {
                    Some(end) => &bytes[..end],
                    None if bytes.is_empty() => {
                        return Ok(CommandResult {
                            status: 1,
                            should_exit: false,
                        });
                    }
                    None => bytes,
                };
                let line = String::from_utf8(line_bytes.to_vec()).map_err(|_| {
                    ShellError::Parse("read: Eingabe ist keine UTF-8-Zeile.".to_owned())
                })?;
                Some(line)
            }
            None => host.read_input_line()?,
        };
        let Some(mut line) = input else {
            return Ok(CommandResult {
                status: 1,
                should_exit: false,
            });
        };
        if line.ends_with('\r') {
            line.pop();
        }
        if names.len() == 1 {
            self.variables
                .insert(names[0].clone(), line.trim().to_owned());
        } else {
            let fields: Vec<&str> = line.split_whitespace().collect();
            for (index, name) in names.iter().take(names.len() - 1).enumerate() {
                self.variables.insert(
                    name.clone(),
                    fields.get(index).copied().unwrap_or_default().to_owned(),
                );
            }
            let last_value = fields
                .iter()
                .skip(names.len() - 1)
                .copied()
                .collect::<Vec<_>>()
                .join(" ");
            self.variables
                .insert(names[names.len() - 1].clone(), last_value);
        }
        Ok(CommandResult::default())
    }

    fn restore_function_locals(&mut self) {
        let Some(scope) = self.function_local_stack.pop() else {
            return;
        };
        for (name, previous_value) in scope {
            match previous_value {
                Some(value) => {
                    self.variables.insert(name, value);
                }
                None => {
                    self.variables.remove(&name);
                }
            }
        }
    }

    fn set_variable(
        &mut self,
        args: &[String],
        output: &mut Vec<u8>,
    ) -> Result<(), ShellError> {
        if args.is_empty() {
            for (name, value) in &self.variables {
                output.extend_from_slice(format!("{name}={value}\n").as_bytes());
            }
            return Ok(());
        }
        if args.len() != 1 {
            return Err(ShellError::Parse("Verwendung: set NAME=WERT".to_owned()));
        }
        let Some((name, value)) = args[0].split_once('=') else {
            return Err(ShellError::Parse("Verwendung: set NAME=WERT".to_owned()));
        };
        if !valid_variable_name(name) {
            return Err(ShellError::Parse("Ungültiger Variablenname.".to_owned()));
        }
        self.variables.insert(name.to_owned(), value.to_owned());
        Ok(())
    }

    fn assign_arithmetic_variables<H: ShellHost>(
        &mut self,
        args: &[String],
        host: &H,
    ) -> Result<CommandResult, ShellError> {
        if args.is_empty() {
            return Err(ShellError::Parse(
                "Verwendung: let NAME=AUSDRUCK [NAME=AUSDRUCK ...]".to_owned(),
            ));
        }
        let mut last_value = 0;
        for assignment in args {
            let Some((name, expression)) = assignment.split_once('=') else {
                return Err(ShellError::Parse(
                    "Verwendung: let NAME=AUSDRUCK [NAME=AUSDRUCK ...]".to_owned(),
                ));
            };
            if !valid_variable_name(name) {
                return Err(ShellError::Parse(format!(
                    "Ungültiger Variablenname in let-Zuweisung: {name}"
                )));
            }
            let value = evaluate_arithmetic_expression(expression, &self.variables, host)
                .map_err(ShellError::Parse)?;
            self.variables.insert(name.to_owned(), value.to_string());
            last_value = value;
        }
        Ok(CommandResult {
            status: if last_value == 0 { 1 } else { 0 },
            should_exit: false,
        })
    }

    fn unset_variables(&mut self, args: &[String]) -> Result<(), ShellError> {
        if args.is_empty() || args.iter().any(|name| !valid_variable_name(name)) {
            return Err(ShellError::Parse("Verwendung: unset NAME [NAME ...]".to_owned()));
        }
        for name in args {
            self.variables.remove(name);
        }
        Ok(())
    }

    fn list_directory<H: ShellHost>(
        &mut self,
        args: &[String],
        host: &mut H,
        output: &mut Vec<u8>,
    ) -> Result<(), ShellError> {
        let mut show_hidden = false;
        let mut path_arg: Option<&str> = None;
        for arg in args {
            if arg == "-a" || arg == "--all" {
                show_hidden = true;
            } else if path_arg.replace(arg).is_some() {
                return Err(ShellError::Parse("Verwendung: ls [-a] [PFAD]".to_owned()));
            }
        }
        let path = resolve_path(path_arg.unwrap_or("."), host)?;
        let mut entries = host.read_dir(&path)?;
        entries.sort_by(|left, right| left.name.cmp(&right.name));
        for entry in entries {
            if entry.is_hidden && !show_hidden {
                continue;
            }
            output.extend_from_slice(entry.name.as_bytes());
            if entry.is_directory {
                output.push(b'/');
            }
            output.push(b'\n');
        }
        Ok(())
    }

    fn print_files<H: ShellHost>(
        &mut self,
        args: &[String],
        stdin_bytes: Option<&[u8]>,
        host: &mut H,
        output: &mut Vec<u8>,
    ) -> Result<(), ShellError> {
        if args.is_empty() {
            return match stdin_bytes {
                Some(bytes) => {
                    output.extend_from_slice(bytes);
                    Ok(())
                }
                None => Err(ShellError::Parse("Verwendung: cat DATEI... (oder aus einer Pipe)".to_owned())),
            };
        }
        for path in args {
            let resolved = resolve_path(path, host)?;
            output.extend_from_slice(&host.read_file_bytes(&resolved)?);
        }
        Ok(())
    }

    fn make_directories<H: ShellHost>(
        &mut self,
        args: &[String],
        host: &mut H,
    ) -> Result<(), ShellError> {
        let (recursive, paths) = if args.first().is_some_and(|arg| arg == "-p") {
            (true, &args[1..])
        } else {
            (false, args)
        };
        if paths.is_empty() {
            return Err(ShellError::Parse("Verwendung: mkdir [-p] PFAD [PFAD ...]".to_owned()));
        }
        for path in paths {
            let resolved = resolve_path(path, host)?;
            host.create_dir(&resolved, recursive)?;
        }
        Ok(())
    }
}

fn write_final_output<H: ShellHost>(
    stage: &ParsedStage,
    output: Vec<u8>,
    host: &mut H,
) -> Result<(), ShellError> {
    if let Some(redirection) = &stage.stdout {
        let path = resolve_path(&redirection.path, host)?;
        host.write_file_bytes(&path, &output, redirection.append)?;
    } else {
        host.write_stdout_bytes(&output)?;
    }
    Ok(())
}

fn format_command_label(stages: &[ParsedStage], background: bool) -> String {
    let mut label = String::new();
    for (index, stage) in stages.iter().enumerate() {
        if index > 0 {
            label.push_str(" | ");
        }
        label.push_str(
            &stage
                .words
                .iter()
                .map(|word| {
                    if word.chars().any(char::is_whitespace)
                        || word.chars().any(|ch| matches!(ch, '|' | '<' | '>' | ';' | '&' | '"' | '\''))
                    {
                        format!("{word:?}")
                    } else {
                        word.clone()
                    }
                })
                .collect::<Vec<_>>()
                .join(" "),
        );
        if let Some(path) = &stage.stdin {
            label.push_str(&format!(" < {path}"));
        }
        if let Some(redirection) = &stage.stdout {
            label.push_str(if redirection.append { " >> " } else { " > " });
            label.push_str(&redirection.path);
        }
        if let Some(redirection) = &stage.stderr {
            label.push_str(if redirection.append { " 2>> " } else { " 2> " });
            label.push_str(&redirection.path);
        }
    }
    if background {
        label.push_str(" &");
    }
    label
}

fn is_builtin(name: &str) -> bool {
    matches!(
        name,
        "help" | "pwd" | "dirs" | "cd" | "pushd" | "popd" | "source" | "." | "history" | "jobs" | "wait" | "clear" | "diagnose"
            | "shift"
            | "break" | "continue" | "return"
            | "true" | "false" | "test" | "[" | "deactivate" | "venv"
            | "echo" | "printf" | "read" | "set" | "local" | "let" | "unset" | "ls" | "dir" | "cat" | "mkdir" | "exit"
    )
}

fn pipeline_safe_builtin(words: &[String]) -> bool {
    match words[0].as_str() {
        "help" | "pwd" | "echo" | "printf" | "true" | "false" | "test" | "[" | "ls" | "diagnose"
        | "dir" | "cat" => true,
        "dirs" => {
            words.len() == 1
                || words
                    .get(1)
                    .is_some_and(|option| matches!(option.as_str(), "-p" | "-v"))
        }
        "history" | "set" | "jobs" => words.len() == 1,
        "venv" => {
            words.len() == 1
                || (words.len() == 2
                    && matches!(words[1].as_str(), "info" | "status" | "--help" | "-h"))
        }
        _ => false,
    }
}

fn format_printf(args: &[String]) -> Result<Vec<u8>, String> {
    let format = args
        .first()
        .ok_or_else(|| "Verwendung: printf FORMAT [WERT ...]".to_owned())?;
    let values = &args[1..];
    let mut output = String::new();
    let mut value_index = 0;

    loop {
        let pass_start = value_index;
        let mut chars = format.chars();
        while let Some(character) = chars.next() {
            match character {
                '\\' => match chars.next() {
                    Some('n') => output.push('\n'),
                    Some('r') => output.push('\r'),
                    Some('t') => output.push('\t'),
                    Some('\\') => output.push('\\'),
                    Some(other) => {
                        return Err(format!("printf: unbekannte Escape-Sequenz \\{other}."));
                    }
                    None => return Err("printf: FORMAT endet mit einem Backslash.".to_owned()),
                },
                '%' => {
                    let conversion = chars
                        .next()
                        .ok_or_else(|| "printf: FORMAT endet mit %%.".to_owned())?;
                    if conversion == '%' {
                        output.push('%');
                        continue;
                    }
                    let value = values.get(value_index).map(String::as_str);
                    if value.is_some() {
                        value_index += 1;
                    }
                    match conversion {
                        's' => {
                            if let Some(value) = value {
                                output.push_str(value);
                            }
                        }
                        'd' | 'i' => {
                            let number = match value {
                                Some(value) => value.parse::<i64>().map_err(|_| {
                                    format!("printf: '{value}' ist keine Ganzzahl.")
                                })?,
                                None => 0,
                            };
                            output.push_str(&number.to_string());
                        }
                        'u' | 'x' | 'X' | 'o' => {
                            let number = match value {
                                Some(value) => value.parse::<u64>().map_err(|_| {
                                    format!("printf: '{value}' ist keine nichtnegative Ganzzahl.")
                                })?,
                                None => 0,
                            };
                            let rendered = match conversion {
                                'u' => number.to_string(),
                                'x' => format!("{number:x}"),
                                'X' => format!("{number:X}"),
                                'o' => format!("{number:o}"),
                                _ => unreachable!(),
                            };
                            output.push_str(&rendered);
                        }
                        'c' => output.push(value.and_then(|value| value.chars().next()).unwrap_or('\0')),
                        _ => {
                            return Err(format!("printf: unbekanntes Format %{}.", conversion));
                        }
                    }
                }
                other => output.push(other),
            }
        }
        if value_index == pass_start || value_index >= values.len() {
            break;
        }
    }

    Ok(output.into_bytes())
}

fn evaluate_test_expression<H: ShellHost>(args: &[String], host: &H) -> Result<bool, String> {
    TestExpressionParser {
        args,
        index: 0,
        host,
    }
    .parse()
}

struct TestExpressionParser<'args, 'host, H: ShellHost> {
    args: &'args [String],
    index: usize,
    host: &'host H,
}

impl<H: ShellHost> TestExpressionParser<'_, '_, H> {
    fn parse(&mut self) -> Result<bool, String> {
        if self.args.is_empty() {
            return Ok(false);
        }
        let value = self.parse_or()?;
        if self.index != self.args.len() {
            return Err("test: ungültiger Ausdruck.".to_owned());
        }
        Ok(value)
    }

    fn parse_or(&mut self) -> Result<bool, String> {
        let mut value = self.parse_and()?;
        while self.consume("-o") {
            let right = self.parse_and()?;
            value = value || right;
        }
        Ok(value)
    }

    fn parse_and(&mut self) -> Result<bool, String> {
        let mut value = self.parse_unary()?;
        while self.consume("-a") {
            let right = self.parse_unary()?;
            value = value && right;
        }
        Ok(value)
    }

    fn parse_unary(&mut self) -> Result<bool, String> {
        if self.peek() == Some("!") && self.index + 1 < self.args.len() {
            self.index += 1;
            return Ok(!self.parse_unary()?);
        }
        self.parse_primary()
    }

    fn parse_primary(&mut self) -> Result<bool, String> {
        let left = self
            .args
            .get(self.index)
            .ok_or_else(|| "test: ungültiger Ausdruck.".to_owned())?;

        if matches!(left.as_str(), "-a" | "-o") {
            return Err("test: ungültiger Ausdruck.".to_owned());
        }
        if matches!(left.as_str(), "-e" | "-f" | "-d") && self.index + 1 < self.args.len() {
            let operand = &self.args[self.index + 1];
            let kind = if operand.is_empty() {
                None
            } else {
                let path = resolve_path(operand, self.host)
                    .map_err(|error| format!("test: {error}"))?;
                self.host.path_kind(&path).map_err(|error| {
                    if error.kind() == io::ErrorKind::Unsupported {
                        "test: Dateiprüfungen werden von diesem ShellHost nicht unterstützt."
                            .to_owned()
                    } else {
                        format!("test: Pfadprüfung fehlgeschlagen: {error}")
                    }
                })?
            };
            let result = match left.as_str() {
                "-e" => kind.is_some(),
                "-f" => kind == Some(ShellPathKind::File),
                "-d" => kind == Some(ShellPathKind::Directory),
                _ => unreachable!(),
            };
            self.index += 2;
            return Ok(result);
        }
        if matches!(left.as_str(), "-n" | "-z") && self.index + 1 < self.args.len() {
            let value = !self.args[self.index + 1].is_empty();
            self.index += 2;
            return Ok(if left == "-n" { value } else { !value });
        }

        if let Some(operator) = self.args.get(self.index + 1) {
            if matches!(operator.as_str(), "=" | "==" | "!=" | "-eq" | "-ne" | "-lt" | "-le" | "-gt" | "-ge") {
                let right = self
                    .args
                    .get(self.index + 2)
                    .ok_or_else(|| "test: ungültiger Ausdruck.".to_owned())?;
                let result = match operator.as_str() {
                    "=" | "==" => left == right,
                    "!=" => left != right,
                    numeric_operator => {
                        let left_number = left.parse::<i64>().map_err(|_| {
                            format!("test: '{}' ist keine Ganzzahl.", left)
                        })?;
                        let right_number = right.parse::<i64>().map_err(|_| {
                            format!("test: '{}' ist keine Ganzzahl.", right)
                        })?;
                        match numeric_operator {
                            "-eq" => left_number == right_number,
                            "-ne" => left_number != right_number,
                            "-lt" => left_number < right_number,
                            "-le" => left_number <= right_number,
                            "-gt" => left_number > right_number,
                            "-ge" => left_number >= right_number,
                            _ => unreachable!(),
                        }
                    }
                };
                self.index += 3;
                return Ok(result);
            }
        }

        self.index += 1;
        Ok(!left.is_empty())
    }

    fn peek(&self) -> Option<&str> {
        self.args.get(self.index).map(String::as_str)
    }

    fn consume(&mut self, token: &str) -> bool {
        if self.peek() == Some(token) {
            self.index += 1;
            true
        } else {
            false
        }
    }
}

const HELP_TEXT: &str = "ShellDeck Shell — aktuelle Ausbaustufe\n\
Eigene Befehle: cd [--] [PFAD|-] (cd - gibt den Zielpfad aus), pushd [--] [PFAD|+N], popd [+N], source DATEI [ARGUMENT ...], deactivate, venv [info|status], diagnose [venv|python|path|shell], shift [ANZAHL], break, continue, test AUSDRUCK, [ AUSDRUCK ], printf FORMAT [WERT ...], let NAME=AUSDRUCK, pwd, dirs [-p|-v|-c], help [BEFEHL], history [-c], jobs, wait [JOB_ID], true, false, clear, exit [STATUS]\n\
Detailhilfe: help venv, help diagnose und help wait; alternativ venv --help, diagnose --help und wait --help.\n\
Python-venv: source PFAD/bin/activate (Linux/macOS) oder source PFAD/Scripts/activate[.bat|.ps1] (Windows); deactivate beendet die venv dieses Tabs, auch wenn sie von ShellDeck geerbt wurde.\n\
Diagnose: venv info zeigt Status, Umgebungspfad, Interpreter und Version; diagnose fasst Shell und Python-Auflösung zusammen. diagnose path listet PATH-Verzeichnisse samt Existenzstatus.\n\
Python-Prüfung: python3 -c 'import sys; print(sys.executable); print(sys.prefix); print(sys.base_prefix)' (unter Windows ggf. python verwenden).\n\
Netzwerk: ping localhost ist ein externes Systemprogramm und kann mit Ctrl+C beendet werden. ifconfig ist nicht überall installiert; ShellDeck liefert es nicht mit.\n\
Hintergrundjobs: jobs zeigt die IDs; wait wartet auf alle, wait JOB_ID auf einen einzelnen Job. wait --help zeigt Details.\n\
ShellDeck-eigene Befehle werden kleingeschrieben verwendet (zum Beispiel dir, venv info, diagnose); andere Namen werden als externe Programme gestartet.\n\
test unterstützt -e, -f und -d für plattformabhängig bereitgestellte Pfadtypen.\n\
Dateien: ls [-a] [PFAD], dir [PFAD], cat DATEI..., mkdir [-p] PFAD...\n\
Text und Variablen: echo [-n] TEXT..., read [NAME ...], set NAME=WERT, local NAME[=WERT], unset NAME...\n\
Operatoren: |, ;, &&, ||, <, >, >>, 1>, 1>>, 2>, 2>>, & (externe Programme)\n\
Andere Namen starten ein installiertes Programm direkt.\n\
Tilde: ~, ~/PFAD, ~+, ~+/PFAD, ~- und ~-/PFAD expandieren unquotiert am Wortanfang.\n\
cd, pushd und popd aktualisieren bei Verzeichniswechseln PWD und OLDPWD.\n\
Variablen: $NAME, ${#NAME}, ${NAME#MUSTER}, ${NAME##MUSTER}, ${NAME%MUSTER}, ${NAME%%MUSTER}.\n\
Standardwerte: ${NAME-WERT}, ${NAME:-WERT}, ${NAME+WERT}, ${NAME:+WERT}.\n\
Pflichtwerte: ${NAME?MELDUNG}, ${NAME:?MELDUNG}, $?; einfache Anführungszeichen unterdrücken Expansion.\n\
Arithmetik: $((AUSDRUCK)) mit Ganzzahlen, Variablen, Klammern, +, -, *, / und %.\n\
Skriptargumente: $1 bis $9, ${10} und $#; keine Wortaufteilung.\n\
Skriptsteuerung: if / elif BEFEHL; then / else / fi; for NAME in WERTE; do / done; while BEFEHL; do / done; case WERT in MUSTER) ... ;; esac.\n\
Funktionen: mehrzeilige FUNKTION() { ... }-Blöcke; return [STATUS]; $? zeigt den vorherigen Befehlsstatus.\n\
Funktionen: mehrzeilige FUNKTION() { ... }-Blöcke in source-Skripten definieren und per Namen aufrufen.\n\
test unterstützt -a (UND) und -o (ODER), -a bindet stärker.\n\
Schleifen sind nur in source-Skripten verfügbar; break / continue steuern ohne Argument die innerste aktive Schleife.\n";

const VENV_HELP_TEXT: &str = "ShellDeck Shell — Python-Umgebungen\n\
venv info | venv status  Zeigt, ob eine Python-venv aktiv ist, sowie Pfad und Interpreter.\n\
source PFAD/bin/activate  Aktiviert eine venv unter Linux/macOS.\n\
source PFAD/Scripts/activate  Aktiviert eine venv unter Windows.\n\
deactivate  Beendet die aktive venv dieses Tabs; geerbte Umgebungen werden im Shell-Prozess ausgeblendet.\n\
Nach der Aktivierung sollte der Prompt (NAME) enthalten, zum Beispiel (.venv).\n\
Beispiel im Projektordner: source .venv/bin/activate\n\
Liegt die venv in einem anderen Ordner, verwende den passenden relativen oder absoluten Pfad.\n\
Für zusätzliche Diagnose: diagnose venv oder diagnose python.\n";

const DIAGNOSE_HELP_TEXT: &str = "ShellDeck Shell — Diagnose\n\
diagnose          Shell- und Python-Auflösung zusammenfassen.\n\
diagnose venv     Aktive Python-venv, Pfad und Interpreter anzeigen.\n\
diagnose python   Python-Befehle und aufgelöste Interpreter anzeigen.\n\
diagnose path     PATH-Verzeichnisse samt Existenzstatus auflisten.\n\
diagnose shell    Shell-, Betriebssystem- und Arbeitsordnerdaten anzeigen.\n\
venv info         Kompakte Statusanzeige für die virtuelle Umgebung.\n\
Tipp: python3 -c 'import sys; print(sys.executable); print(sys.prefix); print(sys.base_prefix)'\n\
Bei Windows kann python statt python3 der verfügbare Befehlsname sein.\n";

const WAIT_HELP_TEXT: &str = "ShellDeck Shell — Hintergrundjobs\n\
jobs         Zeigt von ShellDeck gestartete Hintergrundjobs und ihre IDs.\n\
wait         Wartet, bis alle noch geführten Hintergrundjobs beendet sind.\n\
wait JOB_ID  Wartet auf einen einzelnen Job; die ID steht in der jobs-Ausgabe.\n\
wait --help  Zeigt diese Hilfe.\n\
wait ist ein ShellDeck-Shell-Befehl. Er wartet nicht auf externe Jobs anderer Tabs oder Shells.\n";

#[derive(Debug)]
struct ParsedCommand {
    stages: Vec<ParsedStage>,
    background: bool,
    condition: CommandCondition,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CommandCondition {
    Always,
    OnSuccess,
    OnFailure,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LoopControl {
    Break,
    Continue,
}

#[derive(Debug, Clone)]
struct Redirection {
    path: String,
    append: bool,
}

#[derive(Debug, Default)]
struct ParsedStage {
    words: Vec<String>,
    stdin: Option<String>,
    stdout: Option<Redirection>,
    stderr: Option<Redirection>,
}

#[derive(Debug)]
enum Token {
    Word(String),
    Pipe,
    Background,
    CommandSeparator,
    AndIf,
    OrIf,
    RedirectInput,
    RedirectOutput { append: bool },
    RedirectError { append: bool },
}

fn parse_tokens(tokens: Vec<Token>) -> Result<Vec<ParsedCommand>, String> {
    if tokens.is_empty() {
        return Ok(Vec::new());
    }
    let mut commands = Vec::new();
    let mut pipeline_tokens = Vec::new();
    let mut next_condition = CommandCondition::Always;
    let mut trailing_semicolon = false;
    for token in tokens {
        let connector = match token {
            Token::CommandSeparator => Some((CommandCondition::Always, true)),
            Token::AndIf => Some((CommandCondition::OnSuccess, false)),
            Token::OrIf => Some((CommandCondition::OnFailure, false)),
            other => {
                pipeline_tokens.push(other);
                trailing_semicolon = false;
                None
            }
        };
        if let Some((condition, is_semicolon)) = connector {
            if pipeline_tokens.is_empty() {
                return Err("Vor einem Verknüpfungsoperator fehlt ein Befehl.".to_owned());
            }
            commands.push(parse_pipeline(
                std::mem::take(&mut pipeline_tokens),
                next_condition,
            )?);
            next_condition = condition;
            trailing_semicolon = is_semicolon;
        }
    }
    // A trailing semicolon is accepted; trailing conditional operators are not.
    if !pipeline_tokens.is_empty() {
        commands.push(parse_pipeline(pipeline_tokens, next_condition)?);
    } else if !commands.is_empty() && !trailing_semicolon {
        return Err("Nach && oder || fehlt ein Befehl.".to_owned());
    }
    Ok(commands)
}

fn parse_pipeline(
    tokens: Vec<Token>,
    condition: CommandCondition,
) -> Result<ParsedCommand, String> {
    if tokens.is_empty() {
        return Err("Leerer Befehl.".to_owned());
    }
    let mut stages = Vec::new();
    let mut stage = ParsedStage::default();
    let mut background = false;
    let mut tokens = tokens.into_iter().peekable();
    while let Some(token) = tokens.next() {
        match token {
            Token::Word(word) => stage.words.push(word),
            Token::Pipe => {
                if stage.words.is_empty() {
                    return Err("Pipe ohne vorherigen Befehl.".to_owned());
                }
                stages.push(std::mem::take(&mut stage));
            }
            Token::Background => {
                if stage.words.is_empty() {
                    return Err("Vor & fehlt ein Befehl.".to_owned());
                }
                if tokens.peek().is_some() {
                    return Err("& muss am Ende des Befehls stehen.".to_owned());
                }
                background = true;
            }
            Token::CommandSeparator | Token::AndIf | Token::OrIf => {
                return Err("Befehlsverkettung konnte nicht zerlegt werden.".to_owned());
            }
            Token::RedirectInput => {
                let path = take_redirection_path(&mut tokens)?;
                if stage.stdin.replace(path).is_some() {
                    return Err("Mehrere Eingabeumleitungen sind nicht unterstützt.".to_owned());
                }
            }
            Token::RedirectOutput { append } => {
                let path = take_redirection_path(&mut tokens)?;
                if stage.stdout.replace(Redirection { path, append }).is_some() {
                    return Err("Mehrere Ausgabeumleitungen sind nicht unterstützt.".to_owned());
                }
            }
            Token::RedirectError { append } => {
                let path = take_redirection_path(&mut tokens)?;
                if stage.stderr.replace(Redirection { path, append }).is_some() {
                    return Err("Mehrere Fehlerausgabeumleitungen sind nicht unterstützt.".to_owned());
                }
            }
        }
    }
    if stage.words.is_empty() {
        return Err(if stages.is_empty() {
            "Nach einer Umleitung fehlt ein Befehl.".to_owned()
        } else {
            "Am Ende der Pipe fehlt ein Befehl.".to_owned()
        });
    }
    stages.push(stage);

    for (index, stage) in stages.iter().enumerate() {
        if index > 0 && stage.stdin.is_some() {
            return Err("Eingabeumleitung ist nur am Anfang einer Pipe unterstützt.".to_owned());
        }
        if index + 1 < stages.len() && stage.stdout.is_some() {
            return Err("Ausgabeumleitung ist nur am Ende einer Pipe unterstützt.".to_owned());
        }
    }
    Ok(ParsedCommand {
        stages,
        background,
        condition,
    })
}

fn take_redirection_path(
    tokens: &mut std::iter::Peekable<std::vec::IntoIter<Token>>,
) -> Result<String, String> {
    match tokens.next() {
        Some(Token::Word(path)) => Ok(path),
        _ => Err("Nach einer Umleitung muss ein Dateipfad stehen.".to_owned()),
    }
}

fn expand_home(value: &str, home: &Path) -> PathBuf {
    if value == "~" {
        return home.to_path_buf();
    }
    if let Some(rest) = value.strip_prefix("~/").or_else(|| value.strip_prefix("~\\")) {
        return home.join(rest);
    }
    PathBuf::from(value)
}

fn parse_directory_stack_index(value: &str) -> Result<Option<usize>, String> {
    let Some(digits) = value.strip_prefix('+') else {
        return Ok(None);
    };
    if digits.is_empty() || !digits.bytes().all(|digit| digit.is_ascii_digit()) {
        return Ok(None);
    }
    digits
        .parse::<usize>()
        .map(Some)
        .map_err(|_| "Verzeichnisstack-Index ist zu groß.".to_owned())
}

fn resolve_path<H: ShellHost>(value: &str, host: &H) -> Result<PathBuf, ShellError> {
    let value = match host.home_dir() {
        Some(home) => expand_home(value, &home),
        None => PathBuf::from(value),
    };
    if value.is_absolute() {
        Ok(value)
    } else {
        Ok(host.current_dir()?.join(value))
    }
}

fn restore_shell_variable(
    variables: &mut BTreeMap<String, String>,
    name: &str,
    value: Option<String>,
) {
    if let Some(value) = value {
        variables.insert(name.to_owned(), value);
    } else {
        variables.remove(name);
    }
}

fn same_path_entry(left: &Path, right: &Path) -> bool {
    let left = left.as_os_str().to_string_lossy();
    let right = right.as_os_str().to_string_lossy();
    #[cfg(windows)]
    {
        left.trim_end_matches(|ch| ch == '/' || ch == '\\')
            .eq_ignore_ascii_case(right.trim_end_matches(|ch| ch == '/' || ch == '\\'))
    }
    #[cfg(not(windows))]
    {
        left == right
    }
}

fn valid_variable_start(ch: char) -> bool {
    ch == '_' || ch.is_ascii_alphabetic()
}

fn valid_variable_continue(ch: char) -> bool {
    valid_variable_start(ch) || ch.is_ascii_digit()
}

fn valid_variable_name(name: &str) -> bool {
    let mut chars = name.chars();
    matches!(chars.next(), Some(ch) if valid_variable_start(ch))
        && chars.all(valid_variable_continue)
}

fn valid_variable_reference(name: &str) -> bool {
    name == "#"
        || name == "?"
        || (!name.is_empty() && name.bytes().all(|byte| byte.is_ascii_digit()))
        || valid_variable_name(name)
}

fn take_parameter_expansion(
    chars: &mut std::iter::Peekable<std::str::Chars<'_>>,
) -> Result<Option<ParameterExpansion>, String> {
    if chars.peek() != Some(&'{') {
        return Ok(take_variable_name(chars)?.map(ParameterExpansion::Simple));
    }
    chars.next();
    let mut content = String::new();
    let mut closed = false;
    for character in chars.by_ref() {
        if character == '}' {
            closed = true;
            break;
        }
        content.push(character);
    }
    if !closed {
        return Err("Nicht geschlossene Variablenklammer ${...}.".to_owned());
    }
    if valid_variable_reference(&content) {
        return Ok(Some(ParameterExpansion::Simple(content)));
    }
    if let Some(name) = content.strip_prefix('#') {
        if valid_variable_reference(name) {
            return Ok(Some(ParameterExpansion::Length(name.to_owned())));
        }
    }
    if let Some((index, operator)) = content
        .char_indices()
        .find(|(_, character)| *character == '#' || *character == '%')
    {
        let doubled = content.as_bytes().get(index + 1).copied() == Some(operator as u8);
        let pattern_start = index + if doubled { 2 } else { 1 };
        let name = &content[..index];
        if valid_variable_reference(name) {
            return Ok(Some(ParameterExpansion::RemovePattern {
                name: name.to_owned(),
                pattern: content[pattern_start..].to_owned(),
                from_prefix: operator == '#',
                longest: doubled,
            }));
        }
    }

    let (name, word, when_empty) = if let Some((name, word)) = content.split_once(":-") {
        (name, word, true)
    } else if let Some((name, word)) = content.split_once('-') {
        (name, word, false)
    } else {
        let (name, word, when_nonempty) = if let Some((name, word)) = content.split_once(":+") {
            (name, word, true)
        } else if let Some((name, word)) = content.split_once('+') {
            (name, word, false)
        } else {
            let (name, message, when_empty) =
                if let Some((name, message)) = content.split_once(":?") {
                    (name, message, true)
                } else if let Some((name, message)) = content.split_once('?') {
                    (name, message, false)
                } else {
                    return Err("Ungültige Variablenexpansion in ${...}.".to_owned());
                };
            if !valid_variable_reference(name) {
                return Err("Ungültiger Variablenname in ${...}.".to_owned());
            }
            return Ok(Some(ParameterExpansion::Required {
                name: name.to_owned(),
                message: message.to_owned(),
                when_empty,
            }));
        };
        if !valid_variable_reference(name) {
            return Err("Ungültiger Variablenname in ${...}.".to_owned());
        }
        return Ok(Some(ParameterExpansion::Alternate {
            name: name.to_owned(),
            word: word.to_owned(),
            when_nonempty,
        }));
    };
    if !valid_variable_reference(name) {
        return Err("Ungültiger Variablenname in ${...}.".to_owned());
    }
    Ok(Some(ParameterExpansion::Default {
        name: name.to_owned(),
        word: word.to_owned(),
        when_empty,
    }))
}

fn lookup_variable_value<H: ShellHost>(
    name: &str,
    variables: &BTreeMap<String, String>,
    script_arguments: &[String],
    last_status: i32,
    host: &H,
) -> Option<String> {
    if name == "?" {
        Some(last_status.to_string())
    } else if name == "#" {
        Some(script_arguments.len().to_string())
    } else if name.bytes().all(|byte| byte.is_ascii_digit()) {
        name.parse::<usize>()
            .ok()
            .and_then(|index| index.checked_sub(1))
            .and_then(|index| script_arguments.get(index).cloned())
    } else {
        variables.get(name).cloned().or_else(|| host.env_var(name))
    }
}

fn resolve_parameter_expansion<H: ShellHost>(
    expansion: ParameterExpansion,
    variables: &BTreeMap<String, String>,
    script_arguments: &[String],
    last_status: i32,
    host: &H,
) -> Result<Option<String>, String> {
    match expansion {
        ParameterExpansion::Simple(name) => Ok(lookup_variable_value(
            &name,
            variables,
            script_arguments,
            last_status,
            host,
        )),
        ParameterExpansion::Length(name) => {
            let length = lookup_variable_value(
                &name,
                variables,
                script_arguments,
                last_status,
                host,
            )
            .map_or(0, |value| value.chars().count());
            Ok(Some(length.to_string()))
        }
        ParameterExpansion::RemovePattern {
            name,
            pattern,
            from_prefix,
            longest,
        } => {
            let value = lookup_variable_value(
                &name,
                variables,
                script_arguments,
                last_status,
                host,
            )
            .unwrap_or_default();
            Ok(Some(remove_parameter_pattern(
                &value,
                &pattern,
                from_prefix,
                longest,
            )))
        }
        ParameterExpansion::Default {
            name,
            word,
            when_empty,
        } => {
            let value = lookup_variable_value(&name, variables, script_arguments, last_status, host);
            if value.is_none() || (when_empty && value.as_deref() == Some("")) {
                Ok(Some(word))
            } else {
                Ok(value)
            }
        }
        ParameterExpansion::Alternate {
            name,
            word,
            when_nonempty,
        } => {
            let value = lookup_variable_value(&name, variables, script_arguments, last_status, host);
            let is_set = value.is_some();
            let has_value = value.as_deref().is_some_and(|value| !value.is_empty());
            if is_set && (!when_nonempty || has_value) {
                Ok(Some(word))
            } else {
                Ok(Some(String::new()))
            }
        }
        ParameterExpansion::Required {
            name,
            message,
            when_empty,
        } => {
            let value = lookup_variable_value(&name, variables, script_arguments, last_status, host);
            if value.is_none() || (when_empty && value.as_deref() == Some("")) {
                if message.is_empty() {
                    let state = if when_empty {
                        "nicht gesetzt oder leer"
                    } else {
                        "nicht gesetzt"
                    };
                    Err(format!("Variable {name} ist {state}."))
                } else {
                    Err(message)
                }
            } else {
                Ok(value)
            }
        }
    }
}

fn tokenize<H: ShellHost>(
    line: &str,
    variables: &BTreeMap<String, String>,
    previous_dir: Option<&Path>,
    script_arguments: &[String],
    last_status: i32,
    host: &H,
) -> Result<Vec<Token>, String> {
    let mut tokens = Vec::new();
    let mut word = String::new();
    let mut started = false;
    let mut quote: Option<char> = None;
    let mut chars = line.chars().peekable();

    while let Some(ch) = chars.next() {
        if quote == Some('\'') {
            if ch == '\'' {
                quote = None;
            } else {
                word.push(ch);
            }
            continue;
        }
        if ch == '\\' {
            match chars.peek().copied() {
                Some(next)
                    if matches!(next, '\\' | '"' | '\'' | '$' | '|' | '<' | '>' | ';' | '&' | ' ' | '\t') =>
                {
                    word.push(chars.next().expect("peeked character exists"));
                    started = true;
                }
                _ => {
                    word.push(ch);
                    started = true;
                }
            }
            continue;
        }
        if ch == '$' {
            if chars.peek() == Some(&'(') {
                chars.next();
                if chars.peek() == Some(&'(') {
                    chars.next();
                    let expression = take_arithmetic_expression(&mut chars)?;
                    let value = evaluate_arithmetic_expression(&expression, variables, host)?;
                    word.push_str(&value.to_string());
                    started = true;
                    continue;
                }
                word.push_str("$(");
                started = true;
                continue;
            }
            if let Some(expansion) = take_parameter_expansion(&mut chars)? {
                let value = resolve_parameter_expansion(
                    expansion,
                    variables,
                    script_arguments,
                    last_status,
                    host,
                )?;
                if let Some(value) = value {
                    word.push_str(&value);
                }
                started = true;
            } else {
                word.push('$');
                started = true;
            }
            continue;
        }
        if quote == Some('"') {
            if ch == '"' {
                quote = None;
            } else {
                word.push(ch);
            }
            continue;
        }

        if ch == '~' && !started && chars.peek() == Some(&'+') {
            let mut suffix = chars.clone();
            suffix.next();
            if tilde_prefix_can_expand(suffix.peek().copied()) {
                chars.next();
                let current = host.current_dir().map_err(|error| error.to_string())?;
                word.push_str(&current.to_string_lossy());
                started = true;
                continue;
            }
        }
        if ch == '~' && !started && chars.peek() == Some(&'-') {
            let mut suffix = chars.clone();
            suffix.next();
            if tilde_prefix_can_expand(suffix.peek().copied()) {
                if let Some(previous) = previous_dir {
                    chars.next();
                    word.push_str(&previous.to_string_lossy());
                    started = true;
                    continue;
                }
            }
        }
        if ch == '~' && !started && tilde_prefix_can_expand(chars.peek().copied()) {
            if let Some(home) = host.home_dir() {
                word.push_str(&home.to_string_lossy());
                started = true;
                continue;
            }
        }

        if matches!(ch, '1' | '2') && !started && chars.peek() == Some(&'>') {
            flush_word(&mut tokens, &mut word, &mut started);
            chars.next();
            let append = chars.peek() == Some(&'>');
            if append {
                chars.next();
            }
            if ch == '2' {
                tokens.push(Token::RedirectError { append });
            } else {
                tokens.push(Token::RedirectOutput { append });
            }
            continue;
        }

        match ch {
            '\'' | '"' => {
                quote = Some(ch);
                started = true;
            }
            '|' => {
                flush_word(&mut tokens, &mut word, &mut started);
                if chars.peek() == Some(&'|') {
                    chars.next();
                    tokens.push(Token::OrIf);
                } else {
                    tokens.push(Token::Pipe);
                }
            }
            '<' => {
                flush_word(&mut tokens, &mut word, &mut started);
                tokens.push(Token::RedirectInput);
            }
            '>' => {
                flush_word(&mut tokens, &mut word, &mut started);
                let append = chars.peek() == Some(&'>');
                if append {
                    chars.next();
                }
                tokens.push(Token::RedirectOutput { append });
            }
            ';' => {
                flush_word(&mut tokens, &mut word, &mut started);
                tokens.push(Token::CommandSeparator);
            }
            '&' => {
                flush_word(&mut tokens, &mut word, &mut started);
                if chars.peek() == Some(&'&') {
                    chars.next();
                    tokens.push(Token::AndIf);
                } else {
                    tokens.push(Token::Background);
                }
            }
            ' ' | '\t' => flush_word(&mut tokens, &mut word, &mut started),
            _ => {
                word.push(ch);
                started = true;
            }
        }
    }
    if quote.is_some() {
        return Err("Nicht geschlossenes Anführungszeichen.".to_owned());
    }
    flush_word(&mut tokens, &mut word, &mut started);
    Ok(tokens)
}

fn flush_word(tokens: &mut Vec<Token>, word: &mut String, started: &mut bool) {
    if *started {
        tokens.push(Token::Word(std::mem::take(word)));
        *started = false;
    }
}

fn take_variable_name(
    chars: &mut std::iter::Peekable<std::str::Chars<'_>>,
) -> Result<Option<String>, String> {
    if chars.peek() == Some(&'{') {
        chars.next();
        let mut name = String::new();
        loop {
            match chars.next() {
                Some('}') if valid_variable_reference(&name) => return Ok(Some(name)),
                Some('}') => return Err("Ungültiger Variablenname in ${...}.".to_owned()),
                Some('#') if name.is_empty() => name.push('#'),
                Some('?') if name.is_empty() => name.push('?'),
                Some(ch) if valid_variable_continue(ch) => name.push(ch),
                Some(_) => return Err("Ungültiger Variablenname in ${...}.".to_owned()),
                None => return Err("Nicht geschlossene Variablenklammer ${...}.".to_owned()),
            }
        }
    }
    if chars.peek() == Some(&'#') {
        chars.next();
        return Ok(Some("#".to_owned()));
    }
    if chars.peek() == Some(&'?') {
        chars.next();
        return Ok(Some("?".to_owned()));
    }
    if chars.peek().copied().is_some_and(|ch| ch.is_ascii_digit()) {
        return Ok(chars.next().map(|ch| ch.to_string()));
    }
    if !chars.peek().copied().is_some_and(valid_variable_start) {
        return Ok(None);
    }
    let mut name = String::new();
    while chars.peek().copied().is_some_and(valid_variable_continue) {
        name.push(chars.next().expect("peeked character exists"));
    }
    Ok(Some(name))
}

fn take_arithmetic_expression(
    chars: &mut std::iter::Peekable<std::str::Chars<'_>>,
) -> Result<String, String> {
    let mut expression = String::new();
    let mut nesting = 0usize;
    while let Some(character) = chars.next() {
        match character {
            '(' => {
                nesting += 1;
                expression.push(character);
            }
            ')' if nesting > 0 => {
                nesting -= 1;
                expression.push(character);
            }
            ')' if chars.peek() == Some(&')') => {
                chars.next();
                return Ok(expression);
            }
            ')' => return Err("Unerwartete schließende Klammer in $((...)).".to_owned()),
            _ => expression.push(character),
        }
    }
    Err("Nicht geschlossene arithmetische Expansion $((...)).".to_owned())
}

fn evaluate_arithmetic_expression<H: ShellHost>(
    expression: &str,
    variables: &BTreeMap<String, String>,
    host: &H,
) -> Result<i64, String> {
    let mut parser = ArithmeticParser {
        chars: expression.chars().peekable(),
        variables,
        host,
        nesting: 0,
    };
    let value = parser.parse_additive()?;
    parser.skip_whitespace();
    if parser.chars.peek().is_some() {
        return Err("Ungültiger arithmetischer Ausdruck.".to_owned());
    }
    Ok(value)
}

struct ArithmeticParser<'expr, 'vars, 'host, H: ShellHost> {
    chars: std::iter::Peekable<std::str::Chars<'expr>>,
    variables: &'vars BTreeMap<String, String>,
    host: &'host H,
    nesting: usize,
}

impl<H: ShellHost> ArithmeticParser<'_, '_, '_, H> {
    const MAX_NESTING: usize = 64;

    fn parse_additive(&mut self) -> Result<i64, String> {
        let mut value = self.parse_multiplicative()?;
        loop {
            self.skip_whitespace();
            let operator = match self.chars.peek().copied() {
                Some('+') | Some('-') => self.chars.next().expect("peeked operator exists"),
                _ => break,
            };
            let right = self.parse_multiplicative()?;
            value = match operator {
                '+' => value.checked_add(right),
                '-' => value.checked_sub(right),
                _ => unreachable!(),
            }
            .ok_or_else(|| "Überlauf in arithmetischem Ausdruck.".to_owned())?;
        }
        Ok(value)
    }

    fn parse_multiplicative(&mut self) -> Result<i64, String> {
        let mut value = self.parse_unary()?;
        loop {
            self.skip_whitespace();
            let operator = match self.chars.peek().copied() {
                Some('*') | Some('/') | Some('%') => {
                    self.chars.next().expect("peeked operator exists")
                }
                _ => break,
            };
            let right = self.parse_unary()?;
            value = match operator {
                '*' => value.checked_mul(right),
                '/' if right == 0 => return Err("Division durch null.".to_owned()),
                '/' => value.checked_div(right),
                '%' if right == 0 => return Err("Modulo durch null.".to_owned()),
                '%' => value.checked_rem(right),
                _ => unreachable!(),
            }
            .ok_or_else(|| "Überlauf in arithmetischem Ausdruck.".to_owned())?;
        }
        Ok(value)
    }

    fn parse_unary(&mut self) -> Result<i64, String> {
        self.skip_whitespace();
        let operator = match self.chars.peek().copied() {
            Some('+') | Some('-') => self.chars.next(),
            _ => None,
        };
        if let Some(operator) = operator {
            self.enter_nesting()?;
            let value = self.parse_unary();
            self.nesting -= 1;
            let value = value?;
            return match operator {
                '+' => Ok(value),
                '-' => value
                    .checked_neg()
                    .ok_or_else(|| "Überlauf in arithmetischem Ausdruck.".to_owned()),
                _ => unreachable!(),
            };
        }
        self.parse_primary()
    }

    fn parse_primary(&mut self) -> Result<i64, String> {
        self.skip_whitespace();
        if self.consume('(') {
            self.enter_nesting()?;
            let value = self.parse_additive();
            self.nesting -= 1;
            let value = value?;
            if !self.consume(')') {
                return Err("Fehlende schließende Klammer im arithmetischen Ausdruck.".to_owned());
            }
            return Ok(value);
        }

        if self.chars.peek().copied().is_some_and(|ch| ch.is_ascii_digit()) {
            let mut digits = String::new();
            while self.chars.peek().copied().is_some_and(|ch| ch.is_ascii_digit()) {
                digits.push(self.chars.next().expect("peeked digit exists"));
            }
            return digits
                .parse::<i64>()
                .map_err(|_| format!("Zahl außerhalb des 64-Bit-Bereichs: {digits}"));
        }

        if self
            .chars
            .peek()
            .copied()
            .is_some_and(|ch| ch == '_' || ch.is_ascii_alphabetic())
        {
            let mut name = String::new();
            while self
                .chars
                .peek()
                .copied()
                .is_some_and(|ch| ch == '_' || ch.is_ascii_alphanumeric())
            {
                name.push(self.chars.next().expect("peeked identifier character exists"));
            }
            let value = self
                .variables
                .get(&name)
                .cloned()
                .or_else(|| self.host.env_var(&name));
            return match value.as_deref() {
                None | Some("") => Ok(0),
                Some(value) => value.parse::<i64>().map_err(|_| {
                    format!("Variable '{name}' enthält keine Ganzzahl: '{value}'.")
                }),
            };
        }

        Err("Zahl oder Variablenname im arithmetischen Ausdruck erwartet.".to_owned())
    }

    fn enter_nesting(&mut self) -> Result<(), String> {
        if self.nesting >= Self::MAX_NESTING {
            return Err("Arithmetischer Ausdruck ist zu stark verschachtelt.".to_owned());
        }
        self.nesting += 1;
        Ok(())
    }

    fn skip_whitespace(&mut self) {
        while self.chars.peek().copied().is_some_and(char::is_whitespace) {
            self.chars.next();
        }
    }

    fn consume(&mut self, expected: char) -> bool {
        self.skip_whitespace();
        if self.chars.peek() == Some(&expected) {
            self.chars.next();
            true
        } else {
            false
        }
    }
}
