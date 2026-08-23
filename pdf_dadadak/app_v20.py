from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request, send_file
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
<label><input id="lockAutoWidth" type="checkbox"> 가로 고정</label>
<label><input id="lockAutoHeight" type="checkbox"> 세로 고정</label>
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
import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.min.mjs";
pdfjsLib.GlobalWorkerOptions.workerSrc="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.worker.min.mjs";

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
    const verticalCandidates = [];
    const horizontalCandidates = [];
    const verticalMinimum = Math.max(12, Math.floor(gridHeight * 0.16));
    const horizontalMinimum = Math.max(12, Math.floor(gridWidth * 0.16));

    /* 3셀 너비 안에 선이 있으면 같은 선으로 본다. 스캔 흔들림과 끊김 보정용. */
    for (let gx = 0; gx < gridWidth; gx++) {
      const run = longestRunWithGaps(gy => {
        if (gy < startRow) return false;
        for (let dx = -1; dx <= 1; dx++) {
          const nx = gx + dx;
          if (nx >= 0 && nx < gridWidth && cleaned[gy * gridWidth + nx]) return true;
        }
        return false;
      }, gridHeight, 2);
      if (run >= verticalMinimum) verticalCandidates.push(gx);
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

    if (verticalCandidates.length < 2 || horizontalCandidates.length < 2) return null;

    const left = verticalCandidates[0];
    const right = verticalCandidates[verticalCandidates.length - 1];
    const top = horizontalCandidates[0];
    const bottom = horizontalCandidates[horizontalCandidates.length - 1];

    const widthRatio = (right - left + 1) / gridWidth;
    const heightRatio = (bottom - top + 1) / gridHeight;

    /* 글자 열이나 작은 장식선을 큰 외곽으로 오인하지 않게 최소 면적을 요구한다. */
    if (widthRatio < 0.42 || heightRatio < 0.42) return null;

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
   * 컷선이 있으면 그것을 기본 사각형으로 쓰되,
   * 컷선 밖에서 유효한 글자/그림이 감지되면 가장 바깥쪽까지 확장한다.
   * 컷선이 없으면 기존 전경 분포 감지 결과를 그대로 사용한다.
   */
  const horizontal = panelBounds
    ? {
        start: foregroundHorizontal
          ? Math.min(panelBounds.left, foregroundHorizontal.start)
          : panelBounds.left,
        end: foregroundHorizontal
          ? Math.max(panelBounds.right, foregroundHorizontal.end)
          : panelBounds.right
      }
    : foregroundHorizontal;

  const vertical = panelBounds
    ? {
        start: foregroundVertical
          ? Math.min(panelBounds.top, foregroundVertical.start)
          : panelBounds.top,
        end: foregroundVertical
          ? Math.max(panelBounds.bottom, foregroundVertical.end)
          : panelBounds.bottom
      }
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
    lockedAutoX = { x0: crop.x0, x1: crop.x1 };
    $("status").textContent = `가로 좌표 x0/x1을 고정했습니다 · 이제 위아래만 조정됩니다 · 저장 이름: ${outputName()}`;
  } else {
    lockedAutoX = null;
    $("status").textContent = `가로 좌표 고정을 해제했습니다 · 저장 이름: ${outputName()}`;
  }
});

$("lockAutoHeight").addEventListener("change", () => {
  if ($("lockAutoHeight").checked) {
    lockedAutoY = { y0: crop.y0, y1: crop.y1 };
    $("status").textContent = `세로 좌표 y0/y1을 고정했습니다 · 이제 좌우만 조정됩니다 · 저장 이름: ${outputName()}`;
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

        def validated_crop(value: Any) -> tuple[float, float, float, float]:
            if not isinstance(value, dict):
                raise ValueError("크롭 좌표 형식이 올바르지 않습니다.")
            x0, y0, x1, y1 = (float(value[k]) for k in ("x0", "y0", "x1", "y1"))
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError("크롭 좌표가 올바르지 않습니다.")
            return x0, y0, x1, y1

        fixed_crop = validated_crop(body.get("crop") or {})
        if not apply_all:
            if not isinstance(page_crops, list) or len(page_crops) != len(reader.pages):
                raise ValueError("페이지별 크롭 좌표 수가 PDF 페이지 수와 다릅니다.")

        for page_index, page in enumerate(reader.pages):
            x0, y0, x1, y1 = fixed_crop if apply_all else validated_crop(page_crops[page_index])
            box = page.mediabox
            left, bottom, right, top = map(float, (box.left, box.bottom, box.right, box.top))
            width, height = right - left, top - bottom
            page.cropbox = RectangleObject((
                left + width * x0,
                top - height * y1,
                left + width * x1,
                top - height * y0,
            ))
            writer.add_page(page)

        with destination.open("wb") as output:
            writer.write(output)
        if delete_source:
            source.unlink(missing_ok=True)
        return jsonify(ok=True, output_name=destination.name, source_deleted=delete_source, pages=len(reader.pages))
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
