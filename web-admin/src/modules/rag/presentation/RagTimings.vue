<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{ timings: Record<string, number>; traceId?: string; failed?: boolean; activeStages?: string[] }>();
const labels: Record<string, string> = {
 request_ms: 'Всего на сервере (с ожиданием слота)',
 capacity_wait_ms: 'Ожидание свободного слота',
 total_ms: 'Выполнение RAG',
 retrieval_ms: 'Поиск и подготовка контекста — всего',
 scope_ms: 'Определение доступных документов',
 embedding_identity_ms: 'Проверка embedding-модели',
 query_embedding_ms: 'Векторизация вопроса',
 keyword_search_ms: 'Поиск по ключевым словам (PostgreSQL)',
 vector_search_ms: 'Векторный поиск (Qdrant)',
 candidate_read_ms: 'Чтение и проверка найденных фрагментов',
 rrf_ms: 'Объединение результатов (RRF)',
 query_rewriting_ms: 'Переформулировка вопроса (LLM)',
 query_retry_ms: 'Повторный поиск — всего',
 reranking_ms: 'Переранжирование (LLM)',
 context_ms: 'Подготовка контекста',
 acl_revalidation_ms: 'Повторные проверки доступа',
 generation_ms: 'Генерация ответа (LLM)',
 citation_validation_ms: 'Проверка ответа и цитат',
};
const rows = computed(() => {
 const keys = [...Object.keys(labels), ...Object.keys(props.timings).filter(key => !(key in labels))];
 return keys.filter(key => Number.isFinite(props.timings[key]) && props.timings[key]! >= 0)
  .map(key => ({ key, label: labels[key] || key, value: props.timings[key]! }));
});
function duration(ms: number): string {
 return ms >= 1000 ? `${(ms / 1000).toFixed(2)} с` : `${Number(ms.toFixed(2))} мс`;
}
</script>

<template>
<section class="panel rag-timings" aria-label="Время этапов RAG">
 <h2>Время этапов RAG</h2>
 <p v-if="failed" role="status">Запрос завершился с ошибкой. Показано время до остановки, включая прерванный этап.</p>
 <p>Только выполненные этапы. Повторные вызовы суммируются. Общие интервалы включают вложенные этапы — строки нельзя складывать.</p>
 <table>
  <caption class="visually-hidden">Длительность этапов последнего запроса</caption>
  <thead><tr><th scope="col">Этап</th><th scope="col">Время</th></tr></thead>
  <tbody><tr v-for="row in rows" :key="row.key" :data-stage="row.key"><th scope="row">{{ row.label }}<span v-if="activeStages?.includes(row.key.replace(/_ms$/, ''))" class="running"> · выполняется</span></th><td :title="`${row.value} мс`">{{ duration(row.value) }}</td></tr></tbody>
 </table>
 <small v-if="traceId">Trace ID: {{ traceId }}</small>
</section>
</template>

<style scoped>
.running{color:#16736a;font-size:12px}.rag-timings{padding:20px;margin:20px 0}.rag-timings h2{margin-top:0;font-size:18px}.rag-timings p{font-size:12px;color:#526b7d;line-height:1.6}.rag-timings table{width:100%;border-collapse:collapse;font-size:13px}.rag-timings th,.rag-timings td{padding:9px 0;border-bottom:1px solid #e3eaf0;text-align:left}.rag-timings tbody th{font-weight:400}.rag-timings td,.rag-timings thead th:last-child{text-align:right;white-space:nowrap;padding-left:12px;font-variant-numeric:tabular-nums}.rag-timings small{display:block;margin-top:14px;overflow-wrap:anywhere;color:#526b7d}.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
</style>
