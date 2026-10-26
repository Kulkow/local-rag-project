<script setup lang="ts">
import { ref } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Message from 'primevue/message';
import { useAuth } from '../stores/auth';
const auth = useAuth();
const username = ref(''); const password = ref(''); const busy = ref(false); const error = ref('');
async function signIn() { busy.value = true; error.value = ''; try { await auth.signIn(username.value, password.value); } catch (e) { error.value = e instanceof Error ? e.message : 'Ошибка входа'; } finally { busy.value = false; password.value = ''; } }
async function signOut() { busy.value = true; error.value = ''; try { await auth.signOut(); } catch { error.value = 'Не удалось отозвать токены на сервере. Локальный токен удалён.'; } finally { busy.value = false; } }
</script>
<template>
<section class="panel">
 <p v-if="auth.restoring" role="status">Проверяется сохранённый JWT…</p>
 <template v-else-if="auth.user"><div class="section-title"><strong>{{ auth.user.username }}</strong><span>{{ auth.user.role }}</span><Button label="Выйти" severity="secondary" :loading="busy" @click="signOut" /></div><p>JWT хранится в Pinia и localStorage, действует до 8 часов. Выход отзывает все ваши токены.</p></template>
 <template v-else><h2>Вход в управление семьями</h2><p>Используйте учётную запись БД. Первый администратор создаётся командой make bootstrap-admin.</p><form @submit.prevent="signIn"><label>Логин<InputText v-model="username" autocomplete="username" required maxlength="100" /></label><label>Пароль<InputText v-model="password" type="password" autocomplete="current-password" required maxlength="128" /></label><Button label="Войти" type="submit" :loading="busy" /></form></template>
 <Message v-if="auth.persistenceWarning" severity="warn">{{ auth.persistenceWarning }}</Message>
 <Message v-if="auth.restoreError" severity="warn">{{ auth.restoreError }} <Button label="Повторить проверку" text :disabled="auth.restoring" @click="auth.restore()" /></Message>
 <Message v-if="error" severity="error" role="alert">{{ error }}</Message>
</section>
</template>
