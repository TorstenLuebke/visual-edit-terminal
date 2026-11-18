use reedline::{Color, MouseClickMode, Prompt, PromptEditMode, PromptHistorySearch, Reedline, Signal};
use std::borrow::Cow;
use std::collections::BTreeMap;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, IsTerminal, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdout, Command, ExitCode, Stdio};
use std::thread::{self, JoinHandle};
use std::time::{SystemTime, UNIX_EPOCH};

use shelldeck_shell::{
    BackgroundJobInfo, DirectoryEntry, ErrorTarget, PipelineInput, ProcessCommand, ProcessResult,
    ShellEngine, ShellHost, ShellPathKind, StreamTarget,
};

struct TrackedJob {
    id: u32,
    command: String,
    children: Vec<Child>,
    statuses: Vec<Option<i32>>,
    writers: Vec<JoinHandle<io::Result<()>>>,
}

// Foreground children inherit the PTY's process group. A terminal Ctrl+C is
// therefore sent to both the child and this shell. Keep the shell alive while
// the child retains the default SIGINT/CTRL+C disposition.
#[cfg(unix)]
struct ForegroundInterruptGuard {
    previous: usize,
}

#[cfg(unix)]
extern "C" fn keep_shell_alive_on_sigint(_signal: i32) {}

#[cfg(unix)]
extern "C" {
    fn signal(signal: i32, handler: usize) -> usize;
}

#[cfg(unix)]
impl ForegroundInterruptGuard {
    fn install() -> io::Result<Self> {
        let previous = unsafe { signal(2, keep_shell_alive_on_sigint as usize) };
        if previous == usize::MAX {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { previous })
    }
}

#[cfg(unix)]
impl Drop for ForegroundInterruptGuard {
    fn drop(&mut self) {
        let _ = unsafe { signal(2, self.previous) };
    }
}

#[cfg(windows)]
struct ForegroundInterruptGuard;

#[cfg(windows)]
unsafe extern "system" fn keep_shell_alive_on_console_control(event: u32) -> i32 {
    if event == 0 { 1 } else { 0 }
}

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn SetConsoleCtrlHandler(
        handler: Option<unsafe extern "system" fn(u32) -> i32>,
        add: i32,
    ) -> i32;
}

#[cfg(windows)]
impl ForegroundInterruptGuard {
    fn install() -> io::Result<Self> {
        let registered = unsafe { SetConsoleCtrlHandler(Some(keep_shell_alive_on_console_control), 1) };
        if registered == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self)
    }
}

#[cfg(windows)]
impl Drop for ForegroundInterruptGuard {
    fn drop(&mut self) {
        let _ = unsafe { SetConsoleCtrlHandler(Some(keep_shell_alive_on_console_control), 0) };
    }
}

#[cfg(not(any(unix, windows)))]
struct ForegroundInterruptGuard;

#[cfg(not(any(unix, windows)))]
impl ForegroundInterruptGuard {
    fn install() -> io::Result<Self> {
        Ok(Self)
    }
}

struct ShellPrompt(String);

impl Prompt for ShellPrompt {
    fn render_prompt_left(&self) -> Cow<'_, str> {
        Cow::Borrowed(&self.0)
    }

    fn render_prompt_right(&self) -> Cow<'_, str> {
        Cow::Borrowed("")
    }

    fn render_prompt_indicator(&self, _prompt_mode: PromptEditMode) -> Cow<'_, str> {
        Cow::Borrowed("")
    }

    fn render_prompt_multiline_indicator(&self) -> Cow<'_, str> {
        Cow::Borrowed("... ")
    }

    fn render_prompt_history_search_indicator(
        &self,
        _history_search: PromptHistorySearch,
    ) -> Cow<'_, str> {
        Cow::Borrowed("(reverse-search) ")
    }

    fn get_prompt_color(&self) -> Color {
        Color::Green
    }
}

struct CliHost {
    jobs: Vec<TrackedJob>,
    next_job_id: u32,
    line_editor: Reedline,
    precommand_file: Option<PathBuf>,
    precommand_skip_file: Option<PathBuf>,
}

