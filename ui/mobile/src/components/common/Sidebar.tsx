import { useRef, useEffect } from 'react';
import { Animated, Dimensions, StyleSheet, TouchableOpacity, View } from 'react-native';
import { PanGestureHandler, State } from 'react-native-gesture-handler';

const SIDEBAR_WIDTH = Dimensions.get('window').width * 0.75;
const SWIPE_THRESHOLD = 50;

interface Props {
  visible: boolean;
  onOpen: () => void;
  onClose: () => void;
  children: React.ReactNode;
}

export function Sidebar({ visible, onOpen, onClose, children }: Props) {
  const translateX = useRef(new Animated.Value(-SIDEBAR_WIDTH)).current;

  useEffect(() => {
    Animated.timing(translateX, {
      toValue: visible ? 0 : -SIDEBAR_WIDTH,
      duration: 250,
      useNativeDriver: true,
    }).start();
  }, [visible]);

  function handleEdgeGesture({ nativeEvent }: any) {
    if (nativeEvent.state === State.END && nativeEvent.translationX > SWIPE_THRESHOLD) {
      onOpen();
    }
  }

  function handleSidebarGesture({ nativeEvent }: any) {
    if (nativeEvent.state === State.END && nativeEvent.translationX < -SWIPE_THRESHOLD) {
      onClose();
    }
  }

  return (
    <View
      style={[StyleSheet.absoluteFill, { pointerEvents: visible ? 'auto' : 'box-none' }]}
    >
      {/* Overlay: 点击右侧区域关闭 */}
      <TouchableOpacity
        style={[styles.overlay, { display: visible ? 'flex' : 'none' }]}
        activeOpacity={1}
        onPress={onClose}
      />

      {/* 侧边栏面板：左滑关闭 */}
      <PanGestureHandler onHandlerStateChange={handleSidebarGesture} enabled={visible}>
        <Animated.View
          style={[styles.sidebar, { transform: [{ translateX }] }]}
          pointerEvents={visible ? 'auto' : 'none'}
        >
          {children}
        </Animated.View>
      </PanGestureHandler>

      {/* 左边缘触发区：右滑开启（仅在关闭状态渲染） */}
      {!visible && (
        <PanGestureHandler onHandlerStateChange={handleEdgeGesture}>
          <View style={styles.edgeTrigger} />
        </PanGestureHandler>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.4)',
  },
  sidebar: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: SIDEBAR_WIDTH,
    backgroundColor: '#fff',
    shadowColor: '#000',
    shadowOffset: { width: 2, height: 0 },
    shadowOpacity: 0.12,
    shadowRadius: 8,
    elevation: 8,
  },
  edgeTrigger: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 25,
  },
});
