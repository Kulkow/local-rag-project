// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import PrimeVue from 'primevue/config';
import { mount, flushPromises } from '@vue/test-utils';
import RagPlayground from '../src/modules/rag/presentation/RagPlayground.vue';
import { useAuth } from '../src/modules/identity/presentation/auth-store';
import { downloadDocument, previewPdf } from '../src/modules/documents/infrastructure/api';
import { streamRag } from '../src/modules/rag/infrastructure/api';
import { listFamilies } from '../src/modules/families/infrastructure/api';
vi.mock('../src/modules/documents/infrastructure/api', () => ({ downloadDocument: vi.fn(), previewPdf: vi.fn() }));
vi.mock('../src/modules/rag/infrastructure/api', () => ({ streamRag: vi.fn() }));
vi.mock('../src/modules/families/infrastructure/api', () => ({ listFamilies: vi.fn(), login: vi.fn(), request: vi.fn(), ApiError: class extends Error {} }));
let pinia: ReturnType<typeof createPinia>; let wrapper: ReturnType<typeof mount> | undefined;
beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); pinia = createPinia(); setActivePinia(pinia); vi.mocked(listFamilies).mockResolvedValue([{id:'family',name:'Synthetic family'}]); });
afterEach(() => wrapper?.unmount());
function mountPage(signedIn = true) {
 if (signedIn) { const auth = useAuth(); auth.token='jwt'; auth.user={id:'member',username:'synthetic',role:'member',family_member_id:'member',is_active:true}; }
 wrapper=mount(RagPlayground,{global:{plugins:[pinia,PrimeVue],stubs:{RouterLink:{template:'<a href="/documents#upload"><slot /></a>'}}}}); return wrapper;
}
it('requires authentication before loading scopes', async () => { const view=mountPage(false); await flushPromises(); expect(view.text()).toContain('Вход'); expect(listFamilies).not.toHaveBeenCalled(); });
it('shows abstention and trace metadata for a member query', async () => {
 const view=mountPage(); await flushPromises();
 vi.mocked(streamRag).mockResolvedValue({answer:'Недостаточно данных.',reranked:false,abstained:true,reason:'no_evidence',citations:[],retrieved_chunks:[],retrieval_mode:'vector',chat_model:null,trace_id:'trace',timings:{total_ms:1,retrieval_ms:1}});
 await view.find('textarea').setValue('Retention?'); await view.find('form').trigger('submit'); await flushPromises();
 expect(streamRag).toHaveBeenCalledWith('jwt',{family_id:'family',question:'Retention?',retrieval_mode:'hybrid',top_k:5},true,expect.any(Function),expect.anything());
 expect(view.text()).toContain('Недостаточно данных.'); expect(view.text()).toContain('Trace ID: trace'); expect(view.text()).toContain('Код причины: no_evidence');
});
it('renders citations and untrusted passages as plain text', async () => {
 const view=mountPage(); await flushPromises(); const source={source_id:1,chunk_id:'chunk',document_id:'doc',filename:'guide.pdf',page_number:2,text:'<script>untrusted</script>',score:.8};
 vi.mocked(streamRag).mockResolvedValue({answer:'37 дней [1].',reranked:false,abstained:false,reason:null,citations:[source],retrieved_chunks:[source],retrieval_mode:'keyword',chat_model:'synthetic',trace_id:'trace',timings:{total_ms:2}});
 await view.find('textarea').setValue('Retention?'); await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('a[href="#source-1"]').exists()).toBe(true); expect(view.find('pre').text()).toContain('<script>untrusted</script>'); expect(view.find('script').exists()).toBe(false);
});
it('shows API errors and allows retry', async () => {
 const view=mountPage(); await flushPromises(); vi.mocked(streamRag).mockRejectedValue(new Error('Model unavailable'));
 await view.find('textarea').setValue('Retention?'); await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[role="alert"]').text()).toContain('Model unavailable'); expect(view.find('textarea').attributes('disabled')).toBeUndefined();
});


it('links directly to document upload', async () => {
 const view = mountPage(); await flushPromises();
 expect(view.find('a[href="/documents#upload"]').text()).toContain('Загрузить документ');
});

it('groups source fragments by file, collapses details and downloads the authorized original', async () => {
 const view = mountPage(); await flushPromises();
 const source = { source_id: 1, chunk_id: 'c1', document_id: 'doc', filename: 'guide.pdf', page_number: 1, text: 'Evidence', score: .8 };
 vi.mocked(streamRag).mockResolvedValue({ answer: 'Answer [1]', reranked:false,abstained: false, reason: null, citations: [source], retrieved_chunks: [source, { ...source, source_id: 2, chunk_id: 'c2', page_number: 2 }], retrieval_mode: 'vector', chat_model: 'local', trace_id: 'trace', timings: { total_ms: 20 } });
 await view.find('textarea').setValue('Question'); await view.find('form').trigger('submit'); await flushPromises();
 expect(view.findAll('.source-card')).toHaveLength(1);
 expect(view.findAll('.source-fragment')).toHaveLength(2);
 expect(view.find('.source-fragment').attributes('open')).toBeUndefined();
 await view.find('a[href="#source-1"]').trigger('click');
 expect((view.find('.source-fragment').element as HTMLDetailsElement).open).toBe(true);
 await view.find('button[aria-label="Скачать guide.pdf"]').trigger('click'); await flushPromises();
 expect(downloadDocument).toHaveBeenCalledWith('jwt', 'doc', 'guide.pdf');
 await view.find('button[aria-label="Посмотреть оригинал guide.pdf"]').trigger('click'); await flushPromises();
 expect(previewPdf).toHaveBeenCalledWith('jwt', 'doc');
 vi.mocked(downloadDocument).mockRejectedValue(new Error('Download unavailable'));
 await view.find('button[aria-label="Скачать guide.pdf"]').trigger('click'); await flushPromises();
 expect(view.find('[role="alert"]').text()).toContain('Download unavailable');
});

