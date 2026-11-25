"""
Shared console UI + logging helpers for all three scrapers.

Two jobs:

  1. Colored, arrow-key interactive prompts (menus, yes/no, typed input). The
     menus render an inline ">" pointer you move with the Up/Down arrows and
     pick with Enter. When there is no interactive terminal (piped input, a
     scheduled job) or arrow-key reading isn't available, every prompt falls
     back to plain numbered / typed entry, so non-interactive runs still work.

  2. A single colored logging setup so program output (status, progress,
     results, errors) is consistent everywhere instead of ad-hoc print().

Colors come from colorama (already a dependency); arrow keys are read with the
stdlib ``msvcrt`` module on Windows. Nothing here needs a new package.

Consistent color scheme (same meaning -> same color in every menu):
  * question / banner ....... bold cyan
  * highlighted selection ... bold cyan label + green ">" pointer
  * "(default)" marker ...... green   (always green = "this is the default")
  * description text ........ dim
  * typed-input prompt ...... cyan
  * invalid-input warning ... red
  * summary values .......... green
"""

from __future__ import annotations

import logging
import sys

from colorama import Style, Fore, init as _colorama_init

# Wrap stdout so ANSI color + cursor codes work on legacy Windows consoles too.
# (Windows Terminal / Windows 11 support ANSI natively; this is belt-and-braces.)
_colorama_init()

try:
    import msvcrt  # Windows-only; used for raw arrow-key reading.
    _HAS_MSVCRT = True
except ImportError:                                   # pragma: no cover
    _HAS_MSVCRT = False


# ---------------------------------------------------------------------------
# Color scheme
# ---------------------------------------------------------------------------

RESET = Style.RESET_ALL
C_TITLE = Fore.CYAN + Style.BRIGHT     # questions / banners
C_SELECTED = Fore.CYAN + Style.BRIGHT  # the currently-highlighted option label
C_POINTER = Fore.GREEN + Style.BRIGHT  # the ">" cursor
C_DEFAULT = Fore.GREEN                 # the "(default)" marker
C_LABEL = Style.BRIGHT                 # non-selected option labels
C_DESC = Style.DIM                     # option descriptions / hints
C_PROMPT = Fore.CYAN                   # typed-input prompt text
C_ERROR = Fore.RED                     # invalid-input warnings
C_VALUE = Fore.GREEN                   # summary values


def _tty() -> bool:
    """True only when we can drive a real interactive terminal."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class _ColorFormatter(logging.Formatter):
    """Log formatter that tints the level name by severity."""

    LEVEL_COLORS = {
        logging.DEBUG: Style.DIM,
        logging.INFO: Fore.CYAN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED + Style.BRIGHT,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, "")
        record.levelname = f"{color}{record.levelname:<7}{RESET}"
        return super().format(record)


def setup_logging(level: int = logging.INFO) -> None:
    """Install one colored handler on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(_ColorFormatter("%(asctime)s | %(levelname)s | %(message)s",
                                         datefmt="%H:%M:%S"))
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Small direct-to-terminal helpers (for the interactive questionnaire only)
# ---------------------------------------------------------------------------

def banner(text: str) -> None:
    """A boxed section header shown above a questionnaire."""
    line = "=" * 60
    print(f"\n{C_TITLE}{line}\n  {text}\n{line}{RESET}")


def rule(text: str) -> None:
    """A thin titled rule (used above the config summary)."""
    line = "-" * 60
    print(f"\n{C_TITLE}{line}\n  {text}\n{line}{RESET}")


def note(text: str) -> None:
    """A dim helper/hint line inside a questionnaire."""
    print(f"{C_DESC}{text}{RESET}")


def summary_row(label: str, value, width: int = 18) -> None:
    """One 'Label : value' row in a config summary (value shown in green)."""
    print(f"  {label:<{width}}: {C_VALUE}{value}{RESET}")


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def _cancel() -> "SystemExit":
    print()
    return SystemExit("Cancelled. No changes made.")


def _default_index(options: list, default_value) -> int:
    for i, opt in enumerate(options):
        if opt[0] == default_value:
            return i
    return 0


def select(title: str, options: list[tuple], default_value=None) -> object:
    """
    Ask the user to pick one option.

    options: list of (value, label, description) tuples.
    Returns the chosen value. Arrow-key navigable on an interactive terminal;
    otherwise falls back to numbered entry.
    """
    default_index = _default_index(options, default_value)
    if _tty() and _HAS_MSVCRT:
        return _select_arrows(title, options, default_index)
    return _select_numbered(title, options, default_index)


