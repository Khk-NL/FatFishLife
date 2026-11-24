import { access } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const documentLink = /https:\/\/(?:[a-z0-9-]+\.)*feishu\.cn\/(wiki|docx)\/([a-z0-9]{8,80})(?![a-z0-9/_-])/giu;
const cliPath = 'D:/Code/Projects/FatFishLife/.tools/feishu-1.0.100/lark-cli.exe';
const configPath = 'D:/DSHData/private/feishu-cli';

export function feishuLinks(text) {
  return [...new Set(Array.from(String(text ?? '').matchAll(documentLink), match => match[0]))];
}

async function readApi(path, params, signal) {
  try {
    const { stdout } = await execute(cliPath, ['api', 'GET', path, '--as', 'user', '--format', 'json',
      ...(params ? ['--params', JSON.stringify(params)] : [])], {
      encoding: 'utf-8', windowsHide: true, maxBuffer: 2 * 1024 * 1024, timeout: 12_000, signal,
      env: { ...process.env, LARKSUITE_CLI_CONFIG_DIR: configPath },
    });
    const result = JSON.parse(stdout);
    if (!result || typeof result.data !== 'object' || !result.data || result.ok === false || result.code && result.code !== 0) {
      return { ok: false, reason: '飞书没有返回可确认的读取结果' };
    }
    return { ok: true, data: result.data };
  } catch (error) {
    const diagnostic = String(error.stderr || error.stdout || '').slice(0, 4096);
    if (error.killed || error.code === 'ABORT_ERR') return { ok: false, reason: '飞书读取超时或已经取消' };
    if (/not authenticated|auth login|not logged|unauthenticated|token expired|state expired|cli is not configured|config init/iu.test(diagnostic)) {
      return { ok: false, reason: '本机飞书只读授权还未完成或已失效，请重新授权后再试' };
    }
    if (/forbidden|scope|access denied|permission|无权限/iu.test(diagnostic)) {
      return { ok: false, reason: '当前飞书账号或应用没有权限读取这页，请在飞书核对页面权限和只读授权' };
    }
    return { ok: false, reason: '飞书 API 读取失败，正文状态未确认' };
  }
}

export async function readFeishuDocument(link, { signal, request = readApi, ready = () => access(cliPath) } = {}) {
  const [candidate] = feishuLinks(link);
  if (candidate !== link || !candidate) return { ok: false, reason: '请提供飞书 Wiki 或云文档链接' };
  try { await ready(); }
  catch { return { ok: false, reason: '本机飞书官方命令行组件还未就绪' }; }
  const [type, token] = new URL(link).pathname.slice(1).split('/');
  let document = token;
  if (type === 'wiki') {
    const result = await request('/open-apis/wiki/v2/spaces/get_node', { token }, signal);
    if (!result.ok) return result;
    const node = result.data.node;
    if (node?.obj_type !== 'docx' || !/^[a-z0-9]{8,80}$/iu.test(node.obj_token ?? '')) {
      return { ok: false, reason: '这个知识库页面没有可读取的新版云文档正文' };
    }
    document = node.obj_token;
  }
  const result = await request(`/open-apis/docx/v1/documents/${document}/raw_content`, null, signal);
  if (!result.ok) return result;
  const content = result.data.content;
  if (typeof content !== 'string') return { ok: false, reason: '飞书没有返回文档正文' };
  const limit = 16000;
  return { ok: true, source: link, content: content.slice(0, limit), truncated: content.length > limit };
}
