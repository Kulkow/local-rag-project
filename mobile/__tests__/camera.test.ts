import {NativeModules} from 'react-native';
import {launchCamera} from 'react-native-image-picker';
import {pick, keepLocalCopy} from '@react-native-documents/picker';
import BlobUtil from 'react-native-blob-util';
import {chooseFile, discard, takePhoto} from '../src/native';
import {MAX_BYTES} from '../src/documents/upload';

jest.mock('react-native', () => {
  const actual = jest.requireActual('react-native');
  actual.NativeModules.PrivateFiles = {newId: jest.fn(), clearPhotos: jest.fn()};
  return actual;
});
jest.mock('react-native-image-picker', () => ({launchCamera: jest.fn()}));
jest.mock('@react-native-documents/picker', () => ({pick: jest.fn(), keepLocalCopy: jest.fn(), isErrorWithCode: () => false, errorCodes: {OPERATION_CANCELED: 'cancelled'}}));
jest.mock('react-native-keychain', () => ({ACCESSIBLE: {WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'unlocked'}}));
jest.mock('react-native-blob-util', () => ({
  fs: {dirs: {CacheDir: '/cache'}, stat: jest.fn(), exists: jest.fn(), mkdir: jest.fn(), cp: jest.fn(), unlink: jest.fn()},
}));

const key = 'b203c075-dc70-46fb-9f91-e99d05882b98';
const source = 'file:///cache/picker-photo.jpg';
const photo = {uri: source, type: 'image/jpeg', width: 1800, height: 2400, fileSize: 1};

beforeEach(() => {
  jest.resetAllMocks();
  NativeModules.PrivateFiles.newId.mockResolvedValue(key);
  jest.mocked(launchCamera).mockResolvedValue({assets: [photo]});
  jest.mocked(BlobUtil.fs.stat).mockResolvedValue({size: 1024} as Awaited<ReturnType<typeof BlobUtil.fs.stat>>);
  jest.mocked(BlobUtil.fs.exists).mockResolvedValue(true);
  jest.mocked(BlobUtil.fs.cp).mockResolvedValue(true);
});

it.each(['image/jpeg', 'image/jpg', 'image/png'])('prepares a direct %s camera upload, retains the private copy and cleans the picker file', async type => {
  jest.mocked(launchCamera).mockResolvedValue({assets: [{...photo, type}]});
  const file = await takePhoto();
  const name = `camera-${key}.${type === 'image/png' ? 'png' : 'jpg'}`;
  expect(file).toEqual({uri: `file:///cache/rag-photos/${name}`, name, type: type === 'image/jpg' ? 'image/jpeg' : type, size: 1024, key});
  expect(launchCamera).toHaveBeenCalledWith(expect.objectContaining({saveToPhotos: false, includeBase64: false, includeExtra: false, assetRepresentationMode: 'compatible', maxWidth: 1800, maxHeight: 2400}));
  expect(BlobUtil.fs.cp).toHaveBeenCalledWith('/cache/picker-photo.jpg', `/cache/rag-photos/${name}`);
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith('/cache/picker-photo.jpg');
  expect(BlobUtil.fs.unlink).not.toHaveBeenCalledWith(`/cache/rag-photos/${name}`);
});

it('treats camera cancellation as an empty selection', async () => {
  jest.mocked(launchCamera).mockResolvedValue({didCancel: true});
  await expect(takePhoto()).resolves.toBeNull();
  expect(BlobUtil.fs.cp).not.toHaveBeenCalled(); expect(BlobUtil.fs.unlink).not.toHaveBeenCalled();
});

it.each(['permission', 'camera_unavailable'] as const)('reports camera failure %s', async errorCode => {
  jest.mocked(launchCamera).mockResolvedValue({errorCode});
  await expect(takePhoto()).rejects.toThrow('Камера недоступна');
  expect(BlobUtil.fs.cp).not.toHaveBeenCalled();
});

it('does not accept a camera response without an image', async () => {
  jest.mocked(launchCamera).mockResolvedValue({});
  await expect(takePhoto()).rejects.toThrow('не вернула снимок');
});

it('cleans an oversized image using the actual file size before copying', async () => {
  jest.mocked(BlobUtil.fs.stat).mockResolvedValue({size: MAX_BYTES + 1} as Awaited<ReturnType<typeof BlobUtil.fs.stat>>);
  await expect(takePhoto()).rejects.toThrow('10 MiB');
  expect(BlobUtil.fs.cp).not.toHaveBeenCalled();
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith('/cache/picker-photo.jpg');
});

