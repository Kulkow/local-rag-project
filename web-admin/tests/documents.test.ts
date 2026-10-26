// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import PrimeVue from 'primevue/config';
import { mount, flushPromises } from '@vue/test-utils';
import Documents from '../src/modules/documents/presentation/DocumentsView.vue';
import { useAuth } from '../src/modules/identity/presentation/auth-store';
import * as api from '../src/modules/documents/infrastructure/api';
import { listFamilies } from '../src/modules/families/infrastructure/api';
vi.mock('../src/modules/documents/infrastructure/api', () => ({ previewPdf: vi.fn(), listDocuments: vi.fn(), uploadDocument: vi.fn(), extractionFormats: vi.fn(), enqueueDocument: vi.fn(), processingStatus: vi.fn(), indexStatus: vi.fn(), reindexDocument: vi.fn(), readPages: vi.fn() }));
vi.mock('../src/modules/families/infrastructure/api', () => ({ listFamilies: vi.fn(), login: vi.fn(), request: vi.fn(), ApiError: class extends Error {} }));
let pinia: ReturnType<typeof createPinia>;
let wrapper: ReturnType<typeof mount> | undefined;
beforeEach(() => {
 vi.resetAllMocks(); localStorage.clear(); pinia = createPinia(); setActivePinia(pinia);
 vi.mocked(listFamilies).mockResolvedValue([{ id: 'family-id', name: 'Synthetic family' }]);
 vi.mocked(api.listDocuments).mockResolvedValue([]);
 vi.mocked(api.extractionFormats).mockResolvedValue(["application/pdf"]);
 vi.mocked(api.enqueueDocument).mockResolvedValue({ document_id: "doc", status: "queued", attempts: 0, error_code: null, created_at: null, started_at: null, finished_at: null });
 vi.mocked(api.processingStatus).mockResolvedValue({ document_id: "doc", status: "queued", attempts: 0, error_code: null, created_at: null, started_at: null, finished_at: null });
 vi.mocked(api.indexStatus).mockRejectedValue(new Error('Not indexed'));
 vi.mocked(api.reindexDocument).mockImplementation((...args) => api.enqueueDocument(...args));
});
afterEach(() => wrapper?.unmount());
function mountPage(role: 'admin' | 'manager' | 'member' = 'admin') {
 const auth = useAuth(); auth.token = 'jwt'; auth.user = { id: 'owner', username: 'synthetic', role, family_member_id: 'member', is_active: true };
 wrapper = mount(Documents, { global: { plugins: [pinia, PrimeVue] } }); return wrapper;
}
async function chooseFile(view: ReturnType<typeof mount>, file: File) {
 const input = view.find('input[type="file"]'); Object.defineProperty(input.element, 'files', { value: [file], configurable: true }); await input.trigger('change');
}
it('requires sign-in before requesting documents', async () => {
 wrapper = mount(Documents, { global: { plugins: [pinia, PrimeVue] } }); await flushPromises();
 expect(wrapper.text()).toContain('Вход'); expect(api.listDocuments).not.toHaveBeenCalled();
});
it('uploads a selected file with a stable retry key and reports that it is not indexed', async () => {
 const view = mountPage(); await flushPromises();
 vi.mocked(api.uploadDocument).mockResolvedValue({ id: 'doc', filename: 'guide.pdf', family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'private', size_bytes: 10, checksum: 'hash', content_type: 'application/pdf', error_code: null, created_at: null });
 const file = new File(['%PDF-1.4'], 'guide.pdf', { type: 'application/pdf' }); await chooseFile(view, file); await view.find('form').trigger('submit'); await flushPromises();
 expect(api.uploadDocument).toHaveBeenCalledWith('jwt', file, 'family-id', 'private', expect.any(String));
 expect(view.text()).toContain('Оригинал сохранён'); expect(view.text()).toContain('Поиск и ответы доступны в RAG Playground');
});
it('rejects an oversized file before making an upload request', async () => {
 const view = mountPage(); await flushPromises();
 const file = new File(['x'], 'guide.pdf', { type: 'application/pdf' }); Object.defineProperty(file, 'size', { value: 10485761 });
 await chooseFile(view, file); await view.find('form').trigger('submit'); await flushPromises();
 expect(api.uploadDocument).not.toHaveBeenCalled(); expect(view.find('[role="alert"]').text()).toContain('10 MiB');
});
it('shows upload errors and reuses the same key on retry', async () => {
 const view = mountPage(); await flushPromises(); vi.mocked(api.uploadDocument).mockRejectedValue(new Error('Storage unavailable'));
 await chooseFile(view, new File(['%PDF-1.4'], 'guide.pdf', { type: 'application/pdf' }));
 await view.find('form').trigger('submit'); await flushPromises(); await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[role="alert"]').text()).toContain('Storage unavailable');
 const calls = vi.mocked(api.uploadDocument).mock.calls; expect(calls).toHaveLength(2); expect(calls[0][4]).toBe(calls[1][4]);
});
it('offers document upload to members', async () => {
 const view = mountPage('member'); await flushPromises(); expect(view.find('input[type="file"]').exists()).toBe(true); expect(api.listDocuments).toHaveBeenCalledWith('jwt', 'family-id', 0);
});

