# 更新日志

## v1.0.0

- 支持 Windows 电脑版微信 `Weixin.exe` / `WeChat.exe`。
- UI Automation 优先，本地 RapidOCR 兜底读取用户框选的可见聊天区。
- 直连 TypeSafe Jev API，展示真实意图、危险程度、对方需求、最佳动作等结构化判断。
- 可选直连 DeepSeek API，依据 Jev 判断生成三条建议回复。
- Jev 与 DeepSeek 密钥分别保存在 Windows 凭据管理器，不写入普通配置文件。
- 建议回复只能复制，不自动填写或发送微信消息。
- 截图时自动隐藏助手窗口，避免递归 OCR。
- 会话白名单、交易敏感词拦截和清晰的分阶段状态提示。
