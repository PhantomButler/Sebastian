# SwipePager 平铺滑动侧边栏实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace overlay sidebars with a DeepSeek-style flat swipe pager that lays out panels horizontally and responds to drag gestures with fluid spring animations.

**Architecture:** A single `SwipePager` component manages horizontal panel layout and pan gesture handling using `react-native-reanimated` shared values and `react-native-gesture-handler` v2 `Gesture.Pan()`. All animations run on the UI thread as worklets. Pages consume `SwipePager` via props (left/right content) and a ref for imperative navigation (goToLeft/goToCenter/goToRight).

**Tech Stack:** react-native-reanimated 4.1.x, react-native-gesture-handler 2.28.x (both already installed), TypeScript, React Native

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `ui/mobile/src/components/common/SwipePager.tsx` | Create | Core swipe pager: horizontal panel layout, pan gesture, spring snap, imperative ref API |
| `ui/mobile/app/index.tsx` | Modify | Integrate SwipePager with left (AppSidebar) + right (TodoSidebar), remove old Sidebar/ContentPanGestureArea |
| `ui/mobile/app/subagents/session/[id].tsx` | Modify | Integrate SwipePager with right-only (TodoSidebar), remove old Sidebar/ContentPanGestureArea |
| `ui/mobile/src/components/common/Sidebar.tsx` | Delete | Replaced by SwipePager |
| `ui/mobile/src/components/common/ContentPanGestureArea.tsx` | Delete | Replaced by SwipePager |
| `ui/mobile/ui/mobile/README.md` | Modify | Update component references in navigation table |

---

## Task 1: Create SwipePager component

**Files:**
- Create: `ui/mobile/src/components/common/SwipePager.tsx`

- [ ] **Step 1: Create SwipePager with types, layout, and gesture logic**

Create the full component. It uses Reanimated `useSharedValue` + `useAnimatedStyle` for the translateX-driven layout, and RNGH v2 `Gesture.Pan()` for drag handling. `forwardRef` + `useImperativeHandle` expose navigation methods.

