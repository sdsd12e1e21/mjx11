# 来源与修改说明

项目起点为 [OceanBase PowerContext 官方仓库](https://github.com/oceanbase/powercontext) 的 `2026-competition-ecosystem` 分支，基线 commit `d647275c308e09b7b623f322a26f5c4e85734fb0`。该分支原始 `minimax/` 为占位目录；本交付新增上下文模块、接入、业务样例、测试、容器配置和记录。

使用公开发布的 [PowerContext 1.2.0](https://pypi.org/project/powercontext/1.2.0/) 的 Memory Runtime 与 SeekDBProfile，依赖通过包安装，未复制或修改其源码；[seekdb Python 库](https://pypi.org/project/pylibseekdb/) 提供原生嵌入式数据库。各依赖保留各自许可，准确版本见锁文件和实际运行记录。

MiniMax 接入遵循 [官方 OpenAI 兼容接口](https://platform.minimax.cn/docs/api-reference/text-openai-api)。当前真实请求被余额不足拒绝，尚无模型生成的业务修改；未用模拟输出替代真实开发记录。上下文模块及验收工具由参赛项目实现。业务规格、5 条订单样例及目标/回归测试均为本项目自建的演示数据，不含真实用户业务数据。

根目录 `.github/workflows/minimax.yml` 为运行本目录验收的辅助入口；项目材料均在 `minimax/` 内。`.gitattributes` 统一跨平台换行，以便源码 SHA-256 与真实模型开发记录一致。
