export type Visibility = 'private' | 'family';
export interface Document {
 id: string;
 family_id: string;
 owner_id: string;
 filename: string;
 title?: string | null;
 content_type: string;
 size_bytes: number;
 checksum: string;
 visibility: Visibility;
 status: 'uploading' | 'uploaded' | 'upload_failed';
 error_code: string | null;
 created_at: string | null;
}
export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export function validateUpload(file: { name: string; size: number }): void {
 if (!file.size || file.size > MAX_FILE_BYTES) throw new Error('Размер файла должен быть от 1 байта до 10 MiB.');
 if (!/\.(pdf|docx|html?)$/i.test(file.name)) throw new Error('Поддерживаются PDF, DOCX и HTML.');
}
export const uploadLabels = { uploading: 'Загрузка оригинала', uploaded: 'Оригинал сохранён', upload_failed: 'Ошибка загрузки' };
export const jobLabels = { queued: 'В очереди', processing: 'Обработка', retry_wait: 'Ожидает повтора', succeeded: 'Обработка завершена', failed: 'Ошибка обработки' };
export interface DocumentState { label: string; severity: 'success' | 'danger' | 'warn' | 'info' | 'secondary' }
export function documentState(document: Document, job: { status: keyof typeof jobLabels } | null | undefined, index: { status: string } | null | undefined, supported: boolean, capabilitiesKnown: boolean): DocumentState {
 if (document.status !== 'uploaded') return { label: uploadLabels[document.status], severity: document.status === 'upload_failed' ? 'danger' : 'info' };
 if (job && job.status !== 'succeeded') return { label: jobLabels[job.status], severity: job.status === 'failed' ? 'danger' : job.status === 'retry_wait' ? 'warn' : 'info' };
 if (index?.status === 'indexed') return { label: 'Доступен для поиска', severity: 'success' };
 if (index?.status === 'failed') return { label: 'Ошибка индексации', severity: 'danger' };
 if (!capabilitiesKnown) return { label: 'Оригинал сохранён', severity: 'secondary' };
 if (!supported) return { label: 'Без обработки', severity: 'secondary' };
 return { label: job?.status === 'succeeded' ? 'Обработан' : 'Статус недоступен', severity: 'secondary' };
}
