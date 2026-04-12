# Composer 组件重构与 Session Cancel 闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构主对话页输入区为可扩展 Composer 组件，同时修复停止按钮的完整前后端取消闭环。

**Architecture:** 后端新增 `BaseAgent.cancel_session()` + `POST /sessions/{id}/cancel` 路由实现 session 级取消；前端新建 `src/components/composer/` 目录承载多按钮输入组件，按 sessionId 隔离思考开关状态，通过 `onLayout` 动态调整对话区底部 padding 防止内容被遮挡。

**Tech Stack:** Python 3.12+ / FastAPI / asyncio（后端）；React Native / Expo / Zustand / react-native-svg（前端）

---

## File Map

| 动作 | 文件 |
|---|---|
| 改 | `sebastian/protocol/events/types.py` |
| 改 | `sebastian/core/base_agent.py` |
| 改 | `sebastian/gateway/routes/sessions.py` |
| 改 | `tests/unit/test_base_agent.py` |
| 改 | `tests/integration/test_gateway_sessions.py` |
| 改 | `ui/mobile/src/components/common/Icons.tsx` |
| 新 | `ui/mobile/src/store/composer.ts` |
| 新 | `ui/mobile/src/components/composer/types.ts` |
| 新 | `ui/mobile/src/components/composer/constants.ts` |
| 新 | `ui/mobile/src/components/composer/InputTextArea.tsx` |
| 新 | `ui/mobile/src/components/composer/ThinkButton.tsx` |
| 新 | `ui/mobile/src/components/composer/SendButton.tsx` |
| 新 | `ui/mobile/src/components/composer/ActionsRow.tsx` |
| 新 | `ui/mobile/src/components/composer/index.tsx` |
| 新 | `ui/mobile/src/components/composer/README.md` |
| 改 | `ui/mobile/src/api/turns.ts` |
| 改 | `ui/mobile/src/hooks/useConversation.ts` |
| 改 | `ui/mobile/src/components/conversation/ConversationView.tsx` |
| 改 | `ui/mobile/app/index.tsx` |
| 删 | `ui/mobile/src/components/chat/MessageInput.tsx` |
| 改 | `ui/mobile/README.md` |
| 改 | `ui/mobile/src/components/common/README.md`（若存在）|

---

## Task 1: Icons.tsx — 补齐全部图标

**Files:**
- Modify: `ui/mobile/src/components/common/Icons.tsx`

- [ ] **Step 1: 在 Icons.tsx 末尾追加 8 个新图标**

读取现有 `Icons.tsx`，在文件末尾追加以下内容（保留原有 3 个图标不变）：

