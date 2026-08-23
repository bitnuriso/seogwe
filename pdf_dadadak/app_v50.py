from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request, send_file, Response
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from werkzeug.utils import secure_filename

ROOT = Path.home() / "storage" / "shared" / "PDFCrop"
IN_DIR = ROOT / "in"
OUT_DIR = ROOT / "out"
IN_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024 * 1024

HTML = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>PDF 다다다닥</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif}*{box-sizing:border-box}
body{margin:0;background:#111;color:#eee}header,.toolbar{padding:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
header{position:sticky;top:0;z-index:10;background:#181818;border-bottom:1px solid #333}main{padding:12px}
input,button,select{font:inherit;padding:10px 12px;border-radius:10px;border:1px solid #444;background:#222;color:#eee}
input[type=text],input[type=password]{min-width:150px;flex:1}input[type=file]{width:100%}button{cursor:pointer}
button.primary{background:#f2f2f2;color:#111;font-weight:700}button:disabled,input:disabled,select:disabled{opacity:.45;cursor:default}
.row{display:flex;gap:8px;align-items:center;width:100%;flex-wrap:wrap}.small{width:80px;flex:0 0 auto}.meta,label{font-size:13px;color:#aaa}
details{width:100%;background:#202020;border:1px solid #333;border-radius:12px;padding:8px 10px}summary{cursor:pointer;font-weight:700}
#stage{position:relative;margin:auto;width:min(100%,900px);touch-action:pan-y;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;overflow:hidden}
#canvas{display:block;width:100%;height:auto;background:white}#shade{position:absolute;pointer-events:none;box-shadow:0 0 0 9999px rgba(0,0,0,.48);border:2px solid #ffda44}
.handle{position:absolute;width:28px;height:28px;border-radius:50%;background:#ffda44;border:2px solid #111;transform:translate(-50%,-50%);touch-action:none}
#status,#importStatus{padding:8px 0;min-height:22px;white-space:pre-wrap}.toolbar{position:sticky;bottom:0;z-index:10;background:#181818;border-top:1px solid #333}.toolbar button{flex:1;min-width:90px}

#stage.empty {
  display: none;
}
</style>
</head>
<body>
<header>
<div class="row"><strong>PDF 다다다닥</strong><span id="counter" class="meta">파일 0 / 0</span><span id="pageCounter" class="meta">페이지 0 / 0</span></div>
<details open><summary>PDF·압축파일 가져오기</summary>
<div class="row" style="margin-top:10px"><input id="archive" type="file" multiple accept="application/pdf,.pdf,.zip,.7z,.rar,.cbz,.cbr"></div>
<div class="row"><input id="archivePassword" type="password" placeholder="압축 암호(압축파일 공통)"><button id="extract">PDFCrop/in에 가져오기</button>
<button id="clearInput">in 폴더 비우기</button>
<button id="batchCurrent">
  현재 크롭으로 남은 파일 처리
</button>

<button id="stopBatch" disabled>
  일괄 처리 중지
</button>

<div id="batchStatus"></div>
</div>
<div id="importStatus" class="meta"></div></details>
<div class="row"><a href="/batch" target="_blank">PDF 일괄처리</a></div>
<div class="row">
<input id="title" type="text" placeholder="기본 제목" value="">
<input id="number" class="small" type="number" min="0" value="1">
<select id="digits"><option value="2">2자리</option><option value="3" selected>3자리</option><option value="4">4자리</option></select>
</div>
<div class="row">
<label><input id="useNumber" type="checkbox" checked> 뒤에 번호 붙이기</label>
<label><input id="keepCrop" type="checkbox" checked> 크롭 유지</label>
<label><input id="allPages" type="checkbox" checked> 전체 페이지 적용</label>
<label><input id="autoEachPage" type="checkbox"> 페이지 자동감지</label>
<label><input id="lockAutoWidth" type="checkbox"> 가로 고정(x)</label>
<label><input id="lockAutoHeight" type="checkbox"> 세로 고정(y)</label>
<label><input id="deleteSource" type="checkbox" checked> 저장 후 원본 삭제</label>
</div>
</header>
<main>
<div id="original" class="meta">in 폴더를 읽는 중…</div>
<div id="stage"><canvas id="canvas"></canvas><div id="shade"></div>
<div class="handle" data-corner="tl"></div><div class="handle" data-corner="tr"></div><div class="handle" data-corner="bl"></div><div class="handle" data-corner="br"></div></div>
<div id="status"></div>
</main>
<div class="toolbar"><button id="prev">이전</button><button id="deletePage">현재 페이지 삭제</button><button id="skip">건너뛰기</button><button id="save" class="primary">저장하고 다음</button></div>
<script type="module">
let pdfjsLib = null;
async function ensurePdfJs(){
  if(pdfjsLib) return pdfjsLib;
  try{
    pdfjsLib = await import("/pdfjs/pdf.min.mjs?v=4.10.38");
    pdfjsLib.GlobalWorkerOptions.workerSrc="/pdfjs/pdf.worker.min.mjs?v=4.10.38";
    return pdfjsLib;
  }catch(error){
    const message = `PDF.js 로딩 실패: ${error?.message || error}`;
    const status = document.getElementById("status") || document.getElementById("batchStatus");
    if(status) status.textContent = message;
    throw new Error(message);
  }
}

let files=[],index=0,crop={x0:.03,y0:.03,x1:.97,y1:.97},dragging=null,longPressTimer=null,longPressStart=null;
let pdfDocument=null,pageIndex=0,pageCount=0,pageCrops={};
let explicitPageCrops=new Set();
let lockedAutoX=null,lockedAutoY=null;
const LONG_PRESS_MS=550,MOVE_LIMIT=14,$=id=>document.getElementById(id),stage=$("stage"),canvas=$("canvas"),ctx=canvas.getContext("2d",{willReadFrequently:true}),shade=$("shade"),handles=[...document.querySelectorAll(".handle")];
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

function safeTitle(v){return v.replace(/[\\/:*?"<>|]+/g," ").replace(/\s+/g," ").trim()}
function titleFromFilename(filename){
  return filename.replace(/\.pdf$/i,"").split(/[\s_\-()[\]{}]+/).filter(part=>part.length>0&&!/\d/.test(part)&&/^[가-힣a-zA-Z]+$/.test(part)).join(" ").replace(/\s+/g," ").trim();
}
function outputName(){
  const title=safeTitle($("title").value)||"스캔본";
  if(!$("useNumber").checked)return `${title}.pdf`;
  const number=String(Math.max(0,Number($("number").value)||0)).padStart(Number($("digits").value),"0");
  return `${title}_${number}.pdf`;
}
function updateNumberControls(){const on=$("useNumber").checked;$("number").disabled=!on;$("digits").disabled=!on;if(files.length)$("status").textContent=`저장 이름: ${outputName()} · 사진을 꾹 누르면 자동 선택`;}
function renderCrop(){
  const w=stage.clientWidth,h=canvas.getBoundingClientRect().height;if(!w||!h)return;
  const l=crop.x0*w,t=crop.y0*h,r=crop.x1*w,b=crop.y1*h;
  Object.assign(shade.style,{left:`${l}px`,top:`${t}px`,right:`${w-r}px`,bottom:`${h-b}px`});
  const p={tl:[l,t],tr:[r,t],bl:[l,b],br:[r,b]};handles.forEach(el=>{const[x,y]=p[el.dataset.corner];el.style.left=`${x}px`;el.style.top=`${y}px`;});
}
function eventPoint(e){const r=stage.getBoundingClientRect(),h=canvas.getBoundingClientRect().height;return{x:clamp((e.clientX-r.left)/r.width,0,1),y:clamp((e.clientY-r.top)/h,0,1)}}
function cancelLongPress(){if(longPressTimer)clearTimeout(longPressTimer);longPressTimer=null;longPressStart=null;}
function autoDetectContent() {
  if (!canvas.width || !canvas.height) return false;

  const previousCrop = { ...crop };
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const { data, width, height } = image;

  /*
   * 단행본 스캔용 안전 우선 감지
   * - 연결 요소/사각형성 필터를 사용하지 않는다.
   * - 삽화, 말풍선, 끊어진 컷선 등 모든 전경을 최대한 보존한다.
   * - 행/열 전경 분포에서 가장자리의 소량 노이즈만 제거한다.
   */
  const pixel = (x, y) => {
    const i = (y * width + x) * 4;
    return [data[i], data[i + 1], data[i + 2]];
  };

  /* 모서리 한 점이 그림자일 수 있으므로 가장자리 전체를 샘플링한다. */
  const samples = [];
  const stride = Math.max(3, Math.floor(Math.min(width, height) / 220));
  const inset = Math.max(2, Math.floor(Math.min(width, height) * 0.008));

  for (let x = inset; x < width - inset; x += stride) {
    samples.push(pixel(x, inset));
    samples.push(pixel(x, height - 1 - inset));
  }
  for (let y = inset; y < height - inset; y += stride) {
    samples.push(pixel(inset, y));
    samples.push(pixel(width - 1 - inset, y));
  }

  if (!samples.length) return false;

  const percentile = (values, q) => {
    values.sort((a, b) => a - b);
    return values[Math.min(values.length - 1, Math.max(0, Math.floor((values.length - 1) * q)))];
  };

  /* 밝은 종이색을 잡기 위해 중앙값보다 약간 밝은 60백분위수를 쓴다. */
  const backgroundR = percentile(samples.map(v => v[0]), 0.60);
  const backgroundG = percentile(samples.map(v => v[1]), 0.60);
  const backgroundB = percentile(samples.map(v => v[2]), 0.60);
  const backgroundLuma = 0.2126 * backgroundR + 0.7152 * backgroundG + 0.0722 * backgroundB;

  /*
   * 삽화 여부는 채도(컬러 유무)가 아니라 흰 종이와의 거리로 판정한다.
   * 따라서 컬러 삽화뿐 아니라 검은색/회색 삽화도 같은 규칙을 탄다.
   * 일반 텍스트 페이지가 오인되지 않도록 비백색 픽셀 비율과 퍼짐을 함께 본다.
   */
  const illustrationStep = Math.max(2, Math.ceil(Math.max(width, height) / 500));
  let sampledIllustrationPixels = 0;
  let nonWhitePixels = 0;
  let minInkX = width;
  let minInkY = height;
  let maxInkX = -1;
  let maxInkY = -1;

  for (let y = 0; y < height; y += illustrationStep) {
    for (let x = 0; x < width; x += illustrationStep) {
      const i = (y * width + x) * 4;
      if (data[i + 3] < 20) continue;

      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const distanceFromWhite = Math.sqrt(
        (255 - r) * (255 - r) +
        (255 - g) * (255 - g) +
        (255 - b) * (255 - b)
      );
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;

      sampledIllustrationPixels++;

      /* 스캔 종이의 아주 옅은 누런색/회색은 흰 여백으로 취급한다. */
      if (distanceFromWhite >= 34 && luma <= 246) {
        nonWhitePixels++;
        minInkX = Math.min(minInkX, x);
        minInkY = Math.min(minInkY, y);
        maxInkX = Math.max(maxInkX, x);
        maxInkY = Math.max(maxInkY, y);
      }
    }
  }

  const nonWhiteRatio = nonWhitePixels / Math.max(1, sampledIllustrationPixels);
  const inkSpreadX = maxInkX >= minInkX
    ? (maxInkX - minInkX + illustrationStep) / width
    : 0;
  const inkSpreadY = maxInkY >= minInkY
    ? (maxInkY - minInkY + illustrationStep) / height
    : 0;

  /*
   * 삽화 판정은 두 갈래로 분리한다.
   * 1) 실제 색이 넓게 퍼진 컬러 삽화
   * 2) 검정/회색 면적이 매우 조밀한 흑백 삽화
   *
   * 단순히 비백색 픽셀이 14%만 넘어도 삽화로 보던 기존 조건은
   * 흰 배경 만화의 컷선·글자까지 삽화로 오인했다.
   */
  let chromaticPixels = 0;
  let chromaticMinX = width;
  let chromaticMinY = height;
  let chromaticMaxX = -1;
  let chromaticMaxY = -1;

  const tileColumns = 12;
  const tileRows = 16;
  const tileInk = new Uint32Array(tileColumns * tileRows);
  const tileSamples = new Uint32Array(tileColumns * tileRows);
  const illustrationRowInk = new Uint32Array(Math.ceil(height / illustrationStep));
  const illustrationColumnInk = new Uint32Array(Math.ceil(width / illustrationStep));

  for (let y = 0, sy = 0; y < height; y += illustrationStep, sy++) {
    for (let x = 0, sx = 0; x < width; x += illustrationStep, sx++) {
      const i = (y * width + x) * 4;
      if (data[i + 3] < 20) continue;

      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const maxChannel = Math.max(r, g, b);
      const minChannel = Math.min(r, g, b);
      const chroma = maxChannel - minChannel;
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      const distanceFromWhite = Math.sqrt(
        (255 - r) * (255 - r) +
        (255 - g) * (255 - g) +
        (255 - b) * (255 - b)
      );

      const tx = Math.min(tileColumns - 1, Math.floor(x / width * tileColumns));
      const ty = Math.min(tileRows - 1, Math.floor(y / height * tileRows));
      const tileIndex = ty * tileColumns + tx;
      tileSamples[tileIndex]++;

      const isInk = distanceFromWhite >= 34 && luma <= 246;
      if (isInk) {
        tileInk[tileIndex]++;
        illustrationRowInk[sy]++;
        illustrationColumnInk[sx]++;
      }

      if (chroma >= 24 && luma >= 18 && luma <= 242) {
        chromaticPixels++;
        chromaticMinX = Math.min(chromaticMinX, x);
        chromaticMinY = Math.min(chromaticMinY, y);
        chromaticMaxX = Math.max(chromaticMaxX, x);
        chromaticMaxY = Math.max(chromaticMaxY, y);
      }
    }
  }

  const chromaticRatio = chromaticPixels / Math.max(1, sampledIllustrationPixels);
  const chromaticSpreadX = chromaticMaxX >= chromaticMinX
    ? (chromaticMaxX - chromaticMinX + illustrationStep) / width
    : 0;
  const chromaticSpreadY = chromaticMaxY >= chromaticMinY
    ? (chromaticMaxY - chromaticMinY + illustrationStep) / height
    : 0;

  let denseTiles = 0;
  let validTiles = 0;
  for (let i = 0; i < tileSamples.length; i++) {
    if (!tileSamples[i]) continue;
    validTiles++;
    if (tileInk[i] / tileSamples[i] >= 0.22) denseTiles++;
  }
  const denseTileRatio = denseTiles / Math.max(1, validTiles);

  const sampledColumnsCount = Math.max(1, illustrationColumnInk.length);
  const sampledRowsCount = Math.max(1, illustrationRowInk.length);
  const activeRowRatio = Array.from(illustrationRowInk)
    .filter(value => value >= sampledColumnsCount * 0.14).length /
    sampledRowsCount;
  const activeColumnRatio = Array.from(illustrationColumnInk)
    .filter(value => value >= sampledRowsCount * 0.14).length /
    sampledColumnsCount;

  const isColorIllustration =
    chromaticRatio >= 0.055 &&
    chromaticSpreadX >= 0.50 &&
    chromaticSpreadY >= 0.50;

  const isDenseGrayscaleIllustration =
    nonWhiteRatio >= 0.28 &&
    inkSpreadX >= 0.65 &&
    inkSpreadY >= 0.65 &&
    denseTileRatio >= 0.48 &&
    activeRowRatio >= 0.55 &&
    activeColumnRatio >= 0.55;

  let isIllustration =
    isColorIllustration || isDenseGrayscaleIllustration;

  const step = Math.max(2, Math.ceil(Math.max(width, height) / 620));
  const gridWidth = Math.ceil(width / step);
  const gridHeight = Math.ceil(height / step);
  const mask = new Uint8Array(gridWidth * gridHeight);

  /*
   * 컬러 차이와 명도 차이를 함께 사용한다.
   * 삽화의 옅은 회색/색조도 잡도록 v4보다 훨씬 관대하게 둔다.
   */
  const colorThreshold = 22;
  const lumaThreshold = 16;

  for (let gy = 0; gy < gridHeight; gy++) {
    const y = Math.min(height - 1, gy * step + Math.floor(step / 2));
    for (let gx = 0; gx < gridWidth; gx++) {
      const x = Math.min(width - 1, gx * step + Math.floor(step / 2));
      const i = (y * width + x) * 4;
      if (data[i + 3] < 20) continue;

      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const dr = r - backgroundR;
      const dg = g - backgroundG;
      const db = b - backgroundB;
      const distance = Math.sqrt(dr * dr + dg * dg + db * db);
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;

      if (distance >= colorThreshold || backgroundLuma - luma >= lumaThreshold) {
        mask[gy * gridWidth + gx] = 1;
      }
    }
  }

  /* 고립된 단일 셀만 제거한다. 넓은 삽화나 끊어진 선은 절대 버리지 않는다. */
  const cleaned = new Uint8Array(mask.length);
  for (let gy = 0; gy < gridHeight; gy++) {
    for (let gx = 0; gx < gridWidth; gx++) {
      const index = gy * gridWidth + gx;
      if (!mask[index]) continue;

      let neighbors = 0;
      for (let oy = -1; oy <= 1; oy++) {
        const ny = gy + oy;
        if (ny < 0 || ny >= gridHeight) continue;
        for (let ox = -1; ox <= 1; ox++) {
          const nx = gx + ox;
          if (nx < 0 || nx >= gridWidth || (ox === 0 && oy === 0)) continue;
          neighbors += mask[ny * gridWidth + nx];
        }
      }
      if (neighbors >= 1) cleaned[index] = 1;
    }
  }

  /*
   * 최우선 전처리: 상단 메모/낙서를 다른 모든 판정보다 먼저 제거한다.
   * 여기서 cleaned 마스크 자체를 0으로 지우므로, 이후 삽화 판정·컷선 탐색·
   * 외곽 계산 어느 단계에서도 상단 메모가 다시 포함될 수 없다.
   */
  let topMarkRemoved = false;
  let contentStartRow = 0;

  {
    const preliminaryRows = new Uint32Array(gridHeight);
    for (let gy = 0; gy < gridHeight; gy++) {
      let count = 0;
      for (let gx = 0; gx < gridWidth; gx++) {
        count += cleaned[gy * gridWidth + gx];
      }
      preliminaryRows[gy] = count;
    }

    const smoothPreRows = new Float64Array(gridHeight);
    const radius = 2;
    for (let row = 0; row < gridHeight; row++) {
      let sum = 0;
      let weight = 0;
      for (let d = -radius; d <= radius; d++) {
        const target = row + d;
        if (target < 0 || target >= gridHeight) continue;
        const w = radius + 1 - Math.abs(d);
        sum += preliminaryRows[target] * w;
        weight += w;
      }
      smoothPreRows[row] = sum / Math.max(1, weight);
    }

    const minimumActive = Math.max(2, Math.floor(gridWidth * 0.004));
    const bridgeGap = Math.max(1, Math.floor(gridHeight * 0.004));
    const runs = [];
    let runStart = -1;
    let lastActive = -1;

    for (let row = 0; row < gridHeight; row++) {
      if (smoothPreRows[row] >= minimumActive) {
        if (runStart < 0) runStart = row;
        lastActive = row;
      } else if (runStart >= 0 && row - lastActive > bridgeGap) {
        runs.push({ start: runStart, end: lastActive });
        runStart = -1;
        lastActive = -1;
      }
    }
    if (runStart >= 0) runs.push({ start: runStart, end: lastActive });

    const runMass = run => {
      let mass = 0;
      for (let row = run.start; row <= run.end; row++) mass += smoothPreRows[row];
      return mass;
    };

    const totalMass = smoothPreRows.reduce((sum, value) => sum + value, 0);

    if (runs.length >= 2 && totalMass > 0) {
      const enriched = runs.map(run => ({
        ...run,
        height: run.end - run.start + 1,
        mass: runMass(run)
      }));

      /*
       * 단순 최대 질량 하나만 고르지 않는다.
       * 상단 후보 뒤에서 시작하면서, 충분한 질량과 높이를 가진 첫 본문 덩어리를 찾는다.
       * 이 방식은 페이지마다 가장 큰 컷 위치가 바뀌어도 메모 컷오프 순위가 뒤집히지 않는다.
       */
      let mainIndex = -1;
      for (let i = 1; i < enriched.length; i++) {
        const run = enriched[i];
        const massRatio = run.mass / totalMass;
        const heightRatio = run.height / gridHeight;
        if (massRatio >= 0.22 || heightRatio >= 0.16) {
          mainIndex = i;
          break;
        }
      }

      if (mainIndex > 0) {
        const mainRun = enriched[mainIndex];
        const candidates = enriched.slice(0, mainIndex);
        const candidateStart = candidates[0].start;
        const candidateEnd = candidates[candidates.length - 1].end;
        const candidateHeight = candidateEnd - candidateStart + 1;
        const candidateMass = candidates.reduce((sum, run) => sum + run.mass, 0);
        const detachedGap = mainRun.start - candidateEnd - 1;

        const startsNearTop = candidateStart <= gridHeight * 0.14;
        const staysInTopArea = candidateEnd <= gridHeight * 0.28;
        const smallHeight = candidateHeight <= gridHeight * 0.13;
        const lowMass = candidateMass <= totalMass * 0.12;
        const enoughGap = detachedGap >= Math.max(3, Math.floor(gridHeight * 0.010));

        if (startsNearTop && staysInTopArea && smallHeight && lowMass && enoughGap) {
          contentStartRow = mainRun.start;
          for (let row = 0; row < contentStartRow; row++) {
            const offset = row * gridWidth;
            cleaned.fill(0, offset, offset + gridWidth);
          }
          topMarkRemoved = true;
        }
      }
    }
  }

  /*
   * 2차 상단 메모 폴백.
   * 1차 run 분리가 실패했더라도 상단의 희박한 전경 뒤에
   * 저밀도 골짜기와 본문 밀도 상승이 이어지면 본문 시작으로 확정한다.
   */
  if (!topMarkRemoved) {
    const rowCounts = new Uint32Array(gridHeight);
    for (let gy = 0; gy < gridHeight; gy++) {
      let count = 0;
      for (let gx = 0; gx < gridWidth; gx++) count += cleaned[gy * gridWidth + gx];
      rowCounts[gy] = count;
    }
    const smooth = new Float64Array(gridHeight);
    for (let gy = 0; gy < gridHeight; gy++) {
      let sum = 0, weight = 0;
      for (let d = -2; d <= 2; d++) {
        const y = gy + d;
        if (y < 0 || y >= gridHeight) continue;
        const w = 3 - Math.abs(d);
        sum += rowCounts[y] * w;
        weight += w;
      }
      smooth[gy] = sum / Math.max(1, weight);
    }
    const searchEnd = Math.min(gridHeight - 1, Math.floor(gridHeight * 0.32));
    const quietThreshold = Math.max(1.5, gridWidth * 0.006);
    const bodyThreshold = Math.max(3, gridWidth * 0.025);
    const minQuietRun = Math.max(3, Math.floor(gridHeight * 0.012));
    const minBodyRun = Math.max(5, Math.floor(gridHeight * 0.028));
    let quietStart = -1;
    let fallbackStart = -1;
    for (let gy = 1; gy <= searchEnd; gy++) {
      if (smooth[gy] <= quietThreshold) {
        if (quietStart < 0) quietStart = gy;
        continue;
      }
      if (quietStart >= 0 && gy - quietStart >= minQuietRun) {
        let bodyRows = 0, bodyMass = 0;
        const bodyEnd = Math.min(gridHeight, gy + minBodyRun * 2);
        for (let y = gy; y < bodyEnd; y++) {
          bodyMass += smooth[y];
          if (smooth[y] >= bodyThreshold) bodyRows++;
        }
        let topMass = 0;
        for (let y = 0; y < quietStart; y++) topMass += smooth[y];
        const topHasInk = topMass >= Math.max(5, gridWidth * 0.10);
        const bodyIsStable = bodyRows >= minBodyRun && bodyMass >= bodyThreshold * minBodyRun;
        if (topHasInk && bodyIsStable && gy <= gridHeight * 0.30) {
          fallbackStart = gy;
          break;
        }
      }
      quietStart = -1;
    }
    if (fallbackStart > 0) {
      contentStartRow = fallbackStart;
      for (let row = 0; row < contentStartRow; row++) {
        const offset = row * gridWidth;
        cleaned.fill(0, offset, offset + gridWidth);
      }
      topMarkRemoved = true;
    }
  }

  /*
   * 삽화 판정도 상단 메모가 제거된 마스크만 기준으로 다시 계산한다.
   * 초기 RGB 샘플 판정이 흰 배경 만화를 삽화로 오인하더라도 여기서 교정된다.
   */
  {
    let remainingCells = 0;
    let inkCells = 0;
    let chromaticCells = 0;
    let activeRows = 0;
    let activeColumns = 0;
    const rowInk = new Uint32Array(gridHeight);
    const columnInk = new Uint32Array(gridWidth);

    for (let gy = contentStartRow; gy < gridHeight; gy++) {
      const y = Math.min(height - 1, gy * step + Math.floor(step / 2));
      for (let gx = 0; gx < gridWidth; gx++) {
        remainingCells++;
        if (!cleaned[gy * gridWidth + gx]) continue;
        inkCells++;
        rowInk[gy]++;
        columnInk[gx]++;

        const x = Math.min(width - 1, gx * step + Math.floor(step / 2));
        const i = (y * width + x) * 4;
        const r = data[i];
        const g = data[i + 1];
        const b = data[i + 2];
        const chroma = Math.max(r, g, b) - Math.min(r, g, b);
        const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        if (chroma >= 24 && luma >= 18 && luma <= 242) chromaticCells++;
      }
    }

    for (let gy = contentStartRow; gy < gridHeight; gy++) {
      if (rowInk[gy] >= gridWidth * 0.16) activeRows++;
    }
    for (let gx = 0; gx < gridWidth; gx++) {
      if (columnInk[gx] >= Math.max(1, (gridHeight - contentStartRow) * 0.16)) activeColumns++;
    }

    const inkRatio = inkCells / Math.max(1, remainingCells);
    const chromaticRatioAfterMemo = chromaticCells / Math.max(1, remainingCells);
    const activeRowRatioAfterMemo = activeRows / Math.max(1, gridHeight - contentStartRow);
    const activeColumnRatioAfterMemo = activeColumns / Math.max(1, gridWidth);

    const colorIllustrationAfterMemo =
      chromaticRatioAfterMemo >= 0.050 &&
      activeRowRatioAfterMemo >= 0.42 &&
      activeColumnRatioAfterMemo >= 0.42;

    const denseIllustrationAfterMemo =
      inkRatio >= 0.30 &&
      activeRowRatioAfterMemo >= 0.58 &&
      activeColumnRatioAfterMemo >= 0.58;

    isIllustration = colorIllustrationAfterMemo || denseIllustrationAfterMemo;
  }

  /*
   * 흰 배경 만화 페이지용 외곽 컷선 감지.
   * 글자처럼 짧고 끊긴 획은 무시하고, 길게 이어진 세로/가로 선만 찾는다.
   * 각 방향에서 첫 번째와 마지막 유효 선만 사용해 큰 사각형을 만든다.
   */
  const longestRunWithGaps = (readCell, length, allowedGap = 2) => {
    let best = 0;
    let current = 0;
    let gap = 0;

    for (let i = 0; i < length; i++) {
      if (readCell(i)) {
        current += gap + 1;
        gap = 0;
        if (current > best) best = current;
      } else if (current > 0 && gap < allowedGap) {
        gap++;
      } else {
        current = 0;
        gap = 0;
      }
    }
    return best;
  };

  const detectOuterPanelBounds = (startRow = 0) => {
    const verticalScores = new Uint32Array(gridWidth);
    const horizontalCandidates = [];
    const contentHeight = Math.max(1, gridHeight - startRow);
    const verticalMinimum = Math.max(12, Math.floor(contentHeight * 0.16));
    const horizontalMinimum = Math.max(12, Math.floor(gridWidth * 0.16));

    /*
     * 좌우 경계는 첫/마지막 검출 열을 그대로 쓰지 않는다.
     * 각 열의 세로 연속 길이를 계산한 뒤 인접 후보를 군집화하고,
     * 충분히 긴 선을 가진 안정된 군집끼리만 좌우 경계로 채택한다.
     */
    for (let gx = 0; gx < gridWidth; gx++) {
      verticalScores[gx] = longestRunWithGaps(gy => {
        if (gy < startRow) return false;
        for (let dx = -1; dx <= 1; dx++) {
          const nx = gx + dx;
          if (nx >= 0 && nx < gridWidth && cleaned[gy * gridWidth + nx]) return true;
        }
        return false;
      }, gridHeight, 2);
    }

    const verticalGroups = [];
    let groupStart = -1;
    let groupPeak = 0;
    let groupPeakX = -1;

    for (let gx = 0; gx <= gridWidth; gx++) {
      const active = gx < gridWidth && verticalScores[gx] >= verticalMinimum;
      if (active) {
        if (groupStart < 0) {
          groupStart = gx;
          groupPeak = verticalScores[gx];
          groupPeakX = gx;
        } else if (verticalScores[gx] > groupPeak) {
          groupPeak = verticalScores[gx];
          groupPeakX = gx;
        }
      } else if (groupStart >= 0) {
        const end = gx - 1;
        const width = end - groupStart + 1;
        const strongSingle = groupPeak >= contentHeight * 0.30;
        const stableBand = width >= 2 && groupPeak >= contentHeight * 0.22;
        if (strongSingle || stableBand) {
          verticalGroups.push({
            start: groupStart,
            end,
            peak: groupPeak,
            peakX: groupPeakX
          });
        }
        groupStart = -1;
        groupPeak = 0;
        groupPeakX = -1;
      }
    }

    /*
     * 비정형/들쭉날쭉한 컷을 위한 외곽 픽셀 투표 후보.
     * 각 유효 행에서 가장 왼쪽·오른쪽 전경 픽셀을 기록하고,
     * 여러 행에서 반복해서 나타난 좌표만 감지 방향과 평행한 세로선 후보로 승격한다.
     * 단일 글자나 먼지 한 점은 투표 수가 부족해 후보가 되지 않는다.
     */
    const leftEdgeVotes = new Uint32Array(gridWidth);
    const rightEdgeVotes = new Uint32Array(gridWidth);
    const rowEdgeSamples = [];
    let edgeVoteRows = 0;
    const minimumForegroundPerRow = Math.max(3, Math.floor(gridWidth * 0.012));

    for (let gy = startRow; gy < gridHeight; gy++) {
      let first = -1;
      let last = -1;
      let mass = 0;
      for (let gx = 0; gx < gridWidth; gx++) {
        if (!cleaned[gy * gridWidth + gx]) continue;
        if (first < 0) first = gx;
        last = gx;
        mass++;
      }
      if (mass < minimumForegroundPerRow || first < 0 || last <= first) continue;
      leftEdgeVotes[first]++;
      rightEdgeVotes[last]++;
      rowEdgeSamples.push({ y: gy, left: first, right: last, mass });
      edgeVoteRows++;
    }

    const smoothVotes = votes => {
      const result = new Uint32Array(votes.length);
      for (let x = 0; x < votes.length; x++) {
        let total = 0;
        for (let dx = -2; dx <= 2; dx++) {
          const nx = x + dx;
          if (nx >= 0 && nx < votes.length) total += votes[nx];
        }
        result[x] = total;
      }
      return result;
    };

    const smoothedLeftVotes = smoothVotes(leftEdgeVotes);
    const smoothedRightVotes = smoothVotes(rightEdgeVotes);
    const minimumEdgeVotes = Math.max(3, Math.floor(edgeVoteRows * 0.045));

    const appendSyntheticEdgeCandidates = (votes, side) => {
      let start = -1;
      let peak = 0;
      let peakX = -1;
      for (let x = 0; x <= gridWidth; x++) {
        const active = x < gridWidth && votes[x] >= minimumEdgeVotes;
        if (active) {
          if (start < 0) start = x;
          if (votes[x] > peak) {
            peak = votes[x];
            peakX = x;
          }
        } else if (start >= 0) {
          const end = x - 1;
          const lineX = side === "left" ? start : end;
          const alreadyCovered = verticalGroups.some(group =>
            lineX >= group.start - 2 && lineX <= group.end + 2
          );
          if (!alreadyCovered) {
            verticalGroups.push({
              start: lineX,
              end: lineX,
              peak: Math.max(verticalMinimum, peak),
              peakX,
              synthetic: true,
              side
            });
          }
          start = -1;
          peak = 0;
          peakX = -1;
        }
      }
    };

    if (edgeVoteRows >= 8) {
      appendSyntheticEdgeCandidates(smoothedLeftVotes, "left");
      appendSyntheticEdgeCandidates(smoothedRightVotes, "right");

      /*
       * 연속 행렬 기반 돌출 컷 후보.
       * 일부 컷만 좌우로 튀어나온 경우 전체 행 투표 비율은 낮지만,
       * 그 구간 안에서는 최좌/최우 픽셀이 여러 행에 걸쳐 연속적으로 나타난다.
       * 연속된 행에서 x 변화가 작게 유지되는 구간을 하나의 세로 경계로 보고
       * 감지 방향과 평행한 합성 후보선을 추가한다.
       */
      const appendContinuousEdgeRuns = side => {
        const xKey = side === "left" ? "left" : "right";
        const maxXDrift = Math.max(2, Math.floor(gridWidth * 0.018));
        const minimumRunRows = Math.max(4, Math.floor(contentHeight * 0.045));
        const minimumRunMass = Math.max(
          minimumForegroundPerRow * minimumRunRows,
          Math.floor(gridWidth * minimumRunRows * 0.022)
        );

        let run = [];
        const flushRun = () => {
          if (run.length < minimumRunRows) {
            run = [];
            return;
          }
          const totalMass = run.reduce((sum, sample) => sum + sample.mass, 0);
          if (totalMass < minimumRunMass) {
            run = [];
            return;
          }

          const xs = run.map(sample => sample[xKey]).sort((a, b) => a - b);
          /* 바깥쪽 픽셀을 지나도록 left는 낮은 분위수, right는 높은 분위수를 쓴다. */
          const quantileIndex = side === "left"
            ? Math.floor((xs.length - 1) * 0.15)
            : Math.ceil((xs.length - 1) * 0.85);
          const lineX = xs[Math.max(0, Math.min(xs.length - 1, quantileIndex))];
          const alreadyCovered = verticalGroups.some(group =>
            lineX >= group.start - 2 && lineX <= group.end + 2
          );
          if (!alreadyCovered) {
            verticalGroups.push({
              start: lineX,
              end: lineX,
              peak: Math.max(verticalMinimum, run.length),
              peakX: lineX,
              synthetic: true,
              continuous: true,
              side,
              runStart: run[0].y,
              runEnd: run[run.length - 1].y
            });
          }
          run = [];
        };

        for (const sample of rowEdgeSamples) {
          if (!run.length) {
            run.push(sample);
            continue;
          }
          const previous = run[run.length - 1];
          const consecutiveRow = sample.y <= previous.y + 2;
          const stableX = Math.abs(sample[xKey] - previous[xKey]) <= maxXDrift;
          if (consecutiveRow && stableX) {
            run.push(sample);
          } else {
            flushRun();
            run.push(sample);
          }
        }
        flushRun();
      };

      appendContinuousEdgeRuns("left");
      appendContinuousEdgeRuns("right");

      /*
       * x 고정형 세로 런 후보.
       * 행별 최외곽 좌표는 효과음/말풍선 때문에 흔들릴 수 있으므로,
       * 이번 후보는 반대로 한 x열에서 y만 연속적으로 변하는 전경을 찾는다.
       * 짧은 돌출 컷의 세로 모서리도 후보가 되도록 일반 16% 선 기준보다 낮은
       * 독립 임계값을 사용하되, 인접 열에서도 비슷한 런이 확인되는 경우만 채택한다.
       */
      const fixedXRunMinimum = Math.max(5, Math.floor(contentHeight * 0.035));
      const fixedXRuns = new Array(gridWidth).fill(null);

      const strongestVerticalRunAtX = gx => {
        let bestStart = -1;
        let bestEnd = -1;
        let bestLength = 0;
        let runStart = -1;
        let lastInk = -1;
        let gaps = 0;

        for (let gy = startRow; gy < gridHeight; gy++) {
          let ink = false;
          for (let dx = -1; dx <= 1; dx++) {
            const nx = gx + dx;
            if (nx >= 0 && nx < gridWidth && cleaned[gy * gridWidth + nx]) {
              ink = true;
              break;
            }
          }

          if (ink) {
            if (runStart < 0) runStart = gy;
            lastInk = gy;
            gaps = 0;
          } else if (runStart >= 0) {
            gaps++;
            if (gaps > 1) {
              const length = lastInk - runStart + 1;
              if (length > bestLength) {
                bestLength = length;
                bestStart = runStart;
                bestEnd = lastInk;
              }
              runStart = -1;
              lastInk = -1;
              gaps = 0;
            }
          }
        }

        if (runStart >= 0) {
          const length = lastInk - runStart + 1;
          if (length > bestLength) {
            bestLength = length;
            bestStart = runStart;
            bestEnd = lastInk;
          }
        }
        return { start: bestStart, end: bestEnd, length: bestLength };
      };

      for (let gx = 0; gx < gridWidth; gx++) {
        fixedXRuns[gx] = strongestVerticalRunAtX(gx);
      }

      const runOverlapRatio = (a, b) => {
        if (!a || !b || a.length <= 0 || b.length <= 0) return 0;
        const overlap = Math.max(0, Math.min(a.end, b.end) - Math.max(a.start, b.start) + 1);
        return overlap / Math.max(1, Math.min(a.length, b.length));
      };

      let fixedStart = -1;
      let fixedPeak = 0;
      let fixedPeakX = -1;
      const flushFixedGroup = endExclusive => {
        if (fixedStart < 0) return;
        const end = endExclusive - 1;
        const center = (fixedStart + end) / 2;
        const side = center < gridWidth / 2 ? "left" : "right";
        const lineX = side === "left" ? fixedStart : end;
        const alreadyCovered = verticalGroups.some(group =>
          lineX >= group.start - 1 && lineX <= group.end + 1
        );
        if (!alreadyCovered) {
          verticalGroups.push({
            start: lineX,
            end: lineX,
            peak: fixedPeak,
            peakX: fixedPeakX,
            synthetic: true,
            fixedXRun: true,
            side
          });
        }
        fixedStart = -1;
        fixedPeak = 0;
        fixedPeakX = -1;
      };

      for (let gx = 0; gx <= gridWidth; gx++) {
        let active = false;
        let run = null;
        if (gx < gridWidth) {
          run = fixedXRuns[gx];
          if (run.length >= fixedXRunMinimum) {
            const leftNeighbor = gx > 0 ? fixedXRuns[gx - 1] : null;
            const rightNeighbor = gx + 1 < gridWidth ? fixedXRuns[gx + 1] : null;
            const supportedLeft = leftNeighbor &&
              leftNeighbor.length >= fixedXRunMinimum * 0.75 &&
              runOverlapRatio(run, leftNeighbor) >= 0.55;
            const supportedRight = rightNeighbor &&
              rightNeighbor.length >= fixedXRunMinimum * 0.75 &&
              runOverlapRatio(run, rightNeighbor) >= 0.55;
            active = Boolean(supportedLeft || supportedRight);
          }
        }

        if (active) {
          if (fixedStart < 0) fixedStart = gx;
          if (run.length > fixedPeak) {
            fixedPeak = run.length;
            fixedPeakX = gx;
          }
        } else {
          flushFixedGroup(gx);
        }
      }

      verticalGroups.sort((a, b) => a.start - b.start || a.end - b.end);
    }

    for (let gy = startRow; gy < gridHeight; gy++) {
      const run = longestRunWithGaps(gx => {
        for (let dy = -1; dy <= 1; dy++) {
          const ny = gy + dy;
          if (ny >= 0 && ny < gridHeight && cleaned[ny * gridWidth + gx]) return true;
        }
        return false;
      }, gridWidth, 2);
      if (run >= horizontalMinimum) horizontalCandidates.push(gy);
    }

    if (verticalGroups.length < 2 || horizontalCandidates.length < 2) return null;

    /*
     * 좌우는 군집의 최고점이 아니라 실제 바깥 모서리를 사용한다.
     * 두꺼운 테두리에서는 peakX가 군집 안쪽으로 치우쳐 잘림을 만들 수 있다.
     * 또한 실제 컷이 페이지 폭 대부분을 차지할 수 있으므로 96% 상한은 두지 않는다.
     */
    let bestPair = null;
    for (let i = 0; i < verticalGroups.length - 1; i++) {
      for (let j = i + 1; j < verticalGroups.length; j++) {
        const leftGroup = verticalGroups[i];
        const rightGroup = verticalGroups[j];
        const leftEdge = leftGroup.start;
        const rightEdge = rightGroup.end;
        const span = rightEdge - leftEdge + 1;
        const widthRatio = span / gridWidth;
        if (widthRatio < 0.42) continue;

        const support = Math.min(leftGroup.peak, rightGroup.peak);
        const supportRatio = support / contentHeight;
        /* fixedXRun은 선택 후보가 아니라 선택 후 바깥 확장용 증거로만 사용한다.
         * 내부의 효과음/문자 세로획이 좌우 외곽선으로 승격되는 것을 막는다. */
        if (leftGroup.fixedXRun || rightGroup.fixedXRun) continue;
        const minimumSupportRatio = 0.16;
        if (supportRatio < minimumSupportRatio) continue;

        /* 바깥쪽 쌍을 우선하되, 너무 약한 선 한 쌍은 배제한다. */
        const coverageScore = widthRatio * 4.0;
        const supportScore = Math.min(1, supportRatio) * 1.5;
        const edgeBonus =
          ((gridWidth - 1 - rightEdge) + leftEdge) / gridWidth * -0.35;
        const directionalBonus =
          (leftGroup.synthetic && leftGroup.side === "left" ? 0.22 : 0) +
          (rightGroup.synthetic && rightGroup.side === "right" ? 0.22 : 0) +
          (leftGroup.fixedXRun && leftGroup.side === "left" ? 0.18 : 0) +
          (rightGroup.fixedXRun && rightGroup.side === "right" ? 0.18 : 0);
        const wrongSidePenalty =
          (leftGroup.synthetic && leftGroup.side === "right" ? 1.0 : 0) +
          (rightGroup.synthetic && rightGroup.side === "left" ? 1.0 : 0);
        const score = coverageScore + supportScore + edgeBonus + directionalBonus - wrongSidePenalty;

        if (!bestPair || score > bestPair.score) {
          bestPair = {
            left: leftEdge,
            right: rightEdge,
            score
          };
        }
      }
    }

    if (!bestPair) return null;

    let left = bestPair.left;
    let right = bestPair.right;
    const top = horizontalCandidates[0];
    const bottom = horizontalCandidates[horizontalCandidates.length - 1];

    const heightRatio = (bottom - top + 1) / gridHeight;
    if (heightRatio < 0.42) return null;

    /*
     * 안정적인 좌우 외곽선을 먼저 고른 뒤, 경계 밖으로 실제 연결된 전경만 확장한다.
     * 후보 페어링에 넣지 않으므로 내부 세로획이 경계를 안쪽으로 끌어당길 수 없다.
     */
    const visited = new Uint8Array(cleaned.length);
    const stack = [];
    const minComponentMass = Math.max(6, Math.floor(gridWidth * gridHeight * 0.00012));
    const maxBridgeGap = Math.max(1, Math.floor(gridWidth * 0.012));
    let expandedLeft = left;
    let expandedRight = right;

    for (let sy = top; sy <= bottom; sy++) {
      for (let sx = 0; sx < gridWidth; sx++) {
        const startIndex = sy * gridWidth + sx;
        if (!cleaned[startIndex] || visited[startIndex]) continue;

        visited[startIndex] = 1;
        stack.push(startIndex);
        let minX = sx, maxX = sx, minY = sy, maxY = sy, mass = 0;

        while (stack.length) {
          const index = stack.pop();
          const cy = Math.floor(index / gridWidth);
          const cx = index - cy * gridWidth;
          mass++;
          if (cx < minX) minX = cx;
          if (cx > maxX) maxX = cx;
          if (cy < minY) minY = cy;
          if (cy > maxY) maxY = cy;

          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              if (!dx && !dy) continue;
              const nx = cx + dx, ny = cy + dy;
              if (nx < 0 || nx >= gridWidth || ny < top || ny > bottom) continue;
              const ni = ny * gridWidth + nx;
              if (cleaned[ni] && !visited[ni]) {
                visited[ni] = 1;
                stack.push(ni);
              }
            }
          }
        }

        const componentHeight = maxY - minY + 1;
        const componentWidth = maxX - minX + 1;
        if (mass < minComponentMass || (componentHeight < 3 && componentWidth < 3)) continue;

        const touchesLeftBoundary = minX < left && maxX >= left - maxBridgeGap;
        const touchesRightBoundary = maxX > right && minX <= right + maxBridgeGap;
        if (touchesLeftBoundary) expandedLeft = Math.min(expandedLeft, minX);
        if (touchesRightBoundary) expandedRight = Math.max(expandedRight, maxX);
      }
    }

    left = expandedLeft;
    right = expandedRight;
    return { left, right, top, bottom };
  };

  let panelBounds = null;

  const rowCounts = new Uint32Array(gridHeight);
  const columnCounts = new Uint32Array(gridWidth);
  let foregroundCount = 0;

  for (let gy = 0; gy < gridHeight; gy++) {
    for (let gx = 0; gx < gridWidth; gx++) {
      if (!cleaned[gy * gridWidth + gx]) continue;
      rowCounts[gy]++;
      columnCounts[gx]++;
      foregroundCount++;
    }
  }

  if (foregroundCount < gridWidth * gridHeight * 0.0015) {
    $("status").textContent = "내용을 충분히 찾지 못해 이전 크롭을 유지했습니다.";
    crop = previousCrop;
    renderCrop();
    return false;
  }

  /* 작은 페이지 번호도 살리되, 한두 개 먼지 때문에 외곽이 늘어나지는 않게 한다. */
  const minRowCount = Math.max(2, Math.floor(gridWidth * 0.004));
  const minColumnCount = Math.max(2, Math.floor(gridHeight * 0.004));

  const smoothCounts = (counts, radius = 2) => {
    const result = new Float64Array(counts.length);
    for (let i = 0; i < counts.length; i++) {
      let sum = 0;
      let weight = 0;
      for (let d = -radius; d <= radius; d++) {
        const p = i + d;
        if (p < 0 || p >= counts.length) continue;
        const w = radius + 1 - Math.abs(d);
        sum += counts[p] * w;
        weight += w;
      }
      result[i] = sum / Math.max(1, weight);
    }
    return result;
  };

  const smoothedRows = smoothCounts(rowCounts, 2);
  const smoothedColumns = smoothCounts(columnCounts, 2);

  /* 상단 메모는 cleaned 마스크 생성 직후 이미 제거되었다. */

  /*
   * 상단 메모 제거가 끝난 뒤 외곽 컷선을 찾는다.
   * 이전 버전은 컷선을 먼저 계산해서, 메모 제거 결과가 panelBounds에 반영되지 않았다.
   */
  panelBounds = isIllustration
    ? null
    : detectOuterPanelBounds(contentStartRow);

  /*
   * 컷선 후보를 찾은 뒤에는 선 자체의 검출 열/행만 그대로 쓰지 않고,
   * 그 사각형 바로 주변에서 실제로 가장 바깥에 존재하는 전경 픽셀까지 미세 보정한다.
   * 무제한 극값을 쓰면 먼지 때문에 다시 폭주하므로, 각 방향 최대 2% 이내만 확장한다.
   * 최종 경계는 가장 바깥 픽셀을 지나는 수직/수평선이 된다.
   */
  const refinePanelBoundsToOuterPixels = bounds => {
    if (!bounds) return null;

    const haloX = Math.max(1, Math.floor(gridWidth * 0.008));
    const haloY = Math.max(1, Math.floor(gridHeight * 0.02));
    const scanLeft = Math.max(0, bounds.left - haloX);
    const scanRight = Math.min(gridWidth - 1, bounds.right + haloX);
    const scanTop = Math.max(contentStartRow, bounds.top - haloY);
    const scanBottom = Math.min(gridHeight - 1, bounds.bottom + haloY);

    let left = bounds.left;
    let right = bounds.right;
    let top = bounds.top;
    let bottom = bounds.bottom;
    let found = false;

    for (let gy = scanTop; gy <= scanBottom; gy++) {
      for (let gx = scanLeft; gx <= scanRight; gx++) {
        if (!cleaned[gy * gridWidth + gx]) continue;
        found = true;
        /* 좌우는 안정된 세로 경계 군집을 그대로 유지한다. */
        top = Math.min(top, gy);
        bottom = Math.max(bottom, gy);
      }
    }

    if (!found) return bounds;
    return { left, right, top, bottom };
  };

  panelBounds = refinePanelBoundsToOuterPixels(panelBounds);

  /*
   * 들쭉날쭉한 컷 배열 보정.
   * 기본 컷선 사각형 밖으로 튀어나온 전경을 연결 요소로 묶어 검사한다.
   * 먼지/글자 하나가 아니라 실제 컷 일부로 볼 수 있을 만큼 크거나 길고,
   * 기본 사각형과 가깝거나 한 축에서 충분히 겹치는 요소만 경계에 합친다.
   */
  const expandPanelBoundsForStaggeredPanels = bounds => {
    if (!bounds) return null;

    const visited = new Uint8Array(cleaned.length);
    const queue = new Int32Array(cleaned.length);
    const minMass = Math.max(10, Math.floor(gridWidth * gridHeight * 0.0018));
    const minSpanX = Math.max(4, Math.floor(gridWidth * 0.055));
    const minSpanY = Math.max(4, Math.floor(gridHeight * 0.055));
    const nearGapX = Math.max(1, Math.floor(gridWidth * 0.008));
    const nearGapY = Math.max(2, Math.floor(gridHeight * 0.018));

    let expanded = { ...bounds };
    let expandedAny = false;

    for (let sy = contentStartRow; sy < gridHeight; sy++) {
      for (let sx = 0; sx < gridWidth; sx++) {
        const startIndex = sy * gridWidth + sx;
        if (!cleaned[startIndex] || visited[startIndex]) continue;

        let head = 0;
        let tail = 0;
        queue[tail++] = startIndex;
        visited[startIndex] = 1;

        let mass = 0;
        let minX = sx;
        let maxX = sx;
        let minY = sy;
        let maxY = sy;

        while (head < tail) {
          const index = queue[head++];
          const y = Math.floor(index / gridWidth);
          const x = index - y * gridWidth;
          mass++;
          minX = Math.min(minX, x);
          maxX = Math.max(maxX, x);
          minY = Math.min(minY, y);
          maxY = Math.max(maxY, y);

          for (let oy = -1; oy <= 1; oy++) {
            const ny = y + oy;
            if (ny < contentStartRow || ny >= gridHeight) continue;
            for (let ox = -1; ox <= 1; ox++) {
              if (ox === 0 && oy === 0) continue;
              const nx = x + ox;
              if (nx < 0 || nx >= gridWidth) continue;
              const next = ny * gridWidth + nx;
              if (!cleaned[next] || visited[next]) continue;
              visited[next] = 1;
              queue[tail++] = next;
            }
          }
        }

        const outside =
          minX < bounds.left || maxX > bounds.right ||
          minY < bounds.top || maxY > bounds.bottom;
        if (!outside) continue;

        const spanX = maxX - minX + 1;
        const spanY = maxY - minY + 1;
        const overlapX = Math.max(0, Math.min(maxX, bounds.right) - Math.max(minX, bounds.left) + 1);
        const overlapY = Math.max(0, Math.min(maxY, bounds.bottom) - Math.max(minY, bounds.top) + 1);
        const gapX = minX > bounds.right
          ? minX - bounds.right - 1
          : bounds.left > maxX
            ? bounds.left - maxX - 1
            : 0;
        const gapY = minY > bounds.bottom
          ? minY - bounds.bottom - 1
          : bounds.top > maxY
            ? bounds.top - maxY - 1
            : 0;

        const substantial =
          mass >= minMass &&
          (spanX >= minSpanX || spanY >= minSpanY);
        const alignedWithPage =
          overlapX >= Math.min(spanX, Math.max(3, Math.floor(gridWidth * 0.04))) ||
          overlapY >= Math.min(spanY, Math.max(3, Math.floor(gridHeight * 0.04)));
        const nearMainBounds = gapX <= nearGapX && gapY <= nearGapY;

        if (!substantial || (!nearMainBounds && !alignedWithPage)) continue;

        /*
         * 상하 돌출은 기존대로 적극 반영한다.
         * 좌우 돌출은 실제 컷처럼 세로 길이가 충분하고 본문과 크게 겹치는 경우만 반영한다.
         * 작은 효과음·페이지 번호·먼지가 좌우 경계를 밀어내지 못하도록 최대 확장폭도 제한한다.
         */
        const boundsHeight = bounds.bottom - bounds.top + 1;
        const strongVerticalPanel =
          spanY >= Math.max(minSpanY, Math.floor(gridHeight * 0.12)) &&
          overlapY >= Math.max(4, Math.floor(Math.min(spanY, boundsHeight) * 0.35)) &&
          gapX <= nearGapX;
        const maxHorizontalExpansion = Math.max(2, Math.floor(gridWidth * 0.028));

        /*
         * 좌우는 여기서 확장하지 않는다.
         * 연결 요소 탐색의 minX/maxX를 경계로 직접 승격하면
         * 글자·효과음·노이즈가 한 덩어리로 연결된 페이지에서 폭주한다.
         */
        void strongVerticalPanel;
        void maxHorizontalExpansion;

        expanded.top = Math.min(expanded.top, minY);
        expanded.bottom = Math.max(expanded.bottom, maxY);
        expandedAny = true;
      }
    }

    if (expandedAny) staggeredPanelExpanded = true;
    return expanded;
  };

  let staggeredPanelExpanded = false;
  panelBounds = expandPanelBoundsForStaggeredPanels(panelBounds);

  /* 상하 경계 전용 복구: 좌우는 유지하고 y방향 연속 전경만 반영한다. */
  const rescueVerticalEdges = bounds => {
    if (!bounds) return bounds;
    const xPad = Math.max(1, Math.floor(gridWidth * 0.012));
    const scanLeft = Math.max(0, bounds.left - xPad);
    const scanRight = Math.min(gridWidth - 1, bounds.right + xPad);
    const minRowInk = Math.max(2, Math.floor((scanRight - scanLeft + 1) * 0.012));
    const maxGap = Math.max(1, Math.floor(gridHeight * 0.004));
    const searchDistance = Math.max(3, Math.floor(gridHeight * 0.055));
    const rowInk = gy => {
      let count = 0;
      for (let gx = scanLeft; gx <= scanRight; gx++) count += cleaned[gy * gridWidth + gx];
      return count;
    };
    let rescuedTop = bounds.top, gap = 0;
    for (let gy = bounds.top - 1; gy >= Math.max(contentStartRow, bounds.top - searchDistance); gy--) {
      if (rowInk(gy) >= minRowInk) { rescuedTop = gy; gap = 0; }
      else if (++gap > maxGap) break;
    }
    let rescuedBottom = bounds.bottom;
    gap = 0;
    for (let gy = bounds.bottom + 1; gy <= Math.min(gridHeight - 1, bounds.bottom + searchDistance); gy++) {
      if (rowInk(gy) >= minRowInk) { rescuedBottom = gy; gap = 0; }
      else if (++gap > maxGap) break;
    }
    if (rescuedTop < bounds.top || rescuedBottom > bounds.bottom) staggeredPanelExpanded = true;
    return { ...bounds, top: rescuedTop, bottom: rescuedBottom };
  };
  panelBounds = rescueVerticalEdges(panelBounds);

  /*
   * 메모를 제외한 실제 콘텐츠의 열 분포를 다시 만든다.
   * 컷선 바깥에 말풍선/글자/효과음이 있으면 최종 외곽을 그 위치까지 확장한다.
   */
  const contentColumnCounts = new Uint32Array(gridWidth);
  for (let gy = contentStartRow; gy < gridHeight; gy++) {
    for (let gx = 0; gx < gridWidth; gx++) {
      if (cleaned[gy * gridWidth + gx]) contentColumnCounts[gx]++;
    }
  }
  const contentSmoothedColumns = smoothCounts(contentColumnCounts, 2);

  /*
   * 경계 계산은 검증된 단일 경로를 유지한다.
   * 삽화도 동일한 감지 결과를 사용하고, 차이는 최종 margin만 0으로 둔다.
   */
  const findBounds = (counts, minimum, edgeTrimRatio = 0.006) => {
    const active = [];
    let total = 0;
    for (let i = 0; i < counts.length; i++) {
      const value = counts[i] >= minimum ? counts[i] : 0;
      active.push(value);
      total += value;
    }
    if (total <= 0) return null;

    const trim = total * edgeTrimRatio;
    let cumulative = 0;
    let start = 0;
    for (; start < active.length; start++) {
      cumulative += active[start];
      if (cumulative >= trim) break;
    }

    cumulative = 0;
    let end = active.length - 1;
    for (; end >= 0; end--) {
      cumulative += active[end];
      if (cumulative >= trim) break;
    }

    return start < end ? { start, end } : null;
  };

  const foregroundHorizontal = findBounds(
    contentSmoothedColumns,
    minColumnCount,
    0.004
  );
  const foregroundVertical = findBounds(
    smoothedRows,
    minRowCount,
    0.004
  );

  /*
   * 잘리기 쉬운 주변 콘텐츠 보호.
   * - 상단 좌/우 제목: 메모 제거 이후 남은 상단 모서리의 작은 텍스트 묶음
   * - 하단 좌/우 페이지 번호: 하단 모서리의 작은 숫자/문자 묶음
   * - 비정형 컷: 기본 외곽 밖으로 튀어나왔지만 본문에 가깝거나 충분히 큰 전경
   *
   * 단순 극값을 쓰지 않고 연결 요소를 묶어서 먼지와 고립 노이즈를 배제한다.
   */
  const collectPeripheralProtection = baseBounds => {
    const visited = new Uint8Array(cleaned.length);
    const queue = new Int32Array(cleaned.length);
    const components = [];

    for (let gy = contentStartRow; gy < gridHeight; gy++) {
      for (let gx = 0; gx < gridWidth; gx++) {
        const seed = gy * gridWidth + gx;
        if (!cleaned[seed] || visited[seed]) continue;

        let head = 0;
        let tail = 0;
        queue[tail++] = seed;
        visited[seed] = 1;
        let minX = gx, maxX = gx, minY = gy, maxY = gy, mass = 0;

        while (head < tail) {
          const current = queue[head++];
          const cy = Math.floor(current / gridWidth);
          const cx = current - cy * gridWidth;
          mass++;
          minX = Math.min(minX, cx);
          maxX = Math.max(maxX, cx);
          minY = Math.min(minY, cy);
          maxY = Math.max(maxY, cy);

          for (let oy = -1; oy <= 1; oy++) {
            const ny = cy + oy;
            if (ny < contentStartRow || ny >= gridHeight) continue;
            for (let ox = -1; ox <= 1; ox++) {
              const nx = cx + ox;
              if (nx < 0 || nx >= gridWidth || (ox === 0 && oy === 0)) continue;
              const next = ny * gridWidth + nx;
              if (cleaned[next] && !visited[next]) {
                visited[next] = 1;
                queue[tail++] = next;
              }
            }
          }
        }

        components.push({ minX, maxX, minY, maxY, mass });
      }
    }

    const protectedItems = [];
    const headerLimit = Math.max(contentStartRow + 1, Math.floor(gridHeight * 0.22));
    const footerStart = Math.floor(gridHeight * 0.82);
    const cornerWidth = Math.floor(gridWidth * 0.30);
    const minimumTextMass = Math.max(3, Math.floor(gridWidth * gridHeight * 0.000015));

    const headerLeft = [];
    const headerRight = [];
    const footerLeft = [];
    const footerRight = [];

    for (const component of components) {
      const componentWidth = component.maxX - component.minX + 1;
      const componentHeight = component.maxY - component.minY + 1;
      const validSmallText =
        component.mass >= minimumTextMass &&
        (componentWidth >= 2 || componentHeight >= 2) &&
        componentWidth <= gridWidth * 0.28 &&
        componentHeight <= gridHeight * 0.10;

      if (validSmallText && component.minY >= contentStartRow && component.maxY <= headerLimit) {
        if (component.maxX <= cornerWidth) headerLeft.push(component);
        if (component.minX >= gridWidth - cornerWidth) headerRight.push(component);
      }

      if (validSmallText && component.minY >= footerStart) {
        if (component.maxX <= cornerWidth) footerLeft.push(component);
        if (component.minX >= gridWidth - cornerWidth) footerRight.push(component);
      }

      if (baseBounds) {
        const outside =
          component.minX < baseBounds.left || component.maxX > baseBounds.right ||
          component.minY < baseBounds.top || component.maxY > baseBounds.bottom;
        if (!outside) continue;

        const dx = component.maxX < baseBounds.left
          ? baseBounds.left - component.maxX
          : component.minX > baseBounds.right
            ? component.minX - baseBounds.right
            : 0;
        const dy = component.maxY < baseBounds.top
          ? baseBounds.top - component.maxY
          : component.minY > baseBounds.bottom
            ? component.minY - baseBounds.bottom
            : 0;
        const closeToMain = dx <= gridWidth * 0.025 && dy <= gridHeight * 0.035;
        const substantial =
          component.mass >= Math.max(8, gridWidth * gridHeight * 0.00012) ||
          componentWidth >= gridWidth * 0.045 ||
          componentHeight >= gridHeight * 0.045;

        if (closeToMain && substantial) protectedItems.push(component);
      }
    }

    const addCornerGroup = group => {
      if (!group.length) return;
      const mass = group.reduce((sum, item) => sum + item.mass, 0);
      if (mass < minimumTextMass * 2) return;
      protectedItems.push({
        minX: Math.min(...group.map(item => item.minX)),
        maxX: Math.max(...group.map(item => item.maxX)),
        minY: Math.min(...group.map(item => item.minY)),
        maxY: Math.max(...group.map(item => item.maxY)),
        mass
      });
    };

    addCornerGroup(headerLeft);
    addCornerGroup(headerRight);
    addCornerGroup(footerLeft);
    addCornerGroup(footerRight);

    if (!protectedItems.length) return null;
    return {
      left: Math.min(...protectedItems.map(item => item.minX)),
      right: Math.max(...protectedItems.map(item => item.maxX)),
      top: Math.min(...protectedItems.map(item => item.minY)),
      bottom: Math.max(...protectedItems.map(item => item.maxY)),
      headerProtected: headerLeft.length + headerRight.length > 0,
      footerProtected: footerLeft.length + footerRight.length > 0
    };
  };

  /*
   * 컷선이 있으면 그것을 기본 사각형으로 쓰되,
   * 컷선 밖에서 유효한 글자/그림이 감지되면 가장 바깥쪽까지 확장한다.
   * 컷선이 없으면 기존 전경 분포 감지 결과를 그대로 사용한다.
   */
  /*
   * v23 안정화:
   * 주변 보호 요소로 좌우/우하단을 확장하던 로직을 제거한다.
   * - 컷선이 있으면 컷선 bounds만 사용
   * - 컷선이 없을 때만 기존 전경 bounds 사용
   * 제목/페이지 번호/비정형 컷은 이후 별도 축 제한 로직으로 다시 추가한다.
   */
  const horizontal = panelBounds
    ? { start: panelBounds.left, end: panelBounds.right }
    : foregroundHorizontal;

  const vertical = panelBounds
    ? { start: panelBounds.top, end: panelBounds.bottom }
    : foregroundVertical;

  if (!horizontal || !vertical) {
    $("status").textContent = "안정적인 외곽을 찾지 못해 이전 크롭을 유지했습니다.";
    crop = previousCrop;
    renderCrop();
    return false;
  }

  let x0 = horizontal.start / gridWidth;
  let x1 = (horizontal.end + 1) / gridWidth;
  let y0 = vertical.start / gridHeight;
  let y1 = (vertical.end + 1) / gridHeight;

  const detectedWidth = x1 - x0;
  const detectedHeight = y1 - y0;

  if (detectedWidth < 0.18 || detectedHeight < 0.18) {
    $("status").textContent = "감지 영역이 너무 작아 이전 크롭을 유지했습니다.";
    crop = previousCrop;
    renderCrop();
    return false;
  }

  /* 삽화는 메모 제거 후 판정된 실제 외곽에 맞닿게 추가 여백을 0으로 둔다. */
  const marginX = isIllustration
    ? 0
    : panelBounds
      ? 0.004
      : (detectedWidth > 0.90 ? 0.006 : 0.018);
  const marginY = isIllustration
    ? 0
    : panelBounds
      ? 0.004
      : (detectedHeight > 0.92 ? 0.006 : 0.013);

  x0 = clamp(x0 - marginX, 0, 1);
  x1 = clamp(x1 + marginX, 0, 1);
  y0 = clamp(y0 - marginY, 0, 1);
  y1 = clamp(y1 + marginY, 0, 1);

  /*
   * 축 고정은 크기 고정이 아니라 좌표 자체를 고정한다.
   * - 가로 위치(x) 고정: x0/x1은 잠근 값을 유지하고 y0/y1만 자동감지
   * - 세로 위치(y) 고정: y0/y1은 잠근 값을 유지하고 x0/x1만 자동감지
   */
  if ($("lockAutoWidth")?.checked) {
    const locked = lockedAutoX ?? { x0: previousCrop.x0, x1: previousCrop.x1 };
    x0 = locked.x0;
    x1 = locked.x1;
  }

  if ($("lockAutoHeight")?.checked) {
    const locked = lockedAutoY ?? { y0: previousCrop.y0, y1: previousCrop.y1 };
    y0 = locked.y0;
    y1 = locked.y1;
  }

  crop = {
    x0: clamp(x0, 0, 1),
    y0: clamp(y0, 0, 1),
    x1: clamp(x1, 0, 1),
    y1: clamp(y1, 0, 1)
  };

  renderCrop();
  const detectNotes = [];
  if (panelBounds) detectNotes.push("외곽 컷선 감지");
  if (staggeredPanelExpanded) detectNotes.push("돌출 컷 보정");
  if (topMarkRemoved) detectNotes.push("상단 낙서 제외");
  if ($("lockAutoWidth")?.checked) detectNotes.push("x축 고정");
  if ($("lockAutoHeight")?.checked) detectNotes.push("y축 고정");
  const detectNote = detectNotes.length ? ` · ${detectNotes.join(" · ")}` : "";
  $("status").textContent = isIllustration
    ? `삽화 외곽 자동 선택 · 마진 0${detectNote} · 저장 이름: ${outputName()}`
    : `단행본 외곽 자동 선택${detectNote} · 저장 이름: ${outputName()}`;
  return true;
}

handles.forEach(el=>{
  el.addEventListener("pointerdown",e=>{dragging=el.dataset.corner;cancelLongPress();el.setPointerCapture(e.pointerId);e.preventDefault()});
  el.addEventListener("pointermove",e=>{
    if(!dragging)return;
    const p=eventPoint(e),g=.01;
    const lockX=$("lockAutoWidth")?.checked;
    const lockY=$("lockAutoHeight")?.checked;

    /* 잠긴 축의 좌표는 수동 드래그로도 절대 바뀌지 않는다. */
    if(!lockX && dragging.includes("l"))crop.x0=clamp(p.x,0,crop.x1-g);
    if(!lockX && dragging.includes("r"))crop.x1=clamp(p.x,crop.x0+g,1);
    if(!lockY && dragging.includes("t"))crop.y0=clamp(p.y,0,crop.y1-g);
    if(!lockY && dragging.includes("b"))crop.y1=clamp(p.y,crop.y0+g,1);
    renderCrop();
  });
  el.addEventListener("pointerup",()=>dragging=null);el.addEventListener("pointercancel",()=>dragging=null);
});

$("lockAutoWidth").addEventListener("change", () => {
  if ($("lockAutoWidth").checked) {
    /* 가로/세로 고정은 동시에 사용할 수 없다. 마지막으로 누른 축이 우선한다. */
    $("lockAutoHeight").checked = false;
    lockedAutoY = null;
    lockedAutoX = { x0: crop.x0, x1: crop.x1 };
    $("status").textContent = `가로 좌표 x0/x1을 고정했습니다 · 세로 고정은 해제되었습니다 · 이제 위아래만 조정됩니다 · 저장 이름: ${outputName()}`;
  } else {
    lockedAutoX = null;
    $("status").textContent = `가로 좌표 고정을 해제했습니다 · 저장 이름: ${outputName()}`;
  }
});

$("lockAutoHeight").addEventListener("change", () => {
  if ($("lockAutoHeight").checked) {
    /* 가로/세로 고정은 동시에 사용할 수 없다. 마지막으로 누른 축이 우선한다. */
    $("lockAutoWidth").checked = false;
    lockedAutoX = null;
    lockedAutoY = { y0: crop.y0, y1: crop.y1 };
    $("status").textContent = `세로 좌표 y0/y1을 고정했습니다 · 가로 고정은 해제되었습니다 · 이제 좌우만 조정됩니다 · 저장 이름: ${outputName()}`;
  } else {
    lockedAutoY = null;
    $("status").textContent = `세로 좌표 고정을 해제했습니다 · 저장 이름: ${outputName()}`;
  }
});

stage.addEventListener("pointerdown",e=>{if(e.target.classList.contains("handle")||!files.length)return;longPressStart={x:e.clientX,y:e.clientY};longPressTimer=setTimeout(()=>{longPressTimer=null;autoDetectContent();navigator.vibrate?.(35)},LONG_PRESS_MS)});
stage.addEventListener("pointermove",e=>{if(!longPressTimer||!longPressStart)return;if(Math.hypot(e.clientX-longPressStart.x,e.clientY-longPressStart.y)>MOVE_LIMIT)cancelLongPress()});
stage.addEventListener("pointerup",cancelLongPress);stage.addEventListener("pointercancel",cancelLongPress);stage.addEventListener("pointerleave",cancelLongPress);stage.addEventListener("contextmenu",e=>e.preventDefault());window.addEventListener("resize",renderCrop);

async function drawPreview(resetDocument=false){
  if(!files.length)return;
  $("status").textContent="미리보기 불러오는 중…";
  if(resetDocument || !pdfDocument){
    await ensurePdfJs();
    const url=`/api/pdf?name=${encodeURIComponent(files[index])}&t=${Date.now()}`;
    pdfDocument=await pdfjsLib.getDocument(url).promise;
    pageCount=pdfDocument.numPages;
    pageIndex=clamp(pageIndex,0,Math.max(0,pageCount-1));
  }
  const page=await pdfDocument.getPage(pageIndex+1),base=page.getViewport({scale:1}),cssWidth=Math.min(window.innerWidth-24,900),dpr=Math.min(window.devicePixelRatio||1,2),viewport=page.getViewport({scale:(cssWidth/base.width)*dpr});
  canvas.width=Math.floor(viewport.width);canvas.height=Math.floor(viewport.height);canvas.style.width=`${viewport.width/dpr}px`;canvas.style.height=`${viewport.height/dpr}px`;
  await page.render({canvasContext:ctx,viewport}).promise;
  if(!$("allPages").checked && pageCrops[pageIndex] && explicitPageCrops.has(pageIndex)) crop={...pageCrops[pageIndex]};
  renderCrop();
  updateModeUI();
  const autoDetected =
    !$("allPages").checked &&
    $("autoEachPage").checked &&
    !pageCrops[pageIndex]
      ? autoDetectContent()
      : false;
  if (!autoDetected) {
    $("status").textContent=`저장 이름: ${outputName()} · 사진을 꾹 누르면 자동 선택`;
  }
}
function updateModeUI(){
  const perPage=!$("allPages").checked;
  $("pageCounter").textContent=files.length?`페이지 ${pageIndex+1} / ${pageCount}`:"페이지 0 / 0";
  $("prev").textContent=perPage?"이전 페이지":"이전 파일";
  $("skip").textContent=perPage?"다음 페이지":"건너뛰기";
  $("save").textContent=perPage&&pageIndex<pageCount-1?"이 페이지 확정":"저장하고 다음";
  $("autoEachPage").disabled=!perPage;
  $("batchCurrent").disabled=batchRunning||!files.length||perPage;
}
async function loadFiles(resetTitle=false){
  const r=await fetch("/api/files"),d=await r.json();files=d.files;index=clamp(index,0,Math.max(0,files.length-1));if(resetTitle){$("title").value="";$("number").value=1}if(files.length&&!$("title").value.trim())$("title").value=titleFromFilename(files[0])||"스캔본";showCurrent();
}

function resetToInitialScreen() {
  cancelLongPress();
  dragging = null;

  files = [];
  index = 0;

  crop = {
    x0: 0.03,
    y0: 0.03,
    x1: 0.97,
    y1: 0.97
  };

  ctx.clearRect(
    0,
    0,
    canvas.width,
    canvas.height
  );

  canvas.width = 0;
  canvas.height = 0;
  canvas.style.width = "";
  canvas.style.height = "";

  stage.classList.add("empty");

  $("counter").textContent = "파일 0 / 0";
  $("pageCounter").textContent = "페이지 0 / 0";
  $("original").textContent =
    "압축파일을 선택하거나 PDFCrop/in에 PDF를 넣으세요.";

  $("status").textContent = "";

  $("title").value = "";
  $("number").value = 1;

  $("save").disabled = true;
  $("skip").disabled = true;
  $("prev").disabled = true;
  $("deletePage").disabled = true;
}

function clearFinished(){
  pdfDocument=null;pageIndex=0;pageCount=0;pageCrops={};explicitPageCrops=new Set();
  stage.style.display = "none";
  shade.style.display = "none";

  handles.forEach(handle => {
    handle.style.display = "none";
  });
ctx.clearRect(0,0,canvas.width,canvas.height);canvas.width=0;canvas.height=0;crop={x0:.03,y0:.03,x1:.97,y1:.97};$("title").value="";$("number").value=1;$("original").textContent="작업이 모두 끝났습니다.";$("status").textContent="새 압축파일을 올리면 다시 시작됩니다.";}
function showCurrent(){
  const has=files.length>0&&index<files.length;$("counter").textContent=has?`파일 ${index+1} / ${files.length}`:"파일 0 / 0";$("save").disabled=$("skip").disabled=$("prev").disabled=$("deletePage").disabled=!has;
  if(has){
    stage.style.display = "";
    shade.style.display = "";

    handles.forEach(handle => {
      handle.style.display = "";
    });

    stage.classList.remove("empty");$("original").textContent=`원본: ${files[index]}`;pdfDocument=null;pageIndex=0;pageCount=0;pageCrops={};explicitPageCrops=new Set();drawPreview(true).catch(e=>$("status").textContent=`미리보기 실패: ${e.message}`)}else clearFinished();
}
["title","number","digits"].forEach(id=>$(id).addEventListener("input",()=>{if(files.length)$("status").textContent=`저장 이름: ${outputName()} · 사진을 꾹 누르면 자동 선택`}));
$("useNumber").addEventListener("change",updateNumberControls);
$("deletePage").onclick=async()=>{
  if(!files.length || pageCount < 1) return;

  const currentFile = files[index];
  const targetPage = pageIndex + 1;
  const confirmed = confirm(
    `${currentFile}의 ${targetPage}페이지를 삭제할까요?\n이 작업은 원본 PDF에 바로 반영됩니다.`
  );
  if(!confirmed) return;

  $("deletePage").disabled = true;
  $("status").textContent = `페이지 삭제 중… ${targetPage} / ${pageCount}`;

  try {
    const response = await fetch("/api/delete-page", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({name: currentFile, page_index: pageIndex})
    });
    const data = await response.json();
    if(!response.ok) throw new Error(data.error || "페이지 삭제 실패");

    if(data.file_deleted){
      files.splice(index, 1);
      if(index >= files.length) index = Math.max(0, files.length - 1);
      $("status").textContent = "마지막 페이지를 삭제해 원본 PDF도 삭제했습니다.";
      setTimeout(showCurrent, 150);
      return;
    }

    const oldPageIndex = pageIndex;
    const shifted = {};
    Object.entries(pageCrops).forEach(([key, value])=>{
      const oldIndex = Number(key);
      if(oldIndex < oldPageIndex) shifted[oldIndex] = value;
      else if(oldIndex > oldPageIndex) shifted[oldIndex - 1] = value;
    });
    pageCrops = shifted;
    explicitPageCrops = new Set(Array.from(explicitPageCrops).filter(i => i !== oldPageIndex).map(i => i > oldPageIndex ? i - 1 : i));

    pdfDocument = null;
    pageCount = data.pages_remaining;
    pageIndex = Math.min(oldPageIndex, pageCount - 1);
    $("status").textContent = `페이지 삭제 완료 · 남은 페이지 ${pageCount}개`;
    await drawPreview(true);
  } catch(error) {
    $("status").textContent = `삭제 실패: ${error.message}`;
  } finally {
    $("deletePage").disabled = !files.length;
  }
};
$("prev").onclick=()=>{
  if(!$("allPages").checked){
    pageCrops[pageIndex]={...crop};
    explicitPageCrops.add(pageIndex);
    if(pageIndex>0){pageIndex--;drawPreview().catch(e=>$("status").textContent=`미리보기 실패: ${e.message}`)}
    return;
  }
  if(index>0){index--;showCurrent()}
};
$("skip").onclick=()=>{
  if(!$("allPages").checked){
    pageCrops[pageIndex]={...crop};
    explicitPageCrops.add(pageIndex);
    if(pageIndex<pageCount-1){pageIndex++;if(!$("keepCrop").checked)crop={x0:.03,y0:.03,x1:.97,y1:.97};drawPreview().catch(e=>$("status").textContent=`미리보기 실패: ${e.message}`)}else $("status").textContent="마지막 페이지입니다.";
    return;
  }
  if(index<files.length-1){index++;if(!$("keepCrop").checked)crop={x0:.03,y0:.03,x1:.97,y1:.97};showCurrent()}else $("status").textContent="마지막 파일입니다.";
};
$("allPages").addEventListener("change",()=>{pageIndex=0;pageCrops={};explicitPageCrops=new Set();updateModeUI();if(files.length)drawPreview().catch(e=>$("status").textContent=`미리보기 실패: ${e.message}`)});
$("autoEachPage").addEventListener("change",()=>{
  if($("allPages").checked || !files.length) return;

  /*
   * 자동감지를 끄면 이전 페이지들에 남아 있던 자동감지 좌표를 버린다.
   * 현재 화면의 크롭만 유지해 다음 페이지에도 그대로 이어지게 한다.
   */
  const currentCrop = {...crop};
  pageCrops = {};
  explicitPageCrops = new Set();
  crop = currentCrop;

  if($("autoEachPage").checked){
    drawPreview().catch(e=>$("status").textContent=`자동 감지 실패: ${e.message}`);
  }else{
    renderCrop();
    $("status").textContent=`페이지 자동감지 해제 · 현재 크롭을 다음 페이지에도 유지합니다 · 저장 이름: ${outputName()}`;
  }
});
$("extract").onclick=async()=>{
  const selected=[...$("archive").files];if(!selected.length){$("importStatus").textContent="PDF 또는 압축파일을 선택하세요.";return}
  const fd=new FormData();selected.forEach(file=>fd.append("files",file));fd.append("password",$("archivePassword").value);$("extract").disabled=true;$("importStatus").textContent=`업로드·가져오는 중…\n${selected.map(f=>f.name).join("\n")}`;
  try{const r=await fetch("/api/import",{method:"POST",body:fd}),d=await r.json();if(!r.ok)throw new Error(d.error||"가져오기 실패");$("importStatus").textContent=`완료: PDF ${d.imported}개 추가${d.renamed?`, 중복명 ${d.renamed}개 변경`:""}${d.skipped?`, 건너뜀 ${d.skipped}개`:""}`;$("archive").value="";$("archivePassword").value="";index=0;await loadFiles(true)}catch(e){$("importStatus").textContent=`실패: ${e.message}`}finally{$("extract").disabled=false}
};
$("save").onclick=async()=>{
  if(!files.length)return;
  if(!$("allPages").checked){
    pageCrops[pageIndex]={...crop};
    explicitPageCrops.add(pageIndex);
    if(pageIndex<pageCount-1){pageIndex++;if(!$("keepCrop").checked)crop={x0:.03,y0:.03,x1:.97,y1:.97};await drawPreview();return;}
  }
  $("save").disabled=true;$("status").textContent="저장 중…";
  try{
    const payload={name:files[index],output_name:outputName(),crop,all_pages:$("allPages").checked,page_crops:$("allPages").checked?null:Array.from({length:pageCount},(_,i)=>pageCrops[i]||{x0:0,y0:0,x1:1,y1:1}),delete_source:$("deleteSource").checked};
    const r=await fetch("/api/crop",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}),d=await r.json();if(!r.ok)throw new Error(d.error||"알 수 없는 오류");if($("useNumber").checked)$("number").value=Number($("number").value||0)+1;files.splice(index,1);if(index>=files.length)index=Math.max(0,files.length-1);if(!$("keepCrop").checked)crop={x0:.03,y0:.03,x1:.97,y1:.97};$("status").textContent=`저장 완료: ${d.output_name}`;setTimeout(showCurrent,250)
  }catch(e){$("status").textContent=`실패: ${e.message}`;$("save").disabled=false}
};

$("clearInput").onclick = async () => {
  const confirmed = confirm(
    "PDFCrop/in 폴더의 PDF를 전부 삭제할까요?"
  );

  if (!confirmed) {
    return;
  }

  $("clearInput").disabled = true;

  $("importStatus").textContent =
    "in 폴더 비우는 중…";

  try {
    const response = await fetch(
      "/api/clear-input",
      {
        method: "POST"
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.error || "삭제 실패"
      );
    }

    $("importStatus").textContent =
      `완료: PDF ${data.deleted}개 삭제`;

    resetToInitialScreen();

    $("counter").textContent = "파일 0 / 0";
  $("pageCounter").textContent = "페이지 0 / 0";
    $("save").disabled = true;
    $("skip").disabled = true;
    $("prev").disabled = true;
  } catch (error) {
    $("importStatus").textContent =
      `실패: ${error.message}`;
  } finally {
    $("clearInput").disabled = false;
  }
};



function fileGroupName(filename) {
  return filename
    .replace(/\.pdf$/i, "")
    .replace(/[\s_-]*\d+[\s_-]*$/g, "")
    .trim()
    .toLocaleLowerCase();
}

let batchRunning = false;

function batchSleep(milliseconds) {
  return new Promise(resolve => {
    setTimeout(resolve, milliseconds);
  });
}

async function waitUntilSaveReady(timeout = 120000) {
  const startedAt = Date.now();

  while (batchRunning) {
    const saveButton = $("save");

    if (
      saveButton &&
      !saveButton.disabled &&
      canvas.width > 0 &&
      canvas.height > 0
    ) {
      return true;
    }

    if (Date.now() - startedAt > timeout) {
      throw new Error(
        "PDF 준비 시간이 너무 오래 걸립니다."
      );
    }

    await batchSleep(200);
  }

  return false;
}

async function waitUntilFileChanges(
  previousIndex,
  previousLength,
  timeout = 120000
) {
  const startedAt = Date.now();

  while (batchRunning) {
    const statusText =
      $("status")?.textContent || "";

    if (
      index !== previousIndex ||
      files.length !== previousLength ||
      files.length === 0 ||
      statusText.includes("모두 끝") ||
      statusText.includes("모두 완료")
    ) {
      return true;
    }

    if (Date.now() - startedAt > timeout) {
      throw new Error(
        "저장 완료를 확인하지 못했습니다."
      );
    }

    await batchSleep(200);
  }

  return false;
}

function setBatchControls(running) {
  batchRunning = running;

  $("batchCurrent").disabled = running;
  $("stopBatch").disabled = !running;

  if ($("clearInput")) {
    $("clearInput").disabled = running;
  }
}

$("batchCurrent").onclick = async () => {
  if (
    batchRunning ||
    !$("allPages").checked ||
    !Array.isArray(files) ||
    files.length === 0 ||
    index >= files.length
  ) {
    return;
  }

  const fixedCrop = {
    x0: crop.x0,
    y0: crop.y0,
    x1: crop.x1,
    y1: crop.y1
  };

  const fixedTitle =
    $("title").value.trim();

  const targetCount =
    files.length - index;

  const confirmed = confirm(
    `현재 크롭으로 남은 PDF ${targetCount}개를 처리할까요?`
  );

  if (!confirmed) {
    return;
  }

  batchRunning = true;

  $("batchCurrent").disabled = true;
  $("stopBatch").disabled = false;

  let completed = 0;

  try {
    while (
      batchRunning &&
      files.length > 0 &&
      index < files.length
    ) {
      $("batchStatus").textContent =
        `일괄 처리 중: ${completed + 1} / ${targetCount}`;

      /*
       * 현재 화면에 새 PDF가 완전히 표시될 때까지 기다린다.
       */
      const readyStartedAt = Date.now();

      while (
        batchRunning &&
        (
          canvas.width < 1 ||
          canvas.height < 1 ||
          $("save").disabled
        )
      ) {
        if (
          Date.now() - readyStartedAt >
          120000
        ) {
          throw new Error(
            "현재 PDF가 준비되지 않았습니다."
          );
        }

        await new Promise(resolve =>
          setTimeout(resolve, 200)
        );
      }

      if (!batchRunning) {
        break;
      }

      crop = {
        x0: fixedCrop.x0,
        y0: fixedCrop.y0,
        x1: fixedCrop.x1,
        y1: fixedCrop.y1
      };

      $("title").value = fixedTitle;
      renderCrop();

      /*
       * 현재 파일명을 기억한다.
       * 저장 후 이 파일이 목록에서 사라지거나
       * 다음 파일로 이동할 때까지 기다린다.
       */
      const currentFile = files[index];
      const previousLength = files.length;

      $("save").click();

      const saveStartedAt = Date.now();

      while (batchRunning) {
        const currentChanged =
          files[index] !== currentFile;

        const lengthChanged =
          files.length !== previousLength;

        const finished =
          files.length === 0 ||
          index >= files.length;

        if (
          currentChanged ||
          lengthChanged ||
          finished
        ) {
          break;
        }

        if (
          Date.now() - saveStartedAt >
          120000
        ) {
          throw new Error(
            `저장 완료 대기 시간 초과: ${currentFile}`
          );
        }

        await new Promise(resolve =>
          setTimeout(resolve, 200)
        );
      }

      if (!batchRunning) {
        break;
      }

      completed += 1;

      /*
       * 다음 PDF 렌더링과 버튼 상태 갱신 여유.
       */
      await new Promise(resolve =>
        setTimeout(resolve, 500)
      );
    }

    $("batchStatus").textContent =
      batchRunning
        ? `일괄 처리 완료: ${completed}개`
        : `일괄 처리 중지: ${completed}개 완료`;
  } catch (error) {
    console.error(error);

    $("batchStatus").textContent =
      `일괄 처리 실패: ${error.message}`;
  } finally {
    batchRunning = false;

    $("batchCurrent").disabled =
      !Array.isArray(files) ||
      files.length === 0;

    $("stopBatch").disabled = true;
  }
};$("stopBatch").onclick = () => {
  batchRunning = false;

  $("stopBatch").disabled = true;

  $("batchStatus").textContent =
    "현재 파일 처리 후 중지합니다.";
};

updateNumberControls();loadFiles();


function repairBatchButton() {
  const button =
    document.getElementById("batchCurrent");

  if (!button) {
    return;
  }

  const hasFiles =
    Array.isArray(files) &&
    files.length > 0 &&
    index < files.length;

  button.disabled =
    batchRunning || !hasFiles || !$("allPages").checked;

  button.style.pointerEvents = "auto";
  button.style.position = "relative";
  button.style.zIndex = "9999";
  button.style.opacity = "1";
}

window.addEventListener(
  "load",
  () => {
    repairBatchButton();

    setInterval(
      repairBatchButton,
      500
    );
  }
);


document.addEventListener(
  "click",
  event => {
    const button =
      event.target.closest("#batchCurrent");

    if (!button) {
      return;
    }

    const status =
      document.getElementById("batchStatus");

    if (status) {
      status.textContent =
        "일괄 처리 버튼 클릭 감지됨";
    }
  },
  true
);
</script>
</body>
</html>'''

BATCH_HTML = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PDF 일괄처리</title><style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;padding:16px}main{max-width:760px;margin:auto}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}input,button{font:inherit;padding:10px;border:1px solid #666;border-radius:8px;background:#222;color:#eee}button{background:#2563eb;border-color:#2563eb}button:disabled{opacity:.5}#status{white-space:pre-wrap;margin-top:14px}.box{border:1px solid #444;border-radius:12px;padding:14px}canvas{display:none}a{color:#9ec5ff}</style></head><body><main><h2>IN 폴더 전체 자동 크롭</h2><div class="box"><div class="row"><label>각 파일 뒤에서 <input id="skipLast" type="number" min="0" value="0" style="width:70px"> 페이지 삭제</label><button id="start" type="button">일괄처리</button><button id="stop" type="button" disabled style="background:#b91c1c;border-color:#b91c1c">일괄 중지</button></div><div id="status">대기 중</div></div><p><a href="/">기존 화면으로 돌아가기</a></p><canvas id="canvas"></canvas><div id="detectorStatus" hidden></div><input id="lockAutoWidth" type="checkbox" hidden><input id="lockAutoHeight" type="checkbox" hidden><script type="module">
let pdfjsLib = null;
async function ensurePdfJs(){
  if(pdfjsLib) return pdfjsLib;
  try{
    pdfjsLib = await import("/pdfjs/pdf.min.mjs?v=4.10.38");
    pdfjsLib.GlobalWorkerOptions.workerSrc="/pdfjs/pdf.worker.min.mjs?v=4.10.38";
    return pdfjsLib;
  }catch(error){
    const message = `PDF.js 로딩 실패: ${error?.message || error}`;
    const status = document.getElementById("status") || document.getElementById("batchStatus");
    if(status) status.textContent = message;
    throw new Error(message);
  }
}
const canvas=document.getElementById("canvas"),ctx=canvas.getContext("2d",{willReadFrequently:true});
const status=document.getElementById("status"),startButton=document.getElementById("start"),stopButton=document.getElementById("stop"),skipInput=document.getElementById("skipLast");
let stopRequested=false;
const yieldToBrowser=()=>new Promise(resolve=>setTimeout(resolve,0));
let crop={x0:.03,y0:.03,x1:.97,y1:.97},lockedAutoX=null,lockedAutoY=null;
const $=id=>id==="status"?document.getElementById("detectorStatus"):document.getElementById(id);
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
const outputName=()=>"batch.pdf";
/* 배치 화면에는 크롭 오버레이 UI가 없으므로 공용 감지 코드의 갱신 호출을 무시한다. */
globalThis.renderCrop = globalThis.renderCrop || (() => {});
function autoDetectContent() {
  if (!canvas.width || !canvas.height) return false;

  const previousCrop = { ...crop };
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const { data, width, height } = image;

  /*
   * 단행본 스캔용 안전 우선 감지
   * - 연결 요소/사각형성 필터를 사용하지 않는다.
   * - 삽화, 말풍선, 끊어진 컷선 등 모든 전경을 최대한 보존한다.
   * - 행/열 전경 분포에서 가장자리의 소량 노이즈만 제거한다.
   */
  const pixel = (x, y) => {
    const i = (y * width + x) * 4;
    return [data[i], data[i + 1], data[i + 2]];
  };

  /* 모서리 한 점이 그림자일 수 있으므로 가장자리 전체를 샘플링한다. */
  const samples = [];
  const stride = Math.max(3, Math.floor(Math.min(width, height) / 220));
  const inset = Math.max(2, Math.floor(Math.min(width, height) * 0.008));

  for (let x = inset; x < width - inset; x += stride) {
    samples.push(pixel(x, inset));
    samples.push(pixel(x, height - 1 - inset));
  }
  for (let y = inset; y < height - inset; y += stride) {
    samples.push(pixel(inset, y));
    samples.push(pixel(width - 1 - inset, y));
  }

  if (!samples.length) return false;

  const percentile = (values, q) => {
    values.sort((a, b) => a - b);
    return values[Math.min(values.length - 1, Math.max(0, Math.floor((values.length - 1) * q)))];
  };

  /* 밝은 종이색을 잡기 위해 중앙값보다 약간 밝은 60백분위수를 쓴다. */
  const backgroundR = percentile(samples.map(v => v[0]), 0.60);
  const backgroundG = percentile(samples.map(v => v[1]), 0.60);
  const backgroundB = percentile(samples.map(v => v[2]), 0.60);
  const backgroundLuma = 0.2126 * backgroundR + 0.7152 * backgroundG + 0.0722 * backgroundB;

  /*
   * 삽화 여부는 채도(컬러 유무)가 아니라 흰 종이와의 거리로 판정한다.
   * 따라서 컬러 삽화뿐 아니라 검은색/회색 삽화도 같은 규칙을 탄다.
   * 일반 텍스트 페이지가 오인되지 않도록 비백색 픽셀 비율과 퍼짐을 함께 본다.
   */
  const illustrationStep = Math.max(2, Math.ceil(Math.max(width, height) / 500));
  let sampledIllustrationPixels = 0;
  let nonWhitePixels = 0;
  let minInkX = width;
  let minInkY = height;
  let maxInkX = -1;
  let maxInkY = -1;

  for (let y = 0; y < height; y += illustrationStep) {
    for (let x = 0; x < width; x += illustrationStep) {
      const i = (y * width + x) * 4;
      if (data[i + 3] < 20) continue;

      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const distanceFromWhite = Math.sqrt(
        (255 - r) * (255 - r) +
        (255 - g) * (255 - g) +
        (255 - b) * (255 - b)
      );
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;

      sampledIllustrationPixels++;

      /* 스캔 종이의 아주 옅은 누런색/회색은 흰 여백으로 취급한다. */
      if (distanceFromWhite >= 34 && luma <= 246) {
        nonWhitePixels++;
        minInkX = Math.min(minInkX, x);
        minInkY = Math.min(minInkY, y);
        maxInkX = Math.max(maxInkX, x);
        maxInkY = Math.max(maxInkY, y);
      }
    }
  }

  const nonWhiteRatio = nonWhitePixels / Math.max(1, sampledIllustrationPixels);
  const inkSpreadX = maxInkX >= minInkX
    ? (maxInkX - minInkX + illustrationStep) / width
    : 0;
  const inkSpreadY = maxInkY >= minInkY
    ? (maxInkY - minInkY + illustrationStep) / height
    : 0;

  /*
   * 삽화 판정은 두 갈래로 분리한다.
   * 1) 실제 색이 넓게 퍼진 컬러 삽화
   * 2) 검정/회색 면적이 매우 조밀한 흑백 삽화
   *
   * 단순히 비백색 픽셀이 14%만 넘어도 삽화로 보던 기존 조건은
   * 흰 배경 만화의 컷선·글자까지 삽화로 오인했다.
   */
  let chromaticPixels = 0;
  let chromaticMinX = width;
  let chromaticMinY = height;
  let chromaticMaxX = -1;
  let chromaticMaxY = -1;

  const tileColumns = 12;
  const tileRows = 16;
  const tileInk = new Uint32Array(tileColumns * tileRows);
  const tileSamples = new Uint32Array(tileColumns * tileRows);
  const illustrationRowInk = new Uint32Array(Math.ceil(height / illustrationStep));
  const illustrationColumnInk = new Uint32Array(Math.ceil(width / illustrationStep));

  for (let y = 0, sy = 0; y < height; y += illustrationStep, sy++) {
    for (let x = 0, sx = 0; x < width; x += illustrationStep, sx++) {
      const i = (y * width + x) * 4;
      if (data[i + 3] < 20) continue;

      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const maxChannel = Math.max(r, g, b);
      const minChannel = Math.min(r, g, b);
      const chroma = maxChannel - minChannel;
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      const distanceFromWhite = Math.sqrt(
        (255 - r) * (255 - r) +
        (255 - g) * (255 - g) +
        (255 - b) * (255 - b)
      );

      const tx = Math.min(tileColumns - 1, Math.floor(x / width * tileColumns));
      const ty = Math.min(tileRows - 1, Math.floor(y / height * tileRows));
      const tileIndex = ty * tileColumns + tx;
      tileSamples[tileIndex]++;

      const isInk = distanceFromWhite >= 34 && luma <= 246;
      if (isInk) {
        tileInk[tileIndex]++;
        illustrationRowInk[sy]++;
        illustrationColumnInk[sx]++;
      }

      if (chroma >= 24 && luma >= 18 && luma <= 242) {
        chromaticPixels++;
        chromaticMinX = Math.min(chromaticMinX, x);
        chromaticMinY = Math.min(chromaticMinY, y);
        chromaticMaxX = Math.max(chromaticMaxX, x);
        chromaticMaxY = Math.max(chromaticMaxY, y);
      }
    }
  }

  const chromaticRatio = chromaticPixels / Math.max(1, sampledIllustrationPixels);
  const chromaticSpreadX = chromaticMaxX >= chromaticMinX
    ? (chromaticMaxX - chromaticMinX + illustrationStep) / width
    : 0;
  const chromaticSpreadY = chromaticMaxY >= chromaticMinY
    ? (chromaticMaxY - chromaticMinY + illustrationStep) / height
    : 0;

  let denseTiles = 0;
  let validTiles = 0;
  for (let i = 0; i < tileSamples.length; i++) {
    if (!tileSamples[i]) continue;
    validTiles++;
    if (tileInk[i] / tileSamples[i] >= 0.22) denseTiles++;
  }
  const denseTileRatio = denseTiles / Math.max(1, validTiles);

  const sampledColumnsCount = Math.max(1, illustrationColumnInk.length);
  const sampledRowsCount = Math.max(1, illustrationRowInk.length);
  const activeRowRatio = Array.from(illustrationRowInk)
    .filter(value => value >= sampledColumnsCount * 0.14).length /
    sampledRowsCount;
  const activeColumnRatio = Array.from(illustrationColumnInk)
    .filter(value => value >= sampledRowsCount * 0.14).length /
    sampledColumnsCount;

  const isColorIllustration =
    chromaticRatio >= 0.055 &&
    chromaticSpreadX >= 0.50 &&
    chromaticSpreadY >= 0.50;

  const isDenseGrayscaleIllustration =
    nonWhiteRatio >= 0.28 &&
    inkSpreadX >= 0.65 &&
    inkSpreadY >= 0.65 &&
    denseTileRatio >= 0.48 &&
    activeRowRatio >= 0.55 &&
    activeColumnRatio >= 0.55;

  let isIllustration =
    isColorIllustration || isDenseGrayscaleIllustration;

  const step = Math.max(2, Math.ceil(Math.max(width, height) / 620));
  const gridWidth = Math.ceil(width / step);
  const gridHeight = Math.ceil(height / step);
  const mask = new Uint8Array(gridWidth * gridHeight);

  /*
   * 컬러 차이와 명도 차이를 함께 사용한다.
   * 삽화의 옅은 회색/색조도 잡도록 v4보다 훨씬 관대하게 둔다.
   */
  const colorThreshold = 22;
  const lumaThreshold = 16;

  for (let gy = 0; gy < gridHeight; gy++) {
    const y = Math.min(height - 1, gy * step + Math.floor(step / 2));
    for (let gx = 0; gx < gridWidth; gx++) {
      const x = Math.min(width - 1, gx * step + Math.floor(step / 2));
      const i = (y * width + x) * 4;
      if (data[i + 3] < 20) continue;

      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const dr = r - backgroundR;
      const dg = g - backgroundG;
      const db = b - backgroundB;
      const distance = Math.sqrt(dr * dr + dg * dg + db * db);
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;

      if (distance >= colorThreshold || backgroundLuma - luma >= lumaThreshold) {
        mask[gy * gridWidth + gx] = 1;
      }
    }
  }

  /* 고립된 단일 셀만 제거한다. 넓은 삽화나 끊어진 선은 절대 버리지 않는다. */
  const cleaned = new Uint8Array(mask.length);
  for (let gy = 0; gy < gridHeight; gy++) {
    for (let gx = 0; gx < gridWidth; gx++) {
      const index = gy * gridWidth + gx;
      if (!mask[index]) continue;

      let neighbors = 0;
      for (let oy = -1; oy <= 1; oy++) {
        const ny = gy + oy;
        if (ny < 0 || ny >= gridHeight) continue;
        for (let ox = -1; ox <= 1; ox++) {
          const nx = gx + ox;
          if (nx < 0 || nx >= gridWidth || (ox === 0 && oy === 0)) continue;
          neighbors += mask[ny * gridWidth + nx];
        }
      }
      if (neighbors >= 1) cleaned[index] = 1;
    }
  }

  /*
   * 최우선 전처리: 상단 메모/낙서를 다른 모든 판정보다 먼저 제거한다.
   * 여기서 cleaned 마스크 자체를 0으로 지우므로, 이후 삽화 판정·컷선 탐색·
   * 외곽 계산 어느 단계에서도 상단 메모가 다시 포함될 수 없다.
   */
  let topMarkRemoved = false;
  let contentStartRow = 0;

  {
    const preliminaryRows = new Uint32Array(gridHeight);
    for (let gy = 0; gy < gridHeight; gy++) {
      let count = 0;
      for (let gx = 0; gx < gridWidth; gx++) {
        count += cleaned[gy * gridWidth + gx];
      }
      preliminaryRows[gy] = count;
    }

    const smoothPreRows = new Float64Array(gridHeight);
    const radius = 2;
    for (let row = 0; row < gridHeight; row++) {
      let sum = 0;
      let weight = 0;
      for (let d = -radius; d <= radius; d++) {
        const target = row + d;
        if (target < 0 || target >= gridHeight) continue;
        const w = radius + 1 - Math.abs(d);
        sum += preliminaryRows[target] * w;
        weight += w;
      }
      smoothPreRows[row] = sum / Math.max(1, weight);
    }

    const minimumActive = Math.max(2, Math.floor(gridWidth * 0.004));
    const bridgeGap = Math.max(1, Math.floor(gridHeight * 0.004));
    const runs = [];
    let runStart = -1;
    let lastActive = -1;

    for (let row = 0; row < gridHeight; row++) {
      if (smoothPreRows[row] >= minimumActive) {
        if (runStart < 0) runStart = row;
        lastActive = row;
      } else if (runStart >= 0 && row - lastActive > bridgeGap) {
        runs.push({ start: runStart, end: lastActive });
        runStart = -1;
        lastActive = -1;
      }
    }
    if (runStart >= 0) runs.push({ start: runStart, end: lastActive });

    const runMass = run => {
      let mass = 0;
      for (let row = run.start; row <= run.end; row++) mass += smoothPreRows[row];
      return mass;
    };

    const totalMass = smoothPreRows.reduce((sum, value) => sum + value, 0);

    if (runs.length >= 2 && totalMass > 0) {
      const enriched = runs.map(run => ({
        ...run,
        height: run.end - run.start + 1,
        mass: runMass(run)
      }));

      /*
       * 단순 최대 질량 하나만 고르지 않는다.
       * 상단 후보 뒤에서 시작하면서, 충분한 질량과 높이를 가진 첫 본문 덩어리를 찾는다.
       * 이 방식은 페이지마다 가장 큰 컷 위치가 바뀌어도 메모 컷오프 순위가 뒤집히지 않는다.
       */
      let mainIndex = -1;
      for (let i = 1; i < enriched.length; i++) {
        const run = enriched[i];
        const massRatio = run.mass / totalMass;
        const heightRatio = run.height / gridHeight;
        if (massRatio >= 0.22 || heightRatio >= 0.16) {
          mainIndex = i;
          break;
        }
      }

      if (mainIndex > 0) {
        const mainRun = enriched[mainIndex];
        const candidates = enriched.slice(0, mainIndex);
        const candidateStart = candidates[0].start;
        const candidateEnd = candidates[candidates.length - 1].end;
        const candidateHeight = candidateEnd - candidateStart + 1;
        const candidateMass = candidates.reduce((sum, run) => sum + run.mass, 0);
        const detachedGap = mainRun.start - candidateEnd - 1;

        const startsNearTop = candidateStart <= gridHeight * 0.14;
        const staysInTopArea = candidateEnd <= gridHeight * 0.28;
        const smallHeight = candidateHeight <= gridHeight * 0.13;
        const lowMass = candidateMass <= totalMass * 0.12;
        const enoughGap = detachedGap >= Math.max(3, Math.floor(gridHeight * 0.010));

        if (startsNearTop && staysInTopArea && smallHeight && lowMass && enoughGap) {
          contentStartRow = mainRun.start;
          for (let row = 0; row < contentStartRow; row++) {
            const offset = row * gridWidth;
            cleaned.fill(0, offset, offset + gridWidth);
          }
          topMarkRemoved = true;
        }
      }
    }
  }

  /*
   * 2차 상단 메모 폴백.
   * 1차 run 분리가 실패했더라도 상단의 희박한 전경 뒤에
   * 저밀도 골짜기와 본문 밀도 상승이 이어지면 본문 시작으로 확정한다.
   */
  if (!topMarkRemoved) {
    const rowCounts = new Uint32Array(gridHeight);
    for (let gy = 0; gy < gridHeight; gy++) {
      let count = 0;
      for (let gx = 0; gx < gridWidth; gx++) count += cleaned[gy * gridWidth + gx];
      rowCounts[gy] = count;
    }
    const smooth = new Float64Array(gridHeight);
    for (let gy = 0; gy < gridHeight; gy++) {
      let sum = 0, weight = 0;
      for (let d = -2; d <= 2; d++) {
        const y = gy + d;
        if (y < 0 || y >= gridHeight) continue;
        const w = 3 - Math.abs(d);
        sum += rowCounts[y] * w;
        weight += w;
      }
      smooth[gy] = sum / Math.max(1, weight);
    }
    const searchEnd = Math.min(gridHeight - 1, Math.floor(gridHeight * 0.32));
    const quietThreshold = Math.max(1.5, gridWidth * 0.006);
    const bodyThreshold = Math.max(3, gridWidth * 0.025);
    const minQuietRun = Math.max(3, Math.floor(gridHeight * 0.012));
    const minBodyRun = Math.max(5, Math.floor(gridHeight * 0.028));
    let quietStart = -1;
    let fallbackStart = -1;
    for (let gy = 1; gy <= searchEnd; gy++) {
      if (smooth[gy] <= quietThreshold) {
        if (quietStart < 0) quietStart = gy;
        continue;
      }
      if (quietStart >= 0 && gy - quietStart >= minQuietRun) {
        let bodyRows = 0, bodyMass = 0;
        const bodyEnd = Math.min(gridHeight, gy + minBodyRun * 2);
        for (let y = gy; y < bodyEnd; y++) {
          bodyMass += smooth[y];
          if (smooth[y] >= bodyThreshold) bodyRows++;
        }
        let topMass = 0;
        for (let y = 0; y < quietStart; y++) topMass += smooth[y];
        const topHasInk = topMass >= Math.max(5, gridWidth * 0.10);
        const bodyIsStable = bodyRows >= minBodyRun && bodyMass >= bodyThreshold * minBodyRun;
        if (topHasInk && bodyIsStable && gy <= gridHeight * 0.30) {
          fallbackStart = gy;
          break;
        }
      }
      quietStart = -1;
    }
    if (fallbackStart > 0) {
      contentStartRow = fallbackStart;
      for (let row = 0; row < contentStartRow; row++) {
        const offset = row * gridWidth;
        cleaned.fill(0, offset, offset + gridWidth);
      }
      topMarkRemoved = true;
    }
  }

  /*
   * 삽화 판정도 상단 메모가 제거된 마스크만 기준으로 다시 계산한다.
   * 초기 RGB 샘플 판정이 흰 배경 만화를 삽화로 오인하더라도 여기서 교정된다.
   */
  {
    let remainingCells = 0;
    let inkCells = 0;
    let chromaticCells = 0;
    let activeRows = 0;
    let activeColumns = 0;
    const rowInk = new Uint32Array(gridHeight);
    const columnInk = new Uint32Array(gridWidth);

    for (let gy = contentStartRow; gy < gridHeight; gy++) {
      const y = Math.min(height - 1, gy * step + Math.floor(step / 2));
      for (let gx = 0; gx < gridWidth; gx++) {
        remainingCells++;
        if (!cleaned[gy * gridWidth + gx]) continue;
        inkCells++;
        rowInk[gy]++;
        columnInk[gx]++;

        const x = Math.min(width - 1, gx * step + Math.floor(step / 2));
        const i = (y * width + x) * 4;
        const r = data[i];
        const g = data[i + 1];
        const b = data[i + 2];
        const chroma = Math.max(r, g, b) - Math.min(r, g, b);
        const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        if (chroma >= 24 && luma >= 18 && luma <= 242) chromaticCells++;
      }
    }

    for (let gy = contentStartRow; gy < gridHeight; gy++) {
      if (rowInk[gy] >= gridWidth * 0.16) activeRows++;
    }
    for (let gx = 0; gx < gridWidth; gx++) {
      if (columnInk[gx] >= Math.max(1, (gridHeight - contentStartRow) * 0.16)) activeColumns++;
    }

    const inkRatio = inkCells / Math.max(1, remainingCells);
    const chromaticRatioAfterMemo = chromaticCells / Math.max(1, remainingCells);
    const activeRowRatioAfterMemo = activeRows / Math.max(1, gridHeight - contentStartRow);
    const activeColumnRatioAfterMemo = activeColumns / Math.max(1, gridWidth);

    const colorIllustrationAfterMemo =
      chromaticRatioAfterMemo >= 0.050 &&
      activeRowRatioAfterMemo >= 0.42 &&
      activeColumnRatioAfterMemo >= 0.42;

    const denseIllustrationAfterMemo =
      inkRatio >= 0.30 &&
      activeRowRatioAfterMemo >= 0.58 &&
      activeColumnRatioAfterMemo >= 0.58;

    isIllustration = colorIllustrationAfterMemo || denseIllustrationAfterMemo;
  }

  /*
   * 흰 배경 만화 페이지용 외곽 컷선 감지.
   * 글자처럼 짧고 끊긴 획은 무시하고, 길게 이어진 세로/가로 선만 찾는다.
   * 각 방향에서 첫 번째와 마지막 유효 선만 사용해 큰 사각형을 만든다.
   */
  const longestRunWithGaps = (readCell, length, allowedGap = 2) => {
    let best = 0;
    let current = 0;
    let gap = 0;

    for (let i = 0; i < length; i++) {
      if (readCell(i)) {
        current += gap + 1;
        gap = 0;
        if (current > best) best = current;
      } else if (current > 0 && gap < allowedGap) {
        gap++;
      } else {
        current = 0;
        gap = 0;
      }
    }
    return best;
  };

  const detectOuterPanelBounds = (startRow = 0) => {
    const verticalScores = new Uint32Array(gridWidth);
    const horizontalCandidates = [];
    const contentHeight = Math.max(1, gridHeight - startRow);
    const verticalMinimum = Math.max(12, Math.floor(contentHeight * 0.16));
    const horizontalMinimum = Math.max(12, Math.floor(gridWidth * 0.16));

    /*
     * 좌우 경계는 첫/마지막 검출 열을 그대로 쓰지 않는다.
     * 각 열의 세로 연속 길이를 계산한 뒤 인접 후보를 군집화하고,
     * 충분히 긴 선을 가진 안정된 군집끼리만 좌우 경계로 채택한다.
     */
    for (let gx = 0; gx < gridWidth; gx++) {
      verticalScores[gx] = longestRunWithGaps(gy => {
        if (gy < startRow) return false;
        for (let dx = -1; dx <= 1; dx++) {
          const nx = gx + dx;
          if (nx >= 0 && nx < gridWidth && cleaned[gy * gridWidth + nx]) return true;
        }
        return false;
      }, gridHeight, 2);
    }

    const verticalGroups = [];
    let groupStart = -1;
    let groupPeak = 0;
    let groupPeakX = -1;

    for (let gx = 0; gx <= gridWidth; gx++) {
      const active = gx < gridWidth && verticalScores[gx] >= verticalMinimum;
      if (active) {
        if (groupStart < 0) {
          groupStart = gx;
          groupPeak = verticalScores[gx];
          groupPeakX = gx;
        } else if (verticalScores[gx] > groupPeak) {
          groupPeak = verticalScores[gx];
          groupPeakX = gx;
        }
      } else if (groupStart >= 0) {
        const end = gx - 1;
        const width = end - groupStart + 1;
        const strongSingle = groupPeak >= contentHeight * 0.30;
        const stableBand = width >= 2 && groupPeak >= contentHeight * 0.22;
        if (strongSingle || stableBand) {
          verticalGroups.push({
            start: groupStart,
            end,
            peak: groupPeak,
            peakX: groupPeakX
          });
        }
        groupStart = -1;
        groupPeak = 0;
        groupPeakX = -1;
      }
    }

    /*
     * 비정형/들쭉날쭉한 컷을 위한 외곽 픽셀 투표 후보.
     * 각 유효 행에서 가장 왼쪽·오른쪽 전경 픽셀을 기록하고,
     * 여러 행에서 반복해서 나타난 좌표만 감지 방향과 평행한 세로선 후보로 승격한다.
     * 단일 글자나 먼지 한 점은 투표 수가 부족해 후보가 되지 않는다.
     */
    const leftEdgeVotes = new Uint32Array(gridWidth);
    const rightEdgeVotes = new Uint32Array(gridWidth);
    const rowEdgeSamples = [];
    let edgeVoteRows = 0;
    const minimumForegroundPerRow = Math.max(3, Math.floor(gridWidth * 0.012));

    for (let gy = startRow; gy < gridHeight; gy++) {
      let first = -1;
      let last = -1;
      let mass = 0;
      for (let gx = 0; gx < gridWidth; gx++) {
        if (!cleaned[gy * gridWidth + gx]) continue;
        if (first < 0) first = gx;
        last = gx;
        mass++;
      }
      if (mass < minimumForegroundPerRow || first < 0 || last <= first) continue;
      leftEdgeVotes[first]++;
      rightEdgeVotes[last]++;
      rowEdgeSamples.push({ y: gy, left: first, right: last, mass });
      edgeVoteRows++;
    }

    const smoothVotes = votes => {
      const result = new Uint32Array(votes.length);
      for (let x = 0; x < votes.length; x++) {
        let total = 0;
        for (let dx = -2; dx <= 2; dx++) {
          const nx = x + dx;
          if (nx >= 0 && nx < votes.length) total += votes[nx];
        }
        result[x] = total;
      }
      return result;
    };

    const smoothedLeftVotes = smoothVotes(leftEdgeVotes);
    const smoothedRightVotes = smoothVotes(rightEdgeVotes);
    const minimumEdgeVotes = Math.max(3, Math.floor(edgeVoteRows * 0.045));

    const appendSyntheticEdgeCandidates = (votes, side) => {
      let start = -1;
      let peak = 0;
      let peakX = -1;
      for (let x = 0; x <= gridWidth; x++) {
        const active = x < gridWidth && votes[x] >= minimumEdgeVotes;
        if (active) {
          if (start < 0) start = x;
          if (votes[x] > peak) {
            peak = votes[x];
            peakX = x;
          }
        } else if (start >= 0) {
          const end = x - 1;
          const lineX = side === "left" ? start : end;
          const alreadyCovered = verticalGroups.some(group =>
            lineX >= group.start - 2 && lineX <= group.end + 2
          );
          if (!alreadyCovered) {
            verticalGroups.push({
              start: lineX,
              end: lineX,
              peak: Math.max(verticalMinimum, peak),
              peakX,
              synthetic: true,
              side
            });
          }
          start = -1;
          peak = 0;
          peakX = -1;
        }
      }
    };

    if (edgeVoteRows >= 8) {
      appendSyntheticEdgeCandidates(smoothedLeftVotes, "left");
      appendSyntheticEdgeCandidates(smoothedRightVotes, "right");

      /*
       * 연속 행렬 기반 돌출 컷 후보.
       * 일부 컷만 좌우로 튀어나온 경우 전체 행 투표 비율은 낮지만,
       * 그 구간 안에서는 최좌/최우 픽셀이 여러 행에 걸쳐 연속적으로 나타난다.
       * 연속된 행에서 x 변화가 작게 유지되는 구간을 하나의 세로 경계로 보고
       * 감지 방향과 평행한 합성 후보선을 추가한다.
       */
      const appendContinuousEdgeRuns = side => {
        const xKey = side === "left" ? "left" : "right";
        const maxXDrift = Math.max(2, Math.floor(gridWidth * 0.018));
        const minimumRunRows = Math.max(4, Math.floor(contentHeight * 0.045));
        const minimumRunMass = Math.max(
          minimumForegroundPerRow * minimumRunRows,
          Math.floor(gridWidth * minimumRunRows * 0.022)
        );

        let run = [];
        const flushRun = () => {
          if (run.length < minimumRunRows) {
            run = [];
            return;
          }
          const totalMass = run.reduce((sum, sample) => sum + sample.mass, 0);
          if (totalMass < minimumRunMass) {
            run = [];
            return;
          }

          const xs = run.map(sample => sample[xKey]).sort((a, b) => a - b);
          /* 바깥쪽 픽셀을 지나도록 left는 낮은 분위수, right는 높은 분위수를 쓴다. */
          const quantileIndex = side === "left"
            ? Math.floor((xs.length - 1) * 0.15)
            : Math.ceil((xs.length - 1) * 0.85);
          const lineX = xs[Math.max(0, Math.min(xs.length - 1, quantileIndex))];
          const alreadyCovered = verticalGroups.some(group =>
            lineX >= group.start - 2 && lineX <= group.end + 2
          );
          if (!alreadyCovered) {
            verticalGroups.push({
              start: lineX,
              end: lineX,
              peak: Math.max(verticalMinimum, run.length),
              peakX: lineX,
              synthetic: true,
              continuous: true,
              side,
              runStart: run[0].y,
              runEnd: run[run.length - 1].y
            });
          }
          run = [];
        };

        for (const sample of rowEdgeSamples) {
          if (!run.length) {
            run.push(sample);
            continue;
          }
          const previous = run[run.length - 1];
          const consecutiveRow = sample.y <= previous.y + 2;
          const stableX = Math.abs(sample[xKey] - previous[xKey]) <= maxXDrift;
          if (consecutiveRow && stableX) {
            run.push(sample);
          } else {
            flushRun();
            run.push(sample);
          }
        }
        flushRun();
      };

      appendContinuousEdgeRuns("left");
      appendContinuousEdgeRuns("right");

      /*
       * x 고정형 세로 런 후보.
       * 행별 최외곽 좌표는 효과음/말풍선 때문에 흔들릴 수 있으므로,
       * 이번 후보는 반대로 한 x열에서 y만 연속적으로 변하는 전경을 찾는다.
       * 짧은 돌출 컷의 세로 모서리도 후보가 되도록 일반 16% 선 기준보다 낮은
       * 독립 임계값을 사용하되, 인접 열에서도 비슷한 런이 확인되는 경우만 채택한다.
       */
      const fixedXRunMinimum = Math.max(5, Math.floor(contentHeight * 0.035));
      const fixedXRuns = new Array(gridWidth).fill(null);

      const strongestVerticalRunAtX = gx => {
        let bestStart = -1;
        let bestEnd = -1;
        let bestLength = 0;
        let runStart = -1;
        let lastInk = -1;
        let gaps = 0;

        for (let gy = startRow; gy < gridHeight; gy++) {
          let ink = false;
          for (let dx = -1; dx <= 1; dx++) {
            const nx = gx + dx;
            if (nx >= 0 && nx < gridWidth && cleaned[gy * gridWidth + nx]) {
              ink = true;
              break;
            }
          }

          if (ink) {
            if (runStart < 0) runStart = gy;
            lastInk = gy;
            gaps = 0;
          } else if (runStart >= 0) {
            gaps++;
            if (gaps > 1) {
              const length = lastInk - runStart + 1;
              if (length > bestLength) {
                bestLength = length;
                bestStart = runStart;
                bestEnd = lastInk;
              }
              runStart = -1;
              lastInk = -1;
              gaps = 0;
            }
          }
        }

        if (runStart >= 0) {
          const length = lastInk - runStart + 1;
          if (length > bestLength) {
            bestLength = length;
            bestStart = runStart;
            bestEnd = lastInk;
          }
        }
        return { start: bestStart, end: bestEnd, length: bestLength };
      };

      for (let gx = 0; gx < gridWidth; gx++) {
        fixedXRuns[gx] = strongestVerticalRunAtX(gx);
      }

      const runOverlapRatio = (a, b) => {
        if (!a || !b || a.length <= 0 || b.length <= 0) return 0;
        const overlap = Math.max(0, Math.min(a.end, b.end) - Math.max(a.start, b.start) + 1);
        return overlap / Math.max(1, Math.min(a.length, b.length));
      };

      let fixedStart = -1;
      let fixedPeak = 0;
      let fixedPeakX = -1;
      const flushFixedGroup = endExclusive => {
        if (fixedStart < 0) return;
        const end = endExclusive - 1;
        const center = (fixedStart + end) / 2;
        const side = center < gridWidth / 2 ? "left" : "right";
        const lineX = side === "left" ? fixedStart : end;
        const alreadyCovered = verticalGroups.some(group =>
          lineX >= group.start - 1 && lineX <= group.end + 1
        );
        if (!alreadyCovered) {
          verticalGroups.push({
            start: lineX,
            end: lineX,
            peak: fixedPeak,
            peakX: fixedPeakX,
            synthetic: true,
            fixedXRun: true,
            side
          });
        }
        fixedStart = -1;
        fixedPeak = 0;
        fixedPeakX = -1;
      };

      for (let gx = 0; gx <= gridWidth; gx++) {
        let active = false;
        let run = null;
        if (gx < gridWidth) {
          run = fixedXRuns[gx];
          if (run.length >= fixedXRunMinimum) {
            const leftNeighbor = gx > 0 ? fixedXRuns[gx - 1] : null;
            const rightNeighbor = gx + 1 < gridWidth ? fixedXRuns[gx + 1] : null;
            const supportedLeft = leftNeighbor &&
              leftNeighbor.length >= fixedXRunMinimum * 0.75 &&
              runOverlapRatio(run, leftNeighbor) >= 0.55;
            const supportedRight = rightNeighbor &&
              rightNeighbor.length >= fixedXRunMinimum * 0.75 &&
              runOverlapRatio(run, rightNeighbor) >= 0.55;
            active = Boolean(supportedLeft || supportedRight);
          }
        }

        if (active) {
          if (fixedStart < 0) fixedStart = gx;
          if (run.length > fixedPeak) {
            fixedPeak = run.length;
            fixedPeakX = gx;
          }
        } else {
          flushFixedGroup(gx);
        }
      }

      verticalGroups.sort((a, b) => a.start - b.start || a.end - b.end);
    }

    for (let gy = startRow; gy < gridHeight; gy++) {
      const run = longestRunWithGaps(gx => {
        for (let dy = -1; dy <= 1; dy++) {
          const ny = gy + dy;
          if (ny >= 0 && ny < gridHeight && cleaned[ny * gridWidth + gx]) return true;
        }
        return false;
      }, gridWidth, 2);
      if (run >= horizontalMinimum) horizontalCandidates.push(gy);
    }

    if (verticalGroups.length < 2 || horizontalCandidates.length < 2) return null;

    /*
     * 좌우는 군집의 최고점이 아니라 실제 바깥 모서리를 사용한다.
     * 두꺼운 테두리에서는 peakX가 군집 안쪽으로 치우쳐 잘림을 만들 수 있다.
     * 또한 실제 컷이 페이지 폭 대부분을 차지할 수 있으므로 96% 상한은 두지 않는다.
     */
    let bestPair = null;
    for (let i = 0; i < verticalGroups.length - 1; i++) {
      for (let j = i + 1; j < verticalGroups.length; j++) {
        const leftGroup = verticalGroups[i];
        const rightGroup = verticalGroups[j];
        const leftEdge = leftGroup.start;
        const rightEdge = rightGroup.end;
        const span = rightEdge - leftEdge + 1;
        const widthRatio = span / gridWidth;
        if (widthRatio < 0.42) continue;

        const support = Math.min(leftGroup.peak, rightGroup.peak);
        const supportRatio = support / contentHeight;
        /* fixedXRun은 선택 후보가 아니라 선택 후 바깥 확장용 증거로만 사용한다.
         * 내부의 효과음/문자 세로획이 좌우 외곽선으로 승격되는 것을 막는다. */
        if (leftGroup.fixedXRun || rightGroup.fixedXRun) continue;
        const minimumSupportRatio = 0.16;
        if (supportRatio < minimumSupportRatio) continue;

        /* 바깥쪽 쌍을 우선하되, 너무 약한 선 한 쌍은 배제한다. */
        const coverageScore = widthRatio * 4.0;
        const supportScore = Math.min(1, supportRatio) * 1.5;
        const edgeBonus =
          ((gridWidth - 1 - rightEdge) + leftEdge) / gridWidth * -0.35;
        const directionalBonus =
          (leftGroup.synthetic && leftGroup.side === "left" ? 0.22 : 0) +
          (rightGroup.synthetic && rightGroup.side === "right" ? 0.22 : 0) +
          (leftGroup.fixedXRun && leftGroup.side === "left" ? 0.18 : 0) +
          (rightGroup.fixedXRun && rightGroup.side === "right" ? 0.18 : 0);
        const wrongSidePenalty =
          (leftGroup.synthetic && leftGroup.side === "right" ? 1.0 : 0) +
          (rightGroup.synthetic && rightGroup.side === "left" ? 1.0 : 0);
        const score = coverageScore + supportScore + edgeBonus + directionalBonus - wrongSidePenalty;

        if (!bestPair || score > bestPair.score) {
          bestPair = {
            left: leftEdge,
            right: rightEdge,
            score
          };
        }
      }
    }

    if (!bestPair) return null;

    let left = bestPair.left;
    let right = bestPair.right;
    const top = horizontalCandidates[0];
    const bottom = horizontalCandidates[horizontalCandidates.length - 1];

    const heightRatio = (bottom - top + 1) / gridHeight;
    if (heightRatio < 0.42) return null;

    /*
     * 안정적인 좌우 외곽선을 먼저 고른 뒤, 경계 밖으로 실제 연결된 전경만 확장한다.
     * 후보 페어링에 넣지 않으므로 내부 세로획이 경계를 안쪽으로 끌어당길 수 없다.
     */
    const visited = new Uint8Array(cleaned.length);
    const stack = [];
    const minComponentMass = Math.max(6, Math.floor(gridWidth * gridHeight * 0.00012));
    const maxBridgeGap = Math.max(1, Math.floor(gridWidth * 0.012));
    let expandedLeft = left;
    let expandedRight = right;

    for (let sy = top; sy <= bottom; sy++) {
      for (let sx = 0; sx < gridWidth; sx++) {
        const startIndex = sy * gridWidth + sx;
        if (!cleaned[startIndex] || visited[startIndex]) continue;

        visited[startIndex] = 1;
        stack.push(startIndex);
        let minX = sx, maxX = sx, minY = sy, maxY = sy, mass = 0;

        while (stack.length) {
          const index = stack.pop();
          const cy = Math.floor(index / gridWidth);
          const cx = index - cy * gridWidth;
          mass++;
          if (cx < minX) minX = cx;
          if (cx > maxX) maxX = cx;
          if (cy < minY) minY = cy;
          if (cy > maxY) maxY = cy;

          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              if (!dx && !dy) continue;
              const nx = cx + dx, ny = cy + dy;
              if (nx < 0 || nx >= gridWidth || ny < top || ny > bottom) continue;
              const ni = ny * gridWidth + nx;
              if (cleaned[ni] && !visited[ni]) {
                visited[ni] = 1;
                stack.push(ni);
              }
            }
          }
        }

        const componentHeight = maxY - minY + 1;
        const componentWidth = maxX - minX + 1;
        if (mass < minComponentMass || (componentHeight < 3 && componentWidth < 3)) continue;

        const touchesLeftBoundary = minX < left && maxX >= left - maxBridgeGap;
        const touchesRightBoundary = maxX > right && minX <= right + maxBridgeGap;
        if (touchesLeftBoundary) expandedLeft = Math.min(expandedLeft, minX);
        if (touchesRightBoundary) expandedRight = Math.max(expandedRight, maxX);
      }
    }

    left = expandedLeft;
    right = expandedRight;
    return { left, right, top, bottom };
  };

  let panelBounds = null;

  const rowCounts = new Uint32Array(gridHeight);
  const columnCounts = new Uint32Array(gridWidth);
  let foregroundCount = 0;

  for (let gy = 0; gy < gridHeight; gy++) {
    for (let gx = 0; gx < gridWidth; gx++) {
      if (!cleaned[gy * gridWidth + gx]) continue;
      rowCounts[gy]++;
      columnCounts[gx]++;
      foregroundCount++;
    }
  }

  if (foregroundCount < gridWidth * gridHeight * 0.0015) {
    $("status").textContent = "내용을 충분히 찾지 못해 이전 크롭을 유지했습니다.";
    crop = previousCrop;
    globalThis.renderCrop?.();
    return false;
  }

  /* 작은 페이지 번호도 살리되, 한두 개 먼지 때문에 외곽이 늘어나지는 않게 한다. */
  const minRowCount = Math.max(2, Math.floor(gridWidth * 0.004));
  const minColumnCount = Math.max(2, Math.floor(gridHeight * 0.004));

  const smoothCounts = (counts, radius = 2) => {
    const result = new Float64Array(counts.length);
    for (let i = 0; i < counts.length; i++) {
      let sum = 0;
      let weight = 0;
      for (let d = -radius; d <= radius; d++) {
        const p = i + d;
        if (p < 0 || p >= counts.length) continue;
        const w = radius + 1 - Math.abs(d);
        sum += counts[p] * w;
        weight += w;
      }
      result[i] = sum / Math.max(1, weight);
    }
    return result;
  };

  const smoothedRows = smoothCounts(rowCounts, 2);
  const smoothedColumns = smoothCounts(columnCounts, 2);

  /* 상단 메모는 cleaned 마스크 생성 직후 이미 제거되었다. */

  /*
   * 상단 메모 제거가 끝난 뒤 외곽 컷선을 찾는다.
   * 이전 버전은 컷선을 먼저 계산해서, 메모 제거 결과가 panelBounds에 반영되지 않았다.
   */
  panelBounds = isIllustration
    ? null
    : detectOuterPanelBounds(contentStartRow);

  /*
   * 컷선 후보를 찾은 뒤에는 선 자체의 검출 열/행만 그대로 쓰지 않고,
   * 그 사각형 바로 주변에서 실제로 가장 바깥에 존재하는 전경 픽셀까지 미세 보정한다.
   * 무제한 극값을 쓰면 먼지 때문에 다시 폭주하므로, 각 방향 최대 2% 이내만 확장한다.
   * 최종 경계는 가장 바깥 픽셀을 지나는 수직/수평선이 된다.
   */
  const refinePanelBoundsToOuterPixels = bounds => {
    if (!bounds) return null;

    const haloX = Math.max(1, Math.floor(gridWidth * 0.008));
    const haloY = Math.max(1, Math.floor(gridHeight * 0.02));
    const scanLeft = Math.max(0, bounds.left - haloX);
    const scanRight = Math.min(gridWidth - 1, bounds.right + haloX);
    const scanTop = Math.max(contentStartRow, bounds.top - haloY);
    const scanBottom = Math.min(gridHeight - 1, bounds.bottom + haloY);

    let left = bounds.left;
    let right = bounds.right;
    let top = bounds.top;
    let bottom = bounds.bottom;
    let found = false;

    for (let gy = scanTop; gy <= scanBottom; gy++) {
      for (let gx = scanLeft; gx <= scanRight; gx++) {
        if (!cleaned[gy * gridWidth + gx]) continue;
        found = true;
        /* 좌우는 안정된 세로 경계 군집을 그대로 유지한다. */
        top = Math.min(top, gy);
        bottom = Math.max(bottom, gy);
      }
    }

    if (!found) return bounds;
    return { left, right, top, bottom };
  };

  panelBounds = refinePanelBoundsToOuterPixels(panelBounds);

  /*
   * 들쭉날쭉한 컷 배열 보정.
   * 기본 컷선 사각형 밖으로 튀어나온 전경을 연결 요소로 묶어 검사한다.
   * 먼지/글자 하나가 아니라 실제 컷 일부로 볼 수 있을 만큼 크거나 길고,
   * 기본 사각형과 가깝거나 한 축에서 충분히 겹치는 요소만 경계에 합친다.
   */
  const expandPanelBoundsForStaggeredPanels = bounds => {
    if (!bounds) return null;

    const visited = new Uint8Array(cleaned.length);
    const queue = new Int32Array(cleaned.length);
    const minMass = Math.max(10, Math.floor(gridWidth * gridHeight * 0.0018));
    const minSpanX = Math.max(4, Math.floor(gridWidth * 0.055));
    const minSpanY = Math.max(4, Math.floor(gridHeight * 0.055));
    const nearGapX = Math.max(1, Math.floor(gridWidth * 0.008));
    const nearGapY = Math.max(2, Math.floor(gridHeight * 0.018));

    let expanded = { ...bounds };
    let expandedAny = false;

    for (let sy = contentStartRow; sy < gridHeight; sy++) {
      for (let sx = 0; sx < gridWidth; sx++) {
        const startIndex = sy * gridWidth + sx;
        if (!cleaned[startIndex] || visited[startIndex]) continue;

        let head = 0;
        let tail = 0;
        queue[tail++] = startIndex;
        visited[startIndex] = 1;

        let mass = 0;
        let minX = sx;
        let maxX = sx;
        let minY = sy;
        let maxY = sy;

        while (head < tail) {
          const index = queue[head++];
          const y = Math.floor(index / gridWidth);
          const x = index - y * gridWidth;
          mass++;
          minX = Math.min(minX, x);
          maxX = Math.max(maxX, x);
          minY = Math.min(minY, y);
          maxY = Math.max(maxY, y);

          for (let oy = -1; oy <= 1; oy++) {
            const ny = y + oy;
            if (ny < contentStartRow || ny >= gridHeight) continue;
            for (let ox = -1; ox <= 1; ox++) {
              if (ox === 0 && oy === 0) continue;
              const nx = x + ox;
              if (nx < 0 || nx >= gridWidth) continue;
              const next = ny * gridWidth + nx;
              if (!cleaned[next] || visited[next]) continue;
              visited[next] = 1;
              queue[tail++] = next;
            }
          }
        }

        const outside =
          minX < bounds.left || maxX > bounds.right ||
          minY < bounds.top || maxY > bounds.bottom;
        if (!outside) continue;

        const spanX = maxX - minX + 1;
        const spanY = maxY - minY + 1;
        const overlapX = Math.max(0, Math.min(maxX, bounds.right) - Math.max(minX, bounds.left) + 1);
        const overlapY = Math.max(0, Math.min(maxY, bounds.bottom) - Math.max(minY, bounds.top) + 1);
        const gapX = minX > bounds.right
          ? minX - bounds.right - 1
          : bounds.left > maxX
            ? bounds.left - maxX - 1
            : 0;
        const gapY = minY > bounds.bottom
          ? minY - bounds.bottom - 1
          : bounds.top > maxY
            ? bounds.top - maxY - 1
            : 0;

        const substantial =
          mass >= minMass &&
          (spanX >= minSpanX || spanY >= minSpanY);
        const alignedWithPage =
          overlapX >= Math.min(spanX, Math.max(3, Math.floor(gridWidth * 0.04))) ||
          overlapY >= Math.min(spanY, Math.max(3, Math.floor(gridHeight * 0.04)));
        const nearMainBounds = gapX <= nearGapX && gapY <= nearGapY;

        if (!substantial || (!nearMainBounds && !alignedWithPage)) continue;

        /*
         * 상하 돌출은 기존대로 적극 반영한다.
         * 좌우 돌출은 실제 컷처럼 세로 길이가 충분하고 본문과 크게 겹치는 경우만 반영한다.
         * 작은 효과음·페이지 번호·먼지가 좌우 경계를 밀어내지 못하도록 최대 확장폭도 제한한다.
         */
        const boundsHeight = bounds.bottom - bounds.top + 1;
        const strongVerticalPanel =
          spanY >= Math.max(minSpanY, Math.floor(gridHeight * 0.12)) &&
          overlapY >= Math.max(4, Math.floor(Math.min(spanY, boundsHeight) * 0.35)) &&
          gapX <= nearGapX;
        const maxHorizontalExpansion = Math.max(2, Math.floor(gridWidth * 0.028));

        /*
         * 좌우는 여기서 확장하지 않는다.
         * 연결 요소 탐색의 minX/maxX를 경계로 직접 승격하면
         * 글자·효과음·노이즈가 한 덩어리로 연결된 페이지에서 폭주한다.
         */
        void strongVerticalPanel;
        void maxHorizontalExpansion;

        expanded.top = Math.min(expanded.top, minY);
        expanded.bottom = Math.max(expanded.bottom, maxY);
        expandedAny = true;
      }
    }

    if (expandedAny) staggeredPanelExpanded = true;
    return expanded;
  };

  let staggeredPanelExpanded = false;
  panelBounds = expandPanelBoundsForStaggeredPanels(panelBounds);

  /* 상하 경계 전용 복구: 좌우는 유지하고 y방향 연속 전경만 반영한다. */
  const rescueVerticalEdges = bounds => {
    if (!bounds) return bounds;
    const xPad = Math.max(1, Math.floor(gridWidth * 0.012));
    const scanLeft = Math.max(0, bounds.left - xPad);
    const scanRight = Math.min(gridWidth - 1, bounds.right + xPad);
    const minRowInk = Math.max(2, Math.floor((scanRight - scanLeft + 1) * 0.012));
    const maxGap = Math.max(1, Math.floor(gridHeight * 0.004));
    const searchDistance = Math.max(3, Math.floor(gridHeight * 0.055));
    const rowInk = gy => {
      let count = 0;
      for (let gx = scanLeft; gx <= scanRight; gx++) count += cleaned[gy * gridWidth + gx];
      return count;
    };
    let rescuedTop = bounds.top, gap = 0;
    for (let gy = bounds.top - 1; gy >= Math.max(contentStartRow, bounds.top - searchDistance); gy--) {
      if (rowInk(gy) >= minRowInk) { rescuedTop = gy; gap = 0; }
      else if (++gap > maxGap) break;
    }
    let rescuedBottom = bounds.bottom;
    gap = 0;
    for (let gy = bounds.bottom + 1; gy <= Math.min(gridHeight - 1, bounds.bottom + searchDistance); gy++) {
      if (rowInk(gy) >= minRowInk) { rescuedBottom = gy; gap = 0; }
      else if (++gap > maxGap) break;
    }
    if (rescuedTop < bounds.top || rescuedBottom > bounds.bottom) staggeredPanelExpanded = true;
    return { ...bounds, top: rescuedTop, bottom: rescuedBottom };
  };
  panelBounds = rescueVerticalEdges(panelBounds);

  /*
   * 메모를 제외한 실제 콘텐츠의 열 분포를 다시 만든다.
   * 컷선 바깥에 말풍선/글자/효과음이 있으면 최종 외곽을 그 위치까지 확장한다.
   */
  const contentColumnCounts = new Uint32Array(gridWidth);
  for (let gy = contentStartRow; gy < gridHeight; gy++) {
    for (let gx = 0; gx < gridWidth; gx++) {
      if (cleaned[gy * gridWidth + gx]) contentColumnCounts[gx]++;
    }
  }
  const contentSmoothedColumns = smoothCounts(contentColumnCounts, 2);

  /*
   * 경계 계산은 검증된 단일 경로를 유지한다.
   * 삽화도 동일한 감지 결과를 사용하고, 차이는 최종 margin만 0으로 둔다.
   */
  const findBounds = (counts, minimum, edgeTrimRatio = 0.006) => {
    const active = [];
    let total = 0;
    for (let i = 0; i < counts.length; i++) {
      const value = counts[i] >= minimum ? counts[i] : 0;
      active.push(value);
      total += value;
    }
    if (total <= 0) return null;

    const trim = total * edgeTrimRatio;
    let cumulative = 0;
    let start = 0;
    for (; start < active.length; start++) {
      cumulative += active[start];
      if (cumulative >= trim) break;
    }

    cumulative = 0;
    let end = active.length - 1;
    for (; end >= 0; end--) {
      cumulative += active[end];
      if (cumulative >= trim) break;
    }

    return start < end ? { start, end } : null;
  };

  const foregroundHorizontal = findBounds(
    contentSmoothedColumns,
    minColumnCount,
    0.004
  );
  const foregroundVertical = findBounds(
    smoothedRows,
    minRowCount,
    0.004
  );

  /*
   * 잘리기 쉬운 주변 콘텐츠 보호.
   * - 상단 좌/우 제목: 메모 제거 이후 남은 상단 모서리의 작은 텍스트 묶음
   * - 하단 좌/우 페이지 번호: 하단 모서리의 작은 숫자/문자 묶음
   * - 비정형 컷: 기본 외곽 밖으로 튀어나왔지만 본문에 가깝거나 충분히 큰 전경
   *
   * 단순 극값을 쓰지 않고 연결 요소를 묶어서 먼지와 고립 노이즈를 배제한다.
   */
  const collectPeripheralProtection = baseBounds => {
    const visited = new Uint8Array(cleaned.length);
    const queue = new Int32Array(cleaned.length);
    const components = [];

    for (let gy = contentStartRow; gy < gridHeight; gy++) {
      for (let gx = 0; gx < gridWidth; gx++) {
        const seed = gy * gridWidth + gx;
        if (!cleaned[seed] || visited[seed]) continue;

        let head = 0;
        let tail = 0;
        queue[tail++] = seed;
        visited[seed] = 1;
        let minX = gx, maxX = gx, minY = gy, maxY = gy, mass = 0;

        while (head < tail) {
          const current = queue[head++];
          const cy = Math.floor(current / gridWidth);
          const cx = current - cy * gridWidth;
          mass++;
          minX = Math.min(minX, cx);
          maxX = Math.max(maxX, cx);
          minY = Math.min(minY, cy);
          maxY = Math.max(maxY, cy);

          for (let oy = -1; oy <= 1; oy++) {
            const ny = cy + oy;
            if (ny < contentStartRow || ny >= gridHeight) continue;
            for (let ox = -1; ox <= 1; ox++) {
              const nx = cx + ox;
              if (nx < 0 || nx >= gridWidth || (ox === 0 && oy === 0)) continue;
              const next = ny * gridWidth + nx;
              if (cleaned[next] && !visited[next]) {
                visited[next] = 1;
                queue[tail++] = next;
              }
            }
          }
        }

        components.push({ minX, maxX, minY, maxY, mass });
      }
    }

    const protectedItems = [];
    const headerLimit = Math.max(contentStartRow + 1, Math.floor(gridHeight * 0.22));
    const footerStart = Math.floor(gridHeight * 0.82);
    const cornerWidth = Math.floor(gridWidth * 0.30);
    const minimumTextMass = Math.max(3, Math.floor(gridWidth * gridHeight * 0.000015));

    const headerLeft = [];
    const headerRight = [];
    const footerLeft = [];
    const footerRight = [];

    for (const component of components) {
      const componentWidth = component.maxX - component.minX + 1;
      const componentHeight = component.maxY - component.minY + 1;
      const validSmallText =
        component.mass >= minimumTextMass &&
        (componentWidth >= 2 || componentHeight >= 2) &&
        componentWidth <= gridWidth * 0.28 &&
        componentHeight <= gridHeight * 0.10;

      if (validSmallText && component.minY >= contentStartRow && component.maxY <= headerLimit) {
        if (component.maxX <= cornerWidth) headerLeft.push(component);
        if (component.minX >= gridWidth - cornerWidth) headerRight.push(component);
      }

      if (validSmallText && component.minY >= footerStart) {
        if (component.maxX <= cornerWidth) footerLeft.push(component);
        if (component.minX >= gridWidth - cornerWidth) footerRight.push(component);
      }

      if (baseBounds) {
        const outside =
          component.minX < baseBounds.left || component.maxX > baseBounds.right ||
          component.minY < baseBounds.top || component.maxY > baseBounds.bottom;
        if (!outside) continue;

        const dx = component.maxX < baseBounds.left
          ? baseBounds.left - component.maxX
          : component.minX > baseBounds.right
            ? component.minX - baseBounds.right
            : 0;
        const dy = component.maxY < baseBounds.top
          ? baseBounds.top - component.maxY
          : component.minY > baseBounds.bottom
            ? component.minY - baseBounds.bottom
            : 0;
        const closeToMain = dx <= gridWidth * 0.025 && dy <= gridHeight * 0.035;
        const substantial =
          component.mass >= Math.max(8, gridWidth * gridHeight * 0.00012) ||
          componentWidth >= gridWidth * 0.045 ||
          componentHeight >= gridHeight * 0.045;

        if (closeToMain && substantial) protectedItems.push(component);
      }
    }

    const addCornerGroup = group => {
      if (!group.length) return;
      const mass = group.reduce((sum, item) => sum + item.mass, 0);
      if (mass < minimumTextMass * 2) return;
      protectedItems.push({
        minX: Math.min(...group.map(item => item.minX)),
        maxX: Math.max(...group.map(item => item.maxX)),
        minY: Math.min(...group.map(item => item.minY)),
        maxY: Math.max(...group.map(item => item.maxY)),
        mass
      });
    };

    addCornerGroup(headerLeft);
    addCornerGroup(headerRight);
    addCornerGroup(footerLeft);
    addCornerGroup(footerRight);

    if (!protectedItems.length) return null;
    return {
      left: Math.min(...protectedItems.map(item => item.minX)),
      right: Math.max(...protectedItems.map(item => item.maxX)),
      top: Math.min(...protectedItems.map(item => item.minY)),
      bottom: Math.max(...protectedItems.map(item => item.maxY)),
      headerProtected: headerLeft.length + headerRight.length > 0,
      footerProtected: footerLeft.length + footerRight.length > 0
    };
  };

  /*
   * 컷선이 있으면 그것을 기본 사각형으로 쓰되,
   * 컷선 밖에서 유효한 글자/그림이 감지되면 가장 바깥쪽까지 확장한다.
   * 컷선이 없으면 기존 전경 분포 감지 결과를 그대로 사용한다.
   */
  /*
   * v23 안정화:
   * 주변 보호 요소로 좌우/우하단을 확장하던 로직을 제거한다.
   * - 컷선이 있으면 컷선 bounds만 사용
   * - 컷선이 없을 때만 기존 전경 bounds 사용
   * 제목/페이지 번호/비정형 컷은 이후 별도 축 제한 로직으로 다시 추가한다.
   */
  const horizontal = panelBounds
    ? { start: panelBounds.left, end: panelBounds.right }
    : foregroundHorizontal;

  const vertical = panelBounds
    ? { start: panelBounds.top, end: panelBounds.bottom }
    : foregroundVertical;

  if (!horizontal || !vertical) {
    $("status").textContent = "안정적인 외곽을 찾지 못해 이전 크롭을 유지했습니다.";
    crop = previousCrop;
    globalThis.renderCrop?.();
    return false;
  }

  let x0 = horizontal.start / gridWidth;
  let x1 = (horizontal.end + 1) / gridWidth;
  let y0 = vertical.start / gridHeight;
  let y1 = (vertical.end + 1) / gridHeight;

  const detectedWidth = x1 - x0;
  const detectedHeight = y1 - y0;

  if (detectedWidth < 0.18 || detectedHeight < 0.18) {
    $("status").textContent = "감지 영역이 너무 작아 이전 크롭을 유지했습니다.";
    crop = previousCrop;
    globalThis.renderCrop?.();
    return false;
  }

  /* 삽화는 메모 제거 후 판정된 실제 외곽에 맞닿게 추가 여백을 0으로 둔다. */
  const marginX = isIllustration
    ? 0
    : panelBounds
      ? 0.004
      : (detectedWidth > 0.90 ? 0.006 : 0.018);
  const marginY = isIllustration
    ? 0
    : panelBounds
      ? 0.004
      : (detectedHeight > 0.92 ? 0.006 : 0.013);

  x0 = clamp(x0 - marginX, 0, 1);
  x1 = clamp(x1 + marginX, 0, 1);
  y0 = clamp(y0 - marginY, 0, 1);
  y1 = clamp(y1 + marginY, 0, 1);

  /*
   * 축 고정은 크기 고정이 아니라 좌표 자체를 고정한다.
   * - 가로 위치(x) 고정: x0/x1은 잠근 값을 유지하고 y0/y1만 자동감지
   * - 세로 위치(y) 고정: y0/y1은 잠근 값을 유지하고 x0/x1만 자동감지
   */
  if ($("lockAutoWidth")?.checked) {
    const locked = lockedAutoX ?? { x0: previousCrop.x0, x1: previousCrop.x1 };
    x0 = locked.x0;
    x1 = locked.x1;
  }

  if ($("lockAutoHeight")?.checked) {
    const locked = lockedAutoY ?? { y0: previousCrop.y0, y1: previousCrop.y1 };
    y0 = locked.y0;
    y1 = locked.y1;
  }

  crop = {
    x0: clamp(x0, 0, 1),
    y0: clamp(y0, 0, 1),
    x1: clamp(x1, 0, 1),
    y1: clamp(y1, 0, 1)
  };

  globalThis.renderCrop?.();
  const detectNotes = [];
  if (panelBounds) detectNotes.push("외곽 컷선 감지");
  if (staggeredPanelExpanded) detectNotes.push("돌출 컷 보정");
  if (topMarkRemoved) detectNotes.push("상단 낙서 제외");
  if ($("lockAutoWidth")?.checked) detectNotes.push("x축 고정");
  if ($("lockAutoHeight")?.checked) detectNotes.push("y축 고정");
  const detectNote = detectNotes.length ? ` · ${detectNotes.join(" · ")}` : "";
  $("status").textContent = isIllustration
    ? `삽화 외곽 자동 선택 · 마진 0${detectNote} · 저장 이름: ${outputName()}`
    : `단행본 외곽 자동 선택${detectNote} · 저장 이름: ${outputName()}`;
  return true;
}

async function getFiles(){const r=await fetch("/api/files");if(!r.ok)throw new Error("IN 폴더 목록을 읽지 못했습니다.");const d=await r.json();return Array.isArray(d.files)?d.files:[];}
async function detectPage(pdf,pageNumber){
  let page=null;
  let renderTask=null;
  try{
    page=await pdf.getPage(pageNumber);
    const base=page.getViewport({scale:1});
    const scale=Math.min(2,1200/base.width);
    const viewport=page.getViewport({scale});
    canvas.width=Math.max(1,Math.floor(viewport.width));
    canvas.height=Math.max(1,Math.floor(viewport.height));
    renderTask=page.render({canvasContext:ctx,viewport});
    await renderTask.promise;
    crop={x0:.03,y0:.03,x1:.97,y1:.97};
    if(!autoDetectContent()) throw new Error(`페이지 ${pageNumber} 자동감지 실패`);
    const result={...crop};
    for(const key of ["x0","y0","x1","y1"]){
      if(!Number.isFinite(result[key])) throw new Error(`페이지 ${pageNumber} ${key} 좌표 오류`);
    }
    return result;
  }finally{
    try{page?.cleanup();}catch(_error){}
    ctx.clearRect(0,0,canvas.width,canvas.height);
    canvas.width=1;
    canvas.height=1;
    await yieldToBrowser();
  }
}
async function outputExists(outputName){
  const response=await fetch(`/api/output-exists?name=${encodeURIComponent(outputName)}`);
  if(!response.ok) return false;
  const data=await response.json();
  return Boolean(data.exists);
}

async function run(){
  const skipLast=Math.max(0,Math.floor(Number(skipInput.value)||0));
  stopRequested=false;
  startButton.disabled=true;
  stopButton.disabled=false;
  skipInput.disabled=true;
  let completed=0;
  let skipped=0;
  const failures=[];
  try{
    const files=await getFiles();
    if(!files.length){
      status.textContent="IN 폴더에 PDF가 없습니다.";
      return;
    }
    await ensurePdfJs();
    for(let fi=0;fi<files.length;fi++){
      if(stopRequested) break;
      const name=files[fi];
      const stem=name.replace(/\.pdf$/i,"");
      const outputName=`${stem}_crop.pdf`;
      let pdf=null;
      try{
        if(await outputExists(outputName)){
          skipped++;
          status.textContent=`${fi+1}/${files.length} 기존 출력 건너뜀\n${name}`;
          await yieldToBrowser();
          continue;
        }
        status.textContent=`${fi+1}/${files.length} 파일 여는 중\n${name}`;
        const loadingTask=pdfjsLib.getDocument(`/api/pdf?name=${encodeURIComponent(name)}&t=${Date.now()}`);
        pdf=await loadingTask.promise;
        const keep=pdf.numPages-skipLast;
        if(keep<1) throw new Error("삭제 후 남는 페이지가 없습니다.");
        const crops=[];
        for(let p=1;p<=keep;p++){
          if(stopRequested) break;
          status.textContent=`${fi+1}/${files.length} · ${p}/${keep} 자동감지\n${name}\n완료 ${completed} · 건너뜀 ${skipped} · 실패 ${failures.length}`;
          crops.push(await detectPage(pdf,p));
        }
        if(stopRequested) break;
        const response=await fetch("/api/crop",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({
            name,
            output_name:outputName,
            all_pages:false,
            page_crops:crops,
            page_limit:keep,
            delete_source:false
          })
        });
        const data=await response.json();
        if(!response.ok) throw new Error(data.error||"저장 실패");
        completed++;
      }catch(error){
        failures.push(`${name}: ${error?.stack || error?.message || error}`);
      }finally{
        try{await pdf?.destroy();}catch(_error){}
        pdf=null;
        ctx.clearRect(0,0,canvas.width,canvas.height);
        canvas.width=1;
        canvas.height=1;
        await yieldToBrowser();
      }
    }
    if(stopRequested){
      status.textContent=`중지됨 · 완료 ${completed}개 · 건너뜀 ${skipped}개 · 실패 ${failures.length}개${failures.length?`\n${failures.join("\n\n")}`:""}`;
    }else{
      status.textContent=`일괄처리 완료 · 완료 ${completed}개 · 건너뜀 ${skipped}개 · 실패 ${failures.length}개${failures.length?`\n${failures.join("\n\n")}`:""}`;
    }
  }catch(error){
    status.textContent=`일괄처리 실패: ${error?.stack || error?.message || error}`;
  }finally{
    startButton.disabled=false;
    stopButton.disabled=true;
    skipInput.disabled=false;
  }
}
startButton.addEventListener("click",run);
stopButton.addEventListener("click",()=>{stopRequested=true;stopButton.disabled=true;stopButton.textContent="중지 요청됨";status.textContent += "\n현재 페이지 처리 후 중지합니다.";setTimeout(()=>{stopButton.textContent="일괄 중지";},1000);});
</script></main></body></html>'''


def list_pdfs() -> list[str]:
    return sorted(
        (p.name for p in IN_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
        key=str.casefold,
    )


def safe_input_path(name: str) -> Path:
    if Path(name).name != name:
        raise ValueError("잘못된 파일명입니다.")
    path = IN_DIR / name
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise FileNotFoundError("PDF를 찾을 수 없습니다.")
    return path


def clean_filename(name: str, fallback: str = "파일") -> str:
    stem = Path(Path(name).name).stem
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    return stem or fallback


def unique_path(directory: Path, filename: str) -> tuple[Path, bool]:
    base = clean_filename(filename, "스캔본")
    suffix = Path(filename).suffix.lower() or ".pdf"
    target = directory / f"{base}{suffix}"
    if not target.exists():
        return target, False
    number = 2
    while True:
        candidate = directory / f"{base}_{number}{suffix}"
        if not candidate.exists():
            return candidate, True
        number += 1


def sevenzip_binary() -> str:
    for command in ("7zz", "7z"):
        found = shutil.which(command)
        if found:
            return found
    raise RuntimeError("7-Zip이 없습니다. Termux에서 `pkg install 7zip`을 실행하세요.")


@app.get("/")
def home():
    return render_template_string(HTML)



def pdf_natural_key(filename):
    """
    파일명의 글자와 숫자를 분리해 자연 정렬한다.

    예:
      책 1.pdf
      책 2.pdf
      책 10.pdf
    """
    parts = re.split(
        r"(\d+)",
        filename.casefold(),
    )

    return tuple(
        (1, int(part))
        if part.isdigit()
        else (0, part)
        for part in parts
    )


@app.get("/batch")
def batch_page():
    return render_template_string(BATCH_HTML)


@app.get("/api/files")
def api_files():
    items = []

    for pdf_path in IN_DIR.iterdir():
        if not (
            pdf_path.is_file()
            and pdf_path.suffix.lower() == ".pdf"
        ):
            continue

        try:
            modified_time = pdf_path.stat().st_mtime
        except OSError:
            modified_time = 0

        items.append(
            {
                "name": pdf_path.name,
                "mtime": modified_time,
            }
        )

    items.sort(
        key=lambda item: (
            pdf_natural_key(item["name"]),
            item["mtime"],
            item["name"].casefold(),
        )
    )

    return jsonify(
        files=[
            item["name"]
            for item in items
        ]
    )



PDFJS_VERSION = "4.10.38"

def find_pdfjs_asset(filename: str) -> Path | None:
    """Locate pdfjs-dist installed locally with npm.

    Supported setup (run beside this app):
        npm install pdfjs-dist@4.10.38
    """
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "node_modules" / "pdfjs-dist" / "build" / filename,
        Path.cwd() / "node_modules" / "pdfjs-dist" / "build" / filename,
        ROOT / "node_modules" / "pdfjs-dist" / "build" / filename,
        Path.home() / "node_modules" / "pdfjs-dist" / "build" / filename,
        Path.home() / ".pdfcrop" / "pdfjs" / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@app.get("/pdfjs/<path:filename>")
def local_pdfjs(filename: str):
    allowed = {"pdf.min.mjs", "pdf.worker.min.mjs"}
    if filename not in allowed:
        return Response("not found", status=404, mimetype="text/plain")
    asset = find_pdfjs_asset(filename)
    if asset is None:
        message = (
            "PDF.js local asset is missing. In Termux, open the folder containing this app and run: "
            f"npm install pdfjs-dist@{PDFJS_VERSION}"
        )
        return Response(message, status=404, mimetype="text/plain")
    return send_file(asset, mimetype="text/javascript", conditional=True, max_age=31536000)


@app.get("/api/pdfjs-status")
def pdfjs_status():
    main = find_pdfjs_asset("pdf.min.mjs")
    worker = find_pdfjs_asset("pdf.worker.min.mjs")
    return jsonify(
        ok=bool(main and worker),
        version=PDFJS_VERSION,
        main=str(main) if main else None,
        worker=str(worker) if worker else None,
        install=f"npm install pdfjs-dist@{PDFJS_VERSION}",
    )


@app.get("/api/pdf")
def api_pdf():
    try:
        return send_file(safe_input_path(request.args.get("name", "")), mimetype="application/pdf", conditional=True)
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.post("/api/import")
def api_import():
    uploads = [item for item in request.files.getlist("files") if item and item.filename]
    if not uploads:
        return jsonify(error="PDF 또는 압축파일이 없습니다."), 400

    password = request.form.get("password", "")
    imported = renamed = skipped = 0
    archive_suffixes = {".zip", ".7z", ".rar", ".cbz", ".cbr"}

    try:
        with tempfile.TemporaryDirectory(prefix="pdfcrop_") as temporary_directory:
            temp = Path(temporary_directory)

            for upload_index, upload in enumerate(uploads):
                original_name = secure_filename(upload.filename) or f"upload_{upload_index}"
                suffix = Path(original_name).suffix.lower()

                if suffix == ".pdf":
                    destination, was_renamed = unique_path(IN_DIR, original_name)
                    upload.save(destination)
                    imported += 1
                    renamed += int(was_renamed)
                    continue

                if suffix not in archive_suffixes:
                    skipped += 1
                    continue

                sevenzip = sevenzip_binary()
                archive_path = temp / f"{upload_index}_{original_name}"
                extract_dir = temp / f"extracted_{upload_index}"
                extract_dir.mkdir()
                upload.save(archive_path)
                command = [sevenzip, "x", str(archive_path), f"-o{extract_dir}", "-y", f"-p{password}" if password else "-p"]
                process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=1800)
                if process.returncode != 0:
                    tail = "\n".join(process.stdout.splitlines()[-8:])
                    raise ValueError(f"{original_name}: 암호가 틀렸거나 지원하지 않는 압축파일입니다.\n{tail}")

                found = 0
                for source in sorted(extract_dir.rglob("*")):
                    if not source.is_file() or source.suffix.lower() != ".pdf":
                        continue
                    destination, was_renamed = unique_path(IN_DIR, source.name)
                    shutil.copy2(source, destination)
                    imported += 1
                    found += 1
                    renamed += int(was_renamed)
                if found == 0:
                    skipped += 1

        if imported == 0:
            raise ValueError("가져올 PDF를 찾지 못했습니다.")
        return jsonify(ok=True, imported=imported, renamed=renamed, skipped=skipped)
    except subprocess.TimeoutExpired:
        return jsonify(error="압축 해제 시간이 너무 오래 걸려 중단했습니다."), 408
    except Exception as error:
        return jsonify(error=str(error)), 400



@app.post("/api/clear-input")
def api_clear_input():
    try:
        deleted = 0

        for item in IN_DIR.iterdir():
            if (
                item.is_file()
                and item.suffix.lower() == ".pdf"
            ):
                item.unlink()
                deleted += 1

        return jsonify(
            ok=True,
            deleted=deleted,
        )

    except Exception as error:
        return jsonify(
            error=str(error)
        ), 400


@app.post("/api/delete-page")
def api_delete_page():
    try:
        body: dict[str, Any] = request.get_json(force=True)
        source = safe_input_path(str(body.get("name", "")))
        page_index = int(body.get("page_index", -1))

        reader = PdfReader(str(source))
        page_total = len(reader.pages)
        if not (0 <= page_index < page_total):
            raise ValueError("삭제할 페이지 번호가 올바르지 않습니다.")

        if page_total == 1:
            source.unlink()
            return jsonify(
                ok=True,
                file_deleted=True,
                pages_remaining=0,
            )

        writer = PdfWriter()
        if reader.metadata:
            try:
                writer.add_metadata(dict(reader.metadata))
            except Exception:
                pass

        for current_index, page in enumerate(reader.pages):
            if current_index != page_index:
                writer.add_page(page)

        temporary = source.with_name(f".{source.name}.delete-page.tmp")
        try:
            with temporary.open("wb") as output:
                writer.write(output)
            temporary.replace(source)
        finally:
            temporary.unlink(missing_ok=True)

        return jsonify(
            ok=True,
            file_deleted=False,
            pages_remaining=page_total - 1,
        )
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.get("/api/output-exists")
def api_output_exists():
    try:
        name = str(request.args.get("name", ""))
        if Path(name).name != name or not name.lower().endswith(".pdf"):
            raise ValueError("잘못된 출력 파일명입니다.")
        return jsonify(exists=(OUT_DIR / name).is_file())
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.post("/api/crop")
def api_crop():
    try:
        body: dict[str, Any] = request.get_json(force=True)
        source = safe_input_path(str(body.get("name", "")))
        output_stem = clean_filename(str(body.get("output_name", "스캔본.pdf")), "스캔본")
        destination, _ = unique_path(OUT_DIR, f"{output_stem}.pdf")
        reader = PdfReader(str(source))
        writer = PdfWriter()
        apply_all = bool(body.get("all_pages", True))
        delete_source = bool(body.get("delete_source", False))
        page_crops = body.get("page_crops")
        page_limit_raw = body.get("page_limit")
        page_limit = len(reader.pages) if page_limit_raw is None else max(0, min(len(reader.pages), int(page_limit_raw)))
        if page_limit <= 0:
            raise ValueError("처리할 페이지가 없습니다.")

        def validated_crop(value: Any) -> tuple[float, float, float, float]:
            if not isinstance(value, dict):
                raise ValueError("크롭 좌표 형식이 올바르지 않습니다.")
            x0, y0, x1, y1 = (float(value[k]) for k in ("x0", "y0", "x1", "y1"))
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError("크롭 좌표가 올바르지 않습니다.")
            return x0, y0, x1, y1

        fixed_crop = None
        if apply_all:
            fixed_crop = validated_crop(body.get("crop") or {})
        else:
            if not isinstance(page_crops, list) or len(page_crops) != page_limit:
                raise ValueError("페이지별 크롭 좌표 수가 PDF 페이지 수와 다릅니다.")

        # 먼저 모든 페이지의 실제 크롭 사각형을 계산한다. 출력 페이지 크기는
        # 가장 큰 크롭 폭/높이로 통일하고, 각 크롭 결과는 그 안에 중앙 배치한다.
        crop_rectangles: list[tuple[float, float, float, float]] = []
        for page_index, page in enumerate(reader.pages[:page_limit]):
            x0, y0, x1, y1 = fixed_crop if apply_all else validated_crop(page_crops[page_index])
            box = page.mediabox
            left, bottom, right, top = map(float, (box.left, box.bottom, box.right, box.top))
            width, height = right - left, top - bottom
            crop_rectangles.append((
                left + width * x0,
                top - height * y1,
                left + width * x1,
                top - height * y0,
            ))

        # 좌우 흰 여백은 만들지 않는다. 각 페이지 폭은 실제 크롭 폭을 그대로 쓰고,
        # 세로 높이만 공통값으로 맞춰 위아래 중심을 안정시킨다.
        target_height = max(top - bottom for left, bottom, right, top in crop_rectangles)

        for page, rectangle in zip(reader.pages[:page_limit], crop_rectangles):
            crop_left, crop_bottom, crop_right, crop_top = rectangle
            crop_width = crop_right - crop_left
            crop_height = crop_top - crop_bottom
            offset_y = (target_height - crop_height) / 2

            crop_box = RectangleObject(rectangle)
            page.cropbox = crop_box
            page.mediabox = crop_box
            output_page = writer.add_blank_page(width=crop_width, height=target_height)
            output_page.merge_translated_page(
                page,
                -crop_left,
                offset_y - crop_bottom,
                expand=False,
            )

        with destination.open("wb") as output:
            writer.write(output)
        if delete_source:
            source.unlink(missing_ok=True)
        return jsonify(ok=True, output_name=destination.name, source_deleted=delete_source, pages=page_limit)
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify(error="압축파일이 서버 제한보다 큽니다. 현재 제한은 8GB입니다."), 413


if __name__ == "__main__":
    print(f"입력 폴더: {IN_DIR}")
    print(f"출력 폴더: {OUT_DIR}")
    print("브라우저에서 http://127.0.0.1:8000")
    app.run(host="127.0.0.1", port=8000, debug=False)
