"""
Update page 900 with system information including detected platform.
"""
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import List

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import atomic_write_json


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def detect_platform() -> str:
    """
    Detect the operating system/platform.
    Returns a user-friendly platform name.
    """
    system = platform.system()
    machine = platform.machine()
    
    # Detect specific platforms
    if system == "Windows":
        return "Windows"
    elif system == "Linux":
        # Try to detect Raspberry Pi
        try:
            with open("/proc/cpuinfo", "r") as f:
                cpuinfo = f.read()
                if "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo:
                    return "Raspberry Pi"
        except (FileNotFoundError, PermissionError):
            pass
        
        # Check for other Linux variants
        try:
            with open("/etc/os-release", "r") as f:
                os_release = f.read()
                if "Raspbian" in os_release or "Raspberry Pi OS" in os_release:
                    return "Raspberry Pi"
                elif "Ubuntu" in os_release:
                    return "Linux (Ubuntu)"
                elif "Debian" in os_release:
                    return "Linux (Debian)"
                elif "Fedora" in os_release:
                    return "Linux (Fedora)"
                elif "Arch" in os_release:
                    return "Linux (Arch)"
        except (FileNotFoundError, PermissionError):
            pass
        
        return "Linux"
    elif system == "Darwin":
        return "Mac"
    elif system == "FreeBSD":
        return "FreeBSD"
    elif system == "OpenBSD":
        return "OpenBSD"
    elif system == "NetBSD":
        return "NetBSD"
    else:
        return f"{system} ({machine})"


def get_python_version() -> str:
    """Get Python version string."""
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def build_about_page() -> List[str]:
    """Build the About page with system information."""
    lines: List[str] = []
    lines.append(_pad("ABOUT CEEFAX STATION"))
    lines.append(_pad(""))
    
    platform_name = detect_platform()
    python_version = get_python_version()
    
    lines.append(_pad("Welcome to your Ceefax-style"))
    lines.append(_pad(f"information system running on"))
    lines.append(_pad(f"{platform_name}."))
    lines.append(_pad(""))
    
    sep = _pad("-" * PAGE_WIDTH)
    lines.append(_pad("SYSTEM INFO"))
    lines.append(sep)
    lines.append(_pad(f"Version: 1.0"))
    lines.append(_pad(f"Platform: {platform_name}"))
    lines.append(_pad(f"Python: {python_version}"))
    lines.append(_pad(f"Page Size: {PAGE_WIDTH}x{PAGE_HEIGHT} chars"))
    lines.append(_pad(""))
    
    lines.append(_pad("FEATURES"))
    lines.append(sep)
    lines.append(_pad("- Live weather from wttr.in"))
    lines.append(_pad("- News from BBC RSS feeds"))
    lines.append(_pad("- Football results and tables"))
    lines.append(_pad("- Exchange rates and travel info"))
    lines.append(_pad("- TV guide and film picks"))
    lines.append(_pad("- Lottery results"))
    lines.append(_pad("- PSK Reporter integration"))
    lines.append(_pad(""))
    
    lines.append(_pad("PAGES"))
    lines.append(sep)
    lines.append(_pad("Press 100 for the index of"))
    lines.append(_pad("all pages"))
    lines.append(_pad(""))
    
    lines.append(_pad("Have fun experimenting and"))
    lines.append(_pad("building new Ceefax pages"))
    lines.append(_pad("for your station!"))
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 900 with system information."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "900.json"
    
    content = build_about_page()
    
    page = {
        "page": "900",
        "title": "About Ceefax Station",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    
    platform_name = detect_platform()
    print(f"Updated {page_file} with system info (Platform: {platform_name})")


if __name__ == "__main__":
    main()