```tsx
// ========== 导航/操作 ==========

// Path data from src/assets/icons/close.svg
export function CloseIcon({ size = 20, color = '#999', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M512.201 448.08L885.643 74.638c42.426-42.426 106.066 21.214 63.64 63.64L575.84 511.719l374.353 374.353c42.426 42.427-21.213 106.066-63.64 63.64L512.201 575.359 137.848 949.712c-42.426 42.426-106.066-21.213-63.64-63.64L448.563 511.72 75.12 138.278c-42.427-42.426 21.213-106.066 63.64-63.64L512.2 448.08z"
        fill={color}
      />
    </Svg>
  );
}

// Path data from src/assets/icons/up_down.svg  (viewBox is non-square: 1463×1024)
export function UpDownIcon({ size = 16, color = '#999', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1463 1024" style={style}>
      <Path
        d="M428.324571 353.572571 695.003429 92.306286c20.772571-20.187429 54.272-20.187429 75.044571 0l266.678857 261.266286c20.772571 20.333714 20.772571 53.248 0 73.435429-20.626286 20.333714-54.272 20.333714-75.044571 0L732.452571 202.605714 503.369143 427.008c-20.772571 20.333714-54.272 20.333714-75.044571 0C407.698286 406.820571 407.698286 373.906286 428.324571 353.572571z"
        fill={color}
      />
      <Path
        d="M1036.580571 669.110857 770.048 930.377143c-20.772571 20.187429-54.272 20.187429-75.044571 0L428.324571 669.110857c-20.772571-20.333714-20.772571-53.248 0-73.435429 20.626286-20.333714 54.272-20.333714 75.044571 0l229.083429 224.548571 229.083429-224.548571c20.772571-20.333714 54.272-20.333714 75.044571 0C1057.353143 616.009143 1057.353143 648.777143 1036.580571 669.110857z"
        fill={color}
      />
    </Svg>
  );
}

// ========== 状态/进度 ==========

// Path data from src/assets/icons/cycle_progress.svg
// Ring (background) uses fixed light gray; arc uses color prop.
export function CycleProgressIcon({ size = 16, color = '#12C39B', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M512 1017C233.53 1017 7 790.48 7 512S233.53 7 512 7s505 226.54 505 505-226.51 505-505 505z m0-884.36c-209.18 0-379.34 170.16-379.34 379.34S302.83 891.34 512 891.34 891.35 721.18 891.35 512 721.19 132.66 512 132.66z"
        fill="#DEDEE1"
      />
      <Path
        d="M926.92 728.41a62.91 62.91 0 0 1-59-84.61A379.14 379.14 0 0 0 891.35 512c0-209.18-170.16-379.34-379.34-379.34A62.84 62.84 0 1 1 512 7c278.48 0 505 226.54 505 505a504.34 504.34 0 0 1-31.16 175.3 62.88 62.88 0 0 1-58.92 41.11z"
        fill={color}
      />
    </Svg>
  );
}

// Path data from src/assets/icons/eye_open.svg
export function EyeOpenIcon({ size = 20, color = '#444', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M512 298.666667c-162.133333 0-285.866667 68.266667-375.466667 213.333333 89.6 145.066667 213.333333 213.333333 375.466667 213.333333s285.866667-68.266667 375.466667-213.333333c-89.6-145.066667-213.333333-213.333333-375.466667-213.333333z m0 469.333333c-183.466667 0-328.533333-85.333333-426.666667-256 98.133333-170.666667 243.2-256 426.666667-256s328.533333 85.333333 426.666667 256c-98.133333 170.666667-243.2 256-426.666667 256z m0-170.666667c46.933333 0 85.333333-38.4 85.333333-85.333333s-38.4-85.333333-85.333333-85.333333-85.333333 38.4-85.333333 85.333333 38.4 85.333333 85.333333 85.333333z m0 42.666667c-72.533333 0-128-55.466667-128-128s55.466667-128 128-128 128 55.466667 128 128-55.466667 128-128 128z"
        fill={color}
      />
    </Svg>
  );
}

// Path data from src/assets/icons/eye_close.svg
export function EyeCloseIcon({ size = 20, color = '#444', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M332.8 729.6l34.133333-34.133333c42.666667 12.8 93.866667 21.333333 145.066667 21.333333 162.133333 0 285.866667-68.266667 375.466667-213.333333-46.933333-72.533333-102.4-128-166.4-162.133334l29.866666-29.866666c72.533333 42.666667 132.266667 106.666667 183.466667 192-98.133333 170.666667-243.2 256-426.666667 256-59.733333 4.266667-119.466667-8.533333-174.933333-29.866667z m-115.2-64c-51.2-38.4-93.866667-93.866667-132.266667-157.866667 98.133333-170.666667 243.2-256 426.666667-256 38.4 0 76.8 4.266667 110.933333 12.8l-34.133333 34.133334c-25.6-4.266667-46.933333-4.266667-76.8-4.266667-162.133333 0-285.866667 68.266667-375.466667 213.333333 34.133333 51.2 72.533333 93.866667 115.2 128l-34.133333 29.866667z m230.4-46.933333l29.866667-29.866667c8.533333 4.266667 21.333333 4.266667 29.866666 4.266667 46.933333 0 85.333333-38.4 85.333334-85.333334 0-12.8 0-21.333333-4.266667-29.866666l29.866667-29.866667c12.8 17.066667 17.066667 38.4 17.066666 64 0 72.533333-55.466667 128-128 128-17.066667-4.266667-38.4-12.8-59.733333-21.333333zM384 499.2c4.266667-68.266667 55.466667-119.466667 123.733333-123.733333 0 4.266667-123.733333 123.733333-123.733333 123.733333zM733.866667 213.333333l29.866666 29.866667-512 512-34.133333-29.866667L733.866667 213.333333z"
        fill={color}
      />
    </Svg>
  );
}

// ========== Composer 专用 ==========

// Path data from src/assets/icons/send_msg.svg
export function SendIcon({ size = 18, color = '#fff', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M512 0c282.752 0 512 229.248 512 512s-229.248 512-512 512S0 794.752 0 512 229.248 0 512 0z m-31.274667 292.906667L316.16 457.472a46.506667 46.506667 0 0 0 65.834667 65.834667l87.466666-87.466667v336.170667a46.506667 46.506667 0 0 0 93.056 0v-331.52l82.773334 82.773333a46.506667 46.506667 0 0 0 65.834666-65.792L546.56 292.906667a46.506667 46.506667 0 0 0-65.834667 0z"
        fill={color}
      />
    </Svg>
  );
}

// Path data from src/assets/icons/stop_circle.svg
export function StopCircleIcon({ size = 18, color = '#fff', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M512 42.666667C252.793333 42.666667 42.666667 252.793333 42.666667 512s210.126667 469.333333 469.333333 469.333333 469.333333-210.126667 469.333333-469.333333S771.206667 42.666667 512 42.666667z m213.333333 645.333333a37.373333 37.373333 0 0 1-37.333333 37.333333H336a37.373333 37.373333 0 0 1-37.333333-37.333333V336a37.373333 37.373333 0 0 1 37.333333-37.333333h352a37.373333 37.373333 0 0 1 37.333333 37.333333z"
        fill={color}
      />
    </Svg>
  );
}

// Path data from src/assets/icons/think_icon.svg  (two-path brain icon)
export function ThinkIcon({ size = 16, color = '#999', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M780.826947 178.741895c17.165474 23.174737 25.222737 51.873684 22.689685 80.599579-0.215579 1.455158-0.377263 2.910316-0.646737 4.365473a130.101895 130.101895 0 0 1 79.009684 23.686737c55.969684 39.828211 77.446737 116.466526 60.227368 181.140211a132.096 132.096 0 0 1-41.067789 66.371368c2.802526 2.586947 5.551158 5.389474 8.138105 8.29979a127.838316 127.838316 0 0 1 31.258948 87.632842 170.711579 170.711579 0 0 1-36.45979 96.390737c-20.641684 28.052211-48.101053 54.568421-83.186526 63.083789-5.632 1.347368-11.344842 2.155789-17.111579 2.371368 0.431158 12.773053-1.724632 25.492211-6.305684 37.429895a151.255579 151.255579 0 0 1-66.640843 74.374737 173.325474 173.325474 0 0 1-77.446736 20.210526 169.175579 169.175579 0 0 1-81.461895-14.928842 79.279158 79.279158 0 0 1-46.376421-68.015158v-46.672842l-0.10779-125.035789c-0.134737-163.570526-0.323368-327.141053-0.538947-490.765474V167.612632c0-0.700632 0-1.347368 0.080842-2.048 1.616842-33.630316 27.486316-56.481684 57.721263-68.096 36.378947-14.012632 78.066526-5.362526 112.262737 10.13221a220.106105 220.106105 0 0 1 85.962105 71.168z m-155.621052 687.50821c14.255158 1.482105 26.138947 1.293474 39.073684-0.134737l2.317474-0.40421c8.003368-1.239579 20.291368-4.096 25.680842-6.602105 5.389474-2.479158 10.617263-5.362526 15.602526-8.623158 1.401263-0.862316 2.694737-1.805474 4.096-2.694737l1.536-1.158737c5.093053-4.042105 9.862737-8.461474 14.309053-13.20421 0.970105-1.104842 4.473263-5.335579 5.200842-6.117053a95.420632 95.420632 0 0 0 7.895579-13.123369c-0.727579 1.212632 2.101895-5.578105 2.586947-7.437473 0.458105-1.428211 1.293474-6.278737 1.616842-7.599158a79.764211 79.764211 0 0 0-0.080842-9.081263 56.050526 56.050526 0 0 0-3.422316-11.587369 95.797895 95.797895 0 0 0-7.68-12.746105c1.509053 2.236632-2.101895-2.506105-2.694737-3.179789a29.076211 29.076211 0 0 1 0-40.852211 29.911579 29.911579 0 0 1 41.418106 0c1.940211 1.940211 3.934316 3.799579 6.03621 5.551158-0.053895-0.269474 5.335579 3.664842 6.817684 4.527158 1.131789 0.565895 2.263579 1.104842 3.422316 1.616842 1.670737 0.592842 6.521263 1.428211 8.138106 1.778526 1.967158 0 3.907368 0 5.928421-0.107789a66.56 66.56 0 0 0 10.401684-2.910316c5.605053-2.640842 10.913684-5.820632 15.898947-9.485474 7.168-5.874526 13.797053-12.395789 19.833263-19.402105l2.586948-3.098947a207.575579 207.575579 0 0 0 22.986105-37.591579l0.997053-2.586948c2.425263-6.736842 4.284632-13.662316 5.497263-20.695579 0.754526-6.790737 0.835368-13.608421 0.269473-20.399157-0.215579-0.754526-0.916211-5.874526-1.320421-7.437474a100.163368 100.163368 0 0 0-4.096-13.338948 91.701895 91.701895 0 0 0-6.925473-12.126315c0.107789 0.377263-4.122947-4.904421-5.497263-6.305685a76.261053 76.261053 0 0 0-3.368422-3.152842c-0.673684-0.431158-4.392421-3.260632-5.766736-4.096a73.862737 73.862737 0 0 0-6.925474-3.718736 87.525053 87.525053 0 0 0-5.416421-1.724632c-1.751579-0.512-7.653053-1.536-8.650105-1.832421a104.690526 104.690526 0 0 0-9.350737-0.242526 28.887579 28.887579 0 1 1 0-57.748211l3.934316-0.323368c5.632-0.997053 11.156211-2.452211 16.545684-4.365474a65.859368 65.859368 0 0 0 27.082105-20.533895c4.042105-5.658947 7.545263-11.668211 10.374737-18.000842 2.667789-7.033263 4.634947-14.309053 5.874526-21.719579-0.080842 0 0.754526-6.602105 0.889263-8.353684 0.538947-9.027368 0.269474-18.081684-0.835368-27.082105l-0.538947-2.910316a168.798316 168.798316 0 0 0-6.25179-24.791579c-0.458105-1.347368-2.425263-6.144-2.910316-7.491368a122.179368 122.179368 0 0 0-8.111158-14.632422l-2.694736-4.015157-1.347369-1.805474a112.128 112.128 0 0 0-11.722105-11.910737c-0.970105-0.916211-1.940211-1.724632-2.991158-2.613895a110.376421 110.376421 0 0 0-15.602526-9.162105l-1.293474-0.592842a102.669474 102.669474 0 0 0-18.782316-5.12 101.672421 101.672421 0 0 0-17.92-0.080842h-0.754526c-6.332632 1.077895-12.557474 2.775579-18.593684 5.039158-1.589895 0.700632-3.072 1.509053-4.661895 2.290526a107.870316 107.870316 0 0 0-11.183158 6.736842l-3.179789 2.452211a30.100211 30.100211 0 0 1-41.418106 0 28.725895 28.725895 0 0 1 0-40.879158c4.904421-4.042105 9.512421-8.461474 13.770106-13.204211l1.077894-1.293473c2.263579-3.098947 4.365474-6.332632 6.25179-9.701053 0.592842-1.077895 1.886316-3.853474 2.613895-5.308632 1.428211-3.961263 2.56-8.003368 3.341473-12.126315a84.399158 84.399158 0 0 0 0-13.877895 92.267789 92.267789 0 0 0-4.715789-16.437895 113.448421 113.448421 0 0 0-12.261053-20.210526 176.909474 176.909474 0 0 0-20.641684-20.857263l-4.554105-3.772632-2.048-1.616842c-3.557053-2.613895-7.168-5.12-10.832842-7.545263a197.578105 197.578105 0 0 0-25.061053-14.174316l-3.422316-1.401263a138.778947 138.778947 0 0 0-25.626947-6.979369l-0.323369-0.080842a116.682105 116.682105 0 0 0-21.773473-0.107789c-5.146947 0.916211-10.24 2.263579-15.171369 4.015158-2.452211 1.185684-4.850526 2.506105-7.221895 3.907368-0.107789 0.215579-4.419368 3.584-5.766736 5.012211l-0.188632 0.188631a23.983158 23.983158 0 0 0-1.293474 2.15579 26.812632 26.812632 0 0 0-0.997052 2.694737v0.754526l0.161684 137.485474 0.296421 286.585263 0.188632 246.864842c-0.080842 4.500211 0.350316 7.275789 1.239579 8.353684 1.562947 2.964211 3.368421 5.658947 9.189052 9.674105 3.395368 1.994105 16.653474 8.488421 30.908632 9.943579zM94.962526 340.884211a139.237053 139.237053 0 0 1 61.44-62.517895 132.742737 132.742737 0 0 1 64.026948-14.551579 122.179368 122.179368 0 0 1 21.072842-83.671579 220.321684 220.321684 0 0 1 84.776421-71.545263 150.905263 150.905263 0 0 1 112.936421-11.722106c30.989474 10.590316 57.532632 35.004632 59.176421 68.688843 0.053895 0.673684 0.080842 1.401263 0.080842 2.101894l-0.646737 670.989474a79.575579 79.575579 0 0 1-41.822316 68.823579 156.402526 156.402526 0 0 1-80.222315 17.515789 182.218105 182.218105 0 0 1-77.850948-17.542736 149.800421 149.800421 0 0 1-67.045052-65.724632 103.450947 103.450947 0 0 1-11.452632-48.936421 87.444211 87.444211 0 0 1-24.522105-4.527158 168.205474 168.205474 0 0 1-81.596632-69.335579 161.630316 161.630316 0 0 1-30.477473-96.094316 125.035789 125.035789 0 0 1 36.217263-84.88421c1.024-0.997053 2.074947-1.967158 3.152842-2.937263a106.253474 106.253474 0 0 1-6.521263-5.928421A143.252211 143.252211 0 0 1 76.530526 442.745263c-3.610947-35.031579 2.802526-70.359579 18.53979-101.861052l-0.053895-0.053895z m90.516211 225.091368a76.692211 76.692211 0 0 0-10.078316 2.883368l-2.96421 1.482106a75.722105 75.722105 0 0 0-7.599158 4.581052l-0.269474 0.161684-1.886316 1.670737c-2.209684 1.940211-4.311579 4.042105-6.305684 6.224842l-0.538947 0.646737-2.15579 2.856421c-1.643789 2.479158-3.179789 5.039158-4.608 7.68-0.997053 1.913263-1.886316 3.907368-2.775579 5.901474a104.96 104.96 0 0 0-4.446316 16.976842l-0.269473 2.533053c-0.458105 6.521263-0.377263 13.069474 0.269473 19.563789 1.536 8.838737 4.069053 17.461895 7.545264 25.734737 4.931368 9.808842 10.563368 19.267368 16.815157 28.294737l3.610948 5.01221 1.131789 1.428211c6.656 8.165053 14.066526 15.710316 22.096842 22.501053-0.565895-0.592842 5.200842 3.718737 6.76379 4.661894 3.233684 2.021053 6.521263 3.826526 9.943579 5.470316l3.772631 1.293474c1.536 0.458105 3.072 0.862316 4.608 1.185684 0.646737 0 5.416421 0.592842 7.27579 0.592842 0.916211 0 1.859368-0.080842 2.775579-0.188631 2.586947-0.538947 5.093053-1.266526 7.545263-2.236632 2.694737-1.401263 5.281684-2.937263 7.787789-4.634947l1.293474-1.077895a125.574737 125.574737 0 0 0 5.658947-5.335579 29.911579 29.911579 0 0 1 41.445053 0c11.156211 11.317895 11.156211 29.480421 0 40.771368l-2.910316 3.530106-2.398315 3.47621c-2.425263 3.503158-4.419368 7.275789-6.009264 11.210105a155.594105 155.594105 0 0 0-1.616842 5.389474l-0.40421 1.886316a46.241684 46.241684 0 0 0-0.592842 10.859789c0.134737-0.619789 1.158737 6.009263 1.643789 7.895579 0.377263 1.455158 2.371368 6.467368 2.586947 7.383579 2.344421 4.581053 4.985263 8.946526 7.949474 13.123369-0.808421-1.293474 3.907368 4.769684 5.200842 6.117052 4.149895 4.500211 8.623158 8.677053 13.41979 12.503579 0.107789 0 5.093053 3.637895 6.494316 4.581053 12.234105 8.488421 26.462316 13.743158 41.283368 15.225263l1.886316 0.269474c12.530526 1.455158 25.168842 1.562947 37.726316 0.350315 12.530526-1.185684 15.36-2.209684 24.495157-5.658947 5.524211-2.425263 10.482526-5.928421 14.794106-10.428631 3.449263-4.311579 3.637895-7.114105 3.637894-8.272843v-26.597052c0-62.787368 0.053895-125.547789 0.161685-188.281263-0.538947-144.303158-0.458105-217.896421 0.215579-220.725895l0.107789-71.033263 0.188632-165.376v-3.233684l-0.538948-1.886316-0.808421-1.293474c-0.700632-0.700632-3.584-4.176842-4.931368-5.416421l-0.269474-0.269474-1.643789-1.024a71.949474 71.949474 0 0 0-7.329685-4.015158 91.674947 91.674947 0 0 0-15.171368-3.961263 111.077053 111.077053 0 0 0-21.638737 0.10779l-0.377263 0.080842c-8.380632 1.347368-16.599579 3.530105-24.576 6.467368l-4.554105 1.886316c-11.317895 5.281684-22.096842 11.641263-32.148211 18.997895l-2.775579 2.021052-2.910316 2.236632a166.804211 166.804211 0 0 0-25.249684 24.683789 115.253895 115.253895 0 0 0-12.207158 20.210527 88.387368 88.387368 0 0 0-4.742736 16.437895c-0.350316 3.907368-0.404211 7.814737-0.134737 11.722105 0.242526 1.509053 0.646737 4.554105 0.943158 5.847579a72.757895 72.757895 0 0 0 2.344421 7.787789l0.458105 1.347369 0.40421 0.700631c1.886316 4.015158 4.176842 7.814737 6.709895 11.479579 0.754526 0.943158 2.721684 3.449263 3.557053 4.365474 3.934316 4.365474 8.192 8.407579 12.746105 12.126316a28.672 28.672 0 0 1 0 40.825263 30.181053 30.181053 0 0 1-41.418105 0l-2.101895-1.697684-0.646737-0.458106a109.163789 109.163789 0 0 0-16.249263-9.323789l-3.314526-1.158737a97.495579 97.495579 0 0 0-15.333053-3.907368l-3.610947-0.269474a95.312842 95.312842 0 0 0-9.970527-0.053895l-5.982315 0.538948a102.4 102.4 0 0 0-12.746106 3.125894l-4.069052 1.401263-0.565895 0.269474a106.765474 106.765474 0 0 0-17.192421 9.83579c-5.470316 4.473263-10.509474 9.431579-15.009684 14.874947l-1.13179 1.509053a120.993684 120.993684 0 0 0-11.371789 19.86021l-1.158737 2.937263c-3.206737 9.162105-5.685895 18.593684-7.410526 28.16l-0.727579 4.500211a144.599579 144.599579 0 0 0-0.080842 32.229052l0.754526 4.419369c1.401263 6.790737 3.368421 13.473684 5.874526 19.941052l1.050948 2.101895c1.562947 3.233684 3.314526 6.332632 5.200842 9.377684 0.808421 1.401263 4.015158 5.551158 4.769684 6.736843 3.476211 4.015158 7.275789 7.68 11.398737 10.994526l0.754526 0.512c4.203789 2.883368 8.623158 5.416421 13.285053 7.545263 5.739789 2.101895 11.668211 3.664842 17.704421 4.661895l3.233684 0.269473a28.887579 28.887579 0 1 1 0 57.721264 99.974737 99.974737 0 0 0-10.105263 0.296421l-3.287579 0.619789v0.134737z"
        fill={color}
      />
      <Path
        d="M264.299789 407.794526a26.112 26.112 0 0 1 32.282948-17.946947c48.801684 13.931789 81.300211 72.192 81.30021 138.24 0 62.410105-28.968421 118.029474-73.674105 135.706947-1.616842 0.646737-3.233684 1.212632-4.904421 1.751579a26.112 26.112 0 0 1-18.216421-48.882526l3.907368-1.428211c22.177684-8.784842 40.690526-44.274526 40.690527-87.120842 0-43.573895-19.051789-79.117474-41.229474-87.336421l-2.209684-0.727579a26.112 26.112 0 0 1-17.946948-32.282947z m481.226106 0a26.112 26.112 0 0 0-32.282948-17.946947c-48.828632 13.931789-81.327158 72.192-81.327158 138.24 0 62.410105 28.995368 118.029474 73.674106 135.706947 1.616842 0.646737 3.260632 1.239579 4.904421 1.751579a26.112 26.112 0 0 0 18.243368-48.882526l-3.934316-1.428211c-22.177684-8.784842-40.663579-44.274526-40.663579-87.120842 0-43.573895 19.051789-79.117474 41.229474-87.336421L727.578947 440.050526a26.112 26.112 0 0 0 17.946948-32.282947z"
        fill={color}
      />
    </Svg>
  );
}
```

