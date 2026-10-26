// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { uploadDocument, downloadDocument, previewPdf } from '../src/documents-api';
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
it('sends the original File as bounded binary transport with an idempotency key', async () => {
 const file = new File(['%PDF-1.4\n%%EOF'], 'пример & guide.pdf', { type: 'application/pdf' });
 const fetch = vi.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({ id: 'document' }) }); vi.stubGlobal('fetch', fetch);
 await uploadDocument('jwt', file, 'family', 'private', 'upload-key');
 const [url, options] = fetch.mock.calls[0]; const parsed = new URL(url, 'http://localhost');
 expect(parsed.searchParams.get('filename')).toBe(file.name); expect(parsed.searchParams.get('family_id')).toBe('family');
 expect(options.body).toBe(file); expect(options.headers['Idempotency-Key']).toBe('upload-key'); expect(options.headers.Authorization).toBe('Bearer jwt'); expect(options.headers['Content-Type']).toBe('application/pdf');
});
it('uses the shared API error handling for storage failures', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: 'Storage unavailable' }) }));
 await expect(uploadDocument('jwt', new File(['x'], 'guide.pdf'), 'family', 'private', 'key')).rejects.toThrow('Storage unavailable');
});
it('signals an unauthorized token without swallowing the 401', async () => {
 const listener = vi.fn(); window.addEventListener('auth:unauthorized', listener);
 try {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: 'Revoked' }) }));
  await expect(uploadDocument('expired', new File(['x'], 'guide.pdf'), 'family', 'private', 'key')).rejects.toThrow('Войдите снова');
  expect(listener).toHaveBeenCalledOnce(); expect((listener.mock.calls[0][0] as CustomEvent).detail).toBe('expired');
 } finally { window.removeEventListener('auth:unauthorized', listener); }
});

it('downloads binary content with bearer authentication and releases its object URL', async () => {
 vi.useFakeTimers();
 const NativeURL = URL; const createObjectURL = vi.fn().mockReturnValue('blob:synthetic'); const revokeObjectURL = vi.fn();
 vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = createObjectURL; static revokeObjectURL = revokeObjectURL; });
 const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { expect(this.download).toBe('guide.pdf'); expect(this.href).toBe('blob:synthetic'); });
 const blob = new Blob(['synthetic']);
 const fetch = vi.fn().mockResolvedValue({ ok: true, blob: async () => blob }); vi.stubGlobal('fetch', fetch);
 await downloadDocument('jwt', 'doc', 'guide.pdf');
 expect(fetch).toHaveBeenCalledWith('/api/documents/doc/download', expect.objectContaining({ headers: { Authorization: 'Bearer jwt' }, cache: 'no-store' }));
 expect(createObjectURL).toHaveBeenCalledWith(blob); expect(click).toHaveBeenCalledOnce();
 vi.runAllTimers(); expect(revokeObjectURL).toHaveBeenCalledWith('blob:synthetic');
});
it('reports forbidden downloads without saving an error as a file', async () => {
 const blob = vi.fn(); vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, blob, json: async () => ({ detail: 'Document not found' }) }));
 await expect(downloadDocument('jwt', 'doc', 'guide.pdf')).rejects.toThrow('Document not found');
 expect(blob).not.toHaveBeenCalled();
});

it('opens a PDF tab before fetching and revokes its URL only after the tab closes', async () => {
 vi.useFakeTimers();
 const tab = { opener: window, closed: false, location: { replace: vi.fn() }, close: vi.fn() };
 const open = vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
 const NativeURL = URL; const createObjectURL = vi.fn().mockReturnValue('blob:pdf'); const revokeObjectURL = vi.fn();
 vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = createObjectURL; static revokeObjectURL = revokeObjectURL; });
 const fetch = vi.fn().mockImplementation(async () => { expect(open).toHaveBeenCalledOnce(); return { ok: true, blob: async () => new Blob(['%PDF-1.4']) }; }); vi.stubGlobal('fetch', fetch);
 await previewPdf('jwt', 'doc');
 expect(tab.opener).toBeNull(); expect(tab.location.replace).toHaveBeenCalledWith('blob:pdf');
 expect(createObjectURL.mock.calls[0][0].type).toBe('application/pdf');
 expect(fetch).toHaveBeenCalledWith('/api/documents/doc/download', expect.objectContaining({ headers: { Authorization: 'Bearer jwt' } }));
 vi.advanceTimersByTime(1000); expect(revokeObjectURL).not.toHaveBeenCalled();
 tab.closed = true; vi.advanceTimersByTime(1000); expect(revokeObjectURL).toHaveBeenCalledWith('blob:pdf');
});
it('closes the preview tab on denied access and reports popup blocking', async () => {
 const close = vi.fn(); const open = vi.spyOn(window, 'open').mockReturnValue({ opener: null, close } as unknown as Window);
 const fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'Document not found' }) }); vi.stubGlobal('fetch', fetch);
 await expect(previewPdf('jwt', 'doc')).rejects.toThrow('Document not found'); expect(close).toHaveBeenCalledOnce();
 open.mockReturnValue(null); fetch.mockClear();
 await expect(previewPdf('jwt', 'doc')).rejects.toThrow('заблокировал'); expect(fetch).not.toHaveBeenCalled();
});
