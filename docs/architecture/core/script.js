const ARCHITECTURE = {
  root: {
    id: "sebastian-system",
    title: "Sebastian System",
    short: "当前仓库实现 + 架构占位",
    status: "implemented",
    description:
      "这不是概念图中心词，而是当前代码仓库里已经存在的系统边界。点击外围模块展开当前仓库中的真实实现，再用右侧面板看关键文件、上下游与当前状态。",
    mentalModel:
      "先把 Sebastian 当成一台由入口、协议边界、运行时、状态真相和扩展层组成的机器，而不是一堆独立文件。",
    files: [
      {
        label: "sebastian/README.md",
        path: "/Users/ericw/work/code/ai/sebastian/sebastian/README.md",
        note: "后端目录职责总索引",
      },
      {
        label: "ui/mobile/README.md",
        path: "/Users/ericw/work/code/ai/sebastian/ui/mobile/README.md",
        note: "移动端入口与导航结构",
      },
    ],
    children: [
      {
        id: "clients",
        title: "Client Surface",
        short: "App / Web 入口",
        status: "implemented",
        description:
          "用户真正接触到的是 Mobile App。Web 目前更多是辅助管理占位，因此在系统总图里，Client 更像入口层而不是业务中心。",
        mentalModel:
          "客户端不是系统真相，它是 Session / SSE / Task 状态的观察面。",
        flows: ["turn flow", "session stream", "approval UX"],
        files: [
          {
            label: "ui/mobile/README.md",
            path: "/Users/ericw/work/code/ai/sebastian/ui/mobile/README.md",
            note: "主交互入口说明",
          },
        ],
        deps: ["Gateway", "SSE streams", "Session APIs"],
        children: [
          {
            id: "mobile-app",
            title: "ui/mobile",
            short: "Expo / React Native",
            status: "implemented",
            description:
              "Chat、SubAgents、Settings 已形成基础导航骨架，是当前最重要的人机入口。",
            files: [
              {
                label: "ui/mobile/README.md",
                path: "/Users/ericw/work/code/ai/sebastian/ui/mobile/README.md",
                note: "页面结构与 API 边界",
              },
            ],
            deps: ["Gateway routes", "SSEManager"],
          },
          {
            id: "web-ui",
            title: "ui/web",
            short: "辅助管理界面",
            status: "placeholder",
            description:
              "当前不是主入口，但在 Phase 4 以后会更适合承接配置、调试和管理型界面。",
            files: [],
            deps: ["Gateway", "Admin flows"],
          },
        ],
      },
      {
        id: "gateway",
        title: "Gateway",
        short: "REST / SSE / Auth",
        status: "implemented",
        description:
          "Gateway 是所有外部入口的协议边界。它负责把 runtime 暴露成 REST 和 SSE，而不直接承担业务编排。",
        mentalModel:
          "Gateway 只做协议转换和依赖装配，不做核心推理或任务决策。",
        flows: ["POST /turns", "GET /stream", "session routes"],
        files: [
          {
            label: "sebastian/gateway/sse.py",
            path: "/Users/ericw/work/code/ai/sebastian/sebastian/gateway/sse.py",
            note: "SSEManager、缓冲与重放",
          },
          {
            label: "sebastian/gateway/state.py",
            path: "/Users/ericw/work/code/ai/sebastian/sebastian/gateway/state.py",
            note: "runtime 依赖装配",
          },
        ],
        deps: ["Client Surface", "Orchestrator", "EventBus"],
        children: [
          {
            id: "sse-manager",
            title: "SSEManager",
            short: "事件流出口",
            status: "implemented",
            description:
              "SSEManager 维护 event id、500 条缓冲和 session 过滤，是 App 能看到系统活跃状态的关键出口。",
            files: [
              {
                label: "sebastian/gateway/sse.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/gateway/sse.py",
                note: "stream() / _on_event()",
              },
            ],
            deps: ["EventBus", "sessions/{id}/stream", "global stream"],
          },
          {
            id: "gateway-state",
            title: "gateway/state.py",
            short: "依赖拼装",
            status: "implemented",
            description:
              "这里把 session_store、sse_manager、agent_pools 等关键运行时对象装进 GatewayState。",
            files: [
              {
                label: "sebastian/gateway/state.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/gateway/state.py",
                note: "state fields",
              },
            ],
            deps: ["SessionStore", "SSEManager", "AgentPool"],
          },
        ],
      },
      {
        id: "orchestrator",
        title: "Orchestrator",
        short: "Sebastian 总控",
        status: "implemented",
        description:
          "Sebastian 主管家在编排层接住用户意图，并决定什么时候直接回答、什么时候交给 runtime、以及未来何时委派给 Sub-Agent。",
        mentalModel:
          "这里是‘做什么’的入口，而不是‘怎么流式输出’的细节层。",
        files: [
          {
            label: "sebastian/orchestrator/sebas.py",
            path: "/Users/ericw/work/code/ai/sebastian/sebastian/orchestrator/sebas.py",
            note: "Sebastian 主体",
          },
        ],
        deps: ["Gateway", "Core Runtime", "TaskManager"],
        children: [
          {
            id: "sebastian-class",
            title: "Sebastian(BaseAgent)",
            short: "主管家类",
            status: "implemented",
            description:
              "Sebastian 继承 BaseAgent，并接住 conversation、task_manager、session 创建等总控职责。",
            files: [
              {
                label: "sebastian/orchestrator/sebas.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/orchestrator/sebas.py",
                note: "chat() / get_or_create_session()",
              },
            ],
            deps: ["BaseAgent", "TaskManager", "SessionStore"],
          },
          {
            id: "a2a-protocol",
            title: "A2A Delegation",
            short: "未来多 Agent 边界",
            status: "placeholder",
            description:
              "当前总图里要保留它的位置，但还不应该误记成已实现的协作系统。",
            files: [],
            deps: ["TaskManager", "Sub-Agent runtime"],
          },
        ],
      },
      {
        id: "core-runtime",
        title: "Core Runtime",
        short: "推理 / 工具 / 中断",
        status: "implemented",
        description:
          "这里是 Sebastian 的执行心脏。请求在这里被串成 LLM 事件流、工具回注、partial 保存和 Task 状态变更。",
        mentalModel:
          "先分清谁生成事件、谁执行副作用，再谈每个函数细节。",
        files: [
          {
            label: "sebastian/core/base_agent.py",
            path: "/Users/ericw/work/code/ai/sebastian/sebastian/core/base_agent.py",
            note: "副作用边界",
          },
          {
            label: "sebastian/core/agent_loop.py",
            path: "/Users/ericw/work/code/ai/sebastian/sebastian/core/agent_loop.py",
            note: "LLMStreamEvent generator",
          },
        ],
        deps: ["CapabilityRegistry", "SessionStore", "EventBus"],
        children: [
          {
            id: "base-agent",
            title: "BaseAgent",
            short: "run_streaming / interrupt",
            status: "implemented",
            description:
              "BaseAgent 负责 turn.received、历史加载、工具执行、turn.response、turn.interrupted 和 partial 落盘。它是副作用边界。",
            files: [
              {
                label: "sebastian/core/base_agent.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/core/base_agent.py",
                note: "run_streaming() / _stream_inner()",
              },
            ],
            deps: ["AgentLoop", "CapabilityRegistry", "SessionStore", "EventBus"],
          },
          {
            id: "agent-loop",
            title: "AgentLoop",
            short: "async generator",
            status: "implemented",
            description:
              "AgentLoop 把 LLM 输出统一变成 thinking/text/tool/turn_done 事件，不直接触碰 EventBus 或持久化。",
            files: [
              {
                label: "sebastian/core/agent_loop.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/core/agent_loop.py",
                note: "stream() / ToolResult injection",
              },
            ],
            deps: ["CapabilityRegistry", "Anthropic stream API"],
          },
          {
            id: "agent-pool",
            title: "AgentPool",
            short: "固定 worker 池",
            status: "implemented",
            description:
              "每个 agent_type 维持固定 worker 槽位，支持 acquire/release 和 queue_depth，给 UI 和未来记忆系统稳定身份。",
            files: [
              {
                label: "sebastian/core/agent_pool.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/core/agent_pool.py",
                note: "worker slots / queue",
              },
            ],
            deps: ["GatewayState", "SubAgent supervision"],
          },
          {
            id: "task-manager",
            title: "TaskManager",
            short: "状态机与后台任务",
            status: "implemented",
            description:
              "TaskManager 统一 task 提交、合法状态转换、事件发布与 session/index 同步。",
            files: [
              {
                label: "sebastian/core/task_manager.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/core/task_manager.py",
                note: "_transition() / submit()",
              },
            ],
            deps: ["SessionStore", "IndexStore", "EventBus"],
          },
          {
            id: "stream-events",
            title: "stream_events",
            short: "runtime 契约类型",
            status: "implemented",
            description:
              "LLMStreamEvent 族是 BaseAgent 和 AgentLoop 之间的契约层，也是 block 级 UI 表达的基础。",
            files: [
              {
                label: "sebastian/core/stream_events.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/core/stream_events.py",
                note: "ThinkingDelta / ToolCallReady / TurnDone",
              },
            ],
            deps: ["AgentLoop", "BaseAgent", "SSE UI"],
          },
        ],
      },
      {
        id: "store",
        title: "Store",
        short: "文件系统真相",
        status: "implemented",
        description:
          "当前 Sebastian 的真相主要落在文件系统上。Session、Task、Checkpoint 和索引都在这里形成可读、可调试的状态。",
        mentalModel:
          "Store 不是缓存，而是当前阶段最可信的运行状态来源。",
        files: [
          {
            label: "sebastian/store/session_store.py",
            path: "/Users/ericw/work/code/ai/sebastian/sebastian/store/session_store.py",
            note: "Session / messages / tasks / checkpoints",
          },
        ],
        deps: ["Core Runtime", "Gateway routes", "IndexStore"],
        children: [
          {
            id: "session-store",
            title: "SessionStore",
            short: "session 真相",
            status: "implemented",
            description:
              "管理 meta.json、messages.jsonl、tasks/*.json、checkpoints.jsonl，是当前最重要的数据落盘边界。",
            files: [
              {
                label: "sebastian/store/session_store.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/store/session_store.py",
                note: "_session_dir() / get_messages() / create_task()",
              },
            ],
            deps: ["Session model", "TaskManager", "BaseAgent"],
          },
          {
            id: "index-store",
            title: "IndexStore",
            short: "全局索引",
            status: "implemented",
            description:
              "用于支撑 Session 列表和状态检索，让 Gateway 能按全局视角读取会话。",
            files: [
              {
                label: "sebastian/store/index_store.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/store/index_store.py",
                note: "session index maintenance",
              },
            ],
            deps: ["SessionStore", "Gateway list routes"],
          },
          {
            id: "task-store",
            title: "Task files",
            short: "task + checkpoint",
            status: "implemented",
            description:
              "当前任务状态主要以文件形式伴随 Session 存在，而不是独立数据库子系统。",
            files: [
              {
                label: "sebastian/store/session_store.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/store/session_store.py",
                note: "tasks dir + checkpoint append",
              },
            ],
            deps: ["TaskManager", "Session detail UI"],
          },
        ],
      },
      {
        id: "protocol",
        title: "Protocol",
        short: "事件与协作契约",
        status: "implemented",
        description:
          "Protocol 把运行时变化统一变成前后端和未来 Agent 间都能理解的事件与消息协议。",
        files: [
          {
            label: "sebastian/protocol/events/types.py",
            path: "/Users/ericw/work/code/ai/sebastian/sebastian/protocol/events/types.py",
            note: "EventType 定义",
          },
        ],
        deps: ["SSEManager", "BaseAgent", "TaskManager"],
        children: [
          {
            id: "event-types",
            title: "EventType",
            short: "block 级事件",
            status: "implemented",
            description:
              "thinking_block.*、text_block.*、tool_block.* 和 turn / task 事件让 UI 可以稳定重建系统运行。",
            files: [
              {
                label: "sebastian/protocol/events/types.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/protocol/events/types.py",
                note: "Turn / Task / Approval events",
              },
            ],
            deps: ["SSEManager", "ui/mobile"],
          },
          {
            id: "a2a",
            title: "A2A",
            short: "未来协作协议",
            status: "placeholder",
            description:
              "Google A2A 是后续多 Agent 协作的主边界，但当前仓库里还不是实装主线。",
            files: [],
            deps: ["Orchestrator", "Sub-Agent runtime"],
          },
        ],
      },
      {
        id: "capabilities",
        title: "Capabilities",
        short: "Tools / MCP / Skills",
        status: "implemented",
        description:
          "Capability 层负责把系统外部能力统一纳入运行时，包括原生工具、MCP 工具和技能型能力。",
        mentalModel:
          "它是运行时的外脑接口，但不直接管理对话或任务状态。",
        files: [
          {
            label: "sebastian/capabilities/registry.py",
            path: "/Users/ericw/work/code/ai/sebastian/sebastian/capabilities/registry.py",
            note: "统一调用入口",
          },
        ],
        deps: ["AgentLoop", "BaseAgent"],
        children: [
          {
            id: "capability-registry",
            title: "CapabilityRegistry",
            short: "工具统一入口",
            status: "implemented",
            description:
              "原生工具优先，MCP 工具其次，统一暴露给 AgentLoop 作为 tool specs 和 call 接口。",
            files: [
              {
                label: "sebastian/capabilities/registry.py",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/capabilities/registry.py",
                note: "get_all_tool_specs() / call()",
              },
            ],
            deps: ["tools", "mcp tools", "AgentLoop"],
          },
          {
            id: "tools-scan",
            title: "tools / mcps / skills",
            short: "目录扫描注册",
            status: "implemented",
            description:
              "Sebastian 扩展能力的主路径。当前已经有基础扫描注册，未来还会接进 Dynamic Tool Factory。",
            files: [
              {
                label: "sebastian/capabilities/README.md",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/capabilities/README.md",
                note: "能力层说明",
              },
            ],
            deps: ["CapabilityRegistry", "Future dynamic tools"],
          },
        ],
      },
      {
        id: "future",
        title: "Future Systems",
        short: "当前未实装的主轴",
        status: "placeholder",
        description:
          "这些不是当前仓库主干，但必须保留在总图里，否则你很容易在局部开发中忘记系统最终的形态边界。",
        files: [],
        deps: ["Core Runtime", "Orchestrator", "Mobile UX"],
        children: [
          {
            id: "memory",
            title: "Memory",
            short: "working / episodic / semantic",
            status: "placeholder",
            description:
              "当前已有部分目录和早期实现，但完整三层记忆还不是系统主线。",
            files: [
              {
                label: "sebastian/memory/",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/memory",
                note: "未来长期记忆主轴",
              },
            ],
            deps: ["Agent runtime", "Sub-Agent specialization"],
          },
          {
            id: "trigger",
            title: "Trigger",
            short: "主动触发器",
            status: "placeholder",
            description:
              "到 Phase 4 之后，Sebastian 才会真正从被动响应者转成主动执行者。",
            files: [
              {
                label: "sebastian/trigger/",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/trigger",
                note: "主动触发引擎占位",
              },
            ],
            deps: ["TaskManager", "Orchestrator"],
          },
          {
            id: "identity",
            title: "Identity",
            short: "多因素身份",
            status: "placeholder",
            description:
              "Owner / Family / Guest 与抗仿冒体系，是 Phase 5 的真正安全边界。",
            files: [
              {
                label: "sebastian/identity/",
                path: "/Users/ericw/work/code/ai/sebastian/sebastian/identity",
                note: "身份体系占位",
              },
            ],
            deps: ["Gateway auth", "Approvals", "Voice / Face biometrics"],
          },
        ],
      },
    ],
  },
};

