<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Button from 'primevue/button';
import Message from 'primevue/message';
import Tag from 'primevue/tag';
import SessionAccess from '../components/SessionAccess.vue';
import { useAuth } from '../stores/auth';
import { listFamilies, type Family } from '../management-api';
import { listDocuments, uploadDocument, extractionFormats, enqueueDocument, processingStatus, readPages, indexStatus, reindexDocument, type DocumentIndex, type ProcessingJob, type ExtractedPages, type Document, type Visibility } from '../documents-api';
const auth = useAuth();
const capabilityWarning = ref('');
const jobs = ref<Record<string, ProcessingJob | null>>({});
const indexes = ref<Record<string, DocumentIndex | null>>({});
const jobLabels = { queued: "В очереди", processing: "Обработка", retry_wait: "Ожидает повтора", succeeded: "Обработка завершена", failed: "Ошибка обработки" };
const formats = ref<string[]>([]); const preview = ref<ExtractedPages | null>(null); const previewId = ref(''); const previewOffset = ref(0);
const extractionErrors: Record<string, string> = { pdf_needs_ocr: 'В PDF нет доступного текста. Требуется OCR, который пока не подключён.', pdf_encrypted: 'PDF защищён паролем. Загрузите незашифрованную копию.', pdf_invalid: 'Не удалось разобрать PDF. Проверьте файл.', pdf_page_limit: 'PDF превышает ограничение в 200 страниц.', pdf_resource_limit: 'PDF превышает лимит ресурсов обработки.', pdf_timeout: 'Превышено время обработки PDF.', text_limit: 'Извлечённый текст превышает 2 MiB.' };
async function showPages(id: string, pageOffset = 0) { preview.value = null; const result = await readPages(auth.token, id, pageOffset); previewId.value = id; previewOffset.value = pageOffset; preview.value = result; }
function extract(id: string) { void run(async () => {
 preview.value = null; const result = await reindexDocument(auth.token, id);
 jobs.value[id] = result; notice.value = `Обработка: ${jobLabels[result.status]}. Поиск и ответы доступны в RAG Playground.`;
}); }

