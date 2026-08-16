"""Read a string field out of a JSON document that is still streaming.

The editor returns structured JSON with `say` declared first, so `say` is
complete long before the rest of the object is. Pulling it out of the partial
buffer is what makes the first line usable in ~2 seconds instead of waiting for
the whole response.

Deterministic and dependency-free, so it is unit-testable offline.
"""

from __future__ import annotations

_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def partial_string_field(buffer: str, key: str) -> tuple[str, bool]:
    """Return `(value_so_far, complete)` for a top-level string field.

    `complete` is True once the field's closing quote has arrived. Returns
    `("", False)` while the key or its opening quote is still missing.
    """
    marker = f'"{key}"'
    start = buffer.find(marker)
    if start == -1:
        return "", False

    index = start + len(marker)
    length = len(buffer)

    while index < length and buffer[index] in " \t\r\n":
        index += 1
    if index >= length or buffer[index] != ":":
        return "", False
    index += 1
    while index < length and buffer[index] in " \t\r\n":
        index += 1
    if index >= length:
        return "", False
    if buffer[index] != '"':
        # Field is present but not a string (e.g. null) — nothing to stream.
        return "", True
    index += 1

    out: list[str] = []
    while index < length:
        char = buffer[index]
        if char == "\\":
            if index + 1 >= length:
                # Escape sequence split across chunks; emit what we have.
                break
            nxt = buffer[index + 1]
            if nxt == "u":
                if index + 6 > length:
                    break
                try:
                    out.append(chr(int(buffer[index + 2 : index + 6], 16)))
                except ValueError:
                    out.append(buffer[index + 2 : index + 6])
                index += 6
                continue
            out.append(_ESCAPES.get(nxt, nxt))
            index += 2
            continue
        if char == '"':
            return "".join(out), True
        out.append(char)
        index += 1

    return "".join(out), False
