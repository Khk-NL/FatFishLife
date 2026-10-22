const $ = (id) => document.getElementById(id);
const canvas = $("stage"), ctx = canvas.getContext("2d"), SIZE = 1024;
const makeCanvas = () => Object.assign(document.createElement("canvas"), { width: SIZE, height: SIZE });
const characterLayer = makeCanvas(), faceLayer = makeCanvas(), maskLayer = makeCanvas(), repairLayer = makeCanvas();
const baseLayer = makeCanvas(), hairLayer = makeCanvas();
const state = {
  catalog: [], character: null, characterImage: null, baseImage: null, hairImage: null, faceImage: null, variant: "front", mode: "move",
  x: 0.54, y: 0.27, width: 200, height: 230, angle: 0, feather: 0.05, opacity: 1,
  sourceZoom: 1, sourceX: 0.5, sourceY: 0.5, brush: 35, strokes: [], compare: false,
  drag: null, imageVersion: 0, musicBlob: null, musicUrl: null, musicName: "", imageObjectUrl: null, faceObjectUrl: null,
};
let toastTimer;
function toast(message, error = false, persistent = false) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").classList.toggle("error", error);
  $("toast").hidden = false;
  if (!persistent) toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 7000 : 4000);
}
function loadImage(source) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("图片载入失败，请更换素材或切换头像／半身图。"));
    image.src = source;
  });
}
function fileAllowed(file) {
  if (!file || !file.size) throw new Error("文件为空，请重新选择。");
  if (file.size > 50 * 1024 * 1024) throw new Error("单个文件最大 50 MB。");
}
function fileData(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("无法读取本地文件。"));
    reader.readAsDataURL(blob);
  });
}
function download(url, name) {
  const link = document.createElement("a");
  link.href = url; link.download = name;
  document.body.append(link); link.click(); link.remove();
}
function fit(image, target) {
  const scale = Math.min(SIZE / image.naturalWidth, SIZE / image.naturalHeight);
  const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
  target.drawImage(image, (SIZE - width) / 2, (SIZE - height) / 2, width, height);
}
function buildLayers() {
  const original = characterLayer.getContext("2d");
  original.clearRect(0, 0, SIZE, SIZE);
  if (state.characterImage) fit(state.characterImage, original);
  for (const [layer, image] of [[baseLayer, state.baseImage || state.characterImage], [hairLayer, state.hairImage]]) {
    const target = layer.getContext("2d"); target.clearRect(0, 0, SIZE, SIZE);
    if (image) fit(image, target);
  }
  const face = faceLayer.getContext("2d");
  face.clearRect(0, 0, SIZE, SIZE);
  if (!state.faceImage) return;
  const image = state.faceImage;
  const cropWidth = image.naturalWidth / state.sourceZoom, cropHeight = image.naturalHeight / state.sourceZoom;
  const left = Math.max(0, Math.min(image.naturalWidth - cropWidth, state.sourceX * image.naturalWidth - cropWidth / 2));
  const top = Math.max(0, Math.min(image.naturalHeight - cropHeight, state.sourceY * image.naturalHeight - cropHeight / 2));
  face.save(); face.beginPath(); face.arc(SIZE / 2, SIZE / 2, SIZE / 2, 0, Math.PI * 2); face.clip();
  face.drawImage(image, left, top, cropWidth, cropHeight, 0, 0, SIZE, SIZE); face.restore();
  const thumb = $("faceThumb").getContext("2d");
  thumb.clearRect(0, 0, 100, 100); thumb.drawImage(faceLayer, 0, 0, 100, 100);
  face.globalCompositeOperation = "destination-in";
  if (state.feather > 0) {
    const gradient = face.createRadialGradient(SIZE / 2, SIZE / 2, SIZE / 2 * (1 - state.feather), SIZE / 2, SIZE / 2, SIZE / 2);
    gradient.addColorStop(0, "rgba(0,0,0,1)"); gradient.addColorStop(1, "rgba(0,0,0,0)");
    face.fillStyle = gradient; face.fillRect(0, 0, SIZE, SIZE);
  }
  face.globalCompositeOperation = "source-over";
}
function buildMask() {
  const mask = maskLayer.getContext("2d"); mask.clearRect(0, 0, SIZE, SIZE);
  for (const stroke of state.strokes) {
    mask.globalCompositeOperation = stroke.erase ? "destination-out" : "source-over";
    mask.strokeStyle = "#fff"; mask.fillStyle = "#fff"; mask.lineWidth = stroke.size;
    mask.lineCap = "round"; mask.lineJoin = "round";
    mask.beginPath(); mask.moveTo(stroke.points[0].x, stroke.points[0].y);
    for (const point of stroke.points.slice(1)) mask.lineTo(point.x, point.y);
    mask.stroke();
    for (const point of [stroke.points[0], stroke.points.at(-1)]) {
      mask.beginPath(); mask.arc(point.x, point.y, stroke.size / 2, 0, Math.PI * 2); mask.fill();
    }
  }
  mask.globalCompositeOperation = "source-over";
  const repair = repairLayer.getContext("2d"); repair.clearRect(0, 0, SIZE, SIZE);
  repair.drawImage(characterLayer, 0, 0);
  repair.globalCompositeOperation = "destination-in"; repair.drawImage(maskLayer, 0, 0);
  repair.globalCompositeOperation = "source-over";
}
function paint(target, guides = false, originalOnly = false) {
  target.clearRect(0, 0, SIZE, SIZE);
  if (!$("transparent").checked) { target.fillStyle = $("background").value; target.fillRect(0, 0, SIZE, SIZE); }
  if (originalOnly) { target.drawImage(characterLayer, 0, 0); return; }
  if ($("showBase").checked) target.drawImage(baseLayer, 0, 0);
  const paintHair = () => { if ($("showHair").checked) { target.drawImage(hairLayer, 0, 0); target.drawImage(repairLayer, 0, 0); } };
  if ($("faceOnTop").checked) paintHair();
  if (state.faceImage && $("showFace").checked) {
    target.save(); target.translate(state.x * SIZE, state.y * SIZE); target.rotate(state.angle * Math.PI / 180);
    target.globalAlpha = state.opacity;
    target.drawImage(faceLayer, -state.width / 2, -state.height / 2, state.width, state.height);
    target.restore();
    if (guides) {
      target.save(); target.translate(state.x * SIZE, state.y * SIZE); target.rotate(state.angle * Math.PI / 180);
      target.strokeStyle = "rgba(255,255,255,.9)"; target.lineWidth = 2; target.setLineDash([8, 7]);
      target.beginPath(); target.ellipse(0, 0, state.width / 2 + 4, state.height / 2 + 4, 0, 0, Math.PI * 2); target.stroke();
      target.setLineDash([]); target.fillStyle = "#fff";
      for (const [x, y] of [[-state.width / 2, 0], [state.width / 2, 0], [0, -state.height / 2], [0, state.height / 2]]) target.fillRect(x - 4, y - 4, 8, 8);
      target.restore();
    }
  }
  if (!$("faceOnTop").checked) paintHair();
}
function draw() { paint(ctx, $("guides").checked, state.compare); }
function syncControls() {
  const values = {
    faceWidth: [state.width, `${Math.round(state.width)} px`], faceHeight: [state.height, `${Math.round(state.height)} px`],
    faceRotation: [state.angle, `${Math.round(state.angle)}°`], feather: [state.feather * 100, `${Math.round(state.feather * 100)}%`],
    faceX: [state.x * 100, `${Math.round(state.x * 100)}%`], faceY: [state.y * 100, `${Math.round(state.y * 100)}%`],
    sourceX: [state.sourceX * 100, `${Math.round(state.sourceX * 100)}%`], sourceY: [state.sourceY * 100, `${Math.round(state.sourceY * 100)}%`],
    sourceZoom: [state.sourceZoom, `${state.sourceZoom.toFixed(2)}×`], opacity: [state.opacity * 100, `${Math.round(state.opacity * 100)}%`],
    brushSize: [state.brush, `${state.brush} px`],
  };
  for (const [id, [value, text]] of Object.entries(values)) { $(id).value = value; $(`${id}Value`).textContent = text; }
}
function resetFace() {
  const icon = state.variant === "icon";
  Object.assign(state, icon ? { x: .56, y: .49, width: 370, height: 390, angle: 0 } : { x: .54, y: .27, width: 200, height: 230, angle: 0 });
  if (state.character?.id === "1006") Object.assign(state, icon ? { x: .60, y: .50, width: 370, height: 400, angle: -8 } : { x: .53, y: .27, width: 185, height: 200, angle: 0 });
  if (state.variant === "front" && state.character?.front) {
    const preset = state.character.front, image = state.characterImage;
    const scale = Math.min(SIZE / image.naturalWidth, SIZE / image.naturalHeight);
    const [x, y, width, height] = preset.face;
    Object.assign(state, { x: .5 + (x - .5) * image.naturalWidth * scale / SIZE,
      y: .5 + (y - .5) * image.naturalHeight * scale / SIZE,
      width: width * image.naturalWidth * scale * 1.04, height: height * image.naturalHeight * scale * 1.04, angle: 0 });
    if (state.faceImage) {
      const ratio = state.faceImage.naturalWidth / state.faceImage.naturalHeight;
      const fittedHeight = Math.max(state.height, state.width / ratio);
      state.height = fittedHeight; state.width = fittedHeight * ratio;
    }
  }
  state.strokes = []; state.compare = false;
  $("compare").textContent = "查看原图"; $("compare").setAttribute("aria-pressed", "false");
  syncControls(); buildLayers(); buildMask(); draw();
}
function renderCatalog() {
  const query = $("search").value.trim().toLowerCase();
  const characters = state.catalog.filter(c => (state.variant !== "front" || c.front) && `${c.name} ${c.tag} ${c.id}`.toLowerCase().includes(query));
  $("characterCount").textContent = `${characters.length} 位`;
  $("emptySearch").hidden = characters.length !== 0;
  const fragment = document.createDocumentFragment();
  for (const character of characters) {
    const button = document.createElement("button"); button.className = "character-card";
    button.classList.toggle("selected", state.character?.id === character.id);
    button.setAttribute("aria-label", `选择${character.name}`); button.title = character.name;
    const image = document.createElement("img"); image.src = state.variant === "front" ? character.front.front : character.icon; image.alt = ""; image.loading = "lazy";
    const label = document.createElement("span"); label.textContent = character.name;
    button.append(image, label); button.addEventListener("click", () => selectCharacter(character)); fragment.append(button);
  }
  $("characterGrid").replaceChildren(fragment);
}
async function selectCharacter(character) {
  const version = ++state.imageVersion;
  try {
    const front = state.variant === "front" ? character.front : null;
    if (state.variant === "front" && !front && character.id !== "custom") throw new Error("这个角色还没有经过校准的正面模型素材。");
    const [image, base, hair] = await Promise.all([loadImage(front ? front.front : character.preview),
      front ? loadImage(front.base) : Promise.resolve(null), front ? loadImage(front.hair) : Promise.resolve(null)]);
    if (version !== state.imageVersion) return;
    state.character = character; state.characterImage = image; state.baseImage = base; state.hairImage = hair;
    $("editorTitle").textContent = character.name;
    renderCatalog(); resetFace();
  } catch (error) { if (version === state.imageVersion) toast(error.message, true); }
}
function setVariant(variant) {
  state.variant = variant;
  for (const [id, value] of [["usePreview", "preview"], ["useIcon", "front"]]) {
    $(id).classList.toggle("active", value === variant); $(id).setAttribute("aria-pressed", String(value === variant));
  }
  renderCatalog();
  $("materialMode").textContent = variant === "front" ? "正面模型头像 · 4 个已校准" : "立绘备用 · 不保证正脸";
  const character = variant === "front" && !state.character?.front ? state.catalog.find(c => c.front) : state.character;
  if (character) selectCharacter(character);
}
function setMode(mode) {
  state.mode = mode;
  for (const [id, value] of [["moveTool", "move"], ["restoreTool", "restore"], ["eraseTool", "erase"]]) {
    $(id).classList.toggle("active", mode === value); $(id).setAttribute("aria-pressed", String(mode === value));
  }
  canvas.classList.toggle("brushing", mode !== "move");
  $("toolHint").textContent = mode === "move" ? "拖动脸部调整位置，右侧调节大小与角度" : mode === "restore" ? "涂抹刘海、饰品等区域，画回角色原图" : "擦除修补区域，重新露出脸部";
}
function pointer(event) {
  const rect = canvas.getBoundingClientRect();
  return { x: Math.max(0, Math.min(SIZE, (event.clientX - rect.left) / rect.width * SIZE)), y: Math.max(0, Math.min(SIZE, (event.clientY - rect.top) / rect.height * SIZE)) };
}
canvas.addEventListener("pointerdown", event => {
  if (!state.characterImage || state.compare) return;
  event.preventDefault(); canvas.setPointerCapture(event.pointerId);
  const point = pointer(event);
  state.drag = { x: point.x, y: point.y, faceX: state.x, faceY: state.y };
  if (state.mode !== "move") { state.strokes.push({ erase: state.mode === "erase", size: state.brush, points: [point] }); buildMask(); draw(); }
});
canvas.addEventListener("pointermove", event => {
  if (!state.drag) return;
  const point = pointer(event);
  if (state.mode === "move") {
    state.x = Math.max(0, Math.min(1, state.drag.faceX + (point.x - state.drag.x) / SIZE));
    state.y = Math.max(0, Math.min(1, state.drag.faceY + (point.y - state.drag.y) / SIZE)); syncControls();
  } else { state.strokes.at(-1).points.push(point); buildMask(); }
  draw();
});
for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) canvas.addEventListener(event, () => { state.drag = null; });
canvas.addEventListener("keydown", event => {
  const deltas = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  if (!deltas[event.key]) return;
  event.preventDefault(); const [x, y] = deltas[event.key], step = (event.shiftKey ? 10 : 1) / SIZE;
  state.x = Math.max(0, Math.min(1, state.x + x * step)); state.y = Math.max(0, Math.min(1, state.y + y * step)); syncControls(); draw();
});
const rangeBindings = { faceWidth: ["width", 1], faceHeight: ["height", 1], faceRotation: ["angle", 1], feather: ["feather", 100],
  faceX: ["x", 100], faceY: ["y", 100], sourceX: ["sourceX", 100], sourceY: ["sourceY", 100], sourceZoom: ["sourceZoom", 1], opacity: ["opacity", 100], brushSize: ["brush", 1] };
