<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { downloadDocument, previewPdf } from '../../documents';
import { RouterLink } from 'vue-router';
import Button from 'primevue/button';
import Message from 'primevue/message';
import { SessionAccess } from '../../identity';
import { useAuth } from '../../identity';
import { listFamilies, type Family } from '../../families';
import { queryRag, type RagAnswer } from '../infrastructure/api';
const auth = useAuth();
const families = ref<Family[]>([]); const familyId = ref(''); const offset = ref(0);
const question = ref(''); const mode = ref<'keyword' | 'vector' | 'hybrid'>('hybrid'); const topK = ref(5);
const resultElement = ref<HTMLElement | null>(null);
const downloading = ref<string | null>(null); const downloadError = ref('');
const sourceDocuments = computed(() => {
 const grouped = new Map<string, { id: string; filename: string; sources: RagAnswer['retrieved_chunks'] }>();
 for (const source of result.value?.retrieved_chunks || []) {
  if (!grouped.has(source.document_id)) grouped.set(source.document_id, { id: source.document_id, filename: source.filename, sources: [] });
  grouped.get(source.document_id)!.sources.push(source);
 }
 return [...grouped.values()];
});
async function download(id: string, filename: string) {
 if (downloading.value) return;
 const token = auth.token; downloading.value = id; downloadError.value = '';
 try { await downloadDocument(token, id, filename); }
 catch (e) { if (auth.token === token) downloadError.value = e instanceof Error ? e.message : 'Не удалось скачать документ.'; }
 finally { downloading.value = null; }
}
async function preview(id: string) {
 if (downloading.value) return;
 const token = auth.token; downloading.value = id; downloadError.value = '';
 try { await previewPdf(token, id); }
 catch (e) { if (auth.token === token) downloadError.value = e instanceof Error ? e.message : 'Не удалось открыть оригинал.'; }
 finally { downloading.value = null; }
}
function openSource(id: number) {
 const element = resultElement.value?.querySelector(`#source-${id}`);
 if (element instanceof HTMLDetailsElement) element.open = true;
}
const busy = ref(false); const error = ref(''); const result = ref<RagAnswer | null>(null);
async function loadFamilies(delta = 0) {
 if (busy.value) return;
 busy.value = true; error.value = '';
 try { offset.value = Math.max(0, offset.value + delta * 20); families.value = await listFamilies(auth.token, offset.value); if (!familyId.value) familyId.value = families.value[0]?.id || ''; }
 catch (e) { error.value = e instanceof Error ? e.message : 'Не удалось загрузить семьи.'; }
 finally { busy.value = false; }
}
async function submit(generate = true) {
 if (busy.value) return;
 error.value = ''; downloadError.value = ''; result.value = null;
 if (!familyId.value || !question.value.trim()) { error.value = 'Выберите семью и введите вопрос.'; return; }
 busy.value = true;
 const token = auth.token, scope = familyId.value;
 try { const answer = await queryRag(token, {family_id: familyId.value, question: question.value.trim(), retrieval_mode: mode.value, top_k: topK.value}, generate); if (auth.token === token && familyId.value === scope) result.value = answer; }
 catch (e) { error.value = e instanceof Error ? e.message : 'Не удалось выполнить запрос.'; }
 finally { busy.value = false; }
}
watch([familyId, mode], () => { result.value = null; });
watch(() => auth.token, token => { downloadError.value = ''; result.value = null; question.value = ''; familyId.value = ''; families.value = []; offset.value = 0; if (token) void loadFamilies(); }, { immediate: true });
</script>
<template>
<div class="rag-page">
<header class="rag-header"><div><p class="eyebrow">БАЗА ЗНАНИЙ</p><h1>Спросите документы</h1><p>Ответы с опорой на ваши источники.</p></div><RouterLink class="upload-link" to="/documents#upload">Загрузить документ ↗</RouterLink></header>
<SessionAccess />
<template v-if="auth.user">
<Message v-if="error" severity="error" role="alert">{{ error }}</Message>
<section class="panel question-panel"><form @submit.prevent="submit(true)">
<div class="scope-row"><label>Семья<select v-model="familyId" :disabled="busy"><option value="">Выберите семью</option><option v-for="family in families" :key="family.id" :value="family.id">{{ family.name }}</option><option v-if="familyId && !families.some(f => f.id === familyId)" :value="familyId">Выбранная семья</option></select></label><div v-if="offset || families.length === 20" class="pager"><Button label="Предыдущие семьи" type="button" severity="secondary" :disabled="busy || !offset" @click="loadFamilies(-1)" /><Button label="Следующие семьи" type="button" severity="secondary" :disabled="busy || families.length < 20" @click="loadFamilies(1)" /></div></div>
<label class="question-field">Ваш вопрос<textarea v-model="question" rows="3" placeholder="Что вы хотите узнать из документов?" maxlength="2000" :disabled="busy" required /></label>
<div class="query-footer"><details class="search-options"><summary>Настройки поиска</summary><div class="option-fields"><label>Режим поиска<select v-model="mode" :disabled="busy"><option value="hybrid">Гибридный</option><option value="vector">По смыслу</option><option value="keyword">По ключевым словам</option></select></label><label>Число фрагментов<input v-model.number="topK" type="number" min="1" max="8" :disabled="busy" /></label></div></details><div class="query-actions"><Button label="Только поиск" type="button" severity="secondary" :disabled="busy || !familyId" @click="submit(false)" /><Button label="Получить ответ" type="submit" :loading="busy" :disabled="busy || !familyId" /></div></div>
</form><p v-if="busy" class="query-progress" role="status" aria-live="polite">Ищем источники и готовим ответ…</p></section>
<section v-if="result" ref="resultElement" class="results" aria-live="polite">
<div class="panel answer-panel"><div class="answer-heading"><h2>{{ result.reason === 'search_only' ? 'Результаты поиска' : 'Ответ по документам' }}</h2><span class="result-meta">{{ sourceDocuments.length }} док. · {{ Math.round(result.timings.total_ms || 0) }} мс</span></div>
<Message v-if="result.abstained && result.reason !== 'search_only'" severity="warn" role="status"><span>{{ result.answer }}</span><small v-if="result.reason" class="abstention-code">Код причины: {{ result.reason }}</small></Message><p v-else-if="result.reason !== 'search_only'" class="answer-text">{{ result.answer }}</p>
<div v-if="result.citations.length" class="citation-list"><a v-for="citation in result.citations" :key="citation.source_id" :href="`#source-${citation.source_id}`" @click="openSource(citation.source_id)"><span>{{ citation.source_id }}</span>{{ citation.filename }} · с. {{ citation.page_number }}</a></div>
<p class="answer-note">Сверяйте ответ с источниками: модель может ошибаться.</p>
</div>
<div class="sources-heading"><h2>Источники</h2><span>{{ result.retrieved_chunks.length }} фрагментов</span></div>
<Message v-if="downloadError" severity="error" role="alert">{{ downloadError }}</Message>
<div v-if="!result.retrieved_chunks.length" class="empty">Подходящих доступных фрагментов нет. Проверьте индексацию или смените режим поиска.</div>
<article v-for="doc in sourceDocuments" :key="doc.id" class="panel source-card">
<div class="source-heading"><div class="source-title"><span class="file-badge">ФАЙЛ</span><h3>{{ doc.filename }}</h3></div><div class="source-actions"><Button v-if="/\.pdf$/i.test(doc.filename)" label="Посмотреть оригинал" severity="secondary" size="small" :aria-label="`Посмотреть оригинал ${doc.filename}`" :disabled="!!downloading" @click="preview(doc.id)" /><Button label="Скачать файл" severity="secondary" size="small" :aria-label="`Скачать ${doc.filename}`" :loading="downloading === doc.id" :disabled="!!downloading" @click="download(doc.id, doc.filename)" /></div></div>
<details v-for="source in doc.sources" :id="`source-${source.source_id}`" :key="source.chunk_id" class="source-fragment"><summary><span class="source-number">{{ source.source_id }}</span><span class="fragment-summary"><strong>Страница {{ source.page_number }}</strong><span>{{ source.text.slice(0, 150) }}{{ source.text.length > 150 ? '…' : '' }}</span></span><span class="source-score" title="Оценка ранжирования; не вероятность правильности">{{ source.score.toFixed(3) }}</span></summary><pre>{{ source.text }}</pre><small>Документ: {{ source.document_id }} · Чанк: {{ source.chunk_id }}</small></details>
</article>
<details class="technical-details"><summary>Подробности запроса</summary><dl><div><dt>Режим</dt><dd>{{ result.retrieval_mode === 'hybrid' ? 'Гибридный' : result.retrieval_mode === 'vector' ? 'Векторный' : 'Ключевые слова' }}</dd></div><div v-if="result.retrieval_mode === 'hybrid'"><dt>Ранжирование</dt><dd>{{ result.reranked ? 'RRF + LLM reranker' : 'RRF' }}</dd></div><div v-if="result.timings.reranking_ms !== undefined"><dt>Переранжирование</dt><dd>{{ result.timings.reranking_ms }} мс</dd></div><div><dt>Модель</dt><dd>{{ result.chat_model || 'не вызывалась' }}</dd></div><div><dt>Поиск</dt><dd>{{ result.timings.retrieval_ms || 0 }} мс</dd></div><div><dt>Генерация</dt><dd>{{ result.timings.generation_ms || 0 }} мс</dd></div></dl><small>Trace ID: {{ result.trace_id }}</small></details>
</section>
<div v-else-if="!busy" class="rag-empty"><span>ВОПРОС → ИСТОЧНИКИ → ОТВЕТ</span><p>Задайте вопрос, чтобы найти нужное в документах.</p></div>
</template>
</div>
</template>
<style scoped>
.abstention-code{display:block;margin-top:8px;font-size:11px;overflow-wrap:anywhere}

