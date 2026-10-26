<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Button from 'primevue/button';
import Message from 'primevue/message';
import Tag from 'primevue/tag';
import Dialog from 'primevue/dialog';
import { SessionAccess } from '../../identity';
import { useAuth } from '../../identity';
import { listFamilies, type Family } from '../../families';
import { previewPdf, listDocuments, uploadDocument, extractionFormats, enqueueDocument, processingStatus, readPages, indexStatus, reindexDocument, type DocumentIndex, type ProcessingJob, type ExtractedPages, type Document, type Visibility } from '../infrastructure/api';
import { documentState as resolveDocumentState, jobLabels, uploadLabels as statuses } from '../domain/document';
import { uploadBatch, type UploadItem } from '../application/upload-batch';
const auth = useAuth();
const capabilityWarning = ref('');
const jobs = ref<Record<string, ProcessingJob | null>>({});
const indexes = ref<Record<string, DocumentIndex | null>>({});
const formats = ref<string[]>([]); const preview = ref<ExtractedPages | null>(null); const previewId = ref(''); const previewOffset = ref(0);
const extractionErrors: Record<string, string> = { pdf_needs_ocr: 'В PDF нет доступного текста. Требуется OCR, который пока не подключён.', pdf_encrypted: 'PDF защищён паролем. Загрузите незашифрованную копию.', pdf_invalid: 'Не удалось разобрать PDF. Проверьте файл.', pdf_page_limit: 'PDF превышает ограничение в 200 страниц.', pdf_resource_limit: 'PDF превышает лимит ресурсов обработки.', pdf_timeout: 'Превышено время обработки PDF.', text_limit: 'Извлечённый текст превышает 2 MiB.' };
const previewVisible = ref(false); const previewLoading = ref(false); const previewError = ref('');
let previewRequest = 0;
async function showPages(id: string, pageOffset = 0) {
 const request = ++previewRequest, token = auth.token;
 previewVisible.value = true; previewLoading.value = true; previewError.value = ''; preview.value = null;
 previewId.value = id; previewOffset.value = pageOffset;
 try {
  const result = await readPages(token, id, pageOffset);
  if (request === previewRequest && auth.token === token && previewVisible.value) preview.value = result;
 } catch (e) {
  if (request === previewRequest && auth.token === token && previewVisible.value) previewError.value = errorMessage(e);
 } finally { if (request === previewRequest) previewLoading.value = false; }
}
watch(previewVisible, visible => {
 if (!visible) { ++previewRequest; preview.value = null; previewError.value = ''; previewLoading.value = false; }
}, { flush: 'sync' });
function openOriginal(id: string) { void run(() => previewPdf(auth.token, id)); }
function extract(id: string) { void run(async () => {
 previewVisible.value = false; preview.value = null; const result = await reindexDocument(auth.token, id);
 jobs.value[id] = result; notice.value = `Обработка: ${jobLabels[result.status]}. Поиск и ответы доступны в RAG Playground.`;
}); }

