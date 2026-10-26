import path from 'node:path';

export const boundaries = {
 meta: { type: 'problem', schema: [], messages: { boundary: '{{reason}}' } },
 create(context) {
  const filename = context.filename.replaceAll('\\', '/');
  const origin = filename.match(/\/modules\/([^/]+)\/(domain|application|infrastructure|presentation)\//);
  if (!origin) return {};
  function check(node) {
   const specifier = node.source?.value;
   if (typeof specifier !== 'string') return;
   const target = specifier.startsWith('.') ? path.resolve(path.dirname(filename), specifier).replaceAll('\\', '/') : specifier;
   const destination = target.match(/\/modules\/([^/]+)(?:\/(.*))?$/);
   const layer = origin[2];
   let reason;
   if (destination && destination[1] !== origin[1] && destination[2] && destination[2] !== 'index' && destination[2] !== 'index.ts') reason = 'Import another context through its public index.';
   if (layer === 'domain' && (!specifier.startsWith('.') || !target.includes(`/modules/${origin[1]}/domain/`))) reason = 'Domain may only import its own domain; no Vue, HTTP, DTOs or other contexts.';
   if (layer === 'application' && (!specifier.startsWith('.') || !target.includes(`/modules/${origin[1]}/`) || /\/(infrastructure|presentation)\//.test(target) || /\/index(?:\.ts)?$/.test(target))) reason = 'Application may only import its own application/domain and ports.';
   if (layer === 'infrastructure' && /\/presentation\//.test(target)) reason = 'Infrastructure cannot import presentation.';
   if (reason) context.report({ node, messageId: 'boundary', data: { reason } });
  }
  return { ImportDeclaration: check, ExportNamedDeclaration: check, ExportAllDeclaration: check, ImportExpression(node) { check({ ...node, source: node.source }); } };
 },
};
