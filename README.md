# JevChat Tencent

> 本项目基于原作者 **Liyucheng1997** 的 [332_lab-jev-chat](https://github.com/Liyucheng1997/332_lab-jev-chat) 再开发，当前版本聚焦 Windows 电脑版微信场景。感谢原作者的开源工作；本项目保留原仓库的 MIT 许可证，并在此基础上进行独立改进。

JevChat Tencent 是运行在 Windows 电脑版微信旁的非侵入式对话辅助工具。它读取当前可见聊天内容，优先使用 Windows UI Automation；若微信未暴露消息控件，则对用户明确框选的聊天区域进行本地 OCR。随后调用 TypeSafe Jev 提供结构化判断，并可选用 DeepSeek 生成三条建议回复。

建议回复只能复制。程序不会操作微信输入框、发送消息或模拟 Enter；检测到转账、红包、收款、支付等交易内容时会拒绝分析。

## Windows 客户端

环境：Windows 10/11 x64、Python 3.11（源码运行或构建时需要）、TypeSafe/Jev API Key。DeepSeek API Key 为可选项。

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install.ps1
powershell -ExecutionPolicy Bypass -File .\windows\start.ps1
```

首次启动时打开电脑版微信并进入普通文字聊天，在设置中配置 Jev API Key；需要回复建议时再配置 DeepSeek API Key。框选消息气泡区域后，点击“分析当前微信对话”。两枚密钥保存在 Windows 凭据管理器，不写入普通配置文件。

构建分发版本：

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

详细配置、隐私边界和故障排查见 [Windows 使用说明](windows/README.md)。

## Jev 工具

`tools/jev/` 包含 Jev 判断题目集、API 客户端、演示流程与校准脚手架。具体用法和运行条件请参见各脚本及 Windows 环境说明。运行前请通过环境变量配置所需 API Key；不要将密钥写入代码或提交到仓库。

## 目录

- `windows/`：Windows 微信助手源码、安装/启动/构建脚本及测试。
- `tools/jev/`：Jev 题目集、API 客户端与校准脚手架。
- `LICENSE`：MIT License。

## 来源与许可证

本项目是基于原作者 [Liyucheng1997/332_lab-jev-chat](https://github.com/Liyucheng1997/332_lab-jev-chat) 再开发的独立项目。原项目及其作者的著作权归原作者所有；本仓库所含代码按 [MIT License](LICENSE) 发布。