```tsx
import { forwardRef, useImperativeHandle, useMemo, type ReactNode } from 'react';
import { Dimensions, StyleSheet, View } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  runOnJS,
} from 'react-native-reanimated';

const SCREEN_WIDTH = Dimensions.get('window').width;
const DEFAULT_SIDEBAR_RATIO = 0.8;
const VELOCITY_THRESHOLD = 500;
const SPRING_CONFIG = { damping: 22, stiffness: 220, mass: 0.8 };
const RUBBER_BAND_FACTOR = 0.3;

export type PanelPosition = 'left' | 'center' | 'right';

export interface SwipePagerProps {
  left?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  sidebarWidth?: number;
  onPanelChange?: (panel: PanelPosition) => void;
}

export interface SwipePagerRef {
  goToCenter: () => void;
  goToLeft: () => void;
  goToRight: () => void;
}

export const SwipePager = forwardRef<SwipePagerRef, SwipePagerProps>(
  function SwipePager({ left, right, children, sidebarWidth = DEFAULT_SIDEBAR_RATIO, onPanelChange }, ref) {
    const hasLeft = left !== undefined;
    const hasRight = right !== undefined;
    const sidebarPx = Math.round(SCREEN_WIDTH * sidebarWidth);

    const snapPoints = useMemo(() => {
      if (hasLeft && hasRight) {
        // [leftSnap, centerSnap, rightSnap]
        return [0, -sidebarPx, -(sidebarPx + sidebarPx)];
      }
      if (hasLeft) {
        return [0, -sidebarPx];
      }
      if (hasRight) {
        return [0, -sidebarPx];
      }
      return [0];
    }, [hasLeft, hasRight, sidebarPx]);

    // Center snap is always the "home" position
    const centerIndex = hasLeft ? 1 : 0;
    const translateX = useSharedValue(snapPoints[centerIndex]);
    const startX = useSharedValue(0);

    const minSnap = snapPoints[snapPoints.length - 1];
    const maxSnap = snapPoints[0];

    function fireOnPanelChange(snapValue: number) {
      if (!onPanelChange) return;
      if (hasLeft && snapValue === snapPoints[0]) {
        onPanelChange('left');
      } else if (snapValue === snapPoints[centerIndex]) {
        onPanelChange('center');
      } else {
        onPanelChange('right');
      }
    }

    function snapTo(target: number) {
      'worklet';
      translateX.value = withSpring(target, SPRING_CONFIG);
      if (onPanelChange) runOnJS(fireOnPanelChange)(target);
    }

    // JS-thread version for imperative API (called from useImperativeHandle)
    function navigateTo(target: number) {
      translateX.value = withSpring(target, SPRING_CONFIG);
      fireOnPanelChange(target);
    }

    function findNearestSnap(x: number): number {
      'worklet';
      let nearest = snapPoints[0];
      let minDist = Math.abs(x - snapPoints[0]);
      for (let i = 1; i < snapPoints.length; i++) {
        const dist = Math.abs(x - snapPoints[i]);
        if (dist < minDist) {
          minDist = dist;
          nearest = snapPoints[i];
        }
      }
      return nearest;
    }

    function findCurrentIndex(x: number): number {
      'worklet';
      let idx = 0;
      let minDist = Math.abs(x - snapPoints[0]);
      for (let i = 1; i < snapPoints.length; i++) {
        const dist = Math.abs(x - snapPoints[i]);
        if (dist < minDist) {
          minDist = dist;
          idx = i;
        }
      }
      return idx;
    }

    const panGesture = Gesture.Pan()
      .activeOffsetX([-15, 15])
      .failOffsetY([-10, 10])
      .onStart(() => {
        'worklet';
        startX.value = translateX.value;
      })
      .onUpdate((e) => {
        'worklet';
        const raw = startX.value + e.translationX;
        // Rubber band effect at boundaries
        if (raw > maxSnap) {
          translateX.value = maxSnap + (raw - maxSnap) * RUBBER_BAND_FACTOR;
        } else if (raw < minSnap) {
          translateX.value = minSnap + (raw - minSnap) * RUBBER_BAND_FACTOR;
        } else {
          translateX.value = raw;
        }
      })
      .onEnd((e) => {
        'worklet';
        const currentIdx = findCurrentIndex(translateX.value);

        // Fast fling: jump to next/previous panel
        if (Math.abs(e.velocityX) > VELOCITY_THRESHOLD) {
          const direction = e.velocityX > 0 ? -1 : 1; // positive velocity = swipe right = go to previous panel
          const targetIdx = Math.max(0, Math.min(snapPoints.length - 1, currentIdx + direction));
          snapTo(snapPoints[targetIdx]);
          return;
        }

        // Otherwise snap to nearest
        snapTo(findNearestSnap(translateX.value));
      });

    const animatedStyle = useAnimatedStyle(() => ({
      transform: [{ translateX: translateX.value }],
    }));

    useImperativeHandle(ref, () => ({
      goToCenter: () => navigateTo(snapPoints[centerIndex]),
      goToLeft: () => { if (hasLeft) navigateTo(snapPoints[0]); },
      goToRight: () => { if (hasRight) navigateTo(snapPoints[snapPoints.length - 1]); },
    }));

    return (
      <GestureDetector gesture={panGesture}>
        <Animated.View style={[styles.track, animatedStyle]}>
          {hasLeft && (
            <View style={[styles.panel, { width: sidebarPx }]}>
              {left}
            </View>
          )}
          <View style={[styles.panel, { width: SCREEN_WIDTH }]}>
            {children}
          </View>
          {hasRight && (
            <View style={[styles.panel, { width: sidebarPx }]}>
              {right}
            </View>
          )}
        </Animated.View>
      </GestureDetector>
    );
  },
);

const styles = StyleSheet.create({
  track: {
    flexDirection: 'row',
    flex: 1,
  },
  panel: {
    height: '100%',
    overflow: 'hidden',
  },
});
```

- [ ] **Step 2: Verify TypeScript compiles**

