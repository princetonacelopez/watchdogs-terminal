// =============================================================================
// Watch Dogs ctOS 2.0 GLSL Post-Processing Shader for Ghostty
// Location: ~/.config/ghostty/shaders/ctos-hud.glsl
// Effects:
//   1. Subtle tactical horizontal CRT scanlines (non-intrusive for coding)
//   2. Edge-only RGB chromatic aberration (keep center text razor-sharp)
//   3. Subtle periodic ctOS telemetry refresh line sweep
//   4. Tactical dark corner vignette + cyan phosphor tint
// =============================================================================

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord.xy / iResolution.xy;
    vec2 centered = uv - 0.5;
    float distFromEdge = dot(centered, centered);

    // 1. Edge-weighted chromatic aberration (0 in center for readable code, subtle at edges)
    float aberration = distFromEdge * 0.0025;
    float r = texture(iChannel0, vec2(uv.x + aberration, uv.y)).r;
    float g = texture(iChannel0, uv).g;
    float b = texture(iChannel0, vec2(uv.x - aberration, uv.y)).b;
    vec3 col = vec3(r, g, b);

    // 2. Crisp fine scanlines
    float scanline = sin(fragCoord.y * 3.14159265) * 0.035;
    col -= scanline;

    // 3. Slow vertical ctOS refresh bar sweep every ~8 seconds
    float sweepPos = fract(iTime * 0.12);
    float sweepBand = smoothstep(0.03, 0.0, abs(uv.y - sweepPos));
    col += vec3(0.0, 0.94, 1.0) * sweepBand * 0.025;

    // 4. Subtle corner vignette
    float vignette = 1.0 - distFromEdge * 0.45;
    col *= clamp(vignette, 0.75, 1.0);

    fragColor = vec4(col, 1.0);
}
