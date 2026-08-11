import{r as e}from"./rolldown-runtime-DAXXjFlN.js";import{Ol as t}from"./app-shell-DegOpAUD.js";import{zd as n}from"./feature-editing-core-BrxPONhr.js";var r=`
${n}

const PI: f32 = 3.14159265359;
const TAU: f32 = 6.28318530718;

fn hash(p: vec2f) -> f32 {
  let p2 = vec2f(dot(p, vec2f(127.1, 311.7)), dot(p, vec2f(269.5, 183.3)));
  return fract(sin(dot(p2, vec2f(12.9898, 78.233))) * 43758.5453);
}

fn noise2d(p: vec2f) -> f32 {
  let i = floor(p);
  let f = fract(p);
  let u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash(i + vec2f(0.0, 0.0)), hash(i + vec2f(1.0, 0.0)), u.x),
    mix(hash(i + vec2f(0.0, 1.0)), hash(i + vec2f(1.0, 1.0)), u.x),
    u.y
  );
}

fn fbm(p: vec2f) -> f32 {
  var value = 0.0;
  var amplitude = 0.5;
  var pos = p;
  for (var i = 0; i < 5; i++) {
    value += amplitude * noise2d(pos);
    pos *= 2.0;
    amplitude *= 0.5;
  }
  return value;
}
`,i=`
fn scaleUv(uv: vec2f, scale: f32) -> vec2f {
  let safeScale = max(scale, 0.001);
  return ((uv - vec2f(0.5, 0.5)) / safeScale) + vec2f(0.5, 0.5);
}
`,a={id:`dissolve`,name:`Cross Dissolve`,category:`dissolve`,hasDirection:!1,entryPoint:`dissolveFragment`,uniformSize:16,shader:`
struct DissolveParams {
  progress: f32,
  width: f32,
  height: f32,
  _pad: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: DissolveParams;

@fragment
fn dissolveFragment(input: VertexOutput) -> @location(0) vec4f {
  let left = textureSample(leftTex, texSampler, input.uv);
  let right = textureSample(rightTex, texSampler, input.uv);
  let t = 0.5 - 0.5 * cos(clamp(params.progress, 0.0, 1.0) * PI);
  return mix(left, right, t);
}`,packUniforms:(e,t,n)=>new Float32Array([e,t,n,0])},o=`
@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
`,s=`
fn sampleSoft(tex: texture_2d<f32>, uv: vec2f, radius: vec2f) -> vec4f {
  let center = textureSample(tex, texSampler, uv);
  let a = textureSample(tex, texSampler, clamp(uv + vec2f(radius.x, 0.0), vec2f(0.0), vec2f(1.0)));
  let b = textureSample(tex, texSampler, clamp(uv - vec2f(radius.x, 0.0), vec2f(0.0), vec2f(1.0)));
  let c = textureSample(tex, texSampler, clamp(uv + vec2f(0.0, radius.y), vec2f(0.0), vec2f(1.0)));
  let d = textureSample(tex, texSampler, clamp(uv - vec2f(0.0, radius.y), vec2f(0.0), vec2f(1.0)));
  return center * 0.36 + (a + b + c + d) * 0.16;
}
`,c={id:`additiveDissolve`,name:`Additive Dissolve`,category:`dissolve`,hasDirection:!1,entryPoint:`additiveDissolveFragment`,uniformSize:16,shader:`
struct AdditiveDissolveParams {
  progress: f32,
  width: f32,
  height: f32,
  _pad: f32,
};

${o}
@group(0) @binding(3) var<uniform> params: AdditiveDissolveParams;

@fragment
fn additiveDissolveFragment(input: VertexOutput) -> @location(0) vec4f {
  let p = clamp(params.progress, 0.0, 1.0);
  let left = textureSample(leftTex, texSampler, input.uv);
  let right = textureSample(rightTex, texSampler, input.uv);
  let base = left.rgb * (1.0 - p) + right.rgb * p;
  let flash = (left.rgb + right.rgb) * sin(p * PI) * 0.22;
  return vec4f(clamp(base + flash, vec3f(0.0), vec3f(1.0)), mix(left.a, right.a, p));
}`,packUniforms:(e,t,n)=>new Float32Array([e,t,n,0])},l={id:`blurDissolve`,name:`Blur Dissolve`,category:`dissolve`,hasDirection:!1,entryPoint:`blurDissolveFragment`,uniformSize:16,shader:`
struct BlurDissolveParams {
  progress: f32,
  width: f32,
  height: f32,
  strength: f32,
};

${o}
@group(0) @binding(3) var<uniform> params: BlurDissolveParams;
${s}

@fragment
fn blurDissolveFragment(input: VertexOutput) -> @location(0) vec4f {
  let p = clamp(params.progress, 0.0, 1.0);
  let envelope = sin(p * PI);
  let radius = vec2f(1.0 / params.width, 1.0 / params.height) * params.strength * envelope;
  let left = sampleSoft(leftTex, input.uv, radius);
  let right = sampleSoft(rightTex, input.uv, radius);
  let t = 0.5 - 0.5 * cos(p * PI);
  return mix(left, right, t);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.strength??9;return new Float32Array([e,t,n,a])}},u={id:`dipToColorDissolve`,name:`Dip To Color Dissolve`,category:`dissolve`,hasDirection:!1,entryPoint:`dipToColorDissolveFragment`,uniformSize:32,shader:`
struct DipToColorDissolveParams {
  progress: f32,
  width: f32,
  height: f32,
  colorR: f32,
  colorG: f32,
  colorB: f32,
  _pad1: f32,
  _pad2: f32,
};

${o}
@group(0) @binding(3) var<uniform> params: DipToColorDissolveParams;

@fragment
fn dipToColorDissolveFragment(input: VertexOutput) -> @location(0) vec4f {
  let p = clamp(params.progress, 0.0, 1.0);
  let left = textureSample(leftTex, texSampler, input.uv);
  let right = textureSample(rightTex, texSampler, input.uv);
  let color = vec4f(params.colorR, params.colorG, params.colorB, 1.0);
  let firstHalf = mix(left, color, smoothstep(0.0, 0.5, p));
  let secondHalf = mix(color, right, smoothstep(0.5, 1.0, p));
  return select(secondHalf, firstHalf, p < 0.5);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.color,o=Array.isArray(a)?a:[0,0,0];return new Float32Array([e,t,n,o[0]??0,o[1]??0,o[2]??0,0,0])}},d={id:`nonAdditiveDissolve`,name:`Non-Additive Dissolve`,category:`dissolve`,hasDirection:!1,entryPoint:`nonAdditiveDissolveFragment`,uniformSize:16,shader:`
struct NonAdditiveDissolveParams {
  progress: f32,
  width: f32,
  height: f32,
  _pad: f32,
};

${o}
@group(0) @binding(3) var<uniform> params: NonAdditiveDissolveParams;

@fragment
fn nonAdditiveDissolveFragment(input: VertexOutput) -> @location(0) vec4f {
  let p = clamp(params.progress, 0.0, 1.0);
  let left = textureSample(leftTex, texSampler, input.uv);
  let right = textureSample(rightTex, texSampler, input.uv);
  let neutral = mix(left.rgb, right.rgb, p);
  let luma = dot(neutral, vec3f(0.2126, 0.7152, 0.0722));
  let guarded = mix(neutral, min(neutral, vec3f(luma + 0.18)), sin(p * PI) * 0.18);
  return vec4f(clamp(guarded, vec3f(0.0), vec3f(1.0)), mix(left.a, right.a, p));
}`,packUniforms:(e,t,n)=>new Float32Array([e,t,n,0])},f={id:`smoothCut`,name:`Smooth Cut`,category:`dissolve`,hasDirection:!1,entryPoint:`smoothCutFragment`,uniformSize:16,shader:`
struct SmoothCutParams {
  progress: f32,
  width: f32,
  height: f32,
  strength: f32,
};

${o}
@group(0) @binding(3) var<uniform> params: SmoothCutParams;
${s}

fn smoothCutWarp(uv: vec2f, p: f32, envelope: f32, strength: f32) -> vec2f {
  let low = fbm(uv * vec2f(2.4, 1.8) + vec2f(p * 1.15, -p * 0.8));
  let mid = fbm(uv * vec2f(6.2, 4.8) + vec2f(-p * 1.65, p * 1.25));
  let horizontalBands =
    sin((uv.x * 4.6 + low * 1.8 + p * 1.25) * TAU) * 0.62 +
    sin((uv.x * 8.2 + uv.y * 0.22 + mid * 1.1 - p * 0.9) * TAU) * 0.28 +
    (low - 0.5) * 0.48 +
    (mid - 0.5) * 0.22;
  let horizontalWarp = horizontalBands;
  let verticalWarp = (mid - 0.5) * 0.14;
  let edgeFade = smoothstep(0.03, 0.18, uv.x) * smoothstep(0.97, 0.82, uv.x)
    * smoothstep(0.03, 0.18, uv.y) * smoothstep(0.97, 0.82, uv.y);
  return vec2f(horizontalWarp, verticalWarp) * envelope * strength * 0.052 * edgeFade;
}

@fragment
fn smoothCutFragment(input: VertexOutput) -> @location(0) vec4f {
  let p = clamp(params.progress, 0.0, 1.0);
  let strength = clamp(params.strength, 0.0, 2.0);
  let envelope = sin(p * PI);
  let warp = smoothCutWarp(input.uv, p, envelope, strength);
  let drift = vec2f((p - 0.5) * 0.018 * envelope * strength, 0.0);
  let radius = vec2f(1.0 / params.width, 1.0 / params.height) * envelope * strength * 2.4;
  let leftWarped = sampleSoft(leftTex, clamp(input.uv + warp - drift, vec2f(0.0), vec2f(1.0)), radius);
  let rightWarped = sampleSoft(rightTex, clamp(input.uv - warp + drift, vec2f(0.0), vec2f(1.0)), radius);
  let leftClean = textureSample(leftTex, texSampler, input.uv);
  let rightClean = textureSample(rightTex, texSampler, input.uv);
  let warpMix = smoothstep(0.12, 0.85, envelope);
  let left = mix(leftClean, leftWarped, warpMix);
  let right = mix(rightClean, rightWarped, warpMix);
  let blendWidth = mix(0.18, 0.36, strength);
  let t = smoothstep(0.5 - blendWidth, 0.5 + blendWidth, p);
  return mix(left, right, t);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.strength??.9;return new Float32Array([e,t,n,a])}},p={id:`sparkles`,name:`Sparkles`,category:`custom`,hasDirection:!1,entryPoint:`sparklesFragment`,uniformSize:32,shader:`
struct SparklesParams {
  progress: f32,
  width: f32,
  height: f32,
  sparkleScale: f32,
  intensity: f32,
  density: f32,
  glow: f32,
  _pad: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: SparklesParams;

fn rotateVec2(v: vec2f, angle: f32) -> vec2f {
  let c = cos(angle);
  let s = sin(angle);
  return vec2f(
    (v.x * c) - (v.y * s),
    (v.x * s) + (v.y * c)
  );
}

fn sparkleShape(local: vec2f, size: f32) -> f32 {
  let absLocal = abs(local);
  let core = smoothstep(size * 0.34, 0.0, length(local));
  let horizontal = smoothstep(size * 0.14, 0.0, absLocal.y)
    * smoothstep(size, 0.0, absLocal.x);
  let vertical = smoothstep(size * 0.14, 0.0, absLocal.x)
    * smoothstep(size, 0.0, absLocal.y);
  let diagonalA = smoothstep(size * 0.22, 0.0, abs(local.x - local.y))
    * smoothstep(size * 0.9, 0.0, length(local));
  let diagonalB = smoothstep(size * 0.22, 0.0, abs(local.x + local.y))
    * smoothstep(size * 0.9, 0.0, length(local));
  return max(core, max(horizontal, max(vertical, max(diagonalA, diagonalB) * 0.7)));
}

fn sparkleLayer(
  scaledUv: vec2f,
  progress: f32,
  density: f32,
  sizeBase: f32,
  sizeVariance: f32,
  motionScale: f32,
  threshold: f32,
  phase: f32,
) -> vec4f {
  let cellUv = scaledUv * density;
  let cell = floor(cellUv);
  let local = fract(cellUv) - vec2f(0.5, 0.5);
  let seed = hash(cell + vec2f(phase * 1.37, phase * 2.11));
  let centerSeed = vec2f(
    hash(cell + vec2f(phase + 1.7, phase + 6.2)),
    hash(cell + vec2f(phase + 8.4, phase + 3.1))
  ) - vec2f(0.5, 0.5);
  let sizeSeed = hash(cell + vec2f(phase + 2.4, phase + 9.7));
  let orbitSeed = hash(cell + vec2f(phase + 4.6, phase + 11.2));
  let ignitePoint = clamp(
    0.04
      + (seed * 0.72)
      + (noise2d((cell * 0.17) + vec2f(phase * 0.31, phase * 0.67)) * 0.16),
    0.04,
    0.94
  );
  let igniteDuration = 0.14 + (sizeSeed * 0.18);
  let igniteProgress = clamp((progress - ignitePoint) / igniteDuration, 0.0, 1.0);
  let igniteIn = smoothstep(0.0, 0.16, igniteProgress);
  let igniteOut = 1.0 - smoothstep(0.3, 0.95, igniteProgress);
  let pulse = igniteIn * igniteOut;
  let afterglow = smoothstep(0.06, 0.72, igniteProgress);

  let directionAngle = seed * TAU;
  let direction = vec2f(cos(directionAngle), sin(directionAngle));
  let motionEnvelope = pulse * (0.6 + (0.4 * sin(progress * PI)));
  let drift = direction
    * motionScale
    * (0.42 + (sizeSeed * 1.45))
    * motionEnvelope;
  let orbit = rotateVec2(
    vec2f(0.0, 1.0),
    directionAngle + (igniteProgress * (1.5 + (orbitSeed * 2.6)) * PI)
  ) * motionScale * 0.62 * (0.28 + orbitSeed) * motionEnvelope;

  let center = (centerSeed * 0.72) + drift + orbit;
  let rotation = (seed * TAU) + (igniteProgress * (1.2 + (sizeSeed * 3.1)) * PI);
  let size = sizeBase + (sizeSeed * sizeVariance);
  let twinkle = 0.35 + (0.65 * ((sin((igniteProgress * (2.8 + (sizeSeed * 4.5)) + seed) * TAU) + 1.0) * 0.5));
  let activation = smoothstep(threshold, 1.0, seed);

  let starLocal = rotateVec2(local - center, rotation);
  let main = sparkleShape(starLocal, size) * activation * twinkle * pulse;

  let trailCenter = center - (
    direction
    * motionScale
    * (0.6 + sizeSeed)
    * (0.25 + (pulse * 0.95))
  );
  let trailLocal = rotateVec2(local - trailCenter, rotation - 0.4);
  let trailShape = vec2f(trailLocal.x * 1.7, trailLocal.y * 0.58);
  let trail = sparkleShape(trailShape, size * 0.72)
    * activation
    * twinkle
    * pulse
    * (0.42 + (sizeSeed * 0.28));

  let dustNoise = noise2d((cell * 0.85) + vec2f((igniteProgress * 4.2) + phase, phase * 0.37));
  let dust = smoothstep(0.62, 1.0, dustNoise)
    * afterglow
    * activation
    * (0.16 + (sizeSeed * 0.34));
  let reveal = clamp(
    (main * 0.72)
      + (trail * 0.34)
      + (afterglow * activation * 0.24)
      + (dust * 0.12),
    0.0,
    1.0
  );
  let glow = max(main, trail * 0.88) * (0.65 + (sizeSeed * 0.75)) + (dust * 0.3);

  return vec4f(main, reveal, glow, seed);
}

@fragment
fn sparklesFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = params.progress;
  let aspect = params.width / max(params.height, 1.0);
  let scaledUv = vec2f(uv.x * aspect, uv.y);

  let left = textureSample(leftTex, texSampler, uv);
  let right = textureSample(rightTex, texSampler, uv);

  let coarseLayer = sparkleLayer(
    scaledUv,
    p,
    5.5 + (params.density * 5.0),
    0.15 * params.sparkleScale,
    0.28 * params.sparkleScale,
    0.18,
    0.58,
    3.7
  );
  let microLayer = sparkleLayer(
    scaledUv,
    p,
    10.0 + (params.density * 9.0),
    0.06 * params.sparkleScale,
    0.14 * params.sparkleScale,
    0.09,
    0.7,
    11.4
  );

  let heroMix = step(microLayer.z, coarseLayer.z);
  let heroSeed = mix(microLayer.w, coarseLayer.w, heroMix);
  let sparkleCore = max(coarseLayer.x, microLayer.x * 0.78);
  let sparkleField = max(coarseLayer.y, microLayer.y * 0.86);
  let glowField = max(coarseLayer.z, microLayer.z * 0.74);
  let macroNoise = fbm((scaledUv * (2.6 + (params.density * 0.9))) + vec2f(0.0, p * 0.7));
  let dustNoise = noise2d(
    (scaledUv * (13.0 + (params.density * 7.0)))
      + vec2f((p * 5.2) + (heroSeed * 3.1), heroSeed * 7.4)
  );
  let dissolveCurve = smoothstep(0.03, 0.97, p);
  let sparkleWindow = smoothstep(0.02, 0.28, p) * (1.0 - smoothstep(0.8, 1.0, p));
  let dustField = smoothstep(0.58, 1.0, dustNoise)
    * (0.12 + (sparkleField * 0.88))
    * sin(p * PI);
  let thresholdMap = clamp(
    (macroNoise * 0.58)
      + (dustNoise * 0.14)
      + ((1.0 - sparkleField) * 0.18)
      + ((1.0 - glowField) * 0.08),
    0.0,
    1.0
  );
  let dissolveProgress = clamp(
    (dissolveCurve * 1.08) - 0.04
      + (sparkleField * (0.28 + (params.intensity * 0.12)) * sparkleWindow)
      + (glowField * (0.1 + (params.glow * 0.08)))
      + (dustField * 0.12),
    0.0,
    1.0
  );
  let edge = 0.075 + (0.018 * params.sparkleScale);
  let leftPresence = 1.0 - smoothstep(thresholdMap - edge, thresholdMap + edge, dissolveProgress);
  let rightPresence = 1.0 - leftPresence;

  var color = mix(right, left, leftPresence);
  let dissolveEdge = clamp(leftPresence * rightPresence * 4.0, 0.0, 1.0);
  let sparkleEnvelope = sin(p * PI);
  let edgeGlow = dissolveEdge
    * glowField
    * params.intensity
    * params.glow
    * (0.5 + (sparkleEnvelope * 0.4));
  let sparkleFlash = sparkleCore
    * (0.38 + (params.intensity * 0.52))
    * (0.62 + (sparkleEnvelope * 0.38));
  let glowColor = mix(vec3f(1.0, 0.97, 0.88), vec3f(1.0, 0.82, 0.56), heroSeed);
  let warmVeil = glowColor * glowField * params.glow * (0.06 + (rightPresence * 0.12));
  let incomingLift = right.rgb * (glowField * rightPresence * 0.05 * params.glow);
  let lifted = color.rgb
    + warmVeil
    + incomingLift
    + (glowColor * edgeGlow * 0.95)
    + (glowColor * sparkleFlash * 0.72);
  let compressed = 1.0 - exp(-lifted * (1.0 + (edgeGlow * 0.45)));

  return vec4f(
    clamp(mix(lifted, compressed, 0.46), vec3f(0.0), vec3f(1.0)),
    color.a
  );
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.sparkleScale??1,o=i?.intensity??1,s=i?.density??1,c=i?.glow??1;return new Float32Array([e,t,n,a,o,s,c,0])}},m={id:`glitch`,name:`Glitch`,category:`custom`,hasDirection:!1,entryPoint:`glitchFragment`,uniformSize:32,shader:`
struct GlitchParams {
  progress: f32,
  width: f32,
  height: f32,
  intensity: f32,
  blockSize: f32,
  rgbSplit: f32,
  _pad1: f32,
  _pad2: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: GlitchParams;

@fragment
fn glitchFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = params.progress;

  // Intensity envelope — ramps up, holds, eases out
  let envelope = smoothstep(0.0, 0.2, p) * (1.0 - smoothstep(0.8, 1.0, p));
  let strength = envelope * params.intensity;

  // --- Block displacement (two scales) ---
  let bigBlockH = params.blockSize * 2.0 / params.height;
  let bigBlockY = floor(uv.y / bigBlockH);
  let bigSeed = hash(vec2f(bigBlockY * 17.3, floor(p * 8.0)));
  let bigActive = step(0.55 - strength * 0.35, bigSeed);
  let bigShift = (hash(vec2f(bigBlockY * 31.7, floor(p * 10.0))) - 0.5)
                 * strength * 0.18 * bigActive;

  let sliceH = max(2.0, params.blockSize * 0.3) / params.height;
  let sliceY = floor(uv.y / sliceH);
  let sliceSeed = hash(vec2f(sliceY * 53.1, floor(p * 12.0)));
  let sliceActive = step(0.65 - strength * 0.25, sliceSeed);
  let sliceShift = (hash(vec2f(sliceY * 71.3, floor(p * 14.0))) - 0.5)
                   * strength * 0.1 * sliceActive;

  let totalShift = bigShift + sliceShift;
  let dUv = vec2f(clamp(uv.x + totalShift, 0.0, 1.0), uv.y);

  // --- RGB split (horizontal chromatic aberration) ---
  let split = params.rgbSplit * strength * 0.015 + abs(totalShift) * 0.2;
  let uvR = vec2f(clamp(dUv.x + split, 0.0, 1.0), dUv.y);
  let uvB = vec2f(clamp(dUv.x - split, 0.0, 1.0), dUv.y);

  // --- Per-block clip switching ---
  let switchBlockH = bigBlockH * 0.7;
  let switchY = floor(uv.y / switchBlockH);
  let switchSeed = hash(vec2f(switchY * 7.3, floor(p * 6.0)));
  let threshold = switchSeed * 0.7 + 0.15;
  let useRight = smoothstep(threshold - 0.12, threshold + 0.12, p);

  // Sample both clips with chromatic aberration
  let lR = textureSample(leftTex, texSampler, uvR).r;
  let lG = textureSample(leftTex, texSampler, dUv).g;
  let lB = textureSample(leftTex, texSampler, uvB).b;
  let lA = textureSample(leftTex, texSampler, dUv).a;
  let leftColor = vec4f(lR, lG, lB, lA);

  let rR = textureSample(rightTex, texSampler, uvR).r;
  let rG = textureSample(rightTex, texSampler, dUv).g;
  let rB = textureSample(rightTex, texSampler, uvB).b;
  let rA = textureSample(rightTex, texSampler, dUv).a;
  let rightColor = vec4f(rR, rG, rB, rA);

  // Detect truly empty samples using the alpha channel; fall back to
  // luminance only when alpha is not a reliable signal.
  let leftEmpty  = leftColor.a  < 0.01;
  let rightEmpty = rightColor.a < 0.01;
  let safeLeft  = select(leftColor,  rightColor, leftEmpty  && !rightEmpty);
  let safeRight = select(rightColor, leftColor,  rightEmpty && !leftEmpty);

  var color = mix(safeLeft, safeRight, useRight);

  // --- Digital noise on glitched regions ---
  let noiseSeed = hash(vec2f(uv.x * params.width * 0.5,
                              uv.y * params.height * 0.5 + p * 1000.0));
  let noiseAmt = strength * 0.1 * max(bigActive, sliceActive);
  color = vec4f(mix(color.rgb, vec3f(noiseSeed), noiseAmt), color.a);

  // --- Subtle posterization on displaced blocks ---
  let levels = mix(256.0, 24.0, strength * bigActive * 0.4);
  color = vec4f(floor(color.rgb * levels + 0.5) / levels, color.a);

  return color;
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.intensity??1,o=i?.blockSize??30,s=i?.rgbSplit??1;return new Float32Array([e,t,n,a,o,s,0,0])}},h={id:`pixelate`,name:`Pixelate`,category:`custom`,hasDirection:!1,entryPoint:`pixelateFragment`,uniformSize:32,shader:`
struct PixelateParams {
  progress: f32,
  // Pre-computed on CPU: block size in UV space (1/width * blockPx, 1/height * blockPx)
  blockU: f32,
  blockV: f32,
  crossfade: f32,
  _pad1: f32,
  _pad2: f32,
  _pad3: f32,
  _pad4: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: PixelateParams;

@fragment
fn pixelateFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;

  // Snap UV to block grid center (block size pre-computed on CPU)
  let snappedUv = clamp(
    floor(uv / vec2f(params.blockU, params.blockV)) * vec2f(params.blockU, params.blockV)
      + vec2f(params.blockU, params.blockV) * 0.5,
    vec2f(0.0),
    vec2f(1.0)
  );

  // Sample both clips at the pixelated UV — only 2 texture reads
  let left = textureSample(leftTex, texSampler, snappedUv);
  let right = textureSample(rightTex, texSampler, snappedUv);

  return mix(left, right, params.crossfade);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.maxBlockSize??48,o=1-Math.abs(e*2-1),s=o*o,c=Math.max(1,s*a),l=c/t,u=c/n,d=Math.max(0,Math.min(1,(e-.45)/.1)),f=d*d*(3-2*d);return new Float32Array([e,l,u,f,0,0,0,0])}},g={id:`chromatic`,name:`Chromatic`,category:`custom`,hasDirection:!0,directions:[`from-left`,`from-right`,`from-top`,`from-bottom`],entryPoint:`chromaticFragment`,uniformSize:32,shader:`
struct ChromaticParams {
  progress: f32,
  width: f32,
  height: f32,
  direction: f32,
  spread: f32,
  intensity: f32,
  _pad1: f32,
  _pad2: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: ChromaticParams;

@fragment
fn chromaticFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = params.progress;

  // Intensity envelope — strongest at midpoint
  let envelope = sin(p * PI);
  let strength = envelope * params.intensity;

  // Direction vector for the aberration spread
  let dir = u32(params.direction);
  var aberrationDir: vec2f;
  if (dir == 0u) { aberrationDir = vec2f(1.0, 0.0); }
  else if (dir == 1u) { aberrationDir = vec2f(-1.0, 0.0); }
  else if (dir == 2u) { aberrationDir = vec2f(0.0, 1.0); }
  else { aberrationDir = vec2f(0.0, -1.0); }

  // RGB channel offsets — each channel shifts at different rate
  let spreadAmount = params.spread * strength * 0.02;
  let rOffset = aberrationDir * spreadAmount * 1.0;
  let gOffset = aberrationDir * spreadAmount * 0.0;  // Green stays centered
  let bOffset = aberrationDir * spreadAmount * -1.0;

  // Add slight radial component for lens-like feel
  let center = uv - vec2f(0.5);
  let radialOffset = center * strength * 0.01;

  // Sample outgoing clip (left) with aberration
  let leftR = textureSample(leftTex, texSampler, clamp(uv + rOffset + radialOffset, vec2f(0.0), vec2f(1.0))).r;
  let leftG = textureSample(leftTex, texSampler, clamp(uv + gOffset, vec2f(0.0), vec2f(1.0))).g;
  let leftB = textureSample(leftTex, texSampler, clamp(uv + bOffset - radialOffset, vec2f(0.0), vec2f(1.0))).b;
  let leftA = textureSample(leftTex, texSampler, uv).a;
  let leftColor = vec4f(leftR, leftG, leftB, leftA);

  // Sample incoming clip (right) with aberration
  let rightR = textureSample(rightTex, texSampler, clamp(uv + rOffset + radialOffset, vec2f(0.0), vec2f(1.0))).r;
  let rightG = textureSample(rightTex, texSampler, clamp(uv + gOffset, vec2f(0.0), vec2f(1.0))).g;
  let rightB = textureSample(rightTex, texSampler, clamp(uv + bOffset - radialOffset, vec2f(0.0), vec2f(1.0))).b;
  let rightA = textureSample(rightTex, texSampler, uv).a;
  let rightColor = vec4f(rightR, rightG, rightB, rightA);

  // Directional wipe for the crossfade (not a hard cut)
  var sweepPos: f32;
  if (dir == 0u) { sweepPos = uv.x; }
  else if (dir == 1u) { sweepPos = 1.0 - uv.x; }
  else if (dir == 2u) { sweepPos = uv.y; }
  else { sweepPos = 1.0 - uv.y; }

  // Soft directional crossfade
  let t = smoothstep(p * 1.3 - 0.15, p * 1.3 + 0.15, sweepPos);

  var color = mix(rightColor, leftColor, t);

  // Slight brightness boost at transition edge
  let edgeDist = abs(sweepPos - p);
  let edgeGlow = exp(-edgeDist * edgeDist * 40.0) * 0.08 * envelope;
  color = vec4f(min(color.rgb + edgeGlow, vec3f(1.0)), color.a);

  return color;
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.spread??1.5,o=i?.intensity??1;return new Float32Array([e,t,n,r,a,o,0,0])}},_={id:`radialBlur`,name:`Radial Blur`,category:`custom`,hasDirection:!1,entryPoint:`radialBlurFragment`,uniformSize:32,shader:`
struct RadialBlurParams {
  progress: f32,
  width: f32,
  height: f32,
  blurStrength: f32,
  spin: f32,
  samples: f32,
  _pad1: f32,
  _pad2: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: RadialBlurParams;

fn sampleWithRadialBlur(tex: texture_2d<f32>, uv: vec2f, strength: f32, spinAmount: f32) -> vec4f {
  let center = vec2f(0.5, 0.5);
  let dir = uv - center;
  let dist = length(dir);

  // Combine zoom blur + spin blur
  let numSamples = u32(params.samples);
  var color = vec4f(0.0);
  var totalWeight = 0.0;

  for (var i = 0u; i < numSamples; i++) {
    let t = f32(i) / f32(numSamples - 1u) - 0.5;

    // Zoom: offset along radial direction
    let zoomOffset = dir * t * strength;

    // Spin: rotate around center
    let angle = t * spinAmount;
    let cosA = cos(angle);
    let sinA = sin(angle);
    let rotatedDir = vec2f(
      dir.x * cosA - dir.y * sinA,
      dir.x * sinA + dir.y * cosA
    ) - dir;
    let spinOffset = rotatedDir * strength;

    let sampleUv = clamp(uv + zoomOffset + spinOffset, vec2f(0.0), vec2f(1.0));

    // Gaussian-ish weight (center samples contribute more)
    let weight = exp(-t * t * 4.0);
    color += textureSample(tex, texSampler, sampleUv) * weight;
    totalWeight += weight;
  }

  return color / totalWeight;
}

@fragment
fn radialBlurFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = params.progress;

  // Blur envelope: ramp up → peak at midpoint → ramp down
  let blurEnvelope = sin(p * PI);
  let strength = blurEnvelope * params.blurStrength * 0.15;
  let spinAmount = blurEnvelope * params.spin * 0.3;

  // Sample both clips with radial blur
  let left = sampleWithRadialBlur(leftTex, uv, strength, spinAmount);
  let right = sampleWithRadialBlur(rightTex, uv, strength, spinAmount);

  // Crossfade with smooth S-curve
  let t = smoothstep(0.3, 0.7, p);

  var color = mix(left, right, t);

  // Subtle vignette darkening during blur peak
  let center = uv - vec2f(0.5);
  let vignette = 1.0 - dot(center, center) * blurEnvelope * 0.5;
  color = vec4f(color.rgb * vignette, color.a);

  return color;
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.blurStrength??1,o=i?.spin??.3,s=i?.samples??12;return new Float32Array([e,t,n,a,o,s,0,0])}},v={id:`fade`,name:`Fade`,category:`basic`,hasDirection:!1,entryPoint:`fadeFragment`,uniformSize:16,shader:`
struct FadeParams {
  progress: f32,
  width: f32,
  height: f32,
  _pad: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: FadeParams;

@fragment
fn fadeFragment(input: VertexOutput) -> @location(0) vec4f {
  let p = clamp(params.progress, 0.0, 1.0);

  // cos²/sin² weights summing to 1, plus a 4% scale drift — mirrors the
  // Canvas2D fade renderer so GPU preview matches CPU export exactly.
  let c = cos(p * PI / 2.0);
  let outgoingWeight = c * c;
  let incomingWeight = 1.0 - c * c;
  let outgoingScale = 1.0 - 0.04 * p;
  let incomingScale = 1.04 - 0.04 * p;

  let outgoingUv = (input.uv - vec2f(0.5)) / outgoingScale + vec2f(0.5);
  let incomingUv = (input.uv - vec2f(0.5)) / incomingScale + vec2f(0.5);
  let left = textureSample(leftTex, texSampler, clamp(outgoingUv, vec2f(0.0), vec2f(1.0)));
  let right = textureSample(rightTex, texSampler, clamp(incomingUv, vec2f(0.0), vec2f(1.0)));
  let outgoingMask = f32(all(outgoingUv >= vec2f(0.0)) && all(outgoingUv <= vec2f(1.0)));
  let incomingMask = f32(all(incomingUv >= vec2f(0.0)) && all(incomingUv <= vec2f(1.0)));

  let wOut = outgoingWeight * outgoingMask;
  let wIn = incomingWeight * incomingMask;
  let color = left.rgb * wOut + right.rgb * wIn;
  let alpha = clamp(left.a * wOut + right.a * wIn, 0.0, 1.0);

  return vec4f(color, alpha);
}`,packUniforms:(e,t,n)=>new Float32Array([e,t,n,0])},y={id:`wipe`,name:`Wipe`,category:`wipe`,hasDirection:!0,directions:[`from-left`,`from-right`,`from-top`,`from-bottom`],entryPoint:`wipeFragment`,uniformSize:16,shader:`
struct WipeParams {
  progress: f32,
  width: f32,
  height: f32,
  direction: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: WipeParams;

@fragment
fn wipeFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let dir = u32(params.direction);

  // Sample both textures upfront (uniform control flow required)
  let left = textureSample(leftTex, texSampler, uv);
  let right = textureSample(rightTex, texSampler, uv);

  // Sweep position along the wipe axis (0→1 in sweep direction)
  var sweepPos: f32;
  if (dir == 0u) { sweepPos = uv.x; }             // from-left
  else if (dir == 1u) { sweepPos = 1.0 - uv.x; }  // from-right
  else if (dir == 2u) { sweepPos = uv.y; }         // from-top
  else { sweepPos = 1.0 - uv.y; }                  // from-bottom

  // Hard edge: swept region shows incoming, rest shows outgoing
  let t = step(sweepPos, params.progress);
  return mix(left, right, t);
}`,packUniforms:(e,t,n,r)=>new Float32Array([e,t,n,r])},b={id:`slide`,name:`Slide`,category:`slide`,hasDirection:!0,directions:[`from-left`,`from-right`,`from-top`,`from-bottom`],entryPoint:`slideFragment`,uniformSize:16,shader:`
struct SlideParams {
  progress: f32,
  width: f32,
  height: f32,
  direction: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: SlideParams;

@fragment
fn slideFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = params.progress;
  let dir = u32(params.direction);

  // Push-slide: both clips move together.
  // Compute offset UVs for both clips, then sample upfront.

  // Offset vectors per direction:
  // from-left:   outgoing shifts right by p, incoming shifts from left (offset = p-1)
  // from-right:  outgoing shifts left by p, incoming shifts from right
  // from-top:    outgoing shifts down by p, incoming shifts from top
  // from-bottom: outgoing shifts up by p, incoming shifts from bottom
  var leftUv: vec2f;
  var rightUv: vec2f;
  var splitTest: f32;

  if (dir == 0u) {
    leftUv = vec2f(uv.x - p, uv.y);
    rightUv = vec2f(uv.x - p + 1.0, uv.y);
    splitTest = step(uv.x, p);
  } else if (dir == 1u) {
    leftUv = vec2f(uv.x + p, uv.y);
    rightUv = vec2f(uv.x - (1.0 - p), uv.y);
    splitTest = step(1.0 - p, uv.x);
  } else if (dir == 2u) {
    leftUv = vec2f(uv.x, uv.y - p);
    rightUv = vec2f(uv.x, uv.y - p + 1.0);
    splitTest = step(uv.y, p);
  } else {
    leftUv = vec2f(uv.x, uv.y + p);
    rightUv = vec2f(uv.x, uv.y - (1.0 - p));
    splitTest = step(1.0 - p, uv.y);
  }

  // Sample both textures upfront (uniform control flow required)
  let left = textureSample(leftTex, texSampler, leftUv);
  let right = textureSample(rightTex, texSampler, rightUv);

  return mix(left, right, splitTest);
}`,packUniforms:(e,t,n,r)=>new Float32Array([e,t,n,r])},x={id:`flip`,name:`Flip`,category:`custom`,hasDirection:!0,directions:[`from-left`,`from-right`,`from-top`,`from-bottom`],entryPoint:`flipFragment`,uniformSize:16,shader:`
struct FlipParams {
  progress: f32,
  width: f32,
  height: f32,
  direction: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: FlipParams;

@fragment
fn flipFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = params.progress;
  let dir = u32(params.direction);

  // Horizontal flip (from-left/from-right) scales X, vertical scales Y
  let isHorizontal = (dir == 0u || dir == 1u);
  let midpoint = 0.5;
  let centered = uv - vec2f(0.5, 0.5);

  // Phase 1: outgoing scales 1→0; Phase 2: incoming scales 0→1
  let flipProgress1 = p / midpoint;
  let flipProgress2 = (p - midpoint) / midpoint;
  let scale1 = max(cos(flipProgress1 * PI * 0.5), 0.001);
  let scale2 = max(sin(flipProgress2 * PI * 0.5), 0.001);
  let scale = select(scale2, scale1, p < midpoint);

  // Distort UV from center based on axis
  let hDistorted = vec2f(centered.x / scale + 0.5, uv.y);
  let vDistorted = vec2f(uv.x, centered.y / scale + 0.5);
  let distorted = select(vDistorted, hDistorted, isHorizontal);

  // Sample both textures at the distorted UV (uniform control flow)
  let left = textureSample(leftTex, texSampler, distorted);
  let right = textureSample(rightTex, texSampler, distorted);

  // Out of bounds = black
  let oob = distorted.x < 0.0 || distorted.x > 1.0 || distorted.y < 0.0 || distorted.y > 1.0;
  let black = vec4f(0.0, 0.0, 0.0, 1.0);

  // Phase 1 shows outgoing (left), Phase 2 shows incoming (right)
  let texColor = select(right, left, p < midpoint);
  return select(texColor, black, oob);
}`,packUniforms:(e,t,n,r)=>new Float32Array([e,t,n,r])},S={id:`clockWipe`,name:`Clock Wipe`,category:`mask`,hasDirection:!1,entryPoint:`clockWipeFragment`,uniformSize:16,shader:`
struct ClockWipeParams {
  progress: f32,
  width: f32,
  height: f32,
  edgeSoftness: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: ClockWipeParams;

${i}

fn clockSweepMask(angle: f32, sweepAngle: f32, feather: f32) -> f32 {
  if (sweepAngle <= 0.0) {
    return 0.0;
  }
  if (sweepAngle >= TAU) {
    return 1.0;
  }
  if (feather <= 0.0001) {
    return select(0.0, 1.0, angle <= sweepAngle);
  }
  return 1.0 - smoothstep(sweepAngle - feather, sweepAngle + feather, angle);
}

@fragment
fn clockWipeFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = clamp(params.progress, 0.0, 1.0);

  // Compute angle from center in pixel space (preserves aspect ratio)
  let pixelPos = uv * vec2f(params.width, params.height);
  let center = vec2f(params.width * 0.5, params.height * 0.5);
  let delta = pixelPos - center;

  // atan2(x, -y) gives angle from 12 o'clock (top), clockwise positive
  let angle = atan2(delta.x, -delta.y);

  // Normalize angle from [-PI, PI] to [0, TAU]
  let normalizedAngle = select(angle, angle + TAU, angle < 0.0);
  let sweepAngle = p * TAU;
  let feather = max(0.0, min(params.edgeSoftness * TAU / 360.0, min(sweepAngle, TAU - sweepAngle)));
  let outgoingScale = 1.0 - (0.04 * p);
  let incomingScale = 1.04 - (0.04 * p);
  let outgoingOpacity = 1.0 - (0.1 * p);
  let incomingOpacity = 0.85 + (0.15 * p);
  let leftUv = scaleUv(uv, outgoingScale);
  let rightUv = scaleUv(uv, incomingScale);

  // Sample both textures upfront (uniform control flow required)
  let left = textureSample(leftTex, texSampler, leftUv);
  let right = textureSample(rightTex, texSampler, rightUv);
  let outgoingColor = vec4f(left.rgb * outgoingOpacity, left.a * outgoingOpacity);
  let incomingColor = vec4f(right.rgb * incomingOpacity, right.a * incomingOpacity);

  // Swept region with soft edge: incoming; un-swept: outgoing
  let swept = clockSweepMask(normalizedAngle, sweepAngle, feather);
  return mix(outgoingColor, incomingColor, swept);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.edgeSoftness??8;return new Float32Array([e,t,n,a])}},C={id:`iris`,name:`Iris`,category:`iris`,hasDirection:!1,entryPoint:`irisFragment`,uniformSize:16,shader:`
struct IrisParams {
  progress: f32,
  width: f32,
  height: f32,
  edgeSoftness: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: IrisParams;

${i}

fn circleMask(distanceFromCenter: f32, radius: f32, feather: f32) -> f32 {
  if (radius <= 0.0) {
    return 0.0;
  }
  if (feather <= 0.001) {
    return select(0.0, 1.0, distanceFromCenter <= radius);
  }
  return 1.0 - smoothstep(radius - feather, radius + feather, distanceFromCenter);
}

@fragment
fn irisFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = clamp(params.progress, 0.0, 1.0);

  // Compute distance from center in pixel space
  let pixelPos = uv * vec2f(params.width, params.height);
  let halfW = params.width * 0.5;
  let halfH = params.height * 0.5;
  let center = vec2f(halfW, halfH);
  let dist = length(pixelPos - center);

  // Max radius = diagonal from center to corner * 1.2 (matches CPU)
  let maxRadius = sqrt(halfW * halfW + halfH * halfH) * 1.2;
  let radius = p * maxRadius;
  let feather = max(0.0, min(params.edgeSoftness, min(radius, maxRadius - radius)));
  let outgoingScale = 1.0 - (0.04 * p);
  let incomingScale = 1.04 - (0.04 * p);
  let outgoingOpacity = 1.0 - (0.1 * p);
  let incomingOpacity = 0.85 + (0.15 * p);
  let leftUv = scaleUv(uv, outgoingScale);
  let rightUv = scaleUv(uv, incomingScale);

  // Sample both textures upfront (uniform control flow required)
  let left = textureSample(leftTex, texSampler, leftUv);
  let right = textureSample(rightTex, texSampler, rightUv);
  let outgoingColor = vec4f(left.rgb * outgoingOpacity, left.a * outgoingOpacity);
  let incomingColor = vec4f(right.rgb * incomingOpacity, right.a * incomingOpacity);

  // Inside circle with soft edge: incoming; outside: outgoing
  let inside = circleMask(dist, radius, feather);
  return mix(outgoingColor, incomingColor, inside);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.edgeSoftness??6;return new Float32Array([e,t,n,a])}},w={id:`liquidDistort`,name:`Liquid Distort`,category:`custom`,hasDirection:!0,directions:[`from-left`,`from-right`,`from-top`,`from-bottom`],entryPoint:`liquidDistortFragment`,uniformSize:48,shader:`
struct LiquidDistortParams {
  progress: f32,
  width: f32,
  height: f32,
  direction: f32,
  intensity: f32,
  scale: f32,
  turbulence: f32,
  edgeSoftness: f32,
  chroma: f32,
  swirl: f32,
  shine: f32,
  _pad: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: LiquidDistortParams;

fn liquidAxis(uv: vec2f, dir: u32) -> f32 {
  if (dir == 0u) { return uv.x; }
  if (dir == 1u) { return 1.0 - uv.x; }
  if (dir == 2u) { return uv.y; }
  return 1.0 - uv.y;
}

fn liquidFlow(uv: vec2f, p: f32, scale: f32, turbulence: f32) -> vec2f {
  let aspect = max(params.width / max(params.height, 1.0), 0.001);
  let pos = vec2f(uv.x * aspect, uv.y) * scale;
  let slow = fbm(pos + vec2f(p * 1.8, -p * 1.15));
  let fast = fbm(pos * 1.9 + vec2f(-p * 2.7, p * 1.55));
  let curlX = noise2d(pos + vec2f(slow * 2.5, p * 3.0)) - 0.5;
  let curlY = noise2d(pos + vec2f(p * -2.0, fast * 2.5)) - 0.5;
  return vec2f(curlX, curlY) * turbulence + vec2f(slow - 0.5, fast - 0.5) * 0.45;
}

@fragment
fn liquidDistortFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = clamp(params.progress, 0.0, 1.0);
  let dir = u32(params.direction);
  let envelope = sin(p * PI);
  let axis = liquidAxis(uv, dir);
  let flow = liquidFlow(uv, p, max(params.scale, 0.001), params.turbulence);

  let center = uv - vec2f(0.5);
  let swirlAngle = params.swirl * envelope * 0.42;
  let s = sin(swirlAngle);
  let c = cos(swirlAngle);
  let rotated = vec2f(center.x * c - center.y * s, center.x * s + center.y * c);
  let swirlOffset = (rotated - center) * 0.32;

  let baseStrength = params.intensity * envelope * 0.052;
  let leftOffset = (flow + swirlOffset) * baseStrength;
  let rightOffset = (-flow * 0.82 + swirlOffset * 0.55) * baseStrength;

  let frontNoise = fbm(uv * max(params.scale * 0.72, 0.001) + vec2f(p * 2.2, -p * 1.7));
  let front = axis + (frontNoise - 0.5) * 0.28 * params.intensity * envelope;
  let softness = max(params.edgeSoftness, 0.001);
  let reveal = smoothstep(p - softness, p + softness, front);

  let leftUv = clamp(uv + leftOffset, vec2f(0.0), vec2f(1.0));
  let rightUv = clamp(uv + rightOffset, vec2f(0.0), vec2f(1.0));
  let leftColor = textureSampleLevel(leftTex, texSampler, leftUv, 0.0);
  let rightColor = textureSampleLevel(rightTex, texSampler, rightUv, 0.0);

  let chromaOffset = flow * params.chroma * envelope * 0.018;
  let rightR = textureSampleLevel(rightTex, texSampler, clamp(rightUv + chromaOffset, vec2f(0.0), vec2f(1.0)), 0.0).r;
  let rightB = textureSampleLevel(rightTex, texSampler, clamp(rightUv - chromaOffset, vec2f(0.0), vec2f(1.0)), 0.0).b;
  let refractedRight = vec4f(rightR, rightColor.g, rightB, rightColor.a);

  let caustic = pow(max(0.0, 1.0 - abs(front - p) / max(softness * 2.5, 0.001)), 2.0);
  let shimmerNoise = fbm(uv * max(params.scale * 2.4, 0.001) + vec2f(p * 5.0, p * -4.0));
  let shine = vec3f(0.72, 0.88, 1.0) * caustic * shimmerNoise * params.shine * envelope * 0.22;

  let color = mix(refractedRight, leftColor, reveal);
  let glassMix = smoothstep(0.0, 1.0, caustic * 0.65 + envelope * 0.2);
  let glassed = mix(color.rgb, color.rgb + shine, glassMix);
  return vec4f(min(glassed, vec3f(1.0)), color.a);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.intensity??1,o=i?.scale??4.5,s=i?.turbulence??1,c=i?.edgeSoftness??.18,l=i?.chroma??.75,u=i?.swirl??.8,d=i?.shine??1;return new Float32Array([e,t,n,r,a,o,s,c,l,u,d,0])}},T={id:`lensWarpZoom`,name:`Lens Warp Zoom`,category:`custom`,hasDirection:!1,entryPoint:`lensWarpZoomFragment`,uniformSize:48,shader:`
struct LensWarpZoomParams {
  progress: f32,
  width: f32,
  height: f32,
  zoomStrength: f32,
  warpStrength: f32,
  blurStrength: f32,
  chroma: f32,
  vignette: f32,
  centerX: f32,
  centerY: f32,
  glow: f32,
  _pad: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: LensWarpZoomParams;

fn barrelWarp(uv: vec2f, center: vec2f, amount: f32) -> vec2f {
  let aspect = max(params.width / max(params.height, 1.0), 0.001);
  var p = uv - center;
  p.x *= aspect;
  let r2 = dot(p, p);
  let warped = p * (1.0 + amount * r2);
  return vec2f(warped.x / aspect, warped.y) + center;
}

fn zoomAround(uv: vec2f, center: vec2f, zoom: f32) -> vec2f {
  return center + (uv - center) / max(zoom, 0.001);
}

fn sampleZoomBlur(tex: texture_2d<f32>, uv: vec2f, center: vec2f, strength: f32) -> vec4f {
  let dir = center - uv;
  var color = vec4f(0.0);
  var weightSum = 0.0;
  for (var i = 0u; i < 7u; i++) {
    let t = f32(i) / 6.0;
    let weight = 1.0 - abs(t - 0.5) * 0.8;
    let sampleUv = clamp(uv + dir * strength * (t - 0.5), vec2f(0.0), vec2f(1.0));
    color += textureSampleLevel(tex, texSampler, sampleUv, 0.0) * weight;
    weightSum += weight;
  }
  return color / weightSum;
}

@fragment
fn lensWarpZoomFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = clamp(params.progress, 0.0, 1.0);
  let center = vec2f(params.centerX, params.centerY);
  let envelope = sin(p * PI);
  let punch = smoothstep(0.0, 0.46, p) * (1.0 - smoothstep(0.58, 1.0, p));
  let reveal = smoothstep(0.36, 0.64, p);

  let outgoingZoom = 1.0 + params.zoomStrength * p * 0.42 + punch * 0.18;
  let incomingZoom = 1.0 + params.zoomStrength * (1.0 - p) * 0.58;
  let warp = params.warpStrength * envelope;
  let blur = params.blurStrength * envelope * 0.11;

  let leftWarped = barrelWarp(zoomAround(uv, center, outgoingZoom), center, warp);
  let rightWarped = barrelWarp(zoomAround(uv, center, incomingZoom), center, -warp * 0.65);

  let leftColor = sampleZoomBlur(leftTex, leftWarped, center, blur);
  let rightBase = sampleZoomBlur(rightTex, rightWarped, center, blur * 0.82);

  let chromaDir = normalize((uv - center) + vec2f(0.0001));
  let chromaOffset = chromaDir * params.chroma * envelope * 0.012;
  let rightR = textureSampleLevel(rightTex, texSampler, clamp(rightWarped + chromaOffset, vec2f(0.0), vec2f(1.0)), 0.0).r;
  let rightB = textureSampleLevel(rightTex, texSampler, clamp(rightWarped - chromaOffset, vec2f(0.0), vec2f(1.0)), 0.0).b;
  let rightColor = vec4f(rightR, rightBase.g, rightB, rightBase.a);

  let dist = distance(uv, center);
  let ring = exp(-pow((dist - 0.22 - p * 0.18) * 8.0, 2.0)) * params.glow * envelope;
  let vignette = 1.0 - smoothstep(0.36, 0.9, dist) * params.vignette * envelope * 0.45;
  let edgeLight = vec3f(0.78, 0.9, 1.0) * ring * 0.18;

  let color = mix(leftColor, rightColor, reveal);
  return vec4f(min(color.rgb * vignette + edgeLight, vec3f(1.0)), color.a);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.zoomStrength??1,o=i?.warpStrength??.75,s=i?.blurStrength??1,c=i?.chroma??.65,l=i?.vignette??.7,u=i?.centerX??.5,d=i?.centerY??.5,f=i?.glow??1;return new Float32Array([e,t,n,a,o,s,c,l,u,d,f,0])}},E={id:`lightLeakBurn`,name:`Light Leak Burn`,category:`custom`,hasDirection:!0,directions:[`from-left`,`from-right`,`from-top`,`from-bottom`],entryPoint:`lightLeakBurnFragment`,uniformSize:48,shader:`
struct LightLeakBurnParams {
  progress: f32,
  width: f32,
  height: f32,
  direction: f32,
  intensity: f32,
  spread: f32,
  warmth: f32,
  burn: f32,
  edgeSoftness: f32,
  grain: f32,
  _pad1: f32,
  _pad2: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: LightLeakBurnParams;

fn burnAxis(uv: vec2f, dir: u32) -> f32 {
  if (dir == 0u) { return uv.x; }
  if (dir == 1u) { return 1.0 - uv.x; }
  if (dir == 2u) { return uv.y; }
  return 1.0 - uv.y;
}

@fragment
fn lightLeakBurnFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = clamp(params.progress, 0.0, 1.0);
  let dir = u32(params.direction);
  let axis = burnAxis(uv, dir);
  let envelope = sin(p * PI);

  let left = textureSampleLevel(leftTex, texSampler, uv, 0.0);
  let right = textureSampleLevel(rightTex, texSampler, uv, 0.0);

  let organic = fbm(uv * vec2f(4.0, 3.0) + vec2f(p * 2.7, -p * 1.9));
  let fine = noise2d(uv * vec2f(params.width, params.height) * 0.45 + vec2f(p * 431.0));
  let noisyAxis = axis + (organic - 0.5) * params.spread * 0.28;
  let reveal = smoothstep(p - params.edgeSoftness, p + params.edgeSoftness, noisyAxis);
  // Reveal is 1 ahead of the moving front and 0 behind it. Keep the outgoing
  // frame ahead of the front so p=0 starts on left, then reveal the incoming
  // frame behind it until p=1 ends on right.
  let base = mix(right, left, reveal);

  let frontDist = abs(noisyAxis - p);
  let hotCore = exp(-frontDist * frontDist / max(0.0001, params.edgeSoftness * params.edgeSoftness * 0.38));
  let warmHalo = exp(-frontDist * frontDist / max(0.0001, params.edgeSoftness * params.edgeSoftness * 3.5));
  let warm = mix(vec3f(1.0, 0.88, 0.58), vec3f(1.0, 0.48, 0.16), params.warmth);
  let whiteHot = vec3f(1.0, 0.96, 0.86);
  let grain = (fine - 0.5) * params.grain * envelope * 0.08;
  let burnLight = warm * warmHalo * params.intensity * envelope * 1.15
    + whiteHot * hotCore * params.burn * envelope * 1.35;

  let overexposed = 1.0 - exp(-(base.rgb + burnLight + grain) * (1.0 + hotCore * params.burn));
  let color = mix(base.rgb, overexposed, clamp((warmHalo + hotCore) * envelope, 0.0, 1.0));
  return vec4f(clamp(color, vec3f(0.0), vec3f(1.0)), base.a);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.intensity??1.25,o=i?.spread??1,s=i?.warmth??.75,c=i?.burn??1.1,l=i?.edgeSoftness??.16,u=i?.grain??.5;return new Float32Array([e,t,n,r,a,o,s,c,l,u,0,0])}},D={id:`filmGateSlip`,name:`Film Gate Slip`,category:`custom`,hasDirection:!1,entryPoint:`filmGateSlipFragment`,uniformSize:48,shader:`
struct FilmGateSlipParams {
  progress: f32,
  width: f32,
  height: f32,
  slip: f32,
  shake: f32,
  exposure: f32,
  gateWidth: f32,
  grain: f32,
  chroma: f32,
  roll: f32,
  _pad1: f32,
  _pad2: f32,
};

@group(0) @binding(0) var texSampler: sampler;
@group(0) @binding(1) var leftTex: texture_2d<f32>;
@group(0) @binding(2) var rightTex: texture_2d<f32>;
@group(0) @binding(3) var<uniform> params: FilmGateSlipParams;

fn sampleFilm(tex: texture_2d<f32>, uv: vec2f, chromaOffset: vec2f) -> vec4f {
  let baseUv = clamp(uv, vec2f(0.0), vec2f(1.0));
  let r = textureSampleLevel(tex, texSampler, clamp(baseUv + chromaOffset, vec2f(0.0), vec2f(1.0)), 0.0).r;
  let g = textureSampleLevel(tex, texSampler, baseUv, 0.0).g;
  let b = textureSampleLevel(tex, texSampler, clamp(baseUv - chromaOffset, vec2f(0.0), vec2f(1.0)), 0.0).b;
  let a = textureSampleLevel(tex, texSampler, baseUv, 0.0).a;
  return vec4f(r, g, b, a);
}

@fragment
fn filmGateSlipFragment(input: VertexOutput) -> @location(0) vec4f {
  let uv = input.uv;
  let p = clamp(params.progress, 0.0, 1.0);
  let envelope = sin(p * PI);
  let frame = floor(p * 18.0);
  let jitterA = hash(vec2f(frame, 19.7));
  let jitterB = hash(vec2f(frame + 3.0, 41.3));
  let gatePulse = smoothstep(0.08, 0.22, p) * (1.0 - smoothstep(0.78, 0.96, p));

  let slipOffset = (p - 0.5) * params.slip * envelope * 0.32
    + (jitterA - 0.5) * params.shake * envelope * 0.05;
  let lateral = (jitterB - 0.5) * params.shake * envelope * 0.025;
  let roll = params.roll * envelope * 0.04 * sin(p * TAU * 2.0);
  let outgoingUv = vec2f(uv.x + lateral + roll * (uv.y - 0.5), uv.y + slipOffset);
  let incomingUv = vec2f(uv.x - lateral * 0.65 - roll * (uv.y - 0.5), uv.y - slipOffset * 0.55);

  let chromaOffset = vec2f(params.chroma * envelope * 0.006, 0.0);
  let left = sampleFilm(leftTex, outgoingUv, chromaOffset);
  let right = sampleFilm(rightTex, incomingUv, chromaOffset * 0.7);
  var color = mix(left, right, smoothstep(0.42, 0.58, p));

  let gateTop = smoothstep(params.gateWidth, 0.0, uv.y);
  let gateBottom = smoothstep(1.0 - params.gateWidth, 1.0, uv.y);
  let gateFlash = max(gateTop, gateBottom) * gatePulse * 0.2;
  let flicker = 1.0 + (hash(vec2f(frame, 8.1)) - 0.42) * params.exposure * envelope * 0.38;
  let grain = (hash(floor(uv * vec2f(params.width, params.height) * 0.7) + vec2f(frame)) - 0.5)
    * params.grain * envelope * 0.12;
  let vignette = 1.0 - dot(uv - vec2f(0.5), uv - vec2f(0.5)) * envelope * 0.35;

  color = vec4f(color.rgb * flicker * vignette + grain + vec3f(gateFlash), color.a);
  return vec4f(clamp(color.rgb, vec3f(0.0), vec3f(1.0)), color.a);
}`,packUniforms:(e,t,n,r,i)=>{let a=i?.slip??1,o=i?.shake??1,s=i?.exposure??.85,c=i?.gateWidth??.075,l=i?.grain??.6,u=i?.chroma??.55,d=i?.roll??.75;return new Float32Array([e,t,n,a,o,s,c,l,u,d,0,0])}},O=new Map;function k(e){O.set(e.id,e)}k(a),k(c),k(l),k(u),k(d),k(f),k(p),k(m),k(h),k(g),k(_),k(v),k(y),k(b),k(x),k(S),k(C),k(w),k(T),k(E),k(D);function A(e){return O.get(e)}var j=t(`TransitionPipeline`),M=class e{device;format;sampler;pipelines=new Map;uniformBuffers=new Map;cachedBindGroups=new Map;leftTexture=null;rightTexture=null;leftView=null;rightView=null;outputCanvas=null;outputCtx=null;texW=0;texH=0;initialized=!1;constructor(e){this.device=e,this.format=`rgba8unorm`,this.sampler=e.createSampler({magFilter:`linear`,minFilter:`linear`})}static create(t){let n=t;if(!n)return null;try{let t=new e(n);return t.init(),t}catch{return null}}init(){if(!this.initialized){for(let[e,t]of O)this.createTransitionPipeline(e,t);this.initialized=!0}}createTransitionPipeline(e,t){try{let n=`${r}\n${t.shader}`,i=this.device.createShaderModule({label:`transition-${e}`,code:n});i.getCompilationInfo().then(t=>{for(let n of t.messages)n.type===`error`&&j.error(`Shader "${e}" error at line ${n.lineNum}:${n.linePos}: ${n.message}`)}).catch(()=>{});let a=[{binding:0,visibility:GPUShaderStage.FRAGMENT,sampler:{}},{binding:1,visibility:GPUShaderStage.FRAGMENT,texture:{}},{binding:2,visibility:GPUShaderStage.FRAGMENT,texture:{}}];t.uniformSize>0&&a.push({binding:3,visibility:GPUShaderStage.FRAGMENT,buffer:{type:`uniform`}});let o=this.device.createBindGroupLayout({label:`transition-${e}-layout`,entries:a}),s=this.device.createRenderPipeline({label:`transition-${e}-pipeline`,layout:this.device.createPipelineLayout({bindGroupLayouts:[o]}),vertex:{module:i,entryPoint:`vertexMain`},fragment:{module:i,entryPoint:t.entryPoint,targets:[{format:this.format}]},primitive:{topology:`triangle-list`}});this.pipelines.set(e,{pipeline:s,bindGroupLayout:o})}catch(t){j.warn(`Failed to create pipeline for "${e}"`,t)}}ensureTextures(e,t){if(this.leftTexture&&this.texW===e&&this.texH===t)return;this.leftTexture?.destroy(),this.rightTexture?.destroy();let n={size:{width:e,height:t},format:`rgba8unorm`,usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT};this.leftTexture=this.device.createTexture(n),this.rightTexture=this.device.createTexture(n),this.leftView=this.leftTexture.createView(),this.rightView=this.rightTexture.createView(),this.cachedBindGroups.clear(),this.texW=e,this.texH=t}getOrCreateUniformBuffer(e,t){let n=this.uniformBuffers.get(e);return n&&n.size>=t?n:(n?.destroy(),n=this.device.createBuffer({size:t,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.uniformBuffers.set(e,n),n)}writeUniforms(e,t,n,r,i,a,o){if(t.uniformSize<=0)return null;let s=t.packUniforms(n,r,i,N(a),o);if(s.byteLength>t.uniformSize)return j.warn(`Uniform data for "${e}" is ${s.byteLength} bytes, exceeding declared size ${t.uniformSize}`),null;let c=this.getOrCreateUniformBuffer(e,t.uniformSize);return this.device.queue.writeBuffer(c,0,s.buffer,s.byteOffset,s.byteLength),c}getOrCreateBindGroup(e,t,n,r){if(n.uniformSize>0&&!r)return this.cachedBindGroups.delete(e),null;let i=this.cachedBindGroups.get(e);return i||(!this.leftView||!this.rightView?null:(i=this.createBindGroup(t,this.leftView,this.rightView,r),this.cachedBindGroups.set(e,i),i))}createBindGroup(e,t,n,r){let i=[{binding:0,resource:this.sampler},{binding:1,resource:t},{binding:2,resource:n}];return r&&i.push({binding:3,resource:{buffer:r}}),this.device.createBindGroup({layout:e,entries:i})}uploadInputs(e,t,n,r){return this.ensureTextures(n,r),!this.leftTexture||!this.rightTexture?!1:(this.device.queue.copyExternalImageToTexture({source:e,flipY:!1},{texture:this.leftTexture,premultipliedAlpha:!0},{width:n,height:r}),this.device.queue.copyExternalImageToTexture({source:t,flipY:!1},{texture:this.rightTexture,premultipliedAlpha:!0},{width:n,height:r}),!0)}renderUploadedInputsToView(e,t,n,r,i,a,o){let s=this.pipelines.get(e),c=A(e);if(!s||!c)return!1;let l=this.writeUniforms(e,c,t,n,r,a,o),u=this.getOrCreateBindGroup(e,s.bindGroupLayout,c,l);if(!u)return!1;let d=this.device.createCommandEncoder(),f=d.beginRenderPass({colorAttachments:[{view:i,loadOp:`clear`,storeOp:`store`}]});return f.setPipeline(s.pipeline),f.setBindGroup(0,u),f.draw(6),f.end(),this.device.queue.submit([d.finish()]),!0}render(e,t,n,r,i,a,o,s){if(!this.pipelines.has(e)||!A(e)||i<2||a<2||!this.uploadInputs(t,n,i,a))return null;if(!this.outputCanvas||this.outputCanvas.width!==i||this.outputCanvas.height!==a){this.outputCanvas=new OffscreenCanvas(i,a);let e=this.outputCanvas.getContext(`webgpu`);if(!e)return null;e.configure({device:this.device,format:this.format,alphaMode:`premultiplied`}),this.outputCtx=e}return!this.outputCtx||!this.renderUploadedInputsToView(e,r,i,a,this.outputCtx.getCurrentTexture().createView(),o,s)?null:this.outputCanvas}renderToTexture(e,t,n,r,i,a,o,s,c){return!this.pipelines.has(e)||!A(e)||a<2||o<2||r.width!==a||r.height!==o||!this.uploadInputs(t,n,a,o)?!1:this.renderUploadedInputsToView(e,i,a,o,r.createView(),s,c)}renderTexturesToTexture(e,t,n,r,i,a,o,s,c){let l=this.pipelines.get(e),u=A(e);if(!l||!u||a<2||o<2||t.width!==a||t.height!==o||n.width!==a||n.height!==o||r.width!==a||r.height!==o)return!1;let d=this.writeUniforms(e,u,i,a,o,s,c);if(u.uniformSize>0&&!d)return!1;let f=this.createBindGroup(l.bindGroupLayout,t.createView(),n.createView(),d),p=this.device.createCommandEncoder(),m=p.beginRenderPass({colorAttachments:[{view:r.createView(),loadOp:`clear`,storeOp:`store`}]});return m.setPipeline(l.pipeline),m.setBindGroup(0,f),m.draw(6),m.end(),this.device.queue.submit([p.finish()]),!0}has(e){return this.pipelines.has(e)}destroy(){this.leftTexture?.destroy(),this.rightTexture?.destroy(),this.leftTexture=null,this.rightTexture=null,this.leftView=null,this.rightView=null,this.outputCanvas=null,this.outputCtx=null;for(let e of this.uniformBuffers.values())e.destroy();this.uniformBuffers.clear(),this.cachedBindGroups.clear(),this.pipelines.clear(),this.initialized=!1}};function N(e){switch(e){case`from-left`:return 0;case`from-right`:return 1;case`from-top`:return 2;case`from-bottom`:return 3;default:return 0}}var P=e({TransitionPipeline:()=>M});export{M as n,A as r,P as t};