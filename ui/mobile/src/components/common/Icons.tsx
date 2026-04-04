/**
 * Icon components using react-native-svg inline components.
 * Path data comes from src/assets/icons/*.svg (kept as design source files).
 * Using inline Svg/Path avoids the SVG file transformer, which is unreliable
 * across Expo SDK versions.
 */
import type { ViewStyle } from 'react-native';
import Svg, { Path } from 'react-native-svg';

interface IconProps {
  size?: number;
  color?: string;
  style?: ViewStyle;
}

// Path data from src/assets/icons/delete.svg (openJax TrashIcon)
export function DeleteIcon({ size = 16, color = '#bbb', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M781.28 851.36a58.56 58.56 0 0 1-58.56 58.56H301.28a58.72 58.72 0 0 1-58.56-58.56V230.4h538.56z m-421.6-725.92a11.84 11.84 0 0 1 12-12h281.28a11.84 11.84 0 0 1 12 12V160H359.68zM956.8 160H734.72v-34.56a81.76 81.76 0 0 0-81.76-81.76H371.68a82.08 82.08 0 0 0-81.76 81.76V160H67.2a35.36 35.36 0 0 0 0 70.56h105.12v620.8a128.96 128.96 0 0 0 128.96 128.96h421.44a128.96 128.96 0 0 0 128.96-128.96V230.4H956.8a35.2 35.2 0 0 0 35.2-35.2 34.56 34.56 0 0 0-35.2-35.2zM512 804.16a35.2 35.2 0 0 0 35.2-35.36V393.92a35.2 35.2 0 1 0-70.4 0V768.8a35.2 35.2 0 0 0 35.2 35.36m-164.32 0a35.36 35.36 0 0 0 35.36-35.36V393.92a35.36 35.36 0 1 0-70.56 0V768.8a36.32 36.32 0 0 0 35.2 35.36m328.64 0a35.36 35.36 0 0 0 35.2-35.36V393.92a35.36 35.36 0 1 0-70.56 0V768.8a35.36 35.36 0 0 0 35.36 35.36"
        fill={color}
      />
    </Svg>
  );
}