it('shows hybrid ranking metadata and supports model-free search', async () => {
 const view = mountPage(); await flushPromises();
 vi.mocked(streamRag).mockResolvedValue({ answer: 'Answer', abstained: false, reranked: true, reason: null, citations: [], retrieved_chunks: [], retrieval_mode: 'hybrid', chat_model: 'local', trace_id: 'trace', timings: { total_ms: 30, rrf_ms: 1, reranking_ms: 12 } });
 expect((view.findAll('select')[1].element as HTMLSelectElement).value).toBe('hybrid');
 await view.find('textarea').setValue('Question');
 await view.find('form').trigger('submit'); await flushPromises();
 expect(view.text()).toContain('Гибридный'); expect(view.text()).toContain('RRF + LLM reranker');
 expect(view.text()).toContain('12 мс');
 vi.mocked(streamRag).mockResolvedValue({ answer: '', abstained: true, reranked: false, reason: 'search_only', citations: [], retrieved_chunks: [], retrieval_mode: 'hybrid', chat_model: null, trace_id: 'trace', timings: { rrf_ms: 1 } });
 const search = view.findAll('button').find(button => button.text() === 'Только поиск')!;
 await search.trigger('click'); await flushPromises();
 expect(streamRag).toHaveBeenCalledWith('jwt', { family_id: 'family', question: 'Question', retrieval_mode: 'hybrid', top_k: 5 }, false, expect.any(Function), expect.anything());
 expect(view.text()).toContain('RRF'); expect(view.text()).not.toContain('LLM reranker');
});

it('shows every measured stage and omits unexecuted stages', async () => {
 const view = mountPage(); await flushPromises();
 const timings = { request_ms: 1525, capacity_wait_ms: 5, total_ms: 1520, retrieval_ms: 510, scope_ms: 1, embedding_identity_ms: 2, query_embedding_ms: 100, keyword_search_ms: 3, vector_search_ms: 4, candidate_read_ms: 5, rrf_ms: .12, query_rewriting_ms: 10, query_retry_ms: 110, reranking_ms: 270, context_ms: .08, acl_revalidation_ms: 1, generation_ms: 1000, citation_validation_ms: .2 };
 vi.mocked(streamRag).mockResolvedValue({ answer: 'Answer', abstained: false, reranked: true, reason: null, citations: [], retrieved_chunks: [], retrieval_mode: 'hybrid', chat_model: 'local', trace_id: 'trace', timings });
 await view.find('textarea').setValue('Question'); await view.find('form').trigger('submit'); await flushPromises();
 const panel = view.find('[aria-label="Время этапов RAG"]');
 expect(panel.findAll('tbody tr')).toHaveLength(Object.keys(timings).length);
 expect(panel.find('[data-stage="generation_ms"]').text()).toContain('1.00 с');
 expect(panel.find('[data-stage="rrf_ms"]').text()).toContain('0.12 мс');
 expect(panel.text()).toContain('строки нельзя складывать');
 vi.mocked(streamRag).mockResolvedValue({ answer: '', abstained: true, reranked: false, reason: 'search_only', citations: [], retrieved_chunks: [], retrieval_mode: 'keyword', chat_model: null, trace_id: 'next', timings: { total_ms: 2, keyword_search_ms: 1 } });
 await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[data-stage="generation_ms"]').exists()).toBe(false);
 expect(view.find('[data-stage="reranking_ms"]').exists()).toBe(false);
});

it('keeps partial timings after a timeout and clears them on retry and scope change', async () => {
 const { ApiError } = await import('../src/shared/infrastructure/http');
 const view = mountPage(); await flushPromises();
 vi.mocked(streamRag).mockRejectedValue(new ApiError(503, 'Model timed out', { generation_ms: 65000, total_ms: 66000 }, 'failed-trace'));
 await view.find('textarea').setValue('Question'); await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[data-stage="generation_ms"]').text()).toContain('65.00 с');
 expect(view.text()).toContain('Trace ID: failed-trace');
 expect(view.text()).toContain('включая прерванный этап');
 expect(view.find('.answer-panel').exists()).toBe(false);
 await view.findAll('select')[1].setValue('keyword');
 expect(view.find('[aria-label="Время этапов RAG"]').exists()).toBe(false);
 await view.find('form').trigger('submit'); await flushPromises();
 vi.mocked(streamRag).mockRejectedValue(new Error('Network unavailable'));
 await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[aria-label="Время этапов RAG"]').exists()).toBe(false);
 expect(view.text()).not.toContain('failed-trace');
});

