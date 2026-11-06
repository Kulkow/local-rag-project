import {Api, ApiError} from '../src/api/client';
import type {Document, LocalFile} from '../src/api/types';
import {MAX_BYTES, sendDraft, validateFile, validateImageDimensions, type UploadDraft} from '../src/documents/upload';

const photo: LocalFile = {uri: 'file:///cache/scan.jpg', name: 'scan.jpg', type: 'image/jpeg', size: 1024, key: 'b203c075-dc70-46fb-9f91-e99d05882b98'};
const saved: Document = {id: 'document', filename: photo.name, content_type: photo.type, family_id: 'family', owner_id: 'owner', size_bytes: photo.size, checksum: 'checksum', visibility: 'private', status: 'uploaded', error_code: null, created_at: null};

it.each([['scan.png', 'image/png'], ['scan.jpg', 'image/jpeg'], ['scan.JPEG', 'image/jpeg'], ['scan.png', 'application/octet-stream']])('accepts supported image %s', (name, type) => {
  expect(() => validateFile({...photo, name, type})).not.toThrow();
});

it.each([
  {size: 0}, {size: -1}, {size: NaN}, {size: 0.5}, {size: MAX_BYTES + 1},
  {name: '../scan.jpg'}, {name: 'scan.svg', type: 'image/svg+xml'},
  {name: 'scan.png', type: 'image/jpeg'}, {name: 'scan.jpg', type: 'text/html'},
])('rejects invalid image metadata before upload: %j', change => {
  expect(() => validateFile({...photo, ...change})).toThrow();
});

it.each([[5000, 4000], [12000, 1], [1800, 2400]])('accepts bounded dimensions %s x %s', (width, height) => {
  expect(() => validateImageDimensions(width, height)).not.toThrow();
});
it.each([[5000, 5000], [12001, 1], [0, 100], [-1, -1], [NaN, 100], [undefined, 100]])('rejects invalid dimensions %s x %s', (width, height) => {
  expect(() => validateImageDimensions(width, height)).toThrow('20 мегапикселей');
});

it('sends binary JPEG with its MIME, ACL, authentication and stable retry key', async () => {
  const binary = jest.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValue({status: 201, data: JSON.stringify(saved)});
  const api = new Api('https://example.test/api', 'jwt', jest.fn(), binary);
  await expect(api.upload(photo, 'family', 'private')).rejects.toThrow('тем же ключом');
  await expect(api.upload(photo, 'family', 'private')).resolves.toEqual(saved);
  for (const call of binary.mock.calls) {
    expect(call).toEqual(['https://example.test/api/documents?family_id=family&filename=scan.jpg&visibility=private', {'Authorization': 'Bearer jwt', 'Content-Type': 'image/jpeg', 'Idempotency-Key': photo.key}, photo.uri]);
  }
});

function fakeApi() {
  return {upload: jest.fn().mockResolvedValue(saved), formats: jest.fn().mockResolvedValue(['application/pdf', 'image/png', 'image/jpeg']), process: jest.fn().mockResolvedValue({status: 'queued'})};
}

it('retries only scheduling after an image was saved, preserving its ACL', async () => {
  const api = fakeApi();
  api.process.mockRejectedValueOnce(new Error('queue unavailable'));
  const draft: UploadDraft = {file: photo, family: 'family', visibility: 'private'};
  await expect(sendDraft(api as unknown as Api, draft, () => true)).rejects.toThrow('queue unavailable');
  expect(draft.saved).toEqual(saved);
  await expect(sendDraft(api as unknown as Api, draft, () => true)).resolves.toContain('очередь RAG');
  expect(api.upload).toHaveBeenCalledTimes(1);
  expect(api.upload).toHaveBeenCalledWith(photo, 'family', 'private');
  expect(api.process).toHaveBeenCalledTimes(2);
});

it('keeps an original saved on a server without image OCR without claiming an index', async () => {
  const api = fakeApi(); api.formats.mockResolvedValue(['application/pdf']);
  const result = await sendDraft(api as unknown as Api, {file: photo, family: 'family', visibility: 'family'}, () => true);
  expect(result).toContain('пока не индексирует');
  expect(api.process).not.toHaveBeenCalled();
});

it('does not schedule an image after the session was closed', async () => {
  const api = fakeApi();
  await sendDraft(api as unknown as Api, {file: photo, family: 'family', visibility: 'private'}, () => false);
  expect(api.formats).not.toHaveBeenCalled(); expect(api.process).not.toHaveBeenCalled();
});

it('surfaces denied uploads without requesting processing', async () => {
  const api = fakeApi(); api.upload.mockRejectedValue(new ApiError(403, 'Недостаточно прав'));
  await expect(sendDraft(api as unknown as Api, {file: photo, family: 'other-family', visibility: 'private'}, () => true)).rejects.toThrow('Недостаточно прав');
  expect(api.process).not.toHaveBeenCalled();
});
