# 实测状态与复现入口

日期：2026-11-08，Asia/Shanghai。

## 已完成

- 在题目指定基线 d647275c308e09b7b623f322a26f5c4e85734fb0 上开发，作品资产全部位于 dify/grudge-shop。
- Dify Cloud 的九节点 Chatflow 已导入、配置并完整试玩。Dify 内置对话记忆保持关闭。
- 本机 PowerContext 官方源码版本 ed8902b234c4111b6f54e66694806430e25be3a9，Windows/Python 3.11.1，使用默认 SQLite 持久化；显式 Memory 与 FTS 召回无需额外模型。
- cloudflared 2026.10.7 从官方来源下载，通过临时 HTTPS 隧道转发本机受 Bearer 密钥保护的网关。PowerContext 8000端口只监听本机，没有直接公网暴露。
- 真实公网网关验证通过：初始为空、写入返回 records、新请求召回此前恶作剧、不同玩家分区隔离、错误密钥返回401。结果见 evidence/powercontext-roundtrip.json；该脚本的回复是固定测试夹具。
- Dify 实际互动验证通过：首次光临 → 偷换罐头 → 新建对话后主动回忆恶作剧 → 道歉后心软 → 继续补偿后获得熟客徽章。每轮界面均显示“工作流运行成功”。这部分是真实 Dify → 公网隧道 → 本机网关 → PowerContext → Dify 模型 → 持久化写入后的完整结果，不是手工填入历史的单节点测试。
- 试玩发现模型会拖延发放徽章，现以明确规则结算结局。四项规则回归测试与 DSL 编码/失败处理检查通过，结局已再次通过完整 Dify 运行验证。
- 经用户明确批准，Dify体验版已发布。公开入口也已发送真实请求并正常收到回复，见 evidence/dify-public-play.*。

体验入口：https://udify.app/chat/eHIpVvwq2zFxqKVT

## 实测证据

- dify-e2e-first.jpg：首次光临，工作流成功。
- dify-e2e-prank.jpg：量子罐头恶作剧及“记仇”反馈。
- dify-e2e-recall.jpg：新对话中主动回忆罐头被换成空气。
- dify-e2e-apology.jpg：道歉与补偿后态度变为“心软”。
- dify-e2e-finale.jpg/txt：固定规则结算，“友好结局·本店最不放心的熟客”及成功状态。
- dify-published.jpg：Dify发布状态。
- dify-public-play.jpg/txt：公开Web入口实际回复。
- powercontext-roundtrip.json：指定技术真实写入与召回记录。

## 复现与边界

按 README 和 LOCAL-DEMO.md 在评审环境重新启动服务、配置模型及网关地址/密钥，再执行 TESTING.md。提交 DSL 保留占位值，不包含作者真实密钥。无需作者已有记忆数据，验证脚本每次使用新玩家。

当前公网地址为临时隧道，作者电脑关机、断网或隧道停止后不可用；重建可能换地址。评审不应依赖作者临时服务存活，材料提供完整本地初始化和复现方式。未部署长期云服务器，也未做容量基准。

全文上下文预算6000字节，长对局早期记录可能被截断，不声称无限记忆。结局是基于明确关键词的小游戏规则，不是一般自然语言任务完成判断。同玩家并发轮次无强顺序保证，写入无 exactly-once 保障，HTTP写入不自动重试。

自部署Dify 1.9.1尚未在本机执行；本次实际运行环境为用户Dify Cloud，使用已有 langgenius/openai/openai 的 gpt-4o-mini。没有记录云端插件的具体版本；评审需配置自己的有效模型供应商凭据。此前单节点测试截图单独保留，不混作完整流程证据。

## 报名仓库

用户确认的团队仓库：https://github.com/sdsd12e1e21/mjx11

仓库原先没有比赛分支，因此从官方比赛基线新建2026-competition-ecosystem分支；不修改既有main、master或其他题目的分支。推送结果以交付说明及实际远程分支为准。测评平台还需填写已推送的分支与commit hash，本次没有代交测评表单。
