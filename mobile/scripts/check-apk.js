const {execFileSync} = require('node:child_process');
const {existsSync, readFileSync} = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const properties = path.join(root, 'android/local.properties');
const sdk = process.env.ANDROID_HOME || process.env.ANDROID_SDK_ROOT ||
  (existsSync(properties) ? /^sdk\.dir=(.+)$/m.exec(readFileSync(properties, 'utf8'))?.[1].trim() : undefined);
if (!sdk) {throw new Error('Укажите ANDROID_HOME или sdk.dir в android/local.properties.');}
const apk = path.join(root, 'android/app/build/outputs/apk/debug/app-debug.apk');
if (!existsSync(apk)) {throw new Error('Сначала соберите Android APK: ./gradlew :app:assembleDebug.');}
const aapt = path.join(sdk, 'build-tools/37.0.0', process.platform === 'win32' ? 'aapt2.exe' : 'aapt2');
const manifest = execFileSync(aapt, ['dump', 'permissions', apk], {encoding: 'utf8'});
const forbidden = [
  'CAMERA', 'READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE', 'MANAGE_EXTERNAL_STORAGE',
  'READ_MEDIA_IMAGES', 'READ_MEDIA_VIDEO', 'READ_MEDIA_AUDIO', 'READ_MEDIA_VISUAL_USER_SELECTED',
];
for (const permission of forbidden) {
  if (manifest.includes(`name='android.permission.${permission}'`)) {
    throw new Error(`APK запрашивает лишнее разрешение: ${permission}`);
  }
}
if (!manifest.includes("name='android.permission.INTERNET'")) {throw new Error('APK не содержит разрешение INTERNET.');}
console.log('Android APK: камера и общее хранилище без широких разрешений; INTERNET присутствует.');
