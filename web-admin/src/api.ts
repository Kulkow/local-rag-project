import type { components } from './schema';
export type Readiness = components['schemas']['Readiness'];
export async function getReadiness(username: string, password: string): Promise<Readiness> {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  const auth = btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''));
  const response = await fetch('/api/ready', {headers: {Authorization: `Basic ${auth}`}, signal: AbortSignal.timeout(10000)});
  if (response.status === 401) throw new Error('Invalid administrator credentials.');
  if (response.status !== 200 && response.status !== 503) throw new Error(`API returned ${response.status}`);
  return response.json();
}
