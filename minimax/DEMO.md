# 验证样例：订单金额闭区间

当前仅完成前置验证；第 4–7 步的完整模型改码验收待 MiniMax 额度可用后执行，不能视为已经通过。独立模块测试已经覆盖真实 PowerContext 跨进程读写和 seekdb 规格重新导入。

任务 ID：`orders-inclusive-amount-range`。将订单金额筛选从开区间修复为闭区间，同时保留状态筛选、ID 升序、不修改输入和参数校验行为。

## 上下文必须包含的工程来源

| 来源 | 必要内容 |
|---|---|
| `demo/specs/orders.md` | ORD-001 上下界均包含，零金额、相等上下界；ORD-002 状态、排序、不修改输入；ORD-003 非法参数抛出 ValueError |
| `demo/src/order_service.py` | `select_orders` 函数、验证分支与两个边界比较分支；上下文提供真实行号、文件哈希 |
| `demo/tests/test_target.py` | 闭区间 1000..3000、相同边界 2000..2000、零金额 0..0 的断言 |
| `demo/tests/test_regression.py` | 原有 6 项行为测试，修改前后同一文件 |

初始数据来自 `demo/data/orders.json`：5 个订单，金额分别 0、1000、2000、2000、3000 分；3 个 paid、1 个 new、1 个 cancelled。无需下载外部数据。

按 README 的 `prepare` → `verify` 操作。验收观察点：

1. 空状态开始：PowerContext 第一条 read 的 `found` 为 false；seekdb import 写入四个工程文件。
2. 修改前：3 项目标断言失败，6 项回归通过；`before-*.json` 记录命令、退出码、Python 版本及每份源码的 SHA-256。
3. 实际上下文：`context.json` 包含上述四份来源、规格条款及已保存的基线测试结果。`technology/seekdb.jsonl` 可核对参数化 SQL、返回路径、修订号和哈希。
4. MiniMax 修改：核对 `evidence/minimax-development.json` 请求的任务与上下文，以及最终 `files` 与交付差异。真实记录必须是 `live-minimax`；单元测试的模拟传输不会被当成真实记录接受。
5. 修改后：3 项目标测试及 6 项回归全部通过，两份测试文件哈希与修改前一致。1000..3000 返回 [2,3,4,5]，paid 2000..2000 返回 [3]，0..0 返回 [1]。
6. 跨进程恢复：独立进程打开数据库，`resumed-context.json` 使用同一任务的实际模型响应 ID、成功测试结果和已完成步骤；待办为空，后续处理据此继续。
7. 规格变化：在运行副本的 `specs/orders.md` 追加 `ORD-UPDATE`，重新导入。`updated-spec-context.json` 应包含该新增原文、规格修订号 2，并将 `needs_revalidation` 置 true。原有成功测试不能冒充更新后已验证。

模块回归还验证：未重新导入的规格拒绝使用、重复导入无变更、非法改码路径拒绝、代码版本变化拒绝重放、真实 PowerContext 跨进程读写、记录不含认证信息和私有思维链。

重置使用 `reset` 归档标记过的运行目录，再从 `prepare` 开始；交付源码及原始数据保持可重复使用。`verify` 的任何必做项失败都会以非零退出，不通过跳过断言或改写预期结果获得通过。