const GROUP_COLORS = {
  root: "#77c7ff",
  clients: "#ff9d7a",
  gateway: "#63d6ff",
  orchestrator: "#ffd66e",
  "core-runtime": "#70efc1",
  store: "#7da4ff",
  protocol: "#ff92bf",
  capabilities: "#c7f36f",
  future: "#b7b2ff",
};

function activePathLabel(path) {
  return path.map((item) => item.title).join(" > ");
}

function findNodeById(node, id, path = []) {
  const nextPath = [...path, node];
  if (node.id === id) return { node, path: nextPath };
  for (const child of node.children || []) {
    const found = findNodeById(child, id, nextPath);
    if (found) return found;
  }
  return null;
}

function getBranchId(root, nodeId) {
  if (nodeId === root.id) return "root";
  const path = findNodeById(root, nodeId)?.path || [];
  return path[1]?.id || "root";
}

function buildMapState(root, expandedId, selectedId) {
  const ring = root.children || [];
  const centerX = 900;
  const centerY = 650;
  const ringRadius = 420;

  const expanded = ring.find((item) => item.id === expandedId);
  const focusMode = Boolean(expanded && expanded.children?.length);

  const nodes = [{ ...root, x: centerX, y: focusMode ? 120 : centerY, level: 0, parentId: null }];

  if (!focusMode) {
    ring.forEach((child, index) => {
      nodes.push({
        ...child,
        x:
          centerX
          + Math.cos(((Math.PI * 2) / ring.length) * index - Math.PI / 2) * ringRadius,
        y:
          centerY
          + Math.sin(((Math.PI * 2) / ring.length) * index - Math.PI / 2) * ringRadius,
        level: 1,
        parentId: root.id,
      });
    });
  } else {
    const sideNodes = ring.filter((item) => item.id !== expanded.id);
    const leftNodes = sideNodes.filter((_, index) => index % 2 === 0);
    const rightNodes = sideNodes.filter((_, index) => index % 2 === 1);

    nodes.push({
      ...expanded,
      x: centerX,
      y: 360,
      level: 1,
      parentId: root.id,
      layoutRole: "focus",
    });

    leftNodes.forEach((child, index) => {
      nodes.push({
        ...child,
        x: 200,
        y: 250 + index * 190,
        level: 1,
        parentId: root.id,
        layoutRole: "context",
      });
    });

    rightNodes.forEach((child, index) => {
      nodes.push({
        ...child,
        x: 1600,
        y: 250 + index * 190,
        level: 1,
        parentId: root.id,
        layoutRole: "context",
      });
    });

    const children = expanded.children || [];
    const cols = children.length <= 2 ? children.length : Math.min(3, Math.ceil(Math.sqrt(children.length)));
    const rows = Math.ceil(children.length / cols);
    const xStart = centerX - ((cols - 1) * 260) / 2;
    const yStart = 660 - ((rows - 1) * 190) / 2;

    children.forEach((child, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      nodes.push({
        ...child,
        x: xStart + col * 260,
        y: yStart + row * 190,
        level: 2,
        parentId: expanded.id,
        layoutRole: "child-grid",
      });
    });
  }

  const selected = nodes.find((item) => item.id === selectedId) || root;
  return { nodes, selected, focusMode };
}