it('extracts PDF text and renders document contents as plain text', async () => {
 vi.mocked(api.listDocuments).mockResolvedValue([{ id: 'doc', filename: 'guide.pdf', family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'family', size_bytes: 10, checksum: 'hash', content_type: 'application/pdf', error_code: null, created_at: null }]);
 vi.mocked(api.enqueueDocument).mockResolvedValue({ document_id: 'doc', status: 'queued', attempts: 0, error_code: null, created_at: null, started_at: null, finished_at: null });
 vi.mocked(api.readPages).mockResolvedValue({ total_pages: 1, pages: [{ page_number: 1, text: '<script>untrusted</script>' }] });
 const view = mountPage(); await flushPromises();
 await view.findAll('button').find(b => b.text().includes('Переиндексировать'))!.trigger('click'); await flushPromises();
 expect(api.enqueueDocument).toHaveBeenCalledWith('jwt', 'doc');
 await view.findAll('button').find(b => b.text().includes('Просмотреть текст'))!.trigger('click'); await flushPromises();
 expect(view.find('pre').text()).toContain('<script>untrusted</script>');
 expect(view.find('script').exists()).toBe(false);
});
it('shows extraction failures without presenting the document as indexed', async () => {
 vi.mocked(api.listDocuments).mockResolvedValue([{ id: 'doc', filename: 'scan.pdf', family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'family', size_bytes: 10, checksum: 'hash', content_type: 'application/pdf', error_code: null, created_at: null }]);
 vi.mocked(api.enqueueDocument).mockRejectedValue(new Error('pdf_needs_ocr'));
 const view = mountPage(); await flushPromises();
 await view.findAll('button').find(b => b.text().includes('Переиндексировать'))!.trigger('click'); await flushPromises();
 expect(view.find('[role="alert"]').text()).toContain('OCR');
 expect(api.readPages).not.toHaveBeenCalled();
});

it('schedules supported uploads without waiting for extraction', async () => {
 const view = mountPage(); await flushPromises();
 vi.mocked(api.uploadDocument).mockResolvedValue({ id: 'doc', filename: 'guide.pdf', family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'private', size_bytes: 10, checksum: 'hash', content_type: 'application/pdf', error_code: null, created_at: null });
 vi.mocked(api.enqueueDocument).mockResolvedValue({ document_id: 'doc', status: 'queued', attempts: 0, error_code: null, created_at: null, started_at: null, finished_at: null });
 await chooseFile(view, new File(['%PDF-1.4'], 'guide.pdf', { type: 'application/pdf' }));
 await view.find('form').trigger('submit'); await flushPromises();
 expect(api.enqueueDocument).toHaveBeenCalledWith('jwt', 'doc');
 expect(view.text()).toContain('Обработка: В очереди');
});

it('keeps a saved original when queue confirmation fails', async () => {
 const view = mountPage(); await flushPromises();
 vi.mocked(api.uploadDocument).mockResolvedValue({ id: 'doc', filename: 'scan.pdf', family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'private', size_bytes: 10, checksum: 'hash', content_type: 'application/pdf', error_code: null, created_at: null });
 vi.mocked(api.enqueueDocument).mockRejectedValue(new Error('pdf_needs_ocr'));
 await chooseFile(view, new File(['%PDF-1.4'], 'scan.pdf', { type: 'application/pdf' }));
 await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[role="alert"]').text()).toContain('OCR');
 expect(view.text()).toContain('Оригинал сохранён');
 expect(view.find('button[type="submit"]').attributes('disabled')).toBeDefined();
 expect(api.uploadDocument).toHaveBeenCalledTimes(1);
});

