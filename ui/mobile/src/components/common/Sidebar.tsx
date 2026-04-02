import { useRef, useEffect } from 'react';
import { Animated, Dimensions, StyleSheet, TouchableOpacity, View } from 'react-native';

const SIDEBAR_WIDTH = Dimensions.get('window').width * 0.75;

interface Props {
  visible: boolean;
  onClose: () => void;
  children: React.ReactNode;
}

export function Sidebar({ visible, onClose, children }: Props) {
  const translateX = useRef(new Animated.Value(-SIDEBAR_WIDTH)).current;

  useEffect(() => {
    Animated.timing(translateX, {
      toValue: visible ? 0 : -SIDEBAR_WIDTH,
      duration: 250,
      useNativeDriver: true,
    }).start();
  }, [visible]);

  return (
    <View style={[StyleSheet.absoluteFill, { pointerEvents: visible ? 'auto' : 'none' }]}>
      <TouchableOpacity
        style={[styles.overlay, { display: visible ? 'flex' : 'none' }]}
        activeOpacity={1}
        onPress={onClose}
      />
      <Animated.View style={[styles.sidebar, { transform: [{ translateX }] }]}>
        {children}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.4)' },
  sidebar: { position: 'absolute', left: 0, top: 0, bottom: 0, width: SIDEBAR_WIDTH, backgroundColor: '#fff' },
});