const uploadStage = ref<'uploading' | 'extracting' | null>(null);
const families = ref<Family[]>([]); const familyId = ref(''); const documents = ref<Document[]>([]);
const uploads = ref<UploadItem[]>([]);
const batchSize = computed(() => uploads.value.reduce((sum, item) => sum + item.file.size, 0));
const savedCount = computed(() => uploads.value.filter(item => item.status === 'saved').length);
const canUpload = computed(() => uploads.value.some(item => item.status === 'pending' || item.status === 'failed'));
const uploadLabels = { pending: 'Ожидает загрузки', uploading: 'Загружается', saved: 'Оригинал сохранён', failed: 'Ошибка загрузки' };
const familyOffset = ref(0); const offset = ref(0); const fileInput = ref<HTMLInputElement | null>(null);
const visibility = ref<Visibility>('private'); const busy = ref(false); const error = ref(''); const notice = ref('');
async function run(action: () => Promise<void>) { if (busy.value) return; busy.value = true; error.value = ''; notice.value = ''; try { await action(); } catch (e) { const message = e instanceof Error ? e.message : 'Ошибка запроса'; error.value = Object.entries(extractionErrors).find(([code]) => message.includes(code))?.[1] || message; } finally { busy.value = false; uploadStage.value = null; } }
function documentState(document: Document) {
 return resolveDocumentState(document, jobs.value[document.id], indexes.value[document.id], formats.value.includes(document.content_type), !capabilityWarning.value);
}
function fileSize(bytes: number) { return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MiB` : `${(bytes / 1024).toFixed(1)} KiB`; }
function fileType(document: Document) { return document.filename.split('.').pop()?.toUpperCase() || 'ФАЙЛ'; }
async function loadDocuments() {
 if (!familyId.value) return;
 const loaded = await listDocuments(auth.token, familyId.value, offset.value);
 documents.value = loaded;
 const states = await Promise.all(loaded.filter(d => d.status === 'uploaded' && formats.value.includes(d.content_type)).map(async d => {
  try { return [d.id, await processingStatus(auth.token, d.id)] as const; }
  catch { return [d.id, null] as const; }
 }));
 jobs.value = Object.fromEntries(states);
 const indexStates = await Promise.all(loaded.filter(d => d.status === 'uploaded' && formats.value.includes(d.content_type)).map(async d => {
  try { return [d.id, await indexStatus(auth.token, d.id)] as const; }
  catch { return [d.id, null] as const; }
 }));
 indexes.value = Object.fromEntries(indexStates);
}
function chooseFile(event: Event) {
 uploads.value = Array.from((event.target as HTMLInputElement).files || []).map(file => ({ file, key: crypto.randomUUID(), status: 'pending', message: '' }));
 error.value = ''; notice.value = '';
}
function changeFamily() { previewVisible.value = false; preview.value = null; uploads.value = []; if (fileInput.value) fileInput.value.value = ''; offset.value = 0; documents.value = []; void run(loadDocuments); }
function errorMessage(e: unknown) {
 const message = e instanceof Error ? e.message : 'Ошибка запроса';
 return Object.entries(extractionErrors).find(([code]) => message.includes(code))?.[1] || message;
}
async function submit() {
 await run(async () => {
  if (!canUpload.value || !familyId.value) throw new Error('Выберите семью и файлы.');
  const token = auth.token, selectedFamily = familyId.value, selectedVisibility = visibility.value;
  const batch = uploads.value;
  const failures = await uploadBatch(batch, { token, familyId: selectedFamily, visibility: selectedVisibility }, {
   upload: uploadDocument, schedule: enqueueDocument,
  }, { formats: formats.value, capabilitiesKnown: !capabilityWarning.value,
   active: () => auth.token === token, stage: stage => { uploadStage.value = stage; }, errorMessage });
  if (auth.token !== token) return;
  offset.value = 0;
  error.value = failures.join(' · ');
  if (savedCount.value) notice.value = `Сохранено: ${savedCount.value} из ${batch.length}. Поиск и ответы доступны в RAG Playground.`;
  try { await loadDocuments(); }
  catch (e) { error.value = [error.value, `Не удалось обновить список: ${errorMessage(e)}`].filter(Boolean).join(' · '); }
 });
}
function page(delta: number) { void run(async () => { offset.value = Math.max(0, offset.value + delta * 20); await loadDocuments(); }); }
function familyPage(delta: number) { void run(async () => { familyOffset.value = Math.max(0, familyOffset.value + delta * 20); families.value = await listFamilies(auth.token, familyOffset.value); if (!familyId.value) { familyId.value = families.value[0]?.id || ''; await loadDocuments(); } }); }
watch(visibility, () => {
 // A changed ACL is a new operation; preserve results of completed uploads.
 for (const item of uploads.value) if (item.status === 'pending') item.key = crypto.randomUUID();
});
watch(() => auth.token, token => {
 jobs.value = {}; indexes.value = {}; previewVisible.value = false; preview.value = null; formats.value = []; capabilityWarning.value = '';
 familyId.value = ''; families.value = []; documents.value = []; uploads.value = []; if (fileInput.value) fileInput.value.value = ''; offset.value = 0; familyOffset.value = 0;
 if (token) void run(async () => {
  const [familyResult, formatResult] = await Promise.allSettled([listFamilies(token), extractionFormats(token)]);
  if (formatResult.status === 'fulfilled') formats.value = formatResult.value;
  else capabilityWarning.value = 'Сведения об автоматической обработке недоступны. Загрузка оригинала доступна; обновите страницу для проверки обработки.';
  if (familyResult.status === 'rejected') throw familyResult.reason;
  families.value = familyResult.value; familyId.value = families.value[0]?.id || '';
  await loadDocuments();
 });
}, { immediate: true });
</script>
<template>
<header><p class="eyebrow">БАЗА ЗНАНИЙ</p><h1>Документы для RAG</h1><a href="#upload">Перейти к форме загрузки</a><p>Загрузка оригиналов PDF, DOCX и HTML. После загрузки PDF попадает в очередь: извлечение текста, чанкинг и эмбеддинги. Поиск и ответы доступны в RAG Playground. Сканы требуют OCR.</p></header>
<SessionAccess />
<Message v-if="!auth.user" severity="info">Чтобы загрузить документ, войдите в свою учётную запись.</Message>
<template v-if="auth.user">
<Message v-if="capabilityWarning" severity="warn">{{ capabilityWarning }}</Message>
<Message v-if="error" severity="error" role="alert">{{ error }}</Message><Message v-if="notice" severity="success" role="status">{{ notice }}</Message><p v-if="busy" role="status" aria-live="polite">{{ uploadStage === 'uploading' ? 'Сохраняем оригинал…' : uploadStage === 'extracting' ? 'Оригинал сохранён. Проверяем очередь обработки…' : 'Выполняется запрос…' }}</p>
<section class="panel"><h2>Семья и доступ</h2><label>Семья<select v-model="familyId" :disabled="busy" @change="changeFamily"><option value="">Выберите семью</option><option v-for="family in families" :key="family.id" :value="family.id">{{ family.name }}</option><option v-if="familyId && !families.some(f => f.id === familyId)" :value="familyId">Выбранная семья</option></select></label><div class="pager"><Button label="Обновить список семей" severity="secondary" :disabled="busy" @click="familyPage(0)" /><Button label="Предыдущие семьи" severity="secondary" :disabled="busy || !familyOffset" @click="familyPage(-1)" /><Button label="Следующие семьи" severity="secondary" :disabled="busy || families.length < 20" @click="familyPage(1)" /></div><p v-if="!families.length && !busy">Доступных семей на этой странице нет. Создайте семью или попросите администратора проверить вашу связь с участником.</p></section>
<section id="upload" class="panel"><h2>Загрузить файлы пакетом</h2>
<Message v-if="!familyId && !busy" severity="info"><template v-if="auth.isAdmin">Сначала создайте или выберите семью. <a href="/families">Открыть управление семьями</a>.</template><template v-else>Сначала выберите семью. Если список пуст, попросите администратора проверить вашу связь с участником семьи.</template></Message><form @submit.prevent="submit"><label>Документы (до 10 MiB каждый)<input ref="fileInput" type="file" multiple accept=".pdf,.docx,.html,.htm" :disabled="busy || !familyId" @change="chooseFile" /></label><label>Кто видит документ<select v-model="visibility" :disabled="busy || !familyId || uploads.some(item => item.status !== 'pending')"><option value="private">Только владелец и администратор</option><option value="family">Участники этой семьи</option></select></label><Button :label="uploads.some(item => item.status === 'failed') ? 'Повторить неуспешные' : 'Загрузить файлы'" type="submit" :disabled="busy || !canUpload || !familyId" :loading="busy" /></form><div v-if="uploads.length" aria-live="polite"><p>Выбрано файлов: {{ uploads.length }} · {{ (batchSize / 1048576).toFixed(1) }} MiB · Сохранено: {{ savedCount }} из {{ uploads.length }}</p><ul class="record-list"><li v-for="item in uploads" :key="item.key"><strong>{{ item.file.name }}</strong> · {{ (item.file.size / 1048576).toFixed(1) }} MiB · {{ uploadLabels[item.status] }}<p v-if="item.message">{{ item.message }}</p></li></ul></div><p>Можно выбрать несколько файлов. Общий размер пакета может превышать 10 MiB: файлы отправляются по одному. Лимит одного файла — 10 MiB. Ошибка одного файла не останавливает остальные; повторяются только неуспешные загрузки.</p><p>Повторное нажатие с тем же файлом после сетевой ошибки не создаст дубликат. PDF обрабатываются последовательно в фоновом worker. Статус обновляется кнопкой «Обновить». DOCX и HTML сохраняются без обработки. При ошибке обработки повторите извлечение в списке документов. Файл не отправляется модели на этапе загрузки.</p></section>
<section class="panel documents-catalog" aria-labelledby="documents-heading">
 <div class="catalog-header"><div><h2 id="documents-heading">Ваши документы</h2><p>На странице: {{ documents.length }}<span v-if="busy"> · Обновляем…</span></p></div><Button label="Обновить" severity="secondary" size="small" :disabled="busy || !familyId" @click="run(loadDocuments)" /></div>
 <div v-if="!documents.length && !busy" class="catalog-empty"><span class="empty-symbol" aria-hidden="true">▤</span><h3>Здесь пока нет документов</h3><p>Нет доступных документов на этой странице.</p><a href="#upload">Перейти к загрузке ↑</a></div>
 <ul class="record-list documents-list">
  <li v-for="document in documents" :key="document.id" class="document-record">
   <div class="document-main">
    <div class="document-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M8 12h8M8 16h5"/></svg></div>
    <div class="document-identity"><strong>{{ document.title || document.filename }}</strong><span v-if="document.title" class="document-filename">{{ document.filename }}</span><div class="document-meta"><span class="format-label">{{ fileType(document) }}</span><span>{{ fileSize(document.size_bytes) }}</span><span>{{ document.visibility === 'family' ? 'Для семьи' : 'Личный' }}</span></div></div>
    <Tag class="document-state" :value="documentState(document).label" :severity="documentState(document).severity" />
   </div>
   <p v-if="document.error_code" class="document-warning" role="status">{{ document.error_code === 'cleanup_required' ? 'Нужна проверка хранилища администратором.' : 'Не удалось завершить загрузку. Повторите отправку выбранного файла.' }}</p>
   <p v-if="jobs[document.id]?.error_code" class="document-warning" role="status">{{ extractionErrors[jobs[document.id]!.error_code!] || 'Обработка завершилась ошибкой. Подробности — в сведениях о документе.' }}</p>
   <div class="document-footer">
    <div v-if="document.status === 'uploaded'" class="document-actions"><Button v-if="document.content_type === 'application/pdf'" label="Открыть оригинал" severity="secondary" size="small" :aria-label="`Открыть оригинал ${document.filename}`" :disabled="busy" @click="openOriginal(document.id)" /><Button v-if="formats.includes(document.content_type)" label="Просмотреть текст" severity="secondary" text size="small" :disabled="busy" @click="showPages(document.id)" /></div>
    <details class="document-details"><summary>Сведения о документе</summary><div class="document-details-body"><dl><div><dt>ID</dt><dd>{{ document.id }}</dd></div><div><dt>SHA-256</dt><dd>{{ document.checksum }}</dd></div><div><dt>Оригинал</dt><dd>{{ statuses[document.status] }}</dd></div><div v-if="jobs[document.id]"><dt>Обработка</dt><dd>{{ jobLabels[jobs[document.id]!.status] }} · Попыток: {{ jobs[document.id]!.attempts }}<span v-if="jobs[document.id]!.error_code"> · {{ jobs[document.id]!.error_code }}</span></dd></div><div v-if="indexes[document.id]"><dt>Индекс: {{ indexes[document.id]!.status }}</dt><dd>{{ indexes[document.id]!.chunk_count }} чанков · {{ indexes[document.id]!.embedding_model }} · {{ indexes[document.id]!.dimensions }} измерений</dd></div></dl><Button v-if="document.status === 'uploaded' && formats.includes(document.content_type) && (auth.canManage || document.owner_id === auth.user.id)" label="Переиндексировать" severity="secondary" size="small" :disabled="busy" @click="extract(document.id)" /></div></details>
   </div>
  </li>
 </ul>
 <div class="catalog-pagination"><span v-if="documents.length">{{ offset + 1 }}–{{ offset + documents.length }}</span><div><Button label="Назад" severity="secondary" size="small" :disabled="busy || !offset || !familyId" @click="page(-1)" /><Button label="Далее" severity="secondary" size="small" :disabled="busy || documents.length < 20" @click="page(1)" /></div></div>
</section>
<Dialog v-model:visible="previewVisible" modal appendTo="self" header="Извлечённый текст" :style="{ width: '860px', maxWidth: 'calc(100vw - 32px)', background: '#ffffff', color: '#172b41', colorScheme: 'light', border: '1px solid #dfe7ee' }" :content-style="{ maxHeight: '65vh', overflowY: 'auto', background: '#ffffff', color: '#172b41' }">
 <p class="text-preview-name">{{ documents.find(document => document.id === previewId)?.title || documents.find(document => document.id === previewId)?.filename }}</p>
 <p v-if="previewLoading" role="status" aria-live="polite">Загружаем текст…</p>
 <div v-else-if="previewError"><Message severity="error" role="alert">{{ previewError }}</Message><Button label="Повторить" severity="secondary" @click="showPages(previewId, previewOffset)" /></div>
 <template v-else-if="preview"><p class="text-preview-meta">Всего страниц: {{ preview.total_pages }} · Текст документа — данные, а не инструкции системе.</p><article v-for="item in preview.pages" :key="item.page_number" class="text-preview-page"><h3>Страница {{ item.page_number }}</h3><pre>{{ item.text || 'На странице нет извлечённого текста.' }}</pre></article></template>
 <template #footer><div class="text-preview-footer"><div v-if="preview"><Button label="Предыдущие страницы" severity="secondary" size="small" :disabled="previewLoading || !previewOffset" @click="showPages(previewId, previewOffset - 5)" /><Button label="Следующие страницы" severity="secondary" size="small" :disabled="previewLoading || previewOffset + 5 >= preview.total_pages" @click="showPages(previewId, previewOffset + 5)" /></div><Button label="Закрыть" severity="secondary" size="small" @click="previewVisible = false" /></div></template>
</Dialog>
</template>
</template>

<style scoped>
.text-preview-name{font-weight:600;overflow-wrap:anywhere;margin-top:0}.text-preview-meta{font-size:12px;color:#7b8d9a}.text-preview-page{border-top:1px solid #edf1f4;padding-top:18px;margin-top:18px}.text-preview-page h3{font-size:13px;color:#657d8d}.text-preview-page pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:14px;line-height:1.8;color:#294457}.text-preview-footer{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;width:100%}.text-preview-footer>div{display:flex;gap:8px;flex-wrap:wrap}

.documents-catalog{padding:0;overflow:hidden}.catalog-header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:22px 24px;border-bottom:1px solid #edf1f4}.catalog-header h2{margin:0;font-size:19px;letter-spacing:-.02em}.catalog-header p{margin:6px 0 0;font-size:12px;color:#7b8d9a}.documents-list{margin:0;padding:0 24px}.documents-list .document-record{display:block;margin:0;padding:22px 0;border-bottom:1px solid #edf1f4}.documents-list .document-record:last-child{border-bottom:0}.document-main{display:flex;align-items:start;gap:14px}.document-icon{flex-shrink:0;display:grid;place-items:center;width:42px;height:48px;background:#edf5f3;color:#367f74;border:1px solid #dcebe6;border-radius:9px}.document-icon svg{width:25px;height:25px}.document-identity{flex:1;min-width:0}.document-identity>strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;font-size:15px;line-height:1.6;font-weight:600;color:#243e50}.document-filename{display:block;font-size:12px;color:#7c8d99;margin-top:3px;overflow-wrap:anywhere}.document-meta{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:8px;font-size:11px;color:#7a8b97}.document-meta>span+span:before{content:'·';margin-right:10px;color:#bbc7ce}.format-label{font-weight:600;letter-spacing:.04em;color:#557b82}.document-state{flex-shrink:0;font-size:11px;margin-top:3px}.document-footer{margin:13px 0 0 56px}.document-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.document-details{margin-top:12px}.document-details summary{cursor:pointer;width:fit-content;color:#82929d;font-size:11px}.document-details summary:hover{color:#27796e}.document-details-body{margin-top:12px;padding:14px 16px;background:#f7f9fb;border:1px solid #edf1f4;border-radius:8px}.document-details dl{margin:0 0 12px;font-size:11px;line-height:1.7}.document-details dl>div{display:grid;grid-template-columns:90px minmax(0,1fr);gap:12px;margin:5px 0}.document-details dt{color:#84949f}.document-details dd{margin:0;overflow-wrap:anywhere;color:#4c6577}.document-warning{margin:10px 0 0 56px!important;width:auto!important;color:#a35d21;font-size:12px;line-height:1.6}.catalog-pagination{display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:1px solid #edf1f4;padding:16px 24px;color:#7c8d99;font-size:12px}.catalog-pagination>div{display:flex;gap:8px;margin-left:auto}.catalog-empty{text-align:center;padding:36px 20px 28px;color:#82929d}.empty-symbol{display:inline-grid;place-items:center;background:#f0f6f4;width:46px;height:46px;border-radius:12px;color:#62938b;font-size:25px}.catalog-empty h3{font-size:15px;margin:16px 0 6px;text-transform:none;color:#4c6577}.catalog-empty p{font-size:12px}.catalog-empty a{color:#287c70;font-size:12px;text-decoration:none}@media(max-width:650px){.catalog-header{padding:18px}.documents-list{padding:0 18px}.document-main{flex-wrap:wrap;gap:10px}.document-icon{width:34px;height:40px}.document-identity{flex-basis:calc(100% - 44px)}.document-state{margin-left:44px}.document-footer,.document-warning{margin-left:0!important}.catalog-pagination{padding:14px 18px}.document-details dl>div{grid-template-columns:1fr;gap:0}.document-actions{gap:5px}}
</style>
