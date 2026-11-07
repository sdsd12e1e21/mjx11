# 星屿：浏览器本地向量化 × seekdb 混合检索

阶跃星辰赛题实现。文档和查询的 embedding 都在浏览器 Web Worker 中计算；Node API 只接收已生成的向量，通过官方 **seekdb-js（npm 包名 `seekdb`）** 写入和检索。无云端推理、无服务端 embedding、无客户端结果融合或模拟数据库。

## 运行环境

- Node.js 22 或更新版本；Chrome / Edge 最新版，使用 `localhost`（安全上下文，支持 WebGPU）。
- Docker Engine + Compose v2；Windows/macOS 可以使用 Docker Desktop 的 Linux containers。数据库镜像固定为 `oceanbase/seekdb:1.3.0.0-100000092026051510`。建议给 Docker 至少 4 GB 内存。
- 首次需要网络下载 npm 依赖和公开模型。之后可使用本地模型文件；所有推理仍发生在浏览器设备。

## 启动（在 stepfun 目录执行）

```sh
npm ci
npm run db:up
npm run build
npm start
```

打开 **http://localhost:3001**。`db:up` 会等待数据库健康检查，并创建不存在的 `test` 数据库。数据库启动可能需数分钟；失败时运行 `docker compose logs seekdb` 查看原因。停止数据库使用 `docker compose stop`，数据保留在命名卷中。

也可执行一键脚本：Windows PowerShell `./scripts/start.ps1`；Linux/macOS `bash scripts/start.sh`。脚本不安装 Docker、不更改系统配置。

开发模式：先启动数据库，再执行 `npm run dev`，打开 **http://localhost:5173**。前端通过 Vite 代理访问本地 Node API。

### 连接现成的本地 seekdb

复制 `.env.example` 为 `.env`，填写 `SEEKDB_HOST`、`SEEKDB_PORT`、`SEEKDB_USER`、`SEEKDB_PASSWORD`、`SEEKDB_DATABASE`。`.env` 不提交仓库。此时不执行 `db:up`，改为：

```sh
npm ci
npx tsx scripts/init-db.ts
npm run build
npm start
```

API 仅监听本机 `127.0.0.1:3001`。前端从同一服务加载，不需要向浏览器暴露数据库凭据。

## 操作与复现

1. 保持默认 `personal / INT8 / 自动选择`，点击“导入 12 篇示例文档”，或导入 `.txt/.md`、粘贴文字。可多次导入。界面展示本地向量化进度，以及写入和索引刷新阶段。
2. 等待“已就绪”后输入问题，例如“浏览器没有可用显卡时怎么办？”。结果展示原文、文档 ID、分块序号和耗时。
3. 新建 `research` 知识库并导入不同文档，切换后验证结果隔离。相同标题与内容重复导入使用稳定 SHA-256 ID，upsert 不重复增加；修改后的文件视为一个新版本增量追加，不自动删除旧版本。
4. 切换 FP32 会进入同名知识库的独立 FP32 集合，需要重新导入。不能将不同精度/版本的向量混用。
5. 选择“强制 WASM”可验证无 GPU 后端流程；默认自动模式优先尝试 WebGPU，初始化或执行失败时降级至 WASM。两种后端均显示实际名称及降级原因。

## 模型获取与 INT8

