import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class AudioConfig:
    sample_rate: int
    symbol_rate: int
    frequency_mark: float
    frequency_space: float
    amplitude: float
    pre_tone_ms: int
    post_tone_ms: int
    vox_hold_ms: int
    output: str


@dataclass
class Ax25Config:
    enabled: bool
    callsign: str
    kiss_port: str
    baud_rate: int
    dest_callsign: str
    max_info_bytes: int
    preamble_flags: int
    inter_frame_flags: int
    postamble_flags: int
    loops_per_hour: int
    refresh_lead_seconds: int


@dataclass
class CarouselConfig:
    page_duration_ms: int
    loop_delay_ms: int


@dataclass
class GeneralConfig:
    mode: str
    page_dir: str
    log_level: str
    output_dir: str


@dataclass
class RadioConfig:
    band: str


@dataclass
class HfConfig:
    mode: str
    kiss_host: str
    kiss_port: int
    control_port: int
    max_frame_bytes: int
    loops_per_hour: int


@dataclass
class AppConfig:
    general: GeneralConfig
    audio: AudioConfig
    ax25: Ax25Config
    carousel: CarouselConfig
    radio: RadioConfig
    hf: HfConfig


VALID_BANDS = ("vhf", "hf")
VALID_HF_MODES = ("RDM-600S", "RDM-300S")


def _require_choice(value: str, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        choices = ", ".join(allowed)
        raise ValueError(f"{label} must be one of {choices}, got {value!r}")
    return value


def _upsert_toml_assignment(text: str, section: str, key: str, literal: str) -> str:
    """Set key = literal inside [section], appending the section when it is missing."""
    lines = text.splitlines()
    header = f"[{section}]"
    start = None
    for index, line in enumerate(lines):
        if line.strip() == header:
            start = index
            break
    assignment = f"{key} = {literal}"
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([header, assignment])
    else:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if lines[index].strip().startswith("[") and lines[index].strip().endswith("]"):
                end = index
                break
        replaced = False
        prefix = f"{key}"
        for index in range(start + 1, end):
            stripped = lines[index].strip()
            if stripped.startswith(prefix) and "=" in stripped.split("#", 1)[0]:
                name = stripped.split("=", 1)[0].strip()
                if name == key:
                    lines[index] = assignment
                    replaced = True
                    break
        if not replaced:
            lines.insert(end, assignment)
    body = "\n".join(lines)
    if text.endswith("\n") or not text:
        body += "\n"
    return body


def save_link_settings(band: str, mode: str, path: str | None = None) -> None:
    """
    Write [radio] band and [hf] mode into the active config.toml.

    The viewer asks for these on every launch. Other keys in the file are left as they are.
    """
    from .paths import config_path

    band = _require_choice(str(band).strip().lower(), VALID_BANDS, "radio.band")
    mode = _require_choice(str(mode).strip(), VALID_HF_MODES, "hf.mode")
    target = config_path() if path is None else Path(path)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    updated = _upsert_toml_assignment(existing, "radio", "band", f'"{band}"')
    updated = _upsert_toml_assignment(updated, "hf", "mode", f'"{mode}"')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated, encoding="utf-8")


def load_config(path: str | None = None) -> AppConfig:
    from .paths import ceefax_root, config_path, pages_dir, uses_user_data

    package_ceefax = Path(__file__).resolve().parent.parent

    if path is None:
        config_path_obj = config_path()
        if not config_path_obj.exists():
            for candidate in (
                package_ceefax / "config.toml",
                package_ceefax / "config.default.toml",
            ):
                if candidate.exists():
                    config_path_obj = candidate
                    break
    else:
        config_path_obj = Path(path)
        if not config_path_obj.exists() and path == "config.toml":
            for candidate in (
                package_ceefax / "config.toml",
                package_ceefax / "config.default.toml",
            ):
                if candidate.exists():
                    config_path_obj = candidate
                    break

    if not config_path_obj.exists():
        print(f"Config file not found: {config_path_obj}", file=sys.stderr)
        sys.exit(1)

    with open(config_path_obj, "rb") as f:
        data = tomllib.load(f)

    def get(section: str, key: str, default=None):
        return data.get(section, {}).get(key, default)

    base_dir = config_path_obj.parent

    def resolve_path(p: str) -> str:
        pp = Path(p)
        if pp.is_absolute():
            return str(pp)
        return str((base_dir / pp).resolve())

    # Always use the writable pages directory. Relative config paths still work
    # for output_dir under the same data root.
    page_dir_value = str(pages_dir())
    output_raw = str(get("general", "output_dir", "out"))
    if uses_user_data() and not Path(output_raw).is_absolute():
        output_dir_value = str((ceefax_root() / output_raw).resolve())
    else:
        output_dir_value = resolve_path(output_raw)

    general = GeneralConfig(
        mode=get("general", "mode", "audio"),
        page_dir=page_dir_value,
        log_level=get("general", "log_level", "INFO"),
        output_dir=output_dir_value,
    )

    audio = AudioConfig(
        sample_rate=int(get("audio", "sample_rate", 48000)),
        symbol_rate=int(get("audio", "symbol_rate", 1200)),
        frequency_mark=float(get("audio", "frequency_mark", 1200.0)),
        frequency_space=float(get("audio", "frequency_space", 2200.0)),
        amplitude=float(get("audio", "amplitude", 0.5)),
        pre_tone_ms=int(get("audio", "pre_tone_ms", 300)),
        post_tone_ms=int(get("audio", "post_tone_ms", 300)),
        vox_hold_ms=int(get("audio", "vox_hold_ms", 250)),
        output=str(get("audio", "output", "files")),
    )

    ax25 = Ax25Config(
        enabled=bool(get("ax25", "enabled", False)),
        callsign=str(get("ax25", "callsign", "N0CALL-1")),
        kiss_port=str(get("ax25", "kiss_port", "/dev/ttyUSB0")),
        baud_rate=int(get("ax25", "baud_rate", 9600)),
        dest_callsign=str(get("ax25", "dest_callsign", "CEEFAX")),
        max_info_bytes=int(get("ax25", "max_info_bytes", 240)),
        preamble_flags=int(get("ax25", "preamble_flags", 150)),
        inter_frame_flags=int(get("ax25", "inter_frame_flags", 2)),
        postamble_flags=int(get("ax25", "postamble_flags", 20)),
        loops_per_hour=int(get("ax25", "loops_per_hour", 3)),
        refresh_lead_seconds=int(get("ax25", "refresh_lead_seconds", 180)),
    )

    carousel = CarouselConfig(
        page_duration_ms=int(get("carousel", "page_duration_ms", 1500)),
        loop_delay_ms=int(get("carousel", "loop_delay_ms", 200)),
    )

    # Band and HF mode are the only validated fields. Everything else stays permissive.
    band = _require_choice(str(get("radio", "band", "vhf")).strip().lower(), VALID_BANDS, "radio.band")
    hf_mode = _require_choice(str(get("hf", "mode", "RDM-600S")).strip(), VALID_HF_MODES, "hf.mode")
    radio = RadioConfig(band=band)
    hf = HfConfig(
        mode=hf_mode,
        kiss_host=str(get("hf", "kiss_host", "127.0.0.1")),
        kiss_port=int(get("hf", "kiss_port", 8001)),
        control_port=int(get("hf", "control_port", 8073)),
        max_frame_bytes=int(get("hf", "max_frame_bytes", 170)),
        loops_per_hour=int(get("hf", "loops_per_hour", 1)),
    )

    return AppConfig(
        general=general,
        audio=audio,
        ax25=ax25,
        carousel=carousel,
        radio=radio,
        hf=hf,
    )
