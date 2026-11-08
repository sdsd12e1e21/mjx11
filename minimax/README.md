# MiniMax：规有所依——SDD 上下文管理系统

已交付真实 MiniMax 开发记录、修改前后快照、代码差异，以及从空状态运行的完整验收入口。验收结果和提交材料逐项对应见 `STATUS.md`；原始记录见 `evidence/`。

此目录独立交付上下文模块、MiniMax 接入、订单业务样例、测试和验收记录。基于官方 `2026-competition-ecosystem` 分支，工程资料由真实嵌入式 seekdb 保存与查询，任务进度由 PowerContext 1.2.0 Memory SDK 保存和恢复。

## 从干净环境运行

推荐 Linux x86_64、Docker Engine 27+、Docker Compose v2、2 GB 可用内存、至少 5 GB 磁盘。Windows 可使用 Docker Desktop 的 Linux 容器。原生 seekdb 不支持直接在 Windows Python 运行；Windows 仍可运行模块单元测试和 MiniMax 接入。

在仓库根目录进入 `minimax/` 后执行（以下命令为 Linux shell）：

```sh
mkdir -p .run
chmod 777 .run
docker compose build
docker compose run --rm sdd python -m pytest -p pytest_asyncio.plugin -q tests --basetemp=/runs/test-tmp
docker compose run --rm sdd python -m minimax_sdd prepare --project /app/demo --run-dir /runs/demo
docker compose run --rm sdd python -m minimax_sdd verify --run-dir /runs/demo --record /app/evidence/minimax-development.json
```

`prepare` 创建隔离业务副本，从交付的 `demo/baseline/` 恢复未实现的功能，初始化空数据库，执行修改前测试，并输出真实数据库查询构建的 `.run/demo/context.json`。目标测试预期退出 1、包含三项断言失败；原有回归测试退出 0。命令本身在成功确认这些前置条件后退出 0。

`verify` 重放已交付真实 MiniMax 记录的最终代码，校验输入来源和文件 SHA-256，执行同一组测试，保存进度，再启动独立 Python 进程恢复进度；最后修改规格、重新导入并确认新规格进入上下文。全部成功才输出 `all_required_checks_passed: true`。该重放无需再次调用模型，符合题面“不要求模型重新生成完全相同补丁”的验收方式。真实调用由 M Plan 订阅 Key 完成；交付记录含请求上下文、响应标识和最终代码，不含认证信息或私有思维链。

查看输出与状态：

```sh
cat .run/demo/verification.json
cat .run/demo/reports/before-target.json
cat .run/demo/reports/after-target.json
docker compose run --rm sdd python -m minimax_sdd context --run-dir /runs/demo --output /runs/demo/current-context.json
docker compose run --rm sdd python -m minimax_sdd state-show --state-dir /runs/demo/state --task-id orders-inclusive-amount-range
```

重复演示前归档运行目录；此操作保留旧数据，不删除目录：

```sh
docker compose run --rm sdd python -m minimax_sdd reset --run-dir /runs/demo
```

然后重新执行 `prepare`、`verify`。首次构建需要网络下载公开依赖；默认验收容器 `network_mode: none`，运行无需外部数据库、API 凭据或宿主机隐藏文件。容器仅为识别本机地址建立一个内部虚拟网卡；数据库不会访问外网。`minimax/requirements-linux.lock` 固定运行、测试及原生数据库依赖，基础镜像固定 digest。

## 新的真实 MiniMax 调用

`minimax/.env.example` 只包含占位配置，程序不自动加载它。将 `MINIMAX_API_KEY` 设置在当前进程环境中；不要提交真实凭据。M Plan 使用“套餐管理”中的订阅 Key，按量计费使用“API Key”页的 Key，两者不可互换；仅有 M Plan 订阅而钱包为零时，按量 Key 会返回余额不足。见[官方前置准备](https://platform.minimax.cn/docs/guides/quickstart-preparation)。中国区默认 `MINIMAX_BASE_URL=https://api.minimax.cn/v1`、`MINIMAX_MODEL=MiniMax-M3.1-Flash`；其他官方地区可显式配置相应端点。调用可能产生正常模型用量。

Linux 主机 Python 3.12 可安装并调用：

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-linux.lock
python -m pip install --no-deps -e .
python -m minimax_sdd develop --context .run/demo/context.json --record .run/new-minimax-development.json
docker compose run --rm sdd python -m minimax_sdd verify --run-dir /runs/demo --record /runs/new-minimax-development.json
```

先对新的空运行目录执行 `prepare` 再调用；不要在已完成的目录重复应用补丁。API Key 通过进程环境读取，只发送至允许的官方 HTTPS 端点。开发记录只保存请求上下文、最终代码、响应标识、时间和用量，不保存 Authorization、真实凭据或模型私有思维链。容器验收测试会去除模型及 GitHub 凭据。

## 模块入口和格式

Python 接口：`ContextModule(state_dir, project_id).ingest(project)`、`.build(project, task)`；CLI 为 `python -m minimax_sdd`，可用子命令 `prepare/context/develop/verify/state-show/reset/versions`。输入任务格式见 `demo/task.json`，工程资料来自 `specs/**/*.md`、`src/**/*.py`、`tests/**/*.py`。

输出上下文含任务、规格/代码/测试全文、文件相对路径、类别、SHA-256、数据库修订号、行号和 AST 符号，以及 PowerContext 恢复的已完成步骤、待办、测试结果和引用。`needs_revalidation` 表示工程资料与上次测试版本不同。数据库查询结果直接进入 `sources`；索引与文件不一致时拒绝生成陈旧上下文，重新导入后才继续。

## 材料索引

| 要求 | 交付位置 |
|---|---|
| 完整源码与接入 | `src/minimax_sdd/`、`demo/src/`、`pyproject.toml`、`requirements-linux.lock`、`docker/`、`compose.yaml` |
| 运行说明 | 本文、`.env.example` |
| 验证样例与重置 | `DEMO.md`、`demo/task.json`、`demo/specs/`、`demo/data/` |
| 修改前后代码与差异 | `demo/baseline/`、`demo/src/`、`evidence/development/` |
| 新增功能和原有回归测试 | `demo/tests/test_target.py`、`demo/tests/test_regression.py`、`tests/` |
| 实际调用、数据库、状态复用记录 | `evidence/minimax-development.json`、`evidence/model-input/`、`evidence/verification/` |
| 一页技术说明、来源 | `TECHNICAL.md`、`NOTICE.md` |

## 限制

当前面向单进程、单项目的小型 Python 工程；每文件最多 100 KB，按规格/代码/测试分别返回最多 3 个全文文件。检索使用真实 seekdb 全文索引，英文词和中文单字规范化；未实现向量检索、多租户鉴权、大仓库分片或任意语言符号解析。任务进度使用 PowerContext 的 SQLite 持久化后端，工程资料使用 seekdb，二者职责独立。模型只可修改任务明确列出的 `src/` 文件，测试和规格不可由模型修改。示例测试覆盖本题声明的订单筛选行为，不声称验证任意第三方业务代码的安全性。
