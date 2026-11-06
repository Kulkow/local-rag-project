import React, {useEffect, useState} from 'react';
import {ScrollView, Text, View} from 'react-native';
import {ApiError} from '../api/client';
import type {Document, Index, Job} from '../api/types';
import {message} from '../auth/session';
import {session} from '../native';
import {Button, Card, Loading, Notice, s} from '../ui';
import {processableMediaTypes} from './upload';

const jobs: Record<string, string> = {queued: 'В очереди', processing: 'Обработка', retry_wait: 'Ожидание повтора', succeeded: 'Обработка завершена', failed: 'Ошибка обработки'};

function DocumentCard({document, revision}: {document: Document; revision: number}): React.JSX.Element {
  const [job, setJob] = useState<Job | null>(null);
  const [index, setIndex] = useState<Index | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setBusy(true); setError(''); setJob(null); setIndex(null);
    const api = session.api();
    void Promise.allSettled([api.job(document.id), api.index(document.id)]).then(([processing, indexing]) => {
      if (!active) {return;}
      if (processing.status === 'fulfilled') {setJob(processing.value);}
      if (indexing.status === 'fulfilled') {setIndex(indexing.value);}
      for (const result of [processing, indexing]) {
        if (result.status === 'rejected' && !(result.reason instanceof ApiError && result.reason.status === 404)) {setError(message(result.reason));}
      }
      setBusy(false);
    });
    return () => {active = false;};
  }, [document.id, revision, attempt]);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState('');
  const state = session.snapshot();
  const mayRetry = document.owner_id === state.user?.id || state.user?.role === 'admin' || state.user?.role === 'manager';
  async function retry(): Promise<void> {
    setRetrying(true); setRetryError('');
    try {await session.api().process(document.id); setAttempt(value => value + 1);}
    catch (reason) {setRetryError(message(reason));}
    finally {setRetrying(false);}
  }
  return <Card>
    <Text style={s.heading}>{document.title || document.filename}</Text>
    {!!document.title && <Text style={s.muted}>{document.filename}</Text>}
    <Text style={s.muted}>{(document.size_bytes / 1024 / 1024).toFixed(2)} MiB · {document.visibility === 'private' ? 'Личный' : 'Для семьи'}</Text>
    <Text style={s.badge}>{index?.status === 'indexed' ? 'Доступен для поиска' : job ? jobs[job.status] ?? job.status : document.status === 'uploaded' ? 'Оригинал сохранён' : document.status}</Text>
    {busy && <Loading text="Проверяем индекс…"/>}
    {index?.status === 'indexed' && <Text style={s.muted}>Фрагментов: {index.chunk_count}</Text>}
    {!!job?.error_code && <Notice text={`Обработка: ${job.error_code}`} error/>}
    <Notice text={error || retryError} error/>
    {mayRetry && processableMediaTypes.includes(document.content_type) && document.status === 'uploaded' && !busy && (!job || job.status === 'failed') && <Button title="Поставить в очередь" disabled={retrying} secondary onPress={() => {void retry();}}/>}
  </Card>;
}

export function DocumentsScreen({family, refresh}: {family: string; refresh: number}): React.JSX.Element {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setBusy(true); setError(''); setDocuments([]);
    void session.api().documents(family, offset).then(value => {if (active) {setDocuments(value);}})
      .catch(reason => {if (active) {setError(message(reason));}})
      .finally(() => {if (active) {setBusy(false);}});
    return () => {active = false;};
  }, [family, offset, revision, refresh]);
  return <ScrollView contentContainerStyle={s.content}>
    <Text style={s.title}>Документы</Text>
    <Text style={s.muted}>Только доступные вам документы выбранной семьи. Готовность RAG подтверждается индексом.</Text>
    <Button title="Обновить состояния" secondary disabled={busy} onPress={() => setRevision(value => value + 1)}/>
    {busy && <Loading/>}
    <Notice text={error} error/>
    {!busy && !error && !documents.length && <Card><Text style={s.text}>На этой странице документов нет.</Text><Text style={s.muted}>Загрузите файл или сфотографируйте документ на вкладке «Загрузить».</Text></Card>}
    {documents.map(document => <DocumentCard key={document.id} document={document} revision={revision + refresh}/>)}
    <View style={s.row}>
      <Button title="Назад" secondary disabled={busy || offset === 0} onPress={() => setOffset(value => Math.max(0, value - 20))}/>
      <Text style={s.muted}>Страница {offset / 20 + 1}</Text>
      <Button title="Далее" secondary disabled={busy || !!error || documents.length < 20} onPress={() => setOffset(value => value + 20)}/>
    </View>
  </ScrollView>;
}
