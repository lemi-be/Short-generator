import{$o as e,Ol as t,_s as n,bs as r,cs as i,es as a,fs as o,hs as s,is as c,ls as l,ms as u,ns as d,ps as f,rs as p,ss as m,ts as h,us as g,vs as _,xs as v,ys as y}from"./app-shell-DegOpAUD.js";var b=t(`WorkspaceV2Migrator`),x=`filmstrips`,S=`waveform-bin`,C=`preview-audio`,w=`proxies`,T=`thumbnail.meta.json`,E=`thumbnail.jpg`;async function D(e){let t=performance.now(),i={ran:!1,fromVersion:null,toVersion:`2.0`,filmstripMediaMoved:0,waveformBinMoved:0,previewAudioMoved:0,proxiesMoved:0,thumbnailMetaRemoved:0,projectThumbnailsFixed:0,errors:[],durationMs:0},o=await n(e,[a]);if(!o||(i.fromVersion=o.schemaVersion,o.schemaVersion===`2.0`))return i.durationMs=performance.now()-t,i;i.ran=!0,b.info(`Migrating workspace ${o.schemaVersion} → 2.0`);let s=await O(e);try{i.filmstripMediaMoved=await k(e,i.errors)}catch(e){i.errors.push(`filmstrips: ${L(e)}`)}try{i.waveformBinMoved=await A(e,i.errors)}catch(e){i.errors.push(`waveform-bin: ${L(e)}`)}try{i.previewAudioMoved=await j(e,i.errors)}catch(e){i.errors.push(`preview-audio: ${L(e)}`)}try{i.proxiesMoved=await M(e,i.errors)}catch(e){i.errors.push(`proxies: ${L(e)}`)}try{i.thumbnailMetaRemoved=await N(e,i.errors)}catch(e){i.errors.push(`thumbnail-meta: ${L(e)}`)}try{i.projectThumbnailsFixed=await P(e,s,i.errors)}catch(e){i.errors.push(`project-thumbnails: ${L(e)}`)}if(i.errors.length===0){let t={...o,schemaVersion:`2.0`};await r(e,[a],t),b.info(`Workspace migrated to v2`,i)}else b.warn(`Workspace migration completed with errors; marker left at v1 for retry`,{errorCount:i.errors.length});return i.durationMs=performance.now()-t,i}async function O(e){let t=await u(e,[d]),n=new Set;for(let e of t)e.kind===`directory`&&n.add(e.name);return n}async function k(e,t){let n=await u(e,[x]),r=0;for(let i of n){if(i.kind!==`directory`)continue;let n=i.name;try{await v(`migrate-v2:filmstrip:${n}`,async()=>{let t=await u(e,[x,n]);for(let r of t){if(r.kind!==`file`)continue;let t=await s(e,[x,n,r.name]);t&&await y(e,[...c(n),r.name],t)}await _(e,[x,n],{recursive:!0})}),r++}catch(e){t.push(`filmstrip ${n}: ${L(e)}`)}}return r>0&&await F(e,x),r}async function A(e,t){let n=await u(e,[S]),r=0;for(let i of n){if(i.kind!==`file`||!i.name.endsWith(`.bin`))continue;let n=i.name.slice(0,-4);try{await v(`migrate-v2:waveform-bin:${n}`,async()=>{let t=await s(e,[S,i.name]);t&&(await y(e,o(n),t),await _(e,[S,i.name]))}),r++}catch(e){t.push(`waveform-bin ${n}: ${L(e)}`)}}return r>0&&await F(e,S),r}async function j(e,t){let n=await u(e,[C]),r=0;for(let a of n){if(a.kind!==`directory`)continue;let n=await u(e,[C,a.name]);for(let o of n){if(o.kind!==`directory`)continue;let n=await u(e,[C,a.name,o.name]);for(let c of n){if(c.kind!==`file`||!c.name.endsWith(`.wav`))continue;let n=c.name.slice(0,-4);try{await v(`migrate-v2:preview-audio:${n}`,async()=>{let t=await s(e,[C,a.name,o.name,c.name]);t&&(await y(e,i(n),t),await _(e,[C,a.name,o.name,c.name]))}),r++}catch(e){t.push(`preview-audio ${n}: ${L(e)}`)}}await I(e,[C,a.name,o.name])}await I(e,[C,a.name])}return r>0&&await F(e,C),r}async function M(e,t){let n=await u(e,[w]),r=0;for(let i of n){if(i.kind!==`directory`)continue;let n=i.name;try{await v(`migrate-v2:proxy:${n}`,async()=>{let t=await u(e,[w,n]);for(let r of t){if(r.kind!==`file`)continue;let t=await s(e,[w,n,r.name]);t&&await y(e,[...g(),n,r.name],t)}await _(e,[w,n],{recursive:!0})}),r++}catch(e){t.push(`proxy ${n}: ${L(e)}`)}}return r>0&&await F(e,w),r}async function N(e,t){let n=await u(e,[h]),r=0;for(let i of n){if(i.kind!==`directory`)continue;let n=i.name,a=[...m(n),T];try{if(!await f(e,a))continue;await _(e,a),r++}catch(e){t.push(`thumbnail.meta ${n}: ${L(e)}`)}}return r}async function P(e,t,n){let r=await u(e,[h]),i=0;for(let a of r){if(a.kind!==`directory`||!t.has(a.name))continue;let r=a.name;try{let t=await u(e,m(r));if(t.some(e=>e.kind===`file`&&e.name===`metadata.json`))continue;let n=await s(e,[...m(r),E]);if(!n||(await y(e,l(r),n),t.some(e=>!(e.kind===`file`&&e.name===E))))continue;await _(e,m(r),{recursive:!0}),i++}catch(e){n.push(`project-thumbnail ${r}: ${L(e)}`)}}return i}async function F(e,t){await I(e,[t])}async function I(e,t){if(!((await u(e,t)).length>0))try{await _(e,t)}catch(e){b.debug(`removeDirIfEmpty skipped`,{segments:t,error:e})}}function L(e){return e instanceof Error?e.message:String(e)}var R=`# FreeCut Workspace

This folder is your FreeCut project workspace - the app's source of truth
for everything: projects, media metadata, thumbnails, waveforms, caches.

Everything here is **plain files** you can \`cat\`, \`grep\`, and diff with
normal tools. AI coding agents can read them directly without a browser.

## Layout

\`\`\`
./
|-- README.md                  <- this file
|-- .freecut-workspace.json    <- marker + schema version
|-- index.json                 <- fast project list
|-- projects/
|   \`-- <projectId>/
|       |-- project.json       <- timeline, settings, keyframes, markers, transitions
|       |-- thumbnail.jpg
|       \`-- media-links.json   <- which media this project uses
|-- media/
|   \`-- <mediaId>/
|       |-- metadata.json      <- codec, duration, resolution, etc.
|       |-- source.<ext>       <- inline source file
|       |-- source.link.json   <- OR a link descriptor to an external file
|       |-- thumbnail.jpg
|       \`-- cache/
|           |-- filmstrip/     <- timeline frame thumbnails (0.jpg, 1.jpg, ...)
|           |-- waveform/      <- audio peaks (binned binary + multi-res.bin)
|           |-- gif-frames/    <- pre-extracted GIF frames
|           |-- decoded-audio/ <- chunked PCM for preview playback
|           |-- preview-audio.wav  <- conformed WAV for non-browser codecs
|           \`-- ai/            <- transcripts, captions, scene cuts, ...
\`-- content/
    |-- <hash[0:2]>/<hash>/    <- content-addressable source dedup (reserved)
    |   |-- refs.json
    |   \`-- data.<ext>
    \`-- proxies/<proxyKey>/    <- shared proxies (keyed by content fingerprint)
        |-- proxy.mp4
        \`-- meta.json
\`\`\`

## Safe to edit?

Everything except media source bytes is safe to inspect. Editing
\`project.json\` externally works; FreeCut picks up changes on next load.

Binary caches (waveforms, decoded audio, filmstrips) are regeneratable -
delete them and the app will rebuild them on demand.

## Moving the workspace

You can move this folder to a new location - the app just needs you to
re-pick it via the "Reconnect" prompt on next launch.
`,z=t(`WorkspaceBootstrap`);async function B(e,t){let n=0;async function r(e){let t=[];for await(let n of e.values())t.push({name:n.name,kind:n.kind});for(let i of t){if(i.kind===`directory`){try{await r(await e.getDirectoryHandle(i.name,{create:!1}))}catch(e){z.debug(`sweepStrandedTmpFiles: subdir skipped`,{name:i.name,error:e})}continue}if(i.name.endsWith(`.tmp`))try{await e.removeEntry(i.name),n++}catch(e){z.debug(`sweepStrandedTmpFiles: remove failed`,{name:i.name,error:e})}}}for(let n of t)try{await r(await e.getDirectoryHandle(n,{create:!1}))}catch{}return n}var V=/^[hof]-/;async function H(e){let t=await u(e,g()),n=0;for(let r of t){if(r.kind!==`directory`||!V.test(r.name))continue;let t=r.name,i=t.slice(2),a=[...g(),t],o=[...g(),i];try{if(await f(e,o)){await _(e,a,{recursive:!0}),n++;continue}let r=await u(e,a),i=[],c=!0;for(let t of r){if(t.kind!==`file`)continue;let n=await s(e,[...a,t.name]).catch(()=>null);if(!n){c=!1;break}i.push({name:t.name,blob:n})}if(!c){z.warn(`stripProxyKeyPrefixes: aborting ${t} — unreadable file, leaving source intact`);continue}let l=!0,d=[];for(let n of i)try{await y(e,[...o,n.name],n.blob),d.push(n.name)}catch(e){z.warn(`stripProxyKeyPrefixes: write failed for ${t}/${n.name}`,e),l=!1;break}if(!l){for(let t of d)await _(e,[...o,t],{recursive:!1}).catch(()=>void 0);continue}await _(e,a,{recursive:!0}),n++}catch(e){z.warn(`stripProxyKeyPrefixes: failed to rename ${t}`,e)}}return n}async function U(t){if(!await f(t,[`README.md`]))try{await y(t,[p],R)}catch(e){z.warn(`Failed to write README.md`,e)}if(await f(t,[`.freecut-workspace.json`]))try{let e=await D(t);e.ran&&z.info(`Workspace migration finished`,{from:e.fromVersion,to:e.toVersion,filmstrips:e.filmstripMediaMoved,waveforms:e.waveformBinMoved,previewAudio:e.previewAudioMoved,proxies:e.proxiesMoved,thumbnailMetaRemoved:e.thumbnailMetaRemoved,projectThumbnailsFixed:e.projectThumbnailsFixed,errors:e.errors.length,durationMs:Math.round(e.durationMs)})}catch(e){z.warn(`Workspace migration failed`,e)}else{let e={schemaVersion:`2.0`,createdAt:Date.now()};try{await r(t,[a],e)}catch(e){z.warn(`Failed to write workspace marker`,e)}}try{let e=await H(t);e>0&&z.info(`Stripped source-type prefix from ${e} proxy folder(s)`)}catch(e){z.warn(`stripProxyKeyPrefixes failed`,e)}try{let n=await B(t,[d,h,e]);n>0&&z.info(`Swept ${n} stranded .tmp file(s) from prior crash`)}catch(e){z.warn(`sweepStrandedTmpFiles failed`,e)}}export{U as bootstrapWorkspace};