.rag-page{max-width:1000px;margin:0 auto}.rag-header{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:24px}.rag-header .eyebrow{margin-top:0}.rag-header h1{font-size:32px}.rag-header p:last-child{margin-bottom:0;color:#65778b}.upload-link{color:#16736a;text-decoration:none;font-size:13px;font-weight:600;white-space:nowrap}.question-panel{padding:24px;box-shadow:0 4px 22px #172b4105}.question-panel form{display:block}.scope-row{display:flex;align-items:end;gap:16px;margin-bottom:22px}.scope-row label{min-width:220px}.question-field{font-size:15px;font-weight:600}.question-field textarea{width:100%;resize:vertical;min-height:110px;border:1px solid #ccd9df;border-radius:10px;padding:16px;font:inherit;font-size:16px;font-weight:400;line-height:1.6;background:#fafcfd;color:#172b41}.question-field textarea:focus{outline:2px solid #227d72;outline-offset:2px}.query-footer{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:18px;margin-top:18px}.query-actions{display:flex;gap:10px;flex-wrap:wrap}.search-options summary,.technical-details summary{cursor:pointer;color:#526b7d;font-size:13px}.option-fields{display:flex;gap:14px;flex-wrap:wrap;margin-top:14px}.option-fields input{padding:10px;border:1px solid #bdcbd7;border-radius:6px;width:100px}.query-progress{font-size:13px}.answer-panel{border-top:3px solid #247e73;padding:26px}.answer-heading,.sources-heading,.source-heading{display:flex;justify-content:space-between;align-items:center;gap:16px}.answer-heading h2,.sources-heading h2{margin:0}.result-meta,.sources-heading>span{color:#65778b;font-size:12px;white-space:nowrap}.answer-text{white-space:pre-wrap;line-height:1.85;font-size:16px;color:#20374c;overflow-wrap:anywhere}.citation-list{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}.citation-list a{display:inline-flex;align-items:center;gap:7px;max-width:100%;overflow-wrap:anywhere;background:#edf5f3;color:#206c62;border:1px solid #d9e9e5;border-radius:7px;padding:7px 10px;font-size:12px;text-decoration:none}.citation-list a span{font-weight:700}.answer-note{font-size:12px;color:#7c8995;margin-bottom:0;margin-top:20px}.sources-heading{margin:26px 0 12px}.source-card{padding:18px 20px;margin-bottom:12px}.source-heading{margin-bottom:10px}.source-actions{display:flex;gap:8px;flex-wrap:wrap}.source-title{display:flex;align-items:center;gap:10px;min-width:0}.source-title h3{font-size:14px;text-transform:none;overflow-wrap:anywhere;margin:0}.file-badge{font-size:9px;letter-spacing:.08em;color:#527788;background:#eff4f7;padding:7px;border-radius:5px}.source-fragment{border-top:1px solid #edf1f4;padding:12px 0;scroll-margin-top:20px}.source-fragment:last-child{padding-bottom:0}.source-fragment summary{display:flex;gap:12px;align-items:start;cursor:pointer;list-style:none}.source-fragment summary::after{content:'+';color:#65818a}.source-fragment[open] summary::after{content:'−'}.source-number{background:#f0f5f7;color:#527181;border-radius:5px;padding:3px 7px;font-size:11px}.fragment-summary{flex:1;min-width:0;display:flex;flex-direction:column;gap:5px;font-size:12px;line-height:1.6}.fragment-summary strong{font-weight:500}.fragment-summary>span{color:#718392;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.source-score{font-size:11px;color:#718392;padding-top:4px}.source-fragment pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fb;padding:16px;border-radius:8px;font:inherit;font-size:13px;line-height:1.8}.source-fragment small,.technical-details small{font-size:11px;color:#7c8995;overflow-wrap:anywhere}.technical-details{margin:20px 0;color:#65778b}.technical-details dl{display:flex;gap:24px;flex-wrap:wrap;font-size:12px}.technical-details dt{color:#8493a1;margin-bottom:5px}.technical-details dd{margin:0}.rag-empty{text-align:center;padding:45px 20px;color:#8396a5}.rag-empty span{font-size:10px;letter-spacing:.15em}.rag-empty p{font-size:14px}@media(max-width:700px){.rag-header{align-items:start;flex-direction:column;gap:12px}.rag-header h1{font-size:28px}.question-panel,.answer-panel{padding:18px}.query-footer{align-items:start;flex-direction:column}.query-actions{width:100%}.answer-heading{align-items:start;flex-direction:column;gap:8px}.source-heading{align-items:start;flex-wrap:wrap}.source-card{padding:16px}.scope-row label{min-width:0;width:100%}}
</style>