it('saves unsupported extraction formats without claiming RAG readiness', async () => {
 const view = mountPage(); await flushPromises();
 vi.mocked(api.uploadDocument).mockResolvedValue({ id: 'doc', filename: 'guide.html', family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'private', size_bytes: 10, checksum: 'hash', content_type: 'text/html', error_code: null, created_at: null });
 await chooseFile(view, new File(['<html>synthetic</html>'], 'guide.html', { type: 'text/html' }));
 await view.find('form').trigger('submit'); await flushPromises();
 expect(api.enqueueDocument).not.toHaveBeenCalled();
 expect(view.text()).toContain('для этого формата пока недоступно');
});

it('shows actual index metadata without presenting answer search as implemented', async () => {
 vi.mocked(api.listDocuments).mockResolvedValue([{ id: 'doc', filename: 'guide.pdf', family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'private', size_bytes: 10, checksum: 'hash', content_type: 'application/pdf', error_code: null, created_at: null }]);
 vi.mocked(api.indexStatus).mockResolvedValue({ document_id: 'doc', status: 'indexed', embedding_model: 'synthetic-model', embedding_digest: 'synthetic-digest', dimensions: 3, chunk_count: 2, error_code: null });
 const view = mountPage(); await flushPromises();
 expect(view.text()).toContain('2 чанков');
 expect(view.text()).toContain('synthetic-model');
 expect(view.text()).toContain('3 измерений');
 expect(view.text()).toContain('Поиск и ответы доступны в RAG Playground');
});

it('shows the upload form with a clear prerequisite when no family exists', async () => {
 vi.mocked(listFamilies).mockResolvedValue([]);
 const view = mountPage(); await flushPromises();
 expect(view.find('input[type="file"]').exists()).toBe(true);
 expect(view.find('input[type="file"]').attributes('disabled')).toBeDefined();
 expect(view.text()).toContain('Сначала создайте или выберите семью');
 expect(view.find('a[href="/families"]').exists()).toBe(true);
});

it('loads families and keeps upload available if extraction capabilities fail', async () => {
 vi.mocked(api.extractionFormats).mockRejectedValue(new Error('Capabilities unavailable'));
 const view = mountPage(); await flushPromises();
 expect(listFamilies).toHaveBeenCalled();
 expect(view.find('input[type="file"]').exists()).toBe(true);
 expect(view.find('input[type="file"]').attributes('disabled')).toBeUndefined();
 expect(view.text()).toContain('Сведения об автоматической обработке недоступны');
});

it('allows a member to upload a document', async () => {
 const view = mountPage('member'); await flushPromises();
 vi.mocked(api.uploadDocument).mockResolvedValue({ id: 'doc', filename: 'guide.pdf', family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'private', size_bytes: 10, checksum: 'hash', content_type: 'application/pdf', error_code: null, created_at: null });
 const file = new File(['%PDF-1.4'], 'guide.pdf', { type: 'application/pdf' });
 await chooseFile(view, file); await view.find('form').trigger('submit'); await flushPromises();
 expect(api.uploadDocument).toHaveBeenCalledWith('jwt', file, 'family-id', 'private', expect.any(String));
});

it('allows managers to see the upload form for their family', async () => {
 const view = mountPage('manager'); await flushPromises();
 expect(view.find('input[type="file"]').exists()).toBe(true);
 expect(view.find('input[type="file"]').attributes('disabled')).toBeUndefined();
});

it('enables upload after refreshing a previously empty family list', async () => {
 vi.mocked(listFamilies).mockResolvedValueOnce([]).mockResolvedValueOnce([{ id: 'family-id', name: 'Synthetic family' }]);
 const view = mountPage(); await flushPromises();
 expect(view.find('input[type="file"]').attributes('disabled')).toBeDefined();
 await view.findAll('button').find(button => button.text().includes('Обновить список семей'))!.trigger('click'); await flushPromises();
 expect(view.find('input[type="file"]').attributes('disabled')).toBeUndefined();
 expect(api.listDocuments).toHaveBeenCalledWith('jwt', 'family-id', 0);
});

