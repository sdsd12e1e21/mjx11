# 实测状态与提交前剩余工作

记录日期：2026-11-07，Asia/Shanghai。

## 已完成并有证据

1. 基于比赛指定 `2026-competition-ecosystem` 分支创建项目，全部作品资产位于 `dify/grudge-shop/`。
2. 在用户已有 Dify Cloud Chatflow 中成功导入九节点 DSL，应用更名为“记仇杂货铺 · 乌老板的小本本”，保留未发布草稿。原应用包已备份，备份独立于比赛提交包。
3. 本地 `check_dsl.py` 通过：图引用、引号/换行/emoji JSON 编码、空历史、写入失败时停止流程。Python 编译检查通过。
4. 使用官方 PowerContext `ed8902b234c4111b6f54e66694806430e25be3a9`，Windows/Python 3.11.1，真实启动 HTTP Server，默认 SQLite 持久化。`verify.py` 通过实际写入、跨 HTTP 请求召回、玩家分区隔离、网关错误token拒绝。记录见 `evidence/powercontext-roundtrip.json`。
5. Dify Cloud 的 `gpt-4o-mini` 节点单独测试成功：2026-11-07 23:16:55，5.080 秒，774 tokens。手工填入取自同一恶作剧情节的历史摘要，以及“我又来了，你还认得我吗？”。实际回复引用了“上次把借口罐头换成空气的恶作剧”，并给出三种继续选项。截图见 `evidence/dify-model-test.jpg`。

第五项是手工输入历史的模型节点测试，不是网关与 Dify 的端到端运行。第四项的店主台词是固定测试夹具，不是语言模型输出。两项证据分别验证相应组件，不合并声称完整云端试玩成功。

## 尚待完成，不能据此认定已通过赛事完整验收

- 用户暂无公网 PowerContext/网关服务。需要在用户控制的服务器部署 README 中的两个服务和有效 HTTPS 入口，并在 Dify 设置 `GATEWAY_URL`、`GATEWAY_TOKEN`。当前值是不可用占位符。
- 模型供应商在用户当前 Dify Cloud 工作区已可调用；自建评审环境需按 README 重新安装/绑定官方供应商并配置模型凭据。未记录云端插件具体版本，因此不将该工作区状态作为唯一复现依赖。
- 配置可达网关后执行 TESTING.md 的 B 部分，重新导入/检查 DSL，保留从召回到写入全部节点成功、新会话确实复用记录的证据。
- 通过后再发布 Web 应用。本次没有发布未接通服务的作品。
- 将代码推送至赛事登记的团队仓库，再使用该远程仓库真实存在的分支和 commit hash 提测。本次仅生成本地作品和基于指定分支的 Git 补丁，没有推送到报名仓库，也没有向赛事提交结果。

## 已知限制

对局由模型即兴展开，没有固定数值胜负；不同采样可给出不同结局。全文召回预算6000字节，不承诺长对局全部记住。当前小规模单实例网关未做负载测试，不支持同玩家并发轮次的强顺序，也未保证网络重试时记忆写入 exactly-once。请在两个 HTTP 节点保持不自动重试，失败后核对已有记录。

## 提交到报名仓库

本交付提供 Git 补丁，先在团队仓库的比赛分支确认没有未提交改动，再执行（路径按实际文件调整）：

```bash
git switch 2026-competition-ecosystem
git am /path/to/grudge-shop.patch
git push origin 2026-competition-ecosystem
git rev-parse HEAD
```

如果已有本题目录或补丁冲突，先人工核对并合并；不要强制覆盖团队代码。也可以将压缩包中的 `dify/grudge-shop/` 合并到对应目录后正常 commit/push。测评平台的 Branch 和 Commit id 必须来自已推送的报名仓库；本地补丁或导入 Dify 不会自动填入平台。