it('removes a partially copied photo after a cache failure', async () => {
  jest.mocked(BlobUtil.fs.cp).mockRejectedValue(new Error('disk full'));
  await expect(takePhoto()).rejects.toThrow('disk full');
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith(`/cache/rag-photos/camera-${key}.jpg`);
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith('/cache/picker-photo.jpg');
});

it('accepts the Android successful copy callback without a return value', async () => {
  // Android calls callback.invoke() on success, despite the Promise<boolean> declaration.
  jest.mocked(BlobUtil.fs.cp).mockResolvedValue(undefined as unknown as boolean);
  const file = await takePhoto();
  expect(file?.size).toBe(1024);
  expect(BlobUtil.fs.stat).toHaveBeenCalledWith(`/cache/rag-photos/camera-${key}.jpg`);
  expect(BlobUtil.fs.unlink).not.toHaveBeenCalledWith(`/cache/rag-photos/camera-${key}.jpg`);
});

it('rejects and cleans a truncated copy even when its size is within the upload limit', async () => {
  jest.mocked(BlobUtil.fs.stat)
    .mockResolvedValueOnce({size: 1024} as Awaited<ReturnType<typeof BlobUtil.fs.stat>>)
    .mockResolvedValueOnce({size: 512} as Awaited<ReturnType<typeof BlobUtil.fs.stat>>);
  await expect(takePhoto()).rejects.toThrow('временный снимок');
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith(`/cache/rag-photos/camera-${key}.jpg`);
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith('/cache/picker-photo.jpg');
});

it('does not return a prepared photo when the copied file cannot be read', async () => {
  jest.mocked(BlobUtil.fs.stat)
    .mockResolvedValueOnce({size: 1024} as Awaited<ReturnType<typeof BlobUtil.fs.stat>>)
    .mockRejectedValueOnce(new Error('destination missing'));
  await expect(takePhoto()).rejects.toThrow('destination missing');
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith('/cache/picker-photo.jpg');
});

it('rejects a failed copy even if the native bridge resolves false', async () => {
  jest.mocked(BlobUtil.fs.cp).mockResolvedValue(false);
  await expect(takePhoto()).rejects.toThrow('временный снимок');
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith('/cache/picker-photo.jpg');
});

it('removes the prepared image if its copied size exceeds the limit', async () => {
  jest.mocked(BlobUtil.fs.stat)
    .mockResolvedValueOnce({size: 1024} as Awaited<ReturnType<typeof BlobUtil.fs.stat>>)
    .mockResolvedValueOnce({size: MAX_BYTES + 1} as Awaited<ReturnType<typeof BlobUtil.fs.stat>>);
  await expect(takePhoto()).rejects.toThrow('10 MiB');
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith(`/cache/rag-photos/camera-${key}.jpg`);
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith('/cache/picker-photo.jpg');
});

it('rejects an image exceeding the pixel limit before copying', async () => {
  jest.mocked(launchCamera).mockResolvedValue({assets: [{...photo, width: 5000, height: 5000}]});
  await expect(takePhoto()).rejects.toThrow('20 мегапикселей');
  expect(BlobUtil.fs.cp).not.toHaveBeenCalled(); expect(BlobUtil.fs.unlink).toHaveBeenCalledWith('/cache/picker-photo.jpg');
});

it('allows PNG/JPEG in the file picker and checks the copied file size', async () => {
  jest.mocked(pick).mockResolvedValue([{uri: 'content://provider/image', name: 'scan.JPEG', type: 'image/jpeg', size: 1024, error: null, nativeType: 'image/jpeg', isVirtual: false, convertibleToMimeTypes: null, hasRequestedType: true}]);
  jest.mocked(keepLocalCopy).mockResolvedValue([{status: 'success', sourceUri: 'content://provider/image', localUri: 'file:///cache/selected.jpg'}]);
  const file = await chooseFile();
  expect(pick).toHaveBeenCalledWith(expect.objectContaining({type: expect.arrayContaining(['image/png', 'image/jpeg'])}));
  expect(file?.name).toBe('scan.JPEG'); expect(file?.type).toBe('image/jpeg');
  jest.mocked(BlobUtil.fs.stat).mockResolvedValue({size: MAX_BYTES + 1} as Awaited<ReturnType<typeof BlobUtil.fs.stat>>);
  await expect(chooseFile()).rejects.toThrow('10 MiB');
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith('/cache/selected.jpg');
});

it('discards a cancelled prepared photo', async () => {
  const file = await takePhoto();
  await discard(file);
  expect(BlobUtil.fs.unlink).toHaveBeenCalledWith(`/cache/rag-photos/camera-${key}.jpg`);
});
