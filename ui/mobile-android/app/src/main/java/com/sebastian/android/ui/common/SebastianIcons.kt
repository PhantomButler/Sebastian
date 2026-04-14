package com.sebastian.android.ui.common

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp

/**
 * Custom icon set migrated from the React Native app (ui/mobile/src/components/common/Icons.tsx).
 * Each icon is a lazily-built ImageVector, consistent with how Material Icons work.
 */
object SebastianIcons {

    val Delete: ImageVector by lazy {
        ImageVector.Builder(
            name = "Delete",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(685.85f, 61.04f)
                lineTo(634.07f, 11.28f)
                curveTo(628.57f, 5.79f, 621.05f, 2.89f, 613.53f, 2.89f)
                horizontalLineToRelative(-203.06f)
                curveToRelative(-7.81f, 0f, -15.04f, 2.89f, -20.54f, 8.39f)
                lineToRelative(-51.78f, 49.75f)
                curveToRelative(-5.5f, 5.21f, -13.02f, 8.39f, -20.54f, 8.39f)
                horizontalLineTo(131.62f)
                curveToRelative(-16.49f, 0f, -29.79f, 13.31f, -29.79f, 29.79f)
                verticalLineToRelative(71.16f)
                curveToRelative(0f, 16.49f, 13.31f, 29.79f, 29.79f, 29.79f)
                horizontalLineToRelative(760.77f)
                curveToRelative(16.49f, 0f, 29.79f, -13.31f, 29.79f, -29.79f)
                verticalLineTo(98.93f)
                curveToRelative(0f, -16.49f, -13.31f, -29.79f, -29.79f, -29.79f)
                horizontalLineToRelative(-186f)
                curveToRelative(-7.52f, 0f, -15.04f, -2.89f, -20.54f, -8.1f)
                close()
                moveTo(134.22f, 902.8f)
                curveToRelative(-0.87f, 64.51f, 50.91f, 117.44f, 115.42f, 118.31f)
                horizontalLineToRelative(524.73f)
                curveToRelative(64.51f, -0.87f, 116.28f, -53.8f, 115.42f, -118.31f)
                verticalLineTo(328.61f)
                curveToRelative(0f, -16.49f, -13.31f, -29.79f, -29.79f, -29.79f)
                horizontalLineTo(163.72f)
                curveToRelative(-16.49f, 0f, -29.79f, 13.31f, -29.79f, 29.79f)
                verticalLineToRelative(574.19f)
                close()
                moveTo(390.8f, 798.38f)
                horizontalLineToRelative(-29.51f)
                curveToRelative(-16.49f, 0f, -29.79f, -13.31f, -29.79f, -29.79f)
                verticalLineToRelative(-239.51f)
                curveToRelative(0f, -16.49f, 13.31f, -29.79f, 29.79f, -29.79f)
                horizontalLineToRelative(29.51f)
                curveToRelative(16.49f, 0f, 29.79f, 13.31f, 29.79f, 29.79f)
                verticalLineToRelative(239.51f)
                curveToRelative(-0.29f, 16.49f, -13.6f, 29.79f, -29.79f, 29.79f)
                close()
                moveTo(663.86f, 798.38f)
                horizontalLineToRelative(-30.66f)
                curveToRelative(-16.49f, 0f, -29.79f, -13.31f, -29.79f, -29.79f)
                verticalLineToRelative(-239.51f)
                curveToRelative(0f, -16.49f, 13.31f, -29.79f, 29.79f, -29.79f)
                horizontalLineToRelative(30.66f)
                curveToRelative(16.2f, 0f, 29.51f, 13.31f, 29.79f, 29.51f)
                lineToRelative(1.45f, 239.51f)
                curveToRelative(0f, 16.78f, -13.31f, 30.08f, -29.79f, 30.08f)
                close()
            }
        }.build()
    }

    /** 两条横杠的侧栏/菜单图标（仿 ChatGPT 顶栏左按钮） */
    val Sidebar: ImageVector by lazy {
        ImageVector.Builder(
            name = "Sidebar",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            // 上横
            path(fill = SolidColor(Color.Black)) {
                moveTo(220f, 340f)
                horizontalLineToRelative(584f)
                curveToRelative(22f, 0f, 40f, 18f, 40f, 40f)
                curveToRelative(0f, 22f, -18f, 40f, -40f, 40f)
                horizontalLineTo(220f)
                curveToRelative(-22f, 0f, -40f, -18f, -40f, -40f)
                curveToRelative(0f, -22f, 18f, -40f, 40f, -40f)
                close()
            }
            // 下横（短，约上横 60% 长）
            path(fill = SolidColor(Color.Black)) {
                moveTo(220f, 604f)
                horizontalLineToRelative(340f)
                curveToRelative(22f, 0f, 40f, 18f, 40f, 40f)
                curveToRelative(0f, 22f, -18f, 40f, -40f, 40f)
                horizontalLineTo(220f)
                curveToRelative(-22f, 0f, -40f, -18f, -40f, -40f)
                curveToRelative(0f, -22f, 18f, -40f, 40f, -40f)
                close()
            }
        }.build()
    }

    val Edit: ImageVector by lazy {
        ImageVector.Builder(
            name = "Edit",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(772.18f, 141.48f)
                curveToRelative(-1.77f, 0f, -3.53f, 0.11f, -5.29f, 0.34f)
                curveToRelative(-13.91f, 0f, -26.07f, 6.95f, -34.73f, 17.41f)
                lineToRelative(-219.31f, 260.91f)
                curveToRelative(-9.39f, 11.18f, -18.09f, 27.56f, -26.03f, 45.23f)
                lineToRelative(-41.81f, 142.68f)
                curveToRelative(-3.15f, 10.75f, 0.51f, 22.44f, 8.75f, 34.77f)
                curveToRelative(5.89f, 4.65f, 13.1f, 6.95f, 20.86f, 6.95f)
                curveToRelative(5.21f, 0f, 10.45f, -1.71f, 13.99f, -5.21f)
                lineToRelative(135.59f, -64.38f)
                horizontalLineToRelative(1.71f)
                curveToRelative(15.7f, -8.66f, 29.7f, -19.11f, 40.11f, -33.02f)
                lineToRelative(217.39f, -257.45f)
                curveToRelative(19.2f, -20.91f, 15.74f, -53.97f, -5.21f, -71.34f)
                lineToRelative(-64.97f, -65.04f)
                curveToRelative(-9.05f, -7.55f, -19.5f, -12.5f, -31.23f, -12.5f)
                moveTo(771.88f, 211.33f)
                lineToRelative(54.49f, 46.81f)
                lineToRelative(-209.28f, 247.72f)
                lineToRelative(-1.19f, 1.41f)
                lineToRelative(-1.07f, 1.49f)
                curveToRelative(-3.88f, 3.53f, -8.02f, 7.41f, -12.42f, 10.97f)
                lineToRelative(-5.55f, 2.65f)
                lineToRelative(-69.72f, 33.07f)
                lineToRelative(20.14f, -68.91f)
                curveToRelative(4.39f, -10.37f, 9.39f, -19.11f, 14.59f, -25.17f)
                lineToRelative(210.01f, -250.03f)
                close()
            }
            path(fill = SolidColor(Color.Black)) {
                moveTo(442.62f, 174.63f)
                curveToRelative(1.44f, 21.17f, -0.62f, 42.74f, 4.31f, 63.7f)
                lineToRelative(-4.31f, 0.3f)
                horizontalLineTo(296.19f)
                curveToRelative(-74.56f, 0f, -135.98f, 58.84f, -135.98f, 136.11f)
                verticalLineToRelative(339.63f)
                curveToRelative(0f, 74.56f, 58.84f, 136.11f, 136.19f, 136.15f)
                horizontalLineToRelative(339.54f)
                curveToRelative(74.56f, 0f, 135.85f, -58.84f, 136.06f, -136.15f)
                verticalLineToRelative(-95.57f)
                curveToRelative(21.37f, 1.18f, 42.61f, -0.62f, 64f, -4.31f)
                verticalLineToRelative(99.88f)
                curveToRelative(-0.76f, 109.89f, -86.09f, 200.15f, -200.07f, 200.15f)
                horizontalLineTo(296.11f)
                curveToRelative(-109.89f, 0f, -199.94f, -86.09f, -200.15f, -200.15f)
                verticalLineTo(374.74f)
                curveToRelative(0.76f, -109.89f, 86.09f, -200.11f, 200.15f, -200.11f)
                horizontalLineToRelative(146.43f)
                close()
            }
        }.build()
    }

    val RightArrow: ImageVector by lazy {
        ImageVector.Builder(
            name = "RightArrow",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(296.8f, 856f)
                lineToRelative(357.8f, -344f)
                lineToRelative(-357.8f, -344f)
                curveToRelative(-7.9f, -7.5f, -12.4f, -18f, -12.5f, -28.9f)
                curveToRelative(0f, -36.5f, 45.9f, -54.8f, 72.7f, -28.9f)
                lineToRelative(357.8f, 344f)
                curveToRelative(33.3f, 32f, 33.3f, 83.9f, 0f, 115.8f)
                lineTo(357f, 913.9f)
                curveToRelative(-26.8f, 25.8f, -72.7f, 7.5f, -72.7f, -28.9f)
                curveToRelative(0f, -11f, 4.5f, -21.4f, 12.5f, -29f)
                close()
            }
        }.build()
    }

    val DownArrow: ImageVector by lazy {
        ImageVector.Builder(
            name = "DownArrow",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(
                fill = SolidColor(Color.Black),
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 20f,
            ) {
                moveTo(537.6f, 760.49f)
                lineToRelative(175.72f, -175.72f)
                curveToRelative(10.0f, -9.99f, 26.19f, -9.99f, 36.18f, 0f)
                curveToRelative(10.0f, 10.0f, 10.0f, 26.22f, 0f, 36.22f)
                lineToRelative(-219.41f, 219.41f)
                curveToRelative(-10.0f, 10.0f, -26.18f, 10.0f, -36.18f, 0f)
                lineTo(274.43f, 620.99f)
                curveToRelative(-10.0f, -10.0f, -10.0f, -26.19f, 0f, -36.18f)
                curveToRelative(10.0f, -10.0f, 26.22f, -10.0f, 36.22f, 0f)
                lineToRelative(175.72f, 175.68f)
                verticalLineTo(186.2f)
                curveToRelative(0f, -14.14f, 11.46f, -25.6f, 25.6f, -25.6f)
                curveToRelative(14.14f, 0f, 25.6f, 11.46f, 25.6f, 25.6f)
                verticalLineTo(760.49f)
                close()
            }
        }.build()
    }

    val Close: ImageVector by lazy {
        ImageVector.Builder(
            name = "Close",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(512.2f, 448.08f)
                lineTo(885.64f, 74.64f)
                curveToRelative(42.43f, -42.43f, 106.07f, -21.21f, 63.64f, 63.64f)
                lineTo(575.84f, 511.72f)
                lineToRelative(374.35f, 374.35f)
                curveToRelative(42.43f, 42.43f, -21.21f, 106.07f, -63.64f, 63.64f)
                lineTo(512.2f, 575.36f)
                lineTo(137.85f, 949.71f)
                curveToRelative(-42.43f, 42.43f, -106.07f, -21.21f, -63.64f, -63.64f)
                lineTo(448.56f, 511.72f)
                lineTo(75.12f, 138.28f)
                curveToRelative(-42.43f, -42.43f, 21.21f, -106.07f, 63.64f, -63.64f)
                lineTo(512.2f, 448.08f)
                close()
            }
        }.build()
    }

    val UpDown: ImageVector by lazy {
        ImageVector.Builder(
            name = "UpDown",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1463f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(428.32f, 353.57f)
                lineTo(695f, 92.31f)
                curveToRelative(20.77f, -20.19f, 54.27f, -20.19f, 75.04f, 0f)
                lineToRelative(266.68f, 261.27f)
                curveToRelative(20.77f, 20.33f, 20.77f, 53.25f, 0f, 73.44f)
                curveToRelative(-20.63f, 20.33f, -54.27f, 20.33f, -75.04f, 0f)
                lineTo(732.45f, 202.61f)
                lineTo(503.37f, 427.01f)
                curveToRelative(-20.77f, 20.33f, -54.27f, 20.33f, -75.04f, 0f)
                curveToRelative(-20.63f, -20.19f, -20.63f, -53.1f, 0f, -73.44f)
                close()
            }
            path(fill = SolidColor(Color.Black)) {
                moveTo(1036.58f, 669.11f)
                lineTo(770.05f, 930.38f)
                curveToRelative(-20.77f, 20.19f, -54.27f, 20.19f, -75.04f, 0f)
                lineTo(428.32f, 669.11f)
                curveToRelative(-20.77f, -20.33f, -20.77f, -53.25f, 0f, -73.44f)
                curveToRelative(20.63f, -20.33f, 54.27f, -20.33f, 75.04f, 0f)
                lineToRelative(229.08f, 224.55f)
                lineToRelative(229.08f, -224.55f)
                curveToRelative(20.77f, -20.33f, 54.27f, -20.33f, 75.04f, 0f)
                curveToRelative(20.77f, 20.33f, 20.77f, 53.1f, 0f, 73.44f)
                close()
            }
        }.build()
    }

    val CycleProgress: ImageVector by lazy {
        ImageVector.Builder(
            name = "CycleProgress",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            // Background ring (fixed light gray)
            path(fill = SolidColor(Color(0xFFDEDEE1))) {
                moveTo(512f, 1017f)
                curveTo(233.53f, 1017f, 7f, 790.48f, 7f, 512f)
                reflectiveCurveTo(233.53f, 7f, 512f, 7f)
                reflectiveCurveToRelative(505f, 226.54f, 505f, 505f)
                reflectiveCurveToRelative(-226.51f, 505f, -505f, 505f)
                close()
                moveTo(512f, 132.66f)
                curveToRelative(-209.18f, 0f, -379.34f, 170.16f, -379.34f, 379.34f)
                reflectiveCurveTo(302.83f, 891.34f, 512f, 891.34f)
                reflectiveCurveTo(891.35f, 721.18f, 891.35f, 512f)
                reflectiveCurveTo(721.19f, 132.66f, 512f, 132.66f)
                close()
            }
            // Active arc (uses tint color)
            path(fill = SolidColor(Color.Black)) {
                moveTo(926.92f, 728.41f)
                curveToRelative(-30.5f, 0f, -55.41f, -21.76f, -59f, -84.61f)
                curveToRelative(9.06f, -48.35f, 23.43f, -79.42f, 23.43f, -131.8f)
                curveToRelative(0f, -209.18f, -170.18f, -379.34f, -379.34f, -379.34f)
                curveToRelative(-34.71f, 0f, -62.84f, -28.13f, -62.84f, -62.84f)
                curveToRelative(0f, -34.71f, 28.13f, -62.84f, 62.84f, -62.84f)
                curveToRelative(278.48f, 0f, 505f, 226.54f, 505f, 505f)
                curveToRelative(0f, 61.52f, -10.97f, 120.51f, -31.16f, 175.3f)
                curveToRelative(-11.39f, 25.58f, -32.64f, 41.11f, -58.92f, 41.11f)
                close()
            }
        }.build()
    }

    val EyeOpen: ImageVector by lazy {
        ImageVector.Builder(
            name = "EyeOpen",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(512f, 298.67f)
                curveToRelative(-162.13f, 0f, -285.87f, 68.27f, -375.47f, 213.33f)
                curveToRelative(89.6f, 145.07f, 213.33f, 213.33f, 375.47f, 213.33f)
                reflectiveCurveToRelative(285.87f, -68.27f, 375.47f, -213.33f)
                curveToRelative(-89.6f, -145.07f, -213.33f, -213.33f, -375.47f, -213.33f)
                close()
                moveTo(512f, 768f)
                curveToRelative(-183.47f, 0f, -328.53f, -85.33f, -426.67f, -256f)
                curveToRelative(98.13f, -170.67f, 243.2f, -256f, 426.67f, -256f)
                reflectiveCurveToRelative(328.53f, 85.33f, 426.67f, 256f)
                curveToRelative(-98.13f, 170.67f, -243.2f, 256f, -426.67f, 256f)
                close()
                moveTo(512f, 597.33f)
                curveToRelative(46.93f, 0f, 85.33f, -38.4f, 85.33f, -85.33f)
                reflectiveCurveToRelative(-38.4f, -85.33f, -85.33f, -85.33f)
                reflectiveCurveToRelative(-85.33f, 38.4f, -85.33f, 85.33f)
                reflectiveCurveToRelative(38.4f, 85.33f, 85.33f, 85.33f)
                close()
                moveTo(512f, 640f)
                curveToRelative(-72.53f, 0f, -128f, -55.47f, -128f, -128f)
                reflectiveCurveToRelative(55.47f, -128f, 128f, -128f)
                reflectiveCurveToRelative(128f, 55.47f, 128f, 128f)
                reflectiveCurveToRelative(-55.47f, 128f, -128f, 128f)
                close()
            }
        }.build()
    }

    val EyeClose: ImageVector by lazy {
        ImageVector.Builder(
            name = "EyeClose",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(332.8f, 729.6f)
                lineToRelative(34.13f, -34.13f)
                curveToRelative(42.67f, 12.8f, 93.87f, 21.33f, 145.07f, 21.33f)
                curveToRelative(162.13f, 0f, 285.87f, -68.27f, 375.47f, -213.33f)
                curveToRelative(-46.93f, -72.53f, -102.4f, -128f, -166.4f, -162.13f)
                lineToRelative(29.87f, -29.87f)
                curveToRelative(72.53f, 42.67f, 132.27f, 106.67f, 183.47f, 192f)
                curveToRelative(-98.13f, 170.67f, -243.2f, 256f, -426.67f, 256f)
                curveToRelative(-59.73f, 4.27f, -119.47f, -8.53f, -174.93f, -29.87f)
                close()
                moveTo(217.6f, 665.6f)
                curveToRelative(-51.2f, -38.4f, -93.87f, -93.87f, -132.27f, -157.87f)
                curveToRelative(98.13f, -170.67f, 243.2f, -256f, 426.67f, -256f)
                curveToRelative(38.4f, 0f, 76.8f, 4.27f, 110.93f, 12.8f)
                lineToRelative(-34.13f, 34.13f)
                curveToRelative(-25.6f, -4.27f, -46.93f, -4.27f, -76.8f, -4.27f)
                curveToRelative(-162.13f, 0f, -285.87f, 68.27f, -375.47f, 213.33f)
                curveToRelative(34.13f, 51.2f, 72.53f, 93.87f, 115.2f, 128f)
                lineToRelative(-34.13f, 29.87f)
                close()
                moveTo(448f, 618.67f)
                lineToRelative(29.87f, -29.87f)
                curveToRelative(8.53f, 4.27f, 21.33f, 4.27f, 29.87f, 4.27f)
                curveToRelative(46.93f, 0f, 85.33f, -38.4f, 85.33f, -85.33f)
                curveToRelative(0f, -12.8f, 0f, -21.33f, -4.27f, -29.87f)
                lineToRelative(29.87f, -29.87f)
                curveToRelative(12.8f, 17.07f, 17.07f, 38.4f, 17.07f, 64f)
                curveToRelative(0f, 72.53f, -55.47f, 128f, -128f, 128f)
                curveToRelative(-17.07f, -4.27f, -38.4f, -12.8f, -59.73f, -21.33f)
                close()
                moveTo(384f, 499.2f)
                curveToRelative(4.27f, -68.27f, 55.47f, -119.47f, 123.73f, -123.73f)
                curveToRelative(0f, 4.27f, -123.73f, 123.73f, -123.73f, 123.73f)
                close()
                moveTo(733.87f, 213.33f)
                lineToRelative(29.87f, 29.87f)
                lineToRelative(-512f, 512f)
                lineToRelative(-34.13f, -29.87f)
                lineTo(733.87f, 213.33f)
                close()
            }
        }.build()
    }

    val TodoCircle: ImageVector by lazy {
        ImageVector.Builder(
            name = "TodoCircle",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                // Dashed circle segments (simplified from original SVG)
                moveTo(512f, 53.33f)
                curveToRelative(63.36f, 0f, 123.93f, 12.46f, 178.65f, 36.27f)
                curveToRelative(8.57f, 3.71f, 14.17f, 12.11f, 14.17f, 21.65f)
                curveToRelative(0f, 17.67f, -14.34f, 32f, -32f, 32f)
                curveToRelative(-4.14f, 0f, -8.17f, -0.79f, -11.84f, -2.3f)
                curveToRelative(-46.84f, -20.32f, -97.63f, -30.96f, -148.98f, -30.96f)
                curveToRelative(-17.67f, 0f, -32f, -14.33f, -32f, -32f)
                reflectiveCurveToRelative(14.33f, -32f, 32f, -32f)
                close()
                moveTo(392.53f, 70.4f)
                curveToRelative(3.97f, -0.85f, 8.07f, -1.28f, 8.92f, -1.28f)
                curveToRelative(14.17f, 0f, 26.45f, 9.21f, 30.67f, 22.01f)
                curveToRelative(1.65f, 4.96f, -0.79f, 35.58f, -13.6f, 40.72f)
                curveToRelative(-42.48f, 14.68f, -82.34f, 36.85f, -118.79f, 66.06f)
                curveToRelative(-6.24f, 5.01f, -14.0f, 7.79f, -22.01f, 7.79f)
                curveToRelative(-10.11f, 0f, -19.7f, -4.79f, -25.87f, -12.97f)
                curveToRelative(-10.83f, -14.36f, -7.73f, -34.83f, 6.63f, -45.66f)
                curveToRelative(42.4f, -33.95f, 88.82f, -59.84f, 134.05f, -76.67f)
                close()
                moveTo(512f, 970.67f)
                curveToRelative(-253.27f, 0f, -458.67f, -205.4f, -458.67f, -458.67f)
                reflectiveCurveTo(258.73f, 53.33f, 512f, 53.33f)
                reflectiveCurveToRelative(458.67f, 205.4f, 458.67f, 458.67f)
                reflectiveCurveTo(765.27f, 970.67f, 512f, 970.67f)
                close()
            }
        }.build()
    }

    val SuccessCircle: ImageVector by lazy {
        ImageVector.Builder(
            name = "SuccessCircle",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(533.33f, 85.33f)
                curveToRelative(-247.43f, 0f, -448f, 200.57f, -448f, 448f)
                reflectiveCurveToRelative(200.57f, 448f, 448f, 448f)
                reflectiveCurveToRelative(448f, -200.57f, 448f, -448f)
                reflectiveCurveToRelative(-200.57f, -448f, -448f, -448f)
                close()
                moveTo(761.75f, 420.42f)
                lineToRelative(-277.33f, 277.33f)
                curveToRelative(-8.33f, 8.33f, -21.84f, 8.33f, -30.17f, 0f)
                lineToRelative(-149.33f, -149.33f)
                curveToRelative(-8.33f, -8.33f, -8.33f, -21.84f, 0f, -30.17f)
                curveToRelative(8.33f, -8.33f, 21.84f, -8.33f, 30.17f, 0f)
                lineTo(469.33f, 652.5f)
                lineToRelative(262.25f, -262.25f)
                curveToRelative(8.33f, -8.33f, 21.84f, -8.33f, 30.17f, 0f)
                curveToRelative(8.33f, 8.33f, 8.33f, 21.84f, 0f, 30.17f)
                close()
            }
        }.build()
    }

    val Send: ImageVector by lazy {
        ImageVector.Builder(
            name = "Send",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(512f, 0f)
                curveToRelative(282.75f, 0f, 512f, 229.25f, 512f, 512f)
                reflectiveCurveToRelative(-229.25f, 512f, -512f, 512f)
                reflectiveCurveTo(0f, 794.75f, 0f, 512f)
                reflectiveCurveTo(229.25f, 0f, 512f, 0f)
                close()
                moveTo(480.73f, 292.91f)
                lineTo(316.16f, 457.47f)
                curveToRelative(-18.15f, 18.15f, -4.72f, 49.12f, 21.31f, 49.12f)
                curveToRelative(7.94f, 0f, 15.88f, -3.03f, 21.93f, -9.08f)
                lineToRelative(87.47f, -87.47f)
                lineToRelative(0f, 336.17f)
                curveToRelative(0f, 25.68f, 20.82f, 46.51f, 46.51f, 46.51f)
                curveToRelative(25.68f, 0f, 46.55f, -20.82f, 46.55f, -46.51f)
                verticalLineToRelative(-331.52f)
                lineToRelative(82.77f, 82.77f)
                curveToRelative(18.15f, 18.15f, 47.68f, 18.15f, 65.83f, 0f)
                curveToRelative(18.15f, -18.22f, 18.15f, -47.61f, 0f, -65.79f)
                lineTo(546.56f, 292.91f)
                curveToRelative(-18.15f, -18.15f, -47.68f, -18.15f, -65.83f, 0f)
                close()
            }
        }.build()
    }

    val StopCircle: ImageVector by lazy {
        ImageVector.Builder(
            name = "StopCircle",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(512f, 42.67f)
                curveTo(252.79f, 42.67f, 42.67f, 252.79f, 42.67f, 512f)
                reflectiveCurveToRelative(210.13f, 469.33f, 469.33f, 469.33f)
                reflectiveCurveToRelative(469.33f, -210.13f, 469.33f, -469.33f)
                reflectiveCurveTo(771.21f, 42.67f, 512f, 42.67f)
                close()
                moveTo(725.33f, 688f)
                curveToRelative(0f, 20.62f, -16.71f, 37.33f, -37.33f, 37.33f)
                horizontalLineTo(336f)
                curveToRelative(-20.62f, 0f, -37.33f, -16.71f, -37.33f, -37.33f)
                verticalLineTo(336f)
                curveToRelative(0f, -20.62f, 16.71f, -37.33f, 37.33f, -37.33f)
                horizontalLineToRelative(352f)
                curveToRelative(20.62f, 0f, 37.33f, 16.71f, 37.33f, 37.33f)
                close()
            }
        }.build()
    }

    /** Upward-arrow only (no outer circle). Use inside a CircleShape Surface for SendButton. */
    val SendAction: ImageVector by lazy {
        ImageVector.Builder(
            name = "SendAction",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(480.73f, 292.91f)
                lineTo(316.16f, 457.47f)
                curveToRelative(-18.15f, 18.15f, -4.72f, 49.12f, 21.31f, 49.12f)
                curveToRelative(7.94f, 0f, 15.88f, -3.03f, 21.93f, -9.08f)
                lineToRelative(87.47f, -87.47f)
                lineToRelative(0f, 336.17f)
                curveToRelative(0f, 25.68f, 20.82f, 46.51f, 46.51f, 46.51f)
                curveToRelative(25.68f, 0f, 46.55f, -20.82f, 46.55f, -46.51f)
                verticalLineToRelative(-331.52f)
                lineToRelative(82.77f, 82.77f)
                curveToRelative(18.15f, 18.15f, 47.68f, 18.15f, 65.83f, 0f)
                curveToRelative(18.15f, -18.22f, 18.15f, -47.61f, 0f, -65.79f)
                lineTo(546.56f, 292.91f)
                curveToRelative(-18.15f, -18.15f, -47.68f, -18.15f, -65.83f, 0f)
                close()
            }
        }.build()
    }

    /** Rounded square only (no outer circle). Use inside a CircleShape Surface for SendButton stop state. */
    val StopAction: ImageVector by lazy {
        ImageVector.Builder(
            name = "StopAction",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                moveTo(725.33f, 688f)
                curveToRelative(0f, 20.62f, -16.71f, 37.33f, -37.33f, 37.33f)
                horizontalLineTo(336f)
                curveToRelative(-20.62f, 0f, -37.33f, -16.71f, -37.33f, -37.33f)
                verticalLineTo(336f)
                curveToRelative(0f, -20.62f, 16.71f, -37.33f, 37.33f, -37.33f)
                horizontalLineToRelative(352f)
                curveToRelative(20.62f, 0f, 37.33f, 16.71f, 37.33f, 37.33f)
                close()
            }
        }.build()
    }

    val Think: ImageVector by lazy {
        ImageVector.Builder(
            name = "Think",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 1024f,
            viewportHeight = 1024f,
        ).apply {
            path(fill = SolidColor(Color.Black)) {
                // Main brain outline (simplified from the detailed path data)
                moveTo(780.83f, 178.74f)
                curveToRelative(17.17f, 23.17f, 25.22f, 51.87f, 22.69f, 80.6f)
                curveToRelative(-0.22f, 1.46f, -0.38f, 2.91f, -0.65f, 4.37f)
                curveToRelative(30.35f, -1.0f, 56.87f, 7.46f, 79.01f, 23.69f)
                curveToRelative(55.97f, 39.83f, 77.45f, 116.47f, 60.23f, 181.14f)
                curveToRelative(-8.8f, 33.04f, -22.99f, 50.34f, -41.07f, 66.37f)
                curveToRelative(2.8f, 2.59f, 5.55f, 5.39f, 8.14f, 8.3f)
                curveToRelative(20.13f, 22.54f, 31.26f, 54.8f, 31.26f, 87.63f)
                curveToRelative(-2.19f, 34.51f, -14.09f, 67.42f, -36.46f, 96.39f)
                curveToRelative(-20.64f, 28.05f, -48.1f, 54.57f, -83.19f, 63.08f)
                curveToRelative(-5.63f, 1.35f, -11.34f, 2.16f, -17.11f, 2.37f)
                curveToRelative(0.43f, 12.77f, -1.72f, 25.49f, -6.31f, 37.43f)
                curveToRelative(-13.71f, 35.53f, -37.22f, 59.76f, -66.64f, 74.37f)
                curveToRelative(-23.67f, 11.76f, -49.94f, 18.67f, -77.45f, 20.21f)
                curveToRelative(-26.34f, 1.57f, -54.68f, -2.64f, -81.46f, -14.93f)
                curveToRelative(-18.74f, -8.6f, -35.34f, -27.05f, -46.38f, -68.02f)
                verticalLineToRelative(-46.67f)
                lineToRelative(-0.11f, -125.04f)
                curveToRelative(-0.13f, -163.57f, -0.32f, -327.14f, -0.54f, -490.77f)
                verticalLineTo(167.61f)
                curveToRelative(0f, -0.7f, 0f, -1.35f, 0.08f, -2.05f)
                curveToRelative(1.62f, -33.63f, 27.49f, -56.48f, 57.72f, -68.1f)
                curveToRelative(36.38f, -14.01f, 78.07f, -5.36f, 112.26f, 10.13f)
                curveToRelative(35.76f, 16.24f, 65.37f, 40.81f, 85.96f, 71.17f)
                close()
            }
            path(fill = SolidColor(Color.Black)) {
                // Left brain half (simplified)
                moveTo(94.96f, 340.88f)
                curveToRelative(14.65f, -28.25f, 35.85f, -48.93f, 61.44f, -62.52f)
                curveToRelative(19.33f, -10.26f, 40.92f, -14.55f, 64.03f, -14.55f)
                curveToRelative(1.51f, -28.32f, 8.94f, -57.42f, 21.07f, -83.67f)
                curveToRelative(20.78f, -25.65f, 49.44f, -51.24f, 84.78f, -71.55f)
                curveToRelative(33.31f, -15.67f, 73.67f, -20.66f, 112.94f, -11.72f)
                curveToRelative(30.99f, 10.59f, 57.53f, 35.0f, 59.18f, 68.69f)
                curveToRelative(0.05f, 0.67f, 0.08f, 1.4f, 0.08f, 2.1f)
                lineToRelative(-0.65f, 670.99f)
                curveToRelative(-7.8f, 34.41f, -22.46f, 55.88f, -41.82f, 68.82f)
                curveToRelative(-22.61f, 15.1f, -50.4f, 18.5f, -80.22f, 17.52f)
                curveToRelative(-28.12f, -0.93f, -55.48f, -6.75f, -77.85f, -17.54f)
                curveToRelative(-29.34f, -14.17f, -51.65f, -36.83f, -67.05f, -65.72f)
                curveToRelative(-5.51f, -14.06f, -9.01f, -29.93f, -11.45f, -48.94f)
                curveToRelative(-7.3f, -0.44f, -16.14f, -1.59f, -24.52f, -4.53f)
                curveToRelative(-35.6f, -13.15f, -62.66f, -36.81f, -81.6f, -69.34f)
                curveToRelative(-18.61f, -31.97f, -30.48f, -62.01f, -30.48f, -96.09f)
                curveToRelative(3.32f, -30.69f, 14.69f, -58.68f, 36.22f, -84.88f)
                curveToRelative(1.02f, -1.0f, 2.07f, -1.97f, 3.15f, -2.94f)
                curveToRelative(-2.28f, -1.88f, -4.46f, -3.85f, -6.52f, -5.93f)
                curveToRelative(-24.56f, -24.1f, -37.2f, -57.18f, -40.64f, -81.64f)
                curveToRelative(-3.61f, -35.03f, 2.8f, -70.36f, 18.54f, -101.86f)
                close()
            }
            // Eyes
            path(fill = SolidColor(Color.Black)) {
                moveTo(264.3f, 407.79f)
                curveToRelative(4.97f, -10.55f, 17.11f, -17.43f, 32.28f, -17.95f)
                curveToRelative(48.8f, 13.93f, 81.3f, 72.19f, 81.3f, 138.24f)
                curveToRelative(0f, 62.41f, -28.97f, 118.03f, -73.67f, 135.71f)
                curveToRelative(-1.62f, 0.65f, -3.23f, 1.21f, -4.9f, 1.75f)
                curveToRelative(-12.8f, 4.27f, -26.66f, -2.05f, -18.22f, -48.88f)
                lineToRelative(3.91f, -1.43f)
                curveToRelative(22.18f, -8.78f, 40.69f, -44.27f, 40.69f, -87.12f)
                curveToRelative(0f, -43.57f, -19.05f, -79.12f, -41.23f, -87.34f)
                lineToRelative(-2.21f, -0.73f)
                curveToRelative(-10.55f, -4.97f, -17.43f, -17.11f, -17.95f, -32.28f)
                close()
            }
            path(fill = SolidColor(Color.Black)) {
                moveTo(745.53f, 407.79f)
                curveToRelative(-4.97f, -10.55f, -17.11f, -17.43f, -32.28f, -17.95f)
                curveToRelative(-48.83f, 13.93f, -81.33f, 72.19f, -81.33f, 138.24f)
                curveToRelative(0f, 62.41f, 29.0f, 118.03f, 73.67f, 135.71f)
                curveToRelative(1.62f, 0.65f, 3.26f, 1.24f, 4.9f, 1.75f)
                curveToRelative(12.8f, 4.27f, 26.66f, -2.05f, 18.24f, -48.88f)
                lineToRelative(-3.93f, -1.43f)
                curveToRelative(-22.18f, -8.78f, -40.66f, -44.27f, -40.66f, -87.12f)
                curveToRelative(0f, -43.57f, 19.05f, -79.12f, 41.23f, -87.34f)
                lineTo(727.58f, 440.05f)
                curveToRelative(10.55f, -4.97f, 17.43f, -17.11f, 17.95f, -32.28f)
                close()
            }
        }.build()
    }
}