- [ ] **Step 2: 验证文件编译无报错**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

Expected: 无 Icons.tsx 相关错误。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/common/Icons.tsx
git commit -m "feat(icons): 补齐全部 11 个图标到 Icons.tsx

新增 CloseIcon, UpDownIcon, CycleProgressIcon, EyeOpenIcon, EyeCloseIcon,
SendIcon, StopCircleIcon, ThinkIcon，全部使用 inline Svg/Path 模式

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: 后端 — EventType.TURN_CANCELLED

**Files:**
- Modify: `sebastian/protocol/events/types.py`

- [ ] **Step 1: 在 EventType 的 Conversation 区块新增一行**

在 `TURN_RESPONSE = "turn.response"` 之后追加：

```python
    TURN_CANCELLED = "turn.cancelled"
```

完整的 Conversation 区块变为：

```python
    # Conversation
    TURN_RECEIVED = "turn.received"
    TURN_RESPONSE = "turn.response"
    TURN_CANCELLED = "turn.cancelled"
```

- [ ] **Step 2: 运行现有事件相关测试确认无回归**

```bash
pytest tests/unit/test_event_bus.py tests/unit/test_types.py -v
```

Expected: 全部 PASS。

- [ ] **Step 3: Commit**

```bash
git add sebastian/protocol/events/types.py
git commit -m "feat(events): 新增 EventType.TURN_CANCELLED

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 后端 — BaseAgent cancel_session（TDD）

**Files:**
- Modify: `sebastian/core/base_agent.py`
- Modify: `tests/unit/test_base_agent.py`

- [ ] **Step 1: 先写失败测试**

在 `tests/unit/test_base_agent.py` 末尾追加以下 7 个测试：

```python
# ──────────────────────────────────────────────────────────────────────────────
# cancel_session tests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_session_returns_false_when_no_active_stream(tmp_path: Path) -> None:
    """Cancelling an idle session returns False — no stream to cancel."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="idle-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    result = await agent.cancel_session("idle-session")

    assert result is False


@pytest.mark.asyncio
async def test_cancel_session_cancels_active_stream(tmp_path: Path) -> None:
    """cancel_session() cancels a long-running stream and clears _active_streams."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="running-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def slow_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="hello")
        stream_started.set()
        await asyncio.sleep(10)  # runs until cancelled

    agent._loop.stream = slow_stream  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hi", "running-session"))
    await stream_started.wait()

    result = await agent.cancel_session("running-session")

    assert result is True
    # After cancellation the stream task is no longer tracked
    assert "running-session" not in agent._active_streams

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task


