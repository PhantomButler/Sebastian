import { forwardRef, useEffect, useImperativeHandle, useMemo, useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, View, useWindowDimensions, type LayoutChangeEvent } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  cancelAnimation,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';

const DEFAULT_SIDEBAR_RATIO = 0.8;
// RNGH velocityX is in px/s (vs PanResponder's px/ms).
const VELOCITY_THRESHOLD = 500;
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

    // translateX drives all panel animations (same logic as before).
    const snapPoints = useMemo(() => {
      if (hasLeft && hasRight) return [0, -sidebarPx, -(2 * sidebarPx)];
      if (hasLeft || hasRight) return [0, -sidebarPx];
      return [0];
    }, [hasLeft, hasRight, sidebarPx]);

    const centerIndex = hasLeft ? 1 : 0;
    const translateX = useSharedValue(snapPoints[centerIndex]);

    // Shared values used inside gesture worklets (no JS-thread access needed).
    const snapsSV = useSharedValue<number[]>(snapPoints);
    const minSnapSV = useSharedValue(snapPoints[snapPoints.length - 1]);
    const maxSnapSV = useSharedValue(snapPoints[0]);
    const startX = useSharedValue(0);
    const startIdx = useSharedValue(centerIndex);

    useEffect(() => {
      snapsSV.value = snapPoints;
      minSnapSV.value = snapPoints[snapPoints.length - 1];
      maxSnapSV.value = snapPoints[0];
    }, [snapPoints]);

    const [activePanel, setActivePanel] = useState<PanelPosition>('center');

    function fireOnPanelChange(snapValue: number) {
      const snaps = snapsSV.value;
      let panel: PanelPosition = 'center';
      if (hasLeft && snapValue === snaps[0]) panel = 'left';
      else if (snapValue !== snaps[centerIndex]) panel = 'right';
      setActivePanel(panel);
      onPanelChange?.(panel);
    }

    function navigateTo(target: number) {
      translateX.value = withSpring(target, SPRING_CONFIG);
      fireOnPanelChange(target);
    }

    // Worklet: find snap index closest to x.
    function findClosestIdx(x: number, snaps: number[]): number {
      'worklet';
      let idx = 0;
      let best = Math.abs(x - snaps[0]);
      for (let i = 1; i < snaps.length; i++) {
        const d = Math.abs(x - snaps[i]);
        if (d < best) { best = d; idx = i; }
      }
      return idx;
    }

    // Pan gesture runs on the native UI thread (RNGH), so it is unaffected by
    // JS-thread load during streaming. failOffsetY ensures vertical scrolling
    // in FlatList is never hijacked.
    const pan = Gesture.Pan()
      .activeOffsetX([-SWIPE_THRESHOLD, SWIPE_THRESHOLD])
      .failOffsetY([-12, 12])
      .onBegin(() => {
        'worklet';
        cancelAnimation(translateX);
        startX.value = translateX.value;
        startIdx.value = findClosestIdx(translateX.value, snapsSV.value);
      })
      .onUpdate(({ translationX }) => {
        'worklet';
        const raw = startX.value + translationX;
        const mn = minSnapSV.value;
        const mx = maxSnapSV.value;
        if (raw > mx) {
          translateX.value = mx + (raw - mx) * RUBBER_BAND_FACTOR;
        } else if (raw < mn) {
          translateX.value = mn + (raw - mn) * RUBBER_BAND_FACTOR;
        } else {
          translateX.value = raw;
        }
      })
      .onEnd(({ velocityX }) => {
        'worklet';
        const snaps = snapsSV.value;
        const sIdx = startIdx.value;
        const allowedMin = Math.max(0, sIdx - 1);
        const allowedMax = Math.min(snaps.length - 1, sIdx + 1);

        let targetIdx: number;
        if (Math.abs(velocityX) > VELOCITY_THRESHOLD) {
          const direction = velocityX > 0 ? -1 : 1;
          targetIdx = Math.max(allowedMin, Math.min(allowedMax, sIdx + direction));
        } else {
          targetIdx = sIdx;
          let best = Math.abs(translateX.value - snaps[sIdx]);
          for (let i = allowedMin; i <= allowedMax; i++) {
            const d = Math.abs(translateX.value - snaps[i]);
            if (d < best) { best = d; targetIdx = i; }
          }
        }
        const target = snaps[targetIdx];
        translateX.value = withSpring(target, SPRING_CONFIG);
        runOnJS(fireOnPanelChange)(target);
      });

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
      <GestureDetector gesture={pan}>
        <View style={styles.container} onLayout={handleContainerLayout}>
          {/* Center panel */}
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

          {/* Left panel */}
          {hasLeft && (
            <Animated.View
              style={[styles.leftPanel, { width: sidebarPx, height: containerHeight }, leftAnimStyle]}
              pointerEvents={activePanel === 'left' ? 'auto' : 'none'}
            >
              {left}
              <View style={styles.panelSepRight} pointerEvents="none" />
            </Animated.View>
          )}

          {/* Right panel */}
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
      </GestureDetector>
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