固定来源 [Xenova/bge-small-zh-v1.5](https://huggingface.co/Xenova/bge-small-zh-v1.5)，revision **75c43b069aac4d136ba6bc1122f995fedcfd2781**，基于 [BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)。运行时 `@huggingface/transformers@4.3.2`，CLS pooling + L2 normalization，512 维；查询加入模型建议的中文检索前缀，文档不加前缀。

采用该固定版本公开的预量化 `onnx/model_quantized.onnx`，设置 `dtype: 'q8'`；基线使用同一模型的 `onnx/model.onnx` 和 `dtype: 'fp32'`。不把仅序列化向量为整数当成模型量化。发布方量化配置为 per-channel、reduce-range、QInt8，完整配置及 SHA-256 保存于 `reports/model-manifest.json`。

模型由浏览器按固定 revision 下载并缓存。也可先执行：

```sh
npm run models:manifest
npm run build
```

该脚本**只下载和核验模型，不执行推理**，把 FP32/INT8 及 tokenizer 文件存入 `public/models/`，供浏览器本地加载，同时记录实际文件字节数、SHA-256 和压缩比。本地模型及 `node_modules` 不提交 Git；构建时 Vite 将模型拷贝到 `dist/models/`。离线运行需要先完成此步骤。

## seekdb 数据层

- 集合 `edge_<知识库名>_<q8|fp32>_bge75c43b`；名称由白名单约束。
- schema：512 维 cosine HNSW + ngram 全文索引（2 字符），embedding function 明确设为 `null`，所有写入和查询显式传入浏览器向量。
- 保存块 ID、原文、标题、文档 ID、分块序号、模型 ID/revision/精度。320 Unicode 字符一块、重叠 40 字符，模型最大长度 512 token；超长输入最终受 tokenizer 截断保护。
- `collection.hybridSearch` 同时传入全文 `whereDocument.$contains` 与 `knn.queryEmbeddings`，数据库执行 RRF（window=30，constant=60）。Node 仅按数据库已返回顺序序列化，不做两路融合。
- 向量每批 8 条，数据库每批最多 64 条 upsert，完成后 `refresh_index()` 一次，成功后才向用户报告可检索。单进程按集合串行化写入/刷新/搜索，前端操作期间禁用集合切换，并用请求 epoch 丢弃过期响应。
- 单次请求最多 1000 块。导入不是跨批事务；中途失败时可能已有部分数据写入，重新导入同一文件可幂等补齐。不要同时启动多个写入 API 进程。

## 验证与性能测试

```sh
npm test          # 分块、向量校验、状态隔离、指标与并发次序测试
npm run build     # TypeScript 检查和生产构建
npm run test:db   # 必须连接真实 seekdb；测试增量导入、刷新、混合检索和集合隔离
```

浏览器“运行完整对照实验”使用 `src/fixture.ts` 的 12 篇中文文档、8 个带相关文档标注的查询，对比四种配置：FP32/WASM 基线、INT8/自动后端、INT8/WASM，以及 INT8/WASM 的批大小 1 + 逐块刷新对照。各配置 3 次导入、1 轮冷查询及 3 轮后续查询。下载/加载、文档推理、写入、刷新、查询推理、数据库和端到端耗时分阶段记录，报告后续查询中位数和平均 Recall@3/nDCG@3，支持导出全部原始数据。

这里的完整配置对比包含多项变化，不可将其所有性能变化归因于单一优化。“仅验证本地推理”对照中，三组都使用 batch=8，便于固定其他条件比较模型精度与后端，**不计算或冒充数据库检索质量**。`downloadWallMs` 是运行时进度回调的文件获取墙钟区间（可来自本地 HTTP/缓存），`loadMs` 包含文件获取和模型初始化，二者不可相加。首次外网下载与已缓存加载应另开干净浏览器配置分别记录。

### 本次验证范围

- 已通过：生产构建、5 项基础测试、浏览器三种配置真实推理；512 维且单位范数；INT8 实际 WebGPU 和强制 WASM 均运行成功。依赖安装审计为 0 个已知漏洞（安装当时）。
- 已测模型大小：权重 FP32 **94,851,877 B**、INT8 **24,010,842 B**，压缩比 **3.9504×**；计入共同 tokenizer/config 后分别 **95,401,750 B / 24,560,715 B**，压缩比 **3.8843×**。
- 原始浏览器数据：`reports/browser-inference.json`。本机 Windows、Chrome 157、16 个逻辑线程，12 篇文档/8 个查询、batch=8、各 3 次，首次与后续分开记录。完整模型来源和配置见一页技术说明。
- **未完成数据库联调及检索质量/端到端性能实测**：当前电脑没有 Docker/WSL 或现成 seekdb。按用户选择先交付源码和启动脚本，不填写虚构指标。自动降级的真实设备故障注入也未执行；已验证强制 WASM 路径。接通 seekdb 后运行 `test:db` 和完整浏览器实验即可补齐。

技术概要见 [TECHNICAL.md](TECHNICAL.md)。这是可本地启动的源码交付，没有发布在线应用，也未提交比赛平台评分。
