<script setup lang="ts">
import { ref } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Message from 'primevue/message';
import Tag from 'primevue/tag';
import { useHealth } from './store';
const health = useHealth();
const username = ref(''); const password = ref('');
</script>
<template><header><p class="eyebrow">PLATFORM HEALTH</p><h1>Service dashboard</h1><p>Live dependency checks from the FastAPI service.</p></header><section class="panel"><h2>Administrator access</h2><p>Use the credentials configured in your local environment. Credentials stay in memory.</p><form @submit.prevent="health.refresh(username, password)"><label>Username<InputText v-model="username" autocomplete="username" required /></label><label>Password<InputText v-model="password" type="password" autocomplete="current-password" required /></label><Button type="submit" label="Check services" :loading="health.loading" /></form></section><Message v-if="health.error" severity="error" role="alert">{{ health.error }}</Message><p v-if="health.loading" role="status">Checking dependencies…</p><section v-if="health.data" aria-live="polite"><div class="section-title"><h2>Dependencies</h2><Tag :value="health.data.status" :severity="health.data.status === 'ready' ? 'success' : 'warn'" /></div><div class="cards"><article v-for="(ok, service) in health.data.services" :key="service" class="panel"><h3>{{ service }}</h3><Tag :value="ok ? 'Available' : 'Unavailable'" :severity="ok ? 'success' : 'danger'" /></article></div><p class="muted">Last checked {{ health.checked }} · Model downloads are checked separately.</p></section><section v-else-if="!health.loading" class="empty">Enter administrator credentials and run a check to see current service availability.</section></template>
