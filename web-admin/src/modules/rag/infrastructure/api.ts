import type { components } from '../../../shared/infrastructure/schema';
import { readResponse } from '../../../shared/infrastructure/http';

export type RagInput = components['schemas']['QuestionInput'];
export type RagAnswer = components['schemas']['AnswerView'];

export async function queryRag(token: string, body: RagInput, generate = true): Promise<RagAnswer> {
 const response = await fetch(`/api/rag/${generate ? 'ask' : 'search'}`, {
  method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify(body), signal: AbortSignal.timeout(85000),
 });
 return readResponse<RagAnswer>(response, token);
}

export type RagStreamEvent = components['schemas']['RagStreamEvent'];

export async function streamRag(
 token: string, body: RagInput, generate: boolean,
 onProgress: (event: RagStreamEvent) => void, signal: AbortSignal,
): Promise<RagAnswer> {
 const controller = new AbortController();
 const abort = () => controller.abort(signal.reason);
 const timer = setTimeout(() => controller.abort(new DOMException('Время ожидания истекло.', 'TimeoutError')), 85000);
 signal.addEventListener('abort', abort, { once: true });
 if (signal.aborted) abort();
 let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
 try {
  const response = await fetch(`/api/rag/${generate ? 'ask' : 'search'}/stream`, {
   method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', Accept: 'text/event-stream' },
   body: JSON.stringify(body), signal: controller.signal,
  });
  if (!response.ok) return await readResponse<RagAnswer>(response, token);
  if (!response.headers.get('content-type')?.startsWith('text/event-stream') || !response.body) throw new Error('Сервер не открыл поток SSE.');
  reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
   const { value, done } = await reader.read();
   buffer += decoder.decode(value, { stream: !done });
   if (buffer.length > 1_000_000) throw new Error('Превышен размер события SSE.');
   let separator: RegExpExecArray | null;
   while ((separator = /\r?\n\r?\n/.exec(buffer))) {
    const block = buffer.slice(0, separator.index);
    buffer = buffer.slice(separator.index + separator[0].length);
    const lines = block.split(/\r?\n/);
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n');
    if (!data) continue; // SSE comments / heartbeat.
    const event = JSON.parse(data) as RagStreamEvent;
    const name = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
    if (name !== event.event || !event.timings || typeof event.trace_id !== 'string') throw new Error('Некорректное событие SSE.');
    if (event.event === 'progress') onProgress(event);
    else if (event.event === 'result' && event.result) return event.result;
    else if (event.event === 'error') {
     const statuses: Record<string, number> = { unauthorized: 401, forbidden: 403, not_found: 404, conflict: 409, invalid: 422, throttled: 429 };
     return await readResponse<RagAnswer>(new Response(JSON.stringify({ detail: event.detail || 'Ошибка RAG.', timings: event.timings, trace_id: event.trace_id, llm_usage: event.llm_usage }), { status: statuses[event.code || ''] || 503 }), token);
    } else throw new Error('Неизвестное событие SSE.');
   }
   if (done) throw new Error('Поток прервался до получения результата. Повторите запрос.');
  }
 } finally {
  clearTimeout(timer);
  signal.removeEventListener('abort', abort);
  await reader?.cancel().catch(() => undefined);
  reader?.releaseLock();
 }
}
