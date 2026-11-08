(function () {
  "use strict";

  var DEMO_CARDS = [
    { topic: "数据库索引", question: "B+ 树索引与 B 树索引的主要区别是什么？" },
    { topic: "事务 ACID", question: "事务的 ACID 属性分别代表什么？" },
    { topic: "隔离级别", question: "请从低到高列出四种事务隔离级别及各级别可能出现的并发问题。" },
    { topic: "范式", question: "第三范式（3NF）要求什么？与 BCNF 有何区别？" },
    { topic: "SQL 连接", question: "INNER JOIN、LEFT JOIN、CROSS JOIN 的结果集有何不同？" },
    { topic: "科研方法", question: "零假设（H0）与备择假设（H1）的关系是什么？" },
    { topic: "统计检验", question: "p 值的含义是什么？p < 0.05 是否意味着假设一定成立？" },
    { topic: "抽样方法", question: "简单随机抽样、分层抽样和系统抽样的适用场景分别是什么？" },
    { topic: "实验偏差", question: "选择偏差、幸存者偏差和确认偏差分别是什么？" },
    { topic: "分布式系统", question: "CAP 定理指出分布式系统最多同时满足哪三个性质？" },
    { topic: "同行评审", question: "同行评审的主要目的和局限性是什么？" },
    { topic: "WAL 机制", question: "Write-Ahead Logging (WAL) 的基本原理是什么？" }
  ];

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderDemoCards() {
    var container = document.getElementById("demo-cards");
    if (!container) return;

    DEMO_CARDS.forEach(function (card) {
      var el = document.createElement("div");
      el.className = "demo-card-item";

      var topicEl = document.createElement("div");
      topicEl.className = "demo-card-topic";
      topicEl.textContent = card.topic;

      var questionEl = document.createElement("div");
      questionEl.className = "demo-card-question";
      questionEl.textContent = card.question;

      el.appendChild(topicEl);
      el.appendChild(questionEl);
      container.appendChild(el);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderDemoCards);
  } else {
    renderDemoCards();
  }
})();
