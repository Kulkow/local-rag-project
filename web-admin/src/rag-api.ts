import type { components } from './schema';
import { readResponse } from './management-api';

export type RagInput = components['schemas']['QuestionInput'];
export type RagAnswer = components['schemas']['AnswerView'];

export async function queryRag(token: string, body: RagInput, generate = true): Promise<RagAnswer> {
 const response = await fetch(`/api/rag/${generate ? 'ask' : 'search'}`, {
  method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify(body), signal: AbortSignal.timeout(85000),
 });
 return readResponse<RagAnswer>(response, token);
}