Run:
```bash
cd ui/mobile && npx tsc --noEmit
```
Expected: No errors related to SwipePager.tsx

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/src/components/common/SwipePager.tsx
git commit -m "feat(mobile): add SwipePager component with Reanimated pan gesture"
```

---

## Task 2: Integrate SwipePager into ChatScreen (main page)

**Files:**
- Modify: `ui/mobile/app/index.tsx`

- [ ] **Step 1: Replace sidebar imports and state**

In `app/index.tsx`, replace these imports:

```tsx
import { Sidebar } from '@/src/components/common/Sidebar';
import { ContentPanGestureArea } from '@/src/components/common/ContentPanGestureArea';
```

with:

```tsx
import { SwipePager, type SwipePagerRef } from '@/src/components/common/SwipePager';
```

Add a ref at the top of `ChatScreen`:

```tsx
const pagerRef = useRef<SwipePagerRef>(null);
```

Remove the two state variables:

```tsx
// DELETE these two lines:
const [sidebarOpen, setSidebarOpen] = useState(false);
const [todoSidebarOpen, setTodoSidebarOpen] = useState(false);
```

Remove `useState` from the react import if no other useState calls remain (but `deleteTarget` still uses it, so keep it).

- [ ] **Step 2: Replace the JSX structure**

Replace the entire return block. The key changes:
- `SwipePager` wraps everything, with `left` and `right` props for sidebars
- Header is inside `SwipePager`'s children (moves with the center panel)
- No more `<Sidebar>` or `<ContentPanGestureArea>` wrappers
- Hamburger button calls `pagerRef.current?.goToLeft()`
- `onClose` callbacks use `pagerRef.current?.goToCenter()`

Full replacement for the return statement:

```tsx
  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.container, { backgroundColor: colors.background }]}
    >
      <SwipePager
        ref={pagerRef}
        left={
          <AppSidebar
            sessions={sessions}
            currentSessionId={currentSessionId}
            draftSession={draftSession}
            onSelect={(id) => { setCurrentSession(id); pagerRef.current?.goToCenter(); }}
            onNewChat={() => { startDraft(); pagerRef.current?.goToCenter(); }}
            onDelete={setDeleteTarget}
            onClose={() => pagerRef.current?.goToCenter()}
          />
        }
        right={
          <TodoSidebar
            sessionId={currentSessionId}
            agentType="sebastian"
            onClose={() => pagerRef.current?.goToCenter()}
          />
        }
      >
        <View
          style={[
            styles.header,
            {
              paddingTop: insets.top,
              backgroundColor: colors.background,
              borderBottomColor: colors.borderLight,
            },
          ]}
        >
          <TouchableOpacity
            style={styles.menuButton}
            onPress={() => pagerRef.current?.goToLeft()}
          >
            <Text style={[styles.menuIcon, { color: colors.text }]}>☰</Text>
          </TouchableOpacity>
          <Text style={[styles.headerTitle, { color: colors.text }]}>Sebastian</Text>
        </View>

        <KeyboardGestureArea
          style={styles.gestureArea}
          interpolator="ios"
          offset={COMPOSER_DEFAULT_HEIGHT}
          textInputNativeID="composer-input"
        >
          {isEmpty ? (
            currentBanner ? (
              <View style={styles.emptyContainer}>
                <ErrorBanner
                  message={currentBanner.message}
                  actionLabel={bannerActionLabel}
                  onAction={handleBannerAction}
                />
              </View>
            ) : (
              <EmptyState message="向 Sebastian 发送消息开始对话" />
            )
          ) : (
            <ConversationView
              sessionId={currentSessionId}
              errorBanner={currentBanner}
              bannerActionLabel={bannerActionLabel}
              onBannerAction={handleBannerAction}
              renderScrollComponent={renderScrollComponent}
            />
          )}

          <KeyboardStickyView offset={stickyOffset} style={styles.stickyComposer}>
            <Composer
              sessionId={currentSessionId}
              isWorking={isWorking}
              onSend={handleSend}
              onStop={handleStop}
            />
          </KeyboardStickyView>
        </KeyboardGestureArea>
      </SwipePager>
      <ConfirmDialog
        visible={deleteTarget !== null}
        title="删除对话"
        message="确认删除这条对话记录？"
        confirmText="删除"
        destructive
        onCancel={() => setDeleteTarget(null)}
        onConfirm={confirmDeleteSession}
      />
    </SafeAreaView>
  );
```

Note: `ConfirmDialog` stays outside `SwipePager` since it's a modal overlay, not a panel.

- [ ] **Step 3: Verify TypeScript compiles**

Run:
```bash
cd ui/mobile && npx tsc --noEmit
```
Expected: No errors in `app/index.tsx`

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/app/index.tsx
git commit -m "feat(mobile): integrate SwipePager into ChatScreen"
```

---

## Task 3: Integrate SwipePager into Sub-Agent Session detail page

