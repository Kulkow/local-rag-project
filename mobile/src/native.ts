import {NativeModules} from 'react-native';
import {pick, keepLocalCopy, isErrorWithCode, errorCodes} from '@react-native-documents/picker';
import {launchCamera} from 'react-native-image-picker';
import * as Keychain from 'react-native-keychain';
import BlobUtil from 'react-native-blob-util';
import {Api, type BinaryUpload} from './api/client';
import {Session, type Vault} from './auth/session';
import type {LocalFile} from './api/types';
import {mimeTypes, validateFile, validateImageDimensions} from './documents/upload';

interface PrivateFiles {
  newId(): Promise<string>;
  clearPhotos(): Promise<void>;
}
const privateFiles = NativeModules.PrivateFiles as PrivateFiles;
const service = 'com.ragmobile.session';
const serverService = 'com.ragmobile.server';
const vault: Vault = {
  async read() {
    const result = await Keychain.getGenericPassword({service});
    return result ? {server: result.username, token: result.password} : null;
  },
  async write(value) {
    await Keychain.setGenericPassword(value.server, value.token, {service, accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY});
  },
  async clear() {await Keychain.resetGenericPassword({service});},
  async readServer() {
    const result = await Keychain.getGenericPassword({service: serverService});
    return result ? result.password : null;
  },
  async writeServer(server) {
    await Keychain.setGenericPassword('api-server', server, {service: serverService, accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY});
  },
};

const binary: BinaryUpload = async (url, headers, uri) => {
  const response = await BlobUtil.config({timeout: 90000, followRedirect: false})
    .fetch('POST', url, headers, BlobUtil.wrap(decodeURI(uri.replace(/^file:\/\//, ''))));
  return {status: response.info().status, data: response.data};
};
export const session = new Session(vault, (url, token, invalidate) => new Api(url, token, invalidate, binary), __DEV__);

export async function discard(file: LocalFile | null): Promise<void> {
  if (file?.uri.startsWith('file://')) {
    const path = decodeURI(file.uri.slice(7));
    if (await BlobUtil.fs.exists(path)) {await BlobUtil.fs.unlink(path);}
  }
}

export async function chooseFile(): Promise<LocalFile | null> {
  try {
    const [chosen] = await pick({type: mimeTypes, allowMultiSelection: false, allowVirtualFiles: false});
    const key = await privateFiles.newId();
    const name = chosen.name ?? 'document';
    // Validate before copying an arbitrarily large provider file into the app cache.
    const file: LocalFile = {uri: chosen.uri, name, size: chosen.size ?? 0, type: chosen.type ?? 'application/octet-stream', key};
    validateFile(file);
    const [copy] = await keepLocalCopy({destination: 'cachesDirectory', files: [{uri: chosen.uri, fileName: `upload-${key}.${name.split('.').pop()}`}]});
    if (copy.status !== 'success') {throw new Error('Не удалось прочитать файл из системного хранилища.');}
    file.uri = copy.localUri;
    // Check actual copied size instead of trusting only document-provider metadata.
    file.size = Number((await BlobUtil.fs.stat(decodeURI(file.uri.replace(/^file:\/\//, '')))).size);
    try {validateFile(file);} catch (error) {await discard(file); throw error;}
    return file;
  } catch (error) {
    if (isErrorWithCode(error) && error.code === errorCodes.OPERATION_CANCELED) {return null;}
    throw error;
  }
}

export async function takePhoto(): Promise<LocalFile | null> {
  // Uses the system camera and its temporary private file; never invokes MediaStore.
  // Android delegates capture to the camera app.
  const result = await launchCamera({mediaType: 'photo', cameraType: 'back', saveToPhotos: false, includeBase64: false, includeExtra: false, assetRepresentationMode: 'compatible', quality: 0.9, maxWidth: 1800, maxHeight: 2400});
  if (result.didCancel) {return null;}
  if (result.errorCode) {throw new Error('Камера недоступна. Проверьте наличие приложения камеры и разрешения в настройках устройства.');}
  const asset = result.assets?.[0];
  if (!asset?.uri) {throw new Error('Камера не вернула снимок.');}
  let file: LocalFile | null = null;
  try {
    const type = asset.type === 'image/jpg' ? 'image/jpeg' : asset.type;
    if (type !== 'image/jpeg' && type !== 'image/png') {throw new Error('Камера должна вернуть изображение JPEG или PNG.');}
    validateImageDimensions(asset.width, asset.height);
    const key = await privateFiles.newId();
    const name = `camera-${key}.${type === 'image/png' ? 'png' : 'jpg'}`;
    const directory = `${BlobUtil.fs.dirs.CacheDir}/rag-photos`;
    const source = decodeURI(asset.uri.replace(/^file:\/\//, ''));
    if (!asset.uri.startsWith('file://')) {throw new Error('Камера не вернула локальный файл снимка.');}
    file = {uri: `file://${directory}/${name}`, name, type, key, size: Number((await BlobUtil.fs.stat(source)).size)};
    validateFile(file);
    if (!await BlobUtil.fs.exists(directory)) {await BlobUtil.fs.mkdir(directory);}
    const target = decodeURI(file.uri.slice(7));
    const sourceSize = file.size;
    // Android resolves undefined on success despite the library's boolean typings.
    if (await BlobUtil.fs.cp(source, target) === false) {throw new Error('Не удалось сохранить временный снимок.');}
    file.size = Number((await BlobUtil.fs.stat(target)).size);
    validateFile(file);
    if (file.size !== sourceSize) {throw new Error('Не удалось сохранить временный снимок полностью. Повторите съёмку.');}
    return file;
  } catch (error) {await discard(file); throw error;}
  finally {
    // The picker file is removed once the app owns a copy, including error paths.
    await discard({uri: asset.uri} as LocalFile);
  }
}

export async function clearPhotos(): Promise<void> {await privateFiles.clearPhotos();}