it('shows a duplicate upload error without scheduling another ingestion', async () => {
 const view = mountPage('member'); await flushPromises();
 vi.mocked(api.uploadDocument).mockRejectedValue(new Error('This document is already uploaded to your account.'));
 await chooseFile(view, new File(['%PDF-1.4'], 'renamed.pdf', { type: 'application/pdf' }));
 await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[role="alert"]').text()).toContain('already uploaded');
 expect(api.enqueueDocument).not.toHaveBeenCalled();
 expect(view.text()).not.toContain('Оригинал сохранён');
});

async function chooseFiles(view: ReturnType<typeof mount>, files: File[]) {
 const input = view.find('input[type="file"]'); Object.defineProperty(input.element, 'files', { value: files, configurable: true }); await input.trigger('change');
}
function uploadedFile(file: File): api.Document {
 return { id: file.name, filename: file.name, family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'private', size_bytes: file.size, checksum: 'hash', content_type: file.type, error_code: null, created_at: null };
}
it('uploads a batch larger than 10 MiB sequentially with individual keys', async () => {
 const view = mountPage('member'); await flushPromises();
 const files = ['first.html', 'second.html'].map(name => { const file = new File(['<html>test</html>'], name, { type: 'text/html' }); Object.defineProperty(file, 'size', { value: 6 * 1024 * 1024 }); return file; });
 let release!: () => void;
 vi.mocked(api.uploadDocument).mockImplementationOnce(async (_token, file) => { await new Promise<void>(resolve => { release = resolve; }); return uploadedFile(file); }).mockImplementation(async (_token, file) => uploadedFile(file));
 await chooseFiles(view, files);
 expect(view.find('input[type="file"]').attributes('multiple')).toBeDefined();
 expect(view.text()).toContain('12.0 MiB');
 await view.find('form').trigger('submit'); await flushPromises();
 expect(api.uploadDocument).toHaveBeenCalledTimes(1);
 release(); await flushPromises();
 expect(api.uploadDocument).toHaveBeenCalledTimes(2);
 const calls = vi.mocked(api.uploadDocument).mock.calls;
 expect(calls.map(call => call[1])).toEqual(files); expect(calls[0][4]).not.toBe(calls[1][4]);
 expect(view.text()).toContain('Сохранено: 2 из 2');
});
it('continues after one file fails and retries only that file with its original key', async () => {
 const view = mountPage(); await flushPromises();
 const files = ['one.html', 'two.html', 'three.html'].map(name => new File(['<html>test</html>'], name, { type: 'text/html' }));
 vi.mocked(api.uploadDocument).mockImplementation(async (_token, file) => { if (file.name === 'two.html') throw new Error('Storage unavailable'); return uploadedFile(file); });
 await chooseFiles(view, files); await view.find('form').trigger('submit'); await flushPromises();
 expect(api.uploadDocument).toHaveBeenCalledTimes(3); expect(view.text()).toContain('Сохранено: 2 из 3');
 const originalKey = vi.mocked(api.uploadDocument).mock.calls[1][4];
 vi.mocked(api.uploadDocument).mockImplementation(async (_token, file) => uploadedFile(file));
 await view.find('form').trigger('submit'); await flushPromises();
 expect(api.uploadDocument).toHaveBeenCalledTimes(4);
 expect(vi.mocked(api.uploadDocument).mock.calls[3][4]).toBe(originalKey);
 expect(vi.mocked(api.uploadDocument).mock.calls[3][1]).toBe(files[1]);
 expect(view.text()).toContain('Сохранено: 3 из 3');
});
it('rejects an oversized member of a batch but uploads the valid member', async () => {
 const view = mountPage(); await flushPromises();
 const large = new File(['x'], 'too-large.pdf', { type: 'application/pdf' }); Object.defineProperty(large, 'size', { value: 10485761 });
 const valid = new File(['<html>test</html>'], 'valid.html', { type: 'text/html' });
 vi.mocked(api.uploadDocument).mockImplementation(async (_token, file) => uploadedFile(file));
 await chooseFiles(view, [large, valid]); await view.find('form').trigger('submit'); await flushPromises();
 expect(api.uploadDocument).toHaveBeenCalledTimes(1); expect(vi.mocked(api.uploadDocument).mock.calls[0][1]).toBe(valid);
 expect(view.text()).toContain('10 MiB'); expect(view.text()).toContain('Сохранено: 1 из 2');
});
it('continues the batch after queue confirmation fails and never reuploads saved originals', async () => {
 const view = mountPage(); await flushPromises();
 const files = ['one.pdf', 'two.pdf'].map(name => new File(['%PDF-1.4'], name, { type: 'application/pdf' }));
 vi.mocked(api.uploadDocument).mockImplementation(async (_token, file) => uploadedFile(file));
 vi.mocked(api.enqueueDocument).mockRejectedValueOnce(new Error('Queue unavailable')).mockResolvedValue({ document_id: 'two.pdf', status: 'queued', attempts: 0, error_code: null, created_at: null, started_at: null, finished_at: null });
 await chooseFiles(view, files); await view.find('form').trigger('submit'); await flushPromises();
 expect(api.uploadDocument).toHaveBeenCalledTimes(2); expect(api.enqueueDocument).toHaveBeenCalledTimes(2);
 expect(view.text()).toContain('Сохранено: 2 из 2'); expect(view.find('[role="alert"]').text()).toContain('Queue unavailable');
 expect(view.find('button[type="submit"]').attributes('disabled')).toBeDefined();
});
it('stops uploading the remaining files when the session changes', async () => {
 const view = mountPage(); await flushPromises();
 let release!: () => void;
 vi.mocked(api.uploadDocument).mockImplementationOnce(async (_token, file) => { await new Promise<void>(resolve => { release = resolve; }); return uploadedFile(file); });
 await chooseFiles(view, ['one.html', 'two.html'].map(name => new File(['<html>test</html>'], name, { type: 'text/html' })));
 await view.find('form').trigger('submit'); await flushPromises();
 useAuth().token = ''; useAuth().user = null; await flushPromises(); release(); await flushPromises();
 expect(api.uploadDocument).toHaveBeenCalledTimes(1); expect(api.enqueueDocument).not.toHaveBeenCalled();
 expect(view.text()).not.toContain('Сохранено:');
});
it('shows a transcript title as text while preserving the original filename', async () => {
 vi.mocked(api.listDocuments).mockResolvedValue([{ id: 'doc', title: '<script>Заголовок</script>', filename: 'original.pdf', family_id: 'family-id', owner_id: 'owner', status: 'uploaded', visibility: 'private', size_bytes: 10, checksum: 'hash', content_type: 'application/pdf', error_code: null, created_at: null }]);
 const view = mountPage(); await flushPromises();
 expect(view.find('.document-record strong').text()).toBe('<script>Заголовок</script>');
 expect(view.find('.document-record').text()).toContain('original.pdf');
 expect(view.find('script').exists()).toBe(false);
});

