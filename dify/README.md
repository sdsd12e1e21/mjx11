# Dify 赛题提交入口

作品：**记仇杂货铺 · 乌老板的小本本**，技术组合 **Dify + PowerContext**。

1. [运行说明](grudge-shop/README.md)：安装依赖、启动服务、导入唯一DSL、绑定模型和服务地址。
2. [验收对照](grudge-shop/ACCEPTANCE.md)：按赛题第三、第四部分逐项定位材料。
3. [Dify DSL](grudge-shop/grudge-shop.yml)：实际导出、脱敏并重新导入验证的DSL 0.7.0。
4. [连续验证样例](grudge-shop/TESTING.md)：初始状态、输入顺序、预期、重置方法。
5. [实际运行证据](grudge-shop/evidence/)：Dify成功截图和PowerContext真实写入/召回记录。
6. [免费临时公网部署](grudge-shop/LOCAL-DEMO.md)：让Dify Cloud连接评审自行启动的记忆服务。

实际环境为Dify Cloud（2026-11-08）、OpenAI插件1.1.0、gpt-4o-mini。没有自定义插件、额外知识库、Embedding或Rerank依赖。作者临时在线入口不能代替评审自行复现；真实凭据不包含在提交中。
