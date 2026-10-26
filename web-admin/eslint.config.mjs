import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import vue from 'eslint-plugin-vue';
import globals from 'globals';
import { boundaries } from './tooling/architecture.mjs';

export default [
 { ignores: ['dist/**', 'node_modules/**', 'src/shared/infrastructure/schema.ts'] },
 js.configs.recommended,
 ...tseslint.configs.recommended,
 ...vue.configs['flat/essential'],
 { files: ['**/*.{ts,vue,mjs}'], languageOptions: { globals: { ...globals.browser, ...globals.node }, parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'] } }, rules: {
  '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' }],
 } },
 { files: ['src/**/*.{ts,vue}'], plugins: { architecture: { rules: { boundaries } } }, rules: { 'architecture/boundaries': 'error' } },
 { files: ['src/modules/*/{domain,application}/**/*.ts'], rules: { 'no-restricted-globals': ['error', 'fetch', 'window', 'document', 'localStorage', 'sessionStorage'] } },
];
