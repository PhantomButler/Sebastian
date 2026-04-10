import { forwardRef, useImperativeHandle, useMemo, useRef, useState, type ReactNode } from 'react';
import { PanResponder, Pressable, StyleSheet, View, useWindowDimensions, type LayoutChangeEvent } from 'react-native';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  cancelAnimation,
} from 'react-native-reanimated';

const DEFAULT_SIDEBAR_RATIO = 0.8;
const VELOCITY_THRESHOLD = 0.5; // PanResponder vx is px/ms; 0.5 = 500 px/s
const SPRING_CONFIG = { damping: 22, stiffness: 220, mass: 0.8 };
const RUBBER_BAND_FACTOR = 0.3;
const SWIPE_THRESHOLD = 10;
const DIM_OPACITY = 0.35;

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
    const { width: screenWidth, height: screenHeight } = useWindowDimensions();
    const hasLeft = left !== undefined;
    const hasRight = right !== undefined;
    const sidebarPx = Math.round(screenWidth * sidebarWidth);

    const [containerHeight, setContainerHeight] = useState(screenHeight);

    function handleContainerLayout(e: LayoutChangeEvent) {
      const h = e.nativeEvent.layout.height;
      if (h > 0) setContainerHeight(h);
    }

    // translateX drives all panel animations, mirroring the old flex-row track offset.
    // snapPoints[i] is the translateX value that brings panel i into view.
    //   hasLeft+hasRight: [0, -sidebarPx, -2*sidebarPx]
    //   left or right only: [0, -sidebarPx]
    //   centerIndex = 1 when hasLeft, else 0
    const snapPoints = useMemo(() => {
      if (hasLeft && hasRight) return [0, -sidebarPx, -(2 * sidebarPx)];
      if (hasLeft || hasRight) return [0, -sidebarPx];
      return [0];
    }, [hasLeft, hasRight, sidebarPx]);

    const centerIndex = hasLeft ? 1 : 0;
    const translateX = useSharedValue(snapPoints[centerIndex]);
    const gesture = useRef({ startX: 0, startIdx: 0 });

    const minSnap = snapPoints[snapPoints.length - 1];
    const maxSnap = snapPoints[0];

    const [activePanel, setActivePanel] = useState<PanelPosition>('center');

    function fireOnPanelChange(snapValue: number) {
      let panel: PanelPosition = 'center';
      if (hasLeft && snapValue === snapPoints[0]) panel = 'left';
      else if (snapValue !== snapPoints[centerIndex]) panel = 'right';
      setActivePanel(panel);
      if (onPanelChange) onPanelChange(panel);
    }

    function findCurrentIndex(x: number): number {
      let idx = 0;
      let best = Math.abs(x - snapPoints[0]);
      for (let i = 1; i < snapPoints.length; i++) {
        const d = Math.abs(x - snapPoints[i]);
        if (d < best) { best = d; idx = i; }
      }
      return idx;
    }

    function navigateTo(target: number) {
      translateX.value = withSpring(target, SPRING_CONFIG);
      fireOnPanelChange(target);
    }

    // PanResponder only claims horizontal swipes; vertical touches pass through to FlatList.
    const panResponder = useMemo(() => PanResponder.create({
      onMoveShouldSetPanResponder: (_, { dx, dy }) =>
        Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > SWIPE_THRESHOLD,
      onPanResponderGrant: () => {
        cancelAnimation(translateX);
        gesture.current.startX = translateX.value;
        gesture.current.startIdx = findCurrentIndex(translateX.value);
      },
      onPanResponderMove: (_, { dx }) => {
        const raw = gesture.current.startX + dx;
        if (raw > maxSnap) {
          translateX.value = maxSnap + (raw - maxSnap) * RUBBER_BAND_FACTOR;
        } else if (raw < minSnap) {
          translateX.value = minSnap + (raw - minSnap) * RUBBER_BAND_FACTOR;
        } else {
          translateX.value = raw;
        }
      },
      onPanResponderRelease: (_, { vx }) => {
        const startIdx = gesture.current.startIdx;
        const allowedMin = Math.max(0, startIdx - 1);
        const allowedMax = Math.min(snapPoints.length - 1, startIdx + 1);

        let targetIdx: number;
        if (Math.abs(vx) > VELOCITY_THRESHOLD) {
          const direction = vx > 0 ? -1 : 1;
          targetIdx = Math.max(allowedMin, Math.min(allowedMax, startIdx + direction));
        } else {
          targetIdx = startIdx;
          let best = Math.abs(translateX.value - snapPoints[startIdx]);
          for (let i = allowedMin; i <= allowedMax; i++) {
            const d = Math.abs(translateX.value - snapPoints[i]);
            if (d < best) { best = d; targetIdx = i; }
          }
        }
        translateX.value = withSpring(snapPoints[targetIdx], SPRING_CONFIG);
        fireOnPanelChange(snapPoints[targetIdx]);
      },
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }), [snapPoints, sidebarPx, minSnap, maxSnap]);

    // Each panel's translateX reproduces the visual position it had in the old flex-row track,
    // but now every panel is absolutely positioned so its layout coordinates are fixed:
    //
    //   left   panel: layout x = 0..sidebarPx          (position: absolute, left: 0)
    //   center panel: layout x = 0..screenWidth         (position: absolute, left: 0)
    //   right  panel: layout x = screenWidth-sidebarPx..screenWidth  (position: absolute, right: 0)
    //
    // When a panel is the active panel, its visual position matches its layout position,
    // so Android touch hit-testing works correctly. Inactive panels have pointerEvents="none".
    //
    // translateX formulas (same as track offset + shared translateX.value):
    //   left:   translateX.value  (was at offset 0 in the track)
    //   center: translateX.value + leftPanelWidth
    //   right:  translateX.value + (hasLeft ? 2 : 1) * sidebarPx
    //           (derived so that right-panel visual = screenWidth-sidebarPx when open)

    const leftPanelWidth = hasLeft ? sidebarPx : 0;

    const leftAnimStyle = useAnimatedStyle(() => ({
      transform: [{ translateX: translateX.value }],
    }));

    const centerAnimStyle = useAnimatedStyle(() => ({
      transform: [{ translateX: translateX.value + leftPanelWidth }],
    }));

    const rightAnimStyle = useAnimatedStyle(() => ({
      transform: [{ translateX: translateX.value + (hasLeft ? 2 : 1) * sidebarPx }],
    }));

    const centerSnapValue = snapPoints[centerIndex];
    const dimStyle = useAnimatedStyle(() => {
      const dist = Math.abs(translateX.value - centerSnapValue);
      const ratio = Math.min(dist / sidebarPx, 1);
      return { opacity: ratio * DIM_OPACITY };
    });

    useImperativeHandle(ref, () => ({
      goToCenter: () => navigateTo(snapPoints[centerIndex]),
      goToLeft: () => { if (hasLeft) navigateTo(snapPoints[0]); },
      goToRight: () => { if (hasRight) navigateTo(snapPoints[snapPoints.length - 1]); },
    }));

    return (
      <View style={styles.container} onLayout={handleContainerLayout} {...panResponder.panHandlers}>
        {/* Render order: center → left → right, so right has highest z-order.
            Active sidebars sit on top; center is always beneath them. */}

        {/* Center panel: layout x=0..screenWidth, always touchable. */}
        <Animated.View
          style={[styles.center, { width: screenWidth, height: containerHeight }, centerAnimStyle]}
        >
          {children}
          {(hasLeft || hasRight) && (
            <Animated.View style={[styles.dimOverlay, dimStyle]} pointerEvents="none" />
          )}
          {activePanel !== 'center' && (
            <Pressable
              style={StyleSheet.absoluteFillObject}
              onPress={() => navigateTo(snapPoints[centerIndex])}
            />
          )}
        </Animated.View>

        {/* Left panel: layout x=0..sidebarPx — matches visual position when open. */}
        {hasLeft && (
          <Animated.View
            style={[styles.leftPanel, { width: sidebarPx, height: containerHeight }, leftAnimStyle]}
            pointerEvents={activePanel === 'left' ? 'auto' : 'none'}
          >
            {left}
            <View style={styles.panelSepRight} pointerEvents="none" />
          </Animated.View>
        )}

        {/* Right panel: layout x=screenWidth-sidebarPx..screenWidth — matches visual when open. */}
        {hasRight && (
          <Animated.View
            style={[styles.rightPanel, { width: sidebarPx, height: containerHeight }, rightAnimStyle]}
            pointerEvents={activePanel === 'right' ? 'auto' : 'none'}
          >
            <View style={styles.panelSepLeft} pointerEvents="none" />
            {right}
          </Animated.View>
        )}
      </View>
    );
  },
);

const styles = StyleSheet.create({
  container: {
    flex: 1,
    overflow: 'hidden',
  },
  center: {
    position: 'absolute',
    left: 0,
    top: 0,
    overflow: 'hidden',
  },
  leftPanel: {
    position: 'absolute',
    left: 0,
    top: 0,
    overflow: 'hidden',
  },
  rightPanel: {
    position: 'absolute',
    right: 0,
    top: 0,
    overflow: 'hidden',
  },
  dimOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: '#000',
  },
  panelSepRight: {
    position: 'absolute',
    right: 0,
    top: 0,
    bottom: 0,
    width: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.12)',
  },
  panelSepLeft: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.12)',
  },
});
