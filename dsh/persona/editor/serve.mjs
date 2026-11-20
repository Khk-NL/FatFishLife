import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';

const assets = new Map([
  ['/', ['index.html', 'text/html']],
  ['/styles.css', ['styles.css', 'text/css']],
  ['/app.mjs', ['app.mjs', 'text/javascript']],
  ['/model.mjs', ['../model.mjs', 'text/javascript']],
  ['/whale.json', ['../whale.json', 'application/json']],
  ['/vendor/jsoneditor.js', ['node_modules/@json-editor/json-editor/dist/jsoneditor.js', 'text/javascript']],
]);
const port = Number(process.argv[2] ?? 7418);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('端口必须为 1–65535');
const host = '127.0.0.1';
const server = createServer(async (request, response) => {
  if (request.url === '/favicon.ico' && request.headers.host === `${host}:${port}` && request.method === 'GET') {
    response.writeHead(204).end();
    return;
  }
  const asset = assets.get(request.url?.split('?')[0]);
  if (request.headers.host !== `${host}:${port}` || !asset || !['GET', 'HEAD'].includes(request.method)) {
    response.writeHead(404).end();
    return;
  }
  try {
    const body = await readFile(new URL(asset[0], import.meta.url));
    response.writeHead(200, {
      'Content-Type': asset[1] + '; charset=utf-8',
      'Content-Length': body.length,
      'Content-Security-Policy': "default-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
      'X-Content-Type-Options': 'nosniff',
    }).end(request.method === 'HEAD' ? undefined : body);
  } catch (error) {
    response.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8' })
      .end(error.code === 'ENOENT' ? '缺少编辑器依赖，请在编辑器目录运行 npm ci。' : '读取本地资源失败。');
  }
});
server.listen(port, host, () => console.log(`人设编辑器 http://${host}:${port}`));