**Files:**
- Modify: `ui/mobile/app/subagents/session/[id].tsx`

- [ ] **Step 1: Replace imports and state**

Replace these imports:

```tsx
import { ContentPanGestureArea } from '../../../src/components/common/ContentPanGestureArea';
import { Sidebar } from '../../../src/components/common/Sidebar';
```

with:

```tsx
import { SwipePager, type SwipePagerRef } from '../../../src/components/common/SwipePager';
```

Add a ref at the top of `SessionDetailScreen`:

```tsx
const pagerRef = useRef<SwipePagerRef>(null);
```

Remove the state variable:

```tsx
// DELETE:
const [todoSidebarOpen, setTodoSidebarOpen] = useState(false);
```

- [ ] **Step 2: Replace the JSX structure**

Replace the return block. Key changes:
- `SwipePager` wraps everything with only `right` prop (no left sidebar)
- Header with BackButton is inside `SwipePager` children
- No more `<ContentPanGestureArea>` or `<Sidebar>`

Full replacement for the return statement:

```tsx
    return (
      <SafeAreaView edges={['bottom']} style={[styles.container, { backgroundColor: colors.secondaryBackground }]}>
        <SwipePager
          ref={pagerRef}
          right={
            <TodoSidebar
              sessionId={effectiveSessionId}
              agentType={agentName}
              onClose={() => pagerRef.current?.goToCenter()}
            />
          }
        >
          <View
            style={[
              styles.header,
              { paddingTop: insets.top, backgroundColor: colors.background, borderBottomColor: colors.borderLight },
            ]}
          >
            <BackButton style={styles.back} />
            <Text style={[styles.title, { color: colors.text }]} numberOfLines={1}>
              {displayTitle}
            </Text>
            <View style={styles.back} />
          </View>

          <KeyboardGestureArea
            style={styles.gestureArea}
            interpolator="ios"
            offset={COMPOSER_DEFAULT_HEIGHT}
            textInputNativeID="composer-input"
          >
            <ConversationView
              sessionId={isMockSession ? null : effectiveSessionId}
              errorBanner={banner}
              bannerActionLabel={bannerActionLabel}
              onBannerAction={() => {
                if (banner?.code === 'no_llm_provider') {
                  router.push('/settings/providers');
                  return;
                }
                router.push('/settings');
              }}
              renderScrollComponent={renderScrollComponent}
            />

            <KeyboardStickyView offset={stickyOffset} style={styles.stickyComposer}>
              <Composer
                sessionId={effectiveSessionId}
                isWorking={isWorking}
                onSend={handleSend}
                onStop={async () => {
                  if (!effectiveSessionId) return;
                  await cancelTurn(effectiveSessionId);
                }}
              />
            </KeyboardStickyView>
          </KeyboardGestureArea>
        </SwipePager>
      </SafeAreaView>
    );
```

- [ ] **Step 3: Verify TypeScript compiles**

Run:
```bash
cd ui/mobile && npx tsc --noEmit
```
Expected: No errors in `app/subagents/session/[id].tsx`

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/app/subagents/session/[id].tsx
git commit -m "feat(mobile): integrate SwipePager into Sub-Agent session detail page"
```

---

## Task 4: Delete old Sidebar and ContentPanGestureArea

**Files:**
- Delete: `ui/mobile/src/components/common/Sidebar.tsx`
- Delete: `ui/mobile/src/components/common/ContentPanGestureArea.tsx`

- [ ] **Step 1: Verify no remaining imports**

Run:
```bash
cd ui/mobile && grep -r "from.*common/Sidebar\|from.*common/ContentPanGestureArea" --include="*.tsx" --include="*.ts" .
```
Expected: No output (all imports were replaced in Tasks 2 and 3)

- [ ] **Step 2: Delete the files**

```bash
rm ui/mobile/src/components/common/Sidebar.tsx
rm ui/mobile/src/components/common/ContentPanGestureArea.tsx
```

- [ ] **Step 3: Verify TypeScript compiles**

Run:
```bash
cd ui/mobile && npx tsc --noEmit
```
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add -u ui/mobile/src/components/common/Sidebar.tsx ui/mobile/src/components/common/ContentPanGestureArea.tsx
git commit -m "refactor(mobile): remove old Sidebar and ContentPanGestureArea replaced by SwipePager"
```

