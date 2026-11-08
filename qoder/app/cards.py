"""Built-in review cards: database fundamentals and research methods."""

from __future__ import annotations

from app.models import ReviewCard

BUILTIN_CARDS: list[ReviewCard] = [
    ReviewCard(
        id="db-btree",
        topic="数据库索引",
        question="B+ 树索引与 B 树索引的主要区别是什么？为什么数据库通常选择 B+ 树？",
        answer="B+ 树的非叶子节点只存键不存数据，所有数据都在叶子节点，且叶子节点用链表相连。"
        "这使得范围查询和顺序访问更高效，磁盘 I/O 次数更少，因此数据库通常选择 B+ 树。",
        difficulty=3,
    ),
    ReviewCard(
        id="db-transaction-acid",
        topic="事务 ACID",
        question="事务的 ACID 属性分别代表什么？",
        answer="Atomicity（原子性）：事务要么全部完成，要么全部回滚。"
        "Consistency（一致性）：事务前后数据库保持一致状态。"
        "Isolation（隔离性）：并发事务互不干扰。"
        "Durability（持久性）：提交后数据永久保存。",
        difficulty=2,
    ),
    ReviewCard(
        id="db-isolation-level",
        topic="隔离级别",
        question="请从低到高列出四种 SQL 标准事务隔离级别，并说明各级别通常可能出现的并发现象。",
        answer="Read Uncommitted → Read Committed → Repeatable Read → Serializable。"
        "较低级别可能出现脏读、不可重复读等现象；Repeatable Read 在多数实现中通过 MVCC 或锁机制"
        "避免了不可重复读，但是否出现幻读取决于具体实现和查询方式。Serializable 通过串行化消除上述现象，但并发性能最低。",
        difficulty=4,
    ),
    ReviewCard(
        id="db-normalization",
        topic="范式",
        question="第三范式（3NF）要求什么？BCNF 与 3NF 有何区别？",
        answer="3NF 要求消除非主属性对候选键的传递依赖（每个非主属性不传递依赖于任何候选键）。"
        "BCNF 更严格：要求每个非平凡函数依赖的决定因素都是超键。"
        "BCNF 消除了主属性对候选键的部分和传递依赖，是 3NF 的加强版。",
        difficulty=3,
    ),
    ReviewCard(
        id="db-sql-join",
        topic="SQL 连接",
        question="INNER JOIN、LEFT JOIN、CROSS JOIN 的结果集有何不同？",
        answer="INNER JOIN 只返回两表匹配的行；LEFT JOIN 返回左表全部行，右表无匹配则补 NULL；"
        "CROSS JOIN 返回两表的笛卡尔积。",
        difficulty=2,
    ),
    ReviewCard(
        id="res-hypothesis",
        topic="科研方法",
        question="科学研究中，零假设（H0）与备择假设（H1）的关系是什么？",
        answer="H0 默认无效果/无差异，H1 是研究者想证明的假设。"
        "统计检验通过计算 p 值判断是否有足够证据拒绝 H0。",
        difficulty=2,
    ),
    ReviewCard(
        id="res-p-value",
        topic="统计检验",
        question="p 值的含义是什么？p < 0.05 是否意味着假设一定成立？",
        answer="p 值是在 H0 为真时，观察到当前或更极端结果的概率。"
        "p < 0.05 只表示在 5% 显著性水平下拒绝 H0，不代表效应大小或实际意义，"
        "也不能证明 H1 一定成立。",
        difficulty=3,
    ),
    ReviewCard(
        id="res-sampling",
        topic="抽样方法",
        question="简单随机抽样、分层抽样和系统抽样的适用场景分别是什么？",
        answer="简单随机抽样适合总体均匀；分层抽样在总体有明显子群且需保证各群代表性时使用；"
        "系统抽样按固定间隔选取，适合名单有序且无周期性的场景。",
        difficulty=3,
    ),
    ReviewCard(
        id="res-bias",
        topic="实验偏差",
        question="选择偏差、幸存者偏差和确认偏差分别是什么？如何减少它们的影响？",
        answer="选择偏差：样本不代表总体，用随机化减少。"
        "幸存者偏差：只看到'存活'样本，需关注缺失数据。"
        "确认偏差：只寻找支持自己观点的证据，应主动寻找反面证据。",
        difficulty=4,
    ),
    ReviewCard(
        id="db-distributed-cap",
        topic="分布式系统",
        question="CAP 定理指出分布式系统最多同时满足哪三个性质？OceanBase 如何选择？",
        answer="CAP：Consistency（一致性）、Availability（可用性）、Partition Tolerance（分区容忍性）。"
        "网络分区不可避免，因此必须在 C 和 A 间取舍。OceanBase 基于 Paxos 协议优先保证一致性和分区容忍性（CP）。",
        difficulty=5,
    ),
    ReviewCard(
        id="res-peer-review",
        topic="同行评审",
        question="同行评审的主要目的和局限性是什么？",
        answer="目的：由领域专家评估研究的质量、原创性和方法严谨性。"
        "局限性：可能引入偏见、耗时长、难以检测精心设计的欺诈、"
        "对跨学科或颠覆性研究可能不够友好。",
        difficulty=2,
    ),
    ReviewCard(
        id="db-wal",
        topic="WAL 机制",
        question="Write-Ahead Logging (WAL) 的基本原理是什么？它如何保证崩溃恢复？",
        answer="WAL 要求在修改数据页之前，先将修改日志写入持久存储。"
        "崩溃恢复时，重做（REDO）已提交但未写入数据页的日志，"
        "撤销（UNDO）未提交的修改，从而保证原子性和持久性。",
        difficulty=4,
    ),
]