function renderFiles(files) {
  if (!files?.length) {
    return '<div class="detail-item">当前层级没有直接绑定具体文件，主要是架构占位。</div>';
  }
  return files
    .map(
      (file) => `
        <a class="file-item" href="file://${file.path}">
          <strong>${file.label}</strong>
          <span>${file.note || ""}</span>
          <code>${file.path}</code>
        </a>
      `
    )
    .join("");
}

function renderSimpleItems(items, emptyText) {
  if (!items?.length) return `<div class="detail-item">${emptyText}</div>`;
  return items.map((item) => `<div class="detail-item">${item}</div>`).join("");
}

function renderInspector(selected, path) {
  const inspector = document.querySelector("[data-inspector]");
  if (!inspector) return;
  inspector.style.setProperty(
    "--panel-accent",
    GROUP_COLORS[getBranchId(ARCHITECTURE.root, selected.id)] || GROUP_COLORS.root
  );
  const statusLabel =
    selected.status === "implemented"
      ? "已实现"
      : selected.status === "wip"
        ? "Phase 1 待补"
        : "未来占位";

  inspector.innerHTML = `
    <div class="detail-header">
      <div class="crumbs">${path.map((item) => `<span>${item.title}</span>`).join("<span>/</span>")}</div>
      <h1>${selected.title}</h1>
      <p>${selected.description || ""}</p>
    </div>

    <div class="status-row">
      <span class="status-badge"><i class="status-dot ${selected.status}"></i>${statusLabel}</span>
      ${selected.short ? `<span class="status-badge">${selected.short}</span>` : ""}
      ${selected.children?.length ? `<span class="status-badge">可展开 ${selected.children.length} 个子模块</span>` : ""}
    </div>

    <div class="detail-card">
      <h3>当前心智模型</h3>
      <p>${selected.mentalModel || "当前层级更适合当成系统坐标节点来看，用来确认它和上下游的边界。"} </p>
    </div>

    <div class="detail-card">
      <h3>关键文件</h3>
      <div class="file-list">${renderFiles(selected.files)}</div>
    </div>

    <div class="detail-card">
      <h3>上下游 / 依赖</h3>
      <div class="detail-list">${renderSimpleItems(selected.deps, "这个层级当前没有额外写入依赖说明。")}</div>
    </div>

    <div class="detail-card">
      <h3>参与的流</h3>
      <div class="detail-list">${renderSimpleItems(selected.flows, "这个模块更偏结构层，而不是独立 flow 节点。")}</div>
    </div>
  `;
}

