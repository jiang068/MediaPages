import { onRequest as serveStream } from '../../range_stream.js';

const catalogs = new WeakMap();
const encodeSegment = value => encodeURIComponent(value).replace(/[!'()*]/g, char => '%' + char.charCodeAt(0).toString(16).toUpperCase());

function canonicalPath(path) {
  try {
    return path.replace(/\/+$/, '').split('/').map(segment => encodeSegment(decodeURIComponent(segment))).join('/');
  } catch (_error) { return null; }
}

function responseWithVary(response) {
  const headers = new Headers(response.headers);
  const vary = headers.get('Vary');
  if (!vary || !vary.split(',').some(value => value.trim().toLowerCase() === 'accept')) headers.set('Vary', vary ? vary + ', Accept' : 'Accept');
  headers.set('Cache-Control', 'private, no-store, no-transform');
  headers.set('Cloudflare-CDN-Cache-Control', 'no-store');
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

async function routes(env, request) {
  const cached = catalogs.get(env.ASSETS);
  if (cached && cached.expires > Date.now()) return cached.promise;
  const promise = (async () => {
    const response = await env.ASSETS.fetch(new Request(new URL('/player/media-routes.json', request.url)));
    if (!response.ok) throw new Error('Media route catalog unavailable');
    return (await response.json()).routes || {};
  })();
  catalogs.set(env.ASSETS, { promise, expires: Date.now() + 60000 });
  try { return await promise; }
  catch (error) { catalogs.delete(env.ASSETS); throw error; }
}

function wantsPage(request, url) {
  if (url.searchParams.get('raw') === '1' || request.headers.has('Range')) return false;
  return (request.headers.get('Accept') || '').split(',').some(part => {
    const [type, ...parameters] = part.split(';');
    const quality = parameters.find(value => /^\s*q\s*=/i.test(value));
    return type.trim().toLowerCase() === 'text/html' && (!quality || Number(quality.split('=')[1]) > 0);
  });
}

export async function onRequest({ request, env }) {
  if (request.method === 'OPTIONS') return responseWithVary(await serveStream({ request, env, params: {} }));
  if (!['GET', 'HEAD'].includes(request.method)) return responseWithVary(new Response('Method not allowed', { status: 405, headers: { Allow: 'GET, HEAD, OPTIONS' } }));
  const url = new URL(request.url);
  if (wantsPage(request, url)) {
    const entry = new URL('/', url);
    return responseWithVary(await env.ASSETS.fetch(new Request(entry, request)));
  }
  try {
    const catalog = await routes(env, request);
    const path = canonicalPath(url.pathname);
    const route = path && Object.hasOwn(catalog, path) && catalog[path];
    if (!route) return responseWithVary(new Response('Media not found', { status: 404 }));
    const source = new URL(route.src, new URL('/', url));
    if (route.streamId) {
      // Use the same byte-exact Range implementation as /stream/<id>.
      return responseWithVary(await serveStream({ request: new Request(source, request), env, params: { file: route.streamId } }));
    }
    // Static MP4/WebM/HLS URLs remain served directly by the asset platform.
    return responseWithVary(new Response(null, { status: 307, headers: { Location: source.href } }));
  } catch (_error) {
    return responseWithVary(new Response('Media stream unavailable', { status: 503 }));
  }
}
