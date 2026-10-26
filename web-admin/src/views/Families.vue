<script setup lang="ts">
import { ref, watch } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Message from 'primevue/message';
import Dialog from 'primevue/dialog';
import SessionAccess from '../components/SessionAccess.vue';
import { useAuth } from '../stores/auth';
import * as api from '../management-api';
const auth = useAuth();
const families = ref<api.Family[]>([]); const members = ref<api.Member[]>([]); const selected = ref<api.Family | null>(null);
const offset = ref(0); const memberOffset = ref(0); const name = ref(''); const rename = ref(''); const firstName = ref(''); const lastName = ref(''); const role = ref('member');
const busy = ref(false); const error = ref(''); const notice = ref(''); const pending = ref<null | { kind: 'family' | 'member'; id: string; label: string }>(null);
async function run(action: () => Promise<void>) { if (busy.value) return; busy.value = true; error.value = ''; notice.value = ''; try { await action(); } catch (e) { error.value = e instanceof Error ? e.message : 'Ошибка запроса'; } finally { busy.value = false; } }
async function load() { families.value = await api.listFamilies(auth.token, offset.value); }
async function loadMembers() { if (selected.value) members.value = await api.listMembers(auth.token, selected.value.id, memberOffset.value); }
async function select(family: api.Family) { await run(async () => { selected.value = family; rename.value = family.name; memberOffset.value = 0; members.value = []; await loadMembers(); }); }
async function create() { await run(async () => { const family = await api.createFamily(auth.token, name.value); name.value = ''; offset.value = 0; await load(); selected.value = family; rename.value = family.name; memberOffset.value = 0; await loadMembers(); notice.value = 'Семья создана'; }); }
async function saveName() { await run(async () => { if (!selected.value) return; selected.value = await api.renameFamily(auth.token, selected.value.id, rename.value); await load(); notice.value = 'Название сохранено'; }); }
async function add() { await run(async () => { if (!selected.value) return; await api.addMember(auth.token, selected.value.id, { first_name: firstName.value, last_name: lastName.value, role: role.value }); firstName.value = ''; lastName.value = ''; memberOffset.value = 0; await loadMembers(); notice.value = 'Участник добавлен'; }); }
async function saveRole(member: api.Member) { await run(async () => { if (!selected.value) return; await api.changeMember(auth.token, selected.value.id, member.id, member.role); await loadMembers(); notice.value = 'Роль в семье сохранена'; }); }
async function confirmDelete() { const target = pending.value; if (!target) return; await run(async () => { if (target.kind === 'family') { await api.deleteFamily(auth.token, target.id); selected.value = null; members.value = []; await load(); } else if (selected.value) { await api.removeMember(auth.token, selected.value.id, target.id); await loadMembers(); } pending.value = null; notice.value = 'Удалено'; }); }
function page(delta: number) { void run(async () => { offset.value = Math.max(0, offset.value + delta * 20); await load(); }); }
function memberPage(delta: number) { void run(async () => { memberOffset.value = Math.max(0, memberOffset.value + delta * 20); await loadMembers(); }); }
watch(() => auth.token, token => { selected.value = null; families.value = []; members.value = []; error.value = ''; notice.value = ''; offset.value = 0; pending.value = null; if (token) void run(load); }, { immediate: true });
</script>
<template>
<header><p class="eyebrow">СЕМЬИ И УЧАСТНИКИ</p><h1>Управление семьёй</h1><p>Состав семьи и роли участников. Права входа задаются отдельно на странице пользователей.</p></header>
<SessionAccess />
<template v-if="auth.user">
 <Message v-if="error" severity="error" role="alert">{{ error }}</Message><Message v-if="notice" severity="success" role="status">{{ notice }}</Message><p v-if="busy" role="status">Выполняется запрос…</p>
 <section v-if="auth.isAdmin" class="panel"><h2>Создать семью</h2><form @submit.prevent="create"><label>Название<InputText v-model="name" required maxlength="255" /></label><Button label="Создать семью" type="submit" :disabled="busy" /></form></section>
 <div class="management-grid"><section class="panel"><div class="section-title"><h2>Доступные семьи</h2><Button label="Обновить" severity="secondary" :disabled="busy" @click="run(load)" /></div><p v-if="!families.length && !busy">На этой странице нет доступных семей.</p><ul class="record-list"><li v-for="family in families" :key="family.id"><Button :label="family.name" :severity="selected?.id === family.id ? 'primary' : 'secondary'" :disabled="busy" @click="select(family)" /></li></ul><div class="pager"><Button label="Назад" :disabled="busy || !offset" @click="page(-1)" /><span>{{ offset + 1 }}–{{ offset + families.length }}</span><Button label="Далее" :disabled="busy || families.length < 20" @click="page(1)" /></div></section>
 <section v-if="selected" class="panel"><h2>{{ selected.name }}</h2><form v-if="auth.canManage" @submit.prevent="saveName"><label>Название семьи<InputText v-model="rename" required maxlength="255" /></label><Button label="Сохранить название" type="submit" :disabled="busy" /></form><Button v-if="auth.isAdmin" label="Удалить семью" severity="danger" outlined :disabled="busy" @click="pending = { kind: 'family', id: selected.id, label: selected.name }" />
 <h3 class="subheading">Участники</h3><p v-if="!members.length && !busy">Участников пока нет.</p><ul class="record-list"><li v-for="member in members" :key="member.id" class="member-record"><strong>{{ member.first_name }} {{ member.last_name }}</strong><small>ID участника: {{ member.id }}</small><form v-if="auth.canManage" @submit.prevent="saveRole(member)"><label>Роль в семье<InputText v-model="member.role" required maxlength="50" /></label><Button label="Сохранить роль" type="submit" :disabled="busy" /><Button label="Удалить участника" severity="danger" outlined :disabled="busy" @click="pending = { kind: 'member', id: member.id, label: `${member.first_name} ${member.last_name}` }" /></form><p v-else>{{ member.role }}</p></li></ul>
 <div class="pager"><Button label="Назад" :disabled="busy || !memberOffset" @click="memberPage(-1)" /><Button label="Далее" :disabled="busy || members.length < 20" @click="memberPage(1)" /></div>
 <template v-if="auth.canManage"><h3 class="subheading">Добавить участника</h3><form @submit.prevent="add"><label>Имя<InputText v-model="firstName" required maxlength="100" /></label><label>Фамилия<InputText v-model="lastName" required maxlength="100" /></label><label>Роль в семье<InputText v-model="role" required maxlength="50" /></label><Button label="Добавить участника" type="submit" :disabled="busy" /></form></template></section><section v-else class="empty">Выберите семью для просмотра состава.</section></div>
</template>
<Dialog :visible="!!pending" modal header="Подтвердите удаление" :closable="!busy" @update:visible="value => { if (!value) pending = null; }"><p>Удалить «{{ pending?.label }}»?</p><p>Люди сохраняются. Связанные пользователи или животные могут блокировать удаление.</p><Button label="Отмена" severity="secondary" :disabled="busy" @click="pending = null" /><Button label="Удалить" severity="danger" :loading="busy" @click="confirmDelete" /><Message v-if="error" severity="error" role="alert">{{ error }}</Message></Dialog>
</template>