def _render_options(options: list[tuple], cursor: int, default_index: int,
                    redraw: bool) -> None:
    """Draw (or redraw) the option list with the pointer on `cursor`."""
    if redraw:
        # Move the cursor back up over the previously-drawn block.
        sys.stdout.write(f"\x1b[{len(options)}A")
    for i, (_value, label, desc) in enumerate(options):
        selected = i == cursor
        pointer = f"{C_POINTER}>{RESET} " if selected else "  "
        label_color = C_SELECTED if selected else C_LABEL
        tag = f" {C_DEFAULT}(default){RESET}" if i == default_index else ""
        line = f" {pointer}{label_color}{label}{RESET}  {C_DESC}{desc}{RESET}{tag}"
        # Clear the whole line first so shorter redraws don't leave artifacts.
        sys.stdout.write("\x1b[2K" + line + "\n")
    sys.stdout.flush()


def _select_arrows(title: str, options: list[tuple], default_index: int) -> object:
    print(f"\n{C_TITLE}{title}{RESET}")
    cursor = default_index
    _render_options(options, cursor, default_index, redraw=False)
    while True:
        try:
            ch = msvcrt.getwch()
        except (KeyboardInterrupt, EOFError):
            raise _cancel()
        if ch in ("\r", "\n"):                       # Enter
            return options[cursor][0]
        if ch == "\x03":                             # Ctrl+C
            raise _cancel()
        if ch in ("\x00", "\xe0"):                   # arrow-key prefix
            arrow = msvcrt.getwch()
            if arrow == "H":                         # Up
                cursor = (cursor - 1) % len(options)
            elif arrow == "P":                       # Down
                cursor = (cursor + 1) % len(options)
            else:
                continue
            _render_options(options, cursor, default_index, redraw=True)


def _read(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise _cancel()


def _select_numbered(title: str, options: list[tuple], default_index: int) -> object:
    print(f"\n{C_TITLE}{title}{RESET}")
    for i, (_value, label, desc) in enumerate(options, 1):
        tag = f" {C_DEFAULT}(default){RESET}" if i - 1 == default_index else ""
        print(f"  {Fore.YELLOW}[{i}]{RESET} {C_LABEL}{label}{RESET}  "
              f"{C_DESC}{desc}{RESET}{tag}")
    n = default_index + 1
    while True:
        raw = _read(f"{C_PROMPT}Selection [{n}] (Enter = {n}): {RESET}")
        if not raw:
            return options[default_index][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(f"{C_ERROR}  Please enter a number between 1 and {len(options)}.{RESET}")


def confirm(question: str, default: bool = True) -> bool:
    """Yes/No question. Arrow-selectable; falls back to typed y/n."""
    options = [(True, "Yes", ""), (False, "No", "")]
    if _tty() and _HAS_MSVCRT:
        return bool(select(question, options, default_value=default))
    # Typed fallback.
    d = "Yes" if default else "No"
    while True:
        raw = _read(f"{C_PROMPT}{question} [Y/N] (Enter = {d}): {RESET}").lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print(f"{C_ERROR}  Please answer 'y' or 'n'.{RESET}")


def ask_int(question: str, default: int, minimum: int = 0) -> int:
    """Ask for a whole number no less than `minimum`."""
    while True:
        raw = _read(f"{C_PROMPT}{question} [{default}] (Enter = {default}): {RESET}")
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print(f"{C_ERROR}  Please enter a whole number.{RESET}")
            continue
        if value < minimum:
            print(f"{C_ERROR}  Please enter a number of {minimum} or greater.{RESET}")
            continue
        return value


def ask_float(question: str, default: float, minimum: float = 0.0) -> float:
    """Ask for a number (decimals allowed) no less than `minimum`."""
    while True:
        raw = _read(f"{C_PROMPT}{question} [{default}] (Enter = {default}): {RESET}")
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            print(f"{C_ERROR}  Please enter a number.{RESET}")
            continue
        if value < minimum:
            print(f"{C_ERROR}  Please enter a number of {minimum} or greater.{RESET}")
            continue
        return value


def ask_text(question: str, default: str, allow_empty: bool = True,
             validate=None, transform=None) -> str:
    """
    Ask for free text. `transform` cleans the raw input; `validate` returns True
    for acceptable values. Empty input keeps `default`.
    """
    shown = default if default else "auto"
    while True:
        raw = _read(f"{C_PROMPT}{question} [{shown}] (Enter = {shown}): {RESET}")
        if not raw:
            return default
        value = transform(raw) if transform else raw
        if not value and not allow_empty:
            print(f"{C_ERROR}  Please enter a value.{RESET}")
            continue
        if validate and not validate(value):
            print(f"{C_ERROR}  That value isn't valid — try again.{RESET}")
            continue
        return value
