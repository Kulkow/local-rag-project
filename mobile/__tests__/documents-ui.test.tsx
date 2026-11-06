import React from 'react';
import {Image, Text} from 'react-native';
import ReactTestRenderer, {act} from 'react-test-renderer';
import type {Document, LocalFile} from '../src/api/types';
import {UploadScreen} from '../src/documents/UploadScreen';
import {DocumentsScreen} from '../src/documents/DocumentsScreen';
import {discard, session, takePhoto} from '../src/native';
import {Button} from '../src/ui';

jest.mock('../src/native', () => {
  const api = {upload: jest.fn(), formats: jest.fn(), process: jest.fn(), documents: jest.fn(), job: jest.fn(), index: jest.fn()};
  const state = {token: 'jwt', user: {id: 'owner', role: 'member'}};
  return {session: {api: () => api, snapshot: () => state}, takePhoto: jest.fn(), chooseFile: jest.fn(), discard: jest.fn()};
});

const photo: LocalFile = {uri: 'file:///cache/rag-photos/scan.jpg', name: 'scan.jpg', type: 'image/jpeg', size: 1024, key: 'key'};
const saved: Document = {id: 'image', filename: photo.name, content_type: photo.type, family_id: 'family', owner_id: 'owner', size_bytes: photo.size, checksum: 'checksum', visibility: 'private', status: 'uploaded', error_code: null, created_at: null};
let renderer: ReactTestRenderer.ReactTestRenderer;

beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(takePhoto).mockResolvedValue(photo);
  jest.mocked(discard).mockResolvedValue(undefined);
  const api = session.api();
  jest.mocked(api.upload).mockResolvedValue(saved);
  jest.mocked(api.formats).mockResolvedValue(['application/pdf', 'image/jpeg', 'image/png']);
  jest.mocked(api.process).mockResolvedValue({document_id: 'image', status: 'queued', attempts: 0, error_code: null, created_at: null, started_at: null, finished_at: null});
  jest.mocked(api.documents).mockResolvedValue([saved]);
  jest.mocked(api.job).mockResolvedValue({document_id: 'image', status: 'failed', attempts: 1, error_code: 'invalid', created_at: null, started_at: null, finished_at: null});
  jest.mocked(api.index).mockResolvedValue({document_id: 'image', status: 'failed', embedding_model: 'synthetic', embedding_digest: 'digest', dimensions: 3, chunk_count: 0, error_code: 'invalid'});
});
afterEach(async () => {if (renderer) {await act(async () => {renderer.unmount();});}});

async function render(element: React.ReactElement): Promise<void> {
  await act(async () => {renderer = ReactTestRenderer.create(element);});
}
function buttons(title: string) {return renderer.root.findAllByType(Button).filter(button => button.props.title === title);}
async function press(title: string): Promise<void> {
  await act(async () => {buttons(title)[0].props.onPress();});
}
function text(): string {return renderer.root.findAllByType(Text).map(node => node.props.children).flat().join(' ');}

it('previews a camera image, uploads it with the selected ACL and removes it after scheduling', async () => {
  const onSaved = jest.fn();
  await render(<UploadScreen family="family" onSaved={onSaved}/>);
  await press('Для семьи');
  await press('Сфотографировать документ');
  expect(renderer.root.findByType(Image).props.source).toEqual({uri: photo.uri});
  await press('Отправить в RAG');
  expect(session.api().upload).toHaveBeenCalledWith(photo, 'family', 'family');
  expect(session.api().process).toHaveBeenCalledWith('image');
  expect(discard).toHaveBeenCalledWith(photo); expect(onSaved).toHaveBeenCalledTimes(1);
  expect(renderer.root.findAllByType(Image)).toHaveLength(0);
  expect(text()).toContain('поставлен в очередь RAG');
});

it('cancels a prepared photo without uploading it', async () => {
  await render(<UploadScreen family="family" onSaved={jest.fn()}/>);
  await press('Сфотографировать документ'); await press('Отменить выбор');
  expect(discard).toHaveBeenCalledWith(photo); expect(session.api().upload).not.toHaveBeenCalled();
  expect(buttons('Отправить в RAG')).toHaveLength(0);
});

it('preserves the original on a queue error and retries only scheduling', async () => {
  jest.mocked(session.api().process).mockRejectedValueOnce(new Error('Очередь недоступна'));
  await render(<UploadScreen family="family" onSaved={jest.fn()}/>);
  await press('Сфотографировать документ'); await press('Отправить в RAG');
  expect(text()).toContain('Оригинал уже сохранён');
  expect(discard).not.toHaveBeenCalledWith(photo);
  await press('Повторить постановку в очередь');
  expect(session.api().upload).toHaveBeenCalledTimes(1); expect(session.api().process).toHaveBeenCalledTimes(2);
});

it('keeps the form usable after camera cancellation and reports permission errors', async () => {
  jest.mocked(takePhoto).mockResolvedValueOnce(null).mockRejectedValueOnce(new Error('Камера недоступна'));
  await render(<UploadScreen family="family" onSaved={jest.fn()}/>);
  await press('Сфотографировать документ'); expect(buttons('Отправить в RAG')).toHaveLength(0);
  await press('Сфотографировать документ');
  expect(text()).toContain('Камера недоступна'); expect(session.api().upload).not.toHaveBeenCalled();
});

it('cleans a late camera result after leaving the upload screen', async () => {
  let resolvePhoto!: (file: LocalFile | null) => void;
  jest.mocked(takePhoto).mockImplementation(() => new Promise(resolve => {resolvePhoto = resolve;}));
  await render(<UploadScreen family="family" onSaved={jest.fn()}/>);
  await press('Сфотографировать документ');
  await act(async () => {renderer.unmount();});
  await act(async () => {resolvePhoto(photo);});
  expect(discard).toHaveBeenCalledWith(photo); expect(session.api().upload).not.toHaveBeenCalled();
});

it('lets the owner retry processing a failed PNG/JPEG', async () => {
  await render(<DocumentsScreen family="family" refresh={0}/>);
  await press('Поставить в очередь');
  expect(session.api().process).toHaveBeenCalledWith('image');
});

it('does not offer image processing controls for another member’s document', async () => {
  jest.mocked(session.api().documents).mockResolvedValue([{...saved, owner_id: 'someone-else', visibility: 'family'}]);
  await render(<DocumentsScreen family="family" refresh={0}/>);
  expect(buttons('Поставить в очередь')).toHaveLength(0);
});
