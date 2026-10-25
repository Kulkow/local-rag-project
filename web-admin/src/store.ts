import { defineStore } from 'pinia';
import { getReadiness, type Readiness } from './api';
export const useHealth = defineStore('health', {
  state: () => ({data: null as Readiness | null, loading: false, error: '', checked: ''}),
  actions: {async refresh(username: string, password: string) {
    this.loading = true; this.error = ''; this.data = null;
    try {this.data = await getReadiness(username, password); this.checked = new Date().toLocaleTimeString();}
    catch (error) {this.error = error instanceof Error ? error.message : 'Unable to reach API';}
    finally {this.loading = false;}
  }}
});
