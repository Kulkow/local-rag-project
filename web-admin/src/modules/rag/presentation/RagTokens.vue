<script setup lang="ts">
import type { components } from '../../../shared/infrastructure/schema';

defineProps<{ usage?: components['schemas']['LlmUsage'] | null; pending?: boolean; partial?: boolean }>();
const labels = { generation: 'Генерация ответа', query_rewriting: 'Переформулировка вопроса', reranking: 'Переранжирование' };
function count(value: number | null | undefined): string {
 return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('ru-RU') : 'Нет данных';
}
</script>

<template>
 <section class="panel rag-tokens" aria-label="Токены LLM">
  <h2>Токены LLM</h2>
  <p v-if="pending">Счётчики обновляются после завершения каждого вызова LLM.</p>
  <p v-else-if="partial">Частичные данные до остановки запроса. Расход прерванного вызова может быть неизвестен.</p>
  <p v-if="!usage">Нет данных об использовании токенов.</p>
  <template v-else>
   <p v-if="!usage.calls?.length">{{ pending ? 'Вызовов LLM пока нет.' : 'LLM не вызывалась.' }}</p>
   <table>
    <caption>Входные и выходные токены по данным провайдера</caption>
    <thead><tr><th scope="col">Этап</th><th scope="col">Вход</th><th scope="col">Выход</th></tr></thead>
    <tbody>
     <tr v-for="(call, index) in usage.calls" :key="index"><th scope="row">{{ labels[call.stage || 'generation'] }}</th><td>{{ count(call.input_tokens) }}</td><td>{{ count(call.output_tokens) }}</td></tr>
    </tbody>
    <tfoot><tr><th scope="row">{{ pending || partial ? 'Итого на данный момент' : 'Итого' }}</th><td>{{ count(usage.input_tokens) }}</td><td>{{ count(usage.output_tokens) }}</td></tr></tfoot>
   </table>
   <p>Вход включает системные инструкции и контекст; выход — весь сгенерированный ответ модели. Embedding не учитывается. «Нет данных» означает, что провайдер не вернул счётчик хотя бы одного вызова.</p>
  </template>
 </section>
</template>

<style scoped>
.rag-tokens{padding:20px;margin:20px 0}.rag-tokens h2{margin-top:0;font-size:18px}.rag-tokens p,.rag-tokens caption{font-size:12px;color:#526b7d;line-height:1.6;text-align:left}.rag-tokens table{width:100%;border-collapse:collapse;font-size:13px}.rag-tokens th,.rag-tokens td{padding:9px 4px;border-bottom:1px solid #e3eaf0;text-align:right;font-variant-numeric:tabular-nums}.rag-tokens th:first-child{text-align:left}.rag-tokens tbody th{font-weight:400}
</style>
