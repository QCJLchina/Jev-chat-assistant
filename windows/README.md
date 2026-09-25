# Jev 对话助手（Windows）

Windows 桌面版使用 Vue 3 + TypeScript 界面和 pywebview 窗口，保留 Python 本地 OCR、Jev 判断、Windows 凭据管理器和本地安全检查。它可框选桌面上的任意聊天应用，不要求微信运行；不读取微信数据库，不注入微信进程，也不调用微信接口。

回复模型支持三种接口协议：`openai-chat`（`/chat/completions`）、`openai-responses`（`/responses`）和 `anthropic`（`/messages`）。Jev 会比较模型生成的三条候选回复，页面显示原始推荐概率，并在最高推荐项后标记红色“推荐”。不同服务可以保存为多套配置并切换。候选回复只能复制，不会自动填写或发送；交易相关对话仍会拒绝分析。

## 环境

- Windows 10/11（x64）
- Python 3.12、Node.js 20+ 和 npm（源码运行/构建）
- Microsoft Edge WebView2 Runtime
- TypeSafe / Jev API Key
- 可选的回复模型 API Key

## 安装和启动

在仓库根目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install.ps1
powershell -ExecutionPolicy Bypass -File .\windows\start.ps1
```

安装脚本会安装 Vue 依赖并构建前端，再安装 Python 依赖。首次使用时，在设置页保存 TypeSafe 控制台生成的 Jev API Key；在“回复模型”中添加模型配置、选择接口协议、填写接口地址和 API Key，并选择或手动输入模型名称。地址和密钥填写后会尝试读取模型列表；列表不可用时仍可手动输入。连接测试只发送固定的短提示，不携带聊天内容。

接口地址可填基础地址（如 `https://host/v1`），也可填完整接口地址。程序会按所选协议推导请求端点：OpenAI Chat 使用 Bearer 认证，OpenAI Responses 使用 Bearer 认证，Anthropic 使用 `x-api-key` 和 `anthropic-version` 请求头。

回复模型密钥按配置分别保存到 Windows 凭据管理器；Jev 密钥也保存在凭据管理器。设置文件 `%APPDATA%\JevChatAssistant\settings.json` 只存非机密配置。旧版 DeepSeek 模型、密钥、关系说明、白名单和聊天框选坐标会在升级后继续可用；旧 DeepSeek API 密钥首次读取时迁移到对应模型凭据项。

## 使用

### 界面语言（v1.1.1）

在设置页的“界面语言”中选择跟随系统、简体中文、English、Français、Русский 或 日本語。语言独立保存并立即生效，不需要点击“保存设置”，也不会保存其他正在编辑的配置。写入失败会保留原语言。

首次使用默认跟随 Windows 当前用户的界面语言；英语、法语、俄语、日语和简体中文会匹配对应翻译，其他语言回退英语。跟随系统会在启动或重新选择时重新检测。已有设置但没有语言字段的旧用户保持简体中文。切换后窗口标题、进度、错误、框选提示和 Jev 结果标签同步使用所选语言。

翻译资源内置在分发包中，离线可用。本次不扩展 OCR 识别语言或改变中文回复提示词；聊天内容、已有关系说明和模型名称不会自动翻译。

### 分析对话

1. 打开任意聊天应用并进入普通文字聊天。
2. 首次使用或窗口/显示器位置变化后，点击“框选对话区域”，拖选屏幕上的聊天消息。
3. 选择要生成建议的回复模型，点击“分析当前选区”。
4. 查看 Jev 判断、候选推荐度与红色推荐项；点击复制后自行检查、修改和发送。

分析期间助手窗口会短暂隐藏，避免 OCR 将助手自身识别为聊天内容。框选区域按虚拟桌面坐标保存；旧版微信客户区坐标会保留，但升级后需重新框选一次以使用通用桌面采集。

## 构建分发程序

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

产物位于 `dist\Jev对话助手\Jev对话助手.exe`。PyInstaller 会将 Vue 静态资源、OCR 模型和 Python 运行依赖一起打包，同时生成更新辅助程序 `update_helper.exe`（需与主程序同目录分发）。目标电脑需要 Microsoft Edge WebView2 Runtime；缺少时程序会显示提示。

## 应用内更新

应用支持在软件内自行拉取更新。启动后会延迟几秒静默检查 GitHub Releases；发现新版本时主页顶部出现提示横幅，也可以在设置页的"版本与更新"中手动检查。检查只向 `api.github.com` 查询最新版本号，不发送任何聊天内容。

确认更新后，应用在后台下载 Release 压缩包（可查看进度、可取消），随后进行 SHA256 校验（发布附件包含 `SHA256SUMS.txt` 时启用；否则降级为大小校验）并解压暂存。点击"重启并安装更新"后，主程序退出，辅助程序 `update_helper.exe` 用暂存内容原子替换安装目录并自动重启新版本；替换过程中任何一步失败都会回滚到旧版本，聊天数据与设置保存在 `%APPDATA%`，不受更新影响。

## 隐私边界

- OCR 在本机执行；点击分析后，识别出的聊天文本会发送给 TypeSafe Jev。启用回复模型时，对话和 Jev 判断也会发送给所选服务生成候选回复。
- 模型列表和连接测试只使用当前配置的接口地址、API Key 和模型信息，不会发送聊天内容。
- 界面桥接不会向前端返回已保存密钥；API Key 按配置 ID 存储在 Windows 凭据管理器，也不会写入日志或 `settings.json`。
- 不读取本地聊天数据库，不操作微信输入框，不自动发送。转账、红包、收款、支付等交易内容会拒绝分析。
- 当前面向可见的普通文字聊天；图片、语音和引用卡片不会被可靠还原。

## 常见问题

- **Jev 密钥无效**：填写 `console.typesafe.ai` 控制台生成的 API Key。
- **无法加载模型列表**：有些代理或服务不提供模型列表端点；可直接手动输入服务端支持的模型 ID。
- **连接测试失败**：核对协议、基础地址、API Key 和模型名称。Anthropic 配置应选择 `anthropic`；Responses 接口应选择 `openai-responses`。
- **无法启动桌面窗口**：安装或修复 Microsoft Edge WebView2 Runtime 后重试。
- **微信文字识别不完整**：重新框选聊天气泡区域，不要包含会话列表、标题或输入区。
