# 记仇杂货铺 · 乌老板的小本本

你把借口罐头换成空气，关掉聊天再来砍价，乌老板却掏出写着“量子罐头”的标签。

这是 Dify Chatflow 角色游戏。玩家试用奇物、恶作剧、道歉和补偿，尝试得到“本店最不放心的熟客”徽章。模型即兴演绎，网关根据玩家实际行动结算友好/黑名单结局。**Dify 负责编排和模型调用，PowerContext 保存并召回真实游戏互动。** 不使用 seekdb、额外知识库、Embedding 或 Rerank。

## 本次修订与材料入口

2026-11-09 修订：改用 PyPI PowerContext **1.5.0** 正式发行版；提供统一启动、就绪检查和本地 DSL 配置工具；加强召回/写入的返回结构校验。唯一提交 DSL 为 `grudge-shop.yml`，采用 **0.4.0 兼容格式**，不是将运行环境版本号改为 0.4.0。

旧 Dify Cloud 的 0.7.0 导出在 Dify 1.9.1 导入器中会进入 pending；本次保留所需的九个基础节点并使用 0.4.0 格式，重新在 Cloud 导入测试。**没有声称本机完成了 Dify 1.9.1 的整套自部署验收**；实际测试环境和结果见 [REVISION-20261109.md](REVISION-20261109.md)。修订不能代替赛事最终评分，也不能证明上次未知原因的失败一定由版本导致。

- [验收对照](ACCEPTANCE.md)：第三、第四部分材料。
- [完整试玩样例](TESTING.md)：初始条件、操作顺序、输入、预期和重置方式。
- `workflow_code/` 与 `grudge-shop.yml`：实际节点源码和唯一需导入的 DSL，`check_dsl.py` 会检查二者一致。
- `gateway.py`、`requirements.txt`、`run_local.py`、`configure_dsl.py`：后端及从空环境启动的工具。
- `evidence/`：真实记忆读写、Dify 运行和本次修订的证据；2026-11-08 的材料是历史记录，旧依赖清单在 `evidence/legacy-requirements-windows-20261108.txt`，不要用它安装当前版本。

## 从空环境安装

需要 Python **3.12**（本次实测）、互联网下载依赖，以及一个可以在 Dify 中调用的中文聊天模型。PowerContext 使用官方 SQLite 持久化，不是应用自行存储历史。网关与启动/配置脚本只依赖 Python 标准库。

在本目录执行，Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe run_local.py
```

Linux/macOS：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_local.py
```

本轮新建虚拟环境从 PyPI 安装；`python -m pip check` 应无依赖冲突。无需 Git 源码安装、编译 PowerContext 或预置作者数据库。此题未提供离线依赖镜像，首次安装需要联网。

启动脚本依次等待 PowerContext 和网关真正就绪，默认各最多 120 秒。提前退出、超时或运行期间服务退出，均报错并清理本次启动的进程。端口被占用时会拒绝启动，不会停止或复用其他服务；可用 `--pc-port 18100 --gateway-port 18765` 指定新端口。`Ctrl+C` 停止这两个自有进程树。

默认目录 `.runtime/` 包含官方持久化数据、诊断日志、`connection.json` 和已配置 DSL，已由 `.gitignore` 排除。**保留此目录才能在重启后继续同一玩家的历史。** 使用 `--state-dir` 指定新的空目录可创建独立世界，旧目录不会被删除。密钥由脚本随机生成，保存到私有本地文件，不在终端或仓库中输出。

## 连接 Dify Cloud

1. 保持 `run_local.py` 运行。默认仅监听本机：PowerContext 8000、网关 8765。
2. 在自己的服务器提供 HTTPS 网关反向代理；临时测试也可按 [LOCAL-DEMO.md](LOCAL-DEMO.md) 使用 Cloudflare Quick Tunnel。只代理网关，不能把原始 PowerContext 暴露到公网。Dify Cloud 的 `localhost` 指向云端自身，无法访问你电脑。
3. 新终端运行（以下用 Windows 解释器为例，POSIX 换为 `.venv/bin/python`）：

```powershell
.venv/Scripts/python.exe configure_dsl.py --gateway-url https://你的可达网关
```

