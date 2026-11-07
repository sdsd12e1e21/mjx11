# 阶跃星辰 · 一页技术说明

**实现**：星屿迷你知识库；浏览器 Web Worker + Transformers.js **4.3.2** 完成文档/查询 embedding；本地 Node API 经 seekdb-js **1.4.0** 存储和检索，无云端推理。模型为公开的 [Xenova/bge-small-zh-v1.5](https://huggingface.co/Xenova/bge-small-zh-v1.5)，固定版本 `75c43b069aac4d136ba6bc1122f995fedcfd2781`；CLS pooling、L2 归一化、512 维，查询加中文检索前缀。

**量化**：使用同一发布版本的 FP32 ONNX 与预量化 QInt8 ONNX（per-channel、reduce-range），浏览器显式配置 `dtype: fp32/q8`。逐文件实际下载、计数字节并计算 SHA-256，权重 **94,851,877 → 24,010,842 B，3.9504×**；含相同 tokenizer/config 的配置包 **95,401,750 → 24,560,715 B，3.8843×**。来源与量化配置见 `reports/model-manifest.json`，可运行 `npm run models:manifest` 重现。量化前后检索质量变化待接入真实数据库测量，不由体积推断。

**端侧后端**：自动模式先尝试 `device: webgpu`，初始化或推理失败时重建 `wasm` pipeline，并展示实际后端和原因；可强制 WASM 复测。模型单例复用、浏览器缓存、Worker 串行队列、默认 batch=8；文档 320 字符/块、重叠 40 字符。当前设备已实际运行 FP32/WASM、INT8/WebGPU、INT8/WASM；未对物理设备故障作注入测试。

**seekdb**：每个知识库/模型版本/精度独立集合，cosine HNSW(512) + ngram 全文索引。原文、向量、文档 ID 和块元数据均存 seekdb，服务端 embedding function 设为 null。单次 `hybridSearch` 由数据库执行全文与 KNN 召回、RRF 融合（窗口 30、常数 60），不在客户端拼接。稳定内容 ID + upsert 保证重复导入幂等，64 块/批写入后统一 `refresh_index()`；集合锁覆盖写入/刷新/搜索，前端禁用处理中切换并丢弃过期响应。

**已实测的浏览器推理**（Windows、Chrome 157、16 逻辑线程，固定 12 篇中文文档/8 条查询，三组 batch=8，各重复 3 次，后两次的中位数；模型文件已在本地 HTTP 提供，非首次外网下载）：

| 配置 | 首次加载含初始化 ms | 12 篇文档推理 ms | 8 条查询推理 ms |
|---|---:|---:|---:|
| FP32 / WASM | 2558.3 | 756.25 | 269.45 |
| INT8 / WebGPU | 895.8 | 521.60 | 197.65 |
| INT8 / WASM | 136.8 | 416.90 | 139.00 |

在此小批量样本上，INT8/WASM 文档推理耗时较 FP32/WASM 降低约 **44.9%**；WebGPU 未优于 INT8/WASM，不能外推 GPU 始终更快。首次加载受缓存和顺序影响，不作为纯精度或后端加速结论。原始记录含逐次耗时、维度与范数，见 `reports/browser-inference.json`。

**状态与待测项**：编译及 5 项基础测试通过。按用户要求先交付源码与启动脚本：当前无 Docker/WSL/seekdb，故数据库延迟、端到端查询、Recall@3/nDCG@3 和完整导入检索闭环尚未实测。提供真实数据库集成测试与界面完整实验：12 篇语料、8 个标注查询、4 个配置、1 轮冷查询和 3 轮后续查询；导出原始记录及中位数、平均质量指标。连接 seekdb 后依 README 启动并复测即可补齐，未以模拟数据库或预计算结果替代。
