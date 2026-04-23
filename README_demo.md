# Demo Shell Quick Start

## What this is
A lightweight **demo shell** for recording and presentation.
It visualizes the current runtime capability chain:

`mission/action -> policy_decision_event -> adapter -> action_result -> replay`

> It is **not** a production GUI and **not** a real PX4/MAVLink integration.

## Run locally
From repo root:

```bash
python -m http.server 8000
```

Open:

- `http://localhost:8000/demo/`

## Built-in scenarios
- **ALLOW**: accepted path
- **DENY**: policy blocked path
- **REQUIRE_CONFIRM**: waiting confirmation path

## Recording tip
Use `docs/demo_video_script.md` as the 2-minute narration guide.