@pytest.mark.asyncio
async def test_cancel_session_flushes_partial_text_to_episodic(tmp_path: Path) -> None:
    """Partial text is saved to episodic memory with [用户中断] suffix on cancel."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta, TextBlockStop
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="partial-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def partial_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="你好世界")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = partial_stream  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hello", "partial-session"))
    await stream_started.wait()
    await asyncio.sleep(0.01)  # let TextDelta be processed

    await agent.cancel_session("partial-session")

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task

    messages = await store.get_messages("partial-session", "sebastian")
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert "你好世界" in assistant_msgs[0]["content"]
    assert "[用户中断]" in assistant_msgs[0]["content"]


@pytest.mark.asyncio
async def test_cancel_session_skips_flush_when_no_partial(tmp_path: Path) -> None:
    """If no text was emitted before cancel, no assistant message is written."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="no-partial", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def empty_stream(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = empty_stream  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hi", "no-partial"))
    await stream_started.wait()

    await agent.cancel_session("no-partial")

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task

    messages = await store.get_messages("no-partial", "sebastian")
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 0


@pytest.mark.asyncio
async def test_cancel_session_emits_turn_cancelled_and_turn_response(tmp_path: Path) -> None:
    """cancel_session emits TURN_CANCELLED then TURN_RESPONSE on the event bus."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    from sebastian.core.types import Session
    from sebastian.protocol.events.bus import EventBus
    from sebastian.protocol.events.types import EventType
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="event-session", agent_type="sebastian", title="t"))
    bus = EventBus()
    collected: list = []
    bus.subscribe(lambda e: collected.append(e))
    agent = TestAgent(MagicMock(), store, bus)

    stream_started = asyncio.Event()

    async def stream_with_text(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="hi")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = stream_with_text  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hello", "event-session"))
    await stream_started.wait()
    await asyncio.sleep(0.01)

    await agent.cancel_session("event-session")

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task

    event_types = [e.type for e in collected]
    assert EventType.TURN_CANCELLED in event_types
    assert EventType.TURN_RESPONSE in event_types
    # TURN_CANCELLED must appear before TURN_RESPONSE
    assert event_types.index(EventType.TURN_CANCELLED) < event_types.index(EventType.TURN_RESPONSE)


@pytest.mark.asyncio
async def test_cancel_session_idempotent(tmp_path: Path) -> None:
    """Second cancel call on same session returns False and does not raise."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="idem-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def slow(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = slow  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hi", "idem-session"))
    await stream_started.wait()

    first = await agent.cancel_session("idem-session")
    second = await agent.cancel_session("idem-session")

    assert first is True
    assert second is False  # stream already gone

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task


@pytest.mark.asyncio
async def test_cancel_session_no_memory_leak_in_buffers(tmp_path: Path) -> None:
    """After cancel, _cancel_requested and _partial_buffer are cleaned up."""
    from sebastian.core.base_agent import BaseAgent
    from sebastian.core.stream_events import TextBlockStart, TextDelta
    from sebastian.core.types import Session
    from sebastian.store.session_store import SessionStore

    class TestAgent(BaseAgent):
        name = "sebastian"

    store = SessionStore(tmp_path / "sessions")
    await store.create_session(Session(id="leak-session", agent_type="sebastian", title="t"))
    agent = TestAgent(MagicMock(), store)

    stream_started = asyncio.Event()

    async def stream_partial(*args, **kwargs):
        yield TextBlockStart(block_id="b1")
        yield TextDelta(block_id="b1", delta="text")
        stream_started.set()
        await asyncio.sleep(10)

    agent._loop.stream = stream_partial  # type: ignore[attr-defined]

    run_task = asyncio.create_task(agent.run_streaming("hi", "leak-session"))
    await stream_started.wait()
    await asyncio.sleep(0.01)

    await agent.cancel_session("leak-session")

    with pytest.raises((asyncio.CancelledError, Exception)):
        await run_task

    assert "leak-session" not in agent._cancel_requested
    assert "leak-session" not in agent._partial_buffer
```

- [ ] **Step 2: 运行测试确认全部失败（预期）**

```bash
pytest tests/unit/test_base_agent.py -k "cancel_session" -v 2>&1 | tail -20
```

Expected: 7 FAILED（`cancel_session` 方法不存在）。

- [ ] **Step 3: 实现 BaseAgent 改动**

在 `sebastian/core/base_agent.py` 的 `__init__` 方法中，在 `self._active_streams` 那行之后新增两行：

```python
        self._active_streams: dict[str, asyncio.Task[str]] = {}  # session_id → task
        self._cancel_requested: set[str] = set()
        self._partial_buffer: dict[str, str] = {}
```

在 `_stream_inner` 方法中，找到处理 `TextDelta` 的代码：

```python
                if isinstance(event, TextDelta):
                    full_text += event.delta
```

改为：

```python
                if isinstance(event, TextDelta):
                    full_text += event.delta
                    self._partial_buffer[session_id] = full_text
```

在 `run_streaming` 的 `try/finally` 块，将现有的 `finally` 内容替换为：

```python
        finally:
            was_cancelled = session_id in self._cancel_requested
            self._cancel_requested.discard(session_id)
            self._active_streams.pop(session_id, None)
            self._current_task_goals.pop(session_id, None)
            self._current_depth.pop(session_id, None)

            if was_cancelled:
                partial = self._partial_buffer.pop(session_id, "")
                if partial:
                    partial += "\n\n[用户中断]"
                    try:
                        await self._episodic.add_turn(
                            session_id, "assistant", partial, agent=agent_context,
                        )
                    except Exception:
                        logger.warning("Failed to flush partial text on cancel", exc_info=True)
                await self._publish(
                    session_id,
                    EventType.TURN_CANCELLED,
                    {"agent_type": agent_context, "had_partial": bool(partial)},
                )
                await self._publish(session_id, EventType.TURN_RESPONSE, {})
            else:
                self._partial_buffer.pop(session_id, None)
```

在 `BaseAgent` 类末尾（`_publish` 方法之后）新增：

```python
    async def cancel_session(self, session_id: str) -> bool:
        """Cancel the active streaming turn for session_id.

        Returns True if a stream was cancelled, False if no active stream exists.
        """
        stream = self._active_streams.get(session_id)
        if stream is None or stream.done():
            return False
        self._cancel_requested.add(session_id)
        stream.cancel()
        try:
            await stream
        except (asyncio.CancelledError, Exception):
            pass
        return True
```

- [ ] **Step 4: 运行测试确认全部通过**

```bash
pytest tests/unit/test_base_agent.py -v 2>&1 | tail -20
```

Expected: 全部 PASS（含新增 7 个）。

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/base_agent.py tests/unit/test_base_agent.py
git commit -m "feat(agent): BaseAgent 新增 cancel_session + partial text flush

_cancel_requested / _partial_buffer 两个 instance 字段；
取消时 flush partial + [用户中断] 标记进 episodic；
emit TURN_CANCELLED + TURN_RESPONSE；finally 兜底清理防内存泄漏

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 后端 — cancel 路由 + 集成测试

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Modify: `tests/integration/test_gateway_sessions.py`

- [ ] **Step 1: 先写集成测试**

打开 `tests/integration/test_gateway_sessions.py`，在文件末尾追加：

```python
# ──────────────────────────────────────────────────────────────────────────────
# POST /sessions/{session_id}/cancel
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_cancel_unknown_session_returns_404(client: AsyncClient) -> None:
    """Non-existent session returns 404."""
    resp = await client.post(
        "/api/v1/sessions/nonexistent-session/cancel",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_cancel_idle_session_returns_404(client: AsyncClient, tmp_path) -> None:
    """Session with no active stream returns 404 (no stream to cancel)."""
    import sebastian.gateway.state as state
    from sebastian.core.types import Session

    session = Session(id="idle-cancel", agent_type="sebastian", title="t")
    await state.session_store.create_session(session)
    await state.index_store.upsert(session)

    resp = await client.post(
        "/api/v1/sessions/idle-cancel/cancel",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行新测试确认失败（路由不存在）**

```bash
pytest tests/integration/test_gateway_sessions.py -k "cancel" -v 2>&1 | tail -15
```

Expected: FAILED with 404/405（路由不存在）。

- [ ] **Step 3: 在 sessions.py 新增取消路由**

在 `cancel_task_post` 函数之后、`get_session_recent` 之前，插入：

```python
@router.post("/sessions/{session_id}/cancel", response_model=None)
async def cancel_session_post(
    session_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    """Cancel the active streaming turn for a session (spec Section 8.1)."""
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    agent = state.agent_instances.get(session.agent_type)
    target = agent if agent is not None else state.sebastian
    cancelled = await target.cancel_session(session_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="No active turn for this session")
    return {"ok": True}

```

- [ ] **Step 4: 运行集成测试确认通过**

```bash
pytest tests/integration/test_gateway_sessions.py -k "cancel" -v 2>&1 | tail -15
```

Expected: PASS（2 个新测试）。

- [ ] **Step 5: 运行全量集成测试确认无回归**

```bash
pytest tests/integration/test_gateway_sessions.py -v 2>&1 | tail -20
```

Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/routes/sessions.py tests/integration/test_gateway_sessions.py
git commit -m "feat(gateway): 新增 POST /sessions/{id}/cancel 路由

调用 agent.cancel_session()；空闲 session 返回 404；未知 session 返回 404

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 前端 — cancelTurn 错误处理 + useConversation turn_cancelled

**Files:**
- Modify: `ui/mobile/src/api/turns.ts`
- Modify: `ui/mobile/src/hooks/useConversation.ts`

- [ ] **Step 1: 更新 turns.ts 的 cancelTurn，加错误处理**

将 `cancelTurn` 函数替换为（URL 路径不变，只加错误处理）：

```ts
export async function cancelTurn(sessionId: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/sessions/${sessionId}/cancel`);
  } catch (err) {
    // 404 = 后端已无活跃 stream（正常竞态），静默处理
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      return;
    }
    throw err;
  }
}
```

在文件顶部补充 axios 导入（若不存在）：

```ts
import axios from 'axios';
import { apiClient } from './client';
```

- [ ] **Step 2: 在 useConversation.ts 的 switch 中新增 turn.cancelled 处理**

找到 `handleEvent` 函数中的 `switch (event.type)` 块，在 `case 'turn.response':` 之后、`default:` 之前插入：

```ts
        case 'turn.cancelled': {
          // Partial text was flushed by backend; finalize the streaming UI now.
          s.completeTurn(sid);
          queryClient.invalidateQueries({ queryKey: ['session-detail', sid] });
          break;
        }
