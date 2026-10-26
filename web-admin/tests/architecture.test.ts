import { ESLint } from 'eslint';
import { beforeAll, expect, it } from 'vitest';

const lint = new ESLint();
// Cold loading parsers/plugins is setup I/O; rule assertions retain the normal timeout.
beforeAll(async () => {
 await lint.lintText('export const warmup = true;', { filePath: 'src/modules/documents/domain/warmup.ts' });
}, 30000);
it.each([
 ['domain/fixture.ts', "import { ref } from 'vue'; export const state = ref(1);"],
 ['application/fixture.ts', "import { listDocuments } from '../infrastructure/api'; export const call = listDocuments;"],
 ['presentation/FixtureView.vue', '<script setup lang="ts">import { useAuth } from "../../identity/presentation/auth-store"; useAuth();</script><template><p>Test</p></template>'],
])('rejects forbidden DDD imports in %s', async (file, source) => {
 const [result] = await lint.lintText(source, { filePath: `src/modules/documents/${file}` });
 expect(result.messages.some(message => message.ruleId === 'architecture/boundaries')).toBe(true);
});
it('permits application ports/domain imports and blocks direct browser I/O', async () => {
 const filePath = 'src/modules/documents/application/fixture.ts';
 const [valid] = await lint.lintText("import { validateUpload } from '../domain/document'; export const check = validateUpload;", { filePath });
 expect(valid.errorCount).toBe(0);
 const [invalid] = await lint.lintText("export const call = () => fetch('/documents');", { filePath });
 expect(invalid.messages.some(message => message.ruleId === 'no-restricted-globals')).toBe(true);
});
