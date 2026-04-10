import { forwardRef, useImperativeHandle, useMemo, useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, View, useWindowDimensions, type LayoutChangeEvent } from 'react-native';
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

    // GestureDetector on Android adds an internal wrapper View whose height is
    // auto-sized (content-height) rather than inheriting the parent's flex: 1.
    // This breaks the FlatList height chain and prevents scrolling.
    // Fix: measure the container's actual pixel height via onLayout and pass it
    // explicitly to the track and panels so FlatList gets a bounded height.
    const [containerHeight, setContainerHeight] = useState(screenHeight);

    function handleContainerLayout(e: LayoutChangeEvent) {
      const h = e.nativeEvent.layout.height;
      if (h > 0) setContainerHeight(h);
    }

    const snapPoints = useMemo(() => {
      if (hasLeft && hasRight) {
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

    const centerIndex = hasLeft ? 1 : 0;
    const translateX = useSharedValue(snapPoints[centerIndex]);
    const startX = useSharedValue(0);
    const startPanelIndex = useSharedValue(0);

    const minSnap = snapPoints[snapPoints.length - 1];
    const maxSnap = snapPoints[0];

    const [isSidebarOpen, setIsSidebarOpen] = useState(false);

    function fireOnPanelChange(snapValue: number) {
      setIsSidebarOpen(snapValue !== snapPoints[centerIndex]);
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

    function navigateTo(target: number) {
      translateX.value = withSpring(target, SPRING_CONFIG);
      fireOnPanelChange(target);
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
      .activeOffsetX([-10, 10])
      .failOffsetY([-5, 5])
      .onStart(() => {
        'worklet';
        startX.value = translateX.value;
        startPanelIndex.value = findCurrentIndex(translateX.value);
      })
      .onUpdate((e) => {
        'worklet';
        const raw = startX.value + e.translationX;
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
        const startIdx = startPanelIndex.value;
        const allowedMin = Math.max(0, startIdx - 1);
        const allowedMax = Math.min(snapPoints.length - 1, startIdx + 1);

        let targetIdx: number;
        if (Math.abs(e.velocityX) > VELOCITY_THRESHOLD) {
          const direction = e.velocityX > 0 ? -1 : 1;
          targetIdx = Math.max(allowedMin, Math.min(allowedMax, startIdx + direction));
        } else {
          targetIdx = startIdx;
          let minDist = Math.abs(translateX.value - snapPoints[startIdx]);
          for (let i = allowedMin; i <= allowedMax; i++) {
            const dist = Math.abs(translateX.value - snapPoints[i]);
            if (dist < minDist) {
              minDist = dist;
              targetIdx = i;
            }
          }
        }
        snapTo(snapPoints[targetIdx]);
      });

    const animatedStyle = useAnimatedStyle(() => ({
      transform: [{ translateX: translateX.value }],
    }));

    const centerSnapValue = snapPoints[centerIndex];
    const dimStyle = useAnimatedStyle(() => {
      const distFromCenter = Math.abs(translateX.value - centerSnapValue);
      const ratio = Math.min(distFromCenter / sidebarPx, 1);
      return { opacity: ratio * DIM_OPACITY };
    });

    useImperativeHandle(ref, () => ({
      goToCenter: () => navigateTo(snapPoints[centerIndex]),
      goToLeft: () => { if (hasLeft) navigateTo(snapPoints[0]); },
      goToRight: () => { if (hasRight) navigateTo(snapPoints[snapPoints.length - 1]); },
    }));

    return (
      <View style={styles.container} onLayout={handleContainerLayout}>
        <GestureDetector gesture={panGesture}>
          <Animated.View style={[styles.track, { height: containerHeight }, animatedStyle]}>
            {hasLeft && (
              <View style={{ width: sidebarPx, height: containerHeight, overflow: 'hidden' }}>
                {left}
                <View style={styles.panelSepRight} pointerEvents="none" />
              </View>
            )}
            <View style={{ width: screenWidth, height: containerHeight, overflow: 'hidden' }}>
              {children}
              {(hasLeft || hasRight) && (
                <Animated.View style={[styles.dimOverlay, dimStyle]} pointerEvents="none" />
              )}
              {isSidebarOpen && (
                <Pressable
                  style={StyleSheet.absoluteFillObject}
                  onPress={() => navigateTo(snapPoints[centerIndex])}
                />
              )}
            </View>
            {hasRight && (
              <View style={{ width: sidebarPx, height: containerHeight, overflow: 'hidden' }}>
                <View style={styles.panelSepLeft} pointerEvents="none" />
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
