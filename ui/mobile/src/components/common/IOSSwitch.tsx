import { useEffect, useRef } from 'react';
import { Animated, Pressable, StyleSheet } from 'react-native';

interface Props {
  value: boolean;
  onValueChange: (value: boolean) => void;
  disabled?: boolean;
  activeColor?: string;
}

const TRACK_W = 51;
const TRACK_H = 31;
const THUMB_SIZE = 27;
const MARGIN = 2;
const TRAVEL = TRACK_W - THUMB_SIZE - MARGIN * 2; // 20

export function IOSSwitch({
  value,
  onValueChange,
  disabled = false,
  activeColor = '#34C759',
}: Props) {
  const anim = useRef(new Animated.Value(value ? 1 : 0)).current;

  useEffect(() => {
    Animated.spring(anim, {
      toValue: value ? 1 : 0,
      useNativeDriver: false,
      bounciness: 0,
      speed: 18,
    }).start();
  }, [value]);

  const trackBg = anim.interpolate({
    inputRange: [0, 1],
    outputRange: ['#E5E5EA', activeColor],
  });

  const thumbX = anim.interpolate({
    inputRange: [0, 1],
    outputRange: [MARGIN, MARGIN + TRAVEL],
  });

  return (
    <Pressable
      onPress={() => !disabled && onValueChange(!value)}
      style={{ opacity: disabled ? 0.4 : 1 }}
      hitSlop={8}
    >
      <Animated.View style={[styles.track, { backgroundColor: trackBg }]}>
        <Animated.View style={[styles.thumb, { transform: [{ translateX: thumbX }] }]} />
      </Animated.View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  track: {
    width: TRACK_W,
    height: TRACK_H,
    borderRadius: TRACK_H / 2,
  },
  thumb: {
    position: 'absolute',
    top: MARGIN,
    width: THUMB_SIZE,
    height: THUMB_SIZE,
    borderRadius: THUMB_SIZE / 2,
    backgroundColor: '#FFFFFF',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 3,
    elevation: 4,
  },
});