impl CliHost {
    fn new(
        precommand_file: Option<PathBuf>,
        precommand_skip_file: Option<PathBuf>,
    ) -> io::Result<Self> {
        let line_editor = Reedline::create()
            .with_mouse_click(MouseClickMode::Enabled)
            .use_bracketed_paste(true)
            .with_ansi_colors(true);
        Ok(Self {
            jobs: Vec::new(),
            next_job_id: 1,
            line_editor,
            precommand_file,
            precommand_skip_file,
        })
    }

    fn precommand_text(&self) -> io::Result<String> {
        let Some(path) = self.precommand_file.as_ref() else {
            return Ok(String::new());
        };
        match fs::read_to_string(path) {
            Ok(text) => Ok(text),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(String::new()),
            Err(error) => Err(error),
        }
    }

    fn consume_precommand_skip(&self) -> bool {
        let Some(path) = self.precommand_skip_file.as_ref() else {
            return false;
        };
        let marker = match fs::read_to_string(path) {
            Ok(marker) => marker,
            Err(_) => return false,
        };
        let _ = fs::write(path, "");
        let Some(timestamp) = marker.trim().strip_prefix("skip:") else {
            return false;
        };
        let Ok(timestamp) = timestamp.parse::<u128>() else {
            return false;
        };
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        now >= timestamp && now - timestamp <= 30_000
    }

    fn read_prompted_line(&mut self, prompt: &str) -> io::Result<Option<String>> {
        if !io::stdin().is_terminal() {
            // Keep scripts, pipes, and redirected input independent of a TTY
            // line editor that needs raw key and mouse events.
            print!("{prompt}");
            io::stdout().flush()?;
            let mut line = String::new();
            if io::stdin().lock().read_line(&mut line)? == 0 {
                return Ok(None);
            }
            while line.ends_with('\n') || line.ends_with('\r') {
                line.pop();
            }
            return Ok(Some(line));
        }

        // The editor owns mouse tracking only while a command line is active.
        // ShellDeck's terminal grid routes left clicks to Reedline and resets
        // these modes before a foreground program is started.
        let mut stdout = io::stdout();
        stdout.write_all(b"\x1b[?1000h\x1b[?1006h")?;
        stdout.flush()?;

        let editor_prompt = ShellPrompt(prompt.to_owned());
        let result = self.line_editor.read_line(&editor_prompt);

        let reset_result = stdout
            .write_all(b"\x1b[?1000l\x1b[?1006l")
            .and_then(|_| stdout.flush());
        reset_result?;

        match result.map_err(|error| io::Error::new(io::ErrorKind::Other, error.to_string()))? {
            Signal::Success(line) => Ok(Some(line)),
            Signal::CtrlC => {
                println!();
                Ok(Some(String::new()))
            }
            Signal::CtrlD => Ok(None),
            _ => Ok(Some(String::new())),
        }
    }
}

impl ShellHost for CliHost {
    fn write_stdout(&mut self, text: &str) -> io::Result<()> {
        io::stdout().write_all(text.as_bytes())
    }

    fn write_stdout_bytes(&mut self, bytes: &[u8]) -> io::Result<()> {
        io::stdout().write_all(bytes)
    }

    fn write_stderr(&mut self, text: &str) -> io::Result<()> {
        io::stderr().write_all(text.as_bytes())
    }

    fn current_dir(&self) -> io::Result<PathBuf> {
        env::current_dir()
    }

    fn home_dir(&self) -> Option<PathBuf> {
        env::var_os("HOME")
            .or_else(|| env::var_os("USERPROFILE"))
            .map(PathBuf::from)
    }

    fn env_var(&self, name: &str) -> Option<String> {
        env::var(name).ok()
    }

    fn read_input_line(&mut self) -> io::Result<Option<String>> {
        self.read_prompted_line("")
    }

    fn set_current_dir(&mut self, path: &Path) -> io::Result<()> {
        env::set_current_dir(path)
    }

