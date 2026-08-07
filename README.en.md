# LLM Roleplay Chat + GPT-SoVITS TTS

**Languages:** [中文](README.md) · [日本語](README.ja.md)

A Gradio-based roleplay chat application that integrates an LLM (OpenAI-compatible API) with GPT-SoVITS voice synthesis.

> **v1.3.5 released** (2026-08-07) · [GitHub Releases](https://github.com/AngelinatheMellowWish/llm-tts-chat/releases)

## Features

- **LLM roleplay chat**: OpenAI-compatible APIs (DeepSeek/OpenAI/Qwen, etc.) with multi-provider failover
- **GPT-SoVITS TTS synthesis**: per-character voice cloning, long-text chunked synthesis, volume normalization
- **Multi-session management**: create / switch / delete / rename / export / import (zip)
- **Character system**: JSON config + portrait + reference audio + Lorebook world-knowledge base
- **Character card import**: auto-detects and imports TavernAI (PNG/JSON), RisuAI, Chub, and Character.AI cards (with avatar)
- **Character chat background** (v1.3.1): place a background image in the character folder (`background.png` or the `background` field in `character.json`); the chat-area background switches instantly when you select a character. Supports PNG/JPG/JPEG/WebP/GIF (animated), ≤200MB. Adjustable overlay opacity/color (auto light/dark or manual), global enable switch, upload with in-editor preview
- **Character avatar in chat header** (v1.3.5): a fixed header at the top-left of the chat window shows the current character's `portrait.png` avatar + name (does not scroll with messages or cover the chat background); falls back to a circular initial placeholder when no portrait exists; size can be switched between 128/256px from the sidebar and is persisted
- **Mobile responsive**: ≤900px auto-stacks into a vertical layout
- **Character editor**: WebUI form editing (personality / quirks / background / CoT / Lorebook / avatar)
- **Message favorites / search / stats**: star favorites, in-session search, global stats dashboard
- **Training result management**: one-click pack/archive of GPT-SoVITS training outputs (`gsv_training/`), intermediate cleanup, archive restore, auto training-complete detection, per-character voice linking
- **Long-term memory (RAG)**: per-character/global memory store that remembers user preferences and facts across sessions (rule-based extraction + optional LLM extraction)
- **Session recycle bin**: deleted sessions can be restored; 30-day cleanup reminder
- **Advanced settings**: performance / session-timeout / notification sound / proxy fully configurable; proxy injected as environment variables
- **Adjustable sidebar**: drag to resize (200–600px), one-click collapse/expand, width & state persisted
- **Per-session LLM provider**: each session can override its provider
- **Multilingual UI**: 中文 / 日本語 / English hot-switch
- **Themes**: light / dark + custom colors
- **Greeting flow**: new sessions auto-play the character's voice greeting
- **One-click launch**: `go-llm-tts.bat` starts both the GPT-SoVITS TTS API and the chat app (auto-detect, port skip, dual windows)
- **Error codes + step reports**: system-wide error codes (`[LLM-004]` etc.) + per-run reports (`logs/startup_report_*` / `run_report_*`, text + JSON dual format)
- **Usage guides**: "❓" help buttons on the main UI and the sidebar
- **Regenerate / message editing**: 🔄 regenerate the last AI reply (keeps the old version); ✏️ edit the last AI reply (with version history)
- **Auto backup**: on startup + scheduled (default every 24h) backups of sessions / characters / memories / config to `backup/`, keeping the last 3

## Requirements

- Windows 10/11
- GPT-SoVITS v2Pro (with the runtime Python environment configured)
- LLM API Key

## Installation

1. Run `install_deps.bat` to install dependencies (creates a venv)
2. Make sure GPT-SoVITS and `llm_tts_update` are in the **same parent directory** (one-click launch auto-detects the `GPT-SoVITS*` directory)
3. Run `go-llm-tts.bat` — automatically starts the GPT-SoVITS TTS API (api_v2.py) + the chat app (two windows)
4. On first launch, the configuration wizard asks for the GPT-SoVITS path, TTS API URL, and LLM config

> Note: `go-llm-tts.bat` auto-detects a sibling `GPT-SoVITS*` directory and starts its `api_v2.py` (skips if port 9880 is already in use); TTS loading takes ~30–90s and the app opens first. Startup steps and error codes are logged in `logs/startup_report_*.txt`.

## Usage

1. **Configuration wizard**: on first launch, fill in the GPT-SoVITS path, TTS API URL, and LLM provider (Base URL / API Key / model)
2. **Select a character**: pick one from the left sidebar dropdown; the preset voice model is applied automatically
3. **New session**: click "New Session"; the character greeting plays automatically
4. **Start chatting**: type a message and press Enter to send (Shift+Enter for a new line); replies are synthesized to voice automatically
5. **Character editor**: the left sidebar "Edit Character" panel lets you change personality / background / Lorebook and upload a portrait (or a chat background)
6. **Tools**: export/import sessions, search, stats dashboard
7. **Training management**: pick an experiment in the sidebar "Training Management" panel to preview/pack and clean intermediate files; restore archives with optional write-back to GPT-SoVITS; or use `train_pack.bat` (list / pack / cleanup / restore / list-archives / detect)
8. **UI language**: switch 中 / 日 / 英 from the top dropdown; switch light / dark theme

## FAQ

- **No TTS audio**: make sure GPT-SoVITS is ready and the status bar shows "🟢 TTS API online"; one-click launch starts api_v2.py automatically
- **API Key security**: API Keys are base64-encoded in `config.json`; do not share that file
- **Long replies cut off**: replies over 800 characters are automatically chunked for synthesis
- **Disk usage high after training**: pack and clean intermediate files in the "Training Management" panel or via `train_pack.bat pack <experiment> --cleanup` (only deleted after a successful pack)
- **Errors with codes**: UI errors look like `[LLM-004] No available LLM provider`; use the code to locate the issue; `logs/error.log` and `logs/run_report_*.txt` contain full steps and codes

## Changelog

See [CHANGELOG.md](CHANGELOG.md)

## Contributing

- Branch strategy: main (stable) + dev (development); direct commits to main are forbidden
- Commit convention: Conventional Commits
- Code style: PEP 8 + ruff (`ruff check app.py modules/ tests/`)
- Tests: `pytest tests/ -v` (203 unit/integration tests)
- Detailed development documents are confidential and maintained locally only; they are not published in this repository

## License

MIT
