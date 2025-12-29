from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def play_wav_file(
    wav_path: str,
    *,
    loops: int = 1,
    player: str | None = None,
    device: str | None = None,
) -> None:
    """
    Play a WAV file on the local machine, blocking until playback completes.

    This intentionally uses "system players" rather than adding new dependencies.

    - Linux: aplay (ALSA)
    - macOS: afplay
    - Windows: winsound (builtin)
    """
    wav_path = str(Path(wav_path))
    loops = max(1, int(loops))

    if sys.platform.startswith("win"):
        import winsound  # builtin on Windows

        for _ in range(loops):
            winsound.PlaySound(wav_path, winsound.SND_FILENAME)
        return

    # Prefer explicit player if provided.
    if player:
        for _ in range(loops):
            subprocess.run([player, wav_path], check=True)
        return

    # Auto-pick a sensible default player.
    if sys.platform == "darwin":
        if not shutil.which("afplay"):
            raise FileNotFoundError("No audio player found (expected: afplay)")
        for _ in range(loops):
            subprocess.run(["afplay", wav_path], check=True)
        return

    # Assume Linux / Unix.
    if not shutil.which("aplay"):
        raise FileNotFoundError("No audio player found (expected: aplay)")

    cmd_base = ["aplay", "-q"]
    if device:
        cmd_base += ["-D", device]
    for _ in range(loops):
        subprocess.run([*cmd_base, wav_path], check=True)


