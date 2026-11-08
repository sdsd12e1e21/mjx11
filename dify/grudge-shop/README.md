# 记仇杂货铺 · 乌老板的小本本

你把借口罐头换成了空气。关掉聊天，再来砍价，乌老板却掏出了那张写着“量子罐头”的标签。

这是一个 Dify Chatflow 角色互动游戏。玩家可以试用三件有副作用的奇物、恶作剧、道歉和补偿，尝试得到“本店最不放心的熟客”徽章。场景与对话由语言模型即兴演绎；熟客徽章和黑名单结局由明确的轻量规则结算，避免模型无限追加任务。

## 交付与当前状态

- `grudge-shop.yml`：唯一需要导入的 DSL，包含全部九个节点，JSON 表示的合法 YAML。
- `gateway.py`：标准库 HTTP 网关，没有私有数据、预装状态或本地历史缓存。
- `verify.py`：对真实 PowerContext 执行写入、召回、隔离和鉴权验证，自动保存证据。
- `check_dsl.py`：检查图引用和实际节点代码的输入编码、失败处理。
- `TESTING.md`：完整试玩顺序、预期表现和重置方法。
- `ACCEPTANCE.md`：按赛题第三、第四部分逐条对照，标明材料路径和实测边界。
- `dify-plugin-lock.json`：实际模型插件1.1.0及精确摘要；提交DSL为实际导出并脱敏的0.7.0。
- `evidence/`：真实记忆读写结果。测试中的店主回复为固定夹具，不冒充模型生成。

已在 Dify Cloud 导入并于2026-11-08实际跑通完整互动，通过 Cloudflare 临时 HTTPS 隧道访问本机 PowerContext，并已发布体验版。试玩入口：https://udify.app/chat/eHIpVvwq2zFxqKVT 。作者电脑和隧道需持续运行，评审复现应自行配置网关地址和密钥。本次声明的运行环境为 Dify Cloud（2026-11-08滚动服务），实际导出/重新导入的DSL版本为0.7.0；不声明自部署Dify 1.9.1已验证兼容。实测范围见 `STATUS.md`，免费临时部署见 `LOCAL-DEMO.md`。

## 技术分工

```text
玩家输入 → JSON编码 → HTTP召回 → 检查召回 → LLM乌老板
  → JSON编码本轮记录 → HTTP写入 → 检查写入凭据 → 回复
                       ↓
                 标准库网关 → PowerContext HTTP API → 官方SQLite持久化
```

Dify 承担输入处理、模型调用、HTTP 编排和输出。PowerContext 实际保存玩家行动与虚构回复，并通过 PreparedContext 全文召回提供后续互动的历史。关闭 Dify 内置对话记忆，避免把会话上下文误当作跨会话持久记忆。

本作品选择 **Dify + PowerContext**，不声称使用 seekdb。PowerContext 官方默认 SQLite 是其存储后端，应用不维护第二份历史存储。显式写入及 FTS 召回无需配置 PowerContext 的模型、Embedding 或 Rerank。

## 环境及安装

建议 Linux x86_64 或 macOS；Windows 为 PowerContext 官方实验性支持，本交付已在 Windows、Python 3.11.1 环境执行真实记忆闭环。需要 Python 3.11+、Git、互联网下载依赖；一个可在 Dify 调用的聊天模型。网关自身无第三方依赖。准备独立目录后：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

PowerContext 固定源码提交：`ed8902b234c4111b6f54e66694806430e25be3a9`。`requirements-lock-windows.txt` 如存在，是本次实测依赖版本清单；跨平台优先按 requirements.txt 安装。内存和 CPU 未做容量基准，先预留 2GB 内存、2GB 可用磁盘用于小规模试玩，按实际监控调整。

## 启动：本地或自部署 Dify

终端一（在本项目目录，保持运行）：

```bash
export POWERCONTEXT_HOME="$PWD/pc-data"
powercontext server run --host 127.0.0.1 --port 8000 --no-env-file
```

SQLite 模式使用默认 `all` role，不要改为 `--role api`。首次启动等待 `/health/live` 正常后再继续。不需要启用遥测或自动推理。

终端二：

```bash
source .venv/bin/activate
export POWERCONTEXT_URL=http://127.0.0.1:8000
export GATEWAY_TOKEN='替换为自行保管的随机长密钥'
export GAME_NAMESPACE=grudge-shop-v1
python gateway.py
```

环境示例在 `.env.example`，网关不会自动读取该文件，请显式导出变量。只有 PowerContext 启用 Bearer 鉴权时才设置 `POWERCONTEXT_TOKEN`。这两个 token 用途不同。

Windows PowerShell 对应启动方式：

```powershell
.venv\Scripts\Activate.ps1
$env:POWERCONTEXT_HOME="$PWD/pc-data"
powercontext server run --host 127.0.0.1 --port 8000 --no-env-file
# 另开同目录终端并激活环境
$env:POWERCONTEXT_URL='http://127.0.0.1:8000'
$env:GATEWAY_TOKEN='替换为自行保管的随机长密钥'
python gateway.py
```