    fn path_kind(&self, path: &Path) -> io::Result<Option<ShellPathKind>> {
        match fs::metadata(path) {
            Ok(metadata) => Ok(Some(if metadata.is_file() {
                ShellPathKind::File
            } else if metadata.is_dir() {
                ShellPathKind::Directory
            } else {
                ShellPathKind::Other
            })),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error),
        }
    }

    fn read_dir(&mut self, path: &Path) -> io::Result<Vec<DirectoryEntry>> {
        let mut entries = Vec::new();
        for item in fs::read_dir(path)? {
            let item = item?;
            let name = item.file_name().to_string_lossy().into_owned();
            let is_directory = item.file_type()?.is_dir();
            entries.push(DirectoryEntry {
                is_hidden: name.starts_with('.'),
                name,
                is_directory,
            });
        }
        Ok(entries)
    }

    fn read_file_bytes(&mut self, path: &Path) -> io::Result<Vec<u8>> {
        fs::read(path)
    }

    fn write_file_bytes(&mut self, path: &Path, bytes: &[u8], append: bool) -> io::Result<()> {
        let mut file = open_output(path, append)?;
        file.write_all(bytes)
    }

    fn create_dir(&mut self, path: &Path, recursive: bool) -> io::Result<()> {
        if recursive {
            fs::create_dir_all(path)
        } else {
            fs::create_dir(path)
        }
    }

    fn run_interactive_program(
        &mut self,
        command: &ProcessCommand,
        working_dir: &Path,
        variables: &BTreeMap<String, String>,
    ) -> io::Result<Option<i32>> {
        // The ShellEngine calls this hook only for a single foreground command
        // without redirections. Keep a defensive fallback for future callers
        // that pass a redirected stderr target.
        if matches!(&command.stderr, ErrorTarget::File { .. }) {
            return Ok(None);
        }

        let _interrupt_guard = ForegroundInterruptGuard::install()?;
        let status = Command::new(&command.program)
            .args(&command.args)
            .current_dir(working_dir)
            .envs(variables.iter().map(|(key, value)| (key.as_str(), value.as_str())))
            .stdin(Stdio::inherit())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .status()?;
        Ok(Some(status.code().unwrap_or(1)))
    }

    fn run_pipeline(
        &mut self,
        commands: &[ProcessCommand],
        working_dir: &Path,
        variables: &BTreeMap<String, String>,
        stdin: PipelineInput,
        stdout: StreamTarget,
    ) -> io::Result<ProcessResult> {
        if commands.is_empty() {
            return Ok(ProcessResult::default());
        }
        let _interrupt_guard = ForegroundInterruptGuard::install()?;
        let (mut children, writers) =
            spawn_pipeline_children(commands, working_dir, variables, stdin, &stdout, false)?;
        let mut last_child = children.pop().expect("non-empty command list");
        let result = if matches!(stdout, StreamTarget::Capture) {
            let output = last_child.wait_with_output()?;
            ProcessResult {
                status: output.status.code().unwrap_or(1),
                stdout: output.stdout,
            }
        } else {
            let status = last_child.wait()?;
            ProcessResult {
                status: status.code().unwrap_or(1),
                stdout: Vec::new(),
            }
        };

        for mut child in children {
            child.wait()?;
        }
        join_writers(writers)?;
        Ok(result)
    }

    fn start_background_pipeline(
        &mut self,
        commands: &[ProcessCommand],
        working_dir: &Path,
        variables: &BTreeMap<String, String>,
        stdin: PipelineInput,
        stdout: StreamTarget,
        command_label: &str,
    ) -> io::Result<u32> {
        if commands.is_empty() {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "empty pipeline"));
        }
        if matches!(stdout, StreamTarget::Capture) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "background pipeline output cannot be captured synchronously",
            ));
        }
        let id = self.next_job_id;
        let next_job_id = id.checked_add(1).ok_or_else(|| {
            io::Error::new(io::ErrorKind::Other, "background job ID space exhausted")
        })?;
        let (children, writers) =
            spawn_pipeline_children(commands, working_dir, variables, stdin, &stdout, true)?;
        let statuses = vec![None; children.len()];
        self.jobs.push(TrackedJob {
            id,
            command: command_label.to_owned(),
            children,
            statuses,
            writers,
        });
        self.next_job_id = next_job_id;
        Ok(id)
    }

    fn background_jobs(&mut self) -> io::Result<Vec<BackgroundJobInfo>> {
        self.jobs
            .iter_mut()
            .map(|job| {
                let status = refresh_job(job)?;
                Ok(BackgroundJobInfo {
                    id: job.id,
                    command: job.command.clone(),
                    status,
                })
            })
            .collect()
    }

    fn wait_background_job(
        &mut self,
        job_id: Option<u32>,
    ) -> io::Result<Vec<BackgroundJobInfo>> {
        if let Some(id) = job_id {
            if !self.jobs.iter().any(|job| job.id == id) {
                return Err(io::Error::new(
                    io::ErrorKind::NotFound,
                    format!("background job {id} does not exist"),
                ));
            }
        }
        let ids: Vec<u32> = self
            .jobs
            .iter()
            .filter(|job| job_id.map_or(true, |id| job.id == id))
            .map(|job| job.id)
            .collect();
        let mut completed = Vec::with_capacity(ids.len());
        for id in &ids {
            let job = self
                .jobs
                .iter_mut()
                .find(|job| job.id == *id)
                .expect("selected job still exists");
            let status = finish_job(job)?;
            completed.push(BackgroundJobInfo {
                id: job.id,
                command: job.command.clone(),
                status: Some(status),
            });
        }
        self.jobs.retain(|job| !ids.contains(&job.id));
        Ok(completed)
    }

    fn clear_screen(&mut self) -> io::Result<()> {
        let mut stdout = io::stdout().lock();
        stdout.write_all(b"\x1b[2J\x1b[H")?;
        stdout.flush()
    }
}