```

- [ ] **Step 3: 验证 TypeScript 无报错**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

Expected: 0 errors。

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/api/turns.ts ui/mobile/src/hooks/useConversation.ts
git commit -m "fix(frontend): cancelTurn 错误处理 + turn.cancelled SSE 映射

cancelTurn 静默忽略 404（竞态）；useConversation 新增 turn.cancelled case

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 前端 — Composer store + types

**Files:**
- Create: `ui/mobile/src/store/composer.ts`
- Create: `ui/mobile/src/components/composer/types.ts`
- Create: `ui/mobile/src/components/composer/constants.ts`

- [ ] **Step 1: 创建 store/composer.ts**

```ts
import { create } from 'zustand';

const DRAFT_KEY = '__draft__';

interface ComposerStore {
  thinkingBySession: Record<string, boolean>;
  getThinking: (sessionId: string | null) => boolean;
  setThinking: (sessionId: string | null, v: boolean) => void;
  migrateDraftToSession: (newSessionId: string) => void;
  clearSession: (sessionId: string) => void;
}

export const useComposerStore = create<ComposerStore>((set, get) => ({
  thinkingBySession: {},

  getThinking(sessionId) {
    const key = sessionId ?? DRAFT_KEY;
    return get().thinkingBySession[key] ?? false;
  },

  setThinking(sessionId, v) {
    const key = sessionId ?? DRAFT_KEY;
    set((s) => ({
      thinkingBySession: { ...s.thinkingBySession, [key]: v },
    }));
  },

  migrateDraftToSession(newSessionId) {
    set((s) => {
      const draftVal = s.thinkingBySession[DRAFT_KEY];
      if (draftVal === undefined) return s;
      const next = { ...s.thinkingBySession };
      if (draftVal) next[newSessionId] = true;
      delete next[DRAFT_KEY];
      return { thinkingBySession: next };
    });
  },

  clearSession(sessionId) {
    set((s) => {
      const next = { ...s.thinkingBySession };
      delete next[sessionId];
      return { thinkingBySession: next };
    });
  },
}));
```

- [ ] **Step 2: 创建 composer/types.ts**

先创建目录，然后写文件：

```ts
/** 5-state machine for the Composer input bar. */
export type ComposerState =
  | 'idle_empty'   // text is empty — send button disabled (gray)
  | 'idle_ready'   // text is non-empty — send button enabled (blue)
  | 'sending'      // sendTurn in-flight — button disabled + spinner
  | 'streaming'    // backend is responding — stop button shown
  | 'cancelling';  // cancel POST sent, awaiting turn_complete — button disabled + spinner
