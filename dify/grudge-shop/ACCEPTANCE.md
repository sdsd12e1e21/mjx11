# 赛题第三、第四部分验收对照

核对来源：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lhfslihtnnb8yqh6 ，核对日期2026-11-08。本表为提交材料的自查定位，不代替赛事评审或承诺评分。

| 条款 | 实现或材料 | 验证与边界 |
|---|---|---|
| 3.1 能够运行 | grudge-shop.yml、README.md、requirements.txt、gateway.py | 唯一九节点DSL已实际重新导入，绑定服务和模型后执行连续样例；evidence/audit-reimport-* 为本轮记录 |
| 3.1 体验主要功能 | TESTING.md B部分 | 首次光临→恶作剧→新对话回忆→道歉→熟客徽章，输入、操作顺序与预期均交付 |
| 3.1 技术结合有效 | Dify九节点编排；gateway.py调用真实PowerContext | evidence/powercontext-roundtrip.json 有实际records与PreparedContext；Dify内置对话记忆关闭，后续回忆来自PowerContext |
| 3.1 过程可复现 | README.md、LOCAL-DEMO.md、.env.example、requirements.txt | 无外部素材或预装记忆；新namespace或新玩家得到空初始状态；评审使用自己的模型凭据与网关地址 |
| 3.2 创意、趣味、完成度 | 三件奇物、记仇店主、补偿与两种结局 | 模型生成场景，明确关键词规则结算结局；不以节点数量或双数据库作为质量承诺 |
| 4.1 全部DSL/用途/顺序 | 仅grudge-shop.yml | 导入这一份即可；Dify Cloud实测，DSL0.7.0；无知识库重绑，只需绑定模型及两个网关环境变量 |
| 4.2 创意/玩法/技术分工 | README.md“技术分工”及开篇 | Dify核心编排，PowerContext持久化与召回，网关转换接口并做轻量结算 |
| 4.2 运行环境/版本/插件 | requirements.txt、requirements-lock-windows.txt、dify-plugin-lock.json | Python3.11.1实测，PowerContext固定源码提交；OpenAI插件1.1.0来自官方Marketplace，模型gpt-4o-mini |
| 4.2 完整安装/初始化/启动/入口 | README.md、LOCAL-DEMO.md | 无需预置数据；官方PowerContext首次启动创建持久化存储，网关按sys.user_id创建玩家scope |
| 4.2 外部服务/网络/资源/限制 | README.md“部署”“数据与边界” | Dify Cloud需可达HTTPS网关，PowerContext仅本机；临时隧道依赖电脑持续在线；资源预算是建议而非压测结论 |
| 4.2 占位凭据/来源 | .env.example、DSL环境变量；README.md“来源与许可” | 真实密钥不入库；原创游戏/源码，PowerContext、Dify等外部依赖分别遵循其许可 |
| 4.3 初始状态/输入/顺序/预期 | TESTING.md | 新namespace恢复初始状态，不删除旧数据；每次verify.py随机新玩家，可重复运行 |
| 4.3 实际运行结果/技术记录 | evidence/、STATUS.md | 包含实际Dify连续运行、新会话回忆、结局，以及真实PowerContext读写证据；固定夹具测试与真实模型运行明确区分 |
| 4.4 seekdb部署Dify | 不适用 | 选择Dify+PowerContext；没有声明使用seekdb |
| 4.4 知识库/外部数据 | 不适用 | 三件奇物设定在已交付提示词中，没有未交付知识库或素材 |
| 4.4 预置记忆/互动状态 | 无预置记忆；README.md标识映射 | sys.user_id→namespace与玩家ID哈希→PowerContext幂等scope；不会让模型选择其他玩家scope |
| 4.4 现成插件 | OpenAI1.1.0及dify-plugin-lock.json | 官方来源、版本、精确摘要和配置步骤均提供 |
| 4.4 自定义插件 | 不适用 | 没有自定义插件，无需额外安装包 |
| 4.4 自定义后端 | gateway.py、requirements.txt、.env.example、README.md | 完整源码与启动步骤交付；没有自定义前端或私有镜像依赖 |

## 本轮重新导入复现方式

1. 备份当前Dify草稿，使用仓库中的grudge-shop.yml重新导入，确认九个节点和OpenAI1.1.0依赖。
2. 启动仓库网关源码，使用全新GAME_NAMESPACE=grudge-shop-reimport-20261108（评审可改成任意新的唯一值），保留旧记忆但不复用；PowerContext仍使用实际官方服务。
3. 配置网关地址、secret token以及已验证的模型，运行TESTING.md的连续输入。在同一玩家身份下重新开始Dify对话，验证店主主动提及之前恶作剧。
4. 保存本轮截图、原始界面文本及提交DSL的SHA256到evidence，运行check_dsl.py、test_game_rules.py、verify.py。

DSL导出包含连接配置但不包含知识库数据；本作品不使用知识库，无额外内容遗漏。旧Dify1.9.1仅在开发时参考过节点定义，不声明其已通过运行验证；本次正式声明环境以Dify Cloud和DSL0.7.0为准。
