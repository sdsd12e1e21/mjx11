# 免费临时公网测试

优先按 README 安装并启动 `run_local.py`。PowerContext 和网关默认只监听本机 8000/8765；若使用 `--gateway-port`，下列命令须同步更换端口。

1. 从 Cloudflare 官方来源安装 cloudflared；本机原有测试工具为官方 2026.10.7。下载来源：https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe ，其他系统使用相应官方版本。
2. 保持 `python run_local.py` 运行，另开终端执行 `cloudflared tunnel --url http://127.0.0.1:8765 --no-autoupdate`，等待输出有效 HTTPS 地址。
3. 在项目目录运行 `python configure_dsl.py --gateway-url https://替换为本次实际地址`，将 `.runtime/grudge-shop-configured.yml` 导入自己的 Dify 工作区。该本地文件包含随机网关密钥，禁止提交或转发。源码模板没有真实密钥。
4. 按 README 绑定聊天模型，先运行 TESTING.md 的完整流程，再按需发布。地址变更后，已发布应用也必须更新并重新发布。
5. 可执行 `python verify.py --connection .runtime/connection.json --url https://替换为本次实际地址`，核对公网端的真实读写、隔离及鉴权；此脚本不代替 Dify 完整试玩。

网关 /recall、/remember 要求 Bearer token，/health 不返回玩家数据。只转发网关；不向公网暴露原始 PowerContext。停止 cloudflared 即停止临时入口；电脑关机、断网或重建隧道可能使入口失效。临时方式只用于测试，评审可自行按完整说明重建，无需作者旧服务存活。

官方说明：https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ 。本轮实际验证版本和证据见 REVISION-20261109.md。