fn spawn_pipeline_children(
    commands: &[ProcessCommand],
    working_dir: &Path,
    variables: &BTreeMap<String, String>,
    stdin: PipelineInput,
    stdout: &StreamTarget,
    background: bool,
) -> io::Result<(Vec<Child>, Vec<JoinHandle<io::Result<()>>>)> {
    let mut input_file = match &stdin {
        PipelineInput::File(path) => Some(File::open(path)?),
        _ => None,
    };
    let mut input_bytes = match stdin {
        PipelineInput::Bytes(bytes) => Some(bytes),
        _ => None,
    };
    let stdout_file = match stdout {
        StreamTarget::File { path, append } => Some(open_output(path, *append)?),
        _ => None,
    };
    let mut stderr_files = Vec::with_capacity(commands.len());
    for spec in commands {
        stderr_files.push(match &spec.stderr {
            ErrorTarget::Inherit => None,
            ErrorTarget::File { path, append } => Some(open_output(path, *append)?),
        });
    }
    let mut children: Vec<Child> = Vec::with_capacity(commands.len());
    let mut previous_stdout: Option<ChildStdout> = None;
    let mut writers: Vec<JoinHandle<io::Result<()>>> = Vec::new();

    for (index, spec) in commands.iter().enumerate() {
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .current_dir(working_dir)
            .envs(variables.iter().map(|(key, value)| (key.as_str(), value.as_str())));

        if index == 0 {
            if input_bytes.is_some() {
                command.stdin(Stdio::piped());
            } else if let Some(file) = input_file.take() {
                command.stdin(Stdio::from(file));
            } else if background {
                command.stdin(Stdio::null());
            } else {
                command.stdin(Stdio::inherit());
            }
        } else {
            command.stdin(Stdio::from(
                previous_stdout
                    .take()
                    .expect("previous process stdout is connected"),
            ));
        }

        if index + 1 < commands.len() {
            command.stdout(Stdio::piped());
        } else {
            match stdout {
                StreamTarget::Inherit => {
                    command.stdout(Stdio::inherit());
                }
                StreamTarget::Capture => {
                    command.stdout(Stdio::piped());
                }
                StreamTarget::File { .. } => {
                    command.stdout(Stdio::from(
                        stdout_file
                            .as_ref()
                            .expect("output file was opened")
                            .try_clone()?,
                    ));
                }
            }
        }

        match &stderr_files[index] {
            Some(file) => {
                command.stderr(Stdio::from(file.try_clone()?));
            }
            None => {
                command.stderr(Stdio::inherit());
            }
        }

        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(error) => {
                terminate_children(&mut children);
                let _ = join_writers(writers);
                return Err(error);
            }
        };

        if index == 0 {
            if let Some(bytes) = input_bytes.take() {
                let mut child_stdin = child
                    .stdin
                    .take()
                    .expect("piped stdin was requested for byte input");
                writers.push(thread::spawn(move || {
                    match child_stdin.write_all(&bytes) {
                        Err(error) if error.kind() == io::ErrorKind::BrokenPipe => Ok(()),
                        result => result,
                    }
                }));
            }
        }
        if index + 1 < commands.len() {
            previous_stdout = child.stdout.take();
        }
        children.push(child);
    }
    Ok((children, writers))
}

