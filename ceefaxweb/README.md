## Ceefax Station web tracker

This folder is the source for the **official** public site at [ceefaxstation.com](https://ceefaxstation.com).

**Do not run your own copy of this website.** Station users should:

1. Use the live map at [ceefaxstation.com](https://ceefaxstation.com)
2. Upload logs with `ceefaxstation upload` (no extra config)

Shared teletext pages are also served from that site so stations do not need their own API keys.

Owner-only: the ingest API can email you on new station uploads when Resend env vars are set
(`RESEND_API_KEY`, `CEEFAXWEB_NOTIFY_TO`, `CEEFAXWEB_NOTIFY_FROM`). See the root README developer notes.
