import { sections, validateCard, personaPrefix } from './model.mjs';

const byId = id => document.getElementById(id);
const buttons = [];
const editors = new Map();
let active = 'identity';
let currentCard;
const status = (message, failed = false) => {
  byId('status').textContent = message;
  byId('status').toggleAttribute('data-error', failed);
};

function switchSection(key) {
  active = key;
  for (const [name, { panel }] of editors) panel.hidden = name !== key;
  for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.section === key));
}

function update() {
  if ([...editors.values()].some(({ editor }) => !editor.ready)) return;
  try {
    currentCard = validateCard({ version: 1, ...Object.fromEntries(
      [...editors].map(([key, { editor }]) => [key, editor.getValue()]),
    ) });
    const prefix = personaPrefix(currentCard, byId('channel').value);
    byId('persona-name').textContent = currentCard.identity.name;
    byId('preview-body').textContent = prefix;
    byId('character-count').textContent = `${[...prefix].length} 字符`;
    for (const key of ['export', 'copy', 'markdown']) byId(key).disabled = false;
  } catch (error) {
    currentCard = undefined;
    for (const key of ['export', 'copy', 'markdown']) byId(key).disabled = true;
    status(error.message, true);
  }
}

function download(name, body, type) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function start() {
  const response = await fetch('/whale.json');
  if (!response.ok) throw new Error('读取初始人设失败');
  const card = validateCard(await response.json());
  for (const [key, schema] of Object.entries(sections)) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = schema.title;
    button.dataset.section = key;
    button.addEventListener('click', () => switchSection(key));
    buttons.push(button);
    byId('sections').append(button);
    const panel = document.createElement('div');
    byId('forms').append(panel);
    const editor = new window.JSONEditor(panel, {
      schema, startval: card[key], theme: 'html', disable_collapse: true,
      disable_edit_json: true, disable_properties: true, show_errors: 'never',
    });
    editors.set(key, { panel, editor });
    panel.addEventListener('input', event => {
      if (event.target.matches('textarea, input[type="text"]')) {
        event.target.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    editor.on('ready', update);
    editor.on('change', () => { status(''); update(); });
  }
  switchSection(active);
}

byId('import').addEventListener('click', () => byId('file').click());
byId('file').addEventListener('change', async event => {
  try {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 32 * 1024) throw new Error('人设文件超过 32 KB');
    const card = validateCard(JSON.parse((await file.text()).replace(/^\uFEFF/, '')));
    for (const [key, { editor }] of editors) editor.setValue(card[key]);
    update();
    status('已导入人设');
  } catch (error) {
    status('导入失败：' + error.message, true);
  } finally { event.target.value = ''; }
});
byId('channel').addEventListener('change', update);
byId('export').addEventListener('click', () => {
  if (currentCard) download('fatfish-persona.json', JSON.stringify(currentCard, null, 2) + '\n', 'application/json');
});
byId('markdown').addEventListener('click', () => {
  if (currentCard) download(`fatfish-${byId('channel').value}.md`, byId('preview-body').textContent + '\n', 'text/markdown');
});
byId('copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(byId('preview-body').textContent);
    status('已复制预览');
  } catch { status('剪贴板不可用，可以下载 Markdown。', true); }
});
if (window.JSONEditor) start().catch(error => status(error.message, true));
else status('编辑器组件未载入，请先运行 npm ci。', true);
