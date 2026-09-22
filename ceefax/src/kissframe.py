"""KISS frame codec for modem73's TCP KISS port.

The payload Ceefax hands the modem is the CFX fragment itself. The only extra
byte on the wire is the KISS command byte, which is why HF frames stop at 170
bytes under the 172-byte short-frame PHY payload.
"""

from __future__ import annotations

FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD
DATA_COMMAND = 0x00


def kiss_escape(data: bytes) -> bytes:
    out = bytearray()
    for byte in data:
        if byte == FEND:
            out.extend((FESC, TFEND))
        elif byte == FESC:
            out.extend((FESC, TFESC))
        else:
            out.append(byte)
    return bytes(out)


def kiss_unescape(data: bytes) -> bytes:
    out = bytearray()
    escaped = False
    for byte in data:
        if escaped:
            if byte == TFEND:
                out.append(FEND)
            elif byte == TFESC:
                out.append(FESC)
            else:
                out.append(byte)
            escaped = False
        elif byte == FESC:
            escaped = True
        else:
            out.append(byte)
    return bytes(out)


def encode_kiss_frame(payload: bytes, command: int = DATA_COMMAND) -> bytes:
    return bytes([FEND, command & 0xFF]) + kiss_escape(payload) + bytes([FEND])


def iter_kiss_frames(buffer: bytearray):
    """
    Pop complete KISS frames from a mutable receive buffer.

    Yields the raw bytes between FEND markers, still escaped, including the
    command byte. Incomplete trailing data stays in the buffer.
    """
    while True:
        try:
            start = buffer.index(FEND)
        except ValueError:
            buffer.clear()
            return
        if start:
            del buffer[:start]
        try:
            end = buffer.index(FEND, 1)
        except ValueError:
            return
        frame = bytes(buffer[1:end])
        del buffer[: end + 1]
        if frame:
            yield frame


def payload_from_kiss_frame(frame: bytes) -> bytes | None:
    """Return the data payload, or None for a non-data command."""
    if not frame:
        return None
    command = frame[0]
    if (command & 0x0F) != DATA_COMMAND:
        return None
    return kiss_unescape(frame[1:])
