// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import PrimeVue from 'primevue/config';
import { mount, flushPromises } from '@vue/test-utils';
import RagSettings from '../src/modules/rag/presentation/RagSettings.vue';
import { useAuth } from '../src/modules/identity/presentation/auth-store';
import { getPromptSettings, savePromptSettings } from '../src/modules/rag/infrastructure/settings-api';
import { ApiError } from '../src/shared/infrastructure/http';
vi.mock('../src/modules/rag/infrastructure/settings-api', () => ({getPromptSettings: vi.fn(), savePromptSettings: vi.fn()}));
let wrapper: ReturnType<typeof mount> | undefined;
const initial = {system_prompt: 'Custom prompt', default_system_prompt: 'Standard prompt', version: 1, updated_at: null};
beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); setActivePinia(createPinia()); vi.mocked(getPromptSettings).mockResolvedValue(initial); });
afterEach(() => { wrapper?.unmount(); });
function page(role: 'admin' | 'manager' | 'member' | null = 'admin') {
 if (role) { const auth = useAuth(); auth.token = 'jwt'; auth.user = {id:'user', username:'synthetic',role,family_member_id:null,is_active:true}; }
 wrapper = mount(RagSettings, {global:{plugins:[PrimeVue]}}); return wrapper;
}
it.each(['member', 'manager', null] as const)('does not request settings for %s', async role => {
 const view = page(role); await flushPromises();
 expect(getPromptSettings).not.toHaveBeenCalled(); expect(view.find('textarea').exists()).toBe(false);
});
it('loads and saves the exact prompt with its version, and stages defaults without saving', async () => {
 const view = page(); await flushPromises();
 expect(getPromptSettings).toHaveBeenCalledWith('jwt');
 expect((view.find('textarea').element as HTMLTextAreaElement).value).toBe('Custom prompt');
 const value = 'Новый {literal} prompt\n<script>text</script>';
 vi.mocked(savePromptSettings).mockResolvedValue({...initial, system_prompt:value,version:2});
 await view.find('textarea').setValue(value); await view.find('form').trigger('submit'); await flushPromises();
 expect(savePromptSettings).toHaveBeenCalledWith('jwt', {system_prompt:value,version:1});
 expect(view.text()).toContain('Промпт сохранён'); expect(view.find('script').exists()).toBe(false);
 await view.findAll('button').find(button => button.text() === 'Вернуть стандартный текст')!.trigger('click');
 expect((view.find('textarea').element as HTMLTextAreaElement).value).toBe('Standard prompt');
 expect(savePromptSettings).toHaveBeenCalledTimes(1);
 vi.mocked(savePromptSettings).mockResolvedValue({...initial,system_prompt:'Standard prompt',version:3});
 await view.find('form').trigger('submit'); await flushPromises();
 expect(savePromptSettings).toHaveBeenLastCalledWith('jwt', {system_prompt:'Standard prompt',version:2});
});
it('handles loading failures, blank input and conflicting edits without losing the draft', async () => {
 vi.mocked(getPromptSettings).mockRejectedValueOnce(new Error('Unavailable'));
 const view = page(); await flushPromises();
 expect(view.find('[role="alert"]').text()).toContain('Unavailable');
 await view.findAll('button').find(button => button.text() === 'Перезагрузить настройки')!.trigger('click'); await flushPromises();
 await view.find('textarea').setValue(' \n'); await view.find('form').trigger('submit');
 expect(savePromptSettings).not.toHaveBeenCalled();
 vi.mocked(savePromptSettings).mockRejectedValue(new ApiError(409, 'Conflict'));
 await view.find('textarea').setValue('My changes'); await view.find('form').trigger('submit'); await flushPromises();
 expect(view.find('[role="alert"]').text()).toContain('другой администратор');
 expect((view.find('textarea').element as HTMLTextAreaElement).value).toBe('My changes');
});
it('ignores late responses after the session changes', async () => {
 let resolve!: (value: typeof initial) => void;
 vi.mocked(getPromptSettings).mockReturnValue(new Promise(done => {resolve = done;}));
 const view = page(); await flushPromises(); expect(view.text()).toContain('Загрузка настроек');
 useAuth().token = ''; useAuth().user = null; await flushPromises();
 resolve(initial); await flushPromises(); expect(view.find('textarea').exists()).toBe(false);
});
