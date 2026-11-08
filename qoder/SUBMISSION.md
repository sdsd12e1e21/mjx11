# Qoder 赛题提交与评审入口

- 项目：续学 StudyRelay——会记住进度的复习助手。
- 报名仓库：https://github.com/sdsd12e1e21/mjx11
- 分支：`feat/qoder-study-coach`；项目资产目录：`qoder/`。
- 公开 Qoder Sites 网站：https://studyrelay-3qtjlmas0ke.qoder.zone
- **Qoder 账号 UID：`1686694062281578`**。来源为此前核对过的 Qoder 个人信息页所示阿里云账号 ID；用户已同意补入报名仓库供赛事核验。
- 主要开发会话：`c4e0e483-7235-4a7f-ac2a-d84da5c99548`。
- Sites 发布会话：`dfebd738-4181-45e3-9ea0-41fb78387094`。

## 三、验收标准对应材料

| 验收项 | 入口与核对方式 |
|---|---|
| 网站可访问 | 上述 Qoder Sites 完整网址；公开发布凭证与无 Cookie 访问记录见 [PUBLICATION.json](evidence/PUBLICATION.json) |
| 项目能够运行 | [README.md](README.md) 从安装、环境变量、真实 PowerContext 部署到启动；[VALIDATION.md](VALIDATION.md) 提供初始数据、输入、步骤和预期结果 |
| Qoder 开发可核对 | [QODER_DEVELOPMENT.md](QODER_DEVELOPMENT.md)、[QODER_TRANSCRIPT.md](evidence/QODER_TRANSCRIPT.md)、[qoder-events.json](evidence/qoder-events.json)、[开发记录截图](evidence/QODER_DEVELOPMENT_VIEW.jpg) 和上面的 UID/真实会话 ID |
| 技术结合有效 | 偏好与复习记录实际写入 PowerContext Atomic Memory，读取结果参与后续排程；[LIVE_VALIDATION.json](evidence/LIVE_VALIDATION.json) 包含真实 scope/artifact/revision，验证空间隔离、去重及重启恢复 |

开发记录截图是实际 CLI 日志查看器的截图，非 IDE 原生截图；原始会话可按 ID 核对。主要功能由 Qoder CLI 编写，Codex 的联调与本次启动/测试修正分别记录在验证文档中，不冒充 Qoder 操作。

## 四、提交材料

1. 网站完整网址：见本文件顶部；网站用于作品展示，主要应用按 README 在本地运行。
2. 完整源码：本分支 `qoder/`，包含后端、前端、展示站、锁定依赖、启动脚本、配置模板与测试。
3. 运行说明：[README.md](README.md)。
4. 可执行验证样例：[VALIDATION.md](VALIDATION.md)；原有实际执行结果：[FINAL_VERIFICATION.md](evidence/FINAL_VERIFICATION.md)、[LIVE_VALIDATION.json](evidence/LIVE_VALIDATION.json)；本次修正验证：[ACCEPTANCE_FIX_VERIFICATION.md](evidence/ACCEPTANCE_FIX_VERIFICATION.md)。
5. Qoder 开发记录：上表所列对话、截图与 UID。
6. 使用效果材料为鼓励项：本作品当前提供合成场景的功能验证，不虚构真实用户人数、问卷或提效统计。

## 五、提交方式

当前平台弹窗只有固定仓库、Commit id、Branch、作品链接，没有 UID 或附件栏。因此将 UID 与其余材料随源码交付到本仓库，方便评审从指定 commit 读取。文档与表单的差异在此明确记录；如主办方另有 UID 专用补交通道，应按其要求补交。

- 代码仓库：保持报名仓库默认值。
- Commit id：填写本次修复推送后的完整 40 位 SHA，不能填写旧的 `11ae532e4cb491d171cd0ec8be0e1503612c70c2`。
- Branch：`feat/qoder-study-coach`。
- 作品链接：`https://studyrelay-3qtjlmas0ke.qoder.zone`。

提交前以不带 Cookie/授权头的请求检查网站；提测成功后应在平台记录中核对新 SHA、分支和网址。保持站点公开运行；仅修改本地展示站源码不会更新已发布网站。本次启动和测试修正不改变已发布展示站内容。
