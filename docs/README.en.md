# Jev Chat Assistant (Windows PC)

[简体中文](../README.md) | [English](README.en.md) | [Français](README.fr.md) | [Русский](README.ru.md) | [日本語](README.ja.md)

**Version: v1.1.1**

This project is a Windows PC re-development based on the judgment question bank and analysis flow of the open-source project https://github.com/Liyucheng1997/332_lab-jev-chat.

The Windows version lets you select a chat area on your desktop, recognizes the visible text with UI Automation and local OCR, and analyzes the conversation through Jev. You can also configure a reply model to generate three candidate replies, which Jev then ranks. Candidate replies are for viewing and copying only — they are never filled in or sent automatically.

## Requirements

- Windows 10/11 (x64)
- Microsoft Edge WebView2 Runtime
- Python 3.12, Node.js 20+, and npm for running from source or building
- A TypeSafe / Jev API Key on first use; a reply-model API Key is optional

## Installation and Launch

Open PowerShell in the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install.ps1
powershell -ExecutionPolicy Bypass -File .\windows\start.ps1
```

On first use, enter your Jev API Key on the settings page. To generate candidate replies, additionally add a reply model configuration, its API Key, and the model name.

## Interface Languages

Simplified Chinese, English, Français, Русский, and 日本語 are supported. Pick the "Interface language" on the settings page and it is saved and applied immediately — no restart, and no other unsaved settings are submitted. New users default to the Windows interface language, falling back to English for unsupported system languages; existing users keep Simplified Chinese after upgrading.

This localization covers the interface, prompts, and analysis result labels only. Chat text, user-written relationship notes, and candidate replies stay in their original language; OCR and Chinese reply generation remain unchanged from the previous version.

## Usage

1. Open the chat window you want assistance with and enter a regular text chat.
2. Click "Select conversation area" and drag to cover the chat messages.
3. Click "Analyze current selection" to see the Jev judgment and candidate replies.
4. Review and copy a suitable candidate, then decide yourself whether to send it.

The program never reads chat databases, touches chat input boxes, or sends messages automatically. Transfers, red packets, payment requests, and other transaction content are blocked by the safety checks. Images, voice messages, and quoted cards cannot yet be reliably reconstructed.

## Building

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

Build output: `dist\Jev对话助手\Jev对话助手.exe`. Keep the `_internal` folder next to it when distributing; the target computer also needs the Microsoft Edge WebView2 Runtime.

## Privacy

- OCR runs locally; after you click analyze, the recognized chat text is sent to TypeSafe Jev.
- With a reply model enabled, the conversation text and the Jev judgment are sent to the chosen model service to generate candidate replies.
- API Keys are stored in Windows Credential Manager; `%APPDATA%\JevChatAssistant\settings.json` keeps only non-secret settings.
- Model listing and connection tests never send chat content.

For configuration, usage details, and limitations, see [`windows/README.md`](../windows/README.md).