## Dify 导入与配置

1. 使用 Dify Cloud（本次实际验证环境，2026-11-08），需要可工作的代码执行环境和 HTTP Request 节点。云端未在此界面公开服务构建版本，交付以实际导出的 DSL 0.7.0 与锁定模型插件为准。旧版自部署 Dify 需自行验证导入兼容性，不列为本次验收环境。
2. 在工作室“导入 DSL 文件”选择 `grudge-shop.yml`，或在已有 Chatflow 的菜单中先备份再导入。只导入这一份文件，无知识库、素材或初始化记忆需要导入。
3. 在“乌老板即兴营业”节点选择已配置的聊天模型。DSL 默认为 `langgenius/openai/openai` 的 `gpt-4o-mini`，使用官方 OpenAI 模型供应商插件 **1.1.0**，安装来源 https://marketplace.dify.ai/plugins/langgenius/openai ，以及有效模型凭据/试用额度。导入 DSL 时检查依赖安装，或者在“插件”中从 Marketplace 安装 OpenAI 1.1.0，然后在“模型供应商”中配置自己的凭据，再回到模型节点选择 gpt-4o-mini。精确插件标识及摘要记录在 `dify-plugin-lock.json`，DSL 也已包含相同依赖声明。也可手动换成已配置的其他中文聊天模型，不要将凭据写入 DSL。
4. 设置环境变量 `GATEWAY_URL`（网关根地址，末尾无斜杠）和 secret 类型的 `GATEWAY_TOKEN`。token 与网关启动环境完全一致。HTTP 两个节点会自动引用这两个变量。
5. Dify 云端必须使用公网可达的有效 HTTPS 地址。`127.0.0.1` 指向 Dify 服务器本身，不能用来访问作者电脑。自部署 Dify 的容器也要使用容器实际可达的宿主/内网网关地址，并按 Dify 官方 SSRF 代理策略配置可访问目标。
6. 先用预览执行 TESTING.md；全部通过后才发布 Web 应用，保留 Dify 节点执行记录。不要把导入成功等同于运行验收成功。

无需自定义插件，也无需安装娱乐游戏 DSL。模型节点只是供应商插件的常规调用。

## 长期云端网关部署（可选）

在你控制的服务器按以上步骤启动 PowerContext 与网关，两者仅监听服务器 loopback。使用已有 HTTPS 反向代理仅代理网关端口 8765；PowerContext 8000 端口无需暴露公网。网关校验 Bearer token。下面为已有证书的 Nginx 配置片段，替换域名、证书路径后集成到你的站点：

```nginx
server {
    listen 443 ssl;
    server_name game.example.com;
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
    client_max_body_size 20k;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_read_timeout 40s;
    }
}
```

生产部署应由服务管理器保持两个进程运行，持久化并备份 `POWERCONTEXT_HOME`。网关同时根据召回的玩家实际行动判定轻量结局，写入最终结局后由 Dify 校验并输出。结局识别使用明确关键词（如历史中的“道歉/对不起/补偿”和本轮的“我补回/我归还/整理好货架/诚实宣传”），不是通用的自然语言行为验证器。网关是单实例小规模体验实现，未做速率限制和容量测试，不提供并发同玩家的严格轮次顺序；不要对写入设置自动重试。公网代理应限制流量，保持 token 私密。

## 数据与边界

玩家标识只取 `sys.user_id`，不让模型或用户文本决定 scope。网关用固定游戏 namespace 和玩家 ID 的哈希生成稳定幂等 scope key。它是数据分区映射，不是最终用户身份验证系统；网关 token 只给受信任的 Dify 服务使用。Dify Web 应用通常基于终端用户身份/浏览器维持 ID；换浏览器、清理身份或 API 调用时更改 `user` 会得到新玩家，并不承诺不同设备自动认出同一人。

只保存游戏行动与虚构回复。历史作为不可信引用传给模型，不授予工具权限。FTS 查询使用固定锚词“杂货铺”，每条记录均含该锚词；准备上下文限制 6000 字节，长对局早期内容可能被截断，不声称无限记忆或语义检索。单轮行动不超过1200字、记忆不超过8000 UTF-8字节。模型输出过长或服务不可用会明确失败，不用内存假数据降级冒充成功。

## 来源与许可

原创游戏设定、提示词、网关、DSL 和验证脚本；未复制第三方游戏或素材。代码按本目录 MIT LICENSE 发布。

- 赛题：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lhfslihtnnb8yqh6
- 比赛基线：https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem （基线提交 `d647275c308e09b7b623f322a26f5c4e85734fb0`）
- PowerContext 接口：https://powercontext.oceanbase.io/zh/docs/develop/api-quickstart/ （源码提交优先于后续变更的在线文档）
- Dify HTTP：https://docs.dify.ai/en/cloud/use-dify/nodes/http-request
- Dify 1.9.1：https://github.com/langgenius/dify/releases/tag/1.9.1

PowerContext 与 Dify 均为外部依赖，遵循其自身许可。本目录不包含这两个项目源码。
