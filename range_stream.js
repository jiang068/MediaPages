const FIRST_OUTPUT_BYTES = 64 * 1024;
const STREAM_OUTPUT_BYTES = 1024 * 1024;
const manifests = new WeakMap();
const NO_CACHE = {
  'Cache-Control': 'private, no-store, no-transform',
  'Cloudflare-CDN-Cache-Control': 'no-store'
};
const cors = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
  'Access-Control-Allow-Headers': 'Range, If-Range, If-None-Match',
  'Access-Control-Expose-Headers': 'Accept-Ranges, Content-Length, Content-Range, ETag',
  'Access-Control-Max-Age': '86400'
};

function textResponse(message, status) {
  return new Response(message, {
    status,
    headers: { ...cors, ...NO_CACHE, 'Content-Type': 'text/plain; charset=utf-8' }
  });
}

function parseRange(header, size) {
  const match = /^bytes=(\d*)-(\d*)$/.exec((header || '').trim());
  if (!match || (!match[1] && !match[2]) || size <= 0) return null;
  let start, end;
  if (match[1]) {
    start = Number(match[1]);
    end = match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  } else {
    const suffix = Number(match[2]);
    if (!Number.isSafeInteger(suffix) || suffix <= 0) return null;
    start = Math.max(0, size - suffix);
    end = size - 1;
  }
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || start >= size || end < start) return null;
  return { start, end };
}

async function getManifest(env, request) {
  const cached = manifests.get(env.ASSETS);
  if (cached && cached.expires > Date.now()) return cached.promise;
  const promise = (async () => {
    const manifestUrl = new URL(request.url);
    manifestUrl.pathname = manifestUrl.pathname.replace(/\/[^/]+\/?$/, '/manifest.json');
    manifestUrl.search = '';
    const asset = await env.ASSETS.fetch(new Request(manifestUrl));
    if (!asset.ok) throw new Error(`Static stream manifest returned HTTP ${asset.status}`);
    return asset.json();
  })();
  manifests.set(env.ASSETS, { promise, expires: Date.now() + 60000 });
  try {
    return await promise;
  } catch (error) {
    manifests.delete(env.ASSETS);
    throw error;
  }
}

function fileStream(env, request, chunks, firstIndex, lastIndex, start, end) {
  let index = firstIndex;
  let reader = null;
  let skip = 0;
  let remaining = 0;
  let canceled = false;
  let sentFirstOutput = false;
  const abort = new AbortController();
  return new ReadableStream({
    async pull(controller) {
      try {
        const targetBytes = sentFirstOutput ? STREAM_OUTPUT_BYTES : FIRST_OUTPUT_BYTES;
        const pieces = [];
        let outputBytes = 0;
        while (!canceled && outputBytes < targetBytes) {
          if (!reader) {
            if (index > lastIndex) break;
            const chunk = chunks[index];
            const from = index === firstIndex ? start : 0;
            const to = index === lastIndex ? end : chunk.bytes - 1;
            const response = await env.ASSETS.fetch(new Request(new URL(chunk.path, request.url), {
              headers: { Range: 'bytes=' + from + '-' + to, 'Accept-Encoding': 'identity' },
              signal: abort.signal
            }));
            if (canceled) { await response.body?.cancel(); return; }
            if (!response.body || (response.status !== 200 && response.status !== 206)) {
              await response.body?.cancel();
              throw new Error('chunk ' + index + ' returned HTTP ' + response.status);
            }
            if (response.status === 206) {
              const expected = 'bytes ' + from + '-' + to + '/' + chunk.bytes;
              if (response.headers.get('Content-Range') !== expected) {
                await response.body.cancel();
                throw new Error('chunk ' + index + ' returned an incorrect Content-Range');
              }
              skip = 0;
            } else {
              skip = from;
            }
            remaining = to - from + 1;
            reader = response.body.getReader();
          }
          const { value, done } = await reader.read();
          if (canceled) return;
          if (done) throw new Error('chunk ' + index + ' ended before the requested bytes');
          const offset = Math.min(skip, value.byteLength);
          skip -= offset;
          const length = Math.min(value.byteLength - offset, remaining);
          remaining -= length;
          if (length) {
            pieces.push(value.subarray(offset, offset + length));
            outputBytes += length;
          }
          if (remaining === 0) {
            const finished = reader;
            reader = null;
            index += 1;
            finished.cancel().catch(() => {});
          }
        }
        if (canceled) return;
        if (outputBytes) {
          let output = pieces[0];
          if (pieces.length > 1) {
            output = new Uint8Array(outputBytes);
            let offset = 0;
            for (const piece of pieces) {
              output.set(piece, offset);
              offset += piece.byteLength;
            }
          }
          sentFirstOutput = true;
          controller.enqueue(output);
          return;
        }
        if (index > lastIndex) { controller.close(); return; }
      } catch (error) {
        abort.abort(error);
        reader?.cancel(error).catch(() => {});
        reader = null;
        if (!canceled) {
          console.error('Static stream failed:', error.message);
          controller.error(error);
        }
      }
    },
    cancel(reason) {
      canceled = true;
      abort.abort(reason);
      reader?.cancel(reason).catch(() => {});
      reader = null;
    }
  }, { highWaterMark: STREAM_OUTPUT_BYTES, size: bytes => bytes.byteLength });
}