```

- [ ] **Step 3: 创建 composer/constants.ts**

```ts
export const COMPOSER_LINE_HEIGHT = 22;
export const COMPOSER_MIN_HEIGHT = 44;
export const COMPOSER_MAX_LINES = 5;
/** Max height before TextInput switches to internal scroll. */
export const COMPOSER_MAX_HEIGHT = COMPOSER_LINE_HEIGHT * COMPOSER_MAX_LINES + 24; // ~134px
/** Default bottom padding used before onLayout fires. */
export const COMPOSER_DEFAULT_HEIGHT = 96;
```

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/store/composer.ts ui/mobile/src/components/composer/types.ts ui/mobile/src/components/composer/constants.ts
git commit -m "feat(composer): ComposerStore + types + constants

thinkingBySession 按 sessionId 隔离；migrateDraftToSession 迁移 draft 状态

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 前端 — Composer 子组件

**Files:**
- Create: `ui/mobile/src/components/composer/InputTextArea.tsx`
- Create: `ui/mobile/src/components/composer/ThinkButton.tsx`
- Create: `ui/mobile/src/components/composer/SendButton.tsx`
- Create: `ui/mobile/src/components/composer/ActionsRow.tsx`

- [ ] **Step 1: 创建 InputTextArea.tsx**

```tsx
import { TextInput, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';
import { COMPOSER_MIN_HEIGHT, COMPOSER_MAX_HEIGHT } from './constants';

interface Props {
  value: string;
  onChange: (text: string) => void;
  editable: boolean;
}

export function InputTextArea({ value, onChange, editable }: Props) {
  const colors = useTheme();
  return (
    <TextInput
      style={[styles.input, { color: colors.text }]}
      value={value}
      onChangeText={onChange}
      placeholder="向 Sebastian 发送消息"
      placeholderTextColor={colors.textMuted}
      multiline
      editable={editable}
      scrollEnabled
    />
  );
}

const styles = StyleSheet.create({
  input: {
    fontSize: 15,
    lineHeight: COMPOSER_LINE_HEIGHT,
    minHeight: COMPOSER_MIN_HEIGHT,
    maxHeight: COMPOSER_MAX_HEIGHT,
    paddingTop: 0,
    paddingBottom: 0,
    textAlignVertical: 'top',
  },
});
```

- [ ] **Step 2: 创建 ThinkButton.tsx**

```tsx
import { TouchableOpacity, Text, StyleSheet } from 'react-native';
import { ThinkIcon } from '../common/Icons';
import { useTheme } from '../../theme/ThemeContext';

interface Props {
  active: boolean;
  onPress: () => void;
  disabled?: boolean;
}

const ACTIVE_BG = '#E8F0FE';
const ACTIVE_FG = '#3B82F6';

export function ThinkButton({ active, onPress, disabled }: Props) {
  const colors = useTheme();
  const bg = active ? ACTIVE_BG : colors.inputBackground;
  const fg = active ? ACTIVE_FG : colors.textMuted;

  return (
    <TouchableOpacity
      style={[styles.pill, { backgroundColor: bg }]}
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.7}
    >
      <ThinkIcon size={16} color={fg} />
      <Text style={[styles.label, { color: fg }]}>思考</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 18,
    gap: 6,
  },
  label: {
    fontSize: 14,
    fontWeight: '500',
  },
});
```

- [ ] **Step 3: 创建 SendButton.tsx**

```tsx
import { TouchableOpacity, ActivityIndicator, StyleSheet } from 'react-native';
import { SendIcon, StopCircleIcon } from '../common/Icons';
import { useTheme } from '../../theme/ThemeContext';
import type { ComposerState } from './types';

interface Props {
  state: ComposerState;
  onPress: () => void;
}