const uploadStage = ref<'uploading' | 'extracting' | null>(null);
const families = ref<Family[]>([]); const familyId = ref(''); const documents = ref<Document[]>([]);
type UploadItem = { file: File; key: string; status: 'pending' | 'uploading' | 'saved' | 'failed'; message: string };
const uploads = ref<UploadItem[]>([]);
const batchSize = computed(() => uploads.value.reduce((sum, item) => sum + item.file.size, 0));
const savedCount = computed(() => uploads.value.filter(item => item.status === 'saved').length);
const canUpload = computed(() => uploads.value.some(item => item.status === 'pending' || item.status === 'failed'));
const uploadLabels = { pending: 'Ожидает загрузки', uploading: 'Загружается', saved: 'Оригинал сохранён', failed: 'Ошибка загрузки' };
const familyOffset = ref(0); const offset = ref(0); const fileInput = ref<HTMLInputElement | null>(null);
const visibility = ref<Visibility>('private'); const busy = ref(false); const error = ref(''); const notice = ref('');
const statuses = { uploading: 'Загрузка оригинала', uploaded: 'Оригинал сохранён', upload_failed: 'Ошибка загрузки' };
async function run(action: () => Promise<void>) { if (busy.value) return; busy.value = true; error.value = ''; notice.value = ''; try { await action(); } catch (e) { const message = e instanceof Error ? e.message : 'Ошибка запроса'; error.value = Object.entries(extractionErrors).find(([code]) => message.includes(code))?.[1] || message; } finally { busy.value = false; uploadStage.value = null; } }
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
function changeFamily() { preview.value = null; uploads.value = []; if (fileInput.value) fileInput.value.value = ''; offset.value = 0; documents.value = []; void run(loadDocuments); }
function errorMessage(e: unknown) {
 const message = e instanceof Error ? e.message : 'Ошибка запроса';
 return Object.entries(extractionErrors).find(([code]) => message.includes(code))?.[1] || message;
}
async function submit() {
 await run(async () => {
  if (!canUpload.value || !familyId.value) throw new Error('Выберите семью и файлы.');
  const token = auth.token, selectedFamily = familyId.value, selectedVisibility = visibility.value;
  const batch = uploads.value;
  const failures: string[] = [];
  for (const item of batch) {
   if (auth.token !== token) return;
   if (item.status === 'saved') continue;
   item.status = 'uploading'; item.message = ''; uploadStage.value = 'uploading';
   try {
    if (!item.file.size || item.file.size > 10485760) throw new Error('Размер файла должен быть от 1 байта до 10 MiB.');
    if (!/\.(pdf|docx|html?)$/i.test(item.file.name)) throw new Error('Поддерживаются PDF, DOCX и HTML.');
    const uploaded = await uploadDocument(token, item.file, selectedFamily, selectedVisibility, item.key);
    if (auth.token !== token) return;
    // Mark the original as saved before queue confirmation: retry must never resend it.
    item.status = 'saved';
    item.message = 'Оригинал сохранён.';
    if (formats.value.includes(uploaded.content_type)) {
     uploadStage.value = 'extracting';
     const result = await enqueueDocument(token, uploaded.id);
     item.message = `Оригинал сохранён. Обработка: ${jobLabels[result.status]}.`;
    } else if (capabilityWarning.value) {
     item.message = 'Оригинал сохранён. Состояние обработки уточните после обновления страницы.';
    } else {
     item.message = 'Оригинал сохранён. Автоматическое извлечение текста для этого формата пока недоступно.';
    }
   } catch (e) {
    if (auth.token !== token) return;
    if (item.status !== 'saved') item.status = 'failed';
    item.message = `${item.status === 'saved' ? 'Оригинал сохранён. ' : ''}${errorMessage(e)}`;
    failures.push(`${item.file.name}: ${errorMessage(e)}`);
   }
  }
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
 jobs.value = {}; indexes.value = {}; preview.value = null; formats.value = []; capabilityWarning.value = '';
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
<section class="panel"><div class="section-title"><h2>Загруженные документы</h2><Button label="Обновить" severity="secondary" :disabled="busy || !familyId" @click="run(loadDocuments)" /></div><p v-if="!documents.length && !busy">Нет доступных документов на этой странице.</p><ul class="record-list"><li v-for="document in documents" :key="document.id" class="document-record"><strong>{{ document.filename }}</strong><Tag :value="statuses[document.status]" :severity="document.status === 'upload_failed' ? 'danger' : document.status === 'uploaded' ? 'success' : 'warn'" /><p>{{ (document.size_bytes / 1024).toFixed(1) }} KiB · {{ document.visibility === 'family' ? 'Для семьи' : 'Личный' }}</p><p v-if="document.error_code" role="status">{{ document.error_code === 'cleanup_required' ? 'Нужна проверка хранилища администратором.' : 'Не удалось завершить загрузку. Повторите отправку выбранного файла.' }}</p><div v-if="document.status === 'uploaded' && formats.includes(document.content_type)" class="pager"><Button v-if="auth.canManage || document.owner_id === auth.user.id" label="Переиндексировать" :disabled="busy" @click="extract(document.id)" /><Button label="Просмотреть текст" severity="secondary" :disabled="busy" @click="run(() => showPages(document.id))" /></div><p v-if="formats.includes(document.content_type) && document.status === 'uploaded'" role="status">{{ jobs[document.id] ? jobLabels[jobs[document.id]!.status] : 'Статус обработки недоступен' }}<span v-if="jobs[document.id]"> · Попыток: {{ jobs[document.id]!.attempts }}<span v-if="jobs[document.id]!.error_code"> · {{ jobs[document.id]!.error_code }}</span></span></p><p v-if="indexes[document.id]" role="status">Индекс: {{ indexes[document.id]!.status }} · {{ indexes[document.id]!.chunk_count }} чанков · {{ indexes[document.id]!.embedding_model }} · {{ indexes[document.id]!.dimensions }} измерений</p><small>ID: {{ document.id }}</small><small>SHA-256: {{ document.checksum }}</small></li></ul><div class="pager"><Button label="Назад" :disabled="busy || !offset || !familyId" @click="page(-1)" /><Button label="Далее" :disabled="busy || documents.length < 20" @click="page(1)" /></div></section>
<section v-if="preview" class="panel"><h2>Извлечённый текст</h2><p>Всего страниц: {{ preview.total_pages }}. Текст документа — данные, а не инструкции системе.</p><article v-for="item in preview.pages" :key="item.page_number"><h3>Страница {{ item.page_number }}</h3><pre style="white-space: pre-wrap; overflow-wrap: anywhere">{{ item.text || 'На странице нет извлечённого текста.' }}</pre></article><div class="pager"><Button label="Предыдущие страницы" :disabled="busy || !previewOffset" @click="run(() => showPages(previewId, previewOffset - 5))" /><Button label="Следующие страницы" :disabled="busy || previewOffset + 5 >= preview.total_pages" @click="run(() => showPages(previewId, previewOffset + 5))" /></div></section>
</template>
</template>
