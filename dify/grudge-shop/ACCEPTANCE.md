# Dify 第三、第四部分验收对照

题面：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lhfslihtnnb8yqh6 。核对日期：2026-11-09。下表是材料定位，不代替赛事评审或承诺评分。

| 条款 | 当前实现与材料 | 验证边界 |
|---|---|---|
| 3.1 能够运行 | grudge-shop.yml、requirements.txt、run_local.py、README.md | 新 Python 3.12 环境安装和依赖检查；九节点 DSL 已在 Dify Cloud 重新导入运行；0.4.0 兼容格式不等于已完成旧版整套自部署测试 |
| 3.1 体验主要功能 | TESTING.md B、evidence/revision-20261109-* | 首次光临、恶作剧、服务重启与新会话回忆、道歉、熟客结局均有实际运行记录 |
| 3.1 技术结合有效 | gateway.py 真实调用 PowerContext 1.5.0；Dify 编排与模型调用 | 官方 SQLite 是 PowerContext 自身持久化；无自制历史库或假数据降级；模型确实引用玩家此前行动 |
| 3.1 过程可复现 | README.md、run_local.py --check、configure_dsl.py | 无作者预置数据；自动创建随机 namespace/密钥和官方数据目录；就绪后才启动网关；重复 --check 验证实际重启恢复 |
| 3.2 创意、趣味与互动 | 三件奇物、乌老板、明确结局规则 | 模型生成开放式场景，结局按明确行动关键词结算；不虚构真实用户或提效数据 |
| 4.1 全部 DSL、用途与导入 | 唯一 grudge-shop.yml；workflow_code/ 与 check_dsl.py | 支持本地工具绑定 URL/secret，再导入生成文件；源模板保持占位值，无额外知识库重绑 |
| 4.2 环境、软件、模型和插件 | requirements.txt、evidence/revision-20261109-runtime.json、dify-plugin-lock.json | PowerContext 1.5.0；OpenAI 1.1.0 / gpt-4o-mini 来自官方 Marketplace；需评审自己的有效模型凭据或额度；无 Embedding/Rerank |
| 4.2 安装、初始化、启动、入口 | README.md、LOCAL-DEMO.md、run_local.py、configure_dsl.py | PyPI 安装无需 Git 源码依赖；初次安装需联网；Dify Cloud 需可达 HTTPS 网关，容器不得误用 localhost |
| 4.2 配置与限制 | .env.example、README.md | 私有 connection.json、配置 DSL、数据库和日志不入库；本机/临时隧道不保证持续在线；长期部署需自己的服务器 |
| 4.2 来源与许可 | README.md、LICENSE | 原创玩法、DSL 和配套代码；外部组件遵循各自许可 |
| 4.3 初始数据、输入、顺序、预期、重置 | TESTING.md、verify.py | 随机测试玩家或新 state-dir，不删除旧数据；标准输入顺序和预期表现明确 |
| 4.3 实际运行与技术记录 | evidence/revision-20261109-roundtrip.json、restart.json、failure-checks.json、截图与聊天文本 | 固定夹具 API 验证与真实 Dify 模型互动分开说明；包含真实 ArtifactRef 与 PreparedContext |
| 4.4 数据、记忆初始化 | 无未交付知识库或预置记忆 | 三件奇物在提示词；sys.user_id 与 namespace 的哈希映射到独立 PowerContext Scope |
| 4.4 现成/自定义插件 | OpenAI 1.1.0 与具体标识来源见 README 和 dify-plugin-lock.json | 无自定义插件，无需未交付安装包 |
| 4.4 自定义后端 | gateway.py、requirements.txt、run_local.py、配置模板与启动说明 | 完整源码；不依赖作者预编译后端或既有进程 |

当前验证明细及已知限制见 [REVISION-20261109.md](REVISION-20261109.md)。源码已提交不等于判题端的私有仓库读取授权有效；用户仍需在比赛平台保持正确授权，并填写实际推送的分支和完整 SHA。
