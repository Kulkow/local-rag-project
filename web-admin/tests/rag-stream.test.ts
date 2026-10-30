import { afterEach, expect, it, vi } from 'vitest';
import { streamRag, type RagAnswer } from '../src/modules/rag/infrastructure/api';
import { ApiError } from '../src/shared/infrastructure/http';

const input = { family_id: 'family', question: 'Вопрос', retrieval_mode: 'hybrid' as const, top_k: 3 };
const answer: RagAnswer = { answer: 'Ответ [1]', abstained: false, reason: null, citations: [], retrieved_chunks: [], retrieval_mode: 'hybrid', chat_model: 'local', trace_id: 'trace', timings: { total_ms: 100 }, reranked: false };
const progress = { event: 'progress', trace_id: 'trace', timings: { generation_ms: 20 }, active_stages: ['generation'], elapsed_ms: 30 };
function frame(event: object, name: string) { return `event: ${name}\r\ndata: ${JSON.stringify(event)}\r\n\r\n`; }
function respond(text: string, fragment = false) {
 const bytes = new TextEncoder().encode(text);
 const stream = new ReadableStream<Uint8Array>({ start(controller) {
  if (fragment) for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); else controller.enqueue(bytes);
  controller.close();
 }});
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })));
}
afterEach(() => { vi.unstubAllGlobals(); });
it('decodes split UTF-8 and CRLF frames, comments and final citations', async () => {
 respond(': heartbeat\r\n\r\n' + frame(progress, 'progress') + frame({ event: 'result', trace_id: 'trace', timings: {}, result: answer }, 'result'), true);
 const onProgress = vi.fn();
 const result = await streamRag('private-token', input, true, onProgress, new AbortController().signal);
 expect(result).toEqual(answer); expect(onProgress).toHaveBeenCalledWith(progress);
 expect(fetch).toHaveBeenCalledWith('/api/rag/ask/stream', expect.objectContaining({ method: 'POST', headers: expect.objectContaining({ Authorization: 'Bearer private-token', Accept: 'text/event-stream' }) }));
});
it('keeps timings and usage for a terminal server error', async () => {
 const usage = {input_tokens: 120, output_tokens: 30, calls: [{stage: 'generation', input_tokens: 120, output_tokens: 30}]};
 respond(frame({ event: 'error', trace_id: 'trace', timings: { generation_ms: 65000 }, code: 'storage_unavailable', detail: 'Model unavailable', llm_usage: usage }, 'error'));
 const error = await streamRag('token', input, true, vi.fn(), new AbortController().signal).catch(error => error);
 expect(error).toBeInstanceOf(ApiError); expect(error.timings).toEqual({ generation_ms: 65000 }); expect(error.traceId).toBe('trace'); expect(error.llmUsage).toEqual(usage);
});
it('rejects a truncated stream instead of reporting success or retrying automatically', async () => {
 respond(frame(progress, 'progress'));
 await expect(streamRag('token', input, false, vi.fn(), new AbortController().signal)).rejects.toThrow('Поток прервался');
 expect(fetch).toHaveBeenCalledTimes(1); expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/rag/search/stream');
});
it('handles HTTP authentication errors before the stream opens', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"Unauthorized"}', { status: 401 })));
 await expect(streamRag('token', input, true, vi.fn(), new AbortController().signal)).rejects.toMatchObject({ status: 401 });
});
it('aborts fetch when the user cancels', async () => {
 vi.stubGlobal('fetch', vi.fn((_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(init.signal.reason)))));
 const controller = new AbortController();
 const request = streamRag('token', input, true, vi.fn(), controller.signal);
 controller.abort();
 await expect(request).rejects.toMatchObject({ name: 'AbortError' });
});
it('rejects malformed SSE and incorrect content types', async () => {
 respond('event: progress\ndata: broken\n\n');
 await expect(streamRag('token', input, true, vi.fn(), new AbortController().signal)).rejects.toThrow();
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } })));
 await expect(streamRag('token', input, true, vi.fn(), new AbortController().signal)).rejects.toThrow('Сервер не открыл поток SSE');
});
