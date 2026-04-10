import { forwardRef, useImperativeHandle, useMemo, type ReactNode } from 'react';
import { StyleSheet, View, useWindowDimensions } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  runOnJS,
} from 'react-native-reanimated';

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
    const { width: screenWidth } = useWindowDimensions();
    const hasLeft = left !== undefined;
    const hasRight = right !== undefined;
    const sidebarPx = Math.round(screenWidth * sidebarWidth);

    const snapPoints = useMemo(() => {
      if (hasLeft && hasRight) {
        // [leftSnap, centerSnap, rightSnap]
        return [0, -sidebarPx, -(sidebarPx + screenWidth)];
      }
      if (hasLeft) {
        return [0, -sidebarPx];
      }
      if (hasRight) {
        return [0, -sidebarPx];
      }
      return [0];
    }, [hasLeft, hasRight, sidebarPx, screenWidth]);

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
      runOnJS(fireOnPanelChange)(target);
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
      <View style={styles.container}>
        <GestureDetector gesture={panGesture}>
          <Animated.View style={[styles.track, animatedStyle]}>
            {hasLeft && (
              <View style={[styles.panel, { width: sidebarPx }]}>
                {left}
              </View>
            )}
            <View style={[styles.panel, { width: screenWidth }]}>
              {children}
            </View>
            {hasRight && (
              <View style={[styles.panel, { width: sidebarPx }]}>
                {right}
              </View>
            )}
          </Animated.View>
        </GestureDetector>
      </View>
    );
  },
);

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  track: {
    flexDirection: 'row',
    flex: 1,
  },
  panel: {
    height: '100%',
    overflow: 'hidden',
  },
});
