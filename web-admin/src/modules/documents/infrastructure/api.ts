import type { components } from '../../../shared/infrastructure/schema';
import { readResponse, request } from '../../../shared/infrastructure/http';
import type { Document, Visibility } from '../domain/document';
export type { Document, Visibility } from '../domain/document';

export function listDocuments(token: string, familyId: string, offset = 0): Promise<Document[]> {
  return request(`/documents?family_id=${encodeURIComponent(familyId)}&offset=${offset}&limit=20`, token);
}

export async function uploadDocument(token: string, file: File, familyId: string, visibility: Visibility, key: string): Promise<Document> {
  const parameters = new URLSearchParams({ family_id: familyId, filename: file.name, visibility });
  const response = await fetch(`/api/documents?${parameters}`, {
    method: 'POST', body: file,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': file.type || 'application/octet-stream', 'Idempotency-Key': key },
    signal: AbortSignal.timeout(90000),
  });
  return readResponse<components['schemas']['DocumentView']>(response, token);
}

export type Extraction = components['schemas']['ExtractionView'];
export type ExtractedPages = components['schemas']['ExtractedPagesView'];
export function extractionFormats(token: string): Promise<string[]> {
 return request('/documents/extraction-formats', token);
}
export async function extractDocument(token: string, id: string): Promise<Extraction> {
 const response = await fetch(`/api/documents/${encodeURIComponent(id)}/extract`, {
  method: 'POST', headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(150000),
 });
 return readResponse<Extraction>(response, token);
}
export function readPages(token: string, id: string, offset = 0): Promise<ExtractedPages> {
 return request(`/documents/${encodeURIComponent(id)}/pages?offset=${offset}&limit=5`, token);
}

export type ProcessingJob = components['schemas']['ProcessingJobView'];
export async function enqueueDocument(token: string, id: string): Promise<ProcessingJob> {
 const response = await fetch(`/api/documents/${encodeURIComponent(id)}/process`, {
  method: 'POST', headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(15000),
 });
 return readResponse<ProcessingJob>(response, token);
}
export function processingStatus(token: string, id: string): Promise<ProcessingJob> {
 return request(`/documents/${encodeURIComponent(id)}/processing`, token);
}

export type DocumentIndex = components['schemas']['DocumentIndexView'];
export function indexStatus(token: string, id: string): Promise<DocumentIndex> {
 return request(`/documents/${encodeURIComponent(id)}/index`, token);
}
export async function reindexDocument(token: string, id: string): Promise<ProcessingJob> {
 const response = await fetch(`/api/documents/${encodeURIComponent(id)}/reindex`, {
  method: 'POST', headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(15000),
 });
 return readResponse<ProcessingJob>(response, token);
}

export async function downloadDocument(token: string, id: string, filename: string): Promise<void> {
 const response = await fetch(`/api/documents/${encodeURIComponent(id)}/download`, {
  headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(90000), cache: 'no-store',
 });
 if (!response.ok) { await readResponse<never>(response, token); return; }
 const blob = await response.blob();
 const url = URL.createObjectURL(blob);
 const link = document.createElement('a'); link.href = url; link.download = filename;
 document.body.appendChild(link);
 try { link.click(); } finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
}

export async function previewPdf(token: string, id: string): Promise<void> {
 // Open synchronously from the click, before fetch, so popup blockers allow the tab.
 const tab = window.open('about:blank', '_blank');
 if (!tab) throw new Error('Браузер заблокировал вкладку. Разрешите открытие вкладок для этого сайта.');
 tab.opener = null;
 let url: string | undefined;
 try {
  const response = await fetch(`/api/documents/${encodeURIComponent(id)}/download`, {
   headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(90000), cache: 'no-store',
  });
  if (!response.ok) { await readResponse<never>(response, token); return; }
  const content = await response.blob();
  if (tab.closed) return;
  // The download endpoint deliberately returns octet-stream; use PDF for browser viewing.
  url = URL.createObjectURL(new Blob([content], { type: 'application/pdf' }));
  tab.location.replace(url);
  const previewUrl = url;
  const cleanup = window.setInterval(() => {
   if (tab.closed) { URL.revokeObjectURL(previewUrl); window.clearInterval(cleanup); }
  }, 1000);
 } catch (error) {
  if (url) URL.revokeObjectURL(url);
  tab.close();
  throw error;
 }
}