it('opens an uploaded PDF original for a member even when extraction is unavailable', async () => {
 vi.mocked(api.extractionFormats).mockResolvedValue([]);
 vi.mocked(api.listDocuments).mockResolvedValue([{ ...uploadedFile(new File(['pdf'], 'guide.pdf', { type: 'application/pdf' })), id: 'doc' }]);
 const view = mountPage('member'); await flushPromises();
 await view.find('button[aria-label="Открыть оригинал guide.pdf"]').trigger('click'); await flushPromises();
 expect(api.previewPdf).toHaveBeenCalledWith('jwt', 'doc');
 vi.mocked(api.previewPdf).mockRejectedValue(new Error('Document not found'));
 await view.find('button[aria-label="Открыть оригинал guide.pdf"]').trigger('click'); await flushPromises();
 expect(view.find('[role="alert"]').text()).toContain('Document not found');
});
it('does not offer PDF preview for unfinished uploads or other formats', async () => {
 vi.mocked(api.listDocuments).mockResolvedValue([
  { ...uploadedFile(new File(['pdf'], 'pending.pdf', { type: 'application/pdf' })), status: 'uploading' },
  { ...uploadedFile(new File(['html'], 'guide.html', { type: 'text/html' })) },
  { ...uploadedFile(new File(['pdf'], 'failed.pdf', { type: 'application/pdf' })), status: 'upload_failed' },
 ]);
 const view = mountPage(); await flushPromises();
 expect(view.findAll('button').some(button => button.text().includes('Открыть оригинал'))).toBe(false);
 expect(api.previewPdf).not.toHaveBeenCalled();
});
it('keeps technical metadata collapsed while showing the title, access and primary actions', async () => {
 vi.mocked(api.listDocuments).mockResolvedValue([{ ...uploadedFile(new File(['pdf'], 'guide.pdf', { type: 'application/pdf' })), id: 'doc', title: 'Регламент работы' }]);
 const view = mountPage('member'); await flushPromises();
 expect(view.find('.document-identity strong').text()).toBe('Регламент работы');
 expect(view.find('.document-meta').text()).toContain('Личный');
 const details = view.find('.document-details'); expect(details.attributes('open')).toBeUndefined();
 expect(details.text()).toContain('SHA-256'); expect(details.text()).toContain('Переиндексировать');
 expect(view.find('.document-actions').text()).toContain('Открыть оригинал');
 expect(view.find('.document-actions').text()).not.toContain('Переиндексировать');
});
it('shows search readiness only when an actual index is available', async () => {
 vi.mocked(api.listDocuments).mockResolvedValue([{ ...uploadedFile(new File(['pdf'], 'guide.pdf', { type: 'application/pdf' })), id: 'doc' }]);
 vi.mocked(api.processingStatus).mockResolvedValue({ document_id: 'doc', status: 'succeeded', attempts: 1, error_code: null, created_at: null, started_at: null, finished_at: null });
 const view = mountPage(); await flushPromises();
 expect(view.find('.document-state').text()).toBe('Обработан');
 vi.mocked(api.indexStatus).mockResolvedValue({ document_id: 'doc', status: 'indexed', embedding_model: 'local', embedding_digest: 'digest', dimensions: 768, chunk_count: 3, error_code: null });
 await view.findAll('button').find(button => button.text() === 'Обновить')!.trigger('click'); await flushPromises();
 expect(view.find('.document-state').text()).toBe('Доступен для поиска');
});
it('opens extracted text in a modal, paginates, and reports errors inside it', async () => {
 vi.mocked(api.listDocuments).mockResolvedValue([{ ...uploadedFile(new File(['pdf'], 'guide.pdf', { type: 'application/pdf' })), id: 'doc' }]);
 vi.mocked(api.readPages).mockResolvedValue({ total_pages: 6, pages: [{ page_number: 1, text: 'First page' }] });
 const view = mountPage(); await flushPromises();
 await view.findAll('button').find(button => button.text() === 'Просмотреть текст')!.trigger('click'); await flushPromises();
 expect(view.find('[role="dialog"]').exists()).toBe(true);
 const dialog = view.find('[role="dialog"]').element as HTMLElement;
 expect(dialog.style.background).toBe('rgb(255, 255, 255)');
 expect(dialog.style.color).toBe('rgb(23, 43, 65)');
 expect(dialog.style.colorScheme).toBe('light');
 expect(view.find('[role="dialog"] pre').text()).toBe('First page');
 vi.mocked(api.readPages).mockRejectedValueOnce(new Error('Text unavailable'));
 await view.findAll('button').find(button => button.text() === 'Следующие страницы')!.trigger('click'); await flushPromises();
 expect(api.readPages).toHaveBeenLastCalledWith('jwt', 'doc', 5);
 expect(view.find('[role="dialog"] [role="alert"]').text()).toContain('Text unavailable');
 vi.mocked(api.readPages).mockResolvedValue({ total_pages: 6, pages: [{ page_number: 6, text: 'Last page' }] });
 await view.findAll('button').find(button => button.text() === 'Повторить')!.trigger('click'); await flushPromises();
 expect(view.find('[role="dialog"] pre').text()).toBe('Last page');
 await view.findAll('button').find(button => button.text() === 'Закрыть')!.trigger('click'); await flushPromises();
 expect(view.find('pre').exists()).toBe(false);
});
it('ignores a text response after the popup has been closed', async () => {
 vi.mocked(api.listDocuments).mockResolvedValue([{ ...uploadedFile(new File(['pdf'], 'guide.pdf', { type: 'application/pdf' })), id: 'doc' }]);
 let release!: (value: api.ExtractedPages) => void;
 vi.mocked(api.readPages).mockImplementation(() => new Promise(resolve => { release = resolve; }));
 const view = mountPage(); await flushPromises();
 await view.findAll('button').find(button => button.text() === 'Просмотреть текст')!.trigger('click'); await flushPromises();
 expect(view.find('[role="dialog"]').text()).toContain('Загружаем текст');
 await view.findAll('button').find(button => button.text() === 'Закрыть')!.trigger('click'); await flushPromises();
 release({ total_pages: 1, pages: [{ page_number: 1, text: 'Late response' }] }); await flushPromises();
 expect(view.find('pre').exists()).toBe(false);
 expect(view.text()).not.toContain('Late response');
});
