"""CLI process execution with exclusive private output files and no shell."""
import os
import subprocess


def execute(state_directory, ident, args, prompt, cwd, run=subprocess.run):
    folder = state_directory / 'cli-runs'
    folder.mkdir(mode=0o700, exist_ok=True)
    output = folder / (str(ident) + '.jsonl')
    errors = folder / (str(ident) + '.stderr')
    # Explicit file modes also protect direct callers without the service umask.
    with os.fdopen(os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stdout:
        with os.fdopen(os.open(errors, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stderr:
            return run(args, input=prompt, text=True, stdout=stdout, stderr=stderr, cwd=cwd)
