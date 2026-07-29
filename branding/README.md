# Branding

Master logo assets for Ceefax Station.

| File | Use |
|------|-----|
| `logo.png` | Master artwork (opaque black background) |
| `logo-transparent.png` | Optional derived copy with black knocked out |
| `ceefaxstation.ico` | Windows EXE icon, installer wizard icon, Start Menu / desktop shortcuts |

Derived UI copies (transparent bg so they blend on `#0b0b0b` / GitHub):
`ceefaxweb/static/logo.png`, `screenshots/ceefax-station-logo.png`.

Refresh derived copies with:

```bash
python scripts/generate_readme_logo.py
```

Then rebuild the installer so the EXE picks up the updated `.ico`.
