<script setup lang="ts">
import { watch } from 'vue';
import Button from 'primevue/button';
import Message from 'primevue/message';
import Tag from 'primevue/tag';
import { SessionAccess } from '../../identity';
import { useAuth } from '../../identity';
import { useHealth } from './health-store';
const health = useHealth(); const auth = useAuth();
watch(() => auth.token, () => { health.data = null; health.error = ''; });
</script>
<template>
<header><p class="eyebrow">PLATFORM HEALTH</p><h1>Service dashboard</h1><p>Live dependency checks from the FastAPI service.</p></header><SessionAccess />
<template v-if="auth.isAdmin"><Button label="Проверить сервисы" :loading="health.loading" @click="health.refresh(auth.token)" /><Message v-if="health.error" severity="error" role="alert">{{ health.error }}</Message><p v-if="health.loading" role="status">Checking dependencies…</p><section v-if="health.data" aria-live="polite"><div class="section-title"><h2>Dependencies</h2><Tag :value="health.data.status" :severity="health.data.status === 'ready' ? 'success' : 'warn'" /></div><div class="cards"><article v-for="(ok, service) in health.data.services" :key="service" class="panel"><h3>{{ service }}</h3><Tag :value="ok ? 'Available' : 'Unavailable'" :severity="ok ? 'success' : 'danger'" /></article></div><p class="muted">Last checked {{ health.checked }} · Model downloads are checked separately.</p></section></template><p v-else-if="auth.user" class="empty">Мониторинг сервисов доступен администратору. Перейдите на страницу «Семьи».</p>
</template>
