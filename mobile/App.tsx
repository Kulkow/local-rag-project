import React, {useEffect, useState, useSyncExternalStore} from 'react';
import {Alert, AppState, Modal, ScrollView, StatusBar, Text, View} from 'react-native';
import {SafeAreaProvider, SafeAreaView} from 'react-native-safe-area-context';
import type {Family} from './src/api/types';
import {message} from './src/auth/session';
import {DocumentsScreen} from './src/documents/DocumentsScreen';
import {UploadScreen} from './src/documents/UploadScreen';
import {LoginScreen} from './src/LoginScreen';
import {clearPhotos, session} from './src/native';
import {Button, Card, colors, Loading, Notice, s} from './src/ui';

function Workspace(): React.JSX.Element {
  const [families, setFamilies] = useState<Family[]>([]);
  const [selected, setSelected] = useState<Family | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(0);
  const [more, setMore] = useState(false);
  const [retry, setRetry] = useState(0);
  const [choosing, setChoosing] = useState(false);
  const [tab, setTab] = useState<'documents' | 'upload'>('documents');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    void session.api().families(page * 50).then(result => {
      if (!active) {return;}
      setFamilies(current => page === 0 ? result : [...current, ...result]);
      setMore(result.length === 50);
      if (page === 0) {setSelected(current => current ?? result[0] ?? null);}
    }).catch(reason => {if (active) {setError(message(reason));}})
      .finally(() => {if (active) {setLoading(false);}});
    return () => {active = false;};
  }, [page, retry]);

  function choose(family: Family): void {
    setChoosing(false);
    if (selected?.id === family.id) {return;}
    Alert.alert('Сменить семью?', 'Неотправленный файл будет удалён из временного хранилища приложения.', [
      {text: 'Отмена', style: 'cancel'},
      {text: 'Сменить', onPress: () => {setSelected(family); setTab('documents');}},
    ]);
  }
  const user = session.snapshot().user;
  return <View style={s.root}>
    <View style={[s.card, {margin: 16, marginBottom: 0, padding: 14}]}>
      <View style={s.row}><Text style={s.text}>{user?.username}</Text><Text style={s.badge}>{user?.role}</Text></View>
      <Button title={selected ? `Семья: ${selected.name} ▾` : 'Выбрать семью'} secondary onPress={() => setChoosing(true)}/>
      <Button title="Выйти" secondary onPress={() => Alert.alert('Выйти из аккаунта?', 'Сервер отзывает все JWT этого пользователя, включая вход в Web Admin. Неотправленные файлы будут удалены.', [{text: 'Отмена', style: 'cancel'}, {text: 'Выйти', onPress: () => {void session.logout();}}])}/>
    </View>
    {!selected ? <ScrollView contentContainerStyle={s.content}>
      {loading && <Loading text="Загружаем доступные семьи…"/>}
      <Notice text={error} error/>
      {!loading && !error && <Card><Text style={s.heading}>Нет доступной семьи</Text><Text style={s.text}>Попросите администратора связать вашу учётную запись с участником семьи. После этого войдите снова.</Text></Card>}
      <Button title="Повторить" secondary disabled={loading} onPress={() => setRetry(value => value + 1)}/>
    </ScrollView> : <View style={s.root} key={selected.id}>
      <View style={[s.row, {paddingHorizontal: 20, paddingTop: 16}]}>
        <Button title="Документы" secondary={tab !== 'documents'} onPress={() => setTab('documents')}/>
        <Button title="Загрузить" secondary={tab !== 'upload'} onPress={() => setTab('upload')}/>
      </View>
      <View style={[s.root, {display: tab === 'documents' ? 'flex' : 'none'}]}><DocumentsScreen family={selected.id} refresh={refresh}/></View>
      <View style={[s.root, {display: tab === 'upload' ? 'flex' : 'none'}]}><UploadScreen family={selected.id} onSaved={() => setRefresh(value => value + 1)}/></View>
    </View>}
    <Modal visible={choosing} animationType="slide" onRequestClose={() => setChoosing(false)}>
      <SafeAreaView style={s.root}><ScrollView contentContainerStyle={s.content}>
        <Text style={s.title}>Доступные семьи</Text>
        {families.map(family => <Button key={family.id} title={`${selected?.id === family.id ? '✓ ' : ''}${family.name}`} secondary onPress={() => choose(family)}/>)}
        {loading && <Loading/>}<Notice text={error} error/>
        {!!error && <Button title="Повторить запрос" disabled={loading} onPress={() => setRetry(value => value + 1)}/>}
        {more && !error && <Button title="Загрузить ещё" secondary disabled={loading} onPress={() => setPage(value => value + 1)}/>}
        <Button title="Закрыть" secondary onPress={() => setChoosing(false)}/>
      </ScrollView></SafeAreaView>
    </Modal>
  </View>;
}

function Application(): React.JSX.Element {
  const state = useSyncExternalStore(session.subscribe, session.snapshot);
  useEffect(() => {
    void clearPhotos().catch(() => undefined);
    void session.restore();
    let previous = AppState.currentState;
    const subscription = AppState.addEventListener('change', next => {
      // Camera/picker temporarily backgrounds the app; preserve the pending upload.
      if (next === 'active' && previous !== 'active' && session.snapshot().status === 'authenticated') {
        void session.api().me().catch(() => undefined);
      }
      previous = next;
    });
    return () => subscription.remove();
  }, []);
  return <SafeAreaView style={[s.root, {backgroundColor: colors.navy}]}>
    <StatusBar barStyle="light-content"/>
    <View style={s.header}><Text style={s.brand}>◈ RAG Platform</Text><Text style={s.eyebrow}>MOBILE / DOCUMENTS</Text></View>
    {state.status === 'authenticated' ? <Workspace key={state.token}/> : <LoginScreen state={state}/>}
  </SafeAreaView>;
}

export default function App(): React.JSX.Element {return <SafeAreaProvider><Application/></SafeAreaProvider>;}