---

## Task 5: Update README

**Files:**
- Modify: `ui/mobile/README.md`

- [ ] **Step 1: Update the navigation table and component references**

In `ui/mobile/README.md`, update the modification navigation table:

Replace:
```markdown
| 改侧边栏容器或手势（左右通用） | `src/components/common/Sidebar.tsx`（`side` prop） |
| 改页面级横向 pan 手势识别 | `src/components/common/ContentPanGestureArea.tsx` |
```

with:
```markdown
| 改侧边栏滑动交互（SwipePager 手势/动画/snap） | `src/components/common/SwipePager.tsx` |
```

In the `components/common/` section, replace:
```markdown
- `Sidebar.tsx`：通用侧边栏容器，通过 `side: 'left' | 'right'` 参数控制方向（含手势开/关支持）
- `ContentPanGestureArea.tsx`：页面级横向 pan 手势识别区（左右滑切换左右侧边栏，纵向手势失败让出）
```

with:
```markdown
- `SwipePager.tsx`：三面板平铺滑动容器，Reanimated + Gesture Handler 驱动跟手拖拽 + 弹性 snap（替代旧 Sidebar + ContentPanGestureArea）
```

In the navigation architecture section, replace:
```markdown
- 右滑或点击汉堡按钮 → 打开左侧边栏（AppSidebar）
  - 侧边栏顶部：Sub-Agents、设置、系统总览（占位）入口
  - 侧边栏中部：历史 Session 列表，点击切换会话
  - 侧边栏底部：新对话按钮
- 左滑（在对话内容区域任意位置） → 打开右侧 Todo 侧边栏（TodoSidebar），与左侧呈镜像；点击外部或右滑收起
```

with:
```markdown
- 右滑或点击汉堡按钮 → 滑动到左侧边栏面板（AppSidebar），对话页露出约 20%
  - 侧边栏顶部：Sub-Agents、设置、系统总览（占位）入口
  - 侧边栏中部：历史 Session 列表，点击切换会话
  - 侧边栏底部：新对话按钮
- 左滑 → 滑动到右侧 Todo 侧边栏面板（TodoSidebar），对话页露出约 20%
- 三面板通过 SwipePager 平铺排列，手势跟手拖拽 + 弹性 snap 切换
```

- [ ] **Step 2: Verify no stale references**

```bash
cd ui/mobile && grep -n "ContentPanGestureArea\|Sidebar\.tsx" README.md
```
Expected: No matches for old component names (SwipePager references are the only sidebar-related ones)

- [ ] **Step 3: Commit**

```bash
git add ui/mobile/README.md
git commit -m "docs(mobile): update README to reflect SwipePager replacing Sidebar + ContentPanGestureArea"
```

---

## Task 6: Manual verification on device/emulator

This task is manual — run the app and verify all interactions work correctly.

- [ ] **Step 1: Build and install**

```bash
cd ui/mobile && npx expo run:android
```

- [ ] **Step 2: Verify main chat page**

Checklist:
- [ ] Right swipe from center → left sidebar slides in, chat page visible at ~20% on right edge
- [ ] Left swipe from center → right Todo sidebar slides in, chat page visible at ~20% on left edge
- [ ] Tap hamburger button → animates to left sidebar
- [ ] Tap session in sidebar → switches session and animates back to center
- [ ] Tap "新对话" → creates draft and animates back to center
- [ ] Drag gesture follows finger smoothly (no jank on 60/90/120fps)
- [ ] Fast fling snaps directly to target panel
- [ ] Over-drag beyond boundaries shows rubber band resistance and springs back
- [ ] FlatList vertical scroll works without triggering horizontal pan
- [ ] Keyboard opens/closes correctly, Composer follows keyboard
- [ ] Delete session dialog appears correctly (it's outside SwipePager)

- [ ] **Step 3: Verify Sub-Agent session detail page**

Checklist:
- [ ] Left swipe → right Todo sidebar slides in
- [ ] Right swipe does nothing (no left panel, clamps at boundary)
- [ ] Back button works (Stack pop, not pager navigation)
- [ ] Keyboard and Composer work correctly

- [ ] **Step 4: Commit any fixes if needed**

If any issues are found during manual testing, fix them and commit:
```bash
git add <fixed files>
git commit -m "fix(mobile): <describe the fix>"
```
