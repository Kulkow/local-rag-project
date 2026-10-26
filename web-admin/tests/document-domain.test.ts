import { expect, it } from 'vitest';
import { validateUpload, documentState, MAX_FILE_BYTES, type Document } from '../src/modules/documents/domain/document';
import { canManage } from '../src/modules/identity/domain/roles';

const document: Document = { id: 'doc', family_id: 'family', owner_id: 'owner', filename: 'guide.pdf', content_type: 'application/pdf', size_bytes: 10, checksum: 'hash', visibility: 'private', status: 'uploaded', error_code: null, created_at: null };
it('validates individual limits rather than a total batch limit', () => {
 expect(() => validateUpload({ name: 'guide.pdf', size: MAX_FILE_BYTES })).not.toThrow();
 expect(() => validateUpload({ name: 'guide.pdf', size: MAX_FILE_BYTES + 1 })).toThrow('10 MiB');
 expect(() => validateUpload({ name: 'guide.pdf', size: 0 })).toThrow();
 expect(() => validateUpload({ name: 'guide.exe', size: 10 })).toThrow('PDF');
});
it('requires an actual index for readiness and exposes a failed reindex', () => {
 expect(documentState(document, { status: 'succeeded' }, null, true, true).label).toBe('Обработан');
 expect(documentState(document, { status: 'succeeded' }, { status: 'indexed' }, true, true).label).toBe('Доступен для поиска');
 expect(documentState(document, { status: 'failed' }, { status: 'indexed' }, true, true).severity).toBe('danger');
});
it('keeps member management denied in the presentation policy', () => {
 expect(canManage('member')).toBe(false); expect(canManage(undefined)).toBe(false);
 expect(canManage('manager')).toBe(true); expect(canManage('admin')).toBe(true);
});
