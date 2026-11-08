# 完整交付与验收结果

2026-11-08 已完成真实 MiniMax 改码与 Linux 干净环境验收。12 项模块和原生集成测试全部通过，无跳过；完整业务验证也通过。原始结果见 `evidence/verification/verification.json`、`module-tests.txt` 和 `execution.json`。

实际验收运行：[GitHub Actions 42428924105](https://github.com/sdsd12e1e21/mjx11/actions/runs/42428924105)。运行所用代码 commit：`e6275fc0f2b49853e17eddd9d4d2c5a83970c726`。后续材料提交仅补充文档和原始验收记录。

| 必做项 | 实际结果与核对位置 |
|---|---|
| 能够运行 | 从空目录构建交付容器、初始化工程资料、运行完整验证。准确命令、代码版本和退出码见 `evidence/verification/execution.json`、`reports/` |
| MiniMax 实际参与 | 实际调用 MiniMax-M3.1-Flash，响应 ID `073ef1d374032d9d74e6a309b20a8e90`；输入 3260、输出 351、总计 3611 tokens。完整任务、真实数据库上下文和最终代码见 `evidence/minimax-development.json`，非模拟输出 |
| 上下文正确 | 包含 `specs/orders.md`、`src/order_service.py` 和两份测试的原文、行号/符号和哈希；追加 ORD-UPDATE 并重新导入后，新上下文使用规格 revision 2，且标记旧验证需重做。见 `context.json`、`updated-spec-context.json` |
| 数据库实际参与 | 四份工程资料实际写入嵌入式 seekdb；三类参数化全文 SQL 的结果实际用于上下文。见 `evidence/model-input/technology/seekdb.jsonl`、`evidence/verification/technology/seekdb.jsonl` |
| 状态能够复用 | 第一条 PowerContext read 为未找到；之后写入基线和成功结果；独立 Python 进程读取同一记忆 revision 2，实际复用模型响应 ID、测试结果和已完成步骤。见 `technology/powercontext.jsonl`、`resumed-context.json` |
| 代码修改有效 | 同一组 3 项目标测试修改前因断言失败退出 1，修改后全部通过退出 0；原有 6 项回归两次均通过。两份测试 SHA-256 保持不变。见 `reports/before-*.json`、`reports/after-*.json`、`verification.json` |

表内未带前缀的记录路径均相对于 `evidence/verification/`。

## 六类提交材料

| 材料 | 位置 |
|---|---|
| 完整源码 | `src/minimax_sdd/`、`demo/src/`、容器和依赖配置 |
| 运行说明 | `README.md`、`.env.example`、`requirements-linux.lock`；包含配置、初始化、调用入口、测试命令、重置和限制 |
| 验证样例 | `DEMO.md`、`demo/task.json`、`demo/specs/`、`demo/data/`，明确四份必要上下文来源和预期行为 |
| 代码与测试 | `evidence/development/` 保存修改前后快照、diff 和哈希；`demo/tests/` 保存不变目标/回归测试；`evidence/verification/reports/` 保存实际命令、退出码与来源版本 |
| 技术使用记录 | `evidence/minimax-development.json`、`evidence/model-input/`、`evidence/verification/technology/` 与恢复后的上下文 |
| 一页技术说明 | `TECHNICAL.md`；开源和自建资料来源见 `NOTICE.md` |

## 重现与已知限制

按 README 从空目录执行 `prepare` 和 `verify`。重放已交付真实开发记录不需要再次付费调用模型；如需新的真实调用，M Plan 必须使用订阅 Key，按量 API Key 使用独立钱包，两者不可互换。成功调用使用的订阅密钥未写入任何交付文件。

独立模块测试会因 `/app` 为只读挂载出现一条 pytest 缓存写入警告，不影响 12 项测试通过或运行产物写入 `/runs`。当前按声明支持小型 Python 工程，检索范围及文件大小限制见 README。以上是交付环境中的实际验证结果，最终比赛成绩以评审为准。
