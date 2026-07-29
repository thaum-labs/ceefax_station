# Branding

Master logo assets for Ceefax Station.

| File | Use |
|------|-----|
| `logo.png` | Website (`/static/logo.png`), README (`screenshots/readme-logo.png`) |
| `ceefaxstation.ico` | Windows EXE icon, installer wizard icon, Start Menu / desktop shortcuts |

Refresh derived copies with:

```bash
python scripts/generate_readme_logo.py
```

Then rebuild the installer so the EXE picks up the updated `.ico`.
