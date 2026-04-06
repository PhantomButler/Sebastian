# theme/

> 上级：[src/](../README.md)

## 目录职责

移动端主题系统，提供日间/夜间配色切换能力。通过 React Context 向全 App 提供当前主题的颜色 token 对象。

## 目录结构

```
theme/
├── colors.ts          # Light / Dark 颜色 token 定义（ThemeColors 类型 + lightColors / darkColors 对象）
└── ThemeContext.tsx    # ThemeProvider（根部包裹）+ useTheme() hook + useIsDark() hook
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 调整某种颜色的日间或夜间值 | [colors.ts](colors.ts) |
| 新增颜色 token | [colors.ts](colors.ts)（加字段）→ ThemeContext 自动生效 |
| 修改主题切换逻辑（system/light/dark） | [ThemeContext.tsx](ThemeContext.tsx) |

## 使用方式

```typescript
import { useTheme } from '../../theme/ThemeContext';

function MyComponent() {
  const colors = useTheme();
  return <View style={{ backgroundColor: colors.background }} />;
}
```

---

> 修改本目录后，请同步更新此 README。