function drawMap() {
  const root = ARCHITECTURE.root;
  const map = document.querySelector("[data-map]");
  const svg = document.querySelector("[data-map-svg]");
  const viewport = document.querySelector("[data-map-viewport]");
  const world = document.querySelector("[data-map-world]");
  const atlasGrid = document.querySelector("[data-atlas-grid]");
  const toggleInspectorButton = document.querySelector("[data-toggle-inspector]");
  if (!map || !svg || !viewport || !world || !atlasGrid) return;

  let expandedId = "";
  let selectedId = root.id;
  let scale = 0.62;
  let offsetX = 0;
  let offsetY = 0;
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let inspectorCollapsed = false;
  const nodeElements = new Map();

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  const applyView = () => {
    const rect = viewport.getBoundingClientRect();
    const minX = Math.min(0, rect.width - 1800 * scale);
    const minY = Math.min(0, rect.height - 1300 * scale);
    offsetX = clamp(offsetX, minX - 120, 120);
    offsetY = clamp(offsetY, minY - 120, 120);
    world.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
  };

  const centerOn = (x, y, nextScale = scale) => {
    const rect = viewport.getBoundingClientRect();
    scale = clamp(nextScale, 0.45, 1.6);
    offsetX = rect.width / 2 - x * scale;
    offsetY = rect.height / 2 - y * scale;
    applyView();
  };

  const resetViewForState = () => {
    if (expandedId) {
      centerOn(900, 560, 0.78);
    } else {
      centerOn(900, 650, 0.62);
    }
  };

  const zoomAt = (nextScale, clientX, clientY) => {
    const rect = viewport.getBoundingClientRect();
    const localX = clientX - rect.left;
    const localY = clientY - rect.top;
    const worldX = (localX - offsetX) / scale;
    const worldY = (localY - offsetY) / scale;
    scale = clamp(nextScale, 0.45, 1.6);
    offsetX = localX - worldX * scale;
    offsetY = localY - worldY * scale;
    applyView();
  };

  const update = () => {
    const { nodes, selected, focusMode } = buildMapState(root, expandedId, selectedId);
    svg.innerHTML = "";

    const selectedPath = findNodeById(root, selected.id)?.path || [root];
    renderInspector(selected, selectedPath);

    nodes.forEach((node) => {
      if (!node.parentId) return;
      const parent = nodes.find((item) => item.id === node.parentId);
      if (!parent) return;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", `${parent.x}`);
      line.setAttribute("y1", `${parent.y}`);
      line.setAttribute("x2", `${node.x}`);
      line.setAttribute("y2", `${node.y}`);
      line.setAttribute("class", `line ${node.status}`);
      const branchId = getBranchId(root, node.id);
      line.style.stroke = GROUP_COLORS[branchId] || GROUP_COLORS.root;
      if (selected.id !== node.id && selected.id !== parent.id) {
        line.classList.add("dimmed");
      } else {
        line.classList.add("active");
      }
      svg.appendChild(line);
    });

    const nextIds = new Set(nodes.map((node) => node.id));
    for (const [id, element] of nodeElements.entries()) {
      if (!nextIds.has(id)) {
        element.classList.remove("is-ready");
        window.setTimeout(() => element.remove(), 220);
        nodeElements.delete(id);
      }
    }

    nodes.forEach((node) => {
      let button = nodeElements.get(node.id);
      if (!button) {
        button = document.createElement("button");
        button.dataset.nodeId = node.id;
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const currentTarget = event.currentTarget;
          const currentId = currentTarget?.dataset.nodeId;
          if (!currentId) return;
          selectedId = currentId;
          if (currentTarget?.dataset.expandable === "true") {
            expandedId = expandedId === currentId ? "" : currentId;
          }
          update();
          resetViewForState();
        });
        map.appendChild(button);
        nodeElements.set(node.id, button);
      }

      button.className = `map-node ${node.status} ${node.level === 0 ? "root" : ""} ${node.level === 2 ? "child" : ""}`;
      button.classList.add(`group-${getBranchId(root, node.id)}`);
      if (node.layoutRole === "focus") button.classList.add("focused");
      if (node.layoutRole === "context") button.classList.add("contextual");
      if (node.id === selected.id) button.classList.add("is-active");
      button.dataset.nodeId = node.id;
      button.dataset.expandable = String(node.level === 1 && Boolean(node.children?.length));
      button.style.left = `${node.x}px`;
      button.style.top = `${node.y}px`;
      button.innerHTML = `
        <span class="node-title">${node.title}</span>
        <span class="node-meta">${node.short || ""}</span>
        <span class="node-status">${
          node.level === 0
            ? focusMode
              ? "系统锚点"
              : "系统中心"
            : node.children?.length
              ? expandedId === node.id
                ? "点击折叠"
                : "可展开"
              : "模块详情"
        }</span>
      `;
      requestAnimationFrame(() => {
        button.classList.add("is-ready");
      });
    });
  };

  viewport.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".map-node")) return;
    dragging = true;
    startX = event.clientX - offsetX;
    startY = event.clientY - offsetY;
    viewport.classList.add("is-dragging");
  });

  window.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    offsetX = event.clientX - startX;
    offsetY = event.clientY - startY;
    applyView();
  });

  window.addEventListener("pointerup", () => {
    dragging = false;
    viewport.classList.remove("is-dragging");
  });

  viewport.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const delta = event.deltaY < 0 ? 1.08 : 0.92;
      zoomAt(scale * delta, event.clientX, event.clientY);
    },
    { passive: false }
  );

  document.querySelector("[data-zoom-in]")?.addEventListener("click", () => {
    const rect = viewport.getBoundingClientRect();
    zoomAt(scale * 1.12, rect.left + rect.width / 2, rect.top + rect.height / 2);
  });

  document.querySelector("[data-zoom-out]")?.addEventListener("click", () => {
    const rect = viewport.getBoundingClientRect();
    zoomAt(scale * 0.9, rect.left + rect.width / 2, rect.top + rect.height / 2);
  });

  document.querySelector("[data-reset-view]")?.addEventListener("click", () => {
    resetViewForState();
  });

  toggleInspectorButton?.addEventListener("click", () => {
    inspectorCollapsed = !inspectorCollapsed;
    atlasGrid.classList.toggle("is-sidebar-collapsed", inspectorCollapsed);
    toggleInspectorButton.textContent = inspectorCollapsed ? "展开" : "收起";
    window.setTimeout(() => {
      applyView();
      resetViewForState();
    }, 180);
  });

  update();
  resetViewForState();
}