for (const [id, [key, divisor]] of Object.entries(rangeBindings)) $(id).addEventListener("input", () => {
  state[key] = Number($(id).value) / divisor; syncControls(); buildLayers(); draw();
});
$("search").addEventListener("input", renderCatalog);
$("usePreview").onclick = () => setVariant("preview"); $("useIcon").onclick = () => setVariant("front");
$("moveTool").onclick = () => setMode("move"); $("restoreTool").onclick = () => setMode("restore"); $("eraseTool").onclick = () => setMode("erase");
$("undoBrush").onclick = () => { state.strokes.pop(); buildMask(); draw(); };
$("resetFace").onclick = resetFace;
$("compare").onclick = () => { state.compare = !state.compare; $("compare").textContent = state.compare ? "返回合成" : "查看原图"; $("compare").setAttribute("aria-pressed", String(state.compare)); draw(); };
for (const id of ["background", "transparent", "guides", "showBase", "showHair", "showFace", "faceOnTop"]) $(id).addEventListener("input", draw);
$("characterFile").onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    fileAllowed(file); const url = URL.createObjectURL(file), image = await loadImage(url);
    if (state.imageObjectUrl) URL.revokeObjectURL(state.imageObjectUrl);
    state.imageObjectUrl = url; ++state.imageVersion;
    state.character = { id: "custom", name: file.name, icon: url, preview: url };
    state.characterImage = image; state.baseImage = null; state.hairImage = null; $("editorTitle").textContent = file.name; renderCatalog(); resetFace();
  } catch (error) { toast(error.message, true); }
  event.target.value = "";
};
$("faceFile").onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    fileAllowed(file); toast("正在本机检测正脸并裁去身体…", false, true);
    const result = await post("/api/crop-face", { image: { data: await fileData(file) } });
    const url = result.url, image = await loadImage(url);
    if (state.faceObjectUrl) URL.revokeObjectURL(state.faceObjectUrl);
    state.faceObjectUrl = url; state.faceImage = image;
    state.sourceX = .5; state.sourceY = .5; state.sourceZoom = 1;
    resetFace(); toast(`已自动裁出脸部 ${result.size[0]} × ${result.size[1]}，未使用身体区域。`);
  } catch (error) { toast(error.message, true); }
  event.target.value = "";
};
function exportedImage() {
  if (!state.characterImage || !state.faceImage) throw new Error("请等待角色与脸部素材载入。");
  const output = makeCanvas(); paint(output.getContext("2d")); return output;
}
$("downloadPng").onclick = () => {
  try {
    exportedImage().toBlob(blob => {
      if (!blob) return toast("图片导出失败。", true);
      const url = URL.createObjectURL(blob); download(url, `fatfish-${state.character.id}.png`);
      setTimeout(() => URL.revokeObjectURL(url), 60000); toast("合成角色 PNG 已导出，参考线不会出现在图片中。");
    }, "image/png");
  } catch (error) { toast(error.message, true); }
};
for (const [button, panel] of [["faceTab", "faceSettings"], ["musicTab", "musicSettings"]]) $(button).onclick = () => {
  for (const [id, target] of [["faceTab", "faceSettings"], ["musicTab", "musicSettings"]]) {
    const active = id === button; $(id).classList.toggle("active", active); $(id).setAttribute("aria-selected", String(active)); $(target).hidden = !active;
  }
};

