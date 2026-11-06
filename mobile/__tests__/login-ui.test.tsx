import React from 'react';
import {Text, TextInput} from 'react-native';
import ReactTestRenderer, {act} from 'react-test-renderer';
import {LoginScreen} from '../src/LoginScreen';
import type {SessionState} from '../src/auth/session';
import {session} from '../src/native';
import {Button} from '../src/ui';

jest.mock('../src/native', () => ({session: {connect: jest.fn(), login: jest.fn(), restore: jest.fn()}}));

const initial: SessionState = {status: 'anonymous', server: '', token: '', user: null, error: ''};
let renderer: ReactTestRenderer.ReactTestRenderer;

beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(session.connect).mockResolvedValue('http://192.168.1.20:3000/api');
  jest.mocked(session.login).mockResolvedValue(undefined);
});
afterEach(async () => {await act(async () => {renderer.unmount();});});

async function render(state = initial): Promise<void> {
  await act(async () => {renderer = ReactTestRenderer.create(<LoginScreen state={state}/>);});
}
function input(label: string) {return renderer.root.findAllByType(TextInput).find(node => node.props.accessibilityLabel === label)!;}
function button(title: string) {return renderer.root.findAllByType(Button).find(node => node.props.title === title)!;}
async function change(label: string, value: string): Promise<void> {
  await act(async () => {input(label).props.onChangeText(value);});
}
async function press(title: string): Promise<void> {
  await act(async () => {button(title).props.onPress();});
}
function text(): string {return renderer.root.findAllByType(Text).map(node => node.props.children).flat().join(' ');}

it('shows the API address as the only input on the first screen', async () => {
  await render();
  expect(renderer.root.findAllByType(TextInput)).toHaveLength(1);
  expect(input('Адрес API').props.value).toBe('');
  expect(input('Адрес API').props.placeholder).toBe('http://192.168.1.20');
  expect(button('Подключиться').props.disabled).toBe(true);
  expect(text()).toContain('одной сети Wi-Fi');
});

it('checks the server before revealing credentials and logs in using the normalized address', async () => {
  await render();
  await change('Адрес API', 'http://192.168.1.20');
  await press('Подключиться');
  expect(session.connect).toHaveBeenCalledWith('http://192.168.1.20');
  expect(input('Логин')).toBeDefined();
  expect(input('Адрес API')).toBeUndefined();
  await change('Логин', 'member'); await change('Пароль', 'password');
  await press('Войти');
  expect(session.login).toHaveBeenCalledWith('http://192.168.1.20:3000/api', 'member', 'password');
  expect(input('Пароль').props.value).toBe('');
});

it('keeps the address editable and credentials hidden when the API is unreachable', async () => {
  jest.mocked(session.connect).mockRejectedValue(new Error('Нет соединения с API'));
  await render(); await change('Адрес API', 'http://192.168.1.20'); await press('Подключиться');
  expect(text()).toContain('Нет соединения с API');
  expect(input('Адрес API').props.editable).toBe(true);
  expect(input('Логин')).toBeUndefined();
  expect(session.login).not.toHaveBeenCalled();
});

it('fills in an asynchronously restored address', async () => {
  await render({...initial, status: 'restoring'});
  expect(button('Подключиться').props.disabled).toBe(true);
  await act(async () => {renderer.update(<LoginScreen state={{...initial, server: 'http://192.168.1.20:3000/api'}}/>);});
  expect(input('Адрес API').props.value).toBe('http://192.168.1.20:3000/api');
});

it('allows changing the API address before login and clears the password', async () => {
  await render({...initial, server: 'http://192.168.1.20:3000/api'});
  await press('Подключиться'); await change('Пароль', 'secret'); await press('Изменить адрес API');
  expect(input('Адрес API').props.value).toBe('http://192.168.1.20:3000/api');
  await press('Подключиться');
  expect(input('Пароль').props.value).toBe('');
});

it('disables connection controls while a server check is pending', async () => {
  let finish!: (server: string) => void;
  jest.mocked(session.connect).mockImplementation(() => new Promise(resolve => {finish = resolve;}));
  await render(); await change('Адрес API', 'http://192.168.1.20'); await press('Подключиться');
  expect(button('Подключиться').props.disabled).toBe(true);
  expect(input('Адрес API').props.editable).toBe(false);
  await act(async () => {finish('http://192.168.1.20:3000/api');});
  expect(input('Логин')).toBeDefined();
});