function activateNav() {
  const path = window.location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll("[data-nav]").forEach((link) => {
    if (link.getAttribute("href") === path) link.classList.add("is-active");
  });
}

function bindRoadmapFilters() {
  const buttons = document.querySelectorAll("[data-filter]");
  const cards = document.querySelectorAll("[data-phase]");
  if (!buttons.length || !cards.length) return;

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const filter = button.dataset.filter;
      buttons.forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      cards.forEach((card) => {
        card.hidden = !(filter === "all" || card.dataset.phase === filter);
      });
    });
  });
}

function renderBusDetail(selected) {
  const container = document.querySelector("[data-bus-detail]");
  if (!container || !selected) return;
  const path = findNodeById(ARCHITECTURE.root, selected.id)?.path || [ARCHITECTURE.root];
  const statusLabel =
    selected.status === "implemented"
      ? "已实现"
      : selected.status === "wip"
        ? "Phase 1 待补"
        : "未来占位";

  container.innerHTML = `
    <div class="status-row">
      <span class="status-badge"><i class="status-dot ${selected.status}"></i>${statusLabel}</span>
      ${selected.short ? `<span class="status-badge">${selected.short}</span>` : ""}
    </div>
    <div class="detail-card">
      <div class="crumbs">${path.map((item) => `<span>${item.title}</span>`).join("<span>/</span>")}</div>
      <h3>${selected.title}</h3>
      <p>${selected.description || ""}</p>
    </div>
    <div class="detail-card">
      <h3>关键文件</h3>
      <div class="file-list">${renderFiles(selected.files)}</div>
    </div>
    <div class="detail-card">
      <h3>依赖 / 相邻模块</h3>
      <div class="detail-list">${renderSimpleItems(selected.deps, "当前没有额外依赖说明。")}</div>
    </div>
  `;
}

