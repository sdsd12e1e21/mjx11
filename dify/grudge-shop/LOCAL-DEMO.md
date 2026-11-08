# 免费临时公网体验

不需要购买服务器或域名。本项目可以在本机运行 PowerContext 和网关，再通过 Cloudflare Quick Tunnel 让 Dify Cloud 访问。临时隧道用于测试，不保证长期在线；电脑关机或隧道停止后地址失效，重建通常会换地址。

1. 按 README 安装固定版本依赖、启动 PowerContext 和网关。网关设置自行保管的随机 `GATEWAY_TOKEN`，保持只监听 `127.0.0.1:8765`，PowerContext 只监听 `127.0.0.1:8000`。
2. 从 Cloudflare 官方下载 cloudflared。此次实测 Windows amd64 版本 `2026.10.7`，下载来源：https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe 。评审可按自己的系统使用官方对应版本，无需安装为系统服务。
3. 执行 `cloudflared tunnel --url http://127.0.0.1:8765 --no-autoupdate`，保持进程运行，复制打印的 `https://……trycloudflare.com` 地址。
4. 在 Dify 环境变量配置此地址及与网关一致的 secret token，按 TESTING.md 执行完整试玩。发布后的版本若更改地址，需要再次发布才能生效。
5. 停止 cloudflared 即可撤销临时公网入口。原始 PowerContext 没有直接暴露到公网，网关 `/recall`、`/remember` 均要求 Bearer token；仅 `/health` 无需身份验证且不返回玩家数据。

不要将真实密钥放进 DSL、仓库、日志或截图。提交的 `grudge-shop.yml` 保留占位值，评审需要自行配置地址和密钥，不依赖作者的临时地址。

2026-11-08 已实际通过这种方式完成 Dify Cloud 到本机 PowerContext 的完整互动，证据见 evidence/dify-e2e-*。Dify 内置对话记忆保持关闭；新对话仍能通过 PowerContext 召回此前恶作剧。

官方临时隧道说明：https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/
