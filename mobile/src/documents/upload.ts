import type {Api} from '../api/client';
import type {Document, LocalFile, Visibility} from '../api/types';

export const MAX_BYTES = 10 * 1024 * 1024;
export const processableMediaTypes = ['application/pdf', 'image/png', 'image/jpeg'];
export const mimeTypes = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/html', 'image/png', 'image/jpeg'];

export function validateFile(file: LocalFile): void {
  if (!Number.isSafeInteger(file.size) || file.size <= 0 || file.size > MAX_BYTES) {throw new Error('Выберите непустой файл размером до 10 MiB.');}
  if (!file.name || file.name.length > 255 || /[/\\\x00-\x1f\x7f]/.test(file.name)) {throw new Error('Небезопасное или слишком длинное имя файла.');}
  const extension = file.name.toLowerCase().split('.').pop();
  const expected: Record<string, string> = {pdf: mimeTypes[0], docx: mimeTypes[1], html: mimeTypes[2], htm: mimeTypes[2], png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg'};
  if (!extension || !expected[extension] || ![expected[extension], 'application/octet-stream'].includes(file.type)) {throw new Error('Поддерживаются PDF, DOCX, HTML, PNG и JPEG с соответствующим расширением.');}
}

export function validateImageDimensions(width: number | undefined, height: number | undefined): void {
  if (!width || !height || !Number.isSafeInteger(width) || !Number.isSafeInteger(height) ||
      width <= 0 || height <= 0 || width > 12000 || height > 12000 || width * height > 20000000) {
    throw new Error('Снимок должен быть не больше 20 мегапикселей и 12 000 пикселей по стороне.');
  }
}

export interface UploadDraft {
  file: LocalFile;
  family: string;
  visibility: Visibility;
  saved?: Document;
}

export async function sendDraft(api: Api, draft: UploadDraft, active: () => boolean): Promise<string> {
  validateFile(draft.file);
  if (!draft.saved) {draft.saved = await api.upload(draft.file, draft.family, draft.visibility);}
  if (!active()) {return '';}
  // Retry only scheduling after an upload has been acknowledged.
  const formats = await api.formats();
  if (!active()) {return '';}
  if (!formats.includes(draft.saved.content_type)) {
    return 'Оригинал сохранён. Сервер пока не индексирует этот формат; для RAG используйте PDF или PNG/JPEG на сервере с поддержкой OCR.';
  }
  await api.process(draft.saved.id);
  return 'Файл сохранён и поставлен в очередь RAG. Готовность индекса смотрите в списке документов.';
}
