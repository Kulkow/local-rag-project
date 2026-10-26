import { defineStore } from 'pinia';
import type { Readiness } from './api';
import { sessionReadiness } from './management-api';
export const useHealth = defineStore('health', {
  state: () => ({data: null as Readiness | null, loading: false, error: '', checked: ''}),
  actions: {async refresh(token: string) {
    this.loading = true; this.error = ''; this.data = null;
    try {this.data = await sessionReadiness(token); this.checked = new Date().toLocaleTimeString();}
    catch (error) {this.error = error instanceof Error ? error.message : 'Unable to reach API';}
    finally {this.loading = false;}
  }}
});
