package com.example.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

import androidx.compose.ui.graphics.Color

private val DarkColorScheme = darkColorScheme(
    primary = MinimalFabBg,              // Pastel lavender accent
    secondary = MinimalAccent,           // Deep regal accent
    tertiary = MinimalAccentLight,       // Soft violet hover
    background = Color(0xFF121214),      // Matte dark background
    surface = Color(0xFF1E1E22),         // Dark minimal card surfaces
    onPrimary = Color(0xFF1C1B1F),
    onSecondary = Color.White,
    onBackground = Color(0xFFE2E8F0),    // Slate/chalk white for clean contrast
    onSurface = Color(0xFFE2E8F0),
    surfaceVariant = Color(0xFF26262B),  // Muted grey-black separator
    onSurfaceVariant = Color(0xFFE2E8F0),
    outline = Color(0xFF94A3B8),
    error = MinimalError
)

private val LightColorScheme = lightColorScheme(
    primary = MinimalAccent,             // Deep purple focal points
    secondary = MinimalFabBg,            // Soft lavender selection details
    tertiary = MinimalAccentLight,       // Synced state background
    background = MinimalBg,              // Cozy background: #FDF7FF
    surface = MinimalSurface,            // Pure white cards: #FFFFFF
    onPrimary = Color.White,
    onSecondary = MinimalAccentText,
    onBackground = MinimalTextPrimary,   // Crisp charcoal text: #1C1B1F
    onSurface = MinimalTextPrimary,
    surfaceVariant = MinimalSurfaceVariant, // #F3F0F5
    onSurfaceVariant = MinimalTextPrimary,
    outline = MinimalTextMuted,          // #49454F
    error = MinimalError
)

@Composable
fun MyApplicationTheme(
  darkTheme: Boolean = isSystemInDarkTheme(),
  // Dynamic color is available on Android 12+
  dynamicColor: Boolean = true,
  content: @Composable () -> Unit,
) {
  val colorScheme =
    when {
      dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
        val context = LocalContext.current
        if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
      }

      darkTheme -> DarkColorScheme
      else -> LightColorScheme
    }

  MaterialTheme(colorScheme = colorScheme, typography = Typography, content = content)
}
