import type { components } from '../../../shared/infrastructure/schema';
import { request } from '../../../shared/infrastructure/http';

export type PromptSettings = components['schemas']['PromptSettingsView'];
export type UpdatePrompt = components['schemas']['UpdatePromptInput'];

export function getPromptSettings(token: string): Promise<PromptSettings> {
 return request('/settings/rag', token);
}

export function savePromptSettings(token: string, body: UpdatePrompt): Promise<PromptSettings> {
 return request('/settings/rag', token, 'PUT', body);
}