function initVerticalBusDiagram() {
  const container = document.querySelector("[data-bus-diagram]");
  const rootButton = document.querySelector("[data-bus-root]");
  if (!container || !rootButton) return;

  const root = ARCHITECTURE.root;
  const topLevel = root.children || [];
  let expandedId = "";
  let selectedId = root.id;

  const sideFor = (index) => (index % 2 === 0 ? "left" : "right");

  const render = () => {
    container.innerHTML = "";
    const selected = findNodeById(root, selectedId)?.node || root;
    renderBusDetail(selected);

    topLevel.forEach((branch, index) => {
      const row = document.createElement("div");
      row.className = "bus-row";
      const side = sideFor(index);
      const left = document.createElement("div");
      left.className = "bus-side left";
      const joint = document.createElement("div");
      joint.className = `bus-joint ${side}`;
      const right = document.createElement("div");
      right.className = "bus-side right";
      const branchButton = document.createElement("button");
      branchButton.className = `bus-branch group-${branch.id}`;
      if (selectedId === branch.id) branchButton.classList.add("is-active");
      branchButton.innerHTML = `
        <strong>${branch.title}</strong>
        <span>${branch.short || ""}</span>
      `;
      branchButton.addEventListener("click", () => {
        selectedId = branch.id;
        expandedId = expandedId === branch.id ? "" : branch.id;
        render();
      });

      const tree = document.createElement("div");
      tree.className = `bus-tree ${side}`;

      if (expandedId === branch.id && branch.children?.length) {
        tree.classList.add("is-expanded");
        const childWrap = document.createElement("div");
        childWrap.className = `bus-children ${side}`;
        branch.children.forEach((child) => {
          const childRow = document.createElement("div");
          childRow.className = `bus-child-row ${side}`;
          const childButton = document.createElement("button");
          childButton.className = `bus-child group-${branch.id}`;
          if (selectedId === child.id) childButton.classList.add("is-active");
          childButton.innerHTML = `
            <strong>${child.title}</strong>
            <span>${child.short || ""}</span>
          `;
          childButton.addEventListener("click", (event) => {
            event.stopPropagation();
            selectedId = child.id;
            render();
          });
          childRow.appendChild(childButton);
          childWrap.appendChild(childRow);
        });
        const spine = document.createElement("div");
        spine.className = `bus-spine ${side}`;

        if (side === "left") {
          tree.appendChild(childWrap);
          tree.appendChild(spine);
          tree.appendChild(branchButton);
        } else {
          tree.appendChild(branchButton);
          tree.appendChild(spine);
          tree.appendChild(childWrap);
        }
      } else {
        tree.appendChild(branchButton);
      }

      const slot = side === "left" ? left : right;
      slot.appendChild(tree);

      row.appendChild(left);
      row.appendChild(joint);
      row.appendChild(right);
      container.appendChild(row);
    });
  };

  rootButton.addEventListener("click", () => {
    selectedId = root.id;
    expandedId = "";
    render();
  });

  render();
}

document.addEventListener("DOMContentLoaded", () => {
  activateNav();
  drawMap();
  bindRoadmapFilters();
  initVerticalBusDiagram();
});
