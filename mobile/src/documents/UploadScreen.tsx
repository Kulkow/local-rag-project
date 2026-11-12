import React, {useEffect, useRef, useState} from 'react';
import {Image, ScrollView, Text, TextInput, View} from 'react-native';
import type {Visibility} from '../api/types';
import {message} from '../auth/session';
import {chooseFile, discard, session, takePhoto} from '../native';
import {Button, Card, Loading, Notice, s} from '../ui';
import {sendDraft, type UploadDraft} from './upload';

export function UploadScreen({family, onSaved}: {family: string; onSaved: () => void}): React.JSX.Element {
  const [draft, setDraft] = useState<UploadDraft | null>(null);
  const current = useRef<UploadDraft | null>(null);
  const pending = useRef<UploadDraft[]>([]);
  const [photos, setPhotos] = useState<UploadDraft[]>([]);
  const alive = useRef(true);
  const [visibility, setVisibility] = useState<Visibility>('private');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    alive.current = true;
    return () => {alive.current = false; void Promise.all([current.current, ...pending.current].map(item => discard(item?.file ?? null))).catch(() => undefined);};
  }, []);

  async function select(camera: boolean): Promise<void> {
    setBusy(true); setError(''); setNotice('');
    try {
      const file = await (camera ? takePhoto() : chooseFile());
      if (!alive.current) {await discard(file); return;}
      if (file) {
        if (camera && current.current) {
          pending.current = [...pending.current, current.current];
          setPhotos(pending.current);
        } else {
          await discard(current.current?.file ?? null);
        }
        current.current = {file, family, visibility};
        setDraft(current.current);
      }
    } catch (reason) {if (alive.current) {setError(message(reason));}}
    finally {if (alive.current) {setBusy(false);}}
  }
  async function send(): Promise<void> {
    if (!draft) {return;}
    setBusy(true); setError(''); setNotice('');
    try {
      const batch = [...pending.current, draft];
      let result = '';
      for (const item of batch) {
        result = await sendDraft(session.api(), item, () => alive.current);
        if (!alive.current) {return;}
        // Remove acknowledged items immediately so a partial failure cannot resend them.
        if (item === current.current) {current.current = null; setDraft(null);}
        pending.current = pending.current.filter(photo => photo !== item);
        setPhotos([...pending.current]);
        onSaved();
        await discard(item.file);
      }
      setNotice(result);
    } catch (reason) {if (alive.current) {setError(`${(pending.current[0] ?? current.current)?.saved ? 'Оригинал уже сохранён. Повторится только постановка в очередь. ' : ''}${message(reason)}`);}}
    finally {if (alive.current) {setBusy(false);}}
  }
  async function reset(): Promise<void> {
    setBusy(true);
    try {await Promise.all([current.current, ...pending.current].map(item => discard(item?.file ?? null))); pending.current = []; setPhotos([]); current.current = null; setDraft(null); setError('');}
    catch (reason) {setError(message(reason));}
    finally {setBusy(false);}
  }
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.content}>
    <Text style={s.title}>Загрузить в RAG</Text>
    <Text style={s.muted}>Документы попадут в ту же базу знаний, что и файлы из админки.</Text>
    <Card>
      <Text style={s.heading}>Доступ к документу</Text>
      <View style={s.row}>
        <Button title={visibility === 'private' ? '✓ Личный' : 'Личный'} secondary={visibility !== 'private'} disabled={busy || !!draft} onPress={() => setVisibility('private')}/>
        <Button title={visibility === 'family' ? '✓ Для семьи' : 'Для семьи'} secondary={visibility !== 'family'} disabled={busy || !!draft} onPress={() => setVisibility('family')}/>
      </View>
      <Text style={s.muted}>{visibility === 'private' ? 'Владелец и администратор.' : 'Участники выбранной семьи и администратор.'} После выбора файла доступ фиксируется для повторов.</Text>
    </Card>
    <Card>
      <Text style={s.heading}>Файл или снимок</Text>
      <Text style={s.text}>PDF, DOCX, HTML, PNG, JPEG · до 10 MiB</Text>
      <Button title="Выбрать файл" secondary disabled={busy || photos.length > 0} onPress={() => {void select(false);}}/>
      <Button title="Сфотографировать документ" secondary disabled={busy || photos.length >= 19} onPress={() => {void select(true);}}/>
      <Text style={s.muted}>Можно сделать до 20 снимков подряд: каждый добавится к отправке со своим описанием. После отправки оставайтесь здесь и продолжайте съёмку.</Text>
      <Text style={s.muted}>Снимок отправляется как JPEG/PNG для распознавания текста сервером. Приложение не добавляет его в галерею; временные файлы удаляются после отправки или отмены.</Text>
      {photos.map((photo, index) => <View key={photo.file.key} style={{gap: 10}}>
        <Text style={s.text}>Снимок {index + 1}: {photo.file.name}</Text>
        <Image source={{uri: photo.file.uri}} resizeMode="contain" style={s.imagePreview} accessibilityLabel={`Снимок ${index + 1}`}/>
        <TextInput accessibilityLabel={`Описание снимка ${index + 1}`} placeholder="Комментарий к снимку" multiline maxLength={2000} style={s.input} value={photo.description ?? ''} editable={!busy && !photo.attempted} onChangeText={value => {photo.description = value; setPhotos([...pending.current]);}}/>
      </View>)}
      {draft && <View style={{gap: 10}}>
        {draft.file.type.startsWith('image/') && <Image source={{uri: draft.file.uri}} resizeMode="contain" style={s.imagePreview} accessibilityLabel="Выбранное изображение документа"/>}
        <Text style={s.text}>{draft.file.name}</Text>
        <Text style={s.muted}>{(draft.file.size / 1024 / 1024).toFixed(2)} MiB · {draft.visibility === 'private' ? 'Личный' : 'Для семьи'}</Text>
        <Text style={s.label}>Описание файла или фото (необязательно)</Text>
        <TextInput accessibilityLabel="Описание файла или фото" placeholder="Что изображено или что содержит файл" multiline maxLength={2000} style={s.input} value={draft.description ?? ''} editable={!busy && !draft.attempted} onChangeText={value => {draft.description = value; current.current = {...draft}; setDraft(current.current);}}/>
        <Text style={s.muted}>До 2000 символов. После попытки отправки описание фиксируется для безопасного повтора.</Text>
        <Text style={s.text}>К отправке: {photos.length + 1}</Text>
        <Button title={(pending.current[0] ?? draft).saved ? 'Повторить постановку в очередь' : 'Отправить в обработку'} disabled={busy} onPress={() => {void send();}}/>
        <Button title="Отменить выбор" secondary disabled={busy} onPress={() => {void reset();}}/>
      </View>}
      {busy && <Loading text="Подготовка или отправка…"/>}
      <Notice text={error} error/>
      <Notice text={notice}/>
    </Card>
    <Text style={s.muted}>PDF и PNG/JPEG индексируются в фоне. Снимки распознаются на русском и английском. DOCX/HTML сохраняются без автоматической индексации. Качество OCR зависит от освещения и читаемости снимка.</Text>
  </ScrollView>;
}