export function SendButton({ state, onPress }: Props) {
  const colors = useTheme();
  const isDisabled =
    state === 'idle_empty' || state === 'sending' || state === 'cancelling';
  const bg = state === 'idle_empty' ? '#E5E5EA' : colors.accent;

  return (
    <TouchableOpacity
      style={[styles.btn, { backgroundColor: bg }]}
      onPress={onPress}
      disabled={isDisabled}
      activeOpacity={0.7}
    >
      {state === 'sending' || state === 'cancelling' ? (
        <ActivityIndicator size="small" color="#FFFFFF" />
      ) : state === 'streaming' ? (
        <StopCircleIcon size={18} color="#FFFFFF" />
      ) : (
        <SendIcon size={18} color="#FFFFFF" />
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  btn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
```

- [ ] **Step 4: 创建 ActionsRow.tsx**

```tsx
import { View, StyleSheet } from 'react-native';
import { ThinkButton } from './ThinkButton';
import { SendButton } from './SendButton';
import type { ComposerState } from './types';

interface Props {
  state: ComposerState;
  thinkActive: boolean;
  onThinkToggle: () => void;
  onSendOrStop: () => void;
}

export function ActionsRow({ state, thinkActive, onThinkToggle, onSendOrStop }: Props) {
  const isWorking =
    state === 'streaming' || state === 'cancelling' || state === 'sending';
  return (
    <View style={styles.row}>
      <ThinkButton
        active={thinkActive}
        onPress={onThinkToggle}
        disabled={isWorking}
      />
      <SendButton state={state} onPress={onSendOrStop} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 8,
    height: 36,
  },
});
```

- [ ] **Step 5: 验证 TypeScript 无报错**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

Expected: 0 errors。

- [ ] **Step 6: Commit**

```bash
git add ui/mobile/src/components/composer/InputTextArea.tsx ui/mobile/src/components/composer/ThinkButton.tsx ui/mobile/src/components/composer/SendButton.tsx ui/mobile/src/components/composer/ActionsRow.tsx
git commit -m "feat(composer): 新增 InputTextArea, ThinkButton, SendButton, ActionsRow 子组件

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: 前端 — Composer 主组件 index.tsx

**Files:**
- Create: `ui/mobile/src/components/composer/index.tsx`

- [ ] **Step 1: 创建 composer/index.tsx**

```tsx
import { useState, useMemo, useEffect, useRef } from 'react';
import { View, StyleSheet, Platform, Alert } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';
import { useComposerStore } from '../../store/composer';
import { InputTextArea } from './InputTextArea';
import { ActionsRow } from './ActionsRow';
import { COMPOSER_DEFAULT_HEIGHT } from './constants';
import type { ComposerState } from './types';

export interface ComposerProps {
  /** Current session id. null when composing a new (draft) session. */
  sessionId: string | null;
  /** True while the backend is streaming a response for this session. */
  isWorking: boolean;
  onSend: (text: string, opts: { thinking: boolean }) => Promise<void>;
  onStop: () => Promise<void>;
  /** Safe-area bottom inset in pixels. */
  bottomInset: number;
  /** Called whenever the Composer's rendered height changes. */
  onHeightChange: (height: number) => void;
}

export function Composer({
  sessionId,
  isWorking,
  onSend,
  onStop,
  bottomInset,
  onHeightChange,
}: ComposerProps) {
  const colors = useTheme();
  const [text, setText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const cancelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const thinkActive = useComposerStore((s) => s.getThinking(sessionId));
  const setThinking = useComposerStore((s) => s.setThinking);

  const state: ComposerState = useMemo(() => {
    if (isCancelling) return 'cancelling';
    if (isWorking) return 'streaming';
    if (isSending) return 'sending';
    return text.trim() ? 'idle_ready' : 'idle_empty';
  }, [isCancelling, isWorking, isSending, text]);

  // Auto-exit cancelling state when backend confirms turn is done
  useEffect(() => {
    if (!isWorking && isCancelling) {
      setIsCancelling(false);
    }
  }, [isWorking, isCancelling]);

  // 5s timeout safeguard: force-recover UI if backend doesn't respond
  useEffect(() => {
    if (state !== 'cancelling') {
      if (cancelTimerRef.current) {
        clearTimeout(cancelTimerRef.current);
        cancelTimerRef.current = null;
      }
      return;
    }
    cancelTimerRef.current = setTimeout(() => {
      setIsCancelling(false);
      Alert.alert('提示', '取消可能未生效，请下拉刷新');
    }, 5000);
    return () => {
      if (cancelTimerRef.current) {
        clearTimeout(cancelTimerRef.current);
        cancelTimerRef.current = null;
      }
    };
  }, [state]);

  async function handleSendOrStop() {
    if (state === 'streaming') {
      setIsCancelling(true);
      try {
        await onStop();
      } catch {
        // onStop handles errors; if it throws, recover state
        setIsCancelling(false);
      }
      return;
    }
    if (state !== 'idle_ready') return;
    const content = text.trim();
    setText('');
    setIsSending(true);
    try {
      await onSend(content, { thinking: thinkActive });
    } catch {
      // Restore text so user doesn't lose their message
      setText(content);
    } finally {
      setIsSending(false);
    }
  }

  const isInputDisabled = state === 'sending' || state === 'cancelling';

  return (
    <View
      style={[
        styles.floating,
        {
          bottom: bottomInset + 8,
          backgroundColor: colors.cardBackground,
          borderColor: colors.borderLight,
          shadowColor: colors.shadowColor,
        },
      ]}
      onLayout={(e) => {
        onHeightChange(e.nativeEvent.layout.height);
      }}
    >
      <InputTextArea
        value={text}
        onChange={setText}
        editable={!isInputDisabled}
      />
      <ActionsRow
        state={state}
        thinkActive={thinkActive}
        onThinkToggle={() => setThinking(sessionId, !thinkActive)}
        onSendOrStop={handleSendOrStop}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  floating: {
    position: 'absolute',
    left: 12,
    right: 12,
    borderRadius: 24,
    padding: 12,
    borderWidth: 1,
    // iOS shadow
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 8,
    // Android shadow
    elevation: 3,
  },
});
```

- [ ] **Step 2: 验证 TypeScript 无报错**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -20
```

Expected: 0 errors。

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/composer/index.tsx
git commit -m "feat(composer): Composer 主组件，5 状态机 + 动态高度上报

isCancelling + isWorking + isSending 派生 ComposerState；
5s 超时兜底；onLayout 上报高度

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 9: 前端 — ChatScreen 集成 + 删除旧 MessageInput

**Files:**
- Modify: `ui/mobile/app/index.tsx`
- Modify: `ui/mobile/src/components/conversation/ConversationView.tsx`
- Delete: `ui/mobile/src/components/chat/MessageInput.tsx`

- [ ] **Step 1: 更新 ConversationView 接受动态 bottomPadding**

将 `ConversationView.tsx` 的 `Props` interface 改为：

```tsx
interface Props {
  sessionId: string | null;
  errorBanner?: ErrorBannerType | null;
  onBannerAction?: () => void;
  bottomPadding?: number;
}
```

函数签名改为：

```tsx
export function ConversationView({ sessionId, errorBanner, onBannerAction, bottomPadding = 100 }: Props) {
```

将 `contentContainerStyle` 改为动态值：

```tsx
        contentContainerStyle={{ paddingTop: 12, paddingBottom: bottomPadding }}
```

同时删除文件末尾 styles 中 `content` 里的 `paddingBottom: 100`（改成直接删掉 `content` style key，因为已内联）：

```tsx
const styles = StyleSheet.create({
  container: { flex: 1 },
});
```

- [ ] **Step 2: 重写 app/index.tsx**

完整替换 `app/index.tsx` 内容为：

```tsx
import { useState } from 'react';
import { View, StyleSheet, Alert, TouchableOpacity, Text, Platform } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { KeyboardAvoidingView } from 'react-native';
import { router } from 'expo-router';
import axios from 'axios';
import { useSessionStore } from '@/src/store/session';
import { useSessions } from '@/src/hooks/useSessions';
import { sendTurn, cancelTurn } from '@/src/api/turns';
import { deleteSession } from '@/src/api/sessions';
import { useQueryClient } from '@tanstack/react-query';
import { Sidebar } from '@/src/components/common/Sidebar';
import { EmptyState } from '@/src/components/common/EmptyState';
import { AppSidebar } from '@/src/components/chat/AppSidebar';
import { Composer } from '@/src/components/composer';
import { ConversationView } from '@/src/components/conversation';
import { ErrorBanner } from '@/src/components/conversation/ErrorBanner';
import { useConversationStore } from '@/src/store/conversation';
import { useComposerStore } from '@/src/store/composer';
import { useTheme } from '@/src/theme/ThemeContext';
import { COMPOSER_DEFAULT_HEIGHT } from '@/src/components/composer/constants';

export default function ChatScreen() {
  const colors = useTheme();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [composerHeight, setComposerHeight] = useState(COMPOSER_DEFAULT_HEIGHT);
  const {
    currentSessionId, draftSession,
    setCurrentSession, startDraft, persistSession,
  } = useSessionStore();
  const { data: sessions = [] } = useSessions();
  const isWorking = useConversationStore(
    (s) => !!(currentSessionId && s.sessions[currentSessionId]?.activeTurn),
  );
  const currentBanner = useConversationStore((s) =>
    currentSessionId ? (s.sessions[currentSessionId]?.errorBanner ?? null) : s.draftErrorBanner,
  );

  const bottomPadding = composerHeight + 24;

  async function handleSend(text: string, _opts: { thinking: boolean }) {
    // _opts.thinking is captured for future backend wiring (Phase 2)
    try {
      const { sessionId } = await sendTurn(currentSessionId, text);
      if (!currentSessionId) {
        persistSession({
          id: sessionId,
          agent: 'sebastian',
          title: text.slice(0, 40),
          status: 'active',
          updated_at: new Date().toISOString(),
          task_count: 0,
          active_task_count: 0,
        });
        useComposerStore.getState().migrateDraftToSession(sessionId);
        queryClient.invalidateQueries({ queryKey: ['sessions'] });
      }
      useConversationStore.getState().appendUserMessage(sessionId, text);
      queryClient.invalidateQueries({ queryKey: ['messages', sessionId] });
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 400) {
        const detail = err.response.data?.detail;
        if (detail?.code === 'no_llm_provider') {
          const banner = { code: detail.code, message: detail.message };
          const store = useConversationStore.getState();
          if (currentSessionId) {
            store.setErrorBanner(currentSessionId, banner);
          } else {
            store.setDraftErrorBanner(banner);
          }
          return;
        }
      }
      Alert.alert('发送失败，请重试');
      throw err; // re-throw so Composer restores text
    }
  }

  async function handleStop() {
    if (currentSessionId) await cancelTurn(currentSessionId);
  }

  async function handleDeleteSession(id: string) {
    Alert.alert('删除对话', '确认删除这条对话记录？', [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: async () => {
          try {
            await deleteSession(id);
            if (currentSessionId === id) setCurrentSession(null);
            useComposerStore.getState().clearSession(id);
            queryClient.invalidateQueries({ queryKey: ['sessions'] });
            queryClient.invalidateQueries({ queryKey: ['agent-sessions'] });
          } catch {
            Alert.alert('删除失败，请重试');
          }
        },
      },
    ]);
  }

  const isEmpty = !currentSessionId && !draftSession;

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <View style={[styles.container, { backgroundColor: colors.background }]}>
        <View style={[styles.header, { paddingTop: insets.top, backgroundColor: colors.background, borderBottomColor: colors.borderLight }]}>
          <TouchableOpacity
            style={styles.menuButton}
            onPress={() => setSidebarOpen(true)}
          >
            <Text style={[styles.menuIcon, { color: colors.text }]}>☰</Text>
          </TouchableOpacity>
          <Text style={[styles.headerTitle, { color: colors.text }]}>Sebastian</Text>
        </View>

        {isEmpty ? (
          currentBanner ? (
            <View style={[styles.emptyContainer, { paddingBottom: bottomPadding }]}>
              <ErrorBanner
                message={currentBanner.message}
                onAction={() => router.push('/settings')}
              />
            </View>
          ) : (
            <EmptyState message="向 Sebastian 发送消息开始对话" />
          )
        ) : (
          <ConversationView
            sessionId={currentSessionId}
            errorBanner={currentBanner}
            bottomPadding={bottomPadding}
            onBannerAction={() => router.push('/settings')}
          />
        )}

        <Composer
          sessionId={currentSessionId}
          isWorking={isWorking}
          onSend={handleSend}
          onStop={handleStop}
          bottomInset={insets.bottom}
          onHeightChange={setComposerHeight}
        />

        <Sidebar
          visible={sidebarOpen}
          onOpen={() => setSidebarOpen(true)}
          onClose={() => setSidebarOpen(false)}
        >
          <AppSidebar
            sessions={sessions}
            currentSessionId={currentSessionId}
            draftSession={draftSession}
            onSelect={(id) => { setCurrentSession(id); setSidebarOpen(false); }}
            onNewChat={() => { startDraft(); setSidebarOpen(false); }}
            onDelete={handleDeleteSession}
            onClose={() => setSidebarOpen(false)}
          />
        </Sidebar>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  emptyContainer: { flex: 1 },
  header: {
    minHeight: 48,
    borderBottomWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
  },
  menuButton:  { padding: 8 },
  menuIcon:    { fontSize: 20 },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 16,
    fontWeight: '600',
    marginRight: 36,
  },
});
```

- [ ] **Step 3: 删除旧 MessageInput**

```bash
rm ui/mobile/src/components/chat/MessageInput.tsx
```

验证没有其他地方还在 import 它：

```bash
grep -rn "MessageInput" ui/mobile/src/ ui/mobile/app/ 2>/dev/null
```

Expected: 无输出（或只有 chat/ 目录下其他组件不相关的引用，若有则修改）。

- [ ] **Step 4: TypeScript 全量检查**

```bash
cd ui/mobile && npx tsc --noEmit 2>&1 | head -30
```

Expected: 0 errors。

- [ ] **Step 5: Commit**

```bash
git add ui/mobile/app/index.tsx ui/mobile/src/components/conversation/ConversationView.tsx
git rm ui/mobile/src/components/chat/MessageInput.tsx
git commit -m "feat(ui): Composer 接入 ChatScreen，删除旧 MessageInput

