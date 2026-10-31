"""Turn Python errors into plain English that names the line and says what to change (bible section 7)."""

import difflib
import traceback

SCRIPT_FILENAME = "<script>"


def _script_line(error: BaseException) -> int | None:
    if isinstance(error, SyntaxError) and error.filename == SCRIPT_FILENAME:
        return error.lineno
    line = None
    for frame in traceback.extract_tb(error.__traceback__):
        if frame.filename == SCRIPT_FILENAME:
            line = frame.lineno
    return line


def explain(error: BaseException, known_names: list[str] | None = None) -> dict:
    """Returns {"line", "message", "details"}. "details" is the raw traceback, hidden unless the owner expands it."""
    line = _script_line(error)
    where = f"Line {line}: " if line else ""
    kind = type(error).__name__
    text = str(error)

    if isinstance(error, SyntaxError):
        message = f"{where}Python couldn't understand this line ({error.msg}). Check for a missing bracket, quote, colon or comma."
        if "indent" in (error.msg or ""):
            message = f"{where}The indentation (spaces at the start of the line) doesn't line up. Use 4 spaces per level."
    elif isinstance(error, NameError):
        name = getattr(error, "name", None) or (text.split("'")[1] if "'" in text else text)
        suggestion = difflib.get_close_matches(str(name), known_names or [], n=1)
        hint = f" Did you mean '{suggestion[0]}'?" if suggestion else " Check the spelling, or define it before using it."
        message = f"{where}'{name}' isn't defined.{hint}"
    elif isinstance(error, ImportError):
        message = f"{where}{text}. Scripts can only use the built-in helpers plus math, statistics, numpy and pandas."
    elif isinstance(error, IndexError):
        message = f"{where}This asks for an item that doesn't exist yet. Early candles may not have enough history; check len(data.close) first."
    elif isinstance(error, ZeroDivisionError):
        message = f"{where}This divides by zero. Check the number you divide by isn't 0 first."
    elif isinstance(error, KeyError):
        message = f"{where}The key {text} isn't in that dictionary. Check the spelling."
    elif isinstance(error, AttributeError):
        message = f"{where}{text}. Check the spelling of the name after the dot."
    elif isinstance(error, TypeError):
        message = f"{where}A value is the wrong type here ({text}). For example, a number was expected but got text or a list."
    elif isinstance(error, ValueError):
        message = f"{where}A value isn't allowed here ({text})."
    elif isinstance(error, MemoryError):
        message = f"{where}The script used too much memory and was stopped. Work with fewer candles or smaller lists."
    elif isinstance(error, RecursionError):
        message = f"{where}A function keeps calling itself without stopping."
    else:
        message = f"{where}{kind}: {text}"

    details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    return {"line": line, "message": message, "details": details}


def timeout_error(seconds: float) -> dict:
    return {
        "line": None,
        "message": f"The script took longer than {seconds:g} seconds and was stopped. It may have an endless loop (a 'while' that never ends).",
        "details": "",
    }
