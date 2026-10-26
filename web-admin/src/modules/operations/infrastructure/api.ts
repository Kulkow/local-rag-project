import type { components } from '../../../shared/infrastructure/schema';
import { request } from '../../../shared/infrastructure/http';

export const sessionReadiness = (token: string) => request<components['schemas']['Readiness']>('/ready', token, 'GET', undefined, [503]);