export async function onRequest({ request, params, env }) {
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method not allowed', { status: 405, headers: { ...cors, Allow: 'GET, HEAD, OPTIONS' } });
  }

  const fileId = String(params.file || '');
  if (!fileId) return textResponse('Media not found', 404);

  try {
    const manifest = await getManifest(env, request);
    const file = manifest.files?.[fileId];
    if (!file || !Array.isArray(file.chunks) || !file.chunks.length) {
      return textResponse('Media not found', 404);
    }

    const etag = `"${file.sha256}"`;
    const requestedRange = request.headers.get('Range');
    const ifRange = request.headers.get('If-Range');
    const useRange = requestedRange && (!ifRange || ifRange === etag);
    const ifNoneMatch = request.headers.get('If-None-Match');
    if (ifNoneMatch?.split(',').some(value => value.trim() === '*' || value.trim().replace(/^W\//, '') === etag)) {
      return new Response(null, { status: 304, headers: { ...cors, ...NO_CACHE, ETag: etag, 'Accept-Ranges': 'bytes' } });
    }

    const parsedRange = useRange ? parseRange(requestedRange, file.size) : null;
    if (useRange && !parsedRange) {
      return new Response(null, {
        status: 416,
        headers: { ...cors, ...NO_CACHE, 'Content-Range': `bytes */${file.size}`, 'Accept-Ranges': 'bytes', 'Content-Length': '0' }
      });
    }

    // Keep a whole-file Range as 200 for older FFmpeg/MPV Matroska cue probing; true subranges still return 206.
    const range = parsedRange && !(parsedRange.start === 0 && parsedRange.end === file.size - 1) ? parsedRange : null;
    const start = range?.start ?? 0;
    const end = range?.end ?? file.size - 1;
    const headers = {
      ...cors,
      ...NO_CACHE,
      'Content-Type': file.mime || 'application/octet-stream',
      'Content-Length': String(end - start + 1),
      'Accept-Ranges': 'bytes',
      ETag: etag,
      'Content-Disposition': `inline; filename*=UTF-8''${encodeURIComponent(file.name)}`
    };
    if (range) headers['Content-Range'] = `bytes ${start}-${end}/${file.size}`;
    if (request.method === 'HEAD') return new Response(null, { status: range ? 206 : 200, headers });

    let offset = 0;
    let firstIndex = 0;
    let lastIndex = file.chunks.length - 1;
    for (let i = 0; i < file.chunks.length; i += 1) {
      const chunkEnd = offset + file.chunks[i].bytes - 1;
      if (start <= chunkEnd) { firstIndex = i; break; }
      offset = chunkEnd + 1;
    }
    const firstOffset = start - offset;
    offset = file.chunks.slice(0, firstIndex).reduce((sum, chunk) => sum + chunk.bytes, 0);
    for (let i = firstIndex; i < file.chunks.length; i += 1) {
      const chunkEnd = offset + file.chunks[i].bytes - 1;
      if (end <= chunkEnd) { lastIndex = i; break; }
      offset = chunkEnd + 1;
    }
    const lastOffset = end - offset;
    const source = fileStream(env, request, file.chunks, firstIndex, lastIndex, firstOffset, lastOffset);
    const fixed = new FixedLengthStream(end - start + 1);
    source.pipeTo(fixed.writable).catch(() => {});
    return new Response(fixed.readable, { status: range ? 206 : 200, headers });
  } catch (error) {
    return textResponse(`Unable to read static stream: ${error.message}`, 503);
  }
}
