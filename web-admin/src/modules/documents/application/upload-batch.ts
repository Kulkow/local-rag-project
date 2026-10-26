import { validateUpload, jobLabels, type Document, type Visibility } from '../domain/document';

export interface UploadItem { file: File; key: string; status: 'pending' | 'uploading' | 'saved' | 'failed'; message: string }
export interface UploadScope { token: string; familyId: string; visibility: Visibility }
export interface UploadPorts {
 upload(token: string, file: File, family: string, visibility: Visibility, key: string): Promise<Document>;
 schedule(token: string, id: string): Promise<{ status: keyof typeof jobLabels }>;
}
export interface UploadContext {
 formats: readonly string[];
 capabilitiesKnown: boolean;
 active(): boolean;
 stage(value: 'uploading' | 'extracting'): void;
 errorMessage(error: unknown): string;
}
export async function uploadBatch(items: UploadItem[], scope: UploadScope, ports: UploadPorts, context: UploadContext): Promise<string[]> {
 const failures: string[] = [];
 for (const item of items) {
  if (!context.active()) break;
  if (item.status === 'saved') continue;
  item.status = 'uploading'; item.message = ''; context.stage('uploading');
  try {
   validateUpload(item.file);
   const uploaded = await ports.upload(scope.token, item.file, scope.familyId, scope.visibility, item.key);
   if (!context.active()) break;
   item.status = 'saved'; item.message = 'Оригинал сохранён.';
   if (context.formats.includes(uploaded.content_type)) {
    context.stage('extracting');
    const result = await ports.schedule(scope.token, uploaded.id);
    item.message = `Оригинал сохранён. Обработка: ${jobLabels[result.status]}.`;
   } else if (!context.capabilitiesKnown) {
    item.message = 'Оригинал сохранён. Состояние обработки уточните после обновления страницы.';
   } else {
    item.message = 'Оригинал сохранён. Автоматическое извлечение текста для этого формата пока недоступно.';
   }
  } catch (error) {
   if (!context.active()) break;
   if (item.status !== 'saved') item.status = 'failed';
   item.message = `${item.status === 'saved' ? 'Оригинал сохранён. ' : ''}${context.errorMessage(error)}`;
   failures.push(`${item.file.name}: ${context.errorMessage(error)}`);
  }
 }
 return failures;
}
