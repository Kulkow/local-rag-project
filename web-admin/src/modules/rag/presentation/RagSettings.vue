<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import Button from 'primevue/button';
import Message from 'primevue/message';
import { SessionAccess, useAuth } from '../../identity';
import { ApiError } from '../../../shared/infrastructure/http';
import { getPromptSettings, savePromptSettings, type PromptSettings } from '../infrastructure/settings-api';

const auth = useAuth();
const admin = computed(() => auth.user?.role === 'admin');
const settings = ref<PromptSettings | null>(null);
const draft = ref('');
const busy = ref(false);
const error = ref('');
const saved = ref(false);
let sequence = 0;
const valid = computed(() => !!draft.value.trim() && draft.value.length <= 8000 && !draft.value.includes('\0'));
const changed = computed(() => draft.value !== settings.value?.system_prompt);

async function load() {
 if (!admin.value || busy.value) return;
 const current = ++sequence;
 busy.value = true; error.value = ''; saved.value = false;
 try {
  const value = await getPromptSettings(auth.token);
  if (current === sequence) { settings.value = value; draft.value = value.system_prompt; }
 } catch (e) {
  if (current === sequence) error.value = e instanceof Error ? e.message : 'Не удалось загрузить настройки.';
 } finally {
  if (current === sequence) busy.value = false;
 }
}

async function save() {
 if (!admin.value || busy.value || !settings.value || !valid.value || !changed.value) return;
 const current = ++sequence;
 busy.value = true; error.value = ''; saved.value = false;
 try {
  const value = await savePromptSettings(auth.token, {system_prompt: draft.value, version: settings.value.version});
  if (current === sequence) { settings.value = value; draft.value = value.system_prompt; saved.value = true; }
 } catch (e) {
  if (current === sequence) error.value = e instanceof ApiError && e.status === 409
   ? 'Настройки изменил другой администратор. Скопируйте свои правки и перезагрузите настройки.'
   : e instanceof Error ? e.message : 'Не удалось сохранить настройки.';
 } finally {
  if (current === sequence) busy.value = false;
 }
}

watch([() => auth.token, admin], () => {
 sequence++; settings.value = null; draft.value = ''; busy.value = false; error.value = ''; saved.value = false;
 if (auth.token && admin.value) void load();
}, { immediate: true });
watch(draft, () => { saved.value = false; });
onBeforeUnmount(() => { sequence++; });
</script>

<template>
 <div class="settings-page">
  <h1>Настройки RAG</h1>
  <SessionAccess />
  <Message v-if="auth.user && !admin" severity="warn">Настройки доступны только администратору.</Message>
  <section v-if="admin" class="panel prompt-settings" :aria-busy="busy">
   <h2>Системный промпт</h2>
   <p>Инструкции модели при генерации ответов по документам. Настройка общая для всех пользователей и семей. Сохранённый текст применяется к новым вызовам без перезапуска.</p>
   <Message v-if="error" severity="error" role="alert">{{ error }}</Message>
   <Message v-if="saved" severity="success" role="status">Промпт сохранён.</Message>
   <p v-if="busy" role="status">{{ settings ? 'Сохранение или обновление…' : 'Загрузка настроек…' }}</p>
   <form v-if="settings" @submit.prevent="save">
    <label for="system-prompt">Промпт генерации ответа</label>
    <textarea id="system-prompt" v-model="draft" rows="16" maxlength="8000" required :disabled="busy" aria-describedby="prompt-help" />
    <small id="prompt-help">{{ draft.length }} / 8000 символов. Сохраните требования к JSON: answer, citations, insufficient_evidence и ссылки [1], [2]. Источники передаются отдельно; проверки доступа и цитат выполняет сервер.</small>
    <p v-if="!valid" role="alert">Введите непустой текст до 8000 символов без NUL.</p>
    <div class="actions">
     <Button type="submit" label="Сохранить" :disabled="busy || !valid || !changed" />
     <Button type="button" label="Вернуть стандартный текст" severity="secondary" :disabled="busy" @click="draft = settings.default_system_prompt || ''" />
    </div>
    <p class="hint">Стандартный текст сначала подставляется в форму. Для применения нажмите «Сохранить». Промпты переформулировки и переранжирования здесь не меняются.</p>
   </form>
   <Button type="button" label="Перезагрузить настройки" severity="secondary" :disabled="busy" @click="load" />
  </section>
 </div>
</template>

<style scoped>
.settings-page{max-width:960px}.prompt-settings{padding:24px}.prompt-settings p,.prompt-settings small{line-height:1.6;color:#526b7d}.prompt-settings h2{margin-top:0}.prompt-settings label{display:block;margin:20px 0 8px;font-weight:600}.prompt-settings textarea{width:100%;box-sizing:border-box;resize:vertical;font:14px/1.6 monospace;padding:12px;border:1px solid #a9bcc9;border-radius:8px}.prompt-settings textarea:focus{outline:2px solid #16736a;outline-offset:2px}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px}.hint{font-size:13px}
</style>