const audio = $("audio");
function timeLabel(value) { value = Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0; return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`; }
function updateMusic() {
  const speed = Number($("musicSpeed").value), volume = Number($("volume").value) / 100;
  audio.playbackRate = speed; audio.preservesPitch = $("preservePitch").checked; audio.volume = volume;
  $("musicSpeedValue").textContent = `${speed.toFixed(2)}×`; $("volumeValue").textContent = `${Math.round(volume * 100)}%`;
  document.querySelectorAll("[data-speed]").forEach(button => button.classList.toggle("active", Math.abs(Number(button.dataset.speed) - speed) < .001));
  if (Number.isFinite(audio.duration)) $("adjustedDuration").textContent = `原曲 ${timeLabel(audio.duration)} · 调速后约 ${timeLabel(audio.duration / speed)} · ${audio.preservesPitch ? "保留原调" : "随加速升调"}`;
}
function loadMusic(blob, name) {
  audio.pause(); if (state.musicUrl) URL.revokeObjectURL(state.musicUrl);
  state.musicBlob = blob; state.musicName = name; state.musicUrl = URL.createObjectURL(blob);
  audio.src = state.musicUrl; audio.load();
  $("musicName").textContent = name; $("playMusic").disabled = false; $("exportAudio").disabled = false; $("seek").disabled = false; updateMusic();
}
$("musicFile").onchange = event => { const file = event.target.files[0]; if (!file) return; try { fileAllowed(file); loadMusic(file, file.name); } catch (error) { toast(error.message, true); } event.target.value = ""; };
$("demoMusic").onclick = async () => { try { const response = await fetch("/assets/music/demo-original.wav"); if (!response.ok) throw new Error("测试音乐不存在。"); loadMusic(await response.blob(), "原创测试小曲.wav"); toast("已载入原创合成测试音乐，可自行导入崩铁音乐替换。"); } catch (error) { toast(error.message, true); } };
$("playMusic").onclick = async () => { try { if (audio.paused) await audio.play(); else audio.pause(); } catch (error) { toast(`音乐无法播放：${error.message}`, true); } };
for (const event of ["play", "pause", "ended"]) audio.addEventListener(event, () => { $("playIcon").src = `/assets/icons/${audio.paused ? "play" : "pause"}.svg`; $("playMusic").setAttribute("aria-label", audio.paused ? "播放音乐" : "暂停音乐"); });
audio.addEventListener("loadedmetadata", () => { $("totalTime").textContent = timeLabel(audio.duration); updateMusic(); });
audio.addEventListener("timeupdate", () => { $("currentTime").textContent = timeLabel(audio.currentTime); $("seek").value = Number.isFinite(audio.duration) ? audio.currentTime / audio.duration * 1000 : 0; });
audio.addEventListener("error", () => toast("浏览器无法解码这段音乐，请换用 MP3 或 WAV。", true));
$("seek").oninput = () => { if (Number.isFinite(audio.duration)) audio.currentTime = Number($("seek").value) / 1000 * audio.duration; };
for (const id of ["musicSpeed", "preservePitch", "volume"]) $(id).addEventListener("input", updateMusic);
document.querySelectorAll("[data-speed]").forEach(button => button.onclick = () => { $("musicSpeed").value = button.dataset.speed; updateMusic(); });
$("caption").oninput = () => { $("captionPreview").textContent = $("caption").value || "无字幕"; };
$("duration").oninput = () => { $("durationValue").textContent = `${$("duration").value} 秒`; };

async function payload() {
  return { music: state.musicBlob ? { name: state.musicName, data: await fileData(state.musicBlob) } : null,
    speed: Number($("musicSpeed").value), preserve_pitch: $("preservePitch").checked, volume: Number($("volume").value) / 100 };
}
async function post(url, data) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  const result = await response.json(); if (!response.ok) throw new Error(result.error || "操作失败"); return result;
}
$("exportAudio").onclick = async () => {
  const button = $("exportAudio"); button.disabled = true; toast("正在生成调速后的音乐…", false, true);
  try { const result = await post("/api/export-audio", await payload()); download(result.url, result.filename); toast("WAV 已生成，速度与当前试听设置一致。"); }
  catch (error) { toast(error.message, true); }
  finally { button.disabled = !state.musicBlob; }
};
$("renderVideo").onclick = async () => {
  const button = $("renderVideo"); button.disabled = true;
  try {
    const image = exportedImage().toDataURL("image/png");
    toast("正在生成本地测试视频，请稍候…", false, true);
    const result = await post("/api/render", { ...await payload(), image: { data: image }, caption: $("caption").value,
      duration: Number($("duration").value), background: $("background").value });
    $("videoResult").hidden = false; $("resultPlayer").src = result.url; $("resultPlayer").poster = result.cover;
    $("videoDownload").href = result.url; $("videoDownload").download = result.filename;
    $("videoResult").scrollIntoView({ behavior: "smooth", block: "nearest" }); toast("测试视频已生成，可以预览或下载。");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
};

async function initialize() {
  $("downloadPng").disabled = true; $("renderVideo").disabled = true;
  try {
    const response = await fetch("/api/characters"); const catalog = await response.json();
    if (!response.ok) throw new Error(catalog.error);
    state.catalog = catalog.characters; renderCatalog();
    $("useIcon").classList.add("active"); $("useIcon").setAttribute("aria-pressed", "true");
    $("usePreview").classList.remove("active"); $("usePreview").setAttribute("aria-pressed", "false");
    state.faceImage = await loadImage("/assets/web/kobe-face.png");
    await selectCharacter(state.catalog.find(c => c.id === "1006") || state.catalog[0]);
    if (!state.characterImage) throw new Error("角色图片尚未加载成功。");
    syncControls(); updateMusic(); $("downloadPng").disabled = false; $("renderVideo").disabled = false;
  } catch (error) { $("editorTitle").textContent = "素材暂不可用"; toast(error.message, true, true); }
}
initialize();
