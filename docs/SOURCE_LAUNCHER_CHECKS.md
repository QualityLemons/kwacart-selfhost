# Native source-launcher checks

The **Native source launchers** GitHub Actions workflow is intended for
`QualityLemons/kwacart-selfhost`. It runs on Windows, Intel Mac and Apple silicon
Mac, each with Python 3.12, 3.13 and 3.14. Run it manually in the Actions tab;
source changes and pull requests also trigger it. A passing Linux/Replit unit
test is **not** evidence that these native jobs passed.

Each job builds the allowlisted source ZIP and extracts it with Windows
`Expand-Archive` or macOS `ditto` into a temporary path with spaces. On Mac it
checks both ZIP permission metadata and the extracted executable bit, without
repairing permissions. It executes the actual `.bat` or `.command` wrapper.

The harness installs only its terminal driver in the runner's Python. KwaCart's
first launch must create its own private runtime and actually install every
package in `requirements.txt`; there is no application dependency cache or
`--use-current-python` shortcut. Interpreter-selection tests use controlled
executable probes, then the full launch uses the selected matrix interpreter.
The private runtime's actual version and `pip check` are verified.

A real terminal drives Django's initial email/password prompts with a fresh
synthetic account. A CI-only browser callback checks the exact local URL returns
HTTP 200 before recording the browser request. HTTP login uses CSRF and cookies.
Ctrl+C must stop the launcher and server cleanly. If Windows asks “Terminate
batch job (Y/N)?”, the test answers N so the wrapper can finish and return its
recorded exit status, then dismisses the final pause. An immediate restart on the
same port blocks external Python socket connections and rejects pip/ensurepip
subprocesses, verifies no setup repeats, and checks the account, local key and
authenticated session survive.

## Privacy and limits

All account credentials, cookies, keys, databases and terminal buffers are
temporary, isolated test state. No instance folders, transcripts or databases
are uploaded as CI artifacts. The workflow has read-only repository permissions.
Only the named workflow and harness files are allowlisted for clean publication;
other workspace workflows are not implicitly included.

These are native automated checks, not a claim that a human has tested every
installer or Finder/Explorer double-click. The browser callback verifies
readiness, not desktop browser UI. Offline checks deny external Python TCP
connections and package bootstrap; they do not disconnect the entire runner.
The workflow intentionally fails rather than substituting existing packages if
a supported Python version cannot install a dependency.
