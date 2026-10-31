"""Pine Script conversion helper (bible section 7, phase 14 stretch goal).

Converts SIMPLE Pine Script v4/v5 indicators into this app's Python. It
handles inputs, the common ta.* indicators, plot() and hline(). Anything it
can't convert is kept as a commented "TODO" line and listed as a warning, so
the owner can finish it by hand. It never guesses silently.
"""

import re

COLORS = {
    "red": "#e5767e", "green": "#5cc8a8", "blue": "#7fa7ff", "orange": "#e6b87a", "yellow": "#e6d27a",
    "purple": "#c9a6ff", "white": "#e6e8f0", "gray": "#9aa0b4", "silver": "#c0c4d4", "aqua": "#8fd3e8",
    "teal": "#7cc6b8", "fuchsia": "#f2a6e0", "lime": "#a6e07a", "maroon": "#b56a72", "navy": "#6a7ab5", "olive": "#b5b56a",
}

SERIES = {"close", "open", "high", "low", "volume", "time"}

FUNCTIONS = {
    "ta.sma": "sma", "sma": "sma", "ta.ema": "ema", "ema": "ema", "ta.rma": "rma", "rma": "rma",
    "ta.rsi": "rsi", "rsi": "rsi", "ta.stdev": "stdev", "stdev": "stdev",
    "ta.highest": "highest", "highest": "highest", "ta.lowest": "lowest", "lowest": "lowest",
    "ta.crossover": "crossover", "crossover": "crossover", "ta.crossunder": "crossunder", "crossunder": "crossunder",
    "ta.vwap": "vwap", "math.abs": "np.abs", "math.max": "np.maximum", "math.min": "np.minimum", "nz": "np.nan_to_num",
}


def _translate_expression(text: str, inputs: set[str]) -> str:
    text = text.strip()
    text = re.sub(r"\bta\.atr\(\s*([^)]+)\)", r"atr(data.high, data.low, data.close, \1)", text)
    text = re.sub(r"\bta\.tr\b(\(\s*\w*\s*\))?", "true_range(data.high, data.low, data.close)", text)
    text = re.sub(r"\bta\.vwap\b(\(\s*\w*\s*\))?", "vwap(data.high, data.low, data.close, data.volume)", text)
    for pine_name, python_name in sorted(FUNCTIONS.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<![\w.]){re.escape(pine_name)}\s*\(", f"{python_name}(", text)
    for series in SERIES:
        text = re.sub(rf"(?<![\w.]){series}\b(?!\s*=)", f"data.{series}", text)
    for name in inputs:
        text = re.sub(rf"(?<![\w.]){name}\b", f"inputs.{name}", text)
    text = re.sub(r"\btrue\b", "True", text)
    text = re.sub(r"\bfalse\b", "False", text)
    text = re.sub(r"\band\b", "and", text)
    text = text.replace("na", "nan") if re.fullmatch(r"na", text) else text
    return text


def _color(argument: str | None) -> str | None:
    if not argument:
        return None
    match = re.search(r"color\.(\w+)", argument)
    if match and match.group(1) in COLORS:
        return COLORS[match.group(1)]
    match = re.search(r"#[0-9a-fA-F]{6}", argument)
    return match.group(0) if match else None


def _split_arguments(text: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for char in text:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def convert_pine(source: str) -> dict:
    name = "Converted indicator"
    overlay = True
    inputs: dict[str, str] = {}
    body: list[str] = []
    warnings: list[str] = []

    for number, raw in enumerate(source.splitlines(), start=1):
        line = raw.split("//")[0].rstrip() if "//" in raw and not raw.strip().startswith("//@") else raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("//@"):
            continue
        if raw.strip().startswith("//"):
            body.append("    # " + raw.strip()[2:].strip())
            continue

        match = re.match(r"(indicator|study)\s*\((.*)\)\s*$", stripped)
        if match:
            args = _split_arguments(match.group(2))
            if args and args[0][:1] in "\"'":
                name = args[0].strip("\"'")
            overlay = any(re.match(r"overlay\s*=\s*true", a) for a in args)
            continue
        if re.match(r"strategy\s*\(", stripped):
            warnings.append(f"Line {number}: Pine strategies aren't converted automatically yet; only indicators. Rewrite it with on_bar().")
            continue

        match = re.match(r"(\w+)\s*=\s*input(?:\.\w+)?\s*\((.*)\)\s*$", stripped)
        if match:
            args = _split_arguments(match.group(2))
            default = args[0].split("=", 1)[1].strip() if args and args[0].startswith("defval") else (args[0] if args else "0")
            if default in SERIES:
                warnings.append(f"Line {number}: source inputs become 'close'; change it in the code if needed.")
                default = '"close"'
            inputs[match.group(1)] = default.replace("true", "True").replace("false", "False")
            continue

        match = re.match(r"plot\s*\((.*)\)\s*$", stripped)
        if match:
            args = _split_arguments(match.group(1))
            series = _translate_expression(args[0], set(inputs))
            title = next((a.split("=", 1)[1].strip().strip("\"'") for a in args[1:] if a.startswith("title")), None)
            if title is None and len(args) > 1 and args[1][:1] in "\"'":
                title = args[1].strip("\"'")
            color = _color(next((a for a in args[1:] if "color" in a), None))
            pane = '"price"' if overlay else '"main"'
            color_part = f', color="{color}"' if color else ""
            body.append(f'    plot("{title or "Plot"}", {series}{color_part}, pane={pane})')
            continue

        match = re.match(r"hline\s*\((.*)\)\s*$", stripped)
        if match:
            args = _split_arguments(match.group(1))
            pane = '"price"' if overlay else '"main"'
            body.append(f"    hline({_translate_expression(args[0], set(inputs))}, pane={pane})")
            continue

        match = re.match(r"(?:var\s+)?(?:float|int|bool|series\s+float)?\s*(\w+)\s*:?=\s*(.+)$", stripped)
        if match and not stripped.startswith(("if ", "for ", "while ")) and "?" not in match.group(2) and "[" not in match.group(2):
            body.append(f"    {match.group(1)} = {_translate_expression(match.group(2), set(inputs))}")
            continue

        body.append(f"    # TODO (not converted): {stripped}")
        warnings.append(f"Line {number}: couldn't convert '{stripped[:60]}'. It's kept as a comment for you to finish.")

    lines = [
        "# Converted from Pine Script by the conversion helper.",
        "# Check it carefully: the helper only knows common, simple patterns.",
        "",
        f'name = "{name}"',
        "inputs = {" + ", ".join(f'"{k}": {v}' for k, v in inputs.items()) + "}",
        "",
        "",
        "def calculate(data):",
    ]
    lines += body or ["    pass"]
    return {"code": "\n".join(lines) + "\n", "warnings": warnings, "name": name}