fn refresh_job(job: &mut TrackedJob) -> io::Result<Option<i32>> {
    for (child, status) in job.children.iter_mut().zip(job.statuses.iter_mut()) {
        if status.is_none() {
            if let Some(exit_status) = child.try_wait()? {
                *status = Some(exit_status.code().unwrap_or(1));
            }
        }
    }
    if job.statuses.iter().all(Option::is_some) {
        Ok(job.statuses.last().copied().flatten())
    } else {
        Ok(None)
    }
}

fn finish_job(job: &mut TrackedJob) -> io::Result<i32> {
    for (child, status) in job.children.iter_mut().zip(job.statuses.iter_mut()) {
        if status.is_none() {
            *status = Some(child.wait()?.code().unwrap_or(1));
        }
    }
    join_writers(std::mem::take(&mut job.writers))?;
    Ok(job.statuses.last().copied().flatten().unwrap_or(1))
}

fn open_output(path: &Path, append: bool) -> io::Result<File> {
    OpenOptions::new()
        .write(true)
        .create(true)
        .append(append)
        .truncate(!append)
        .open(path)
}

fn terminate_children(children: &mut [Child]) {
    for child in children.iter_mut() {
        let _ = child.kill();
    }
    for child in children.iter_mut() {
        let _ = child.wait();
    }
}

fn join_writers(writers: Vec<JoinHandle<io::Result<()>>>) -> io::Result<()> {
    for writer in writers {
        match writer.join() {
            Ok(result) => result?,
            Err(_) => {
                return Err(io::Error::new(
                    io::ErrorKind::Other,
                    "pipeline input writer thread panicked",
                ));
            }
        }
    }
    Ok(())
}

fn run_shell(
    precommand_file: Option<PathBuf>,
    precommand_skip_file: Option<PathBuf>,
) -> io::Result<i32> {
    let mut shell = ShellEngine::new();
    let mut host = CliHost::new(precommand_file, precommand_skip_file)?;

    loop {
        let cwd = host.current_dir()?;
        let prompt = format!("{} > ", cwd.display());
        let Some(input) = host.read_prompted_line(&prompt)? else {
            return Ok(0);
        };

        if !input.trim().is_empty() && !host.consume_precommand_skip() {
            let precommand = host.precommand_text()?;
            if !precommand.trim().is_empty() {
                match shell.execute_line(&precommand, &mut host) {
                    Ok(result) if result.should_exit => return Ok(result.status),
                    Ok(_) => {}
                    Err(error) => host.write_stderr(&format!("{error}\n"))?,
                }
            }
        }

        match shell.execute_line(&input, &mut host) {
            Ok(result) if result.should_exit => return Ok(result.status),
            Ok(_) => {}
            Err(error) => host.write_stderr(&format!("{error}\n"))?,
        }
    }
}

fn parse_host_options() -> Result<(Option<PathBuf>, Option<PathBuf>), String> {
    let mut arguments = env::args_os().skip(1);
    let mut precommand_file = None;
    let mut precommand_skip_file = None;
    while let Some(argument) = arguments.next() {
        if argument == "--precommand-file" {
            let Some(path) = arguments.next() else {
                return Err("--precommand-file benötigt einen Dateipfad.".to_owned());
            };
            precommand_file = Some(PathBuf::from(path));
        } else if argument == "--precommand-skip-file" {
            let Some(path) = arguments.next() else {
                return Err("--precommand-skip-file benötigt einen Dateipfad.".to_owned());
            };
            precommand_skip_file = Some(PathBuf::from(path));
        } else {
            return Err(format!("Unbekannte Option: {}", argument.to_string_lossy()));
        }
    }
    Ok((precommand_file, precommand_skip_file))
}

fn main() -> ExitCode {
    let (precommand_file, precommand_skip_file) = match parse_host_options() {
        Ok(options) => options,
        Err(error) => {
            eprintln!("shelldeck-shell: {error}");
            eprintln!("Aufruf: shelldeck-shell [--precommand-file PFAD] [--precommand-skip-file PFAD]");
            return ExitCode::FAILURE;
        }
    };
    match run_shell(precommand_file, precommand_skip_file) {
        Ok(status) => ExitCode::from(status.clamp(0, 255) as u8),
        Err(error) => {
            eprintln!("shell host error: {error}");
            ExitCode::FAILURE
        }
    }
}
