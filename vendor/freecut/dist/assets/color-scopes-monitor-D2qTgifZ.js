import{o as e}from"./rolldown-runtime-DAXXjFlN.js";import{En as t,Fs as n,Li as r,Ri as i,Rt as a,Sn as o,Ut as s,Vt as c,Wt as l,da as u,or as d,zt as f}from"./app-shell-CbVZDWsj.js";import{jo as p}from"./feature-editing-core-BMx2bO8G.js";import{Dt as m}from"./vendor-icons-BvhAFILG.js";var h={r:.04,g:.04,b:.04,a:1};function g(e,t){return e.createBindGroupLayout({entries:t.map((e,t)=>({binding:t,visibility:GPUShaderStage.FRAGMENT,buffer:{type:e}}))})}function _({device:e,format:t,layout:n,shaderCode:r}){let i=e.createShaderModule({code:r});return e.createRenderPipeline({layout:e.createPipelineLayout({bindGroupLayouts:[n]}),vertex:{module:i,entryPoint:`vs`},fragment:{module:i,entryPoint:`fs`,targets:[{format:t}]}})}function v({encoder:e,pipeline:t,bindGroup:n,srcW:r,srcH:i}){let a=e.beginComputePass();a.setPipeline(t),a.setBindGroup(0,n),a.dispatchWorkgroups(Math.ceil(r/16),Math.ceil(i/16)),a.end()}function y({device:e,context:t,pipeline:n,bindGroup:r,encoder:i=e.createCommandEncoder(),submit:a=!0}){let o=i.beginRenderPass({colorAttachments:[{view:t.getCurrentTexture().createView(),loadOp:`clear`,storeOp:`store`,clearValue:h}]});o.setPipeline(n),o.setBindGroup(0,r),o.draw(3),o.end(),a&&e.queue.submit([i.finish()])}var b=`
struct Params {
  srcW: u32,
  srcH: u32,
  _pad0: u32,
  _pad1: u32,
  kr: f32,
  kb: f32,
  rangeMin: f32,
  rangeMax: f32,
}

@group(0) @binding(0) var inputTex: texture_2d<f32>;
@group(0) @binding(1) var<storage, read_write> histR: array<atomic<u32>>;
@group(0) @binding(2) var<storage, read_write> histG: array<atomic<u32>>;
@group(0) @binding(3) var<storage, read_write> histB: array<atomic<u32>>;
@group(0) @binding(4) var<storage, read_write> histL: array<atomic<u32>>;
@group(0) @binding(5) var<uniform> params: Params;

fn normRange(v: f32, rMin: f32, rMax: f32) -> f32 {
  return clamp((v - rMin) / max(rMax - rMin, 0.001), 0.0, 1.0);
}

@compute @workgroup_size(16, 16)
fn main(@builtin(global_invocation_id) gid: vec3u) {
  if (gid.x >= params.srcW || gid.y >= params.srcH) { return; }
  let pixel = textureLoad(inputTex, vec2i(gid.xy), 0);
  let rn = normRange(pixel.r, params.rangeMin, params.rangeMax);
  let gn = normRange(pixel.g, params.rangeMin, params.rangeMax);
  let bn = normRange(pixel.b, params.rangeMin, params.rangeMax);
  let r = min(u32(rn * 255.0), 255u);
  let g = min(u32(gn * 255.0), 255u);
  let b = min(u32(bn * 255.0), 255u);
  let kg = 1.0 - params.kr - params.kb;
  let luma = normRange(params.kr * pixel.r + kg * pixel.g + params.kb * pixel.b, params.rangeMin, params.rangeMax);
  let l = min(u32(luma * 255.0), 255u);
  atomicAdd(&histR[r], 1u);
  atomicAdd(&histG[g], 1u);
  atomicAdd(&histB[b], 1u);
  atomicAdd(&histL[l], 1u);
}
`,x=`
struct VertexOutput { @builtin(position) pos: vec4f, @location(0) uv: vec2f }

@vertex
fn vs(@builtin(vertex_index) vid: u32) -> VertexOutput {
  var p = array<vec2f, 3>(vec2f(-1,-1), vec2f(3,-1), vec2f(-1,3));
  var out: VertexOutput;
  out.pos = vec4f(p[vid], 0, 1);
  out.uv = vec2f((p[vid].x + 1.0) * 0.5, (1.0 - p[vid].y) * 0.5);
  return out;
}

struct Params {
  totalPixels: f32,
  mode: f32,
  _pad1: f32,
  _pad2: f32,
}

@group(0) @binding(0) var<storage, read> histR: array<u32>;
@group(0) @binding(1) var<storage, read> histG: array<u32>;
@group(0) @binding(2) var<storage, read> histB: array<u32>;
@group(0) @binding(3) var<storage, read> histL: array<u32>;
@group(0) @binding(4) var<uniform> params: Params;

fn sampleHist(hist: ptr<storage, array<u32>, read>, fx: f32) -> f32 {
  let b0 = u32(clamp(fx, 0.0, 255.0));
  let b1 = min(b0 + 1u, 255u);
  let t = fract(fx);
  return mix(f32((*hist)[b0]), f32((*hist)[b1]), t);
}

@fragment
fn fs(in: VertexOutput) -> @location(0) vec4f {
  let uv = in.uv;
  if (uv.x < 0.0 || uv.x >= 1.0 || uv.y < 0.0 || uv.y >= 1.0) {
    return vec4f(0.04, 0.04, 0.04, 1.0);
  }

  let mode = u32(params.mode);
  let fx = uv.x * 255.0;
  let rVal = sampleHist(&histR, fx);
  let gVal = sampleHist(&histG, fx);
  let bVal = sampleHist(&histB, fx);
  let lVal = sampleHist(&histL, fx);

  let scale = 1.0 / sqrt(params.totalPixels * 0.08);
  let rH = sqrt(rVal) * scale;
  let gH = sqrt(gVal) * scale;
  let bH = sqrt(bVal) * scale;
  let lH = sqrt(lVal) * scale;

  let y = 1.0 - uv.y;
  let aaW = 0.004;
  var color = vec3f(0.0);

  if (mode == 0u) {
    let lFill = smoothstep(lH, lH - aaW, y);
    let rFill = smoothstep(rH, rH - aaW, y);
    let gFill = smoothstep(gH, gH - aaW, y);
    let bFill = smoothstep(bH, bH - aaW, y);
    let rGrad = 0.35 + 0.35 * (y / max(rH, 0.001));
    let gGrad = 0.35 + 0.35 * (y / max(gH, 0.001));
    let bGrad = 0.35 + 0.35 * (y / max(bH, 0.001));
    color += vec3f(0.08) * lFill;
    color += vec3f(rGrad, 0.05, 0.05) * rFill;
    color += vec3f(0.05, gGrad, 0.05) * gFill;
    color += vec3f(0.05, 0.05, bGrad) * bFill;
  } else if (mode == 1u) {
    let fill = smoothstep(rH, rH - aaW, y);
    let grad = 0.3 + 0.5 * (y / max(rH, 0.001));
    color = vec3f(grad, 0.08, 0.08) * fill;
  } else if (mode == 2u) {
    let fill = smoothstep(gH, gH - aaW, y);
    let grad = 0.3 + 0.5 * (y / max(gH, 0.001));
    color = vec3f(0.08, grad, 0.08) * fill;
  } else if (mode == 3u) {
    let fill = smoothstep(bH, bH - aaW, y);
    let grad = 0.3 + 0.5 * (y / max(bH, 0.001));
    color = vec3f(0.08, 0.08, grad) * fill;
  } else {
    let fill = smoothstep(lH, lH - aaW, y);
    let grad = 0.3 + 0.4 * (y / max(lH, 0.001));
    color = vec3f(grad) * fill;
  }

  let edgeW = 0.006;
  if (mode == 0u) {
    let rEdge = smoothstep(edgeW, 0.0, abs(y - rH)) * step(y, rH + edgeW);
    let gEdge = smoothstep(edgeW, 0.0, abs(y - gH)) * step(y, gH + edgeW);
    let bEdge = smoothstep(edgeW, 0.0, abs(y - bH)) * step(y, bH + edgeW);
    color += vec3f(0.6, 0.12, 0.12) * rEdge;
    color += vec3f(0.12, 0.55, 0.12) * gEdge;
    color += vec3f(0.12, 0.12, 0.6) * bEdge;
  } else if (mode == 1u) {
    let e = smoothstep(edgeW, 0.0, abs(y - rH)) * step(y, rH + edgeW);
    color += vec3f(0.7, 0.18, 0.18) * e;
  } else if (mode == 2u) {
    let e = smoothstep(edgeW, 0.0, abs(y - gH)) * step(y, gH + edgeW);
    color += vec3f(0.18, 0.65, 0.18) * e;
  } else if (mode == 3u) {
    let e = smoothstep(edgeW, 0.0, abs(y - bH)) * step(y, bH + edgeW);
    color += vec3f(0.18, 0.18, 0.7) * e;
  } else {
    let e = smoothstep(edgeW, 0.0, abs(y - lH)) * step(y, lH + edgeW);
    color += vec3f(0.6) * e;
  }

  let gridBins = array<f32, 3>(64.0, 128.0, 192.0);
  for (var i = 0u; i < 3u; i += 1u) {
    let gx = gridBins[i] / 256.0;
    let gAA = smoothstep(0.003, 0.001, abs(uv.x - gx));
    color = max(color, vec3f(0.10) * gAA);
  }
  for (var i = 1u; i < 4u; i += 1u) {
    let gy = f32(i) * 0.25;
    let hAA = smoothstep(0.004, 0.001, abs(y - gy));
    color = max(color, vec3f(0.07) * hAA);
  }

  return vec4f(clamp(color, vec3f(0.0), vec3f(1.0)), 1.0);
}
`,ee=class{device;computePipeline;renderPipeline;computeBGL;renderBGL;histR;histG;histB;histL;computeParams;renderParams;constructor(e,t){this.device=e;let n=256*4;this.histR=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.histG=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.histB=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.histL=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.computeParams=e.createBuffer({size:32,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.renderParams=e.createBuffer({size:16,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.computeBGL=e.createBindGroupLayout({entries:[{binding:0,visibility:GPUShaderStage.COMPUTE,texture:{sampleType:`float`}},{binding:1,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:2,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:3,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:4,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:5,visibility:GPUShaderStage.COMPUTE,buffer:{type:`uniform`}}]}),this.computePipeline=e.createComputePipeline({layout:e.createPipelineLayout({bindGroupLayouts:[this.computeBGL]}),compute:{module:e.createShaderModule({code:b}),entryPoint:`main`}}),this.renderBGL=g(e,[`read-only-storage`,`read-only-storage`,`read-only-storage`,`read-only-storage`,`uniform`]),this.renderPipeline=_({device:e,format:t,layout:this.renderBGL,shaderCode:x})}render(e,t,n,r,i,a,o){let s=this.device,c=e.width,l=e.height,u=new ArrayBuffer(32);new Uint32Array(u,0,4).set([c,l,0,0]),new Float32Array(u,16,4).set([r,i,a,o]),s.queue.writeBuffer(this.computeParams,0,u),s.queue.writeBuffer(this.renderParams,0,new Float32Array([c*l,n,0,0]));let d=s.createCommandEncoder();d.clearBuffer(this.histR),d.clearBuffer(this.histG),d.clearBuffer(this.histB),d.clearBuffer(this.histL);let f=s.createBindGroup({layout:this.computeBGL,entries:[{binding:0,resource:e.createView()},{binding:1,resource:{buffer:this.histR}},{binding:2,resource:{buffer:this.histG}},{binding:3,resource:{buffer:this.histB}},{binding:4,resource:{buffer:this.histL}},{binding:5,resource:{buffer:this.computeParams}}]});v({encoder:d,pipeline:this.computePipeline,bindGroup:f,srcW:c,srcH:l});let p=s.createBindGroup({layout:this.renderBGL,entries:[{binding:0,resource:{buffer:this.histR}},{binding:1,resource:{buffer:this.histG}},{binding:2,resource:{buffer:this.histB}},{binding:3,resource:{buffer:this.histL}},{binding:4,resource:{buffer:this.renderParams}}]});y({device:s,context:t,pipeline:this.renderPipeline,bindGroup:p,encoder:d})}destroy(){for(let e of[this.histR,this.histG,this.histB,this.histL,this.computeParams,this.renderParams])e?.destroy()}},S=`
struct Params {
  outW: u32,
  outH: u32,
  srcW: u32,
  srcH: u32,
  kr: f32,
  kb: f32,
  rangeMin: f32,
  rangeMax: f32,
}

@group(0) @binding(0) var inputTex: texture_2d<f32>;
@group(0) @binding(1) var<storage, read_write> accumR: array<atomic<u32>>;
@group(0) @binding(2) var<storage, read_write> accumG: array<atomic<u32>>;
@group(0) @binding(3) var<storage, read_write> accumB: array<atomic<u32>>;
@group(0) @binding(4) var<uniform> params: Params;
@group(0) @binding(5) var<storage, read_write> accumL: array<atomic<u32>>;

fn normRange(v: f32, rMin: f32, rMax: f32) -> f32 {
  return clamp((v - rMin) / max(rMax - rMin, 0.001), 0.0, 1.0);
}

@compute @workgroup_size(16, 16)
fn main(@builtin(global_invocation_id) gid: vec3u) {
  if (gid.x >= params.srcW || gid.y >= params.srcH) { return; }

  let pixel = textureLoad(inputTex, vec2i(gid.xy), 0);

  // Sub-pixel X: distribute weight across 2 adjacent columns (scale 256)
  let fxPos = f32(gid.x) * f32(params.outW) / f32(params.srcW);
  let x0 = u32(fxPos);
  let x1 = min(x0 + 1u, params.outW - 1u);
  let frac = fxPos - f32(x0);
  let w0 = u32((1.0 - frac) * 256.0);
  let w1 = 256u - w0;

  let hm1 = f32(params.outH - 1u);
  let maxY = i32(params.outH - 1u);

  // Gaussian vertical spread kernel — 5 rows for smooth traces
  let gK = array<f32, 5>(0.06, 0.24, 0.40, 0.24, 0.06);

  // Range-normalized channel values
  let rn = normRange(pixel.r, params.rangeMin, params.rangeMax);
  let gn = normRange(pixel.g, params.rangeMin, params.rangeMax);
  let bn = normRange(pixel.b, params.rangeMin, params.rangeMax);
  let kg = 1.0 - params.kr - params.kb;
  let ln = normRange(params.kr * pixel.r + kg * pixel.g + params.kb * pixel.b, params.rangeMin, params.rangeMax);

  // Red
  let ryC = i32(hm1 - clamp(rn, 0.0, 1.0) * hm1);
  for (var d: i32 = -2; d <= 2; d += 1) {
    let y = u32(clamp(ryC + d, 0, maxY));
    let yw = gK[u32(d + 2)];
    let idx = y * params.outW;
    let wA = u32(f32(w0) * yw);
    let wB = u32(f32(w1) * yw);
    if (wA > 0u) { atomicAdd(&accumR[idx + x0], wA); }
    if (wB > 0u) { atomicAdd(&accumR[idx + x1], wB); }
  }

  // Green
  let gyC = i32(hm1 - clamp(gn, 0.0, 1.0) * hm1);
  for (var d: i32 = -2; d <= 2; d += 1) {
    let y = u32(clamp(gyC + d, 0, maxY));
    let yw = gK[u32(d + 2)];
    let idx = y * params.outW;
    let wA = u32(f32(w0) * yw);
    let wB = u32(f32(w1) * yw);
    if (wA > 0u) { atomicAdd(&accumG[idx + x0], wA); }
    if (wB > 0u) { atomicAdd(&accumG[idx + x1], wB); }
  }

  // Blue
  let byC = i32(hm1 - clamp(bn, 0.0, 1.0) * hm1);
  for (var d: i32 = -2; d <= 2; d += 1) {
    let y = u32(clamp(byC + d, 0, maxY));
    let yw = gK[u32(d + 2)];
    let idx = y * params.outW;
    let wA = u32(f32(w0) * yw);
    let wB = u32(f32(w1) * yw);
    if (wA > 0u) { atomicAdd(&accumB[idx + x0], wA); }
    if (wB > 0u) { atomicAdd(&accumB[idx + x1], wB); }
  }

  // Luma
  let lyC = i32(hm1 - clamp(ln, 0.0, 1.0) * hm1);
  for (var d: i32 = -2; d <= 2; d += 1) {
    let y = u32(clamp(lyC + d, 0, maxY));
    let yw = gK[u32(d + 2)];
    let idx = y * params.outW;
    let wA = u32(f32(w0) * yw);
    let wB = u32(f32(w1) * yw);
    if (wA > 0u) { atomicAdd(&accumL[idx + x0], wA); }
    if (wB > 0u) { atomicAdd(&accumL[idx + x1], wB); }
  }
}
`,C=`
struct VertexOutput {
  @builtin(position) pos: vec4f,
  @location(0) uv: vec2f,
}

@vertex
fn vs(@builtin(vertex_index) vid: u32) -> VertexOutput {
  var p = array<vec2f, 3>(vec2f(-1,-1), vec2f(3,-1), vec2f(-1,3));
  var out: VertexOutput;
  out.pos = vec4f(p[vid], 0, 1);
  out.uv = vec2f((p[vid].x + 1.0) * 0.5, (1.0 - p[vid].y) * 0.5);
  return out;
}

struct RenderParams {
  outW: f32,
  outH: f32,
  refValue: f32,
  intensity: f32,
  mode: u32,
  _pad0: u32,
  _pad1: u32,
  _pad2: u32,
}

@group(0) @binding(0) var<storage, read> accumR: array<u32>;
@group(0) @binding(1) var<storage, read> accumG: array<u32>;
@group(0) @binding(2) var<storage, read> accumB: array<u32>;
@group(0) @binding(3) var<uniform> params: RenderParams;
@group(0) @binding(4) var<storage, read> accumL: array<u32>;

fn sampleAccum(acc: ptr<storage, array<u32>, read>, fx: f32, fy: f32, w: u32, h: u32) -> f32 {
  let x0 = u32(clamp(fx, 0.0, f32(w - 1u)));
  let y0 = u32(clamp(fy, 0.0, f32(h - 1u)));
  let x1 = min(x0 + 1u, w - 1u);
  let y1 = min(y0 + 1u, h - 1u);
  let dx = fract(fx);
  let dy = fract(fy);
  let v00 = f32((*acc)[y0 * w + x0]);
  let v10 = f32((*acc)[y0 * w + x1]);
  let v01 = f32((*acc)[y1 * w + x0]);
  let v11 = f32((*acc)[y1 * w + x1]);
  return mix(mix(v00, v10, dx), mix(v01, v11, dx), dy);
}

fn readAccum(acc: ptr<storage, array<u32>, read>, x: i32, y: i32, w: i32, h: i32) -> f32 {
  return f32((*acc)[u32(clamp(y, 0, h - 1)) * u32(w) + u32(clamp(x, 0, w - 1))]);
}

fn bloomSingle(acc: ptr<storage, array<u32>, read>, ix: i32, iy: i32, w: i32, h: i32) -> f32 {
  let bK = array<f32, 3>(0.25, 0.50, 0.25);
  var total = 0.0;
  for (var dy: i32 = -1; dy <= 1; dy += 1) {
    for (var dx: i32 = -1; dx <= 1; dx += 1) {
      total += readAccum(acc, ix + dx * 4, iy + dy * 4, w, h) * bK[u32(dx + 1)] * bK[u32(dy + 1)];
    }
  }
  return total;
}

@fragment
fn fs(in: VertexOutput) -> @location(0) vec4f {
  let uv = in.uv;
  if (uv.x < 0.0 || uv.x >= 1.0 || uv.y < 0.0 || uv.y >= 1.0) {
    return vec4f(0.04, 0.04, 0.04, 1.0);
  }

  let w = u32(params.outW);
  let h = u32(params.outH);
  let iw = i32(w);
  let ih = i32(h);
  let mode = params.mode;
  let rv = params.refValue;
  let s = params.intensity;

  var color: vec3f;

  if (mode == 5u) {
    // Parade mode: R | G | B side by side
    let section = min(u32(uv.x * 3.0), 2u);
    let localX = fract(uv.x * 3.0);
    let pfx = localX * params.outW - 0.5;
    let pfy = uv.y * params.outH - 0.5;
    let pix = i32(pfx + 0.5);
    let piy = i32(pfy + 0.5);

    var cv: f32;
    var bv: f32;

    if (section == 0u) {
      cv = sampleAccum(&accumR, pfx, pfy, w, h);
      bv = bloomSingle(&accumR, pix, piy, iw, ih);
    } else if (section == 1u) {
      cv = sampleAccum(&accumG, pfx, pfy, w, h);
      bv = bloomSingle(&accumG, pix, piy, iw, ih);
    } else {
      cv = sampleAccum(&accumB, pfx, pfy, w, h);
      bv = bloomSingle(&accumB, pix, piy, iw, ih);
    }

    let vT = pow(clamp(sqrt(cv) / rv, 0.0, 1.0), 0.75) * s;
    let vG = pow(clamp(sqrt(bv) / rv, 0.0, 1.0), 0.65) * 0.12;
    let v = clamp(vT + vG, 0.0, 1.0);

    if (section == 0u) {
      color = vec3f(v, v * 0.15, v * 0.15);
    } else if (section == 1u) {
      color = vec3f(v * 0.15, v, v * 0.15);
    } else {
      color = vec3f(v * 0.15, v * 0.15, v);
    }

    // Section dividers (anti-aliased)
    let divW = 2.0 / params.outW;
    let d1 = smoothstep(divW, 0.0, abs(uv.x - 1.0 / 3.0));
    let d2 = smoothstep(divW, 0.0, abs(uv.x - 2.0 / 3.0));
    color = max(color, vec3f(0.18) * max(d1, d2));
  } else {
    // Standard waveform modes (0=RGB, 1=R, 2=G, 3=B, 4=Luma)
    let fx = uv.x * params.outW - 0.5;
    let fy = uv.y * params.outH - 0.5;

    let rCenter = sampleAccum(&accumR, fx, fy, w, h);
    let gCenter = sampleAccum(&accumG, fx, fy, w, h);
    let bCenter = sampleAccum(&accumB, fx, fy, w, h);
    let lCenter = sampleAccum(&accumL, fx, fy, w, h);

    let ix = i32(fx + 0.5);
    let iy = i32(fy + 0.5);
    let rBloom = bloomSingle(&accumR, ix, iy, iw, ih);
    let gBloom = bloomSingle(&accumG, ix, iy, iw, ih);
    let bBloom = bloomSingle(&accumB, ix, iy, iw, ih);
    let lBloom = bloomSingle(&accumL, ix, iy, iw, ih);

    let rT = pow(clamp(sqrt(rCenter) / rv, 0.0, 1.0), 0.75) * s;
    let gT = pow(clamp(sqrt(gCenter) / rv, 0.0, 1.0), 0.75) * s;
    let bT = pow(clamp(sqrt(bCenter) / rv, 0.0, 1.0), 0.75) * s;
    let lT = pow(clamp(sqrt(lCenter) / rv, 0.0, 1.0), 0.75) * s;

    let rG = pow(clamp(sqrt(rBloom) / rv, 0.0, 1.0), 0.65) * 0.12;
    let gG = pow(clamp(sqrt(gBloom) / rv, 0.0, 1.0), 0.65) * 0.12;
    let bG = pow(clamp(sqrt(bBloom) / rv, 0.0, 1.0), 0.65) * 0.12;
    let lG = pow(clamp(sqrt(lBloom) / rv, 0.0, 1.0), 0.65) * 0.12;

    if (mode == 0u) {
      color = clamp(vec3f(rT + rG, gT + gG, bT + bG), vec3f(0.0), vec3f(1.0));
    } else if (mode == 1u) {
      let v = clamp(rT + rG, 0.0, 1.0);
      color = vec3f(v, v * 0.15, v * 0.15);
    } else if (mode == 2u) {
      let v = clamp(gT + gG, 0.0, 1.0);
      color = vec3f(v * 0.15, v, v * 0.15);
    } else if (mode == 3u) {
      let v = clamp(bT + bG, 0.0, 1.0);
      color = vec3f(v * 0.15, v * 0.15, v);
    } else {
      let v = clamp(lT + lG, 0.0, 1.0);
      color = vec3f(v);
    }
  }

  // Grid: every 10 IRE (10% of height)
  let gridY = fract(uv.y * 10.0);
  let dGrid = min(gridY, 1.0 - gridY) * params.outH * 0.5;
  if (dGrid < 0.8) {
    let a = 0.15 * (1.0 - dGrid / 0.8);
    color = max(color, vec3f(0.55, 0.45, 0.12) * a);
  }

  return vec4f(color, 1.0);
}
`,w=1024,T=512,E=class{device;computePipeline;renderPipeline;computeBGL;renderBGL;accumR;accumG;accumB;accumL;computeParams;renderParams;constructor(e,t){this.device=e;let n=w*T*4;this.accumR=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.accumG=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.accumB=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.accumL=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.computeParams=e.createBuffer({size:32,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.renderParams=e.createBuffer({size:32,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.computeBGL=e.createBindGroupLayout({entries:[{binding:0,visibility:GPUShaderStage.COMPUTE,texture:{sampleType:`float`}},{binding:1,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:2,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:3,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:4,visibility:GPUShaderStage.COMPUTE,buffer:{type:`uniform`}},{binding:5,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}}]}),this.computePipeline=e.createComputePipeline({layout:e.createPipelineLayout({bindGroupLayouts:[this.computeBGL]}),compute:{module:e.createShaderModule({code:S}),entryPoint:`main`}}),this.renderBGL=g(e,[`read-only-storage`,`read-only-storage`,`read-only-storage`,`uniform`,`read-only-storage`]),this.renderPipeline=_({device:e,format:t,layout:this.renderBGL,shaderCode:C})}accumulate(e,t,n,r,i){let a=this.device,o=e.width,s=e.height,c=new ArrayBuffer(32);new Uint32Array(c,0,4).set([w,T,o,s]),new Float32Array(c,16,4).set([t,n,r,i]),a.queue.writeBuffer(this.computeParams,0,c);let l=a.createCommandEncoder();l.clearBuffer(this.accumR),l.clearBuffer(this.accumG),l.clearBuffer(this.accumB),l.clearBuffer(this.accumL);let u=a.createBindGroup({layout:this.computeBGL,entries:[{binding:0,resource:e.createView()},{binding:1,resource:{buffer:this.accumR}},{binding:2,resource:{buffer:this.accumG}},{binding:3,resource:{buffer:this.accumB}},{binding:4,resource:{buffer:this.computeParams}},{binding:5,resource:{buffer:this.accumL}}]});return v({encoder:l,pipeline:this.computePipeline,bindGroup:u,srcW:o,srcH:s}),a.queue.submit([l.finish()]),s}renderAccumulated(e,t,n){let r=this.device,i=Math.sqrt(n/T)*40,a=new ArrayBuffer(32);new Float32Array(a,0,4).set([w,T,i,.9]),new Uint32Array(a,16,4).set([t,0,0,0]),r.queue.writeBuffer(this.renderParams,0,a);let o=r.createBindGroup({layout:this.renderBGL,entries:[{binding:0,resource:{buffer:this.accumR}},{binding:1,resource:{buffer:this.accumG}},{binding:2,resource:{buffer:this.accumB}},{binding:3,resource:{buffer:this.renderParams}},{binding:4,resource:{buffer:this.accumL}}]});y({device:r,context:e,pipeline:this.renderPipeline,bindGroup:o})}render(e,t,n,r,i,a,o){this.renderBatch(e,[{ctx:t,mode:n}],r,i,a,o)}renderBatch(e,t,n,r,i,a){if(t.length===0)return;let o=this.accumulate(e,n,r,i,a);for(let{ctx:e,mode:n}of t)this.renderAccumulated(e,n,o)}destroy(){for(let e of[this.accumR,this.accumG,this.accumB,this.accumL,this.computeParams,this.renderParams])e?.destroy()}},D=`
struct Params {
  outSize: u32,
  srcW: u32,
  srcH: u32,
  _pad: u32,
  kr: f32,
  kb: f32,
  _pad2: f32,
  _pad3: f32,
}

@group(0) @binding(0) var inputTex: texture_2d<f32>;
@group(0) @binding(1) var<storage, read_write> accumR: array<atomic<u32>>;
@group(0) @binding(2) var<storage, read_write> accumG: array<atomic<u32>>;
@group(0) @binding(3) var<storage, read_write> accumB: array<atomic<u32>>;
@group(0) @binding(4) var<uniform> params: Params;

@compute @workgroup_size(16, 16)
fn main(@builtin(global_invocation_id) gid: vec3u) {
  if (gid.x >= params.srcW || gid.y >= params.srcH) { return; }
  let pixel = textureLoad(inputTex, vec2i(gid.xy), 0);

  let r = pixel.r;
  let g = pixel.g;
  let b = pixel.b;
  let kg = 1.0 - params.kr - params.kb;

  // Y'CbCr from configurable matrix coefficients
  let y = params.kr * r + kg * g + params.kb * b;
  let cb = (b - y) / (2.0 * (1.0 - params.kb));
  let cr = (r - y) / (2.0 * (1.0 - params.kr));

  let center = f32(params.outSize) * 0.5;
  let scale = center * 0.92;
  // Cb/Cr are in [-0.5, 0.5], map to pixel coordinates
  let px = u32(clamp(center + cb * 2.0 * scale, 0.0, f32(params.outSize - 1u)));
  let py = u32(clamp(center - cr * 2.0 * scale, 0.0, f32(params.outSize - 1u)));

  let idx = py * params.outSize + px;
  // Accumulate raw pixel color scaled to [1, 255] for visible contribution
  atomicAdd(&accumR[idx], u32(max(r * 255.0, 1.0)));
  atomicAdd(&accumG[idx], u32(max(g * 255.0, 1.0)));
  atomicAdd(&accumB[idx], u32(max(b * 255.0, 1.0)));
}
`,O=`
struct VertexOutput { @builtin(position) pos: vec4f, @location(0) uv: vec2f }

@vertex
fn vs(@builtin(vertex_index) vid: u32) -> VertexOutput {
  var p = array<vec2f, 3>(vec2f(-1,-1), vec2f(3,-1), vec2f(-1,3));
  var out: VertexOutput;
  out.pos = vec4f(p[vid], 0, 1);
  out.uv = vec2f((p[vid].x + 1.0) * 0.5, (1.0 - p[vid].y) * 0.5);
  return out;
}

struct Params { outSize: f32, refValue: f32, _p0: f32, _p1: f32 }

@group(0) @binding(0) var<storage, read> accumR: array<u32>;
@group(0) @binding(1) var<storage, read> accumG: array<u32>;
@group(0) @binding(2) var<storage, read> accumB: array<u32>;
@group(0) @binding(3) var<uniform> params: Params;

fn sampleVS(acc: ptr<storage, array<u32>, read>, fx: f32, fy: f32, sz: u32) -> f32 {
  let x0 = u32(clamp(fx, 0.0, f32(sz - 1u)));
  let y0 = u32(clamp(fy, 0.0, f32(sz - 1u)));
  let x1 = min(x0 + 1u, sz - 1u);
  let y1 = min(y0 + 1u, sz - 1u);
  let dx = fract(fx);
  let dy = fract(fy);
  let v00 = f32((*acc)[y0 * sz + x0]);
  let v10 = f32((*acc)[y0 * sz + x1]);
  let v01 = f32((*acc)[y1 * sz + x0]);
  let v11 = f32((*acc)[y1 * sz + x1]);
  return mix(mix(v00, v10, dx), mix(v01, v11, dx), dy);
}

fn readVS(acc: ptr<storage, array<u32>, read>, x: i32, y: i32, sz: i32) -> f32 {
  return f32((*acc)[u32(clamp(y, 0, sz - 1)) * u32(sz) + u32(clamp(x, 0, sz - 1))]);
}

@fragment
fn fs(in: VertexOutput) -> @location(0) vec4f {
  let uv = in.uv;
  let size = params.outSize;
  let sz = u32(size);
  let isz = i32(sz);
  let center = 0.5;
  let d = distance(uv, vec2f(center));
  let gratScale = 0.92;

  var color = vec3f(0.04);

  // Graticule circles: 100%, 75%, 25% saturation
  let radiusFull = gratScale * 0.5;
  let radius75 = gratScale * 0.5 * 0.75;
  let radius25 = gratScale * 0.5 * 0.25;
  let lineW = 1.2 / size;
  let aa = smoothstep(0.0, lineW, abs(d - radiusFull));
  color = mix(vec3f(0.20), color, aa);
  let aa75 = smoothstep(0.0, lineW, abs(d - radius75));
  color = mix(vec3f(0.14), color, aa75);
  let aa25 = smoothstep(0.0, lineW, abs(d - radius25));
  color = mix(vec3f(0.10), color, aa25);

  // Crosshair
  let crossW = 0.8 / size;
  if (d < radiusFull + 0.01) {
    let axH = smoothstep(0.0, crossW, abs(uv.y - center));
    let axV = smoothstep(0.0, crossW, abs(uv.x - center));
    color = mix(vec3f(0.12), color, axH);
    color = mix(vec3f(0.12), color, axV);
  }

  // Skin tone line (~123 degrees)
  let angle = atan2(-(uv.y - center), uv.x - center);
  let skinAngle = radians(123.0);
  let skinAA = smoothstep(0.0, crossW, abs(angle - skinAngle));
  if (d < radiusFull + 0.01 && d > 0.01) {
    color = mix(vec3f(0.28, 0.20, 0.08), color, skinAA);
  }

  // Color targets on 75% ring (R, MG, B, CY, G, YL)
  let targetAngles = array<f32, 6>(
    radians(103.0), radians(61.0), radians(-13.0),
    radians(-77.0), radians(-119.0), radians(167.0)
  );
  let targetColors = array<vec3f, 6>(
    vec3f(0.6, 0.15, 0.15), vec3f(0.5, 0.15, 0.5), vec3f(0.15, 0.15, 0.6),
    vec3f(0.15, 0.5, 0.5), vec3f(0.15, 0.5, 0.15), vec3f(0.5, 0.5, 0.1)
  );
  let dotR = 8.0 / size;
  let ringW = 2.0 / size;
  for (var i = 0u; i < 6u; i += 1u) {
    let ta = targetAngles[i];
    let tx = center + cos(ta) * radius75;
    let ty = center - sin(ta) * radius75;
    let td = distance(uv, vec2f(tx, ty));
    let dotAA = smoothstep(dotR, dotR - ringW, td);
    let ringAA = smoothstep(ringW * 0.5, 0.0, abs(td - dotR));
    color = mix(color, targetColors[i] * 0.5, dotAA);
    color = mix(color, targetColors[i], ringAA);
  }

  // Data visualization: bilinear center + bloom glow
  if (uv.x >= 0.0 && uv.x < 1.0 && uv.y >= 0.0 && uv.y < 1.0) {
    let fx = uv.x * size - 0.5;
    let fy = uv.y * size - 0.5;

    let rCenter = sampleVS(&accumR, fx, fy, sz);
    let gCenter = sampleVS(&accumG, fx, fy, sz);
    let bCenter = sampleVS(&accumB, fx, fy, sz);

    // Bloom: 3x3 gaussian at 3px step
    let ix = i32(fx + 0.5);
    let iy = i32(fy + 0.5);
    var rBloom = 0.0; var gBloom = 0.0; var bBloom = 0.0;
    let bK = array<f32, 3>(0.25, 0.50, 0.25);
    for (var by: i32 = -1; by <= 1; by += 1) {
      for (var bx: i32 = -1; bx <= 1; bx += 1) {
        let bw = bK[u32(bx + 1)] * bK[u32(by + 1)];
        rBloom += readVS(&accumR, ix + bx * 3, iy + by * 3, isz) * bw;
        gBloom += readVS(&accumG, ix + bx * 3, iy + by * 3, isz) * bw;
        bBloom += readVS(&accumB, ix + bx * 3, iy + by * 3, isz) * bw;
      }
    }

    let rv = params.refValue;
    let totalCenter = rCenter + gCenter + bCenter;
    let totalBloom = rBloom + gBloom + bBloom;
    let density = pow(clamp(sqrt(totalCenter / 3.0) / rv, 0.0, 1.0), 0.7);
    let bloomD = pow(clamp(sqrt(totalBloom / 3.0) / rv, 0.0, 1.0), 0.6) * 0.18;

    if (totalCenter > 0.0) {
      let rRatio = rCenter / totalCenter;
      let gRatio = gCenter / totalCenter;
      let bRatio = bCenter / totalCenter;
      let chromaColor = vec3f(rRatio, gRatio, bRatio) * 3.0;
      let whiteMix = density * density * 0.5;
      let traceColor = mix(chromaColor, vec3f(1.0), whiteMix) * (density + bloomD);
      color = max(color, clamp(traceColor, vec3f(0.0), vec3f(1.0)));
    }
  }

  return vec4f(color, 1.0);
}
`,k=512,A=class{device;computePipeline;renderPipeline;computeBGL;renderBGL;accumR;accumG;accumB;computeParams;renderParams;constructor(e,t){this.device=e;let n=k*k*4;this.accumR=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.accumG=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.accumB=e.createBuffer({size:n,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),this.computeParams=e.createBuffer({size:32,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.renderParams=e.createBuffer({size:16,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.computeBGL=e.createBindGroupLayout({entries:[{binding:0,visibility:GPUShaderStage.COMPUTE,texture:{sampleType:`float`}},{binding:1,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:2,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:3,visibility:GPUShaderStage.COMPUTE,buffer:{type:`storage`}},{binding:4,visibility:GPUShaderStage.COMPUTE,buffer:{type:`uniform`}}]}),this.computePipeline=e.createComputePipeline({layout:e.createPipelineLayout({bindGroupLayouts:[this.computeBGL]}),compute:{module:e.createShaderModule({code:D}),entryPoint:`main`}}),this.renderBGL=g(e,[`read-only-storage`,`read-only-storage`,`read-only-storage`,`uniform`]),this.renderPipeline=_({device:e,format:t,layout:this.renderBGL,shaderCode:O})}render(e,t,n,r){let i=this.device,a=e.width,o=e.height,s=new ArrayBuffer(32);new Uint32Array(s,0,4).set([k,a,o,0]),new Float32Array(s,16,4).set([n,r,0,0]),i.queue.writeBuffer(this.computeParams,0,s);let c=Math.sqrt(a*o/(k*k))*18;i.queue.writeBuffer(this.renderParams,0,new Float32Array([k,c,0,0]));let l=i.createCommandEncoder();l.clearBuffer(this.accumR),l.clearBuffer(this.accumG),l.clearBuffer(this.accumB);let u=i.createBindGroup({layout:this.computeBGL,entries:[{binding:0,resource:e.createView()},{binding:1,resource:{buffer:this.accumR}},{binding:2,resource:{buffer:this.accumG}},{binding:3,resource:{buffer:this.accumB}},{binding:4,resource:{buffer:this.computeParams}}]});v({encoder:l,pipeline:this.computePipeline,bindGroup:u,srcW:a,srcH:o});let d=i.createBindGroup({layout:this.renderBGL,entries:[{binding:0,resource:{buffer:this.accumR}},{binding:1,resource:{buffer:this.accumG}},{binding:2,resource:{buffer:this.accumB}},{binding:3,resource:{buffer:this.renderParams}}]});y({device:i,context:t,pipeline:this.renderPipeline,bindGroup:d,encoder:l})}destroy(){for(let e of[this.accumR,this.accumG,this.accumB,this.computeParams,this.renderParams])e?.destroy()}},te=class e{device;format;histogram;waveform;vectorscope;srcTexture=null;srcW=0;srcH=0;kr=.2126;kb=.0722;rangeMin=0;rangeMax=1;constructor(e){this.device=e,this.format=navigator.gpu.getPreferredCanvasFormat(),this.histogram=new ee(e,this.format),this.waveform=new E(e,this.format),this.vectorscope=new A(e,this.format)}static async create(){if(typeof navigator>`u`||!navigator.gpu)return null;try{let t=await navigator.gpu.requestAdapter();if(!t)return null;let n=await t.requestDevice();return new e(n)}catch{return null}}configureCanvas(e){try{let t=e.getContext(`webgpu`);return t?(t.configure({device:this.device,format:this.format,alphaMode:`opaque`}),t):null}catch{return null}}setMatrix(e,t){this.kr=e,this.kb=t}setRange(e,t){this.rangeMin=e,this.rangeMax=t}ensureTexture(e,t){this.srcTexture&&this.srcW===e&&this.srcH===t||(this.srcTexture?.destroy(),this.srcTexture=this.device.createTexture({size:{width:e,height:t},format:`rgba8unorm`,usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT}),this.srcW=e,this.srcH=t)}uploadFromCanvas(e){let t=e.width,n=e.height;t<2||n<2||(this.ensureTexture(t,n),this.device.queue.copyExternalImageToTexture({source:e,flipY:!1},{texture:this.srcTexture,mipLevel:0},{width:t,height:n}))}uploadFrame(e){let t=e.width,n=e.height;this.ensureTexture(t,n),this.device.queue.writeTexture({texture:this.srcTexture},e.data,{bytesPerRow:t*4},{width:t,height:n})}renderWaveforms(e){!this.srcTexture||e.length===0||this.waveform.renderBatch(this.srcTexture,e,this.kr,this.kb,this.rangeMin,this.rangeMax)}renderHistogram(e,t){this.srcTexture&&this.histogram.render(this.srcTexture,e,t,this.kr,this.kb,this.rangeMin,this.rangeMax)}renderVectorscope(e){this.srcTexture&&this.vectorscope.render(this.srcTexture,e,this.kr,this.kb)}destroy(){this.srcTexture?.destroy(),this.srcTexture=null,this.waveform.destroy(),this.histogram.destroy(),this.vectorscope.destroy()}},j=e(n(),1),M=[0,25,50,75,100],N=[{label:`R`,x:39,y:16},{label:`Mg`,x:66,y:18},{label:`B`,x:78,y:55},{label:`Cy`,x:61,y:84},{label:`G`,x:35,y:78},{label:`Yl`,x:22,y:45}],P=d();function F({children:e,className:t,containerRef:n,kind:r}){return(0,P.jsxs)(`div`,{ref:n,className:o(`relative overflow-hidden rounded border border-border/70 bg-black/80`,t),children:[e,(0,P.jsx)(I,{kind:r})]})}function I({kind:e}){return e===`vectorscope`?(0,P.jsx)(z,{}):(0,P.jsx)(L,{parade:e===`parade`,histogram:e===`histogram`})}function L({parade:e,histogram:t}){return(0,P.jsxs)(`div`,{"aria-hidden":`true`,className:`pointer-events-none absolute inset-0`,children:[M.map(e=>(0,P.jsx)(`div`,{className:`absolute left-0 right-0 border-t border-slate-400/18`,style:{top:`${100-e}%`},children:(0,P.jsx)(`span`,{className:`absolute left-1 -translate-y-1/2 rounded-sm bg-black/45 px-1 font-mono text-[9px] leading-4 text-slate-300/80`,children:e})},e)),t?(0,P.jsxs)(P.Fragment,{children:[(0,P.jsx)(`div`,{className:`absolute bottom-1 left-1 font-mono text-[9px] text-slate-400/80`,children:`0`}),(0,P.jsx)(`div`,{className:`absolute bottom-1 right-1 font-mono text-[9px] text-slate-400/80`,children:`255`})]}):null,e?(0,P.jsx)(R,{}):null]})}function R(){return(0,P.jsxs)(P.Fragment,{children:[[1,2].map(e=>(0,P.jsx)(`div`,{className:`absolute top-0 bottom-0 border-l border-slate-400/25`,style:{left:`${e/3*100}%`}},e)),[[`R`,`16.666%`,`text-red-300/90`],[`G`,`50%`,`text-emerald-300/90`],[`B`,`83.333%`,`text-blue-300/90`]].map(([e,t,n])=>(0,P.jsx)(`span`,{className:o(`absolute top-1 -translate-x-1/2 rounded-sm bg-black/45 px-1 font-mono text-[10px] leading-4`,n),style:{left:t},children:e},e))]})}function z(){return(0,P.jsxs)(`svg`,{"aria-hidden":`true`,className:`pointer-events-none absolute inset-0 h-full w-full`,preserveAspectRatio:`xMidYMid meet`,viewBox:`0 0 100 100`,children:[(0,P.jsx)(`circle`,{cx:`50`,cy:`50`,r:`45`,fill:`none`,stroke:`rgba(148,163,184,0.24)`}),(0,P.jsx)(`circle`,{cx:`50`,cy:`50`,r:`30`,fill:`none`,stroke:`rgba(148,163,184,0.18)`}),(0,P.jsx)(`circle`,{cx:`50`,cy:`50`,r:`15`,fill:`none`,stroke:`rgba(148,163,184,0.12)`}),(0,P.jsx)(`path`,{d:`M50 5 V95 M5 50 H95`,stroke:`rgba(148,163,184,0.2)`,strokeWidth:`0.8`}),(0,P.jsx)(`path`,{d:`M50 50 L36 15`,stroke:`rgba(251,191,36,0.72)`,strokeWidth:`1.2`}),(0,P.jsx)(`text`,{x:`33`,y:`13`,fill:`rgba(251,191,36,0.9)`,fontSize:`4`,fontFamily:`monospace`,textAnchor:`end`,children:`skin`}),N.map(e=>(0,P.jsxs)(`g`,{children:[(0,P.jsx)(`rect`,{x:e.x-3,y:e.y-3,width:`6`,height:`6`,fill:`none`,stroke:`rgba(226,232,240,0.34)`,strokeWidth:`0.8`}),(0,P.jsx)(`text`,{x:e.x,y:e.y-4.5,fill:`rgba(226,232,240,0.78)`,fontSize:`4`,fontFamily:`monospace`,textAnchor:`middle`,children:e.label})]},e.label))]})}var ne=384,re=216,ie=256,ae=144,oe=66,se=220,ce=1e3,le=`timeline:scopes:stackLayout`,ue=10/3,B=`bt709`,V=`full`,de=[{value:`waveform`,label:`Waveform`},{value:`parade`,label:`Parade`},{value:`vectorscope`,label:`Vectorscope`},{value:`histogram`,label:`Histogram`}],fe={rgb:0,r:1,g:2,b:3,luma:4};function H(e){return e===`bt601`?{kr:.299,kb:.114}:{kr:.2126,kb:.0722}}function pe(){try{let e=localStorage.getItem(le);if(de.some(t=>t.value===e))return e}catch{}return`parade`}function U(e,t){if(t===`legal`){let t=16/255;return Math.max(0,Math.min(1,(e-t)/(235/255-t)))}return Math.max(0,Math.min(1,e))}function W(e,t,n){e.save(),e.strokeStyle=`rgba(148, 163, 184, 0.18)`,e.lineWidth=1,e.fillStyle=`rgba(148, 163, 184, 0.8)`,e.font=`10px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`;for(let r of[0,25,50,75,100]){let i=Math.round(n-1-r/100*(n-1));e.beginPath(),e.moveTo(0,i+.5),e.lineTo(t,i+.5),e.stroke(),e.fillText(String(r),4,Math.max(10,i-2))}e.restore()}function G(e,t){let{data:n,width:r,height:i}=e;for(let e=0;e<i;e++)for(let i=0;i<r;i++){let a=(e*r+i)*4;t(i,e,(n[a]??0)/255,(n[a+1]??0)/255,(n[a+2]??0)/255)}}function me(e,t,n,r,i,a){let{kr:o,kb:s}=H(n),c=1-o-s,{width:l}=e,u=new Uint16Array(i*a),d=0;G(e,(e,t,n,f,p)=>{let m=U(o*n+c*f+s*p,r),h=Math.floor(e/Math.max(1,l-1)*(i-1)),g=(a-1-Math.floor(m*(a-1)))*i+h,_=(u[g]??0)+1;u[g]=_,_>d&&(d=_)});let f=t.createImageData(i,a),p=f.data,m=Math.log1p(Math.max(1,d));for(let e=0;e<u.length;e++){let t=u[e]??0;if(t<=0)continue;let n=Math.log1p(t)/m;if(n<=0)continue;let r=e*4;p[r]=40,p[r+1]=Math.min(255,Math.round(65+n*190)),p[r+2]=120,p[r+3]=Math.min(255,Math.round(95+n*160))}t.fillStyle=`#030712`,t.fillRect(0,0,i,a),t.putImageData(f,0,0),W(t,i,a)}function he(e,t,n,r,i){let{data:a,width:o,height:s}=e,c=new Uint16Array(r*i),l=0,u=Math.floor(r/3),d=[[255,80,80],[60,255,120],[90,130,255]];for(let e=0;e<s;e++)for(let t=0;t<o;t++){let s=(e*o+t)*4,d=[(a[s]??0)/255,(a[s+1]??0)/255,(a[s+2]??0)/255],f=Math.floor(t/Math.max(1,o-1)*(u-1));for(let e=0;e<3;e++){let t=U(d[e]??0,n),a=e*u+f,o=(i-1-Math.floor(t*(i-1)))*r+a,s=(c[o]??0)+1;c[o]=s,s>l&&(l=s)}}let f=t.createImageData(r,i),p=f.data,m=Math.log1p(Math.max(1,l));for(let e=0;e<i;e++)for(let t=0;t<r;t++){let n=e*r+t,i=c[n]??0;if(i<=0)continue;let a=Math.log1p(i)/m,o=d[Math.min(2,Math.floor(t/Math.max(1,u)))]??[180,180,180],s=n*4;p[s]=Math.min(255,Math.round((o[0]??180)*(.25+.75*a))),p[s+1]=Math.min(255,Math.round((o[1]??180)*(.25+.75*a))),p[s+2]=Math.min(255,Math.round((o[2]??180)*(.25+.75*a))),p[s+3]=Math.min(255,Math.round(85+a*160))}t.fillStyle=`#030712`,t.fillRect(0,0,r,i),t.putImageData(f,0,0),W(t,r,i),t.save(),t.strokeStyle=`rgba(148, 163, 184, 0.28)`,t.lineWidth=1;for(let e=1;e<3;e++){let n=e*u;t.beginPath(),t.moveTo(n+.5,0),t.lineTo(n+.5,i),t.stroke()}t.fillStyle=`rgba(148, 163, 184, 0.9)`,t.font=`10px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`,t.fillText(`R`,8,12),t.fillText(`G`,u+8,12),t.fillText(`B`,u*2+8,12),t.restore()}function ge(e,t,n,r,i,a){let{kr:o,kb:s}=H(n),c=1-o-s,l=new Uint32Array(256),u=0;G(e,(e,t,n,i,a)=>{let d=U(o*n+c*i+s*a,r),f=Math.max(0,Math.min(255,Math.round(d*255))),p=(l[f]??0)+1;l[f]=p,p>u&&(u=p)}),t.fillStyle=`#030712`,t.fillRect(0,0,i,a),W(t,i,a);let d=Math.log1p(Math.max(1,u));for(let e=0;e<256;e++){let n=l[e]??0;if(n<=0)continue;let r=Math.log1p(n)/d,o=Math.round(e/255*(i-1)),s=Math.max(1,Math.round(r*(a-1)));t.fillStyle=`rgba(116, 232, 195, ${.35+r*.65})`,t.fillRect(o,a-s,Math.max(1,Math.round(i/256)),s)}}function _e(e,t,n,r){let{kr:i,kb:a}=H(n),o=1-i-a,s=new Uint32Array(r*r),c=0,l=Math.floor(r/2),u=l-2;G(e,(e,t,n,d,f)=>{let p=i*n+o*d+a*f,m=(f-p)/(2*(1-a)),h=(n-p)/(2*(1-i)),g=Math.round(l+m*u*2),_=Math.round(l-h*u*2);if(g<0||g>=r||_<0||_>=r)return;let v=_*r+g,y=(s[v]??0)+1;s[v]=y,y>c&&(c=y)}),t.fillStyle=`#030712`,t.fillRect(0,0,r,r);let d=t.createImageData(r,r),f=d.data,p=Math.log1p(Math.max(1,c));for(let e=0;e<s.length;e++){let t=s[e]??0;if(t<=0)continue;let n=Math.log1p(t)/p;if(n<=0)continue;let r=e*4;f[r]=70,f[r+1]=Math.min(255,Math.round(70+n*185)),f[r+2]=255,f[r+3]=Math.min(255,Math.round(90+n*165))}t.putImageData(d,0,0),t.strokeStyle=`rgba(148, 163, 184, 0.25)`,t.lineWidth=1,t.beginPath(),t.arc(l,l,u,0,Math.PI*2),t.stroke(),t.beginPath(),t.arc(l,l,Math.floor(u*.66),0,Math.PI*2),t.stroke(),t.beginPath(),t.moveTo(l,0),t.lineTo(l,r),t.moveTo(0,l),t.lineTo(r,l),t.stroke()}function K(e,t,n,r,i){let a=e.getBoundingClientRect(),o=Math.max(2,Math.min(r,Math.round(a.width||t))),s=Math.max(2,Math.min(i,Math.round(a.height||n)));return(e.width!==o||e.height!==s)&&(e.width=o,e.height=s),{width:o,height:s}}function q({mode:e,onChange:t}){return(0,P.jsx)(`div`,{className:`flex items-center gap-0.5`,children:[{value:`rgb`,label:`RGB`},{value:`r`,label:`R`,activeColor:`#ff6666`},{value:`g`,label:`G`,activeColor:`#66cc66`},{value:`b`,label:`B`,activeColor:`#6688ff`},{value:`luma`,label:`Y`,activeColor:`#ccccaa`}].map(n=>(0,P.jsx)(`button`,{className:o(`h-4 px-1 text-[9px] font-semibold font-mono rounded transition-colors`,e===n.value?`text-white`:`text-muted-foreground hover:text-foreground`),style:e===n.value?{backgroundColor:`${n.activeColor??`#888`}33`,borderBottom:`1.5px solid ${n.activeColor??`#888`}`}:void 0,onClick:()=>t(n.value),"aria-pressed":e===n.value,children:n.label},n.value))})}function J(e,t,n,r=!0){(0,j.useEffect)(()=>{if(!r)return;let i=t.current,a=e.current;if(!i||!a)return;let o=(e,t)=>{if(e<=0||t<=0)return;let r=window.devicePixelRatio||1,i=e,o=t;if(n){let r=e/n;r<=t?o=r:(o=t,i=t*n)}let s=Math.round(i*r),c=Math.round(o*r);(a.width!==s||a.height!==c)&&(a.width=s,a.height=c,a.style.width=`${Math.round(i)}px`,a.style.height=`${Math.round(o)}px`)},s=new ResizeObserver(e=>{let t=e[0];t&&o(t.contentRect.width,t.contentRect.height)});s.observe(i),o(i.clientWidth,i.clientHeight);let c=requestAnimationFrame(()=>{o(i.clientWidth,i.clientHeight)});return()=>{cancelAnimationFrame(c),s.disconnect()}},[n,e,t,r])}var ve=(0,j.memo)(function({open:e,embedded:t=!1,embeddedLayout:n=`grid`}){let[u,d]=(0,j.useState)(`idle`),[h,g]=(0,j.useState)(null),[_,v]=(0,j.useState)(`luma`),[y,b]=(0,j.useState)(`rgb`),[x,ee]=(0,j.useState)(()=>pe()),S=i(e=>e.isPlaying),C=p(e=>e.captureFrameImageData),w=p(e=>e.captureFrame),T=t&&n===`stack`,E=e=>!T||x===e,D=E(`waveform`),O=t&&E(`parade`),k=E(`vectorscope`),A=t&&E(`histogram`),M=(0,j.useRef)(null),N=(0,j.useRef)(null),I=(0,j.useRef)(null),L=(0,j.useRef)(null),R=(0,j.useRef)(null),z=(0,j.useRef)(null),U=(0,j.useRef)(null),W=(0,j.useRef)(null),G=(0,j.useRef)(null),ve=(0,j.useRef)(new Map),Y=(0,j.useRef)(!1),ye=(0,j.useRef)(!1),X=(0,j.useRef)(!1),be=(0,j.useRef)(null),xe=(0,j.useRef)(0),Z=(0,j.useRef)(S);Z.current=S;let Se=(0,j.useRef)(_);Se.current=_;let Ce=(0,j.useRef)(y);Ce.current=y,(0,j.useEffect)(()=>{try{localStorage.setItem(le,x)}catch{}},[x]),J(M,R,void 0,D),J(N,z,ue,O),J(L,W,void 0,A),J(I,U,1,k),(0,j.useEffect)(()=>{if(!e)return;let t=!1,n=ve.current;return g(null),G.current?.destroy(),G.current=null,n.clear(),te.create().then(e=>{if(t){e?.destroy();return}e?(G.current=e,g(!0)):g(!1)}),()=>{t=!0,G.current?.destroy(),G.current=null,n.clear()}},[e]);let Q=(0,j.useCallback)(e=>{if(!e)return null;let t=G.current;if(!t||e.width<2||e.height<2)return null;let n=ve.current,r=n.get(e);if(r&&r.width===e.width&&r.height===e.height)return r.ctx;for(let e of n.keys())e.isConnected||n.delete(e);let i=t.configureCanvas(e)??void 0;return i&&n.set(e,{ctx:i,width:e.width,height:e.height}),i??null},[]);(0,j.useEffect)(()=>{if(h!==!0||!e)return;let t=G.current;if(!t)return;let n=!1,r=0,a=0,o=0;Y.current=!1;let s=e=>{n||(Y.current&&e-a>=ce&&(Y.current=!1),e-r>=oe&&!Y.current&&(r=e,c()),requestAnimationFrame(s))},c=async()=>{if(Y.current||i.getState().previewFrame!==null)return;let e=++o;Y.current=!0,a=performance.now();let r=()=>n||o!==e,{kr:s,kb:c}=H(B);t.setMatrix(s,c),t.setRange(0,1);try{let e=p.getState().captureCanvasSource;if(e){let n=await e({fresh:Z.current,preferRenderedFrame:!0});n&&!r()?t.uploadFromCanvas(n):r()||await l(t,r)}else await l(t,r);if(r())return;let n=Q(M.current),i=[];n&&i.push({ctx:n,mode:fe[Se.current]});let a=Q(N.current);a&&i.push({ctx:a,mode:5});let o=Q(L.current);o&&t.renderHistogram(o,fe[Ce.current]),i.length>0&&t.renderWaveforms(i);let s=Q(I.current);s&&t.renderVectorscope(s),d(`live`)}catch{d(`error`)}finally{o===e&&(Y.current=!1)}},l=async(e,t)=>{let n=p.getState().captureFrameImageData;if(!n)return;let r=await n({width:Z.current?ie:ne,height:Z.current?ae:re,fresh:Z.current,preferRenderedFrame:!0});r&&!t?.()&&e.uploadFrame(r)};return requestAnimationFrame(s),()=>{n=!0}},[h,e,Q]);let we=(0,j.useCallback)(async(t=0)=>{if(!e||h!==!1||!C&&!w)return;let n=()=>{let e=i.getState();return r({currentFrame:e.currentFrame,currentFrameEpoch:e.currentFrameEpoch,previewFrame:e.previewFrame,previewFrameEpoch:e.previewFrameEpoch,isPlaying:e.isPlaying,displayedFrame:p.getState().displayedFrame})},a=n(),o=M.current,s=I.current;if(!o&&!s&&!N.current&&!L.current)return;let c=o?K(o,512,256,1920,1080):null,l=N.current?K(N.current,512,256,1920,1080):null,u=L.current?K(L.current,512,256,1920,1080):null,f=0;if(s){let e=K(s,256,256,1024,1024);f=Math.max(2,Math.min(e.width,e.height)),(s.width!==f||s.height!==f)&&(s.width=f,s.height=f)}let m=o?.getContext(`2d`)??null,g=N.current?.getContext(`2d`)??null,_=s?.getContext(`2d`)??null,v=L.current?.getContext(`2d`)??null;try{let e=S?ie:ne,r=S?ae:re,i=null;if(C&&(i=await C({width:e,height:r,fresh:S,preferRenderedFrame:!0})),!i&&w){let t=await w({width:e,height:r,format:`image/jpeg`,quality:S?.72:.85,fresh:S,preferRenderedFrame:!0});if(t){let n=new Image;n.src=t,await n.decode();let a=be.current;a||(a=document.createElement(`canvas`),be.current=a),(a.width!==e||a.height!==r)&&(a.width=e,a.height=r);let o=a.getContext(`2d`,{willReadFrequently:!0});if(!o)return;o.clearRect(0,0,e,r),o.drawImage(n,0,0,e,r),i=o.getImageData(0,0,e,r)}}if(!i){d(`idle`);return}if(n()!==a){t<1&&await we(t+1);return}m&&c&&me(i,m,B,V,c.width,c.height);let o=!S||xe.current%2==0;xe.current+=1,g&&l&&o&&he(i,g,V,l.width,l.height),_&&f>0&&_e(i,_,B,f),v&&u&&o&&ge(i,v,B,V,u.width,u.height),d(`live`)}catch{d(`error`)}},[C,w,e,h,S]),$=(0,j.useCallback)(async()=>{if(ye.current){X.current=!0;return}ye.current=!0;try{do X.current=!1,await we();while(X.current)}finally{ye.current=!1}},[we]);return(0,j.useEffect)(()=>{h!==!1||!e||$()},[h,e,D,O,k,A,$]),(0,j.useEffect)(()=>{if(h!==!1||!e||S)return;let t=null,n=()=>{t===null&&(t=requestAnimationFrame(()=>{t=null,$()}))};n();let a=(e,t)=>{e!==t&&n()},o=i.subscribe((e,t)=>{if(e.isPlaying||e.previewFrame!==null)return;if(t.previewFrame!==null){n();return}let i=r({currentFrame:e.currentFrame,currentFrameEpoch:e.currentFrameEpoch,previewFrame:e.previewFrame,previewFrameEpoch:e.previewFrameEpoch,isPlaying:e.isPlaying,displayedFrame:p.getState().displayedFrame}),o=r({currentFrame:t.currentFrame,currentFrameEpoch:t.currentFrameEpoch,previewFrame:t.previewFrame,previewFrameEpoch:t.previewFrameEpoch,isPlaying:t.isPlaying,displayedFrame:p.getState().displayedFrame});a(i,o)}),s=p.subscribe((e,t)=>{let n=i.getState();if(n.isPlaying||n.previewFrame!==null)return;let o=r({currentFrame:n.currentFrame,currentFrameEpoch:n.currentFrameEpoch,previewFrame:n.previewFrame,previewFrameEpoch:n.previewFrameEpoch,isPlaying:n.isPlaying,displayedFrame:e.displayedFrame}),s=r({currentFrame:n.currentFrame,currentFrameEpoch:n.currentFrameEpoch,previewFrame:n.previewFrame,previewFrameEpoch:n.previewFrameEpoch,isPlaying:n.isPlaying,displayedFrame:t.displayedFrame});a(o,s)});return()=>{o(),s(),t!==null&&cancelAnimationFrame(t),X.current=!1}},[h,e,S,$]),(0,j.useEffect)(()=>{if(h!==!1||!e||!S)return;let t=!1;return(async()=>{for(;!t;)await $(),await new Promise(e=>setTimeout(e,se))})(),()=>{t=!0}},[h,e,S,$]),e?(0,P.jsxs)(`div`,{className:o(t?`h-full rounded-md border border-border bg-background p-2`:`absolute bottom-3 right-3 z-20 rounded-md border border-border bg-background/95 backdrop-blur-sm shadow-lg p-2 pointer-events-none`),children:[(0,P.jsxs)(`div`,{className:`flex items-center justify-between mb-2`,children:[(0,P.jsxs)(`div`,{className:`flex items-center gap-2`,children:[(0,P.jsx)(`div`,{className:`text-[10px] uppercase tracking-wide text-muted-foreground`,children:`Scopes`}),T&&(0,P.jsxs)(a,{value:x,onValueChange:e=>ee(e),children:[(0,P.jsx)(s,{"aria-label":`Scope`,className:`h-5 w-[104px] gap-1 rounded border-border/70 px-1.5 py-0 text-[10px]`,children:(0,P.jsx)(l,{})}),(0,P.jsx)(f,{children:de.map(e=>(0,P.jsx)(c,{value:e.value,className:`text-xs`,children:e.label},e.value))})]})]}),(0,P.jsxs)(`div`,{className:`flex items-center gap-1 text-[10px] text-muted-foreground`,children:[(0,P.jsx)(m,{className:`w-3 h-3 ${u===`live`?`text-emerald-500`:u===`error`?`text-red-500`:``}`}),u===`live`?h?`gpu`:`cpu`:u===`error`?`err`:`idle`]})]}),t?n===`stack`?(0,P.jsxs)(`div`,{className:`h-[calc(100%-22px)] min-h-0 flex flex-col gap-2`,children:[D&&(0,P.jsxs)(`div`,{className:`flex min-h-0 flex-1 flex-col`,children:[(0,P.jsxs)(`div`,{className:`mb-1 flex items-center justify-between`,children:[(0,P.jsx)(`div`,{className:`text-[10px] text-muted-foreground`,children:`Waveform`}),h&&(0,P.jsx)(q,{mode:_,onChange:v})]}),(0,P.jsx)(F,{containerRef:R,kind:`waveform`,className:`min-h-0 flex-1`,children:(0,P.jsx)(`canvas`,{ref:M,className:`w-full h-full`})})]}),O&&(0,P.jsxs)(`div`,{className:`flex min-h-0 flex-1 flex-col`,children:[(0,P.jsx)(`div`,{className:`text-[10px] mb-1 text-muted-foreground`,children:`RGB Parade`}),(0,P.jsx)(F,{containerRef:z,kind:`parade`,className:`min-h-0 w-full aspect-[10/3]`,children:(0,P.jsx)(`canvas`,{ref:N,className:`w-full h-full`})})]}),k&&(0,P.jsxs)(`div`,{className:`flex min-h-0 min-w-0 flex-1 flex-col`,children:[(0,P.jsx)(`div`,{className:`text-[10px] mb-1 text-muted-foreground`,children:`Vectorscope`}),(0,P.jsx)(F,{containerRef:U,kind:`vectorscope`,className:`mx-auto flex min-h-0 min-w-0 w-full max-w-[420px] flex-1 items-center justify-center`,children:(0,P.jsx)(`canvas`,{ref:I,className:`max-w-full max-h-full aspect-square`})})]}),A&&(0,P.jsxs)(`div`,{className:`flex min-h-0 flex-1 flex-col`,children:[(0,P.jsxs)(`div`,{className:`mb-1 flex items-center justify-between`,children:[(0,P.jsx)(`div`,{className:`text-[10px] text-muted-foreground`,children:`Histogram`}),h&&(0,P.jsx)(q,{mode:y,onChange:b})]}),(0,P.jsx)(F,{containerRef:W,kind:`histogram`,className:`min-h-0 flex-1`,children:(0,P.jsx)(`canvas`,{ref:L,className:`w-full h-full`})})]})]}):(0,P.jsxs)(`div`,{className:`h-[calc(100%-22px)] min-h-0 flex gap-3`,children:[(0,P.jsxs)(`div`,{className:`min-w-0 flex-1 grid grid-cols-2 gap-3 auto-rows-fr`,children:[(0,P.jsxs)(`div`,{className:`flex min-h-0 flex-col`,children:[(0,P.jsxs)(`div`,{className:`flex items-center justify-between mb-1`,children:[(0,P.jsx)(`div`,{className:`text-[10px] text-muted-foreground`,children:`Waveform`}),h&&(0,P.jsx)(q,{mode:_,onChange:v})]}),(0,P.jsx)(F,{containerRef:R,kind:`waveform`,className:`flex-1 min-h-[160px]`,children:(0,P.jsx)(`canvas`,{ref:M,className:`w-full h-full`})})]}),(0,P.jsxs)(`div`,{className:`flex min-h-0 flex-col`,children:[(0,P.jsx)(`div`,{className:`text-[10px] mb-1 text-muted-foreground`,children:`RGB Parade`}),(0,P.jsx)(F,{containerRef:z,kind:`parade`,className:`w-full aspect-[10/3]`,children:(0,P.jsx)(`canvas`,{ref:N,className:`w-full h-full`})})]}),(0,P.jsxs)(`div`,{className:`col-span-2 flex min-h-0 flex-col`,children:[(0,P.jsxs)(`div`,{className:`flex items-center justify-between mb-1`,children:[(0,P.jsx)(`div`,{className:`text-[10px] text-muted-foreground`,children:`Histogram`}),h&&(0,P.jsx)(q,{mode:y,onChange:b})]}),(0,P.jsx)(F,{containerRef:W,kind:`histogram`,className:`flex-1 min-h-[160px]`,children:(0,P.jsx)(`canvas`,{ref:L,className:`w-full h-full`})})]})]}),(0,P.jsxs)(`div`,{className:`basis-[32%] min-w-[220px] max-w-[380px] flex min-h-0 flex-col`,children:[(0,P.jsx)(`div`,{className:`text-[10px] mb-1 text-muted-foreground`,children:`Vectorscope`}),(0,P.jsx)(F,{containerRef:U,kind:`vectorscope`,className:`flex flex-1 min-h-0 items-center justify-center`,children:(0,P.jsx)(`canvas`,{ref:I,className:`max-w-full max-h-full aspect-square`})})]})]}):(0,P.jsxs)(`div`,{className:`grid grid-cols-2 gap-2`,children:[(0,P.jsxs)(`div`,{children:[(0,P.jsxs)(`div`,{className:`flex items-center justify-between mb-1`,children:[(0,P.jsx)(`div`,{className:`text-[10px] text-muted-foreground`,children:`Waveform`}),h&&(0,P.jsx)(q,{mode:_,onChange:v})]}),(0,P.jsx)(F,{containerRef:R,kind:`waveform`,className:`w-[220px] h-[110px]`,children:(0,P.jsx)(`canvas`,{ref:M,className:`w-full h-full`})})]}),(0,P.jsxs)(`div`,{children:[(0,P.jsx)(`div`,{className:`text-[10px] mb-1 text-muted-foreground`,children:`Vectorscope`}),(0,P.jsx)(F,{containerRef:U,kind:`vectorscope`,className:`w-[160px] h-[160px]`,children:(0,P.jsx)(`canvas`,{ref:I,className:`w-full h-full`})})]})]})]}):null});function Y({onClose:e}){return(0,P.jsxs)(`div`,{className:`flex flex-1 flex-col min-h-0 min-w-0`,children:[(0,P.jsxs)(`div`,{className:`flex items-center justify-between border-b border-border px-3 shrink-0`,style:{height:u.previewSplitHeaderHeight},children:[(0,P.jsx)(`span`,{className:`text-xs text-muted-foreground truncate`,children:`Color Scopes`}),(0,P.jsx)(`button`,{onClick:e,className:`p-1 rounded hover:bg-muted transition-colors shrink-0`,"aria-label":`Close color scopes`,children:(0,P.jsx)(t,{className:`w-3.5 h-3.5 text-muted-foreground`})})]}),(0,P.jsx)(`div`,{className:`flex-1 min-h-0 overflow-hidden p-2 bg-background/70`,children:(0,P.jsx)(ve,{open:!0,embedded:!0,embeddedLayout:`stack`})})]})}export{Y as ColorScopesMonitor};