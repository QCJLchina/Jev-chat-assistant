# Jev 对话助手（Windows PC 版）

**版本：v1.0.0**

本项目是基于开源项目https://github.com/Liyucheng1997/332_lab-jev-chat 的判断题库与分析流程进行的 Windows PC 端再开发。

Windows 版可框选桌面上的聊天区域，使用 UI Automation 与本地 OCR 识别可见文字，通过 Jev 分析对话；也可配置回复模型生成三条候选回复，再由 Jev 排序。候选回复只供查看和复制，不会自动填入或发送。

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

## 使用

1. 打开要辅助的聊天窗口，进入普通文字聊天。
2. 点击“框选对话区域”，拖动选择聊天消息范围。
3. 点击“分析当前选区”，查看 Jev 判断和候选回复。
4. 检查并复制合适的候选内容，再自行决定是否发送。

程序不会读取聊天数据库、操作聊天输入框或自动发送消息。转账、红包、收款和支付等交易内容会被安全检查拦截。图片、语音及引用卡片中的内容目前无法可靠还原。

## 构建

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

构建产物：`dist\Jev对话助手\Jev对话助手.exe`。分发时请保留其旁边的 `_internal` 目录；目标电脑也需要安装 Microsoft Edge WebView2 Runtime。

## 隐私

- OCR 在本机执行；点击分析后，识别出的聊天文本会发送给 TypeSafe Jev。
- 启用回复模型后，对话文本和 Jev 判断会发送给所选模型服务生成候选回复。
- API Key 保存在 Windows 凭据管理器；`%APPDATA%\JevChatAssistant\settings.json` 仅保存非机密设置。
- 模型列表和连接测试不会发送聊天内容。

更多配置、使用说明与限制见 [`windows/README.md`](windows/README.md)。
