// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import PrimeVue from 'primevue/config';
import { mount, flushPromises } from '@vue/test-utils';
import RagPlayground from '../src/views/RagPlayground.vue';
import { useAuth } from '../src/stores/auth';
import { downloadDocument, previewPdf } from '../src/documents-api';
import { queryRag } from '../src/rag-api';
import { listFamilies } from '../src/management-api';
vi.mock('../src/documents-api', () => ({ downloadDocument: vi.fn(), previewPdf: vi.fn() }));
vi.mock('../src/rag-api', () => ({ queryRag: vi.fn() }));
vi.mock('../src/management-api', () => ({ listFamilies: vi.fn(), login: vi.fn(), request: vi.fn(), ApiError: class extends Error {} }));
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
 vi.mocked(queryRag).mockResolvedValue({answer:'Недостаточно данных.',abstained:true,reason:'no_evidence',citations:[],retrieved_chunks:[],retrieval_mode:'vector',chat_model:null,trace_id:'trace',timings:{total_ms:1,retrieval_ms:1}});
 await view.find('textarea').setValue('Retention?'); await view.find('form').trigger('submit'); await flushPromises();
 expect(queryRag).toHaveBeenCalledWith('jwt',{family_id:'family',question:'Retention?',retrieval_mode:'vector',top_k:5},true);
 expect(view.text()).toContain('Недостаточно данных.'); expect(view.text()).toContain('Trace ID: trace');
});
it('renders citations and untrusted passages as plain text', async () => {
 const view=mountPage(); await flushPromises(); const source={source_id:1,chunk_id:'chunk',document_id:'doc',filename:'guide.pdf',page_number:2,text:'<script>untrusted</script>',score:.8};
 vi.mocked(queryRag).mockResolvedValue({answer:'37 дней [1].',abstained:false,reason:null,citations:[source],retrieved_chunks:[source],retrieval_mode:'keyword',chat_model:'synthetic',trace_id:'trace',timings:{total_ms:2}});
 await view.find('textarea').setValue('Retention?'); await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('a[href="#source-1"]').exists()).toBe(true); expect(view.find('pre').text()).toContain('<script>untrusted</script>'); expect(view.find('script').exists()).toBe(false);
});
it('shows API errors and allows retry', async () => {
 const view=mountPage(); await flushPromises(); vi.mocked(queryRag).mockRejectedValue(new Error('Model unavailable'));
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
 vi.mocked(queryRag).mockResolvedValue({ answer: 'Answer [1]', abstained: false, reason: null, citations: [source], retrieved_chunks: [source, { ...source, source_id: 2, chunk_id: 'c2', page_number: 2 }], retrieval_mode: 'vector', chat_model: 'local', trace_id: 'trace', timings: { total_ms: 20 } });
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
