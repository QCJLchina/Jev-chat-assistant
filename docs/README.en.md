# Jev Chat Assistant (Windows PC)

[简体中文](../README.md) | [English](README.en.md) | [Français](README.fr.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

**Version: v1.4.0**

## v1.4.0 new features

- **Review before analysis**: Edit text, speakers and message order, add or delete messages, restore recognition or capture again. Analysis services run only after confirmation. Original input and initial supplements remain subject to transaction checks; drafts stay in memory.
- **Reply goals**: General reply, politely decline, clarify misunderstanding, end topic or ease conflict. Combine with length, tone and language. Goals are session-only and frozen when analysis is confirmed.
- **Rewrite individual replies**: Make a candidate shorter, more natural or more tactful; undo, cancel and retry. Changes clear old scores; rank again manually. Replies remain copy-only.

This project is a Windows PC re-development based on the judgment question bank and analysis flow of the open-source project https://github.com/Liyucheng1997/332_lab-jev-chat.

The Windows version lets you select a chat area on your desktop, recognizes the visible text with local OCR, and analyzes the conversation through Jev. You can also configure a reply model to generate three candidate replies, which Jev then ranks. Candidate replies are for viewing and copying only — they are never filled in or sent automatically.

[Download v1.4.0 for Windows](https://github.com/QCJLchina/Jev-chat-assistant/releases/tag/v1.4.0)

## v1.3.1 new features

- **Full context**: Analyze all messages by default, or explicitly select the last 10, 20, or 50. Prior conversation is prepended to the current messages before selection. Selected message bodies and background notes together must fit within 20,000 characters; reduce the range or shorten the content if needed, without silent truncation. Statistics show total messages, used messages, characters, the selected limit, and omitted messages. Transaction checks cover the complete input, including omitted messages, prior conversation, and background notes.
- **Prior conversation and background**: Prior text accepts `我：` / `对方：` and `me:` / `other:`. Background provides context rather than a chat message. Supplements stay in memory only, can be cleared manually, and are cleared when switching the bound target window or exiting the app. Contact changes inside the same window cannot be detected automatically; clear supplements yourself before switching conversations.
- **Follow the window**: New installations default to Follow window. Existing fixed areas retain Fixed screen area mode, even after reselection; choose Follow window before reselecting to enable following. In Follow window mode, moving the window moves the selection. Following across displays with different DPI works only while window geometry remains consistent. A size change exceeding 2 DIP requires reselection. After the target closes or the app restarts, confirm a candidate window before restoring the binding.
- **Capture on demand**: OCR runs when you click analyze, with no continuous background OCR or background capture of minimized or occluded windows. Restore the window and make the chat area visible first.

## Released v1.3.0 features (historical behavior)

- **Paste conversation text**: No area selection needed. Supports `我：` / `对方：` and `me:` / `other:` prefixes, with case-insensitive English prefixes and either colon style. Input is limited to 20,000 characters; analysis uses the last 10 messages, while transaction safety checks cover the full input.
- **Cancel and retry from checkpoints**: Keep completed judgments and candidates and resume the first unfinished stage; candidates remain copyable if ranking fails. Retries reuse the original task’s frozen configuration, including relationship notes, model, and reply preferences. Start a new analysis to apply changed settings. Cancellation stops later stages and ignores stale results, but an active HTTP request may still finish or time out.
- **Reply preferences**: Save global length, tone, and reply-language preferences, with temporary session overrides on the home page. Reply language is separate from interface language and supports Simplified Chinese, English, French, Russian, Japanese, and Korean, plus a “follow interface language” option. Chat text and checkpoints stay in memory; no local chat history is saved.

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

Simplified Chinese, English, Français, Русский, 日本語, and 한국어 are supported. Pick the "Interface language" on the settings page and it is saved and applied immediately — no restart, and no other unsaved settings are submitted. New users default to the Windows interface language, falling back to English for unsupported system languages; existing users keep Simplified Chinese after upgrading.

This localization covers the interface, prompts, and analysis result labels. Chat text and user-written relationship notes are not translated, and OCR remains unchanged. Candidate replies use the separate reply-language preference: Simplified Chinese, English, French, Russian, Japanese, or Korean, or follow the interface language.

## Usage

1. Open the chat window you want assistance with and enter a regular text chat.
2. Click "Select conversation area" and drag to cover the chat messages.
3. Click "Capture and review", correct the messages and select a reply goal, then click "Confirm and analyze".
4. Review and copy a suitable candidate, then decide yourself whether to send it.

The program never reads chat databases, touches chat input boxes, or sends messages automatically. Transfers, red packets, payment requests, and other transaction content are blocked by the safety checks. Images, voice messages, and quoted cards cannot yet be reliably reconstructed.

## Building

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

Build output: `dist\Jev对话助手\Jev对话助手.exe`. PyInstaller bundles the Vue assets, OCR models, and Python runtime, and also builds the update helper `update_helper.exe` (ship it next to the main executable). Keep the `_internal` folder next to it when distributing; the target computer also needs the Microsoft Edge WebView2 Runtime.

## In-app updates

The app can fetch updates on its own. A few seconds after launch it silently checks GitHub Releases; when a new version exists, a banner appears at the top of the home page, and you can also check manually under "Version & updates" in settings. The check only queries `api.github.com` for the latest version number — no chat content is ever sent.

Once you confirm, the app downloads the release archive in the background (with progress and cancel support), verifies its SHA256 (enabled when the release ships a `SHA256SUMS.txt`; otherwise falls back to a size check) and extracts it to a staging folder. Clicking "Restart & install update" exits the main program; the helper `update_helper.exe` atomically swaps the install directory and restarts the new version. If any step fails, it rolls back to the old version. Settings and data live in `%APPDATA%` and are unaffected by updates.

## Privacy

- OCR runs locally; after you click analyze, the recognized chat text is sent to TypeSafe Jev.
- With a reply model enabled, the conversation text and the Jev judgment are sent to the chosen model service to generate candidate replies.
- API Keys are stored in Windows Credential Manager; `%APPDATA%\JevChatAssistant\settings.json` keeps only non-secret settings.
- Model listing and connection tests never send chat content.

For configuration, usage details, and limitations, see [`windows/README.md`](../windows/README.md).
