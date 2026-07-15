# RelayAI

## Vision

RelayAI is an open-source, privacy-first, AI-powered voice productivity platform.

The goal is to build the best open-source alternative to Wispr Flow while remaining completely independent of any proprietary application.

RelayAI should own the complete voice pipeline:

Microphone
→ Voice Activity Detection
→ Speech-to-Text
→ AI Refinement
→ Text Insertion
→ Workflow Automation

Users should never need Wispr Flow installed.

The long-term vision is not simply voice dictation.

RelayAI should become an extensible Voice AI platform capable of interacting with applications, LLMs, MCP servers, local models, and cloud services.

---

# Philosophy

Voice should feel invisible.

The user should think.

RelayAI handles:

- transcription
- formatting
- grammar
- context
- automation

The interaction should feel as fast as typing.

---

# Product Goals

Primary goals:

- Open Source
- Cross-platform
- Local-first
- Extensible
- Privacy-friendly
- Provider agnostic
- Beautiful UX
- Developer friendly

Secondary goals:

- Voice commands
- Meeting mode
- Plugin ecosystem
- AI Agents
- MCP integration

---

# MVP

The first release should include:

- Global hotkey
- Push-to-talk
- Toggle recording
- Streaming transcription
- Raw transcript
- AI refinement
- Automatic text insertion
- Clipboard fallback
- Transcript history
- Settings UI

---

# Supported Providers

RelayAI should never be tightly coupled to one provider.

Speech providers:

- faster-whisper
- whisper.cpp
- OpenAI
- Groq
- Deepgram
- ElevenLabs
- AssemblyAI

LLM Providers:

- OpenAI
- Anthropic
- Gemini
- Ollama
- LM Studio
- vLLM
- OpenRouter
- Any OpenAI-compatible endpoint

Every provider should implement a common interface.

---

# Core Architecture

relay-core

Contains:

- Audio capture
- Recording
- Streaming
- VAD
- STT abstraction
- LLM abstraction
- Clipboard
- Text insertion
- Settings
- Plugin API

Desktop Application

Contains:

- UI
- Tray/Menu Bar
- Settings
- Shortcuts
- History
- Notifications

---

# Design Principles

Everything should be modular.

Avoid singleton classes.

Dependency injection preferred.

Every provider is replaceable.

Every workflow should be configurable.

No business logic inside UI.

UI only renders state.

---

# UX Principles

Zero-friction.

Recording should start instantly.

Latency should be minimal.

AI refinement should never feel blocking.

The user should remain in flow.

---

# Future Features

Voice macros

Voice snippets

Application-specific prompts

Context awareness

Meeting recording

Speaker diarization

Realtime streaming

Voice commands

Plugin marketplace

MCP tools

Clipboard history

Custom dictionaries

Domain-specific vocabularies

Personal writing style

Agent mode

Coding mode

---

# Technology Stack

Desktop:

Tauri
React
TypeScript

Backend:

Python

Future:

Rust where performance matters.

Storage:

SQLite

Configuration:

JSON/TOML

Secrets:

OS Keychain

---

# Repository Rules

Never hardcode providers.

Never hardcode prompts.

Never hardcode endpoints.

Everything configurable.

Avoid unnecessary dependencies.

Keep startup fast.

Prefer async.

Strong typing everywhere.

---

# Success Metric

The fastest way to turn human speech into polished text on any computer.
