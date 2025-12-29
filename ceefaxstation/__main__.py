from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run_module(mod: str, argv: list[str]) -> int:
    """
    Run a Python module as a subprocess.

    We do this for the curses viewer so it owns the terminal cleanly.
    """
    cmd = [sys.executable, "-m", mod, *argv]
    return subprocess.call(cmd)


def _refresh_pages(
    *,
    callsign: str | None,
    frequency: str | None,
    location: str | None,
    auto_location: bool,
) -> None:
    from ceefax.src.update_all import prime_user_settings, update_all

    loc_tuple = None
    if location:
        # Accept "Frome,GB" and display-name defaults to the first segment.
        name = location.split(",", 1)[0].strip() or location.strip()
        loc_tuple = (name, location.strip())

    prime_user_settings(
        callsign=(callsign.strip().upper() if callsign else None),
        frequency=(frequency.strip() if frequency is not None else None),
        location=loc_tuple,
        auto_location=auto_location,
    )
    update_all()


def _tx_now(
    *,
    refresh: bool,
    callsign: str | None,
    frequency: str | None,
    location: str | None,
    auto_location: bool,
    carousel_loops: int | None,
    play: bool,
    play_loops: int,
    play_device: str | None,
    play_player: str | None,
) -> int:
    from ceefax.src.ax25_audio import build_ax25_audio_plan, write_ax25_audio_wav_and_or_stdout
    from ceefax.src.compiler import load_all_pages
    from ceefax.src.config import load_config
    from ceefax.src.playback import play_wav_file

    cfg = load_config(str(_repo_root() / "ceefax" / "config.toml"))

    if refresh:
        _refresh_pages(
            callsign=callsign or cfg.ax25.callsign,
            frequency=frequency if frequency is not None else "",
            location=location,
            auto_location=auto_location,
        )

    pages = load_all_pages(cfg.general.page_dir)
    if not pages:
        print("No pages found. Check ceefax/config.toml [general].page_dir.", file=sys.stderr)
        return 2

    src = (callsign or cfg.ax25.callsign).strip()
    loops_in_wav = cfg.ax25.loops_per_hour if carousel_loops is None else int(carousel_loops)
    plan = build_ax25_audio_plan(
        pages=pages,
        loops=max(1, loops_in_wav),
        dest_callsign=cfg.ax25.dest_callsign,
        src_callsign=src,
        max_info_bytes=cfg.ax25.max_info_bytes,
    )
    wav = write_ax25_audio_wav_and_or_stdout(
        plan=plan,
        sample_rate=cfg.audio.sample_rate,
        symbol_rate=cfg.audio.symbol_rate,
        frequency_mark=cfg.audio.frequency_mark,
        frequency_space=cfg.audio.frequency_space,
        amplitude=cfg.audio.amplitude,
        preamble_flags=cfg.ax25.preamble_flags,
        inter_frame_flags=cfg.ax25.inter_frame_flags,
        postamble_flags=cfg.ax25.postamble_flags,
        output_dir=cfg.general.output_dir,
        output_mode=cfg.audio.output,
    )

    print(f"WAV: {wav}")
    print(f"TX_ID: {plan.tx_id}")

    if play:
        try:
            play_wav_file(
                wav,
                loops=max(1, int(play_loops)),
                device=play_device,
                player=play_player,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Playback failed: {exc}", file=sys.stderr)
            return 3

    return 0


def _tx_hourly(
    *,
    callsign: str | None,
    refresh_lead: int | None,
    carousel_loops: int | None,
    play: bool,
    play_loops: int,
    play_device: str | None,
    play_player: str | None,
) -> int:
    from ceefax.src.config import load_config
    from ceefax.src.hourly_ax25_audio import run_hourly_ax25_audio

    cfg = load_config(str(_repo_root() / "ceefax" / "config.toml"))
    if callsign:
        cfg.ax25.callsign = callsign.strip().upper()

    run_hourly_ax25_audio(
        cfg,
        refresh_lead_seconds=refresh_lead,
        carousel_loops=carousel_loops,
        play=play,
        play_loops=play_loops,
        play_device=play_device,
        play_player=play_player,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        prog="ceefaxstation",
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Ceefax Station CLI\n\n"
            "Examples:\n"
            "  ceefaxstation debug --refresh --view\n"
            "  ceefaxstation rx latest --listener M7TJF\n"
            "  ceefaxstation rx live --device USB --listener M7TJF\n"
            "  ceefaxstation tx hourly --refresh-lead 300 --carousel-loops 3 --play --play-loops 2\n"
            "  ceefaxstation shell\n"
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ---- upload ----
    p_upload = sub.add_parser("upload", help="Upload logs_tx/logs_rx to a server for the public tracker website.")
    p_upload.add_argument(
        "--server",
        default="https://ceefaxstation.com",
        help="Server base URL (default: https://ceefaxstation.com). Use http://127.0.0.1:8088 for local testing.",
    )
    p_upload.add_argument("--token", default=None, help="Upload token (optional; required if server enforces).")
    p_upload.add_argument("--callsign", default=None, help="Uploader callsign (defaults to ceefax/radio_config.json).")
    p_upload.add_argument("--grid", default=None, help="Uploader Maidenhead grid (e.g. IO91wm) (defaults to ceefax/radio_config.json).")
    p_upload.add_argument("--poll", type=float, default=2.0, help="Poll interval seconds (default 2.0).")
    p_upload.add_argument("--once", action="store_true", help="Upload current logs once and exit (no watching).")

    # ---- shell ----
    p_shell = sub.add_parser(
        "shell",
        help="Print the repo root path (useful for scripts / shortcuts).",
    )
    p_shell.add_argument(
        "--spawn",
        action="store_true",
        help="Spawn a new interactive shell in the repo root (best effort).",
    )

    # ---- debug ----
    p_debug = sub.add_parser("debug", help="Refresh feeds/pages and open the viewer (no signal processing).")
    p_debug.add_argument("--refresh", dest="refresh", action="store_true", default=True)
    p_debug.add_argument("--no-refresh", dest="refresh", action="store_false")
    p_debug.add_argument("--view", dest="view", action="store_true", default=True)
    p_debug.add_argument("--no-view", dest="view", action="store_false")
    p_debug.add_argument("--callsign", default=None, help="Station callsign for header/pages (optional).")
    p_debug.add_argument("--frequency", default=None, help="Frequency text for header/pages (optional).")
    p_debug.add_argument(
        "--location",
        default=None,
        help="Location query for wttr.in (e.g. 'Frome,GB') (optional).",
    )
    p_debug.add_argument(
        "--no-auto-location",
        dest="auto_location",
        action="store_false",
        default=True,
        help="Disable automatic location detection for refresh runs.",
    )

    # ---- rx ----
    p_rx = sub.add_parser("rx", help="Receive/decode AX.25 audio and view pages.")
    rx_sub = p_rx.add_subparsers(dest="rx_cmd", required=True)

    p_rx_latest = rx_sub.add_parser("latest", help="Decode and view the most recent WAV in output_dir.")
    p_rx_latest.add_argument("--listener", default=None, help="Listener/receiver callsign (optional).")
    p_rx_latest.add_argument("--direwolf", default=None, help="Path to direwolf executable (optional).")
    p_rx_latest.add_argument("--dest", default="CEEFAX", help="AX.25 destination callsign filter.")

    p_rx_file = rx_sub.add_parser("file", help="Decode and view a specific WAV file.")
    p_rx_file.add_argument("wav", help="Path to WAV file.")
    p_rx_file.add_argument("--listener", default=None, help="Listener/receiver callsign (optional).")
    p_rx_file.add_argument("--direwolf", default=None, help="Path to direwolf executable (optional).")
    p_rx_file.add_argument("--dest", default="CEEFAX", help="AX.25 destination callsign filter.")

    p_rx_live = rx_sub.add_parser("live", help="Decode live audio from a sound device via Dire Wolf.")
    p_rx_live.add_argument("--listener", default=None, help="Listener/receiver callsign (optional).")
    p_rx_live.add_argument("--direwolf", default=None, help="Path to direwolf executable (optional).")
    p_rx_live.add_argument("--direwolf-config", default=None, help="Path to direwolf.conf (optional).")
    p_rx_live.add_argument("--device", default=None, help="Dire Wolf ADEVICE string/substring (optional).")
    p_rx_live.add_argument("--dest", default="CEEFAX", help="AX.25 destination callsign filter.")
    p_rx_live.add_argument("--sample-rate", type=int, default=48000, help="Sample rate for Dire Wolf (-r).")
    p_rx_live.add_argument("--baud", type=int, default=1200, help="Baud rate for Dire Wolf (-B).")

    # ---- tx ----
    p_tx = sub.add_parser("tx", help="Transmit/generate AX.25 audio.")
    tx_sub = p_tx.add_subparsers(dest="tx_cmd", required=True)

    p_tx_hourly = tx_sub.add_parser(
        "hourly",
        help="Hourly scheduler (refresh before :00, generate WAV, optionally play loops on the hour).",
    )
    p_tx_hourly.add_argument("--callsign", default=None, help="AX.25 source callsign (optional).")
    p_tx_hourly.add_argument(
        "--refresh-lead",
        type=int,
        default=300,
        help="Seconds before the hour to refresh feeds/pages (default: 300).",
    )
    p_tx_hourly.add_argument(
        "--carousel-loops",
        type=int,
        default=3,
        help="How many times to repeat the carousel inside the generated WAV (default: 3).",
    )
    p_tx_hourly.add_argument("--play", dest="play", action="store_true", default=True)
    p_tx_hourly.add_argument("--no-play", dest="play", action="store_false")
    p_tx_hourly.add_argument(
        "--play-loops",
        type=int,
        default=1,
        help="How many times to play the generated WAV on the hour (default: 1).",
    )
    p_tx_hourly.add_argument(
        "--play-device",
        default=None,
        help="Playback device (Linux aplay -D <device>) (optional).",
    )
    p_tx_hourly.add_argument(
        "--play-player",
        default=None,
        help="Override player executable (optional).",
    )

    p_tx_now = tx_sub.add_parser(
        "now",
        help="Refresh (optional), generate a single WAV now, optionally play it.",
    )
    p_tx_now.add_argument("--refresh", dest="refresh", action="store_true", default=True)
    p_tx_now.add_argument("--no-refresh", dest="refresh", action="store_false")
    p_tx_now.add_argument("--callsign", default=None, help="AX.25 source callsign (optional).")
    p_tx_now.add_argument("--frequency", default=None, help="Frequency text for header/pages (optional).")
    p_tx_now.add_argument(
        "--location",
        default=None,
        help="Location query for wttr.in (e.g. 'Frome,GB') (optional).",
    )
    p_tx_now.add_argument(
        "--no-auto-location",
        dest="auto_location",
        action="store_false",
        default=True,
    )
    p_tx_now.add_argument(
        "--carousel-loops",
        type=int,
        default=3,
        help="How many times to repeat the carousel inside the generated WAV (default: 3).",
    )
    p_tx_now.add_argument("--play", dest="play", action="store_true", default=True)
    p_tx_now.add_argument("--no-play", dest="play", action="store_false")
    p_tx_now.add_argument("--play-loops", type=int, default=1)
    p_tx_now.add_argument("--play-device", default=None)
    p_tx_now.add_argument("--play-player", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "upload":
        from ceefaxstation.uploader import upload_logs

        upload_logs(
            server_url=str(args.server),
            token=args.token,
            uploader_callsign=(str(args.callsign).strip().upper() if args.callsign else None),
            uploader_grid=(str(args.grid).strip().upper() if args.grid else None),
            poll_seconds=float(args.poll),
            once=bool(args.once),
        )
        return 0

    if args.cmd == "shell":
        root = str(_repo_root())
        print(root)
        if getattr(args, "spawn", False):
            # Best-effort: spawn a child shell rooted at the repo.
            if sys.platform.startswith("win"):
                return subprocess.call(["powershell", "-NoExit", "-Command", f"Set-Location '{root}'"])
            # Unix-ish:
            return subprocess.call(["bash", "-lc", f"cd '{root}' && exec \"$SHELL\" -i"])
        return 0

    if args.cmd == "debug":
        if args.refresh:
            _refresh_pages(
                callsign=args.callsign,
                frequency=args.frequency,
                location=args.location,
                auto_location=bool(args.auto_location),
            )
        if args.view:
            return _run_module("ceefax.src.viewer", [])
        return 0

    if args.cmd == "rx":
        if args.rx_cmd == "latest":
            argv2 = ["--rx-latest", "--dest", args.dest]
            if args.listener:
                argv2 += ["--listener", args.listener]
            if args.direwolf:
                argv2 += ["--direwolf", args.direwolf]
            return _run_module("ceefax.src.viewer", argv2)

        if args.rx_cmd == "file":
            argv2 = ["--rx-wav", args.wav, "--dest", args.dest]
            if args.listener:
                argv2 += ["--listener", args.listener]
            if args.direwolf:
                argv2 += ["--direwolf", args.direwolf]
            return _run_module("ceefax.src.viewer", argv2)

        if args.rx_cmd == "live":
            argv2 = ["--rx-live", "--dest", args.dest]
            if args.listener:
                argv2 += ["--listener", args.listener]
            if args.direwolf:
                argv2 += ["--direwolf", args.direwolf]
            if args.direwolf_config:
                argv2 += ["--direwolf-config", args.direwolf_config]
            if args.device:
                argv2 += ["--device", args.device]
            argv2 += ["--sample-rate", str(int(args.sample_rate)), "--baud", str(int(args.baud))]
            return _run_module("ceefax.src.viewer", argv2)

        return 2

    if args.cmd == "tx":
        if args.tx_cmd == "hourly":
            return _tx_hourly(
                callsign=args.callsign,
                refresh_lead=int(args.refresh_lead),
                carousel_loops=int(args.carousel_loops),
                play=bool(args.play),
                play_loops=int(args.play_loops),
                play_device=args.play_device,
                play_player=args.play_player,
            )

        if args.tx_cmd == "now":
            return _tx_now(
                refresh=bool(args.refresh),
                callsign=args.callsign,
                frequency=args.frequency,
                location=args.location,
                auto_location=bool(args.auto_location),
                carousel_loops=int(args.carousel_loops),
                play=bool(args.play),
                play_loops=int(args.play_loops),
                play_device=args.play_device,
                play_player=args.play_player,
            )

        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())


