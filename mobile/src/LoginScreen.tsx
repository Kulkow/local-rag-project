import React, {useEffect, useState} from 'react';
import {KeyboardAvoidingView, ScrollView, Text, TextInput, View} from 'react-native';
import type {SessionState} from './auth/session';
import {message} from './auth/session';
import {session} from './native';
import {Button, Card, Loading, Notice, s} from './ui';

export function LoginScreen({state}: {state: SessionState}): React.JSX.Element {
  const [server, setServer] = useState(state.server);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [connected, setConnected] = useState(false);
  const [checking, setChecking] = useState(false);
  const busy = state.status === 'restoring' || checking;
  useEffect(() => {setServer(state.server);}, [state.server]);
  async function connect(): Promise<void> {
    setError(''); setChecking(true);
    try {
      setServer(await session.connect(server));
      setConnected(true);
    } catch (reason) {setError(message(reason));}
    finally {setChecking(false);}
  }
  async function signIn(): Promise<void> {
    setError('');
    try {await session.login(server, username, password);}
    catch (reason) {setError(message(reason));}
    finally {setPassword('');}
  }
  return <KeyboardAvoidingView behavior="height" style={s.root}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.content}>
    <Text style={s.title}>{connected ? 'Вход в платформу' : 'Подключение к API'}</Text>
    <Text style={s.muted}>{connected ? 'Используйте ту же учётную запись, что и в Web Admin.' : 'Подключите телефон и компьютер с сервером к одной сети Wi-Fi.'}</Text>
    {!connected ? <Card>
      <Text style={s.heading}>Сервер в локальной сети</Text>
      <Text nativeID="server-label" style={s.label}>Адрес API</Text>
      <TextInput accessibilityLabel="Адрес API" accessibilityLabelledBy="server-label" style={s.input} value={server} onChangeText={setServer} autoCapitalize="none" autoCorrect={false} keyboardType="url" editable={!busy} placeholder="http://192.168.1.20" returnKeyType="go" onSubmitEditing={() => {if (!busy && server.trim()) {void connect();}}}/>
      <Text style={s.muted}>Введите http://IP-компьютера. Порт 3000 и /api добавятся автоматически. Пример полного адреса: http://192.168.1.20:3000/api.</Text>
      <Text style={s.muted}>Используйте IP компьютера в Wi-Fi сети, а не localhost. HTTP доступен в debug-сборке; для release нужен HTTPS.</Text>
      <Notice text={error || state.error} error/>
      {busy && <Loading text={checking ? 'Проверяем соединение с API…' : 'Проверяем сохранённую сессию…'}/>}
      <Button title="Подключиться" disabled={busy || !server.trim()} onPress={() => {void connect();}}/>
    </Card> : <Card>
      <Text style={s.heading}>Учётная запись</Text>
      <Text style={s.muted}>API: {server}</Text>
      <Button title="Изменить адрес API" secondary disabled={busy} onPress={() => {setConnected(false); setPassword(''); setError('');}}/>
      <Text style={s.label}>Логин</Text>
      <TextInput accessibilityLabel="Логин" style={s.input} value={username} onChangeText={setUsername} autoCapitalize="none" autoCorrect={false} autoComplete="username" editable={!busy} maxLength={100}/>
      <Text style={s.label}>Пароль</Text>
      <TextInput accessibilityLabel="Пароль" style={s.input} value={password} onChangeText={setPassword} secureTextEntry autoComplete="current-password" editable={!busy} maxLength={128} onSubmitEditing={() => {if (!busy && username && password) {void signIn();}}}/>
      <Notice text={error || state.error} error/>
      {busy && <Loading text="Проверяем сессию…"/>}
      <Button title="Войти" disabled={busy || !server.trim() || !username.trim() || !password} onPress={() => {void signIn();}}/>
      <Button title="Проверить сохранённую сессию" secondary disabled={busy} onPress={() => {void session.restore();}}/>
    </Card>}
    <View><Text style={s.muted}>Пароль не сохраняется. JWT хранится в защищённом хранилище Android и проверяется сервером.</Text></View>
  </ScrollView></KeyboardAvoidingView>;
}