4. 在 Dify 工作室“创建 → 导入应用”中选择生成的 **`.runtime/grudge-shop-configured.yml`**。该文件从提交模板生成，已绑定网关地址和 secret token，只供导入你自己的 Dify 工作区；不要上传到 GitHub 或发送给别人。也可导入仓库中的脱敏模板，手动设置 `GATEWAY_URL` 和 secret 类型的 `GATEWAY_TOKEN`，后者必须与本地连接文件一致。
5. 在“乌老板即兴营业”节点选择已配置的模型。默认官方 OpenAI 插件 **1.1.0**、`gpt-4o-mini`，安装来源 https://marketplace.dify.ai/plugins/langgenius/openai ，精确标识见 `dify-plugin-lock.json`。模型需要自己的有效供应商凭据或 Dify 额度；凭据不包含在提交材料中。也可绑定自己的中文聊天模型，并记录替代型号。
6. 预览运行 [TESTING.md](TESTING.md) 的连续样例，再发布应用。Dify 内置对话记忆保持关闭。导入成功、单节点成功或健康端口返回成功都不能代替完整试玩。

如使用自部署 Dify，网关地址必须从 Dify 的 API/worker/SSRF 代理容器实际可达，并遵守该部署的 SSRF 网络策略；容器里的 `127.0.0.1` 不是宿主机。配置工具不会修改 Dify 的网络安全策略。

## 自测与实际记忆证据

保持服务运行，在另一个本目录终端执行：

```powershell
.venv/Scripts/python.exe check_dsl.py
.venv/Scripts/python.exe -m unittest discover -p "test_*.py" -v
.venv/Scripts/python.exe verify.py --connection .runtime/connection.json
```

跨公网验证时，可给最后一条命令加 `--url https://你的可达网关`；证据可用 `--output 路径.json` 另存。该脚本用随机测试玩家，不需要作者旧数据，检查真实写入的 ArtifactRef、召回内容、重复输入、玩家隔离和错误 token 返回 401。脚本台词是明确标注的固定测试夹具；Dify 模型互动须另外按 TESTING.md 验证。

`GET /health` 只有在网关能连接真实 PowerContext 时才返回 200；服务不可达返回 503。`POST /recall`、`POST /remember` 要求 Bearer token，实际保存玩家输入与模型回复。服务错误不会当作空历史；无效写入凭据不会生成已保存的假成功回复。HTTP 写入不自动重试。

## 数据语义与边界

`sys.user_id` → 固定游戏 namespace 与玩家 ID 哈希 → PowerContext 幂等 Scope。模型或玩家文本不能决定其他玩家分区。该映射是数据分区，不是跨设备身份认证；更换浏览器身份或 API 的 user 会得到新玩家。

三件奇物设定在已交付提示词里，无素材下载或知识库初始化。只保存虚构游戏行动与回复，历史作为不可信引用输入模型。FTS 固定锚词“杂货铺”，上下文 6000 字节；长对局早期内容可能截断。输入最多 1200 字，单轮记忆最多 8000 UTF-8 字节。结局按明确关键词结算，不是通用行为判断器。同玩家并发无强轮次顺序，写入无 exactly-once 保证，尚未做容量基准。

小规模试玩建议先预留 2GB 内存和 2GB 磁盘，按实际监控调整；不是经压测得出的最低配置。长期在线应在自己的服务器保持进程运行并备份状态目录；作者电脑和临时隧道不是评审复现的必要条件。

## 来源与许可

原创游戏设定、提示词、网关、DSL 和验证脚本；未复制第三方游戏或素材。本目录代码使用 MIT LICENSE。PowerContext 与 Dify 为外部依赖，遵循各自许可证。

- 题面：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lhfslihtnnb8yqh6
- 比赛代码基线：https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem ，提交 `d647275c308e09b7b623f322a26f5c4e85734fb0`。
- PowerContext：https://github.com/oceanbase/powercontext ，运行依赖固定 PyPI 1.5.0；接口与该发行版核对。
- Dify HTTP：https://docs.dify.ai/en/cloud/use-dify/nodes/http-request
- 导入兼容性参考：https://github.com/langgenius/dify/blob/1.9.1/api/services/app_dsl_service.py
