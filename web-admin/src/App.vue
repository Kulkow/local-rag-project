<script setup lang="ts">
import { useAuth } from './modules/identity';
const auth = useAuth();
</script>
<template><div class="shell"><aside><div class="brand">◈ RAG Platform</div><p class="eyebrow">OPERATIONS / LOCAL</p><nav aria-label="Main navigation"><RouterLink to="/">◉ Service dashboard</RouterLink><RouterLink to="/families">Семьи</RouterLink><RouterLink to="/documents#upload">Загрузка документов</RouterLink><RouterLink to="/rag">RAG Playground</RouterLink><RouterLink to="/users">Пользователи</RouterLink></nav><p class="roadmap">Документы · RAG<br>Индексация, поиск и ответы с цитатами. Проверяйте источники.</p></aside><main><RouterView :key="auth.token" /></main></div></template>