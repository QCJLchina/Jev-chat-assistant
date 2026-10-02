# Jev 对话助手（Windows PC 版）

[简体中文](README.md) | [English](docs/README.en.md) | [Français](docs/README.fr.md) | [Русский](docs/README.ru.md) | [日本語](docs/README.ja.md)

**版本：v1.3.0**

本项目是基于开源项目https://github.com/Liyucheng1997/332_lab-jev-chat 的判断题库与分析流程进行的 Windows PC 端再开发。

Windows 版可框选桌面上的聊天区域，使用本地 OCR 识别可见文字，通过 Jev 分析对话；也可配置回复模型生成三条候选回复，再由 Jev 排序。候选回复只供查看和复制，不会自动填入或发送。

## v1.3.0 新功能

- **粘贴文本分析**：无需框选，支持 `我：`／`对方：` 和 `me:`／`other:`。最多 20,000 个字符，分析最后 10 条消息，交易内容检查覆盖完整输入。
- **取消与分阶段重试**：保留已完成的判断和候选，失败时只重试未完成阶段；排序失败仍可复制候选。取消会停止后续流程，但不能撤销已经发送的服务端请求。
- **回复偏好**：选择简短或详细、自然／正式／委婉／直接，以及六种回复语言或跟随界面语言；支持全局默认与不落盘的本次覆盖。
- **任务隔离**：开始分析时冻结配置，旧请求结果不会覆盖新任务；聊天和阶段缓存仅保留在内存。

[下载 v1.3.0 Windows 版](https://github.com/QCJLchina/Jev-chat-assistant/releases/tag/v1.3.0) · [完整更新日志](windows/CHANGELOG.md)

## 环境要求

- Windows 10/11（x64）
- Microsoft Edge WebView2 Runtime
- 源码运行或构建需要 Python 3.12、Node.js 20+ 和 npm
- 首次使用需要 TypeSafe / Jev API Key；回复模型 API Key 可选

## 安装与启动

在仓库根目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install.ps1
powershell -ExecutionPolicy Bypass -File .\windows\start.ps1
```

首次使用时，在设置页填写 Jev API Key。需要生成候选回复时，再添加回复模型配置、API Key 和模型名称。

## 界面语言

支持简体中文、English、Français、Русский、日本語、한국어（韩文／朝鲜语）。在设置页选择“界面语言”后立即保存并切换，无需重启，也不会提交其他未保存的设置。新用户默认跟随 Windows 界面语言（包含韩文），不支持的系统语言回退英语；旧版用户升级后保持简体中文。

界面支持多语言提示和分析结果标签；聊天原文与用户填写的关系说明保持原内容。OCR 能力沿用现有版本，回复语言可在设置中单独指定或跟随界面语言。

## 使用

1. 打开要辅助的聊天窗口，进入普通文字聊天。
2. 点击“框选对话区域”，拖动选择聊天消息范围。
3. 点击“分析当前选区”，查看 Jev 判断和候选回复。
4. 检查并复制合适的候选内容，再自行决定是否发送。

也可在首页切换“粘贴文本”直接分析，支持 `我：`／`对方：` 和 `me:`／`other:` 前缀。设置页可保存回复长度、风格和语言，首页可临时覆盖。分析中可取消，失败后可按阶段重试，排序失败仍可复制候选。

程序不会读取聊天数据库、操作聊天输入框或自动发送消息。转账、红包、收款和支付等交易内容会被安全检查拦截。图片、语音及引用卡片中的内容目前无法可靠还原。

## 构建

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

构建产物：`dist\Jev对话助手\Jev对话助手.exe`。分发时请保留其旁边的 `_internal` 目录；目标电脑也需要安装 Microsoft Edge WebView2 Runtime。

前端已构建时，可加 `-SkipFrontendBuild` 复用 `windows/frontend/dist`，跳过 `npm ci` 与 `npm run build`。

## 发版流程

流水线配置在 `.github/workflows/ci.yml`，`main` 分支推送、`v*.*.*` 标签推送、PR 和手动触发都走这一个工作流。

1. 同步 `windows/jev_windows/__init__.py` 的 `__version__`、`windows/frontend/package.json` 与 lock 文件的版本，以及各语言 README，并在 `windows/CHANGELOG.md` 中补上对应版本的章节，提交并推送：

```powershell
git push origin main
```

这一步只运行检查（前端构建 + `pytest`），不会发版。

2. 打标签并单独推送标签：

```powershell
git tag v1.3.0
git push origin v1.3.0
```

这一步运行同一条流水线，在检查通过后构建并创建或更新 GitHub Release。**请分两次推送，不要用 `git push --follow-tags`**：一次推送同时包含分支和标签时，GitHub 会发两个 push 事件，Actions 里会出现两条运行记录。仅推送标签时只产生一条记录。

## 隐私

- OCR 在本机执行；点击分析后，识别出的聊天文本会发送给 TypeSafe Jev。
- 启用回复模型后，对话文本和 Jev 判断会发送给所选模型服务生成候选回复。
- 检查应用内更新时，仅向 GitHub 查询最新版本号，不发送任何聊天内容。
- API Key 保存在 Windows 凭据管理器；`%APPDATA%\JevChatAssistant\settings.json` 仅保存非机密设置。
- 模型列表和连接测试不会发送聊天内容。

更多配置、使用说明与限制见 [`windows/README.md`](windows/README.md)。