KeyboardAvoidingView 包裹；动态 bottomPadding 防遮挡；
draft→session thinking 迁移；delete session 清理 composer store

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 10: 前端 — Android KeyboardAvoidingView 真机验证

**Files:** 无代码改动（验证 + 可能需修复）

- [ ] **Step 1: 启动模拟器 + Metro + Gateway**

```bash
# Terminal 1
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_36.1 -no-snapshot-load &
~/Library/Android/sdk/platform-tools/adb wait-for-device shell getprop sys.boot_completed

# Terminal 2 (项目根目录)
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload

# Terminal 3
cd ui/mobile && npx expo run:android
```

- [ ] **Step 2: 手工验证 Checklist**

```
- [ ] 空输入框：发送按钮灰色不可点
- [ ] 输入一个字符：按钮变蓝色可点
- [ ] 全选删除：按钮回到灰色
- [ ] 点击发送：按钮瞬间变 spinner，连接 Gateway 后切换到停止按钮
- [ ] 点击停止：按钮变 spinner + disabled
- [ ] 后端响应 cancel 后：按钮回到发送态，最后一条 assistant 消息包含 [用户中断]
- [ ] 思考按钮切换高亮/非高亮
- [ ] 切换 session A→B：A 的思考开关保留，B 显示 B 的状态
- [ ] 多行输入到 5 行：Composer 扩高，对话区最后一条可上滑到 Composer 上方
- [ ] 超过 5 行：TextInput 内部滚动，Composer 高度不再增加
- [ ] 键盘弹起：Composer 跟随键盘上移（Android behavior=height）
- [ ] ErrorBanner 显示时不被 Composer 遮挡，可上滑查看
- [ ] 新 session（draft）→ 发送 → 成为真 session，思考开关状态保留
- [ ] 删除 session 后对应 thinking 状态被清除
```

- [ ] **Step 3: 如果 Android KeyboardAvoidingView 不正常（常见问题）**

检查 `app.json` 中是否有 `android.softwareKeyboardLayoutMode`：

```bash
grep -n "softwareKeyboardLayoutMode" ui/mobile/app.json
```

如果存在且为 `"resize"`，或者 `behavior="height"` 导致页面跳动，将 `app/index.tsx` 中的 `KeyboardAvoidingView` 改为：

```tsx
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
```

Android 在 edge-to-edge 模式下 `behavior=undefined` + window insets 通常效果更好。

---

## Task 11: 更新 README

**Files:**
- Modify: `ui/mobile/README.md`
- Create: `ui/mobile/src/components/composer/README.md`

- [ ] **Step 1: 在 ui/mobile/src/components/composer/ 创建 README.md**

```markdown
# composer/

Composer 是主对话输入区组件，负责文本输入、思考开关、发送/停止控制。

## 文件职责

| 文件 | 职责 |
|---|---|
| `index.tsx` | 主组件。状态机管理，组合子组件，onLayout 上报高度 |
| `InputTextArea.tsx` | 多行 TextInput，最多 5 行，超出内部滚动 |
| `ActionsRow.tsx` | 底部按钮容器，左思考右发送布局 |
| `ThinkButton.tsx` | 胶囊式思考开关（UI 占位，未接后端） |
| `SendButton.tsx` | 圆形按钮，根据 ComposerState 渲染 4 种视觉 |
| `types.ts` | `ComposerState` 5 状态枚举 |
| `constants.ts` | 行高、最大行数等布局常量 |

## 状态机

```
idle_empty ──has text──→ idle_ready
idle_ready ──send──────→ sending ──activeTurn──→ streaming ──stop──→ cancelling
streaming  ──turn done→ idle_empty
cancelling ──turn done→ idle_empty
cancelling ──5s timeout→ idle_empty + toast
```

## Props (Composer)

| Prop | 类型 | 说明 |
|---|---|---|
| `sessionId` | `string \| null` | null = draft session |
| `isWorking` | `boolean` | 来自 conversationStore.activeTurn |
| `onSend` | `(text, opts) => Promise<void>` | `opts.thinking` 预留字段 |
| `onStop` | `() => Promise<void>` | 调用 cancelTurn API |
| `bottomInset` | `number` | Safe area 底部 |
| `onHeightChange` | `(h: number) => void` | 供 ChatScreen 动态 padding |

## 思考开关

状态存于 `src/store/composer.ts` 的 `useComposerStore`，按 `sessionId` 隔离。
Draft session 用 `__draft__` key，`persistSession` 后调 `migrateDraftToSession(newId)` 迁移。
```

- [ ] **Step 2: 在 ui/mobile/README.md 的 src/components 表格中追加 composer/ 条目**

找到 README 中描述 `src/components/` 的部分，追加：

```
| `src/components/composer/` | Composer 输入组件（文本输入 + 思考开关 + 发送/停止）|
```

同时在"修改导航"或类似章节中增加：

```
- 修改输入框行为/样式：`src/components/composer/index.tsx`
- 修改发送/停止按钮：`src/components/composer/SendButton.tsx`
- 修改思考按钮：`src/components/composer/ThinkButton.tsx`
- 修改思考开关 session 状态：`src/store/composer.ts`
```

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/composer/README.md ui/mobile/README.md
git commit -m "docs(mobile): 更新 README，新增 composer/ 目录说明

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 12: 后端全量回归测试

- [ ] **Step 1: 运行全量单元测试**

```bash
pytest tests/unit/ -v 2>&1 | tail -30
```

Expected: 全部 PASS。

- [ ] **Step 2: 运行全量集成测试**

```bash
pytest tests/integration/ -v 2>&1 | tail -30
```

Expected: 全部 PASS。

- [ ] **Step 3: Lint 检查**

```bash
ruff check sebastian/ tests/ && ruff format --check sebastian/ tests/
```

Expected: 无错误。

---

## Self-Review

### Spec coverage check

| Spec 章节 | 对应 Task |
|---|---|
| 后端 cancel 闭环（BaseAgent.cancel_session）| Task 3 |
| EventType.TURN_CANCELLED | Task 2 |
| POST /sessions/{id}/cancel 路由 | Task 4 |
| cancelTurn 错误处理 | Task 5 |
| turn_cancelled SSE 映射 | Task 5 |
| Icons.tsx 统一 11 个图标 | Task 1 |
| ComposerState 5 状态机 | Tasks 6-8 |
| 思考开关按 session 隔离 | Task 6 |
| draft→real session 迁移 | Task 9 |
| 动态 bottomPadding | Task 9 |
| KeyboardAvoidingView | Task 9 |
| Android 真机验证 | Task 10 |
| README 更新 | Task 11 |

所有 spec 章节均有对应 task，无遗漏。

### Placeholder scan

无 TBD / TODO / "implement later" / "similar to Task N" 等占位。

### Type consistency

- `ComposerState` 在 `types.ts` 定义，`SendButton`、`ActionsRow`、`Composer/index.tsx` 均从 `./types` 导入，类型一致。
- `COMPOSER_DEFAULT_HEIGHT` 在 `constants.ts` 定义，`ChatScreen` 从 `@/src/components/composer/constants` 导入，一致。
- `cancel_session` 方法在 `BaseAgent`，gateway 路由调用 `target.cancel_session(session_id)`，签名一致。
- `EventType.TURN_CANCELLED` 在 `types.py` 新增，`base_agent.py` 的 `run_streaming finally` 块使用，一致。
- `migrateDraftToSession` 在 `composer.ts` 定义，`handleSend` 调用时用 `useComposerStore.getState().migrateDraftToSession(sessionId)`，一致。