it('updates live timings and cancels the SSE request', async () => {
 const view = mountPage(); await flushPromises();
 vi.mocked(streamRag).mockImplementation((_token, _body, _generate, progress, signal) => new Promise((_resolve, reject) => {
  progress({event:'progress',trace_id:'live',elapsed_ms:1200,waiting:false,active_stages:['generation'],timings:{retrieval_ms:100,generation_ms:1100}});
  signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
 }));
 await view.find('textarea').setValue('Question'); await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[data-stage="generation_ms"]').text()).toContain('выполняется');
 expect(view.find('[data-stage="generation_ms"]').text()).toContain('1.10 с');
 expect(view.find('.answer-panel').exists()).toBe(false);
 await view.findAll('button').find(button => button.text() === 'Остановить')!.trigger('click'); await flushPromises();
 expect(view.text()).toContain('Запрос остановлен');
 expect(view.find('textarea').attributes('disabled')).toBeUndefined();
 expect(view.find('[data-stage="generation_ms"]').text()).not.toContain('выполняется');
});

it('aborts the stream when leaving the page', async () => {
 const view = mountPage(); await flushPromises(); let signal: AbortSignal | undefined;
 vi.mocked(streamRag).mockImplementation((_token, _body, _generate, _progress, current) => { signal = current; return new Promise(() => {}); });
 await view.find('textarea').setValue('Question'); await view.find('form').trigger('submit');
 view.unmount(); wrapper = undefined;
 expect(signal?.aborted).toBe(true);
});

it('shows input/output totals and per-call usage, then clears them for search and logout', async () => {
 const view = mountPage(); await flushPromises();
 vi.mocked(streamRag).mockResolvedValue({ answer: 'Answer', abstained: false, reason: null, citations: [], retrieved_chunks: [], retrieval_mode: 'hybrid', chat_model: 'local', trace_id: 'trace', timings: {},
  llm_usage: { input_tokens: 350, output_tokens: 65, calls: [{stage: 'reranking', input_tokens: 150, output_tokens: 15}, {stage: 'generation', input_tokens: 200, output_tokens: 50}] } });
 await view.find('textarea').setValue('Question'); await view.find('form').trigger('submit'); await flushPromises();
 const panel = view.find('[aria-label="Токены LLM"]');
 expect(panel.find('tfoot').text()).toContain('350'); expect(panel.find('tfoot').text()).toContain('65');
 expect(panel.findAll('tbody tr')).toHaveLength(2);
 expect(panel.text()).toContain('Переранжирование');
 vi.mocked(streamRag).mockResolvedValue({ answer: '', abstained: true, reason: 'search_only', citations: [], retrieved_chunks: [], retrieval_mode: 'hybrid', chat_model: null, trace_id: 'next', timings: {}, llm_usage: {input_tokens: 0, output_tokens: 0, calls: []} });
 await view.findAll('button').find(button => button.text() === 'Только поиск')!.trigger('click'); await flushPromises();
 expect(view.find('[aria-label="Токены LLM"]').text()).toContain('LLM не вызывалась.'); expect(view.find('[aria-label="Токены LLM"]').text()).not.toContain('350');
 useAuth().token = ''; await flushPromises();
 expect(view.find('[aria-label="Токены LLM"]').exists()).toBe(false);
});

it('keeps unknown and known token counts on SSE cancellation and error', async () => {
 const view = mountPage(); await flushPromises();
 const usage = {input_tokens: null, output_tokens: null, calls: [{stage: 'reranking' as const, input_tokens: 150, output_tokens: 15}, {stage: 'generation' as const, input_tokens: null, output_tokens: null}]};
 vi.mocked(streamRag).mockImplementation((_token, _body, _generate, progress, signal) => new Promise((_resolve, reject) => {
  progress({event:'progress',trace_id:'live',elapsed_ms:1200,timings:{generation_ms:1100}, llm_usage: usage});
  signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
 }));
 await view.find('textarea').setValue('Question'); await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[aria-label="Токены LLM"]').text()).toContain('150');
 expect(view.find('[aria-label="Токены LLM"] tfoot').text()).toContain('Нет данных');
 await view.findAll('button').find(button => button.text() === 'Остановить')!.trigger('click'); await flushPromises();
 expect(view.find('[aria-label="Токены LLM"]').text()).toContain('Частичные данные');
 const { ApiError } = await import('../src/shared/infrastructure/http');
 vi.mocked(streamRag).mockRejectedValue(new ApiError(503, 'Unavailable', {generation_ms: 1100}, 'failed', usage));
 await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[aria-label="Токены LLM"]').text()).toContain('150');
 await view.findAll('select')[1].setValue('keyword');
 expect(view.find('[aria-label="Токены LLM"]').exists()).toBe(false);
});
